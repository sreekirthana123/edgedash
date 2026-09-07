import time
from datetime import datetime
from edgedash.agents.base import AgentResult
from edgedash.sources.base import SOURCES
from edgedash.sources.http import SourceError
from edgedash import storage

# Import sources to trigger registration
import edgedash.sources.arbeitnow


class Fetcher:
    name = "Fetcher"

    @staticmethod
    def run(config, storage_module, stop_conditions: dict = None) -> AgentResult:
        """Fetch jobs from all enabled sources, combining and deduping results.
        
        Args:
            config: Config object
            storage_module: Storage module
            stop_conditions: dict with keys like max_pages, max_listings (optional)
        """
        start_time = datetime.utcnow()
        stop_conditions = stop_conditions or {}
        max_listings = stop_conditions.get("max_listings", 1000)
        
        all_rows = []
        source_results = []
        
        cycle_start = start_time.isoformat()

        # Iterate through enabled sources in order
        for source_name in config.sources:
            if source_name not in SOURCES:
                print(f"  ⚠️  Source '{source_name}' not found in registry")
                source_results.append(f"{source_name}: NOT FOUND")
                continue

            try:
                source_class = SOURCES[source_name]
                source_instance = source_class()

                rows = source_instance.fetch(config)
                all_rows.extend(rows)
                
                cycle_end = datetime.utcnow().isoformat()
                
                # Fixed: Correct positional signature for your log_cycle
                storage_module.log_cycle(
                    config.db_path,
                    f"Fetcher[{source_name}]",
                    cycle_start,
                    cycle_end,
                    len(rows),
                    "ok",
                    f"Fetched {len(rows)} rows from {source_name}"
                )

            except SourceError as e:
                print(f"  ⚠️  Source '{source_name}' failed: {e}")
                source_results.append(f"{source_name}: FAILED ({str(e)[:30]})")
                
                cycle_end = datetime.utcnow().isoformat()
                storage_module.log_cycle(
                    config.db_path,
                    f"Fetcher[{source_name}]",
                    cycle_start,
                    cycle_end,
                    0,
                    "failed",
                    str(e)
                )
                continue

            except Exception as e:
                # Rule 12: Catch per source, log failure, and continue
                print(f"  ⚠️  Source '{source_name}' error: {type(e).__name__}: {e}")
                source_results.append(f"{source_name}: FAILED ({type(e).__name__})")
                
                cycle_end = datetime.utcnow().isoformat()
                storage_module.log_cycle(
                    config.db_path,
                    f"Fetcher[{source_name}]",
                    cycle_start,
                    cycle_end,
                    0,
                    "failed",
                    f"{type(e).__name__}: {e}"
                )
                continue

        # Prepare payload rows: Inject missing IDs and timestamps
        rows_with_ids = []
        for row in all_rows:
            row_copy = row.copy()
            row_copy["id"] = storage_module.compute_id(row["source"], row["url"]) if hasattr(storage_module, "compute_id") else storage_module._make_listing_id(row["source"], row["url"])
            row_copy["fetched_at"] = cycle_start
            rows_with_ids.append(row_copy)

        # Write data to storage
        new_count = storage_module.upsert_listings(config.db_path, rows_with_ids)

        # Generate custom instructor text layout notes string 
        notes_list = []
        for source_name in config.sources:
            source_rows_count = len([r for r in all_rows if r.get("source") == source_name])
            if source_rows_count > 0:
                notes_list.append(f"{source_name}: {source_rows_count} rows → {new_count} new")
            else:
                failed_state = next((s for s in source_results if source_name in s), None)
                if failed_state:
                    notes_list.append(failed_state)

        final_notes = " | ".join(notes_list)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        return AgentResult(
            agent=Fetcher.name,
            status="ok",
            records_touched=new_count,
            notes=final_notes,
            duration_seconds=duration,
        )
