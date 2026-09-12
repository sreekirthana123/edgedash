"""Tests for verification state in storage (count_unverified / mark_verified).

Rule 38: stale verified data beats fresh unverified data — a failing Verifier
run must never overwrite the last known-good verified state.
"""

import sqlite3

import pytest

from datetime import datetime, timezone

from edgedash import storage


@pytest.fixture(autouse=True)
def _force_sqlite_backend(monkeypatch):
    """Pin storage to SQLite for deterministic tests (see test_extraction_cache)."""
    monkeypatch.setattr(storage, "_using_postgres", lambda: False)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    storage.init_db(path)
    return path


def _seed_and_score(db_path, title="Role", url="https://example.com/job"):
    listing_id = storage._make_listing_id("arbeitnow", url)
    storage.upsert_listings(db_path, [{
        "id": listing_id,
        "source": "arbeitnow",
        "title": title,
        "company": "ACME GmbH",
        "location": "Berlin",
        "url": url,
        "description": "Python and SQL in Berlin.",
    }])
    storage.save_score(db_path, listing_id, 78, "3/4 skills - seniority fits")
    return listing_id


def test_count_unverified_zero_on_empty_db(db_path):
    assert storage.count_unverified(db_path) == 0


def test_count_unverified_tracks_scored_but_unverified_rows(db_path):
    _seed_and_score(db_path, title="A", url="https://example.com/a")
    assert storage.count_unverified(db_path) == 1
    # re-scoring re-enters the unverified pool (rule 38)
    listing_id = storage._make_listing_id("arbeitnow", "https://example.com/a")
    storage.save_score(db_path, listing_id, 90, "re-scored")
    assert storage.count_unverified(db_path) == 1


def test_mark_verified_clears_unverified_count(db_path):
    _seed_and_score(db_path, title="A", url="https://example.com/a")
    _seed_and_score(db_path, title="B", url="https://example.com/b")
    assert storage.count_unverified(db_path) == 2
    assert storage.mark_verified(db_path) == 2
    assert storage.count_unverified(db_path) == 0


def test_mark_verified_before_cutoff_only_marks_older_rows(db_path):
    _seed_and_score(db_path, title="A", url="https://example.com/a")
    # cut-off before any listing existed: nothing is eligible
    assert storage.mark_verified(db_path, before="2000-01-01T00:00:00") == 0
    assert storage.count_unverified(db_path) == 1
    # far-future cut-off verifies everything
    assert storage.mark_verified(db_path, before="2999-01-01T00:00:00") == 1
    assert storage.count_unverified(db_path) == 0


def test_failed_verification_leaves_verified_state_untouched(db_path):
    """Rule 38: a failing Verifier run must not overwrite prior verified state."""
    _seed_and_score(db_path, title="A", url="https://example.com/a")
    storage.mark_verified(db_path)

    # a later cycle produces new scored output, then FAILS verification:
    _seed_and_score(db_path, title="B", url="https://example.com/b")
    # (the orchestrator simply does NOT call mark_verified on the failure path)

    assert storage.count_unverified(db_path) == 1  # only B is unverified
    with storage.get_conn(db_path) as conn:
        row_a = conn.execute(
            "SELECT verified_at FROM listings WHERE title = 'A'"
        ).fetchone()
        row_b = conn.execute(
            "SELECT verified_at FROM listings WHERE title = 'B'"
        ).fetchone()
    assert row_a["verified_at"] is not None
    assert row_b["verified_at"] is None


def test_init_db_adds_verified_at_column_to_existing_table(db_path):
    """Simulate a pre-migration DB and confirm init_db upgrades it."""
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE listings DROP COLUMN verified_at")
    conn.commit()
    conn.close()

    storage.init_db(db_path)

    with storage.get_conn(db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()
        }
    assert "verified_at" in columns
    assert storage.count_unverified(db_path) == 0


def test_get_last_verifier_row_none_when_never_run(db_path):
    assert storage.get_last_verifier_row(db_path) is None


def test_get_last_verifier_row_returns_newest_verifier(db_path):
    now = datetime.now(timezone.utc)
    storage.log_cycle(db_path, agent="Scorer[abc]", started_at=now.isoformat(),
                      finished_at=now.isoformat(), records_touched=1, status="ok",
                      notes="Score: 42")
    storage.log_cycle(db_path, agent="Verifier", started_at=now.isoformat(),
                      finished_at=now.isoformat(), records_touched=0, status="ok",
                      notes="VERDICT: pass")
    storage.log_cycle(db_path, agent="Verifier", started_at=now.isoformat(),
                      finished_at=now.isoformat(), records_touched=0, status="ok",
                      notes="VERDICT: fail — score_spread observed 4.0")

    row = storage.get_last_verifier_row(db_path)
    assert row is not None
    assert row["agent"] == "Verifier"
    assert "VERDICT: fail" in row["notes"]