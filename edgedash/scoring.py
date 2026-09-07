from datetime import datetime, timedelta, timezone
from typing import Optional


def _score_skills_match(required_skills: list[str], my_skills: list[str]) -> float:
    """Score skill coverage: 0.0-1.0. Normalized to config.my_skills.
    
    Case insensitive matching. If no required skills listed, return 0.5 (neutral).
    """
    if not required_skills:
        return 0.5

    my_skills_lower = [s.lower() for s in my_skills]
    matches = sum(1 for skill in required_skills if skill.lower() in my_skills_lower)

    return matches / len(required_skills)


def _score_seniority_match(listing_seniority: str, target_seniority: str) -> float:
    """Score seniority alignment: 0.0-1.0.
    
    Exact match: 1.0
    One band away (junior<->mid, mid<->senior, senior<->lead): 0.6
    Two bands away: 0.25
    Three+ bands away: 0.0
    Unknown in either: 0.5
    """
    if listing_seniority == "unknown" or target_seniority == "unknown":
        return 0.5

    seniority_order = ["junior", "mid", "senior", "lead"]

    try:
        listing_idx = seniority_order.index(listing_seniority)
        target_idx = seniority_order.index(target_seniority)
    except ValueError:
        return 0.5

    distance = abs(listing_idx - target_idx)

    if distance == 0:
        return 1.0
    elif distance == 1:
        return 0.6
    elif distance == 2:
        return 0.25
    else:
        return 0.0


def _score_location_match(listing_location: Optional[str], target_city: str, remote_ok: Optional[bool]) -> float:
    """Score location fit: 0.0-1.0.
    
    Exact city match: 1.0
    Unknown location: 0.5
    Remote allowed: 1.0
    Different location, not remote: 0.1
    """
    if remote_ok is True:
        return 1.0

    if listing_location is None:
        return 0.5

    if target_city.lower() in listing_location.lower():
        return 1.0

    # Not target city and not remote
    return 0.1


def _score_recency(posted_at: Optional[str]) -> float:
    """Score job recency: 0.0-1.0.
    
    Posted today: 1.0
    Decays linearly to 0.0 at 30 days.
    Null posted_at: 0.5 (neutral)
    """
    if posted_at is None:
        return 0.5

    try:
        posted_dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        
        # Handle naive timestamps
        if posted_dt.tzinfo is None:
            posted_dt = posted_dt.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        age_days = (now - posted_dt).days

        if age_days < 0:
            return 1.0  # Posted in future (shouldn't happen)

        if age_days >= 30:
            return 0.0

        return 1.0 - (age_days / 30.0)

    except (ValueError, AttributeError, TypeError):
        return 0.5


def score_listing(facts: dict, config) -> dict:
    """Compute deterministic fit score from extracted facts.

    Args:
        facts: Extracted dict with required_skills, seniority, years_required, remote_ok, location
        config: Config with my_skills, target_seniority, score_weights, etc.

    Returns:
        Dict with:
        - score: 0-100 (int)
        - reason: human-readable string per rule 19
        - components: {skills_match, seniority_match, location_match, recency} each 0.0-1.0
    """

    # Extract component scores (0.0-1.0)
    skills_score = _score_skills_match(facts.get("required_skills", []), config.my_skills)

    seniority_score = _score_seniority_match(
        facts.get("seniority", "unknown"),
        config.target_seniority,
    )

    location_score = _score_location_match(
        facts.get("location"),
        config.target_city,
        facts.get("remote_ok"),
    )

    recency_score = _score_recency(facts.get("posted_at"))

    # Weighted sum to 0-100
    weights = config.score_weights
    total_score = (
        skills_score * weights["skills_match"]
        + seniority_score * weights["seniority_match"]
        + location_score * weights["location_match"]
        + recency_score * weights["recency"]
    )

    final_score = int(round(total_score * 100))

    # Clamp to 0-100
    final_score = max(0, min(100, final_score))

    components = {
        "skills_match": skills_score,
        "seniority_match": seniority_score,
        "location_match": location_score,
        "recency": recency_score,
    }

    reason = _build_reason(components, facts, config)

    return {
        "score": final_score,
        "reason": reason,
        "components": components,
    }


def _build_reason(components: dict, facts: dict, config) -> str:
    """Build human-readable reason from score components and facts.

    Per rule 19: generated FROM NUMBERS, naming actual gaps.
    Format: "4/6 required skills - seniority fits - remote - posted 2d ago - gap: kubernetes, spark"
    """

    parts = []

    # Skills
    required_skills = facts.get("required_skills", [])
    if required_skills:
        my_skills_lower = [s.lower() for s in config.my_skills]
        matched = sum(1 for s in required_skills if s.lower() in my_skills_lower)
        parts.append(f"{matched}/{len(required_skills)} skills")

        # Identify gaps
        gaps = [s for s in required_skills if s.lower() not in my_skills_lower]
        if gaps:
            parts.append(f"gap: {', '.join(gaps[:3])}")  # Top 3 gaps
    else:
        parts.append("no required skills stated")

    # Seniority
    listing_seniority = facts.get("seniority", "unknown")
    if listing_seniority != "unknown":
        if components["seniority_match"] >= 0.9:
            parts.append("seniority fits")
        elif components["seniority_match"] >= 0.5:
            parts.append(f"seniority {listing_seniority}")
        else:
            parts.append(f"seniority {listing_seniority} (mismatch)")

    # Location
    if facts.get("remote_ok") is True:
        parts.append("remote")
    elif facts.get("location"):
        if components["location_match"] >= 0.9:
            parts.append("location OK")
        else:
            parts.append(f"location {facts['location']}")

    # Recency
    posted_at = facts.get("posted_at")
    if posted_at:
        try:
            posted_dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            
            # Handle naive timestamps
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            age_days = (now - posted_dt).days
            if age_days == 0:
                parts.append("posted today")
            elif age_days == 1:
                parts.append("posted 1d ago")
            elif age_days < 30:
                parts.append(f"posted {age_days}d ago")
        except (ValueError, AttributeError, TypeError):
            pass

    return " - ".join(parts)
