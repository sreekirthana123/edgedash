import hashlib
import re
from html.parser import HTMLParser
from edgedash import llm, storage


EXTRACTION_SCHEMA = {
    "required_skills": list,
    "nice_to_have": list,
    "seniority": str,
    "years_required": int,
    "remote_ok": bool,
}

# Valid seniority levels
VALID_SENIORITY = {"junior", "mid", "senior", "lead", "unknown"}

PROMPT_TEMPLATE = """You are reading a job listing. Extract ONLY facts explicitly stated in the text.
Do NOT infer, guess, evaluate, or assume. Do NOT mention candidates, profiles, or hiring criteria.
You are a document reader, nothing more.

From the listing text, extract:
- required_skills: List of skills explicitly required. Empty list if none mentioned.
- nice_to_have: List of skills marked as preferred, nice-to-have, or optional. Empty list if none.
- seniority: Job level category. Only use exact terms from listing: "junior", "mid", "senior", "lead". If not clear, use "unknown".
- years_required: Minimum years of experience explicitly stated. null if not mentioned.
- remote_ok: Can work remote? Only true if listing explicitly says remote/work-from-home. null if listing doesn't address it.

Listing text:
{description}

Respond with ONLY valid JSON matching the schema. No prose, no markdown fences, no explanation."""


class MLStripper(HTMLParser):
    """Strip HTML tags from text."""

    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def get_data(self):
        return "".join(self.text)


def _strip_html(html: str) -> str:
    """Remove HTML tags, normalize whitespace."""
    if not html:
        return ""
    stripper = MLStripper()
    try:
        stripper.feed(html)
        text = stripper.get_data()
    except Exception:
        text = html
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _hash_description(description: str) -> str:
    """Generate stable hash of cleaned job description."""
    if not description:
        return ""
    cleaned = _strip_html(description)
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]


def _normalize_skills(skills: list) -> list[str]:
    """Normalize skill names to lowercase, filter empty."""
    result = []
    for skill in skills:
        if isinstance(skill, str) and skill.strip():
            result.append(skill.lower().strip())
    return result


def _coerce_result(extracted: dict) -> dict:
    """Normalize extraction result: lowercase skills, validate seniority, handle bool strings."""
    # Normalize skills
    extracted["required_skills"] = _normalize_skills(extracted.get("required_skills", []))
    extracted["nice_to_have"] = _normalize_skills(extracted.get("nice_to_have", []))

    # Clamp seniority to valid enum
    seniority = extracted.get("seniority", "unknown")
    if isinstance(seniority, str):
        seniority = seniority.lower().strip()
    if seniority not in VALID_SENIORITY:
        seniority = "unknown"
    extracted["seniority"] = seniority

    # Handle bool coercion (models sometimes return "true"/"false" strings)
    remote_ok = extracted.get("remote_ok")
    if isinstance(remote_ok, str):
        if remote_ok.lower() in ("true", "yes", "1"):
            remote_ok = True
        elif remote_ok.lower() in ("false", "no", "0"):
            remote_ok = False
        else:
            remote_ok = None
    extracted["remote_ok"] = remote_ok

    # years_required can be None
    years_required = extracted.get("years_required")
    if isinstance(years_required, str):
        try:
            years_required = int(years_required)
        except (ValueError, TypeError):
            years_required = None
    extracted["years_required"] = years_required

    return extracted


def extract(listing: dict, config, db_path: str) -> dict:
    """Extract structured facts from job listing with caching.

    Args:
        listing: Job listing dict with 'description' key
        config: Config object
        db_path: Path to SQLite database

    Returns:
        Extracted dict with required_skills, nice_to_have, seniority, years_required, remote_ok

    Raises:
        llm.LLMError: If LLM call fails (caller handles per rule 17)
    """

    description = listing.get("description", "")
    if not description:
        # No description to extract from
        return {
            "required_skills": [],
            "nice_to_have": [],
            "seniority": "unknown",
            "years_required": None,
            "remote_ok": None,
        }

    # Clean and hash description
    cleaned_description = _strip_html(description)
    description_hash = _hash_description(description)

    # Check extraction cache FIRST (rule 18)
    cached = storage.get_extraction_cache(db_path, description_hash)
    if cached is not None:
        return cached

    # Cache miss: call LLM
    # Truncate to 6000 chars to stay within context windows
    truncated = cleaned_description[:6000]
    prompt = PROMPT_TEMPLATE.format(description=truncated)

    extracted = llm.complete_json(prompt, EXTRACTION_SCHEMA, config)

    # Normalize and coerce result
    extracted = _coerce_result(extracted)

    # Store in cache (rule 18)
    storage.set_extraction_cache(db_path, description_hash, extracted)

    return extracted
