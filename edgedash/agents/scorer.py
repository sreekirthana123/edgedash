import statistics
import argparse
import time
from datetime import datetime
from edgedash.agents.base import AgentResult
from edgedash.agents.extractor import extract
from edgedash.scoring import score_listing
from edgedash import llm, storage


class Scorer:
    name = "Scorer"

    @staticmethod
    def run(config, storage_module, stop_conditions: dict = None) -> AgentResult:
        """Score unscored listings using extracted facts and deterministic scoring.

        Per rule 21: limit to config.score_batch_size to prevent cost blowup.
        Per rule 17: per-listing try/except, failures logged but don't stop cycle.
        Per rule 20: log score distribution (count, min, max, mean, spread).
        
        Args:
            config: Config object
            storage_module: Storage module
            stop_conditions: dict with keys like max_items, max_seconds (optional)
        """
        start_time = datetime.utcnow()
        stop_conditions = stop_conditions or {}
        max_items = stop_conditions.get("max_items", config.score_batch_size)
        batch_size = min(max_items, config.score_batch_size)
        
        unscored = storage_module.get_unscored_listings(config.db_path, batch_size)

        if not unscored:
            return AgentResult(
                agent=Scorer.name,
                status="ok",
                records_touched=0,
                notes="No unscored listings",
            )

        scores = []
        failed_listings = []
        quota_exhausted = False
        cycle_start = datetime.utcnow().isoformat()

        for listing in unscored:
            try:
                time.sleep(4)
                
                # Extract facts from description
                listing_dict = dict(listing)
                facts = extract(listing_dict, config, config.db_path)

                # Add location to facts for scoring
                facts["location"] = listing_dict.get("location")
                facts["posted_at"] = listing_dict.get("posted_at")

                # Score deterministically
                result = score_listing(facts, config)
                fit_score = result["score"]
                fit_reason = result["reason"]

                # Save score to database
                storage_module.save_score(
                    config.db_path,
                    listing["id"],
                    fit_score,
                    fit_reason,
                )

                scores.append(fit_score)

                # Log success to cycle_log
                storage_module.log_cycle(
                    config.db_path,
                    agent=f"Scorer[{listing['id'][:8]}]",
                    started_at=cycle_start,
                    finished_at=datetime.utcnow().isoformat(),
                    records_touched=1,
                    status="ok",
                    notes=f"Score: {fit_score}",
                )

            except llm.LLMError as e:
                # Check if it's a quota exhaustion error
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(f"\n⚠️  API quota exhausted. Stopping scorer for this cycle.")
                    quota_exhausted = True
                    # Log this as a quota event, then break to stop processing
                    storage_module.log_cycle(
                        config.db_path,
                        agent="Scorer[quota]",
                        started_at=cycle_start,
                        finished_at=datetime.utcnow().isoformat(),
                        records_touched=0,
                        status="failed",
                        notes=(
                            "API quota exhausted (429 RESOURCE_EXHAUSTED): "
                            f"{str(e)[:500]}"
                        ),
                    )
                    break
                
                # Other LLM errors — log and skip this listing
                failed_listings.append(f"{listing['id'][:8]} (extraction failed)")

                storage_module.log_cycle(
                    config.db_path,
                    agent=f"Scorer[{listing['id'][:8]}]",
                    started_at=cycle_start,
                    finished_at=datetime.utcnow().isoformat(),
                    records_touched=0,
                    status="failed",
                    notes=f"Extraction failed: {str(e)[:50]}",
                )

            except Exception as e:
                # Other error — log and skip
                failed_listings.append(f"{listing['id'][:8]} ({type(e).__name__})")

                storage_module.log_cycle(
                    config.db_path,
                    agent=f"Scorer[{listing['id'][:8]}]",
                    started_at=cycle_start,
                    finished_at=datetime.utcnow().isoformat(),
                    records_touched=0,
                    status="failed",
                    notes=f"{type(e).__name__}: {str(e)[:50]}",
                )

        # Compute distribution stats
        notes_parts = []

        if scores:
            min_score = min(scores)
            max_score = max(scores)
            mean_score = statistics.mean(scores)
            spread = max_score - min_score

            notes_parts.append(f"scored {len(scores)}")
            notes_parts.append(f"range {min_score}-{max_score}")
            notes_parts.append(f"mean {int(mean_score)}")

            # Flag suspect runs (spread < 10)
            if spread < 10:
                notes_parts.append("SUSPECT (spread < 10)")
                distribution_status = "suspect"
            else:
                notes_parts.append(f"spread {spread}")
                distribution_status = "ok"

            # Log distribution to cycle_log
            storage_module.log_cycle(
                config.db_path,
                agent="Scorer[distribution]",
                started_at=cycle_start,
                finished_at=datetime.utcnow().isoformat(),
                records_touched=len(scores),
                status=distribution_status,
                notes=f"Distribution: count={len(scores)} min={min_score} max={max_score} mean={int(mean_score)} spread={spread}",
            )
        else:
            notes_parts.append("scored 0")
            distribution_status = "ok"

        if failed_listings:
            notes_parts.append(f"{len(failed_listings)} failed")

        notes = " · ".join(notes_parts)

        # Determine overall status
        if quota_exhausted:
            # If quota was exhausted, report suspect (even if we scored some)
            overall_status = "suspect"
        else:
            # Otherwise use distribution_status
            overall_status = distribution_status if scores else "ok"

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        return AgentResult(
            agent=Scorer.name,
            status=overall_status,
            records_touched=len(scores),
            notes=notes,
            duration_seconds=duration,
        )


def main() -> None:
    """CLI entry point: python -m edgedash.agents.scorer --limit N"""
    parser = argparse.ArgumentParser(
        description="Score unscored job listings using deterministic scoring.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of listings to score (default: use config.score_batch_size)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )

    args = parser.parse_args()

    from edgedash.config import Config

    try:
        config = Config.load(args.config)

        # Override batch size if --limit specified
        if args.limit is not None:
            config.score_batch_size = args.limit

        print(f"Scoring up to {config.score_batch_size} listings...")
        result = Scorer.run(config, storage)

        print(f"\nResult:")
        print(f"  Agent: {result.agent}")
        print(f"  Status: {result.status}")
        print(f"  Records touched: {result.records_touched}")
        print(f"  Notes: {result.notes}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        exit(1)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        exit(1)


if __name__ == "__main__":
    main()
