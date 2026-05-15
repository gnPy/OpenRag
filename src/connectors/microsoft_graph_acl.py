"""Microsoft Graph group ACL helpers shared by Microsoft connectors."""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import jwt

from utils.group_acl import canonical_group_role, canonical_group_roles
from utils.logging_config import get_logger

logger = get_logger(__name__)

MICROSOFT_GRAPH_GROUP_PROVIDER = "m365"


def tenant_id_from_access_token(access_token: str | None, fallback: str | None = None) -> str:
    """Read the tenant id from a Microsoft access token without validating it."""
    if access_token:
        raw_token = access_token.removeprefix("Bearer ").strip()
        try:
            claims = jwt.decode(
                raw_token,
                options={"verify_signature": False, "verify_aud": False},
            )
            token_tenant = claims.get("tid")
            if token_tenant:
                return token_tenant
        except Exception as e:
            logger.debug("Could not decode Microsoft access token tenant", error=str(e))
    return fallback or "common"


def microsoft_group_role(
    group_id: str | None,
    *,
    access_token: str | None = None,
    tenant_id: str | None = None,
) -> str | None:
    """Return the canonical OpenSearch role for a Microsoft group id."""
    if not group_id:
        return None
    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)
    return canonical_group_role(
        MICROSOFT_GRAPH_GROUP_PROVIDER,
        resolved_tenant,
        group_id,
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def get_oauth_access_token(oauth: Any) -> str | None:
    """Return an access token string from either old dict or current string APIs."""
    if oauth is None:
        return None
    token_value = await _maybe_await(oauth.get_access_token())
    if isinstance(token_value, dict):
        return token_value.get("access_token")
    if isinstance(token_value, str):
        return token_value.removeprefix("Bearer ").strip()
    return None


async def get_current_user_microsoft_group_roles(
    oauth: Any,
    graph_base_url: str,
    *,
    tenant_id: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[str]:
    """Fetch transitive Microsoft group memberships for the current OAuth user."""
    if oauth is None:
        return []

    try:
        access_token = await get_oauth_access_token(oauth)
    except Exception as e:
        logger.warning("Unable to get Microsoft Graph token for group ACLs", error=str(e))
        return []

    if not access_token:
        return []

    resolved_tenant = tenant_id_from_access_token(access_token, fallback=tenant_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{graph_base_url}/me/transitiveMemberOf/microsoft.graph.group"
    params: dict[str, str] | None = {"$select": "id"}
    group_ids: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            while url:
                response = await client.get(url, headers=headers, params=params)
                params = None
                if response.status_code in (401, 403):
                    logger.warning(
                        "Microsoft Graph group ACL lookup denied",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    return []
                if response.status_code != 200:
                    logger.warning(
                        "Microsoft Graph group ACL lookup failed",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    return []

                data = response.json()
                for entry in data.get("value", []):
                    group_id = entry.get("id")
                    if group_id:
                        group_ids.append(group_id)
                url = data.get("@odata.nextLink")
    except Exception as e:
        logger.warning("Microsoft Graph group ACL lookup errored", error=str(e))
        return []

    return canonical_group_roles(
        MICROSOFT_GRAPH_GROUP_PROVIDER,
        resolved_tenant,
        group_ids,
    )
