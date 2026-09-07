#!/usr/bin/env python3
"""
Debug script to diagnose scorer failures.
Runs extraction and scoring step-by-step without exception handling.
"""

import json
from edgedash.config import Config
from edgedash import storage
from edgedash.agents.extractor import extract
from edgedash.scoring import score_listing


def main():
    print("Loading config...")
    config = Config.load()
    print(f"  Config loaded: {config.target_role} in {config.target_city}")
    print(f"  DB: {config.db_path}")
    print(f"  LLM: {config.llm_provider} ({config.llm_model})\n")

    print("Fetching 1 unscored listing...")
    unscored = storage.get_unscored_listings(config.db_path, 1)

    if not unscored:
        print("ERROR: No unscored listings found!")
        print("  Try running: python run_cycle.py")
        print("  This will fetch and store jobs first.")
        return

    listing = unscored[0]
    listing_dict = dict(listing)

    print(f"  Found listing: {listing['id'][:8]}")
    print(f"  Title: {listing_dict.get('title')}")
    print(f"  Company: {listing_dict.get('company')}")
    print(f"  Description length: {len(listing_dict.get('description', ''))} chars\n")

    print("=" * 70)
    print("EXTRACTION PHASE (no exception handling)")
    print("=" * 70)

    try:
        facts = extract(listing_dict, config, config.db_path)

        print("\nExtraction succeeded!")
        print("\nRaw facts dict:")
        print(json.dumps(facts, indent=2, default=str))

        # Add location and posted_at for scoring
        facts["location"] = listing_dict.get("location")
        facts["posted_at"] = listing_dict.get("posted_at")

        print(f"\nFacts with location/posted_at added:")
        print(json.dumps(facts, indent=2, default=str))

    except Exception as e:
        print(f"\nEXTRACTION FAILED!")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {e}")
        raise

    print("\n" + "=" * 70)
    print("SCORING PHASE (no exception handling)")
    print("=" * 70)

    try:
        result = score_listing(facts, config)

        print("\nScoring succeeded!")
        print("\nRaw result dict:")
        print(json.dumps(result, indent=2, default=str))

        print(f"\n✓ Final score: {result['score']}/100")
        print(f"✓ Reason: {result['reason']}")

    except Exception as e:
        print(f"\nSCORING FAILED!")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {e}")
        raise

    print("\n" + "=" * 70)
    print("SUCCESS")
    print("=" * 70)


if __name__ == "__main__":
    main()
