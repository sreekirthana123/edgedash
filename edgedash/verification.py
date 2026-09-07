"""Pure plausibility checks for cycle outputs."""

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    """Result of one verification plausibility check."""

    check_name: str
    passed: bool
    observed_value: Any
    reason: str


@dataclass(frozen=True)
class Verdict:
    """Final verdict for all plausibility checks in a cycle."""

    summary: str
    passed: bool
    checks: tuple[CheckResult, ...]


def check_score_spread(
    scores: list[float], min_spread: float, min_stdev: float
) -> CheckResult:
    """Check that scores are not implausibly flat or tightly clustered."""
    if len(scores) < 5:
        return CheckResult(
            check_name="score_spread",
            passed=True,
            observed_value={"count": len(scores), "skipped": True},
            reason="Skipped because fewer than 5 scores were produced.",
        )

    spread = max(scores) - min(scores)
    stdev = pstdev(scores)
    observed_value = {
        "count": len(scores),
        "spread": spread,
        "stdev": stdev,
    }

    if spread < min_spread or stdev < min_stdev:
        return CheckResult(
            check_name="score_spread",
            passed=False,
            observed_value=observed_value,
            reason=(
                f"Score distribution is too flat or clustered: spread={spread:.3f} "
                f"(minimum {min_spread}), stdev={stdev:.3f} "
                f"(minimum {min_stdev})."
            ),
        )

    return CheckResult(
        check_name="score_spread",
        passed=True,
        observed_value=observed_value,
        reason="Score distribution has sufficient spread and variation.",
    )


def check_extraction_sanity(
    facts_list: list[dict],
    max_empty_pct: float,
    max_skills_per_listing: int | None = None,
) -> CheckResult:
    """Check extraction emptiness and, when configured, skill-list shape."""
    empty_count = sum(1 for facts in facts_list if not facts)
    total_count = len(facts_list)
    empty_pct = empty_count / total_count if total_count else 0.0
    oversized_count = 0
    if max_skills_per_listing is not None:
        oversized_count = sum(
            1
            for facts in facts_list
            if len(facts.get("required_skills", [])) > max_skills_per_listing
            or len(facts.get("nice_to_have", [])) > max_skills_per_listing
        )
    observed_value = {
        "total": total_count,
        "empty": empty_count,
        "empty_pct": empty_pct,
        "oversized_skill_lists": oversized_count,
    }

    if empty_pct > max_empty_pct or oversized_count:
        reasons = []
        if empty_pct > max_empty_pct:
            reasons.append(
                f"too many empty extraction results: {empty_pct:.1%} "
                f"(maximum {max_empty_pct:.1%})"
            )
        if oversized_count:
            reasons.append(
                f" {oversized_count} listing(s) exceed the maximum skill-list "
                f"size of {max_skills_per_listing}"
            )
        reason = "Extraction sanity failed: " + "; ".join(reasons) + "."
        return CheckResult(
            check_name="extraction_sanity",
            passed=False,
            observed_value=observed_value,
            reason=reason,
        )

    return CheckResult(
        check_name="extraction_sanity",
        passed=True,
        observed_value=observed_value,
        reason=(
            f"Empty extraction results are within the allowed limit: "
            f"{empty_pct:.1%} (maximum {max_empty_pct:.1%})."
        ),
    )


def check_gap_sample_size(gaps: list[dict], config: Any) -> CheckResult:
    """Check that the top gap is supported by enough listings."""
    min_gap_sample = config.min_gap_sample
    top_sample = gaps[0].get("listings_blocked", 0) if gaps else 0
    observed_value = {
        "gap_count": len(gaps),
        "top_sample": top_sample,
        "min_gap_sample": min_gap_sample,
    }
    passed = top_sample >= min_gap_sample
    reason = (
        f"Top gap has {top_sample} listings; minimum is {min_gap_sample}."
        if not passed
        else f"Top gap meets the minimum sample size of {min_gap_sample} listings."
    )
    return CheckResult("gap_sample_size", passed, observed_value, reason)


def check_freshness(
    latest_fetch_at: datetime, config: Any, now: datetime
) -> CheckResult:
    """Check that fetched data is no older than the configured maximum age."""
    if latest_fetch_at.tzinfo is None:
        latest_fetch_at = latest_fetch_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_days = (now - latest_fetch_at).total_seconds() / 86400
    max_data_age_days = config.max_data_age_days
    passed = age_days <= max_data_age_days
    observed_value = {
        "age_days": age_days,
        "max_data_age_days": max_data_age_days,
    }
    reason = (
        f"Data is {age_days:.2f} days old; maximum is {max_data_age_days} days."
    )
    return CheckResult("freshness", passed, observed_value, reason)


def run_all_checks(
    scores: list[float],
    facts_list: list[dict],
    gaps: list[dict],
    latest_fetch_at: datetime,
    config: Any,
    now: datetime,
) -> Verdict:
    """Run every verification check and combine the resulting verdict."""
    checks = (
        check_score_spread(scores, config.min_spread, config.min_stdev),
        check_extraction_sanity(
            facts_list,
            config.max_empty_extraction_pct,
            config.max_skills_per_listing,
        ),
        check_gap_sample_size(gaps, config),
        check_freshness(latest_fetch_at, config, now),
    )
    failed_checks = tuple(check for check in checks if not check.passed)
    if failed_checks:
        summary = "Verification failed: " + "; ".join(
            f"{check.check_name}: {check.reason}" for check in failed_checks
        )
    else:
        summary = "Verification passed: all plausibility checks passed."
    return Verdict(summary=summary, passed=not failed_checks, checks=checks)
