"""Auth dependency for the /api/infra/* plane.

Pure JWT-claim (SaaS / on_prem) or HTTP Basic (OSS). No DB lookup, no
RBAC. Returns an `InfraAdmin` dataclass identifying the principal so
handlers can attribute audit_log rows.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Literal

from fastapi import Depends, HTTPException, Request

from config import settings as app_settings
from dependencies import get_session_manager
from utils.logging_config import get_logger
from utils.run_mode_utils import get_run_mode, is_run_mode_oss

logger = get_logger(__name__)


@dataclass(frozen=True)
class InfraAdmin:
    """A principal authorized to call the infra plane."""

    subject: str  # JWT `sub` (or `user_id`) or basic-auth username
    source: Literal["jwt", "basic"]


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


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    return None


def _verify_jwt(request: Request, session_manager) -> InfraAdmin:
    token = request.cookies.get("auth_token") or _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"error": "infra_auth_required"})
    payload = session_manager.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})

    claim_name = app_settings.OPENRAG_INFRA_ADMIN_CLAIM
    accepted = _accepted_claim_values()
    if not accepted:
        # Misconfiguration: claim values list is empty. Fail closed so
        # we don't silently let everyone with a valid token through.
        raise HTTPException(
            status_code=503,
            detail={"error": "infra_admin_claim_values_unset"},
        )

    have = _flatten_claim(payload.get(claim_name))
    if not (have & accepted):
        raise HTTPException(status_code=403, detail={"error": "infra_role_required"})

    subject = (
        payload.get("sub")
        or payload.get("user_id")
        or payload.get("preferred_username")
        or "unknown"
    )
    return InfraAdmin(subject=str(subject), source="jwt")


def _scheme_from_request(request: Request) -> str:
    """Effective scheme, honoring X-Forwarded-Proto from a TLS-terminating proxy."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
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
                "Infra basic auth requires HTTPS. Set OPENRAG_INFRA_ALLOW_INSECURE=true "
                "to permit plain HTTP (only behind a trusted proxy)."
            ),
        },
    )


def _verify_basic(request: Request) -> InfraAdmin:
    _enforce_https_or_local(request)

    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail={"error": "basic_auth_required"},
            headers={"WWW-Authenticate": 'Basic realm="infra"'},
        )

    encoded = header[len("Basic ") :].strip()
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_basic_auth"},
            headers={"WWW-Authenticate": 'Basic realm="infra"'},
        )

    if ":" not in decoded:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_basic_auth"},
            headers={"WWW-Authenticate": 'Basic realm="infra"'},
        )

    username, password = decoded.split(":", 1)

    expected_user = (
        app_settings.OPENRAG_INFRA_ADMIN_USER or app_settings.OPENSEARCH_USERNAME or ""
    )
    expected_pw = (
        app_settings.OPENRAG_INFRA_ADMIN_PASSWORD or app_settings.OPENSEARCH_PASSWORD or ""
    )
    if not expected_user or not expected_pw:
        raise HTTPException(
            status_code=503,
            detail={"error": "infra_admin_credentials_not_configured"},
        )

    if not (
        secrets.compare_digest(username, expected_user)
        and secrets.compare_digest(password, expected_pw)
    ):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_credentials"},
            headers={"WWW-Authenticate": 'Basic realm="infra"'},
        )

    return InfraAdmin(subject=username, source="basic")


def require_infra_admin() -> Callable[..., Any]:
    """FastAPI dependency factory — matches the shape of require_permission().

    Dispatches on run-mode at request time so that mode changes (e.g. an
    operator flipping OPENRAG_RUN_MODE for a smoke test) take effect on the
    next request rather than requiring a restart.
    """

    async def _dep(
        request: Request,
        session_manager=Depends(get_session_manager),
    ) -> InfraAdmin:
        if is_run_mode_oss():
            return _verify_basic(request)
        # saas / on_prem (and anything unrecognized, which run_mode_utils
        # defaults to "oss" — so this branch is genuinely just JWT modes).
        if get_run_mode() == "oss":
            return _verify_basic(request)
        return _verify_jwt(request, session_manager)

    return _dep
