"""Main orchestration loop: state-driven agent coordination.

Per rules 28-33:
- Read state, build plan, print plan, execute only planned tasks
- Agents are resolved from registry by name (rule 30)
- One agent failure doesn't stop the cycle (rule 32)
- Cycle outcome is complete | partial | nothing_to_do (rule 33)
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from edgedash.state import read_state
from edgedash.planning import build_plan
from edgedash.agents.registry import build_agents as registry_build_agents, get_agent_class
from edgedash import storage


def build_agents() -> dict:
    """Build the agent registry used by the orchestrator."""
    return registry_build_agents()


def _agent_class(agent_name):
    """Resolve an agent from the current registry, including test overrides."""
    return build_agents().get(agent_name) or get_agent_class(agent_name)


def _retry_agent_for_verification(failed_checks: tuple) -> str | None:
    """Map a failed plausibility check to its producing agent."""
    producers = {
        "score_spread": "Scorer",
        "extraction_sanity": "Scorer",
        "gap_sample_size": "GapAnalyzer",
        "freshness": "Fetcher",
    }
    for check in failed_checks:
        if check.check_name in producers:
            return producers[check.check_name]
    return None


def run_cycle(config, storage_module=storage):
    """Run one complete state-driven cycle.
    
    1. Read state
    2. Build plan from state
    3. Print plan (rule 31)
    4. Execute planned tasks with error isolation (rule 32)
    5. Write cycle summary (rule 33)
    """
    
    # Report the active backend before any cycle output or database work.
    storage_module._log_backend()

    # INIT: Ensure database exists
    storage_module.init_db(config.db_path)
    
    # Header
    print("\nEDGEDASH — cycle started")
    print("=" * 50)
    
    # STATE: Read current system state
    print("\nSTATE")
    print("_" * 50)
    current_time = datetime.now(timezone.utc)
    state = read_state(config, storage_module, current_time)
    hours_since = state['hours_since_fetch']
    hours_str = f"{hours_since:.1f}" if hours_since is not None else "None"
    print(f"Last fetch     : {state['last_fetch_at']}")
    print(f"Hours since    : {hours_str}")
    print(f"Unscored count : {state['unscored_count']}")
    print(f"Gaps stale     : {state['gaps_stale']}")
    print(f"Unverified     : {state.get('unverified_count', 0)}")
    
    # PLAN: Build plan from state
    plan = build_plan(state, config)
    
    # Check if plan is entirely skipped
    is_nothing_to_do = all(task.skipped for task in plan.tasks)
    
    print("\nPLAN")
    print("_" * 50)
    print(plan.render())
    
    # EXECUTION: Run only the planned tasks
    print("\nEXECUTION")
    print("_" * 50)
    
    results = []
    cycle_outcome = "complete"
    retry_count = 0
    final_verdict = None
    
    for task in plan.tasks:
        if task.skipped:
            # Print skipped tasks (rule 31)
            print(f"X {task.agent_name:<14} SKIPPED | {task.reason}")
            continue
        
        # Resolve agent from registry
        try:
            agent_class = _agent_class(task.agent_name)
            agent_instance = agent_class()
        except KeyError:
            print(f"✗ {task.agent_name:<12} status-failed new-0  | agent not found in registry")
            results.append({
                "agent": task.agent_name,
                "status": "failed",
                "notes": "agent not found in registry",
                "duration": 0.0,
            })
            cycle_outcome = "partial"
            continue
        
        # Execute agent with stop_conditions (rule 29)
        try:
            result = agent_instance.run(config, storage_module, stop_conditions=task.stop_conditions)

            if task.agent_name == "Verifier" and not hasattr(result, "status"):
                result = SimpleNamespace(
                    agent="Verifier",
                    status="ok" if result.passed else "failed",
                    records_touched=0,
                    notes=result.summary,
                    duration_seconds=0.0,
                    verdict=result,
                )
            
            # Format output
            status_sym = "✓" if result.status == "ok" else ("X" if result.status == "suspect" else "✗")
            print(f"{status_sym} {result.agent:<12} status-{result.status} new-{result.records_touched}  | {result.notes}")
            
            results.append({
                "agent": result.agent,
                "status": result.status,
                "records_touched": result.records_touched,
                "notes": result.notes,
                "duration": result.duration_seconds,
                "verdict": getattr(result, "verdict", None),
            })
            
            # Mark cycle as partial if any agent failed
            if result.status == "failed":
                cycle_outcome = "degraded" if task.agent_name == "Verifier" else "partial"

            if task.agent_name == "Verifier":
                verdict = getattr(result, "verdict", None)
                verification_failed = (
                    result.status != "ok"
                    or (verdict is not None and not verdict.passed)
                )
                if verification_failed:
                    final_verdict = verdict
                    failed_checks = tuple(
                        check for check in verdict.checks if not check.passed
                    ) if verdict is not None else ()
                    retry_agent_name = _retry_agent_for_verification(failed_checks)
                    if retry_agent_name is None:
                        cycle_outcome = "degraded"
                        break

                    retry_count = 1
                    print("\nRETRY (1/1) re-running: " + retry_agent_name)
                    print("_" * 50)
                    try:
                        retry_class = _agent_class(retry_agent_name)
                        retry_result = retry_class().run(
                            config,
                            storage_module,
                            stop_conditions={
                                "retry": 1,
                                "adjusted_context": failed_checks,
                            },
                        )
                        results.append({
                            "agent": retry_result.agent,
                            "status": retry_result.status,
                            "records_touched": retry_result.records_touched,
                            "notes": retry_result.notes,
                            "duration": retry_result.duration_seconds,
                        })
                    except Exception as retry_error:
                        results.append({
                            "agent": retry_agent_name,
                            "status": "failed",
                            "records_touched": 0,
                            "notes": f"retry failed: {type(retry_error).__name__}: {retry_error}",
                            "duration": 0.0,
                        })

                    retry_verifier = _agent_class("Verifier")()
                    second_verdict = retry_verifier.run(
                        config,
                        storage_module,
                        stop_conditions={"retry": 1},
                    )
                    results.append({
                        "agent": second_verdict.agent,
                        "status": second_verdict.status,
                        "records_touched": 0,
                        "notes": second_verdict.notes,
                        "duration": second_verdict.duration_seconds,
                        "verdict": second_verdict.verdict,
                    })
                    final_verdict = second_verdict.verdict
                    if second_verdict.status != "ok":
                        cycle_outcome = "degraded"
                    break
        
        except Exception as e:
            # Rule 32: Log failure, continue with remaining plan
            print(f"✗ {task.agent_name:<12} status-failed new-0  | {type(e).__name__}: {str(e)[:50]}")
            results.append({
                "agent": task.agent_name,
                "status": "failed",
                "notes": f"{type(e).__name__}: {str(e)[:50]}",
                "duration": 0.0,
            })
            cycle_outcome = "degraded" if task.agent_name == "Verifier" else "partial"
            if task.agent_name == "Verifier":
                break
    
    # CYCLE SUMMARY (rule 33)
    print("\nCYCLE SUMMARY")
    print("_" * 50)
    
    # If nothing to do, it's a success (rule 6)
    if is_nothing_to_do:
        cycle_outcome = "nothing_to_do"
    
    # Count what ran vs skipped
    core_tasks = [task for task in plan.tasks if task.agent_name != "Verifier"]
    ran_count = sum(1 for task in core_tasks if not task.skipped)
    skipped_count = sum(1 for task in core_tasks if task.skipped)
    initial_agents = {task.agent_name for task in core_tasks if not task.skipped}
    total_new = sum(
        r.get("records_touched", 0)
        for r in results
        if r.get("agent") in initial_agents
    )
    total_duration = sum(r.get("duration", 0.0) for r in results)
    
    if final_verdict is None:
        verifier_results = [
            result for result in results if result.get("agent") == "Verifier"
        ]
        if verifier_results:
            final_verdict = verifier_results[-1].get("verdict")

    print(f"Outcome          : {cycle_outcome}")
    failed_checks = []
    if final_verdict is not None:
        verdict_status = "pass" if final_verdict.passed else "fail"
        failed_checks = [check for check in final_verdict.checks if not check.passed]
    else:
        verdict_status = "not_run"
    print(f"Verdict          : {verdict_status}")
    print(
        f"Failed checks    : "
        f"{', '.join(check.check_name for check in failed_checks) if failed_checks else 'none'}"
    )
    for check in failed_checks:
        print(
            f"  {check.check_name}: observed={check.observed_value} | "
            f"{check.reason}"
        )
    print(f"Retry count      : {retry_count}")
    print(f"Agents run       : {ran_count}  | skipped: {skipped_count}")
    print(f"Total new rows   : {total_new}")
    print(f"Cycle duration   : {total_duration:.1f}s")
    print("_" * 50)
    
    # Return "nothing to do" as success with exit code 0
    if is_nothing_to_do:
        return None
    
    # Return the last result (for backward compatibility with tests)
    return results[-1] if results else None
