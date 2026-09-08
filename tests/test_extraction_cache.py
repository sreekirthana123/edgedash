"""Tests for extraction-failure caching and the retry cooldown window.

Covers the storage layer (failure sentinels in extraction_cache, no schema
change) and the extractor behaviour (skip inside the cooldown window, cache
transient failures, never cache quota errors).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from edgedash import storage
from edgedash.agents.extractor import ExtractionSkippedError, _hash_description, extract
from edgedash.llm import LLMError

VALID_FACTS = {
    "required_skills": ["python", "sql"],
    "nice_to_have": [],
    "seniority": "mid",
    "years_required": None,
    "remote_ok": None,
}


@pytest.fixture(autouse=True)
def _force_sqlite_backend(monkeypatch):
    """Pin the storage backend to SQLite for deterministic unit tests.

    The project .env may set DATABASE_URL (hosted Postgres for deployment);
    without this, real storage calls in tests would try to reach Postgres.
    """
    monkeypatch.setattr(storage, "_using_postgres", lambda: False)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    storage.init_db(path)
    return path


@pytest.fixture
def listing():
    return {"description": "<p>Python developer in Berlin. SQL, Tableau.</p>"}


@pytest.fixture
def config():
    return SimpleNamespace(
        llm_provider="gemini",
        llm_model="gemini-3.6-flash",
        extraction_retry_hours=24.0,
    )


def test_mark_failure_hides_from_cache_but_is_readable(db_path, listing):
    h = _hash_description(listing["description"])
    storage.mark_extraction_failed(db_path, h, "Gemini API timeout after 30s")
    assert storage.get_extraction_cache(db_path, h) is None
    failure = storage.get_extraction_failure(db_path, h)
    assert failure is not None
    assert failure["attempted_at"]
    assert "timeout" in failure["error_tail"]


def test_successful_cache_overwrites_failure_marker(db_path, listing):
    h = _hash_description(listing["description"])
    storage.mark_extraction_failed(db_path, h, "timeout")
    storage.set_extraction_cache(db_path, h, VALID_FACTS)
    assert storage.get_extraction_cache(db_path, h) == VALID_FACTS
    assert storage.get_extraction_failure(db_path, h) is None


def test_fresh_failure_skips_without_llm_call(db_path, listing, config):
    storage.mark_extraction_failed(db_path, _hash_description(listing["description"]), "timeout")
    with patch("edgedash.agents.extractor.llm.complete_json") as complete_json:
        with pytest.raises(ExtractionSkippedError):
            extract(listing, config, db_path)
        complete_json.assert_not_called()


def test_expired_failure_allows_retry_and_overwrites_marker(db_path, listing, config):
    old_attempt = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    storage.mark_extraction_failed(
        db_path, _hash_description(listing["description"]), "timeout", attempted_at=old_attempt
    )
    with patch(
        "edgedash.agents.extractor.llm.complete_json",
        return_value=dict(VALID_FACTS),
    ):
        result = extract(listing, config, db_path)
    assert result["required_skills"] == ["python", "sql"]
    assert storage.get_extraction_failure(db_path, _hash_description(listing["description"])) is None


def test_transient_error_is_cached_and_second_call_skips(db_path, listing, config):
    h = _hash_description(listing["description"])
    with patch(
        "edgedash.agents.extractor.llm.complete_json",
        side_effect=LLMError("Gemini API error: 503 UNAVAILABLE. {'error': {'code': 503}}"),
    ):
        with pytest.raises(LLMError):
            extract(listing, config, db_path)
    assert storage.get_extraction_failure(db_path, h) is not None

    with patch("edgedash.agents.extractor.llm.complete_json") as complete_json:
        with pytest.raises(ExtractionSkippedError):
            extract(listing, config, db_path)
        complete_json.assert_not_called()


def test_quota_error_is_not_cached(db_path, listing, config):
    h = _hash_description(listing["description"])
    with patch(
        "edgedash.agents.extractor.llm.complete_json",
        side_effect=LLMError(
            "Gemini API error: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"
        ),
    ):
        with pytest.raises(LLMError):
            extract(listing, config, db_path)
    assert storage.get_extraction_failure(db_path, h) is None


def test_default_cooldown_when_config_lacks_hours(db_path, listing):
    config = SimpleNamespace(llm_provider="gemini", llm_model="gemini-3.6-flash")
    storage.mark_extraction_failed(db_path, _hash_description(listing["description"]), "timeout")
    with patch("edgedash.agents.extractor.llm.complete_json") as complete_json:
        with pytest.raises(ExtractionSkippedError):
            extract(listing, config, db_path)
        complete_json.assert_not_called()