"""Skill canonicalisation module."""

import re
from typing import Optional


def canonical(raw: str, aliases: dict[str, str]) -> str:
    """Canonicalise a raw skill string to a standard form.
    
    Pure deterministic function. Same input always produces same output.
    
    Steps:
    1. Lowercase and strip whitespace
    2. Drop parenthetical qualifiers
    3. Remove surrounding punctuation
    4. Collapse internal whitespace
    5. Apply alias map
    
    Args:
        raw: Raw skill string from job listing
        aliases: Dict of {canonical_alias: canonical_form}
    
    Returns:
        Canonicalised skill string, or empty string if input is empty/None
    """
    if not raw:
        return ""
    
    # Step 1: Lowercase and strip
    text = str(raw).lower().strip()
    
    if not text:
        return ""
    
    # Step 2: Drop parenthetical qualifiers (qualifiers after main skill)
    # E.g., "kubernetes (eks)" -> "kubernetes", but "(rust)" stays to be handled by step 3
    text = re.sub(r'\s+\(.*?\)', '', text)
    
    # Step 3: Remove surrounding punctuation
    text = text.strip('.,;:!?"\'-()[]{}').strip()
    
    # Step 4: Collapse internal whitespace (multiple spaces to single space)
    text = re.sub(r'\s+', ' ', text).strip()
    
    if not text:
        return ""
    
    # Step 5: Apply alias map
    if text in aliases:
        return aliases[text]
    
    # No alias found, return normalized form
    return text
