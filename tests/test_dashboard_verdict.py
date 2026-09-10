"""Tests for the dashboard's current_verdict helper (app.py).

The "Current verdict" metric must reflect the most recent Verifier row's
verdict, not whatever row happens to be newest in cycle_log overall.
"""

from app import current_verdict


def _row(agent, status="ok", notes=""):
    return {"agent": agent, "status": status, "notes": notes}


def test_empty_log_returns_no_cycles():
    assert current_verdict([]) == "no cycles"


def test_no_verifier_row_returns_not_run():
    rows = [_row("Scorer[abc123]", status="ok", notes="Score: 42")]
    assert current_verdict(rows) == "not_run"


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