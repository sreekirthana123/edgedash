from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class AgentResult:
    agent: str
    status: str  # "ok", "suspect", or "failed"
    records_touched: int
    notes: str
    duration_seconds: float = 0.0  # Time spent executing this agent
    verdict: Any = None


class Agent(Protocol):
    name: str

    def run(self, config, storage_module, stop_conditions: dict = None) -> AgentResult:
        ...
