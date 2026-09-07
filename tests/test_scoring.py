import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from edgedash.scoring import (
    score_listing,
    _score_skills_match,
    _score_seniority_match,
    _score_location_match,
    _score_recency,
)


@pytest.fixture
def mock_config():
    """Mock config with scoring parameters."""
    config = Mock()
    config.my_skills = ["python", "sql", "tableau", "excel"]
    config.target_seniority = "mid"
    config.target_city = "Berlin"
    config.score_weights = {
        "skills_match": 0.35,
        "seniority_match": 0.25,
        "location_match": 0.20,
        "recency": 0.20,
    }
    return config


class TestSkillsMatch:
    def test_perfect_match(self):
        """All required skills match."""
        required = ["python", "sql"]
        my_skills = ["python", "sql", "excel"]
        score = _score_skills_match(required, my_skills)
        assert score == 1.0

    def test_partial_match(self):
        """Half of required skills match."""
        required = ["python", "java", "sql", "rust"]
        my_skills = ["python", "sql"]
        score = _score_skills_match(required, my_skills)
        assert score == 0.5

    def test_zero_match(self):
        """No required skills match."""
        required = ["rust", "go", "erlang"]
        my_skills = ["python", "sql", "javascript"]
        score = _score_skills_match(required, my_skills)
        assert score == 0.0

    def test_empty_required_skills(self):
        """No required skills listed — return neutral 0.5."""
        required = []
        my_skills = ["python", "sql"]
        score = _score_skills_match(required, my_skills)
        assert score == 0.5

    def test_case_insensitive(self):
        """Skill matching is case insensitive."""
        required = ["Python", "SQL"]
        my_skills = ["python", "sql", "excel"]
        score = _score_skills_match(required, my_skills)
        assert score == 1.0


class TestSeniorityMatch:
    def test_exact_match(self):
        """Listing seniority matches target."""
        score = _score_seniority_match("mid", "mid")
        assert score == 1.0

    def test_one_band_away(self):
        """One band of seniority away: junior->mid, mid->senior, etc."""
        assert _score_seniority_match("junior", "mid") == 0.6
        assert _score_seniority_match("mid", "senior") == 0.6
        assert _score_seniority_match("senior", "mid") == 0.6

    def test_two_bands_away(self):
        """Two bands away."""
        assert _score_seniority_match("junior", "senior") == 0.25
        assert _score_seniority_match("mid", "lead") == 0.25

    def test_three_bands_away(self):
        """Three or more bands away."""
        score = _score_seniority_match("junior", "lead")
        assert score == 0.0

    def test_unknown_listing(self):
        """Unknown seniority in listing."""
        score = _score_seniority_match("unknown", "mid")
        assert score == 0.5

    def test_unknown_target(self):
        """Unknown seniority in target."""
        score = _score_seniority_match("mid", "unknown")
        assert score == 0.5


class TestLocationMatch:
    def test_remote_allowed(self):
        """Remote OK always scores 1.0."""
        score = _score_location_match("New York", "Berlin", remote_ok=True)
        assert score == 1.0

    def test_city_match(self):
        """Exact city match."""
        score = _score_location_match("Berlin, Germany", "Berlin", remote_ok=False)
        assert score == 1.0

    def test_city_match_case_insensitive(self):
        """City match is case insensitive."""
        score = _score_location_match("BERLIN, GERMANY", "berlin", remote_ok=False)
        assert score == 1.0

    def test_different_city_not_remote(self):
        """Different city, not remote."""
        score = _score_location_match("London, UK", "Berlin", remote_ok=False)
        assert score == 0.1

    def test_unknown_location(self):
        """Unknown location."""
        score = _score_location_match(None, "Berlin", remote_ok=None)
        assert score == 0.5

    def test_unknown_remote_status(self):
        """Unknown remote status but city match."""
        score = _score_location_match("Berlin", "Berlin", remote_ok=None)
        assert score == 1.0


class TestRecency:
    def test_posted_today(self):
        """Posted today scores close to 1.0."""
        # Fixed to timezone-aware UTC datetime format
        now = datetime.now(timezone.utc).replace(microsecond=0)
        posted_at = now.isoformat()
        score = _score_recency(posted_at)
        assert score >= 0.98

    def test_posted_15_days_ago(self):
        """Posted 15 days ago should be ~0.5."""
        now = datetime.now(timezone.utc)
        posted_dt = now - timedelta(days=15)
        posted_at = posted_dt.isoformat()
        score = _score_recency(posted_at)
        assert 0.48 < score < 0.52

    def test_posted_30_days_ago(self):
        """Posted 30 days ago scores ~0.0."""
        now = datetime.now(timezone.utc)
        posted_dt = now - timedelta(days=30)
        posted_at = posted_dt.isoformat()
        score = _score_recency(posted_at)
        assert score <= 0.02

    def test_posted_more_than_30_days_ago(self):
        """Posted >30 days ago scores 0.0."""
        now = datetime.now(timezone.utc)
        posted_dt = now - timedelta(days=45)
        posted_at = posted_dt.isoformat()
        score = _score_recency(posted_at)
        assert score == 0.0

    def test_null_posted_at(self):
        """Null posted_at returns neutral 0.5."""
        score = _score_recency(None)
        assert score == 0.5

    def test_invalid_posted_at(self):
        """Invalid posted_at format returns neutral 0.5."""
        score = _score_recency("not-a-date")
        assert score == 0.5


class TestFullScoreListing:
    def test_perfect_match(self, mock_config):
        """Perfect fit: all skills, correct seniority, right city, posted today."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        facts = {
            "required_skills": ["python", "sql"],
            "seniority": "mid",
            "location": "Berlin",
            "remote_ok": False,
            "posted_at": now.isoformat(),
        }
        result = score_listing(facts, mock_config)

        assert result["score"] == 100
        assert result["reason"]
        assert result["components"]["skills_match"] == 1.0
        assert result["components"]["seniority_match"] == 1.0

    def test_zero_match(self, mock_config):
        """Zero fit: no skills, wrong seniority, wrong city, old job."""
        old_dt = datetime.now(timezone.utc) - timedelta(days=35)
        facts = {
            "required_skills": ["rust", "go"],
            "seniority": "lead",
            "location": "Tokyo",
            "remote_ok": False,
            "posted_at": old_dt.isoformat(),
        }
        result = score_listing(facts, mock_config)

        assert result["score"] <= 15
        assert result["reason"]

    def test_empty_required_skills(self, mock_config):
        """Empty required skills list."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        facts = {
            "required_skills": [],
            "seniority": "mid",
            "location": "Berlin",
            "remote_ok": True,
            "posted_at": now.isoformat(),
        }
        result = score_listing(facts, mock_config)

        assert 80 <= result["score"] <= 85

    def test_null_posted_at(self, mock_config):
        """Null posted_at should not crash."""
        facts = {
            "required_skills": ["python"],
            "seniority": "mid",
            "location": "Berlin",
            "remote_ok": False,
            "posted_at": None,
        }
        result = score_listing(facts, mock_config)

        assert 0 <= result["score"] <= 100
        assert result["reason"]

    def test_null_remote_ok(self, mock_config):
        """Null remote_ok should not crash."""
        facts = {
            "required_skills": ["python"],
            "seniority": "mid",
            "location": "Berlin",
            "remote_ok": None,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        result = score_listing(facts, mock_config)

        assert 0 <= result["score"] <= 100
        assert result["reason"]

    def test_seniority_three_bands_off(self, mock_config):
        """Seniority two bands away (mid vs lead = 0.25)."""
        facts = {
            "required_skills": ["python"],
            "seniority": "lead",
            "location": "Berlin",
            "remote_ok": False,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        result = score_listing(facts, mock_config)

        assert result["components"]["seniority_match"] == 0.25
        assert result["score"] <= 85

    def test_reason_includes_gaps(self, mock_config):
        """Reason should include skill gaps."""
        facts = {
            "required_skills": ["rust", "go", "python"],
            "seniority": "mid",
            "location": "Berlin",
            "remote_ok": False,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        result = score_listing(facts, mock_config)

        reason = result["reason"]
        assert "gap:" in reason or "skills" in reason
