"""Unit tests for ``utils.watsonx_retry.request_with_retry``."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from utils.watsonx_retry import _retry_after_seconds, request_with_retry


def _resp(status: int, *, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers or {})


@pytest.mark.asyncio
async def test_returns_immediately_on_200():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.return_value = _resp(200)

    with patch("utils.watsonx_retry.asyncio.sleep", AsyncMock()) as sleep:
        resp = await request_with_retry(client, "POST", "https://example/x")

    assert resp.status_code == 200
    assert client.request.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.side_effect = [_resp(429), _resp(429), _resp(200)]

    sleeps: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("utils.watsonx_retry.asyncio.sleep", side_effect=_record_sleep):
        resp = await request_with_retry(client, "POST", "https://example/x", base=1.0, cap=15.0)

    assert resp.status_code == 200
    assert client.request.await_count == 3
    assert len(sleeps) == 2
    # Full jitter: each sleep is in [0, min(cap, base*2**(attempt-1))]
    assert 0 <= sleeps[0] <= 1.0
    assert 0 <= sleeps[1] <= 2.0


@pytest.mark.asyncio
async def test_honors_retry_after_seconds_header():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.side_effect = [_resp(429, headers={"Retry-After": "2"}), _resp(200)]

    sleeps: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("utils.watsonx_retry.asyncio.sleep", side_effect=_record_sleep):
        resp = await request_with_retry(client, "POST", "https://example/x", cap=15.0)

    assert resp.status_code == 200
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_honors_retry_after_http_date_header():
    future = datetime.now(UTC) + timedelta(seconds=5)
    header = format_datetime(future, usegmt=True)
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.side_effect = [_resp(429, headers={"Retry-After": header}), _resp(200)]

    sleeps: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("utils.watsonx_retry.asyncio.sleep", side_effect=_record_sleep):
        resp = await request_with_retry(client, "POST", "https://example/x", cap=15.0)

    assert resp.status_code == 200
    assert len(sleeps) == 1
    # Allow a small tolerance because we compute "now" twice.
    assert 4.0 <= sleeps[0] <= 5.5


@pytest.mark.asyncio
async def test_retry_after_clamped_at_cap():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.side_effect = [_resp(429, headers={"Retry-After": "999"}), _resp(200)]

    sleeps: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("utils.watsonx_retry.asyncio.sleep", side_effect=_record_sleep):
        await request_with_retry(client, "POST", "https://example/x", cap=5.0, total_cap_s=60.0)

    assert sleeps == [5.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 502, 503])
async def test_does_not_retry_on_non_429(status):
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.return_value = _resp(status)

    with patch("utils.watsonx_retry.asyncio.sleep", AsyncMock()) as sleep:
        resp = await request_with_retry(client, "POST", "https://example/x")

    assert resp.status_code == status
    assert client.request.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhausts_after_max_attempts_and_returns_last_429():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.return_value = _resp(429)

    with patch("utils.watsonx_retry.asyncio.sleep", AsyncMock()):
        resp = await request_with_retry(client, "POST", "https://example/x", max_attempts=4)

    assert resp.status_code == 429
    assert client.request.await_count == 4


@pytest.mark.asyncio
async def test_total_cap_short_circuits_loop():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request.return_value = _resp(429)

    # First call to time.monotonic gives start; subsequent calls jump past the budget.
    times = iter([0.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    with (
        patch("utils.watsonx_retry.time.monotonic", side_effect=lambda: next(times)),
        patch("utils.watsonx_retry.asyncio.sleep", AsyncMock()) as sleep,
    ):
        resp = await request_with_retry(
            client, "POST", "https://example/x", max_attempts=5, total_cap_s=30.0
        )

    assert resp.status_code == 429
    # The retry loop exits via the total-cap short-circuit, so we never sleep
    # despite seeing a 429.
    sleep.assert_not_awaited()
    assert client.request.await_count == 1


def test_retry_after_seconds_missing_header():
    assert _retry_after_seconds(_resp(429), cap=10.0) is None


def test_retry_after_seconds_invalid_value():
    assert _retry_after_seconds(_resp(429, headers={"Retry-After": "nonsense"}), cap=10.0) is None


def test_retry_after_seconds_negative_clamped_to_zero():
    assert _retry_after_seconds(_resp(429, headers={"Retry-After": "-5"}), cap=10.0) == 0.0
