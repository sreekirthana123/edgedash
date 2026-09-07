"""Fixed, parameterised query tools for the natural-language router."""

from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

from edgedash import storage
from edgedash.agents.extractor import _hash_description
from edgedash.skills import canonical


TOOLS: dict[str, dict[str, Any]] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable:
    """Register a deterministic query function and its router metadata."""
    def decorator(function: Callable) -> Callable:
        TOOLS[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "function": function,
        }
        return wraps(function)(function)

    return decorator


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    """Convert untrusted input to an integer inside an inclusive range."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _verified_cutoff(db_path: str) -> str | None:
    """Return the latest passing cycle timestamp used as the data cutoff."""
    passing = storage.get_last_passing_cycle(db_path)
    return passing.get("timestamp") if passing else None


@tool(
    name="companies_hiring",
    description=(
        "Use when the user asks which companies posted job listings recently. "
        "Returns company names and listing counts for the last N days, "
        "restricted to the last passing cycle."
    ),
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "default": 7,
                "description": "Number of recent days to inspect.",
            }
        },
        "additionalProperties": False,
    },
)
def companies_hiring(
    days: int = 7,
    *,
    db_path: str = "edgedash.db",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return companies with listings posted in the clamped recent window."""
    days = _clamp_int(days, 1, 90, 7)
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    cutoff = _verified_cutoff(db_path)
    rows = storage.get_listings_posted_since(db_path, since, cutoff)
    total = sum(row["listing_count"] for row in rows)
    return {
        "rows": rows,
        "summary": f"{total} listings from the last {days} days across {len(rows)} companies.",
    }


@tool(
    name="seniority_distribution",
    description=(
        "Use when the user asks for the seniority or experience-level breakdown "
        "of recent job listings. Returns counts grouped by seniority from the "
        "last passing cycle over the requested number of days."
    ),
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "default": 30,
                "description": "Number of recent days to inspect.",
            }
        },
        "additionalProperties": False,
    },
)
def seniority_distribution(
    days: int = 30,
    *,
    db_path: str = "edgedash.db",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return seniority counts for listings in the clamped recent window."""
    days = _clamp_int(days, 1, 90, 30)
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    cutoff = _verified_cutoff(db_path)
    rows = storage.get_seniority_distribution(db_path, since, cutoff)
    return {
        "rows": rows,
        "summary": f"Seniority breakdown over the last {days} days.",
    }


@tool(
    "best_matches",
    "Use when the user asks for the highest-scoring or best matching listings.",
    {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10}}, "additionalProperties": False},
)
def best_matches(n: int = 10, *, db_path: str = "edgedash.db") -> dict[str, Any]:
    n = _clamp_int(n, 1, 25, 10)
    rows = storage.get_best_matches_at_cutoff(db_path, _verified_cutoff(db_path), n)
    return {"rows": rows, "summary": f"Top {n} scored listings from the last passing cycle."}


@tool(
    "top_gaps",
    "Use when the user asks for the most important or highest-cost skill gaps.",
    {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5}}, "additionalProperties": False},
)
def top_gaps(n: int = 5, *, db_path: str = "edgedash.db") -> dict[str, Any]:
    n = _clamp_int(n, 1, 25, 5)
    rows = storage.get_gaps_at_cutoff(db_path, _verified_cutoff(db_path))[:n]
    return {"rows": rows, "summary": f"Top {n} skill gaps from the last passing cycle."}


@tool(
    "gap_detail",
    "Use when the user asks which listings are blocked by one named skill gap.",
    {"type": "object", "properties": {"skill": {"type": "string"}}, "additionalProperties": False},
)
def gap_detail(skill: str, *, db_path: str = "edgedash.db") -> dict[str, Any]:
    aliases = {}
    normalized = canonical(skill, aliases) if isinstance(skill, str) else ""
    rows = storage.get_gap_detail_at_cutoff(db_path, normalized, _verified_cutoff(db_path)) if normalized else []
    return {"rows": rows, "summary": f"Listings blocked by the skill gap '{normalized}'."}


@tool(
    "trend",
    "Use when the user asks how skill-gap opportunity cost changed over recent weeks.",
    {"type": "object", "properties": {"weeks": {"type": "integer", "minimum": 1, "maximum": 12, "default": 3}}, "additionalProperties": False},
)
def trend(weeks: int = 3, *, db_path: str = "edgedash.db") -> dict[str, Any]:
    weeks = _clamp_int(weeks, 1, 12, 3)
    snapshots = storage.get_all_gap_snapshots_by_date(db_path)[:weeks]
    rows = [{"run_id": run_id, "computed_at": timestamp, "gaps": gaps} for run_id, timestamp, gaps in snapshots]
    return {"rows": rows, "summary": f"Gap opportunity-cost trend over {weeks} weeks."}


@tool(
    "listing_count",
    "Use when the user asks for total, scored, unscored, or newest listing counts.",
    {"type": "object", "properties": {}, "additionalProperties": False},
)
def listing_count(*, db_path: str = "edgedash.db") -> dict[str, Any]:
    rows = [storage.get_listing_count_details(db_path, _verified_cutoff(db_path))]
    return {"rows": rows, "summary": "Listing totals from the last passing cycle."}


@tool(
    "skill_demand",
    "Use when the user asks how often a named skill is required versus nice-to-have.",
    {"type": "object", "properties": {"skill": {"type": "string"}}, "additionalProperties": False},
)
def skill_demand(skill: str, *, db_path: str = "edgedash.db") -> dict[str, Any]:
    normalized = canonical(skill, {}) if isinstance(skill, str) else ""
    rows = []
    for listing in storage.get_listings_at_cutoff(db_path, _verified_cutoff(db_path)):
        description_hash = _hash_description(listing.get("description", ""))
        facts = storage.get_extraction_cache(db_path, description_hash) or {}
        required = sum(canonical(value, {}) == normalized for value in facts.get("required_skills", []))
        nice = sum(canonical(value, {}) == normalized for value in facts.get("nice_to_have", []))
        if required or nice:
            rows.append({"skill": normalized, "required": required, "nice_to_have": nice, "listing_id": listing.get("id")})
    return {"rows": rows, "summary": f"Demand for '{normalized}' in required versus nice-to-have skills."}


__all__ = [
    "TOOLS", "tool", "companies_hiring", "seniority_distribution",
    "best_matches", "top_gaps", "gap_detail", "trend", "listing_count",
    "skill_demand",
]