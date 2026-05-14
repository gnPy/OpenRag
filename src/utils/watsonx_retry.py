"""Async retry helper for watsonx.ai HTTP calls.

Retries only on HTTP 429 using AWS-style "Full Jitter" exponential backoff,
honors the ``Retry-After`` response header when present, and bounds both the
attempt count and the total wall-clock budget so a caller (e.g. a health-check
poll) cannot hang waiting on a throttled upstream.

See https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/.
"""

import asyncio
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from utils.logging_config import get_logger

logger = get_logger(__name__)


def _retry_after_seconds(resp: httpx.Response, cap: float) -> float | None:
    """Parse the ``Retry-After`` header (int seconds or HTTP-date), clamped at ``cap``.

    Returns ``None`` when the header is absent or unparseable, so the caller
    falls back to jittered exponential backoff.
    """
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(max(0.0, float(raw)), cap)
    except (TypeError, ValueError):
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = (dt - datetime.now(UTC)).total_seconds()
        return max(0.0, min(delta, cap))
    except (TypeError, ValueError):
        return None


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    base: float = 1.0,
    cap: float = 15.0,
    total_cap_s: float = 30.0,
    **kwargs,
) -> httpx.Response:
    """Issue an httpx request, retrying only on HTTP 429.

    Non-429 responses (including 4xx auth failures and 5xx server errors) are
    returned to the caller on the first attempt so existing error-shaping logic
    runs unchanged.
    """
    start = time.monotonic()
    resp: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        resp = await client.request(method, url, **kwargs)
        if resp.status_code != 429:
            return resp
        if attempt == max_attempts:
            break
        elapsed = time.monotonic() - start
        remaining = total_cap_s - elapsed
        if remaining <= 0:
            break
        ra = _retry_after_seconds(resp, cap)
        if ra is not None:
            sleep = ra
        else:
            # Full Jitter: random.uniform(0, min(cap, base * 2 ** (attempt - 1)))
            sleep = random.uniform(0, min(cap, base * (2 ** (attempt - 1))))
        sleep = min(sleep, remaining)
        logger.warning(
            "watsonx 429 on %s %s (attempt %d/%d), sleeping %.2fs",
            method,
            url,
            attempt,
            max_attempts,
            sleep,
        )
        await asyncio.sleep(sleep)
    return resp  # type: ignore[return-value]  # loop runs at least once
