# Adding a Fourth Agent to EdgeDash

The orchestrator architecture is designed for minimal coupling when adding new agents. To add a fourth agent:

## Step 1: Create the Agent Class

Create a new agent module (e.g., `edgedash/agents/verifier.py`) that:
- Implements a class with:
  - `name: str` class attribute (e.g., "Verifier")
  - `run(config, storage_module, stop_conditions: dict = None) -> AgentResult` method
- Returns an `AgentResult` with `duration_seconds` set
- Respects the stop conditions passed to it (e.g., `max_seconds`)

Example:
```python
from edgedash.agents.base import AgentResult

class Verifier:
    name = "Verifier"
    
    def run(self, config, storage_module, stop_conditions: dict = None) -> AgentResult:
        start_time = datetime.utcnow()
        stop_conditions = stop_conditions or {}
        max_seconds = stop_conditions.get("max_seconds", 60)
        
        # Your agent logic here
        # Respect max_seconds when checking timeout
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=n,
            notes="...",
            duration_seconds=duration,
        )
```

## Step 2: Register the Agent

Add the agent to `edgedash/agents/registry.py`:

```python
from edgedash.agents.verifier import Verifier

AGENTS = {
    "Fetcher": Fetcher,
    "Scorer": Scorer,
    "GapAnalyzer": GapAnalyzer,
    "Verifier": Verifier,  # <- Add here
}
```

## Step 3: Add Decision Rule to Planner

Add a decision rule in `edgedash/planning.py` → `build_plan()`:

```python
# === VERIFIER ===
should_verify = state["some_condition"]  # Define your condition

if should_verify:
    reason = "your decision reason"
    tasks.append(Task(
        agent_name="Verifier",
        goal="verify cycle output",
        stop_conditions={"max_seconds": 60},
        reason=reason,
        skipped=False,
    ))
else:
    reason = "skipped: your skip reason"
    tasks.append(Task(
        agent_name="Verifier",
        goal="verify cycle output",
        stop_conditions={"max_seconds": 60},
        reason=reason,
        skipped=True,
    ))
```

**That's it.** The Orchestrator will:
- Automatically resolve "Verifier" from the registry
- Pass the stop_conditions to your agent
- Handle failures gracefully (per rule 32)
- Include the agent in cycle summary (per rule 33)

No changes to `orchestrator.py` are needed. The architecture is extensible by design.

## Design Principles

- **Registry pattern**: Agents are registered by name; orchestrator doesn't import them
- **Stop conditions protocol**: Each agent accepts `stop_conditions: dict` and respects the limits
- **Error isolation**: One agent failure doesn't stop the cycle
- **State-driven**: Decision to run an agent is based on read state, not fixed sequence
- **Minimal coupling**: Adding an agent requires only registry entry + planner rule
