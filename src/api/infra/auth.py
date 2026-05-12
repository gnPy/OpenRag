"""Auth dependency for the /api/infra/* plane.

Dispatch is purely on OPENRAG_RUN_MODE:

  * oss     -> HTTP Basic against OPENRAG_INFRA_ADMIN_USER /
               OPENRAG_INFRA_ADMIN_PASSWORD (fallback to OPENSEARCH_USERNAME /
               OPENSEARCH_PASSWORD). Uses FastAPI's HTTPBasic security.
  * saas /
    on_prem -> JWT mode. Reads the token from:
                 - Authorization: Bearer <jwt>, OR
                 - auth_token cookie (native OpenRAG JWT), OR
                 - IBM session cookie (decoded without signature verification
                   because Traefik / the upstream proxy validates it).
               Then checks that OPENRAG_INFRA_ADMIN_CLAIM contains a value
               from OPENRAG_INFRA_ADMIN_CLAIM_VALUES.

No DB lookup, no RBAC. Returns an InfraAdmin dataclass so handlers can
attribute audit_log rows.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config import settings as app_settings
from dependencies import get_session_manager
from utils.logging_config import get_logger
from utils.run_mode_utils import is_run_mode_oss

logger = get_logger(__name__)


# auto_error=False so we can raise a custom 401 detail body rather than
# FastAPI's default "Not authenticated" string.
_basic = HTTPBasic(realm="infra", auto_error=False)


@dataclass(frozen=True)
class InfraAdmin:
    """A principal authorized to call the infra plane."""

    subject: str  # JWT `sub` (or `user_id` / `username`) or basic-auth username
    source: Literal["jwt", "basic"]


# ---------------------------------------------------------------------------
# Claim flattening
# ---------------------------------------------------------------------------


def _flatten_claim(claim: Any) -> set[str]:
    """Reduce a JWT claim to a flat set of strings for membership testing.

    Handles the common shapes operators throw at us:
      * ``"Manager"`` -> ``{"Manager"}``
      * ``["Manager", "User"]`` -> ``{"Manager", "User"}``
      * ``[{"name": "Manager"}, {"name": "User"}]`` -> ``{"Manager", "User"}``
      * ``{"name": "Manager"}`` -> ``{"Manager"}``

    Anything else returns ``set()`` and is logged at INFO with the claim's
    type so operators can debug an IdP that hands us a stranger shape.
    """
    if claim is None:
        return set()
    if isinstance(claim, str):
        return {claim}
    if isinstance(claim, list):
        out: set[str] = set()
        for item in claim:
            if isinstance(item, str):
                out.add(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                out.add(item["name"])
        return out
    if isinstance(claim, dict) and isinstance(claim.get("name"), str):
        return {claim["name"]}
    logger.info(
        "Infra admin JWT claim has unrecognized shape; treating as empty",
        claim_type=type(claim).__name__,
    )
    return set()


def _accepted_claim_values() -> set[str]:
    raw = app_settings.OPENRAG_INFRA_ADMIN_CLAIM_VALUES or ""
    return {v.strip() for v in raw.split(",") if v.strip()}


# ---------------------------------------------------------------------------
# JWT path (saas / on_prem)
# ---------------------------------------------------------------------------


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    return None


def _ibm_session_cookie(request: Request) -> Optional[str]:
    """Return the IBM session cookie value, if present.

    The cookie name is configurable via IBM_SESSION_COOKIE_NAME. We read it
    regardless of IBM_AUTH_ENABLED — the dispatch is on run-mode, and if a
    CPD/IBM-fronted deployment sets the cookie we honour it. Decoding is
    performed without signature verification because Traefik / the upstream
    proxy validates the JWT before the backend ever sees it.
    """
    cookie_name = getattr(app_settings, "IBM_SESSION_COOKIE_NAME", None)
    if not cookie_name:
        return None
    return request.cookies.get(cookie_name)


def _decode_jwt(request: Request, session_manager) -> Optional[dict]:
    """Try every supported JWT decoding strategy. Returns the payload or None.

    Order:
      1. Native OpenRAG JWT (Authorization: Bearer or auth_token cookie)
         via session_manager.verify_token — fully signature-verified.
      2. IBM session cookie via auth.ibm_auth.decode_ibm_jwt — UNVERIFIED;
         trusts the upstream proxy. Only consulted when the native path
         returns nothing.
    """
    native_token = _bearer_token(request) or request.cookies.get("auth_token")
    if native_token:
        try:
            payload = session_manager.verify_token(native_token)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Native JWT verify raised", error=str(exc))
            payload = None
        if payload:
            return payload

    ibm_token = _ibm_session_cookie(request)
    if ibm_token:
        # Imported lazily so the auth module has no hard dependency on the
        # ibm_auth submodule for non-IBM deployments.
        from auth.ibm_auth import decode_ibm_jwt

        return decode_ibm_jwt(ibm_token)

    return None


def _verify_jwt(request: Request, session_manager) -> InfraAdmin:
    payload = _decode_jwt(request, session_manager)
    if not payload:
        raise HTTPException(
            status_code=401, detail={"error": "infra_auth_required"}
        )

    accepted = _accepted_claim_values()
    if not accepted:
        # Misconfiguration: claim values list is empty. Fail closed so
        # we don't silently let everyone with a valid token through.
        raise HTTPException(
            status_code=503,
            detail={"error": "infra_admin_claim_values_unset"},
        )

    claim_name = app_settings.OPENRAG_INFRA_ADMIN_CLAIM
    have = _flatten_claim(payload.get(claim_name))
    if not (have & accepted):
        raise HTTPException(
            status_code=403, detail={"error": "infra_role_required"}
        )

    subject = (
        payload.get("sub")
        or payload.get("user_id")
        or payload.get("username")
        or payload.get("preferred_username")
        or "unknown"
    )
    return InfraAdmin(subject=str(subject), source="jwt")


# ---------------------------------------------------------------------------
# Basic-auth path (oss)
# ---------------------------------------------------------------------------


def _scheme_from_request(request: Request) -> str:
    """Effective scheme, honoring X-Forwarded-Proto from a TLS-terminating proxy."""
    forwarded = (
        request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    )
    if forwarded:
        return forwarded
    return (request.url.scheme or "").lower()


def _is_local_host(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _enforce_https_or_local(request: Request) -> None:
    if app_settings.OPENRAG_INFRA_ALLOW_INSECURE:
        return
    if _scheme_from_request(request) == "https":
        return
    if _is_local_host(request):
        return
    raise HTTPException(
        status_code=426,
        detail={
            "error": "https_required",
            "message": (
                "Infra basic auth requires HTTPS. Set "
                "OPENRAG_INFRA_ALLOW_INSECURE=true to permit plain HTTP "
                "(only behind a trusted proxy)."
            ),
        },
    )


def _verify_basic(
    request: Request, credentials: Optional[HTTPBasicCredentials]
) -> InfraAdmin:
    _enforce_https_or_local(request)

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "basic_auth_required"},
            headers={"WWW-Authenticate": 'Basic realm="infra"'},
        )

    expected_user = (
        app_settings.OPENRAG_INFRA_ADMIN_USER or app_settings.OPENSEARCH_USERNAME or ""
    )
    expected_pw = (
        app_settings.OPENRAG_INFRA_ADMIN_PASSWORD
        or app_settings.OPENSEARCH_PASSWORD
        or ""
    )
    if not expected_user or not expected_pw:
        raise HTTPException(
            status_code=503,
            detail={"error": "infra_admin_credentials_not_configured"},
        )

    if not (
        secrets.compare_digest(credentials.username, expected_user)
        and secrets.compare_digest(credentials.password, expected_pw)
    ):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_credentials"},
            headers={"WWW-Authenticate": 'Basic realm="infra"'},
        )

    return InfraAdmin(subject=credentials.username, source="basic")


# ---------------------------------------------------------------------------
# Public dependency factory
# ---------------------------------------------------------------------------


def require_infra_admin() -> Callable[..., Any]:
    """FastAPI dependency factory — matches the shape of require_permission().

    Dispatches on run-mode at request time so that mode changes (e.g. an
    operator flipping OPENRAG_RUN_MODE for a smoke test) take effect on the
    next request rather than requiring a restart.

      * oss  -> HTTP Basic (FastAPI HTTPBasic).
      * non-oss (saas / on_prem / anything else) -> JWT with role-claim check.
        IBM_AUTH_ENABLED is NOT consulted; the JWT decoder transparently
        falls back to the IBM session cookie when present.
    """

    async def _dep(
        request: Request,
        credentials: Optional[HTTPBasicCredentials] = Depends(_basic),
        session_manager=Depends(get_session_manager),
    ) -> InfraAdmin:
        if is_run_mode_oss():
            return _verify_basic(request, credentials)
        return _verify_jwt(request, session_manager)

    return _dep
