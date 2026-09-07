"""Gap snapshot reporting CLI."""

from datetime import datetime
from edgedash.config import Config
from edgedash import storage
import sys
import io


def print_gaps_table(config: Config) -> None:
    """Print latest gap snapshots matching target layout.
    
    Per rule 27: flags gaps from < 3 listings as "low confidence"
    
    Format: # | SKILL | BLK | COST | MEAN | TOP | NICE | BAR | NOTE
    """
    # Handle Windows Unicode encoding
    if sys.stdout.encoding.lower() == 'utf-8':
        filled_char = "█"
        empty_char = "░"
    else:
        # Fallback for Windows cp1252
        filled_char = "#"
        empty_char = "-"
    
    gaps = storage.get_latest_gap_snapshots(config.db_path)

    if not gaps:
        print("\nNo gap snapshots found. Run cycle with scorer + gap_analyzer first.\n")
        return

    # Get the most recent snapshot timestamp from the first gap
    snapshot_time = gaps[0]["computed_at"] if gaps else None
    if snapshot_time:
        # Parse and format the ISO timestamp nicely
        try:
            dt = datetime.fromisoformat(snapshot_time)
            snapshot_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            snapshot_str = snapshot_time
    else:
        snapshot_str = "Unknown"

    print("\nEdgeDash - Skill Gap Report")
    print(f"\nSnapshot: {snapshot_str}\n")
    print(f" {'#':<3} {'SKILL':<25} {'BLK':<6} {'COST':<7} {'MEAN':<7} {'TOP':<6} {'NICE':<5} {'BAR':<14} {'NOTE':<40}")
    print("-" * 130)

    for rank, gap in enumerate(gaps, 1):
        skill = gap["skill"][:23]
        blocked = gap["listings_blocked"]
        opp_cost = gap["opportunity_cost"]
        mean_score = gap["mean_score"]
        top_score = gap.get("top_score", 0)
        nice_count = gap.get("nice_to_have_count", 0)
        
        # Build visual bar: scale to cost=10.0
        # At cost 10.0, bar should be full (█ █ █)
        # Scale: each block represents ~0.5 cost
        bar_width = min(int(opp_cost * 1.5), 12)  # Max 12 blocks
        filled = min(bar_width, 12)
        empty = 12 - filled
        bar = (filled_char * filled) + (empty_char * empty)

        # Build note column with confidence and nice-to-have info
        notes = []
        if blocked < 3:
            notes.append("LOW confidence (n<3)")
        
        if nice_count > 0:
            if nice_count == 1:
                notes.append("+1 nice-to-have")
            else:
                notes.append(f"+{nice_count} nice-to-have")
        
        note_str = "  ".join(notes) if notes else ""

        print(
            f" {rank:<3} {skill:<25} {blocked:<6} {opp_cost:<7.2f} {mean_score:<7.1f} {top_score:<6} {nice_count:<5} {bar:<14} {note_str:<40}"
        )

    print("-" * 130)
    print(f"\nOpportunity cost = SUM(score/100) for listings blocked by that gap.")
    print(f"\nBar scales to cost=10.0.\n")


def print_gaps_trend(config: Config) -> None:
    """Print trend of top 10 skills across snapshots.
    
    Shows opportunity cost at earliest and latest snapshot, with changes marked.
    Requires at least 2 snapshots to show a trend.
    """
    snapshots = storage.get_all_gap_snapshots_by_date(config.db_path)
    
    if not snapshots:
        print("\nNo gap snapshots found.\n")
        return
    
    if len(snapshots) < 2:
        print("\nEdgeDash - Skill Gap Trend Report")
        print(f"\nSnapshot date: {snapshots[0][1]}\n")
        print("Only 1 snapshot available. Need at least 2 to show a trend.")
        print("Run the cycle again on the next day to see trend data.")
        print("(If you run frequently, you need multiple days of data to see meaningful trends.)\n")
        return
    
    # Get earliest and latest snapshots
    latest = snapshots[0]  # Most recent
    earliest = snapshots[-1]  # Oldest
    
    latest_run_id, latest_time, latest_gaps = latest
    earliest_run_id, earliest_time, earliest_gaps = earliest
    
    # Parse timestamps
    try:
        latest_dt = datetime.fromisoformat(latest_time)
        earliest_dt = datetime.fromisoformat(earliest_time)
        latest_str = latest_dt.strftime("%Y-%m-%d %H:%M:%S")
        earliest_str = earliest_dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        latest_str = latest_time
        earliest_str = earliest_time
    
    # Print header block
    print()
    print(f"Comparing {len(snapshots)} snapshots")
    print(f"Earliest : {earliest_str} UTC (run {earliest_run_id[:8]}...)")
    print(f"Latest   : {latest_str} UTC (run {latest_run_id[:8]}...)")
    print()
    
    # Get current top 10 from latest snapshot
    top_10_latest = latest_gaps[:10]
    latest_skills = {gap["skill"]: gap for gap in top_10_latest}
    
    # Create map of earliest snapshot for quick lookup
    earliest_map = {gap["skill"]: gap for gap in earliest_gaps}
    
    # Print table headers with expanded spacing
    print(f"{'#':>2} {'SKILL':<20}  {'EARLY':>7}  {'LATEST':>7}  {'ΔCOST':>7}  {'Δ%':>6} {'NOTE'}")
    print()
    
    for rank, (skill, latest_gap) in enumerate(latest_skills.items(), 1):
        latest_cost = latest_gap["opportunity_cost"]
        earliest_gap = earliest_map.get(skill)
        
        if earliest_gap:
            earliest_cost = earliest_gap["opportunity_cost"]
            change = latest_cost - earliest_cost
            pct_change = (change / earliest_cost * 100) if earliest_cost > 0 else 0
        else:
            # Skill is NEW
            earliest_cost = 0
            change = latest_cost
            pct_change = 0
        
        # Determine NOTE based on change
        note = "→ stable" if change == 0 else ""
        
        # Truncate skill name to 20 characters and use strict formatting with expanded spacing
        skill_trunc = skill[:20]
        print(f"{rank:>2} {skill_trunc:<20}  {earliest_cost:>7.2f}  {latest_cost:>7.2f}  {change:>+7.2f}  {pct_change:>+5.1f}% {note}")
    
    print()
    print("ΔCOST = latest opportunity cost minus earliest.")
    print("Δ% = percentage change. n/a means skill was absent in that snapshot.")
    print()
