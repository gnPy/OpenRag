"""Helpers for compact connector group ACL role names."""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from collections.abc import Iterable

_SAFE_COMPONENT_RE = re.compile(r"^[a-z0-9_-]+$")


def compact_acl_component(value: object, *, max_length: int = 48) -> str:
    """Return a short, role-safe component for provider/tenant/group IDs."""
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("ACL role component cannot be empty")

    try:
        parsed_uuid = uuid.UUID(text)
    except ValueError:
        if _SAFE_COMPONENT_RE.fullmatch(text) and len(text) <= max_length:
            return text
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return "h" + base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode("ascii")

    return base64.urlsafe_b64encode(parsed_uuid.bytes).rstrip(b"=").decode("ascii")


def canonical_group_role(provider_code: str, tenant_id: object, group_id: object) -> str:
    """Build the OpenSearch backend role used for connector group ACLs."""
    provider = compact_acl_component(provider_code, max_length=16)
    tenant = compact_acl_component(tenant_id or "global")
    group = compact_acl_component(group_id)
    return f"g:{provider}:{tenant}:{group}"


def canonical_group_roles(
    provider_code: str,
    tenant_id: object,
    group_ids: Iterable[object],
) -> list[str]:
    """Canonicalize and deduplicate group IDs while preserving first-seen order."""
    roles: list[str] = []
    seen: set[str] = set()
    for group_id in group_ids or ():
        try:
            role = canonical_group_role(provider_code, tenant_id, group_id)
        except ValueError:
            continue
        if role not in seen:
            seen.add(role)
            roles.append(role)
    return roles
