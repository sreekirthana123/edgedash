"""Tests for the dashboard's current_verdict helper (views/dashboard.py).

The "Current verdict" metric must reflect the most recent Verifier row's
verdict, not whatever row happens to be newest in cycle_log overall.
"""

from views.dashboard import current_verdict


def _row(agent, status="ok", notes=""):
    return {"agent": agent, "status": status, "notes": notes}


def test_empty_log_returns_no_cycles():
    assert current_verdict([]) == "no cycles"


def test_no_verifier_row_returns_not_run():
    rows = [_row("Scorer[abc123]", status="ok", notes="Score: 42")]
    assert current_verdict(rows) == "not_run"


def test_no_verifier_row_but_fallback_pass_returns_pass():
    """Fallback: recent slice has no Verifier, but an earlier pass exists."""
    rows = [_row("Scorer[abc123]", status="ok", notes="Score: 42")]
    fallback = _row("Verifier", status="ok", notes="VERDICT: pass")
    assert current_verdict(rows, fallback) == "pass"


def test_no_verifier_row_but_fallback_fail_returns_fail():
    rows = [_row("Scorer[quota]", status="failed", notes="API quota exhausted")]
    fallback = _row("Verifier", status="failed", notes="VERDICT: fail — score_spread")
    assert current_verdict(rows, fallback) == "fail"


def test_recent_verifier_takes_precedence_over_fallback():
    """A recent Verifier row wins over an older fallback."""
    rows = [_row("Verifier", status="ok", notes="VERDICT: fail — freshness observed")]
    fallback = _row("Verifier", status="ok", notes="VERDICT: pass")
    assert current_verdict(rows, fallback) == "fail"


def test_verdict_from_notes_pass():
    rows = [
        _row("Scorer[abc123]", status="ok", notes="Score: 42"),
        _row("Verifier", status="ok", notes="VERDICT: pass"),
    ]
    assert current_verdict(rows) == "pass"


def test_verdict_from_notes_fail():
    rows = [
        _row("Verifier", status="ok", notes="VERDICT: fail — score_spread observed 4.0"),
    ]
    assert current_verdict(rows) == "fail"


def test_verdict_falls_back_to_status_when_notes_unparsable():
    rows = [_row("Verifier", status="failed", notes="some raw error")]
    assert current_verdict(rows) == "fail"


def test_verdict_prefers_latest_verifier_row():
    rows = [
        _row("Verifier", status="ok", notes="VERDICT: pass"),
        _row("Verifier", status="ok", notes="VERDICT: fail — freshness observed 8.0"),
        _row("Scorer[xyz]", status="ok", notes="Score: 50"),
    ]
    # newest-first ordering: the last Verifier row in the list is the most recent
    assert current_verdict(rows) == "pass"


def test_verdict_ignores_newest_non_verifier_row():
    rows = [
        _row("Scorer[quota]", status="failed", notes="API quota exhausted"),
        _row("Verifier", status="ok", notes="VERDICT: pass"),
    ]
    # even though the Scorer row is newest, the verdict comes from the Verifier
    assert current_verdict(rows) == "pass"


def test_verdict_unknown_status_returns_not_run():
    rows = [_row("Verifier", status="suspect", notes="")]
    assert current_verdict(rows) == "not_run"


def test_empty_log_returns_no_cycles_even_with_fallback():
    """A genuinely empty log still reads 'no cycles' regardless of fallback."""
    fallback = _row("Verifier", status="ok", notes="VERDICT: pass")
    assert current_verdict([], fallback) == "no cycles"


# --- suspect-row summariser -------------------------------------------------

from views.dashboard import _summarize_suspect  # noqa: E402


def test_suspect_distribution_stats_get_human_summary():
    notes = "Distribution: count=8 min=35 max=42 mean=37 spread=7"
    summary = _summarize_suspect(notes)
    assert "Distribution:" not in summary
    assert "count=" not in summary
    assert "unusually similar" in summary
    assert "8 listings scored" in summary
    assert "7-point range" in summary


def test_suspect_without_parseable_stats_gets_generic_summary():
    summary = _summarize_suspect("something odd happened")
    assert "worth a second look" in summary
    assert "count=" not in summary


def test_suspect_extraction_notes_get_human_summary():
    summary = _summarize_suspect("Extraction pattern unusual: 40% empty")
    assert "extracted listing data" in summary
    assert "worth a second look" in summary