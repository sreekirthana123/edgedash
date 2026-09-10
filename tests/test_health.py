"""Tests for the read-only health module (edgedash.health)."""

from datetime import datetime, timedelta, timezone

import pytest

from edgedash import health, storage
from edgedash.runtime import redact_error


@pytest.fixture(autouse=True)
def _force_sqlite_backend(monkeypatch):
    """Pin storage to SQLite for deterministic tests (see test_extraction_cache)."""
    monkeypatch.setattr(storage, "_using_postgres", lambda: False)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "health.db")
    storage.init_db(path)
    return path


def _add_listing(db_path, fetched_at, title="Role", url=None):
    url = url or f"https://example.com/{title}"
    listing_id = storage._make_listing_id("arbeitnow", url)
    with storage.get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO listings
            (id, title, company, location, url, description, source, posted_at, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (listing_id, title, "ACME GmbH", "Berlin", url, "Python and SQL.",
             "arbeitnow", fetched_at, fetched_at),
        )
        conn.commit()
    return listing_id


def _add_listing_hours_ago(db_path, hours_ago, title):
    fetched_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return _add_listing(db_path, fetched_at=fetched_at, title=title)


def _log_cycle(db_path, agent, status, minutes_ago, notes=None):
    finished = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    storage.log_cycle(
        db_path, agent=agent, started_at=finished, finished_at=finished,
        records_touched=0, status=status, notes=notes,
    )


def test_database_reachable(db_path):
    name, passed, message = health.check_database(db_path)
    assert passed is True
    assert name == "database"
    assert "reachable" in message


def test_newest_listing_no_listings_fails(db_path):
    name, passed, message = health.check_newest_listing(db_path)
    assert passed is False
    assert "no listings" in message


def test_newest_listing_fresh_ok(db_path):
    _add_listing_hours_ago(db_path, hours_ago=2, title="fresh")
    name, passed, message = health.check_newest_listing(db_path)
    assert passed is True
    assert "days ago" in message


def test_newest_listing_stale_fails(db_path):
    _add_listing_hours_ago(db_path, hours_ago=24 * 5, title="stale")
    name, passed, message = health.check_newest_listing(db_path)
    assert passed is False
    assert "5.0 days ago" in message


def test_successful_cycle_none_fails(db_path):
    name, passed, message = health.check_successful_cycle(db_path)
    assert passed is False
    assert "no successful cycle" in message


def test_successful_cycle_recent_ok(db_path):
    _log_cycle(db_path, agent="Verifier", status="ok", minutes_ago=30)
    name, passed, message = health.check_successful_cycle(db_path)
    assert passed is True
    assert "0.5h ago" in message


def test_successful_cycle_stale_fails(db_path):
    _log_cycle(db_path, agent="Verifier", status="ok", minutes_ago=60 * 60)
    name, passed, message = health.check_successful_cycle(db_path)
    assert passed is False
    assert "60.0h ago" in message


def test_last_three_verifications_all_failed_fails(db_path):
    for minutes_ago in (5, 10, 15):
        _log_cycle(db_path, agent="Verifier", status="failed", minutes_ago=minutes_ago)
    name, passed, message = health.check_last_three_verifications(db_path)
    assert passed is False
    assert "all failed" in message


def test_last_three_verifications_mixed_ok(db_path):
    _log_cycle(db_path, agent="Verifier", status="ok", minutes_ago=5)
    _log_cycle(db_path, agent="Verifier", status="failed", minutes_ago=10)
    _log_cycle(db_path, agent="Verifier", status="failed", minutes_ago=15)
    name, passed, message = health.check_last_three_verifications(db_path)
    assert passed is True
    assert "ok, failed, failed" in message


def test_last_three_verifications_insufficient_history_ok(db_path):
    _log_cycle(db_path, agent="Verifier", status="failed", minutes_ago=5)
    name, passed, message = health.check_last_three_verifications(db_path)
    assert passed is True
    assert "no Verifier history" in message or "last 1" in message


def test_run_healthy_returns_zero(db_path, capsys):
    _add_listing_hours_ago(db_path, hours_ago=1, title="a")
    _log_cycle(db_path, agent="Verifier", status="ok", minutes_ago=10)
    code = health.run(db_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "HEALTHY" in out
    assert "OK  " in out


def test_run_unhealthy_returns_one(db_path, capsys):
    code = health.run(db_path)  # empty db: no listings, no cycles
    out = capsys.readouterr().out
    assert code == 1
    assert "UNHEALTHY" in out
    assert "FAIL" in out


def test_redact_error_hides_full_connection_url():
    message = (
        'could not connect postgresql://postgres:SUPERSECRETPASS@db-x7.supabase.co:5432/postgres'
        ' (password must not be percent-encoded)'
    )
    out = redact_error(message)
    assert "SUPERSECRETPASS" not in out
    assert "postgresql://" not in out
    assert "redacted" in out


def test_redact_error_hides_schemeless_userinfo_fragment():
    """psycopg quotes only the userinfo@host fragment — no scheme present."""
    message = (
        'psycopg.OperationalError: invalid percent-encoded token: '
        '"SUPERSECRETPASS@db-x7.supabase.co"'
    )
    out = redact_error(message)
    assert "SUPERSECRETPASS" not in out
    assert "@" not in out
    assert "redacted" in out


def test_redact_error_hides_api_keys():
    message = "Gemini API key AIzaSyDEFAULTFULLKEY1234567890abcdefghij was invalid"
    out = redact_error(message)
    assert "AIzaSyDEFAULTFULLKEY1234567890abcdefghij" not in out
    assert "redacted API key" in out