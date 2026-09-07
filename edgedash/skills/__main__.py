"""CLI entry point for skills module.

Usage:
    python -m edgedash.skills --audit
"""

import sys
import json
from collections import Counter
from edgedash import storage
from edgedash.config import Config
from edgedash.skills import canonical


def audit_skills(config: Config) -> None:
    """Audit all extracted skills in the database.
    
    Prints:
    1. Top 40 most common raw skills with canonicalised forms
    2. Separator
    3. Singletons (skills seen exactly once)
    """
    # Collect all raw skills from extraction_cache
    raw_skill_counts: Counter = Counter()
    
    with storage.get_conn(config.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT extracted_json FROM extraction_cache")
        
        for row in cursor.fetchall():
            try:
                extracted = json.loads(row["extracted_json"])
                required = extracted.get("required_skills", [])
                for skill in required:
                    if skill and isinstance(skill, str):
                        raw_skill_counts[skill] += 1
            except (json.JSONDecodeError, KeyError):
                continue
    
    if not raw_skill_counts:
        print("No extracted skills found in database.")
        return
    
    # Print top 40 most common
    print(f"\n=== TOP 40 MOST COMMON SKILLS ({len(raw_skill_counts)} unique) ===\n")
    print(f"{'Rank':<5} {'Count':<6} {'Raw Skill':<30} -> {'Canonical Form':<30}")
    print("-" * 72)
    
    for rank, (raw_skill, count) in enumerate(raw_skill_counts.most_common(40), 1):
        canonical_form = canonical(raw_skill, config.skill_aliases)
        print(f"{rank:<5} {count:<6} {raw_skill:<30} -> {canonical_form:<30}")
    
    # Find and print singletons
    singletons = [skill for skill, count in raw_skill_counts.items() if count == 1]
    
    print(f"\n\n=== SINGLETONS ({len(singletons)} skills seen exactly once) ===")
    print("These are usually typos, junk, or mis-extracted text:\n")
    
    for singleton in sorted(singletons):
        canonical_form = canonical(singleton, config.skill_aliases)
        marker = " (aliased)" if canonical_form != singleton else ""
        print(f"  • {singleton}{marker}")
    
    print(f"\nTotal unique skills: {len(raw_skill_counts)}")
    print(f"Total extracted: {sum(raw_skill_counts.values())}")
    print(f"Coverage: top 40 = {sum(count for skill, count in raw_skill_counts.most_common(40))} / {sum(raw_skill_counts.values())}")


if __name__ == "__main__":
    if "--audit" not in sys.argv:
        print(__doc__)
        sys.exit(1)
    
    config = Config.load()
    audit_skills(config)
