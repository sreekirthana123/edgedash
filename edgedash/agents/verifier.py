"""Read-only Verifier agent for cycle plausibility checks."""

from datetime import datetime, timezone

from edgedash.agents.base import AgentResult
from edgedash.agents.extractor import _hash_description
from edgedash.verification import Verdict, run_all_checks


class Verifier:
    """Verify the current stored cycle without changing any stored data."""

    name = "Verifier"

    def run(self, config, storage_module, stop_conditions: dict = None) -> AgentResult:
        """Read cycle outputs, run checks, and return the resulting Verdict."""
        options = stop_conditions or {}
        listings = storage_module.get_listings(
            config.db_path, limit=10000, min_score=0
        )
        scores = [listing["fit_score"] for listing in listings]
        facts_list = []
        for listing in listings:
            description = listing.get("description") or ""
            facts = listing.get("extracted", {})
            if not facts and description:
                facts = storage_module.get_extraction_cache(
                    config.db_path, _hash_description(description)
                ) or {}
            facts_list.append(facts)

        gaps = storage_module.get_latest_gap_snapshots(config.db_path)
        latest_fetch_at = storage_module.last_fetch_time(config.db_path)
        now = options.get("now") or datetime.now(timezone.utc)
        latest_fetch = (
            datetime.fromisoformat(latest_fetch_at)
            if latest_fetch_at
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        verdict = run_all_checks(
            scores,
            facts_list,
            gaps,
            latest_fetch,
            config,
            now,
        )

        status = "ok" if verdict.passed else "failed"
        notes = _format_verdict_notes(verdict, config)

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=0,
            notes=notes,
            verdict=verdict,
        )


def _format_verdict_notes(verdict: Verdict, config) -> str:
    """Format the verdict and first failed check for cycle logging."""
    if verdict.passed:
        return "VERDICT: pass"

    failed = next(check for check in verdict.checks if not check.passed)
    observed = failed.observed_value
    if failed.check_name == "score_spread":
        observed_text = observed.get("spread", observed)
        minimum = config.min_spread
    elif failed.check_name == "extraction_sanity":
        observed_text = observed.get("empty_pct", observed)
        minimum = config.max_empty_extraction_pct
    elif failed.check_name == "gap_sample_size":
        observed_text = observed.get("top_sample", observed)
        minimum = config.min_gap_sample
    else:
        observed_text = observed.get("age_days", observed)
        minimum = config.max_data_age_days
    return f"VERDICT: fail — {failed.check_name} observed {observed_text} (min {minimum})"