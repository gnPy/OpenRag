"""One-shot runtime migrations from JSON state to the SQL DB.

These run on application startup AFTER Alembic upgrade. Idempotency is
recorded in the `migration_status` table so the migration only ever
inserts once per install.

Phase 1 only migrates *user identity* — connections.json, conversations.json,
and config.yaml are left in place. The legacy users get a placeholder row
with `oauth_provider='legacy'`. The next time they sign in via Google /
IBM, `user_service.ensure_user_row` matches on `email_lookup_hash` and
upgrades the row in place, preserving the original user_id so all
existing JSON references stay valid.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config.paths import get_data_file
from db.models import MigrationStatus, User as UserRow
from db.repositories._helpers import email_lookup_hash
from utils.encryption import read_encrypted_file
from utils.logging_config import get_logger

logger = get_logger(__name__)

JSON_TO_DB_V1 = "json_to_db_v1"


async def _already_done(session: AsyncSession, name: str) -> bool:
    row = await session.get(MigrationStatus, name)
    return row is not None


async def _mark_done(session: AsyncSession, name: str, notes: str = "") -> None:
    session.add(
        MigrationStatus(name=name, completed_at=datetime.utcnow(), notes=notes)
    )
    await session.flush()


async def _read_json(path: str):
    if not os.path.exists(path):
        return None
    raw, _ = await read_encrypted_file(path)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Skipping malformed JSON during migration", path=path)
        return None


def _user_ids_from_connections(payload) -> Iterable[str]:
    if not payload:
        return []
    items = payload.get("connections", []) if isinstance(payload, dict) else payload
    out = []
    for c in items or []:
        if isinstance(c, dict) and c.get("user_id"):
            out.append(str(c["user_id"]))
    return out


def _user_ids_from_conversations(payload) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    return [k for k in payload.keys() if isinstance(k, str)]


def _user_ids_from_session_ownership(payload) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    out = []
    for v in payload.values():
        if isinstance(v, dict):
            uid = v.get("user_id")
            if uid:
                out.append(str(uid))
        elif isinstance(v, str):
            out.append(v)
    return out


async def migrate_legacy_users(session: AsyncSession) -> int:
    """Insert legacy/* users discovered in JSON files. Returns insert count."""
    seen: set[str] = set()
    sources = [
        ("connections.json", _user_ids_from_connections),
        ("conversations.json", _user_ids_from_conversations),
        ("session_ownership.json", _user_ids_from_session_ownership),
    ]
    for filename, extract in sources:
        payload = await _read_json(get_data_file(filename))
        if payload is None:
            continue
        for uid in extract(payload):
            if uid:
                seen.add(uid)

    if not seen:
        return 0

    inserted = 0
    for legacy_id in seen:
        # Email is unknown for legacy rows; use a synthetic placeholder so we
        # still have *some* lookup hash. Real merge happens on next sign-in.
        synth_email = f"{legacy_id}@unknown.local"
        row = UserRow(
            id=legacy_id,
            oauth_provider="legacy",
            oauth_subject=legacy_id,
            email=synth_email,
            email_lookup_hash=email_lookup_hash(synth_email),
            display_name=legacy_id,
        )
        try:
            session.add(row)
            await session.flush()
            inserted += 1
        except IntegrityError:
            await session.rollback()
            # Some other run beat us to it.
            continue
    return inserted


async def run(session: AsyncSession) -> None:
    """Top-level entry. Caller is responsible for committing."""
    if await _already_done(session, JSON_TO_DB_V1):
        return

    inserted = 0
    try:
        inserted = await migrate_legacy_users(session)
    except Exception as exc:  # noqa: BLE001
        logger.error("JSON->DB migration failed; will retry on next boot", error=str(exc))
        return

    await _mark_done(session, JSON_TO_DB_V1, notes=f"legacy_users_inserted={inserted}")
    logger.info("JSON->DB migration completed", inserted=inserted)


# ---------------------------------------------------------------------------
# Alembic upgrade — programmatic invocation
# ---------------------------------------------------------------------------

def run_alembic_upgrade(target: str = "head") -> None:
    """Run `alembic upgrade <target>` programmatically.

    Internally Alembic's env.py spins up its own asyncio.run loop, so this
    function MUST NOT be invoked from inside an already-running event
    loop. Async callers should use `run_alembic_upgrade_async` instead.
    """
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    cfg_path = root / "alembic.ini"
    if not cfg_path.exists():
        logger.warning("alembic.ini not found; skipping schema upgrade", path=str(cfg_path))
        return

    cfg = Config(str(cfg_path))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, target)


async def run_alembic_upgrade_async(target: str = "head") -> None:
    """Async-safe wrapper. Runs the sync alembic command in a worker thread.

    Necessary because `alembic/env.py` uses `asyncio.run(...)` internally,
    which fails when invoked from a running loop.
    """
    import asyncio

    await asyncio.to_thread(run_alembic_upgrade, target)
