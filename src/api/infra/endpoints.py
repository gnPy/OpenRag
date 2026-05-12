"""Infra-admin endpoints.

Mounted at /api/infra/* (via the Next.js proxy that strips the /api prefix,
this module exposes /infra/* to FastAPI itself — same convention used by
api/admin/rbac.py).

All handlers depend on require_infra_admin() rather than require_permission(),
bypassing DB-resident RBAC entirely so the plane is usable before any user
rows exist.

Audit rows are written with actor_user_id=None because the principal here
may not (yet) correspond to a row in the users table. The subject and source
are stored in audit_metadata under {actor, source}; the "infra." event prefix
is the discriminator.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.infra.auth import InfraAdmin, require_infra_admin
from api.infra.schemas import (
    OpenSearchStatus,
    UserCreateBody,
    UserOut,
    UserPatchBody,
    UserRolesReplaceBody,
)
from config.settings import clients
from db.models import AuditLog, User as UserRow, UserRole
from db.repositories import AuditRepo, RoleRepo, UserRepo
from db.repositories._helpers import email_lookup_hash
from dependencies import get_db_session, get_rbac_service, invalidate_user_ensured_cache
from services.opensearch_setup_status import (
    get_last_setup_at,
    get_openrag_user_role,
    is_opensearch_security_configured,
    mark_opensearch_security_configured,
)
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Mounted under /infra; the Next.js proxy strips /api before forwarding.
router = APIRouter(prefix="/infra", tags=["infra"])


# Serialize concurrent setup attempts in this process. setup_opensearch_security
# does a read-modify-write on the all_access mapping and would otherwise race.
# Multi-worker deployments are still racy at the cluster level — operators
# should treat the endpoint as "fire once."
_setup_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _user_to_out(session: AsyncSession, row: UserRow) -> UserOut:
    role_repo = RoleRepo(session)
    roles = await role_repo.list_user_roles(row.id)
    return UserOut(
        id=row.id,
        oauth_provider=row.oauth_provider,
        oauth_subject=row.oauth_subject,
        email=row.email,
        display_name=row.display_name,
        picture_url=row.picture_url,
        is_active=row.is_active,
        roles=[r.name for r in roles],
        created_at=row.created_at.isoformat() if row.created_at else None,
        last_login=row.last_login.isoformat() if row.last_login else None,
    )


def _audit_metadata(actor: InfraAdmin, extra: dict | None = None) -> dict:
    md = {"actor": actor.subject, "source": actor.source}
    if extra:
        md.update(extra)
    return md


async def _replace_user_roles(
    session: AsyncSession,
    user_id: str,
    role_names: List[str],
    actor: InfraAdmin,
) -> List[str]:
    role_repo = RoleRepo(session)

    resolved_ids: list[str] = []
    for name in role_names:
        role = await role_repo.get_by_name(name)
        if role is None:
            raise HTTPException(
                status_code=400, detail={"error": "unknown_role", "name": name}
            )
        resolved_ids.append(role.id)

    current_roles = await role_repo.list_user_roles(user_id)
    current_admin = any(r.name == "admin" for r in current_roles)
    target_admin = "admin" in role_names

    # Last-admin guard. If the user currently holds admin and the new role
    # set doesn't include it, refuse when they're the only one left.
    if current_admin and not target_admin:
        if await role_repo.count_admins() <= 1:
            raise HTTPException(
                status_code=400, detail={"error": "cannot_remove_last_admin"}
            )

    # Drop existing UserRole rows, then re-assign. Done in one transaction
    # so the role set is never partially applied.
    await session.execute(
        UserRole.__table__.delete().where(UserRole.user_id == user_id)
    )
    for rid in resolved_ids:
        await role_repo.assign_role(user_id, rid, granted_by=actor.subject)
    return role_names


# ---------------------------------------------------------------------------
# OpenSearch status + setup
# ---------------------------------------------------------------------------


@router.get("/opensearch/status", response_model=OpenSearchStatus)
async def opensearch_status(
    actor: InfraAdmin = Depends(require_infra_admin()),
) -> OpenSearchStatus:
    """Report the OpenSearch security setup state.

    Always returns HTTP 200 — this endpoint is informational, not a gate.
    Frontend should poll and surface a banner when status != "healthy".
    """
    configured_in_db = await is_opensearch_security_configured()
    last_setup = await get_last_setup_at()

    role_present = False
    live_error: str | None = None
    try:
        body = await get_openrag_user_role(clients.opensearch)
        role_present = body is not None
    except Exception as exc:  # noqa: BLE001
        live_error = str(exc)

    drift = configured_in_db and not role_present and live_error is None

    if live_error:
        status = "degraded"
        message = f"OpenSearch unreachable: {live_error}"
    elif drift:
        status = "degraded"
        message = (
            "DB-recorded setup but the openrag_user_role is missing in OpenSearch. "
            "Run POST /api/infra/opensearch/setup to repair."
        )
    elif not configured_in_db and not role_present:
        status = "unconfigured"
        message = (
            "OpenSearch security has not been configured. "
            "Run POST /api/infra/opensearch/setup."
        )
    elif not configured_in_db and role_present:
        # Role exists (possibly applied by a prior install or out-of-band)
        # but the DB row was never written. Treat as healthy; the setup
        # endpoint will record the row on next run.
        status = "healthy"
        message = (
            "OpenSearch security is configured (DB status row absent). "
            "POST /api/infra/opensearch/setup to record the state."
        )
    else:
        status = "healthy"
        message = "OpenSearch security configured"

    return OpenSearchStatus(
        status=status,
        configured=configured_in_db,
        last_setup_at=last_setup.isoformat() if last_setup else None,
        drift=drift,
        message=message,
    )


@router.post("/opensearch/setup", response_model=OpenSearchStatus)
async def opensearch_setup(
    request: Request,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> OpenSearchStatus:
    """Run OpenSearch security setup. Idempotent — also handles DLS updates.

    Always reads the YAML config and PUTs to OpenSearch, then refreshes the
    migration_status row. Concurrent calls in the same process serialize on
    an asyncio.Lock to avoid the all_access read-modify-write race.
    """
    from utils.opensearch_utils import setup_opensearch_security

    async with _setup_lock:
        try:
            await setup_opensearch_security(clients.opensearch)
        except Exception as exc:  # noqa: BLE001
            logger.error("infra.opensearch.setup failed", error=str(exc))
            await AuditRepo(session).write(
                event="infra.opensearch.setup.failed",
                actor_user_id=None,
                target_type="opensearch",
                target_id="security",
                audit_metadata=_audit_metadata(actor, {"error": str(exc)}),
                ip=request.client.host if request.client else None,
            )
            await session.commit()
            raise HTTPException(
                status_code=500,
                detail={"error": "opensearch_setup_failed", "message": str(exc)},
            )

        await mark_opensearch_security_configured(notes=f"triggered_by={actor.source}")
        await AuditRepo(session).write(
            event="infra.opensearch.setup",
            actor_user_id=None,
            target_type="opensearch",
            target_id="security",
            audit_metadata=_audit_metadata(actor),
            ip=request.client.host if request.client else None,
        )
        await session.commit()

    return await opensearch_status(actor=actor)


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------


@router.get("/users", response_model=List[UserOut])
async def list_users(
    limit: int = 100,
    offset: int = 0,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> List[UserOut]:
    rows = await UserRepo(session).list_all(limit=limit, offset=offset)
    return [await _user_to_out(session, r) for r in rows]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> UserOut:
    row = await UserRepo(session).get_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "user_not_found"})
    return await _user_to_out(session, row)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateBody,
    request: Request,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> UserOut:
    """Create a user explicitly. The bootstrap path now that
    OPENRAG_AUTO_FIRST_ADMIN can disable the implicit first-user-admin rule.

    Accepts optional oauth_provider/oauth_subject so an operator can
    pre-register a user matching the JWT subject the IdP will issue later.
    Otherwise we synthesize provider="infra_provisioned" + subject=uuid.
    """
    if not body.email:
        raise HTTPException(status_code=400, detail={"error": "email_required"})

    user_repo = UserRepo(session)
    if await user_repo.get_by_email(body.email):
        raise HTTPException(status_code=409, detail={"error": "email_exists"})

    provider = body.oauth_provider or "infra_provisioned"
    subject = body.oauth_subject or str(uuid.uuid4())

    if await user_repo.get_by_oauth(provider, subject):
        raise HTTPException(status_code=409, detail={"error": "oauth_identity_exists"})

    user_id = subject
    row = UserRow(
        id=user_id,
        oauth_provider=provider,
        oauth_subject=subject,
        email=body.email,
        email_lookup_hash=email_lookup_hash(body.email),
        display_name=body.display_name,
    )
    await user_repo.add(row)

    assigned_roles: list[str] = []
    if body.roles:
        assigned_roles = await _replace_user_roles(session, row.id, body.roles, actor)

    await AuditRepo(session).write(
        event="infra.user.created",
        actor_user_id=None,
        target_type="user",
        target_id=row.id,
        audit_metadata=_audit_metadata(
            actor, {"email": body.email, "roles": assigned_roles}
        ),
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate(row.id)
    return await _user_to_out(session, row)


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: str,
    body: UserPatchBody,
    request: Request,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> UserOut:
    user_repo = UserRepo(session)
    role_repo = RoleRepo(session)
    row = await user_repo.get_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "user_not_found"})

    changed: dict = {}

    if body.is_active is False and row.is_active:
        current_roles = await role_repo.list_user_roles(user_id)
        if any(r.name == "admin" for r in current_roles):
            if await role_repo.count_admins() <= 1:
                raise HTTPException(
                    status_code=400, detail={"error": "cannot_deactivate_last_admin"}
                )

    if body.is_active is not None and body.is_active != row.is_active:
        row.is_active = body.is_active
        changed["is_active"] = body.is_active

    if body.display_name is not None and body.display_name != row.display_name:
        row.display_name = body.display_name
        changed["display_name"] = body.display_name

    if body.roles is not None:
        applied = await _replace_user_roles(session, row.id, body.roles, actor)
        changed["roles"] = applied

    if changed:
        session.add(row)
        await AuditRepo(session).write(
            event="infra.user.updated",
            actor_user_id=None,
            target_type="user",
            target_id=row.id,
            audit_metadata=_audit_metadata(actor, {"changes": changed}),
            ip=request.client.host if request.client else None,
        )
        await session.commit()
        rbac.invalidate(row.id)
        invalidate_user_ensured_cache(row.oauth_provider, row.oauth_subject)

    return await _user_to_out(session, row)


@router.put("/users/{user_id}/roles", response_model=UserOut)
async def replace_user_roles(
    user_id: str,
    body: UserRolesReplaceBody,
    request: Request,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
) -> UserOut:
    """Replace the user's full role set in a single call.

    Different shape from /api/admin's per-role POST/DELETE pair — convenient
    for operators scripting bulk changes.
    """
    user_repo = UserRepo(session)
    row = await user_repo.get_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "user_not_found"})

    applied = await _replace_user_roles(session, row.id, body.roles, actor)

    await AuditRepo(session).write(
        event="infra.user.roles_replaced",
        actor_user_id=None,
        target_type="user",
        target_id=row.id,
        audit_metadata=_audit_metadata(actor, {"roles": applied}),
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate(row.id)
    return await _user_to_out(session, row)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    actor: InfraAdmin = Depends(require_infra_admin()),
    session: AsyncSession = Depends(get_db_session),
    rbac=Depends(get_rbac_service),
):
    user_repo = UserRepo(session)
    role_repo = RoleRepo(session)
    row = await user_repo.get_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "user_not_found"})

    roles = await role_repo.list_user_roles(user_id)
    if any(r.name == "admin" for r in roles):
        if await role_repo.count_admins() <= 1:
            raise HTTPException(
                status_code=400, detail={"error": "cannot_delete_last_admin"}
            )

    deleted_provider = row.oauth_provider
    deleted_subject = row.oauth_subject

    # Null out any historical audit_log rows that reference this user so
    # the delete event we write below survives the FK cascade. (The 0005
    # migration sets ON DELETE SET NULL but this is belt-and-suspenders
    # for deployments that haven't applied it.)
    await session.execute(
        update(AuditLog)
        .where(AuditLog.actor_user_id == user_id)
        .values(actor_user_id=None)
    )
    await session.execute(
        UserRole.__table__.delete().where(UserRole.user_id == user_id)
    )
    from db.models import UserPreferences

    await session.execute(
        UserPreferences.__table__.delete().where(UserPreferences.user_id == user_id)
    )
    await session.delete(row)

    await AuditRepo(session).write(
        event="infra.user.deleted",
        actor_user_id=None,
        target_type="user",
        target_id=user_id,
        audit_metadata=_audit_metadata(actor),
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    rbac.invalidate(user_id)
    invalidate_user_ensured_cache(deleted_provider, deleted_subject)
    return {"success": True}
