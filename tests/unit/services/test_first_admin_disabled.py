"""Master flag + OPENRAG_AUTO_FIRST_ADMIN gating of _assign_bootstrap_or_default.

Behaviour matrix:

  * master OFF (any AUTO value) -> first user gets admin (today's behaviour).
  * master ON  + AUTO_FIRST_ADMIN=true  -> first user gets admin.
  * master ON  + AUTO_FIRST_ADMIN=false -> first user gets default role.
"""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.repositories import RoleRepo  # noqa: E402
from db.seed import seed_roles_and_permissions  # noqa: E402
from services.user_service import ensure_user_row  # noqa: E402
from session_manager import User  # noqa: E402


@pytest_asyncio.fixture
async def session():
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
        yield s
    await engine.dispose()


def _user(uid: str, email: str) -> User:
    return User(user_id=uid, email=email, name=uid, provider="google")


@pytest.mark.asyncio
async def test_master_off_preserves_first_user_admin(session, monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_ENABLE_INFRA_ENDPOINTS", False, raising=False)
    # AUTO flag is false but irrelevant when master is off.
    monkeypatch.setattr("config.settings.OPENRAG_AUTO_FIRST_ADMIN", False, raising=False)
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")

    row = await ensure_user_row(session, _user("uid-1", "first@example.com"))
    await session.commit()

    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"admin"}, "master flag off must preserve today's first-user-admin behaviour"


@pytest.mark.asyncio
async def test_master_on_auto_true_still_promotes(session, monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_ENABLE_INFRA_ENDPOINTS", True, raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_AUTO_FIRST_ADMIN", True, raising=False)
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")

    row = await ensure_user_row(session, _user("uid-2", "first@example.com"))
    await session.commit()

    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"admin"}


@pytest.mark.asyncio
async def test_master_on_auto_false_skips_admin(session, monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_ENABLE_INFRA_ENDPOINTS", True, raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_AUTO_FIRST_ADMIN", False, raising=False)
    monkeypatch.setenv("OPENRAG_DEFAULT_ROLE", "user")

    row = await ensure_user_row(session, _user("uid-3", "first@example.com"))
    await session.commit()

    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"user"}, "infra endpoints will register the admin explicitly"


@pytest.mark.asyncio
async def test_anonymous_still_gets_noauth_role_under_skip(session, monkeypatch):
    """The skip-bootstrap branch falls through to the default-role path,
    which still honours OPENRAG_NOAUTH_ROLE for the synthetic anonymous user.
    """
    monkeypatch.setattr("config.settings.OPENRAG_ENABLE_INFRA_ENDPOINTS", True, raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_AUTO_FIRST_ADMIN", False, raising=False)
    monkeypatch.setenv("OPENRAG_NOAUTH_ROLE", "viewer")

    row = await ensure_user_row(session, _user("anonymous", "anon@example.com"))
    await session.commit()

    roles = {r.name for r in await RoleRepo(session).list_user_roles(row.id)}
    assert roles == {"viewer"}
