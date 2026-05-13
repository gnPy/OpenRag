"""GET /api/infra/opensearch/status covers the four state branches:

  * unconfigured - no DB row, no live role
  * healthy      - DB row + live role
  * drift        - DB row but no live role
  * degraded     - OpenSearch unreachable / transport error

Uses real OSS basic-auth on the wire so the dispatch path is exercised
end-to-end. Live OpenSearch is mocked at clients.opensearch.
"""

import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db.models  # noqa: E402,F401
from db.models import MigrationStatus  # noqa: E402
from dependencies import get_db_session, get_session_manager  # noqa: E402


_BASIC = "Basic " + base64.b64encode(b"ops:s3cret").decode()


@pytest_asyncio.fixture
async def setup(monkeypatch):
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

    # opensearch_setup_status reads via db.engine.SessionLocal.
    import db.engine as engine_mod

    monkeypatch.setattr(engine_mod, "_engine", engine, raising=False)
    monkeypatch.setattr(engine_mod, "SessionLocal", SessionLocal, raising=False)

    fake_os = MagicMock()
    fake_os.transport.perform_request = AsyncMock()
    import config.settings as settings_mod

    monkeypatch.setattr(settings_mod.clients, "opensearch", fake_os, raising=False)

    from api.infra import endpoints as infra_endpoints

    app = FastAPI()
    app.include_router(infra_endpoints.router)

    async def _db_session():
        async with SessionLocal() as s:
            yield s

    app.dependency_overrides[get_db_session] = _db_session
    # session_manager isn't actually used in OSS mode, but we need an
    # override so FastAPI's Depends resolution doesn't try to load it
    # from request.app.state.services (which we haven't populated).
    app.dependency_overrides[get_session_manager] = lambda: None

    yield app, SessionLocal, fake_os
    await engine.dispose()


@pytest.mark.asyncio
async def test_unconfigured_when_db_empty_and_role_missing(setup):
    app, _, fake_os = setup
    fake_os.transport.perform_request.side_effect = Exception("404 not_found")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/infra/opensearch/status", headers={"Authorization": _BASIC})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unconfigured"
    assert body["configured"] is False
    assert body["drift"] is False
    assert body["last_setup_at"] is None


@pytest.mark.asyncio
async def test_healthy_when_db_row_and_role_present(setup):
    app, SessionLocal, fake_os = setup
    fake_os.transport.perform_request.return_value = {
        "openrag_user_role": {"index_permissions": []}
    }

    async with SessionLocal() as s:
        s.add(MigrationStatus(name="opensearch_security_v1", notes="test"))
        await s.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/infra/opensearch/status", headers={"Authorization": _BASIC})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    assert body["configured"] is True
    assert body["drift"] is False
    assert body["last_setup_at"] is not None


@pytest.mark.asyncio
async def test_drift_when_db_says_yes_but_role_missing(setup):
    app, SessionLocal, fake_os = setup
    fake_os.transport.perform_request.side_effect = Exception("404 not_found")

    async with SessionLocal() as s:
        s.add(MigrationStatus(name="opensearch_security_v1", notes="test"))
        await s.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/infra/opensearch/status", headers={"Authorization": _BASIC})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "degraded"
    assert body["drift"] is True
    assert "missing" in body["message"].lower()


@pytest.mark.asyncio
async def test_degraded_when_opensearch_unreachable(setup):
    app, _, fake_os = setup
    fake_os.transport.perform_request.side_effect = Exception("ConnectionError: cluster down")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/infra/opensearch/status", headers={"Authorization": _BASIC})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "degraded"
    assert body["drift"] is False
    assert "unreachable" in body["message"].lower()
