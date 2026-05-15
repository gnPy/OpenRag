"""Google Drive group ACL helpers."""

from __future__ import annotations

import asyncio
from typing import Any

import jwt
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.group_acl import canonical_group_role
from utils.logging_config import get_logger

logger = get_logger(__name__)

GOOGLE_DRIVE_GROUP_PROVIDER = "gdrive"
GOOGLE_GROUP_LABEL = "cloudidentity.googleapis.com/groups.discussion_forum"


def _group_tenant(group_email: str) -> str:
    if "@" in group_email:
        return group_email.rsplit("@", 1)[1].lower()
    return "global"


def google_drive_group_role(group_email: str | None) -> str | None:
    """Return the canonical OpenSearch role for a Google Drive group email."""
    if not group_email:
        return None
    email = group_email.strip().lower()
    if not email:
        return None
    return canonical_group_role(
        GOOGLE_DRIVE_GROUP_PROVIDER,
        _group_tenant(email),
        email,
    )


def _email_from_id_token(id_token: str | None) -> str | None:
    if not id_token:
        return None
    try:
        claims = jwt.decode(
            id_token,
            options={"verify_signature": False, "verify_aud": False},
        )
        email = claims.get("email")
        if email:
            return str(email)
    except Exception as e:
        logger.debug("Could not decode Google id_token email", error=str(e))
    return None


async def _execute_google_request(request: Any) -> dict[str, Any]:
    return await asyncio.to_thread(request.execute)


def _cel_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


async def _get_drive_user_email(drive_service: Any, credentials: Any) -> str | None:
    email = _email_from_id_token(getattr(credentials, "id_token", None))
    if email:
        return email

    if drive_service is None:
        return None

    try:
        about = await _execute_google_request(
            drive_service.about().get(fields="user(emailAddress)")
        )
        return about.get("user", {}).get("emailAddress")
    except Exception as e:
        logger.warning("Google Drive group ACL lookup could not resolve user email", error=str(e))
        return None


async def _get_cloud_identity_group_roles(
    credentials: Any,
    user_email: str,
) -> list[str] | None:
    """Fetch current-user groups through Cloud Identity when the tenant allows it."""
    try:
        cloud_identity_service = build(
            "cloudidentity",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
    except Exception as e:
        logger.debug("Could not create Google Cloud Identity client for group ACLs", error=str(e))
        return None

    roles: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    query = f"member_key_id == '{_cel_string(user_email)}' && '{GOOGLE_GROUP_LABEL}' in labels"

    try:
        while True:
            request = (
                cloud_identity_service.groups()
                .memberships()
                .searchTransitiveGroups(
                    parent="groups/-",
                    query=query,
                    pageSize=200,
                    pageToken=page_token,
                )
            )
            response = await _execute_google_request(request)

            for membership in response.get("memberships", []) or []:
                group_key = membership.get("groupKey", {}) or {}
                role = google_drive_group_role(group_key.get("id"))
                if role and role not in seen:
                    seen.add(role)
                    roles.append(role)

            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status in (401, 403):
            logger.info(
                "Google Cloud Identity group ACL lookup unavailable; falling back to "
                "Admin SDK if permitted",
                status_code=status,
            )
            return None
        logger.warning("Google Cloud Identity group ACL lookup failed", error=str(e))
        return None
    except Exception as e:
        logger.debug("Google Cloud Identity group ACL lookup errored", error=str(e))
        return None

    return roles


async def get_current_user_google_group_roles(
    drive_service: Any,
    credentials: Any,
) -> list[str]:
    """Fetch Google Workspace groups for the connected Drive user."""
    if credentials is None:
        return []

    user_email = await _get_drive_user_email(drive_service, credentials)
    if not user_email:
        return []

    cloud_identity_roles = await _get_cloud_identity_group_roles(credentials, user_email)
    if cloud_identity_roles is not None:
        return cloud_identity_roles

    try:
        directory_service = build(
            "admin",
            "directory_v1",
            credentials=credentials,
            cache_discovery=False,
        )
    except Exception as e:
        logger.warning("Could not create Google Directory client for group ACLs", error=str(e))
        return []

    roles: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    user_domain = user_email.rsplit("@", 1)[1].lower() if "@" in user_email else None

    try:
        while True:
            kwargs: dict[str, Any] = {
                "userKey": user_email,
                "maxResults": 200,
                "pageToken": page_token,
                "fields": "nextPageToken,groups(email)",
            }
            if user_domain:
                kwargs["domain"] = user_domain
            request = directory_service.groups().list(
                **kwargs,
            )
            response = await _execute_google_request(request)

            for group in response.get("groups", []) or []:
                role = google_drive_group_role(group.get("email"))
                if role and role not in seen:
                    seen.add(role)
                    roles.append(role)

            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status in (401, 403):
            logger.warning(
                "Google Directory group ACL lookup denied; check Admin SDK API and "
                "admin.directory.group.readonly consent",
                status_code=status,
            )
            return []
        logger.warning("Google Directory group ACL lookup failed", error=str(e))
        return []
    except Exception as e:
        logger.warning("Google Directory group ACL lookup errored", error=str(e))
        return []

    return roles
