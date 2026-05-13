"""POST /api/infra/users — creates a user with optional roles, audits, and
rejects unknown role names. Uses real OSS basic-auth on the wire.
"""

import base64
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.models import AuditLog  # noqa: E402
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from dependencies import get_db_session, get_rbac_service, get_session_manager  # noqa: E402
from services.rbac_service import RBACService  # noqa: E402


_BASIC = "Basic " + base64.b64encode(b"ops:s3cret").decode()


@pytest_asyncio.fixture
async def app(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_USER", "ops", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "s3cret", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ALLOW_INSECURE", True, raising=False)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        await seed_roles_and_permissions(s)
        await s.commit()

    rbac = RBACService(SessionLocal)

    from api.infra import endpoints as infra_endpoints

    fastapi_app = FastAPI()
    fastapi_app.include_router(infra_endpoints.router)

    async def _db_session():
        async with SessionLocal() as s:
            yield s

    fastapi_app.dependency_overrides[get_db_session] = _db_session
    fastapi_app.dependency_overrides[get_rbac_service] = lambda: rbac
    fastapi_app.dependency_overrides[get_session_manager] = lambda: None

    yield fastapi_app, SessionLocal
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_with_admin_role(app):
    fastapi_app, SessionLocal = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/infra/users",
            json={
                "email": "first.admin@example.com",
                "display_name": "First Admin",
                "roles": ["admin"],
            },
            headers={"Authorization": _BASIC},
        )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "first.admin@example.com"
    assert body["display_name"] == "First Admin"
    assert body["roles"] == ["admin"]

    # Audit row is written without actor_user_id, with metadata carrying
    # the infra principal and the roles requested.
    async with SessionLocal() as s:
        rows = (
            (await s.execute(select(AuditLog).where(AuditLog.event == "infra.user.created")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].actor_user_id is None
        assert rows[0].audit_metadata["actor"] == "ops"
        assert rows[0].audit_metadata["source"] == "basic"
        assert rows[0].audit_metadata["roles"] == ["admin"]


@pytest.mark.asyncio
async def test_unknown_role_rejected_with_400(app):
    fastapi_app, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/infra/users",
            json={"email": "x@example.com", "roles": ["not-a-role"]},
            headers={"Authorization": _BASIC},
        )

    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["error"] == "unknown_role"
    assert body["detail"]["name"] == "not-a-role"


@pytest.mark.asyncio
async def test_duplicate_email_rejected_with_409(app):
    fastapi_app, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r1 = await c.post(
            "/infra/users",
            json={"email": "dup@example.com", "roles": []},
            headers={"Authorization": _BASIC},
        )
        assert r1.status_code == 201

        r2 = await c.post(
            "/infra/users",
            json={"email": "dup@example.com", "roles": []},
            headers={"Authorization": _BASIC},
        )

    assert r2.status_code == 409
    assert r2.json()["detail"]["error"] == "email_exists"


@pytest.mark.asyncio
async def test_replace_roles_endpoint(app):
    fastapi_app, SessionLocal = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        created = await c.post(
            "/infra/users",
            json={"email": "swap@example.com", "roles": ["user"]},
            headers={"Authorization": _BASIC},
        )
        assert created.status_code == 201
        user_id = created.json()["id"]

        replaced = await c.put(
            f"/infra/users/{user_id}/roles",
            json={"roles": ["developer", "viewer"]},
            headers={"Authorization": _BASIC},
        )

    assert replaced.status_code == 200, replaced.text
    assert set(replaced.json()["roles"]) == {"developer", "viewer"}

    async with SessionLocal() as s:
        roles = await RoleRepo(s).list_user_roles(user_id)
        assert {r.name for r in roles} == {"developer", "viewer"}


@pytest.mark.asyncio
async def test_cannot_remove_last_admin_via_replace(app):
    fastapi_app, _ = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        admin = await c.post(
            "/infra/users",
            json={"email": "only-admin@example.com", "roles": ["admin"]},
            headers={"Authorization": _BASIC},
        )
        assert admin.status_code == 201
        admin_id = admin.json()["id"]

        # Try to demote the only admin
        r = await c.put(
            f"/infra/users/{admin_id}/roles",
            json={"roles": ["user"]},
            headers={"Authorization": _BASIC},
        )

    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "cannot_remove_last_admin"
