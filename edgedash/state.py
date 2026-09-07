"""State inspection: Read current cycle state deterministically.

Per rule 28-31: The orchestrator reads state to decide which agents to run.
No LLM calls. Only timestamps and counts via storage queries.
"""

from datetime import datetime, timezone
from typing import Optional
from edgedash import storage


def read_state(config, storage_module, current_time: datetime) -> dict:
    """Read current state from storage.
    
    Args:
        config: Config object
        storage_module: Storage module
        current_time: Current time (passed in for testability, not datetime.now())
    
    Returns:
        dict with keys:
        - last_fetch_at: ISO 8601 timestamp of last fetch, or None
        - hours_since_fetch: float, hours since last fetch (None if never fetched)
        - unscored_count: int, number of listings without fit_score
        - gaps_computed_at: ISO 8601 timestamp of latest gap snapshot, or None
        - gaps_stale: bool, True if any score is newer than gap snapshot
        - unverified_count: int, number of outputs awaiting verification
        - last_cycle_started_at: ISO 8601 timestamp of last cycle start, or None
    """
    
    # Cheap queries: counts and max timestamps only
    last_fetch_at = storage_module.last_fetch_time(config.db_path)
    unscored_count = storage_module.count_unscored(config.db_path)
    
    # Compute hours since fetch
    hours_since_fetch = None
    if last_fetch_at:
        fetch_dt = datetime.fromisoformat(last_fetch_at)
        if fetch_dt.tzinfo is None:
            # Assume UTC if naive
            fetch_dt = fetch_dt.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        delta = current_time - fetch_dt
        hours_since_fetch = delta.total_seconds() / 3600.0
    
    # Get latest gap snapshot
    latest_snapshots = storage_module.get_latest_gap_snapshots(config.db_path)
    gaps_computed_at = None
    if latest_snapshots:
        # get_latest_gap_snapshots returns dicts with 'timestamp' key
        gaps_computed_at = latest_snapshots[0].get("timestamp")
    
    # Check if gaps are stale
    gaps_stale = _gaps_are_stale(config.db_path, storage_module, gaps_computed_at)
    
    # Get last cycle start time (from cycle_log table)
    last_cycle_started_at = _get_last_cycle_start_time(config.db_path, storage_module)

    count_unverified = getattr(storage_module, "count_unverified", None)
    unverified_count = count_unverified(config.db_path) if count_unverified else 0
    
    return {
        "last_fetch_at": last_fetch_at,
        "hours_since_fetch": hours_since_fetch,
        "unscored_count": unscored_count,
        "gaps_computed_at": gaps_computed_at,
        "gaps_stale": gaps_stale,
        "unverified_count": unverified_count,
        "last_cycle_started_at": last_cycle_started_at,
    }


def _gaps_are_stale(db_path: str, storage_module, gaps_computed_at: Optional[str]) -> bool:
    """Check if any score is newer than the latest gap snapshot.
    
    Gaps are stale if:
    - No gap snapshot exists yet (gaps_computed_at is None), OR
    - Any listing has a fit_score newer than gaps_computed_at
    """
    if gaps_computed_at is None:
        return True
    
    # Convert gap snapshot timestamp to comparable format
    gap_dt = datetime.fromisoformat(gaps_computed_at)
    
    # Get the newest score timestamp from the listings table
    with storage_module.get_conn(db_path) as conn:
        cursor = conn.execute(
            "SELECT MAX(fit_score_set_at) as newest_score_at FROM listings WHERE fit_score IS NOT NULL"
        )
        row = cursor.fetchone()
        if row and row[0]:
            # If any score exists and is newer than gap snapshot, gaps are stale
            newest_score_at = row[0]
            score_dt = datetime.fromisoformat(newest_score_at)
            return score_dt > gap_dt
        # No scores at all, gaps are not stale (they were computed from no scores)
        return False


def _get_last_cycle_start_time(db_path: str, storage_module) -> Optional[str]:
    """Get the timestamp of the last cycle start from cycle_log."""
    with storage_module.get_conn(db_path) as conn:
        cursor = conn.execute(
            "SELECT MAX(started_at) as last_started FROM cycle_log"
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
        return None
