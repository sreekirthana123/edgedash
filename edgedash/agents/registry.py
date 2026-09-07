"""Agent registry: centralized mapping of agent names to classes.

Per rule 30: Orchestrator knows nothing about agent implementations.
It resolves agents by name from the registry only.
"""

from edgedash.agents.fetcher import Fetcher
from edgedash.agents.scorer import Scorer
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.agents.verifier import Verifier


def build_agents() -> dict:
    """Build the centralized agent registry."""
    return {
        "Fetcher": Fetcher,
        "Scorer": Scorer,
        "GapAnalyzer": GapAnalyzer,
        "Verifier": Verifier,
    }


AGENTS = build_agents()


def get_agent_class(agent_name: str):
    """Get agent class by name, or raise KeyError if not found."""
    return AGENTS[agent_name]
