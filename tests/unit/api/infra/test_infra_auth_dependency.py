"""require_infra_admin dispatches on run mode.

Covers both gate paths:
  * SaaS / on_prem: JWT decoded via session_manager.verify_token, claim
    contains an accepted value -> 200.
  * OSS: HTTP Basic compared against OPENRAG_INFRA_ADMIN_USER /
    OPENRAG_INFRA_ADMIN_PASSWORD (with fallback to OPENSEARCH_*).
"""

import base64
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.infra.auth import InfraAdmin, _flatten_claim, require_infra_admin  # noqa: E402
from dependencies import get_session_manager  # noqa: E402


class _StubSessionManager:
    """Tiny stand-in for session_manager that returns a preset payload."""

    def __init__(self, payload: dict | None):
        self.payload = payload

    def verify_token(self, token: str):  # noqa: ARG002 - signature parity
        return self.payload


def _basic_header(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _build_app(payload: dict | None = None) -> FastAPI:
    app = FastAPI()

    def _stub() -> _StubSessionManager:
        return _StubSessionManager(payload)

    app.dependency_overrides[get_session_manager] = _stub

    @app.get("/echo")
    async def echo(actor: InfraAdmin = Depends(require_infra_admin())):
        return {"subject": actor.subject, "source": actor.source}

    return app


# ---------------------------------------------------------------------------
# _flatten_claim
# ---------------------------------------------------------------------------


def test_flatten_claim_handles_string():
    assert _flatten_claim("Manager") == {"Manager"}


def test_flatten_claim_handles_list_of_strings():
    assert _flatten_claim(["Manager", "User"]) == {"Manager", "User"}


def test_flatten_claim_handles_list_of_dicts():
    assert _flatten_claim([{"name": "Manager"}, {"name": "User"}]) == {
        "Manager",
        "User",
    }


def test_flatten_claim_handles_dict_with_name():
    assert _flatten_claim({"name": "Manager"}) == {"Manager"}


def test_flatten_claim_returns_empty_for_unknown_shape():
    assert _flatten_claim(42) == set()
    assert _flatten_claim(None) == set()


# ---------------------------------------------------------------------------
# OSS basic-auth path
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def oss_app(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_USER", "ops", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "s3cret", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ALLOW_INSECURE", True, raising=False)
    return _build_app()


@pytest.mark.asyncio
async def test_oss_basic_auth_happy_path(oss_app):
    transport = httpx.ASGITransport(app=oss_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": _basic_header("ops", "s3cret")})
    assert r.status_code == 200, r.text
    assert r.json() == {"subject": "ops", "source": "basic"}


@pytest.mark.asyncio
async def test_oss_basic_auth_wrong_password(oss_app):
    transport = httpx.ASGITransport(app=oss_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": _basic_header("ops", "wrong")})
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").startswith("Basic")


@pytest.mark.asyncio
async def test_oss_missing_authorization_header(oss_app):
    transport = httpx.ASGITransport(app=oss_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_oss_falls_back_to_opensearch_credentials(monkeypatch):
    """When dedicated infra creds are unset, OPENSEARCH_USERNAME/PASSWORD
    are used."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_USER", "", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ALLOW_INSECURE", True, raising=False)
    monkeypatch.setattr("config.settings.OPENSEARCH_USERNAME", "admin", raising=False)
    monkeypatch.setattr("config.settings.OPENSEARCH_PASSWORD", "fallback-pw", raising=False)

    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/echo",
            headers={"Authorization": _basic_header("admin", "fallback-pw")},
        )
    assert r.status_code == 200
    assert r.json()["source"] == "basic"


@pytest.mark.asyncio
async def test_oss_503_when_no_credentials_configured(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_USER", "", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "", raising=False)
    monkeypatch.setattr("config.settings.OPENSEARCH_USERNAME", "", raising=False)
    monkeypatch.setattr("config.settings.OPENSEARCH_PASSWORD", "", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ALLOW_INSECURE", True, raising=False)

    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": _basic_header("anyone", "anything")})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_oss_refuses_plain_http_without_allow_flag(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_USER", "ops", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "s3cret", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ALLOW_INSECURE", False, raising=False)
    # ASGITransport reports 127.0.0.1 as the client host (which short-circuits
    # the HTTPS check), so force the local-host predicate to False to simulate
    # a request originating from outside the loopback.
    monkeypatch.setattr("api.infra.auth._is_local_host", lambda _request: False)

    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/echo",
            headers={"Authorization": _basic_header("ops", "s3cret")},
        )
    assert r.status_code == 426


@pytest.mark.asyncio
async def test_oss_honors_x_forwarded_proto_https(monkeypatch):
    """Reverse proxy terminated TLS upstream sets X-Forwarded-Proto=https."""
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_USER", "ops", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_PASSWORD", "s3cret", raising=False)
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ALLOW_INSECURE", False, raising=False)
    monkeypatch.setattr("api.infra.auth._is_local_host", lambda _request: False)

    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get(
            "/echo",
            headers={
                "Authorization": _basic_header("ops", "s3cret"),
                "X-Forwarded-Proto": "https",
            },
        )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# SaaS / on_prem JWT path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saas_jwt_with_matching_claim(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_CLAIM", "roles", raising=False)
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )

    app = _build_app(payload={"sub": "uid-1", "roles": ["User", "Manager"]})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": "Bearer fake.jwt"})
    assert r.status_code == 200, r.text
    assert r.json() == {"subject": "uid-1", "source": "jwt"}


@pytest.mark.asyncio
async def test_saas_jwt_with_non_matching_claim(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_CLAIM", "roles", raising=False)
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )

    app = _build_app(payload={"sub": "uid-1", "roles": ["User"]})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": "Bearer fake.jwt"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_saas_jwt_missing_token(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )

    app = _build_app(payload=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_saas_jwt_invalid_token_returns_401(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )

    # verify_token returns None for invalid tokens
    app = _build_app(payload=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": "Bearer bad.jwt"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_saas_jwt_multiple_accepted_values(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_CLAIM", "roles", raising=False)
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES",
        "Manager,Operator",
        raising=False,
    )

    app = _build_app(payload={"sub": "uid-9", "roles": ["Operator"]})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["subject"] == "uid-9"


@pytest.mark.asyncio
async def test_saas_jwt_nested_dict_claim(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_CLAIM", "roles", raising=False)
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )

    app = _build_app(payload={"sub": "uid-2", "roles": [{"name": "Manager"}, {"name": "User"}]})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_on_prem_falls_back_to_ibm_session_cookie(monkeypatch):
    """When no native JWT is present, the dependency decodes the IBM session
    cookie (without signature verification — Traefik validates upstream).
    Triggered purely by OPENRAG_RUN_MODE, no need for IBM_AUTH_ENABLED.
    """
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_CLAIM", "roles", raising=False)
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )
    monkeypatch.setattr(
        "config.settings.IBM_SESSION_COOKIE_NAME",
        "ibm-openrag-session",
        raising=False,
    )
    # Stub the IBM JWT decoder; we don't care about real signatures here.
    import auth.ibm_auth as ibm_auth_mod

    monkeypatch.setattr(
        ibm_auth_mod,
        "decode_ibm_jwt",
        lambda token: {"sub": "ibm-user-1", "roles": ["Manager"]},
    )

    # No native JWT path => session_manager.verify_token would be called with
    # no token. The stub returns None for whatever we hand it.
    app = _build_app(payload=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.cookies.set("ibm-openrag-session", "fake.ibm.jwt")
        r = await c.get("/echo")

    assert r.status_code == 200, r.text
    assert r.json() == {"subject": "ibm-user-1", "source": "jwt"}


@pytest.mark.asyncio
async def test_on_prem_ibm_cookie_with_non_matching_role(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "on_prem")
    monkeypatch.setattr(
        "config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "Manager", raising=False
    )
    monkeypatch.setattr(
        "config.settings.IBM_SESSION_COOKIE_NAME",
        "ibm-openrag-session",
        raising=False,
    )
    import auth.ibm_auth as ibm_auth_mod

    monkeypatch.setattr(
        ibm_auth_mod,
        "decode_ibm_jwt",
        lambda token: {"sub": "ibm-user-2", "roles": ["User"]},
    )

    app = _build_app(payload=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.cookies.set("ibm-openrag-session", "fake.ibm.jwt")
        r = await c.get("/echo")

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_saas_503_when_claim_values_unset(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setattr("config.settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES", "", raising=False)

    app = _build_app(payload={"sub": "uid-x", "roles": ["Manager"]})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"Authorization": "Bearer x"})
    assert r.status_code == 503
