"""Ask-your-data wiring for the resume-aware best_fit_resume tool.

Guarantees under test:
- routing to best_fit_resume adds ZERO Gemini calls beyond ask()'s normal
  two (route + phrase) — the re-ranking is pure computation over cached
  extraction facts;
- asking a resume question with no resume loaded returns an honest
  "no resume loaded" answer without spending the phrasing call.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from edgedash.query.ask import ask

ROUTE = {"tool": "best_fit_resume", "params": {"n": 5}, "confidence": "high"}
PHRASE = {"text": "Here are the best-fit roles for your resume."}


def _patch_config(monkeypatch):
    fake = SimpleNamespace(db_path="test.db", daily_query_cap=200)
    monkeypatch.setattr(
        "edgedash.config.Config.load", staticmethod(lambda *a, **k: fake)
    )
    return fake


def _patch_storage(monkeypatch):
    monkeypatch.setattr("edgedash.query.ask.storage.init_db", lambda *_: None)
    monkeypatch.setattr(
        "edgedash.query.ask.storage.count_queries_today", lambda *_: 0
    )
    log = MagicMock()
    monkeypatch.setattr("edgedash.query.ask.storage.log_query", log)
    return log


def _patch_llm(monkeypatch, responses):
    complete = MagicMock(side_effect=responses)
    monkeypatch.setattr("edgedash.query.ask.llm.complete_json", complete)
    return complete


def test_resume_question_costs_only_the_normal_two_calls(monkeypatch):
    _patch_config(monkeypatch)
    log = _patch_storage(monkeypatch)
    complete = _patch_llm(monkeypatch, [ROUTE, PHRASE])
    recompute = MagicMock(
        return_value=(
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
    )
    monkeypatch.setattr(
        "edgedash.query.tools.resume.recompute_panels", recompute
    )

    profile = {"skills": ["python"], "seniority": "mid"}
    answer = ask(
        "Find the best-fit roles from my resume", [], resume_profile=profile
    )

    assert complete.call_count == 2  # route + phrase, nothing extra
    assert answer.tool_used == "best_fit_resume"
    assert answer.rows[0]["fit_score"] == 80
    # Profile reaches the tool server-side, positional arg 3 of recompute.
    assert recompute.call_args.args[2] is profile
    assert log.call_args.args[4] is True  # logged as successful


def test_resume_question_without_resume_is_honest_and_cheap(monkeypatch):
    _patch_config(monkeypatch)
    log = _patch_storage(monkeypatch)
    complete = _patch_llm(monkeypatch, [ROUTE])  # route fires; phrasing must not

    answer = ask("Find the best-fit roles from my resume", [])

    assert complete.call_count == 1  # no phrasing call spent
    assert answer.tool_used is None
    assert "No resume" in answer.text
    assert "Analyze resume" in answer.text  # tells the user how to fix it
    assert log.call_args.args[4] is False  # logged as unsuccessful
