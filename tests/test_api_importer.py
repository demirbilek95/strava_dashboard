"""Tests for StravaImporter and _RateLimiter."""

import time
from unittest.mock import MagicMock, patch

import pytest

from strava.db.api_importer import _RateLimiter, StravaImporter

# pylint: disable=redefined-outer-name


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_latest_activity_timestamp.return_value = None
    db.activity_has_streams.return_value = False  # default: activity not yet synced
    return db


@pytest.fixture
def mock_api():
    api = MagicMock()
    api.get_all_activities.return_value = []
    api.get_activity_streams.return_value = {}
    api.get_activity_detail.return_value = {}
    return api


@pytest.fixture
def importer(mock_db, mock_api):
    imp = StravaImporter(mock_db, mock_api)
    # Replace the real rate limiter with one that never blocks to keep tests fast.
    imp._rate_limiter = MagicMock()
    return imp


# ── _RateLimiter tests ────────────────────────────────────────────────────────


def test_rate_limiter_no_block_under_limit():
    """acquire() should return immediately when under the call cap."""
    limiter = _RateLimiter(max_calls=10, period_seconds=60)
    start = time.monotonic()
    for _ in range(10):
        limiter.acquire()
    elapsed = time.monotonic() - start
    # Should complete in well under a second with no sleeping.
    assert elapsed < 1.0


def test_rate_limiter_blocks_when_limit_reached():
    """acquire() should block once the cap is exhausted within the window."""
    # Use a very short period so the test doesn't hang.
    limiter = _RateLimiter(max_calls=2, period_seconds=0.3)
    limiter.acquire()
    limiter.acquire()
    # Third call must wait for the window to roll over.
    start = time.monotonic()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.25


# ── import_all_data: lookback_months parameter ────────────────────────────────


def test_import_fresh_db_default_3_months(mock_db, mock_api):
    """Fresh DB should use a 3-month lookback by default."""
    mock_db.get_latest_activity_timestamp.return_value = None
    mock_api.get_all_activities.return_value = []

    imp = StravaImporter(mock_db, mock_api)
    imp._rate_limiter = MagicMock()

    with patch("strava.db.api_importer.time") as mock_time:
        now = 1_700_000_000
        mock_time.time.return_value = now

        imp.import_all_data()

    after_arg = mock_api.get_all_activities.call_args[1].get(
        "after"
    ) or mock_api.get_all_activities.call_args[0][0] if mock_api.get_all_activities.call_args[0] else mock_api.get_all_activities.call_args[1].get("after")
    # The call is `get_all_activities(after=fetch_after)` — use kwargs.
    after_arg = mock_api.get_all_activities.call_args.kwargs.get("after")
    expected = now - 3 * 30 * 24 * 60 * 60
    assert after_arg == expected


def test_import_fresh_db_explicit_6_months(mock_db, mock_api):
    """Fresh DB with lookback_months=6 should use a 6-month lookback."""
    mock_db.get_latest_activity_timestamp.return_value = None
    mock_api.get_all_activities.return_value = []

    imp = StravaImporter(mock_db, mock_api)
    imp._rate_limiter = MagicMock()

    with patch("strava.db.api_importer.time") as mock_time:
        now = 1_700_000_000
        mock_time.time.return_value = now

        imp.import_all_data(lookback_months=6)

    after_arg = mock_api.get_all_activities.call_args.kwargs.get("after")
    expected = now - 6 * 30 * 24 * 60 * 60
    assert after_arg == expected


def test_import_existing_db_incremental_when_db_covers_window(mock_db, mock_api):
    """When DB already covers the requested window, use db_latest (incremental sync)."""
    # db_latest is 4 months ago; 3-month lookback cutoff is more recent → use db_latest.
    with patch("strava.db.api_importer.time") as mock_time:
        now = 1_750_000_000
        mock_time.time.return_value = now
        watermark = now - int(4 * 30 * 24 * 60 * 60)  # 4 months ago
        mock_db.get_latest_activity_timestamp.return_value = watermark
        mock_api.get_all_activities.return_value = []

        imp = StravaImporter(mock_db, mock_api)
        imp._rate_limiter = MagicMock()

        imp.import_all_data(lookback_months=3)

    after_arg = mock_api.get_all_activities.call_args.kwargs.get("after")
    expected_cutoff = now - int(3 * 30 * 24 * 60 * 60)  # 3-month cutoff
    # min(4-months-ago, 3-months-ago) = 4-months-ago = watermark
    assert after_arg == min(watermark, expected_cutoff)


def test_import_existing_db_backfills_when_user_requests_more_history(mock_db, mock_api):
    """When user selects a longer range than the DB covers, fetch the historical gap."""
    # db_latest is 7 days ago (recent sync); user requests 1 year → use 1-year cutoff.
    with patch("strava.db.api_importer.time") as mock_time:
        now = 1_750_000_000
        mock_time.time.return_value = now
        watermark = now - int(7 * 24 * 60 * 60)  # 7 days ago
        mock_db.get_latest_activity_timestamp.return_value = watermark
        mock_api.get_all_activities.return_value = []

        imp = StravaImporter(mock_db, mock_api)
        imp._rate_limiter = MagicMock()

        imp.import_all_data(lookback_months=12)

    after_arg = mock_api.get_all_activities.call_args.kwargs.get("after")
    expected_cutoff = now - int(12 * 30 * 24 * 60 * 60)  # 1-year cutoff
    assert after_arg == expected_cutoff


def test_import_all_time_passes_none(mock_db, mock_api):
    """lookback_months=None should pass after=None to fetch full history."""
    mock_db.get_latest_activity_timestamp.return_value = None
    mock_api.get_all_activities.return_value = []

    imp = StravaImporter(mock_db, mock_api)
    imp._rate_limiter = MagicMock()

    imp.import_all_data(lookback_months=None)

    after_arg = mock_api.get_all_activities.call_args.kwargs.get("after")
    assert after_arg is None


# ── Progress callback ─────────────────────────────────────────────────────────


def test_progress_callback_messages(mock_db, mock_api):
    """Progress callback should receive informative messages during import."""
    mock_db.get_latest_activity_timestamp.return_value = None
    mock_api.get_all_activities.return_value = [
        {"id": 1, "start_date": "2024-01-01T10:00:00Z"},
        {"id": 2, "start_date": "2024-01-02T10:00:00Z"},
    ]
    mock_api.get_activity_streams.return_value = {}
    mock_api.get_activity_detail.return_value = {}

    imp = StravaImporter(mock_db, mock_api)
    imp._rate_limiter = MagicMock()

    messages = []
    imp.import_all_data(progress_callback=lambda msg, pct: messages.append(msg))

    all_text = " ".join(messages)
    assert "3 months" in all_text, "Should mention lookback period"
    assert "Found 2" in all_text, "Should report activity count"
    assert "rate-limited" in all_text.lower(), "Should mention rate limiting"
    assert "Import complete!" in messages, "Should finish with completion message"


# ── Stream-skip optimisation ──────────────────────────────────────────────────


def test_skips_stream_fetch_for_already_synced_activity(mock_db, mock_api):
    """Activities that already have streams should not be re-fetched."""
    mock_db.get_latest_activity_timestamp.return_value = None
    mock_db.activity_has_streams.return_value = True  # already synced
    mock_api.get_all_activities.return_value = [
        {"id": 99, "start_date": "2024-06-01T09:00:00Z"},
    ]

    imp = StravaImporter(mock_db, mock_api)
    imp._rate_limiter = MagicMock()

    imp.import_all_data()

    # Neither streams nor detail should be fetched.
    mock_api.get_activity_streams.assert_not_called()
    mock_api.get_activity_detail.assert_not_called()
    imp._rate_limiter.acquire.assert_not_called()


# ── Rate limiter is called per API request ────────────────────────────────────


def test_rate_limiter_called_for_each_api_request(mock_db, mock_api):
    """_rate_limiter.acquire() must be called once per API call (2 per activity)."""
    mock_db.get_latest_activity_timestamp.return_value = None
    mock_api.get_all_activities.return_value = [
        {"id": 10, "start_date": "2024-03-01T08:00:00Z"},
    ]

    imp = StravaImporter(mock_db, mock_api)
    imp._rate_limiter = MagicMock()

    imp.import_all_data()

    # 1 activity × 2 API calls (streams + detail) = 2 acquires.
    assert imp._rate_limiter.acquire.call_count == 2
