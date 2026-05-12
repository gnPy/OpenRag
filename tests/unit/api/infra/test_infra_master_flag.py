"""The master flag (OPENRAG_ENABLE_INFRA_ENDPOINTS) controls whether the
/api/infra/* router is mounted at all.

This test exercises the conditional include_router() in app/routes/internal.py
indirectly by replaying its logic in a tiny test app: the boolean check is
the integration contract we care about — mounted vs not mounted.
"""

import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _build_app(master_flag: bool) -> FastAPI:
    """Mirror the conditional mount logic in internal.py."""
    app = FastAPI()
    if master_flag:
        from api.infra import router as infra_router

        app.include_router(infra_router)
    return app


@pytest.mark.asyncio
async def test_router_not_mounted_when_master_off():
    app = _build_app(master_flag=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/infra/opensearch/status")
    assert r.status_code == 404, "router must be absent when master flag is off"


@pytest.mark.asyncio
async def test_router_mounted_when_master_on(monkeypatch):
    # OSS path so the test doesn't need a JWT signer.
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    # Force missing creds so the gate replies 503 (not 401); either non-404
    # proves the router IS mounted, which is the whole point of this test.
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_USER", "", raising=False
    )
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "", raising=False
    )
    monkeypatch.setattr("config.settings.OPENSEARCH_USERNAME", "", raising=False)
    monkeypatch.setattr("config.settings.OPENSEARCH_PASSWORD", "", raising=False)
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ALLOW_INSECURE", True, raising=False
    )

    import base64

    app = _build_app(master_flag=True)
    # session_manager is needed for the JWT path even though we hit OSS;
    # the dependency resolver still wires it up.
    from dependencies import get_session_manager

    app.dependency_overrides[get_session_manager] = lambda: None

    transport = httpx.ASGITransport(app=app)
    creds = "Basic " + base64.b64encode(b"any:any").decode()
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/infra/opensearch/status", headers={"Authorization": creds}
        )

    assert r.status_code != 404, "router must be present when master flag is on"
    # Specifically: with no creds configured we expect 503 (the explicit
    # "infra_admin_credentials_not_configured" path).
    assert r.status_code == 503
