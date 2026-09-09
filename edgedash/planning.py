"""Plan generation: Deterministic state → plan mapping.

Per rule 28-31: Build an explicit plan before executing any agent.
Pure function of (state, config) — no I/O, no side effects.
Every agent appears in the plan: either running with a goal, or skipped with a reason.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Task:
    """A single delegated agent task."""
    agent_name: str
    goal: str
    stop_conditions: dict
    reason: str
    skipped: bool = False


@dataclass
class Plan:
    """Ordered list of tasks for the cycle."""
    tasks: list[Task]
    
    def render(self) -> str:
        """Return a compact printable plan (one line per task)."""
        lines = []
        for task in self.tasks:
            if task.skipped:
                lines.append(f"  X {task.agent_name:<12} SKIP stop-n/a              {task.reason}")
            else:
                conditions_str = " ".join(
                    f"{k}={v}" for k, v in task.stop_conditions.items()
                )
                # Pad to align reason column (~30 char width for stop conditions)
                padded_conditions = f"stop-{conditions_str}".ljust(30)
                lines.append(
                    f"  • {task.agent_name:<12} RUN {padded_conditions} {task.reason}"
                )
        return "\n".join(lines)


def build_plan(state: dict, config) -> Plan:
    """Build an explicit plan from current state.
    
    Decision rules:
    - fetch: if hours_since_fetch >= fetch_interval_hours (default 6)
    - score: if unscored_count > 0
    - analyse: if gaps_stale or gaps_computed_at is None
    
    Args:
        state: dict from read_state()
        config: Config object
    
    Returns:
        Plan with ordered tasks
    """
    
    # Use defaults from config, or fall back to sensible values
    fetch_interval_hours = getattr(config, "fetch_interval_hours", 6)
    
    tasks = []
    
    # === FETCHER ===
    hours_since = state["hours_since_fetch"]
    should_fetch = (
        hours_since is None or  # Never fetched
        hours_since >= fetch_interval_hours
    )
    
    if should_fetch:
        reason = f"hours_since_fetch={hours_since:.1f} (threshold {fetch_interval_hours})" if hours_since else "never fetched"
        tasks.append(Task(
            agent_name="Fetcher",
            goal="fetch fresh job listings",
            stop_conditions={
                "max_pages": 5,
                "max_listings": 1000,
            },
            reason=reason,
            skipped=False,
        ))
    else:
        reason = f"skipped: hours_since_fetch={hours_since:.1f} < {fetch_interval_hours}"
        tasks.append(Task(
            agent_name="Fetcher",
            goal="fetch fresh job listings",
            stop_conditions={
                "max_pages": 5,
                "max_listings": 1000,
            },
            reason=reason,
            skipped=True,
        ))
    
    # === SCORER ===
    unscored_count = state["unscored_count"]
    should_score = unscored_count > 0
    
    if should_score:
        reason = f"unscored_count={unscored_count}"
        tasks.append(Task(
            agent_name="Scorer",
            goal="score unscored listings",
            stop_conditions={
                "max_items": config.score_batch_size,
                "max_seconds": 3600,
            },
            reason=reason,
            skipped=False,
        ))
    else:
        reason = "skipped: unscored_count=0"
        tasks.append(Task(
            agent_name="Scorer",
            goal="score unscored listings",
            stop_conditions={
                "max_items": config.score_batch_size,
                "max_seconds": 3600,
            },
            reason=reason,
            skipped=True,
        ))
    
    # === GAP ANALYZER ===
    gaps_stale = state["gaps_stale"]
    should_analyse = gaps_stale
    
    if should_analyse:
        if state["gaps_computed_at"] is None:
            reason = "gaps never computed"
        else:
            reason = "gaps_stale=true (new scores since last snapshot)"
        tasks.append(Task(
            agent_name="GapAnalyzer",
            goal="analyze and snapshot skill gaps",
            stop_conditions={
                "max_seconds": 60,
            },
            reason=reason,
            skipped=False,
        ))
    else:
        reason = "skipped: gaps_stale=false"
        tasks.append(Task(
            agent_name="GapAnalyzer",
            goal="analyze and snapshot skill gaps",
            stop_conditions={
                "max_seconds": 60,
            },
            reason=reason,
            skipped=True,
        ))

    # === VERIFIER ===
    # Verify whenever this cycle will produce new output (a fetch or a score
    # is planned) or when unverified output from an earlier cycle exists.
    # The Verifier is read-only and makes NO LLM calls, so running it is
    # effectively free and keeps rule 38's "only passing cycles are read"
    # invariant fresh. It always runs LAST, after the GapAnalyzer.
    unverified_count = state.get("unverified_count", 0)
    produced_output = should_fetch or should_score
    should_verify = produced_output or unverified_count > 0
    if should_verify:
        if produced_output:
            reason = "cycle produced new output (fetch or score)"
        else:
            reason = f"unverified_count={unverified_count}"
        tasks.append(Task(
            agent_name="Verifier",
            goal="verify cycle output plausibility",
            stop_conditions={
                "max_seconds": 60,
            },
            reason=reason,
            skipped=False,
        ))
    else:
        tasks.append(Task(
            agent_name="Verifier",
            goal="verify cycle output plausibility",
            stop_conditions={
                "max_seconds": 60,
            },
            reason="no new output or unverified backlog — nothing to verify",
            skipped=True,
        ))

    return Plan(tasks=tasks)
