"""Optional resume-upload feature: parse a resume and recompute panels.

Two capabilities, both session-only on the dashboard side:

1. parse_resume() — extracts {skills, seniority} from an uploaded file with
   exactly ONE Gemini call (PDF text via pypdf, images via vision), reusing
   the same JSON-structured-output pattern as the listing extractor.

2. recompute_panels() — re-ranks listings and skill gaps against the resume's
   skills using the EXISTING deterministic scoring formula and the GapAnalyzer's
   opportunity-cost calculation. Reads extraction_cache only; never calls the
   LLM per listing and never writes to the database.

Nothing here touches storage schema, the scheduler, or the scoring formula.
"""

import dataclasses
from typing import Any

from edgedash import storage
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.agents.extractor import _hash_description
from edgedash import llm as llm_module
from edgedash.scoring import score_listing
from edgedash.skills import canonical


RESUME_SCHEMA = {"skills": "list", "seniority": "string"}
SENIORITY_BANDS = ("junior", "mid", "senior", "lead")

_PROMPT_TEMPLATE = (
    "You are a resume parser. From the resume below, extract:\n"
    "1. \"skills\": the concrete technical/professional skills it lists or "
    "clearly demonstrates (tools, languages, frameworks, domains). Max 30 "
    "entries, each 1-4 words, e.g. \"python\", \"incident response\".\n"
    "2. \"seniority\": the overall experience level, exactly one of "
    "\"junior\", \"mid\", \"senior\", \"lead\". Use \"unknown\" only if "
    "genuinely unclear.\n"
    "Respond ONLY with JSON: {{\"skills\": [\"...\"], \"seniority\": \"...\"}}\n\n"
    "RESUME:\n{body}"
)

_MAX_RESUME_CHARS = 15000


def extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes. Raises ValueError if no text layer."""
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - guarded by requirements
        raise ValueError("PDF support requires the pypdf package") from error

    import io

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as error:
        raise ValueError(f"Could not read PDF: {error}") from error

    text = "\n".join(pages).strip()
    if not text:
        raise ValueError(
            "This PDF has no extractable text (likely a scan). "
            "Please upload a text-based PDF or an image instead."
        )
    return text[:_MAX_RESUME_CHARS]


def _normalize_seniority(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    return lowered if lowered in SENIORITY_BANDS else "unknown"


def _normalize_skills(raw: Any, config) -> list[str]:
    aliases = getattr(config, "skill_aliases", {})
    seen: set[str] = set()
    skills: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = canonical(str(item).strip(), aliases)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            skills.append(name)
    return skills[:30]


def parse_resume(file_bytes: bytes, mime: str, config) -> dict:
    """Parse an uploaded resume into {skills, seniority} with ONE Gemini call.

    PDFs are text-extracted locally, then sent as one text call. Images go as
    one multimodal (vision) call. Raises ValueError for unreadable files and
    LLMError for API failures — callers are expected to handle both.
    """
    mime = (mime or "").lower()
    if mime == "application/pdf":
        body = extract_pdf_text(file_bytes)
        prompt = _PROMPT_TEMPLATE.format(body=body)
        raw = llm_module.complete_json(prompt, RESUME_SCHEMA, config, timeout=60)
    elif mime.startswith("image/"):
        prompt = _PROMPT_TEMPLATE.format(body="(see attached image)")
        raw = llm_module.complete_json_image(
            prompt,
            RESUME_SCHEMA,
            config,
            image_bytes=file_bytes,
            image_mime=mime,
            timeout=60,
        )
    else:
        raise ValueError(f"Unsupported resume type: {mime or 'unknown'}")

    return {
        "skills": _normalize_skills(raw.get("skills"), config),
        "seniority": _normalize_seniority(raw.get("seniority")),
    }


def _load_scored_with_facts(db_path: str) -> list[dict]:
    """Scored listings with cached extraction facts attached (no LLM calls).

    Mirrors the GapAnalyzer's fact-loading pattern: description -> hash ->
    extraction_cache. Listings without cached facts are skipped — they have
    nothing to re-rank against.
    """
    scored = storage.get_listings(db_path, limit=10000, min_score=0)
    result = []
    for listing in scored:
        description = listing.get("description", "")
        facts = None
        if description:
            facts = storage.get_extraction_cache(db_path, _hash_description(description))
        if not facts:
            continue
        listing["extracted"] = facts
        result.append(listing)
    return result


def recompute_panels(db_path: str, config, profile: dict) -> tuple[list[dict], list[dict]]:
    """Recompute the two ranked panels against a resume profile.

    Uses the existing deterministic scoring formula and the GapAnalyzer's
    opportunity-cost calculation with the resume's skills/seniority. Pure
    computation: reads extraction_cache, writes nothing.

    Returns (listings, gaps), each sorted best-first, max 10 rows.
    """
    resume_config = dataclasses.replace(
        config,
        my_skills=list(profile.get("skills", [])),
        target_seniority=profile.get("seniority", "unknown"),
    )

    scored = _load_scored_with_facts(db_path)

    # Re-rank listings with the SAME formula, different inputs.
    # Mirrors the default panel's behavior: top 10 by score, no floor —
    # with a narrow resume the configured min_fit_score could empty the
    # panel entirely, and the score is shown anyway.
    rescored = []
    for listing in scored:
        result = score_listing(listing["extracted"], resume_config)
        # Write the resume-based score back so the gap analysis below
        # measures opportunity cost against the RESUME's fit, not the
        # stored config-based score.
        listing["fit_score"] = result["score"]
        rescored.append({
            "id": listing.get("id"),
            "title": listing.get("title", "-"),
            "company": listing.get("company", "-"),
            "fit_score": result["score"],
            "fit_reason": result["reason"],
        })
    rescored.sort(key=lambda row: row["fit_score"], reverse=True)

    # Same opportunity-cost calculation as GapAnalyzer, resume as "have" list.
    gap_dict = GapAnalyzer()._analyse_gaps(scored, resume_config)
    gaps = [
        {
            "skill": skill,
            "listings_blocked": data["listings_blocked"],
            "opportunity_cost": data["opportunity_cost"],
            "mean_score": data["mean_score"],
        }
        for skill, data in gap_dict.items()
    ]
    gaps.sort(key=lambda row: row["opportunity_cost"], reverse=True)

    return rescored[:10], gaps[:10]
