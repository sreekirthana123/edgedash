import uuid
from datetime import datetime, timezone
from edgedash.agents.base import AgentResult
from edgedash.skills import canonical

# Rule 24: rank by opportunity_cost descending
def _sort_gaps(gaps: list) -> list:
    gaps.sort(key=lambda g: g["opportunity_cost"], reverse=True)
    return gaps


class GapAnalyzer:
    """Compute weighted skill gaps from all scored listings using a uniform agent signature."""

    name = "GapAnalyzer"

    def _analyse_gaps(self, scored_listings: list, config) -> dict:
        """Analyze gaps from scored listings with extracted facts.
        
        Returns dict keyed by skill with opportunity_cost, mean_score, listings_blocked, etc.
        """
        aliases = getattr(config, "skill_aliases", {})
        my_skills_canonical = {canonical(s, aliases) for s in config.my_skills}
        
        gap_accumulator = {}
        
        for listing in scored_listings:
            facts = listing.get("extracted", {})
            fit_score = listing.get("fit_score", 0)
            
            # Accumulate strict required blocker requirements
            raw_req = facts.get("required_skills", [])
            for skill_str in raw_req:
                canonical_name = canonical(skill_str, aliases)
                if not canonical_name or canonical_name in my_skills_canonical:
                    continue
                if canonical_name not in gap_accumulator:
                    gap_accumulator[canonical_name] = {
                        "listings": [],
                        "nice_count": 0
                    }
                gap_accumulator[canonical_name]["listings"].append(listing)
            
            # Accumulate nice_to_have entries separately (Rule 23)
            raw_nice = facts.get("nice_to_have", [])
            for skill_str in raw_nice:
                canonical_name = canonical(skill_str, aliases)
                if not canonical_name or canonical_name in my_skills_canonical:
                    continue
                if canonical_name not in gap_accumulator:
                    gap_accumulator[canonical_name] = {
                        "listings": [],
                        "nice_count": 0
                    }
                gap_accumulator[canonical_name]["nice_count"] += 1
        
        # Calculate metrics per gap
        result = {}
        for skill, data in gap_accumulator.items():
            blocked_listings = data["listings"]
            if not blocked_listings:
                continue
            
            listings_blocked = len(blocked_listings)
            opp_cost = sum((l.get("fit_score", 0) / 100.0) for l in blocked_listings)
            mean_score = sum(l.get("fit_score", 0) for l in blocked_listings) / listings_blocked
            
            sorted_by_score = sorted(blocked_listings, key=lambda x: x.get("fit_score", 0), reverse=True)
            top_score = sorted_by_score[0].get("fit_score", 0) if sorted_by_score else 0
            example_ids = [str(l.get("id", "")) for l in sorted_by_score[:5]]
            
            result[skill] = {
                "listings_blocked": listings_blocked,
                "opportunity_cost": round(opp_cost, 2),
                "mean_score": round(mean_score, 1),
                "top_score": top_score,
                "example_ids": example_ids,
                "nice_to_have_count": data["nice_count"]
            }
        
        return result

    def run(self, config, storage_module, stop_conditions: dict = None) -> AgentResult:
        """Analyze gaps from scored listings and write timestamped snapshot.
        
        Args:
            config: Config object
            storage_module: Storage module
            stop_conditions: dict with keys like max_seconds (optional)
        """
        start_time = datetime.now(timezone.utc)
        stop_conditions = stop_conditions or {}
        # max_seconds is informational for now; gap analysis is fast
        
        db_path = config.db_path
        storage_module.init_db(db_path)

        # Get all scored listings (min_score=0 means all listings with a score)
        scored = storage_module.get_listings(db_path, limit=10000, min_score=0)
        if not scored:
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="no scored listings yet",
                duration_seconds=duration,
            )

        # Build extraction map: listing_id -> facts
        # Extract() should not be called here - facts must already be cached from Scorer
        from edgedash.agents.extractor import _hash_description
        for listing in scored:
            # If extracted is already set (e.g., in tests), keep it
            if "extracted" in listing and listing["extracted"]:
                continue
                
            description = listing.get("description", "")
            if description:
                description_hash = _hash_description(description)
                facts = storage_module.get_extraction_cache(db_path, description_hash)
                if facts:
                    listing["extracted"] = facts
                else:
                    listing["extracted"] = {}
            else:
                listing["extracted"] = {}

        # Analyze gaps using the common method
        gap_dict = self._analyse_gaps(scored, config)
        if not gap_dict:
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="no gaps found",
                duration_seconds=duration,
            )

        # Convert dict to list and sort
        analyzed_gaps = []
        for skill, data in gap_dict.items():
            analyzed_gaps.append({
                "skill": skill,
                "listings_blocked": data["listings_blocked"],
                "opportunity_cost": data["opportunity_cost"],
                "mean_score": data["mean_score"],
                "top_score": data["top_score"],
                "example_ids": data["example_ids"],
                "also_nice_to_have": data["nice_to_have_count"]
            })

        _sort_gaps(analyzed_gaps)
        top_10 = analyzed_gaps[:10]

        # Rule 25: Commit snapshot transaction logs through shared interface
        run_id = str(uuid.uuid4())[:8]

        for gap in analyzed_gaps:
            storage_module.save_gap_snapshot(
                db_path,
                run_id=run_id,
                skill=gap["skill"],
                listings_blocked=gap["listings_blocked"],
                opportunity_cost=gap["opportunity_cost"],
                mean_score=gap["mean_score"],
                top_score=gap["top_score"],
                example_ids=gap["example_ids"],
                nice_to_have_count=gap["also_nice_to_have"]
            )

        # Build clean string matching summary requirements precisely
        scored_count = sum(1 for l in scored if l.get("extracted"))
        if top_10:
            top_item = top_10[0]
            notes = f"{len(top_10)} gaps · top: {top_item['skill']} ({top_item['listings_blocked']} listings, cost {top_item['opportunity_cost']}) · {scored_count} listings analysed"
        else:
            notes = f"0 gaps · {scored_count} listings analysed"

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=len(top_10),
            notes=notes,
            duration_seconds=duration,
        )
