"""User lifecycle service.

Single chokepoint for "given an authenticated principal, make sure a row
exists in the users table and assign a default role." Race-safe via a
serialized SQL transaction. Idempotent.

ensure_user_row is intentionally synchronous on its critical section so
parallel sign-ins from the same provider/subject collapse into a single
INSERT (the unique constraint on (oauth_provider, oauth_subject) does the
heavy lifting; we catch IntegrityError and re-fetch).
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User as UserRow
from db.repositories import AuditRepo, RoleRepo, UserRepo
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _default_new_user_role() -> str:
    return os.getenv("OPENRAG_DEFAULT_ROLE", "user")


def _noauth_role() -> str:
    return os.getenv("OPENRAG_NOAUTH_ROLE", "admin")


async def ensure_user_row(
    session: AsyncSession,
    user: User,
    jwt_roles: list[str] | None = None,
) -> UserRow:
    """Ensure the authenticated `user` exists in the SQL `users` table.

    Role assignment:

    * ``jwt_roles is None`` — legacy behavior. First-ever user gets ``admin``;
      subsequent users get ``OPENRAG_DEFAULT_ROLE`` (default ``user``); the
      synthetic anonymous user gets ``OPENRAG_NOAUTH_ROLE`` (default ``admin``).
    * ``jwt_roles is not None`` — JWT is authoritative. The user's DB role
      assignments are reconciled against the list every call; the bootstrap-
      admin shortcut is skipped (the first admin must come from the JWT).

    Returns the persisted UserRow. Caller commits.
    """

    if not user or not user.user_id:
        raise ValueError("ensure_user_row requires a user with a user_id")

    user_repo = UserRepo(session)
    role_repo = RoleRepo(session)
    audit_repo = AuditRepo(session)

    provider = user.provider or "unknown"
    subject = user.user_id

    existing = await user_repo.get_by_oauth(provider, subject)
    if existing:
        await user_repo.update_last_login(existing.id)
        if jwt_roles is not None:
            await _sync_jwt_roles(role_repo, audit_repo, existing.id, jwt_roles)
        return existing

    # Possible legacy row (oauth_provider='legacy', oauth_subject==user_id)
    legacy = await user_repo.get_by_oauth("legacy", subject)
    if legacy is None and user.email:
        # Or a legacy row matched by email_lookup_hash from a prior sign-in
        by_email = await user_repo.get_by_email(user.email)
        if by_email and by_email.oauth_provider == "legacy":
            legacy = by_email

    if legacy is not None:
        merged = await user_repo.merge_legacy(
            legacy,
            real_provider=provider,
            real_subject=subject,
            email=user.email,
            display_name=user.name,
            picture_url=user.picture,
        )
        await audit_repo.write(
            event="user.merged_legacy",
            actor_user_id=merged.id,
            target_type="user",
            target_id=merged.id,
            audit_metadata={"provider": provider},
        )
        if jwt_roles is not None:
            await _sync_jwt_roles(role_repo, audit_repo, merged.id, jwt_roles)
        else:
            # Legacy rows had no role assignment — give them the default.
            await _assign_bootstrap_or_default(session, role_repo, audit_repo, merged.id)
        return merged

    # Brand-new row.
    # We use the OAuth subject (== user.user_id) as the DB primary key so
    # the SQL `users.id` lines up with the JWT subject and with the
    # user_id strings already used by connections.json / conversations.json.
    # If a different provider ever sign-ins with the same subject string we
    # fall back to a UUID — extremely rare in practice.
    new_id = subject if subject else str(uuid.uuid4())
    row = UserRow(
        id=new_id,
        oauth_provider=provider,
        oauth_subject=subject,
        email=user.email,
        display_name=user.name,
        picture_url=user.picture,
    )
    try:
        await user_repo.add(row)
    except IntegrityError:
        # The collision could be on any of the three unique constraints:
        # (oauth_provider, oauth_subject), email_lookup_hash, or id (PK).
        await session.rollback()

        # Case 1: (oauth_provider, oauth_subject) race — a peer process beat us
        # to the INSERT for this exact identity.
        existing = await user_repo.get_by_oauth(provider, subject)
        if existing:
            await user_repo.update_last_login(existing.id)
            return existing

        # Case 2: email_lookup_hash race — same email already inserted (most
        # common for the synthetic anonymous@localhost user in no-auth mode when
        # two concurrent requests both observe an empty table). Look up by email;
        # if the row's (provider, subject) matches ours it's a concurrent insert
        # of the same identity and we can safely return it.
        if user.email:
            by_email = await user_repo.get_by_email(user.email)
            if (
                by_email
                and by_email.oauth_provider == provider
                and by_email.oauth_subject == subject
            ):
                await user_repo.update_last_login(by_email.id)
                return by_email

        # Case 3: PK collision across providers (a different identity already
        # occupies id=subject). Retry with a UUID; (provider, subject) differs
        # from the conflicting row so the INSERT will succeed.
        # If the collision was on email_lookup_hash for a genuinely different
        # identity (two real users sharing an email) this insert also fails —
        # that propagates to the caller as intended.
        new_id = str(uuid.uuid4())
        row = UserRow(
            id=new_id,
            oauth_provider=provider,
            oauth_subject=subject,
            email=user.email,
            display_name=user.name,
            picture_url=user.picture,
        )
        await user_repo.add(row)

    if jwt_roles is not None:
        await _sync_jwt_roles(role_repo, audit_repo, row.id, jwt_roles)
    else:
        await _assign_bootstrap_or_default(session, role_repo, audit_repo, row.id)
    return row


async def sync_jwt_roles(session: AsyncSession, user_id: str, jwt_roles: list[str]) -> None:
    """Public entry point for re-syncing a user's roles from JWT claims.

    Used by the ensure-user cache fast path in ``dependencies.py``: when the
    user row is already in the per-process cache we skip ``ensure_user_row``
    but still need to reconcile roles each request. Caller commits.
    """
    role_repo = RoleRepo(session)
    audit_repo = AuditRepo(session)
    await _sync_jwt_roles(role_repo, audit_repo, user_id, jwt_roles)


async def _sync_jwt_roles(
    role_repo: RoleRepo,
    audit_repo: AuditRepo,
    user_id: str,
    jwt_roles: list[str],
) -> None:
    """Reconcile ``user_roles`` for ``user_id`` against the JWT-derived list.

    JWT is authoritative: roles missing from the JWT are revoked, new ones
    are added. Role names not present in the ``roles`` table are skipped
    (logged at WARNING). A single ``user.roles_synced`` audit row is written
    when the role set changes.
    """
    current = await role_repo.list_user_roles(user_id)
    current_by_name = {r.name: r for r in current}

    desired: dict[str, str] = {}  # name -> role_id
    for name in jwt_roles:
        if name in desired:
            continue
        role = await role_repo.get_by_name(name)
        if role is None:
            logger.warning(
                "JWT role not present in roles table; skipping",
                role=name,
                user_id=user_id,
            )
            continue
        desired[name] = role.id

    added: list[str] = []
    removed: list[str] = []

    for name, role_id in desired.items():
        if name not in current_by_name:
            await role_repo.assign_role(user_id, role_id)
            added.append(name)

    for name, role in current_by_name.items():
        if name not in desired:
            await role_repo.revoke_role(user_id, role.id)
            removed.append(name)

    if added or removed:
        await audit_repo.write(
            event="user.roles_synced",
            actor_user_id=user_id,
            target_type="user",
            target_id=user_id,
            audit_metadata={"added": added, "removed": removed, "source": "jwt"},
        )


async def _assign_bootstrap_or_default(
    session: AsyncSession,
    role_repo: RoleRepo,
    audit_repo: AuditRepo,
    user_id: str,
) -> None:
    admin_count = await role_repo.count_admins()
    if admin_count == 0:
        admin_role = await role_repo.get_by_name("admin")
        if admin_role is None:
            logger.warning("admin role not seeded; skipping bootstrap assignment")
            return
        await role_repo.assign_role(user_id, admin_role.id)
        await session.flush()

        # Race-detect: a concurrent caller may have *also* observed
        # admin_count == 0 and granted admin to a different user. Both
        # writes succeeded (no DB-level mutex). Resolve by lexicographic
        # tie-break — only the smallest user_id keeps admin; others
        # demote and fall through to the default-role path. This is
        # portable across SQLite and Postgres without advisory locks.
        admins = await role_repo.list_admin_user_ids()
        if len(admins) > 1 and min(admins) != user_id:
            await role_repo.revoke_role(user_id, admin_role.id)
            await session.flush()
            logger.warning(
                "bootstrap race detected; demoted to default role",
                user_id=user_id,
                winner=min(admins),
            )
            # Fall through to the default-role assignment block below.
        else:
            await audit_repo.write(
                event="user.bootstrap_admin",
                actor_user_id=user_id,
                target_type="user",
                target_id=user_id,
            )
            return

    # No-auth synthetic user -> configurable role
    if user_id == "anonymous":
        target_name = _noauth_role()
    else:
        target_name = _default_new_user_role()

    role = await role_repo.get_by_name(target_name)
    if role is None:
        logger.warning(
            "default role not found, skipping role assignment",
            role_name=target_name,
            user_id=user_id,
        )
        return
    await role_repo.assign_role(user_id, role.id)
    await audit_repo.write(
        event="user.created",
        actor_user_id=user_id,
        target_type="user",
        target_id=user_id,
        audit_metadata={"role": target_name},
    )


async def get_effective_provider_keys(session: AsyncSession, user_id: str) -> dict:
    """Phase-4 helper. Returns a dict of provider -> overrides for this user.

    Phase 1 ships a no-op shape so call sites can be wired without behavior
    change. Phase 4 will fill it in by reading user_preferences.provider_overrides
    and overlaying onto config_manager's workspace defaults.
    """
    return {}


async def get_effective_agent_config(session: AsyncSession, user_id: str) -> dict | None:
    """Phase-4 helper. Returns the per-user agent config overlay (or None)."""
    return None
