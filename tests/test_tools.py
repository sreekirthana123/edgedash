from datetime import datetime, timezone
from unittest.mock import patch

from edgedash.query.tools import TOOLS, seniority_distribution


def test_seniority_distribution_shape_and_clamping():
    with patch(
        "edgedash.query.tools.storage.get_last_passing_cycle",
        return_value={"timestamp": "2026-09-05T00:00:00+00:00"},
    ), patch(
        "edgedash.query.tools.storage.get_seniority_distribution",
        return_value=[
            {"seniority": "mid", "listing_count": 4},
            {"seniority": "senior", "listing_count": 2},
        ],
    ) as read_distribution:
        result = seniority_distribution(
            999,
            db_path="test.db",
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert "seniority_distribution" in TOOLS
    assert isinstance(result["rows"], list)
    assert all(isinstance(row, dict) for row in result["rows"])
    assert result["summary"] == "Seniority breakdown over the last 90 days."
    assert read_distribution.call_args.args[1] == "2026-06-08T00:00:00+00:00"


def test_best_fit_resume_registered_and_profile_gated():
    assert "best_fit_resume" in TOOLS
    assert TOOLS["best_fit_resume"]["needs_profile"] is True


def test_best_fit_resume_is_pure_computation(monkeypatch):
    """The tool re-ranks with zero LLM calls — patched recompute, no llm module."""
    import edgedash.query.tools as tools_module

    assert not hasattr(tools_module, "llm")  # tools never import the LLM layer

    recorded = {}

    def fake_recompute(db_path, config, profile):
        recorded["args"] = (db_path, config, profile)
        return (
            [
                {
                    "id": 1,
                    "title": "Backend Engineer",
                    "company": "GlassFlow",
                    "fit_score": 80,
                    "fit_reason": "skills match",
                }
            ],
            [],
        )

    monkeypatch.setattr(
        "edgedash.query.tools.resume.recompute_panels", fake_recompute
    )
    profile = {"skills": ["python", "sql"], "seniority": "mid"}
    result = TOOLS["best_fit_resume"]["function"](
        5, db_path="test.db", profile=profile, config=object()
    )

    assert recorded["args"][0] == "test.db"
    assert recorded["args"][2] is profile
    assert result["rows"][0]["fit_score"] == 80
    assert "python" in result["summary"]
    assert "deterministic" in result["summary"]