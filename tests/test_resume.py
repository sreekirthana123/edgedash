"""Tests for the optional resume-upload feature (edgedash/resume.py).

Scope: parsing normalization, one-Gemini-call guarantee, and the session-only
panel recompute over extraction_cache. No network access — the LLM is mocked.
"""

import contextlib
import dataclasses

import pytest

import views.dashboard as dashboard
from edgedash import resume, storage
from edgedash.agents.extractor import _hash_description
from edgedash.config import Config


@pytest.fixture(autouse=True)
def _force_sqlite_backend(monkeypatch):
    """Pin storage to SQLite for deterministic tests."""
    monkeypatch.setattr(storage, "_using_postgres", lambda: False)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "resume_test.db")
    storage.init_db(path)
    return path


@pytest.fixture
def config():
    return Config.load("config.yaml")


def _seed_listing(db_path, url, title, description, facts, fit_score=70):
    listing_id = storage._make_listing_id("arbeitnow", url)
    storage.upsert_listings(db_path, [{
        "id": listing_id,
        "source": "arbeitnow",
        "title": title,
        "company": "ACME GmbH",
        "location": "Berlin",
        "url": url,
        "description": description,
    }])
    storage.set_extraction_cache(db_path, _hash_description(description), facts)
    storage.save_score(db_path, listing_id, fit_score, "seeded")
    return listing_id


# ---------- seniority / skill normalization ----------


def test_normalize_seniority_accepts_known_bands():
    for band in ("junior", "mid", "senior", "lead"):
        assert resume._normalize_seniority(band.upper()) == band


def test_normalize_seniority_maps_unknown_to_unknown():
    assert resume._normalize_seniority("wizard") == "unknown"
    assert resume._normalize_seniority(None) == "unknown"


def test_normalize_skills_canonicalizes_and_dedupes(config):
    config = dataclasses.replace(
        config, skill_aliases={"k8s": "kubernetes", "ml": "machine learning"}
    )
    skills = resume._normalize_skills(
        ["K8s", "kubernetes", " Python ", "ml", "", "python"], config
    )
    assert skills == ["kubernetes", "python", "machine learning"]


def test_normalize_skills_caps_at_thirty(config):
    skills = resume._normalize_skills([f"skill{i}" for i in range(50)], config)
    assert len(skills) == 30


def test_normalize_skills_ignores_non_list_input(config):
    assert resume._normalize_skills("python", config) == []


# ---------- parse_resume: exactly ONE LLM call ----------


def test_parse_resume_makes_exactly_one_llm_call(monkeypatch, config):
    calls = []

    def fake_complete_json(prompt, schema, cfg, timeout=30):
        calls.append(1)
        return {"skills": ["python", "sql"], "seniority": "senior"}

    # Bypass real PDF parsing; the ONE-call guarantee is what's under test.
    monkeypatch.setattr(resume, "extract_pdf_text", lambda data: "resume text")
    monkeypatch.setattr("edgedash.llm.complete_json", fake_complete_json)
    result = resume.parse_resume(b"fake pdf bytes", "application/pdf", config)

    assert len(calls) == 1  # ONE Gemini call, never more
    assert result["skills"] == ["python", "sql"]
    assert result["seniority"] == "senior"


def test_parse_resume_image_uses_vision_path(monkeypatch, config):
    calls = []

    def fake_complete_json_image(prompt, schema, cfg, image_bytes, image_mime, timeout=60):
        calls.append(image_mime)
        return {"skills": ["incident response"], "seniority": "mid"}

    monkeypatch.setattr("edgedash.llm.complete_json_image", fake_complete_json_image)
    result = resume.parse_resume(b"png", "image/png", config)

    assert calls == ["image/png"]
    assert result == {"skills": ["incident response"], "seniority": "mid"}


def test_parse_resume_rejects_unsupported_type(config):
    with pytest.raises(ValueError, match="Unsupported resume type"):
        resume.parse_resume(b"data", "application/zip", config)


def test_parse_resume_bad_seniority_becomes_unknown(monkeypatch, config):
    monkeypatch.setattr(resume, "extract_pdf_text", lambda data: "resume text")
    monkeypatch.setattr(
        "edgedash.llm.complete_json",
        lambda *a, **k: {"skills": ["python"], "seniority": "CEO-level"},
    )
    result = resume.parse_resume(b"x", "application/pdf", config)
    assert result["seniority"] == "unknown"


def test_extract_pdf_text_rejects_garbage():
    with pytest.raises(ValueError):
        resume.extract_pdf_text(b"this is not a pdf at all")


# ---------- recompute_panels: session-only recompute ----------


def test_load_scored_with_facts_skips_uncached_listings(db_path, config):
    facts = {"required_skills": ["python"], "seniority": "mid"}
    _seed_listing(db_path, "https://x.com/1", "Cached", "python role", facts)
    _seed_listing(db_path, "https://x.com/2", "NoCache", "no cache entry", None)

    loaded = resume._load_scored_with_facts(db_path)

    assert len(loaded) == 1
    assert loaded[0]["title"] == "Cached"
    assert loaded[0]["extracted"] == facts


def test_recompute_panels_matches_deterministic_formula(db_path, config):
    facts = {
        "required_skills": ["python", "sql", "docker"],
        "seniority": "senior",
        "location": "Berlin",
        "remote_ok": False,
        "years_required": 3,
    }
    _seed_listing(db_path, "https://x.com/1", "Role A", "desc one", facts, fit_score=55)
    profile = {"skills": ["python", "sql"], "seniority": "senior"}

    listings, _ = resume.recompute_panels(db_path, config, profile)

    from edgedash.scoring import score_listing

    expected_config = dataclasses.replace(
        config, my_skills=["python", "sql"], target_seniority="senior"
    )
    assert len(listings) == 1
    row = listings[0]
    assert row["fit_score"] == score_listing(facts, expected_config)["score"]
    assert row["fit_score"] != 55  # recomputed, not the stored config score
    assert row["title"] == "Role A"


def test_recompute_panels_gaps_use_resume_as_have_list(db_path, config):
    facts = {"required_skills": ["python", "kubernetes"], "seniority": "mid"}
    _seed_listing(db_path, "https://x.com/1", "Role A", "desc", facts)
    profile = {"skills": ["python"], "seniority": "mid"}

    _, gaps = resume.recompute_panels(db_path, config, profile)

    gap_skills = [g["skill"] for g in gaps]
    assert "kubernetes" in gap_skills   # missing from resume -> a gap
    assert "python" not in gap_skills   # in resume -> never a gap


def test_recompute_panels_never_writes_to_database(db_path, config):
    facts = {"required_skills": ["python"], "seniority": "mid"}
    listing_id = _seed_listing(
        db_path, "https://x.com/1", "Role A", "desc", facts, fit_score=80
    )
    profile = {"skills": ["go", "rust"], "seniority": "lead"}

    resume.recompute_panels(db_path, config, profile)

    # The stored listing keeps its config-based score — nothing persisted.
    stored = {r["id"]: r for r in storage.get_listings(db_path, limit=100, min_score=0)}
    assert stored[listing_id]["fit_score"] == 80


def test_recompute_panels_caps_results_at_ten(db_path, config):
    facts = {"required_skills": ["python"], "seniority": "mid"}
    for i in range(14):
        _seed_listing(db_path, f"https://x.com/{i}", f"Role {i}", f"desc {i}", facts)
    profile = {"skills": ["python"], "seniority": "mid"}

    listings, gaps = resume.recompute_panels(db_path, config, profile)

    assert len(listings) <= 10
    assert len(gaps) <= 10


def test_recompute_panels_empty_database_returns_empty(db_path, config):
    listings, gaps = resume.recompute_panels(
        db_path, config, {"skills": ["python"], "seniority": "mid"}
    )
    assert listings == []
    assert gaps == []


# ---------- dashboard upload flow: explicit "Analyze resume" button ----------


class _Rerun(Exception):
    """Sentinel mirroring Streamlit's RerunException."""


class _FakeUpload:
    def __init__(self, name="report.pdf", size=1234, data=b"data",
                 type="application/pdf"):
        self.name = name
        self.size = size
        self.type = type
        self._data = data

    def getvalue(self):
        return self._data


class _FakeSt:
    """Minimal stand-in for the streamlit calls used by the resume section."""

    def __init__(self, uploaded, button_return):
        self.session_state = {}
        self.uploaded = uploaded
        self.button_return = button_return
        self.captions = []
        self.errors = []
        self.successes = []
        self.rerun_called = False

    def file_uploader(self, *args, **kwargs):
        return self.uploaded

    def button(self, *args, **kwargs):
        return self.button_return

    def caption(self, text=""):
        self.captions.append(text)

    def success(self, text):
        self.successes.append(text)

    def error(self, text):
        self.errors.append(text)

    def spinner(self, *args, **kwargs):
        return contextlib.nullcontext()

    def rerun(self):
        self.rerun_called = True
        raise _Rerun()


def _patch_dashboard_st(monkeypatch, fake):
    import streamlit as st_module

    mapping = {
        "file_uploader": fake.file_uploader,
        "button": fake.button,
        "caption": fake.caption,
        "success": fake.success,
        "error": fake.error,
        "spinner": fake.spinner,
        "rerun": fake.rerun,
        "session_state": fake.session_state,
    }
    for name, value in mapping.items():
        monkeypatch.setattr(st_module, name, value)


def test_upload_without_button_click_makes_zero_llm_calls(monkeypatch, config):
    calls = []

    def fake_complete_json(*args, **kwargs):
        calls.append(1)
        return {"skills": ["python"], "seniority": "mid"}

    monkeypatch.setattr("edgedash.llm.complete_json", fake_complete_json)
    fake = _FakeSt(_FakeUpload(), button_return=False)
    _patch_dashboard_st(monkeypatch, fake)

    result = dashboard._render_resume_section(config)

    assert calls == []  # selecting a file must NOT fire the Gemini parse
    assert result is None  # falls back to configured-skills mode
    assert "resume_profile" not in fake.session_state


def test_failed_parse_retries_with_exactly_one_additional_call(monkeypatch, config):
    calls = []

    def flaky_complete_json(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("503 transient")
        return {"skills": ["python"], "seniority": "mid"}

    monkeypatch.setattr("edgedash.llm.complete_json", flaky_complete_json)
    monkeypatch.setattr(resume, "extract_pdf_text", lambda data: "resume text")
    fake = _FakeSt(_FakeUpload(), button_return=True)
    _patch_dashboard_st(monkeypatch, fake)

    # First click: transient Gemini failure — error shown, nothing stored.
    dashboard._render_resume_section(config)
    assert len(calls) == 1
    assert "resume_profile" not in fake.session_state
    assert fake.errors  # the user sees why it failed and can retry

    # Second click: the retry succeeds — exactly ONE additional call.
    with pytest.raises(_Rerun):
        dashboard._render_resume_section(config)
    assert len(calls) == 2
    assert fake.session_state["resume_profile"]["skills"] == ["python"]
    assert fake.session_state["resume_key"] == "report.pdf:1234"

