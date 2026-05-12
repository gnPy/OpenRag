"""Persistence + drift detection for the OpenSearch security setup state.

Status is tracked as a row in the existing `migration_status` table under
the name "opensearch_security_v1". This keeps a single source of truth for
"has the OpenSearch DLS / role / role-mapping bootstrap been applied" that
the infra status endpoint can consult, regardless of whether the setup ran
automatically at startup or was triggered manually via POST /api/infra/opensearch/setup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import db.engine as _engine_mod
from db.models import MigrationStatus
from utils.logging_config import get_logger

logger = get_logger(__name__)

OPENSEARCH_SECURITY_V1 = "opensearch_security_v1"


def _session_local():
    """Resolve SessionLocal at call time so tests can monkeypatch db.engine."""
    if _engine_mod.SessionLocal is None:
        _engine_mod.init_engine()
    assert _engine_mod.SessionLocal is not None
    return _engine_mod.SessionLocal


async def mark_opensearch_security_configured(notes: str = "") -> None:
    """Upsert the migration_status row indicating setup has completed.

    Safe to call multiple times — re-running setup refreshes `completed_at`
    so the status endpoint reflects the latest successful run.
    """
    SessionLocal = _session_local()
    async with SessionLocal() as session:
        existing = await session.get(MigrationStatus, OPENSEARCH_SECURITY_V1)
        if existing is None:
            session.add(
                MigrationStatus(
                    name=OPENSEARCH_SECURITY_V1,
                    completed_at=datetime.utcnow(),
                    notes=notes[:2048],
                )
            )
        else:
            existing.completed_at = datetime.utcnow()
            if notes:
                existing.notes = notes[:2048]
            session.add(existing)
        await session.commit()


async def get_last_setup_at() -> Optional[datetime]:
    """Return the completed_at timestamp of the most recent setup, or None."""
    SessionLocal = _session_local()
    async with SessionLocal() as session:
        row = await session.get(MigrationStatus, OPENSEARCH_SECURITY_V1)
        return row.completed_at if row else None


async def is_opensearch_security_configured() -> bool:
    """True iff the migration_status row exists."""
    return (await get_last_setup_at()) is not None


async def get_openrag_user_role(opensearch_client) -> Optional[dict]:
    """Return the live `openrag_user_role` body from OpenSearch, or None if absent.

    Used by the infra status endpoint to detect drift between the DB-recorded
    setup state and the actual OpenSearch security config. Returns None on 404
    (role not found); re-raises other transport errors so the caller can
    surface them as "degraded - unreachable".
    """
    try:
        resp = await opensearch_client.transport.perform_request(
            "GET", "/_plugins/_security/api/roles/openrag_user_role"
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "404" in msg or "not_found" in msg or "not found" in msg:
            return None
        raise
    if isinstance(resp, dict):
        # OpenSearch returns either {"openrag_user_role": {...}} or {...}
        return resp.get("openrag_user_role", resp)
    return None
