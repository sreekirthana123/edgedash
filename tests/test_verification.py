from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from edgedash.verification import (
    check_extraction_sanity,
    check_freshness,
    check_gap_sample_size,
    check_score_spread,
    run_all_checks,
)


def verification_config():
    return SimpleNamespace(
        min_spread=20.0,
        min_stdev=5.0,
        max_empty_extraction_pct=0.25,
        max_skills_per_listing=5,
        min_gap_sample=3,
        max_data_age_days=7,
    )


def test_score_spread_passes_for_varied_scores():
    result = check_score_spread([10, 30, 50, 70, 90], 20, 5)
    assert result.passed


def test_score_spread_fails_for_clustered_scores():
    result = check_score_spread([50, 51, 50, 49, 50], 20, 5)
    assert not result.passed


def test_score_spread_skips_fewer_than_five_scores():
    result = check_score_spread([10, 90], 20, 5)
    assert result.passed
    assert result.observed_value["skipped"] is True


def test_extraction_sanity_passes_with_few_empty_objects():
    result = check_extraction_sanity([{}, {"required_skills": ["python"]}], 0.5)
    assert result.passed


def test_extraction_sanity_fails_with_too_many_empty_objects():
    result = check_extraction_sanity([{}, {}, {"required_skills": ["python"]}], 0.5)
    assert not result.passed


def test_gap_sample_size_passes_for_supported_top_gap():
    result = check_gap_sample_size([{"listings_blocked": 3}], verification_config())
    assert result.passed


def test_gap_sample_size_fails_for_small_top_gap():
    result = check_gap_sample_size([{"listings_blocked": 2}], verification_config())
    assert not result.passed


def test_freshness_passes_for_recent_data():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    result = check_freshness(now - timedelta(days=2), verification_config(), now)
    assert result.passed


def test_freshness_fails_for_old_data():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    result = check_freshness(now - timedelta(days=8), verification_config(), now)
    assert not result.passed


def test_run_all_checks_passes_when_all_checks_pass():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    verdict = run_all_checks(
        [10, 30, 50, 70, 90],
        [{"required_skills": ["python"]}],
        [{"listings_blocked": 3}],
        now - timedelta(days=1),
        verification_config(),
        now,
    )
    assert verdict.passed
    assert len(verdict.checks) == 4


def test_run_all_checks_summary_names_failed_checks():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    verdict = run_all_checks(
        [50, 50, 50, 50, 50],
        [{}, {}, {"required_skills": ["python"]}],
        [{"listings_blocked": 1}],
        now - timedelta(days=8),
        verification_config(),
        now,
    )
    assert not verdict.passed
    assert "score_spread" in verdict.summary
    assert "gap_sample_size" in verdict.summary
    assert "freshness" in verdict.summary