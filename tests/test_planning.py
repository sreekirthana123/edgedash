"""Tests for state inspection and planning."""

import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from edgedash.state import read_state
from edgedash.planning import build_plan


@dataclass
class MockConfig:
    """Mock config for testing."""
    db_path: str = ":memory:"
    score_batch_size: int = 25
    fetch_interval_hours: int = 6


class MockStorage:
    """Mock storage for testing state queries."""
    
    def __init__(
        self,
        last_fetch_at=None,
        unscored_count=0,
        gaps_computed_at=None,
        has_newer_scores=False,
        last_cycle_started_at=None,
    ):
        self.last_fetch_at = last_fetch_at
        self.unscored_count = unscored_count
        self.gaps_computed_at = gaps_computed_at
        self.has_newer_scores = has_newer_scores
        self.last_cycle_started_at = last_cycle_started_at
    
    def last_fetch_time(self, db_path):
        return self.last_fetch_at
    
    def count_unscored(self, db_path):
        return self.unscored_count
    
    def get_latest_gap_snapshots(self, db_path):
        if self.gaps_computed_at:
            return [{"timestamp": self.gaps_computed_at}]
        return []
    
    def get_conn(self, db_path):
        """Return a mock connection."""
        return MockConnection(self.has_newer_scores, self.last_cycle_started_at)


class MockConnection:
    """Mock database connection."""
    
    def __init__(self, has_newer_scores, last_cycle_started_at):
        self.has_newer_scores = has_newer_scores
        self.last_cycle_started_at = last_cycle_started_at
    
    def execute(self, query):
        if "MAX(fit_score_set_at)" in query:
            return MockCursor([(None,)] if not self.has_newer_scores else [(datetime.now(timezone.utc).isoformat(),)])
        elif "MAX(started_at)" in query:
            return MockCursor([(self.last_cycle_started_at,)])
        return MockCursor([(None,)])
    
    def close(self):
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class MockCursor:
    """Mock database cursor."""
    
    def __init__(self, rows):
        self.rows = rows
    
    def fetchone(self):
        return self.rows[0] if self.rows else None


class TestReadState:
    """Tests for read_state()."""
    
    def test_state_never_fetched(self):
        """State when nothing has ever been fetched."""
        config = MockConfig()
        storage = MockStorage(
            last_fetch_at=None,
            unscored_count=42,
            gaps_computed_at=None,
        )
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        
        state = read_state(config, storage, now)
        
        assert state["last_fetch_at"] is None
        assert state["hours_since_fetch"] is None
        assert state["unscored_count"] == 42
        assert state["gaps_computed_at"] is None
        assert state["gaps_stale"] is True  # No gaps exist
    
    def test_state_fresh_fetch(self):
        """State with a fresh fetch within interval."""
        config = MockConfig(fetch_interval_hours=6)
        two_hours_ago = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        storage = MockStorage(
            last_fetch_at=two_hours_ago,
            unscored_count=15,
            gaps_computed_at=None,
        )
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        
        state = read_state(config, storage, now)
        
        assert state["hours_since_fetch"] == 2.0
        assert state["unscored_count"] == 15
        assert state["gaps_stale"] is True
    
    def test_state_stale_fetch(self):
        """State with a stale fetch (outside interval)."""
        config = MockConfig(fetch_interval_hours=6)
        ten_hours_ago = datetime(2026, 9, 5, 2, 0, 0, tzinfo=timezone.utc).isoformat()
        storage = MockStorage(
            last_fetch_at=ten_hours_ago,
            unscored_count=0,
        )
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        
        state = read_state(config, storage, now)
        
        assert state["hours_since_fetch"] == 10.0
        assert state["unscored_count"] == 0


class TestBuildPlan:
    """Tests for build_plan()."""
    
    def test_plan_everything_stale(self):
        """Plan when everything needs work."""
        config = MockConfig()
        state = {
            "last_fetch_at": None,
            "hours_since_fetch": None,
            "unscored_count": 42,
            "gaps_computed_at": None,
            "gaps_stale": True,
            "last_cycle_started_at": None,
        }
        
        plan = build_plan(state, config)
        
        assert len(plan.tasks) == 4
        assert all(not t.skipped for t in plan.tasks)
        
        # Check agent order
        assert plan.tasks[0].agent_name == "Fetcher"
        assert plan.tasks[1].agent_name == "Scorer"
        assert plan.tasks[2].agent_name == "GapAnalyzer"
        assert plan.tasks[3].agent_name == "Verifier"
        
        # Check reasons
        assert "never fetched" in plan.tasks[0].reason
        assert "unscored_count=42" in plan.tasks[1].reason
        assert "gaps never computed" in plan.tasks[2].reason
    
    def test_plan_nothing_to_do(self):
        """Plan when nothing needs work (all skipped)."""
        config = MockConfig(fetch_interval_hours=6)
        two_hours_ago = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        state = {
            "last_fetch_at": two_hours_ago,
            "hours_since_fetch": 2.0,
            "unscored_count": 0,
            "gaps_computed_at": two_hours_ago,
            "gaps_stale": False,
            "last_cycle_started_at": two_hours_ago,
        }
        
        plan = build_plan(state, config)
        
        assert len(plan.tasks) == 4
        assert all(t.skipped for t in plan.tasks)
        
        # Check reasons
        assert "hours_since_fetch=2.0 < 6" in plan.tasks[0].reason
        assert "unscored_count=0" in plan.tasks[1].reason
        assert "gaps_stale=false" in plan.tasks[2].reason

        # Verifier: skipped — nothing produced, nothing pending
        assert plan.tasks[3].agent_name == "Verifier"
        assert plan.tasks[3].skipped is True
    
    def test_plan_only_unscored(self):
        """Plan when only Scorer should run."""
        config = MockConfig(fetch_interval_hours=6)
        two_hours_ago = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        state = {
            "last_fetch_at": two_hours_ago,
            "hours_since_fetch": 2.0,
            "unscored_count": 10,
            "gaps_computed_at": two_hours_ago,
            "gaps_stale": False,
            "last_cycle_started_at": two_hours_ago,
        }
        
        plan = build_plan(state, config)
        
        # Fetcher: skipped (fresh)
        assert plan.tasks[0].skipped is True
        
        # Scorer: running (unscored items exist)
        assert plan.tasks[1].skipped is False
        assert "unscored_count=10" in plan.tasks[1].reason
        
        # GapAnalyzer: skipped (not stale)
        assert plan.tasks[2].skipped is True

        # Verifier: runs last because the cycle will score new output
        assert plan.tasks[3].agent_name == "Verifier"
        assert plan.tasks[3].skipped is False
        assert "new output" in plan.tasks[3].reason
    
    def test_plan_gaps_stale_no_unscored(self):
        """Plan when gaps are stale but nothing unscored (unusual but valid)."""
        config = MockConfig(fetch_interval_hours=6)
        two_hours_ago = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        state = {
            "last_fetch_at": two_hours_ago,
            "hours_since_fetch": 2.0,
            "unscored_count": 0,
            "gaps_computed_at": two_hours_ago,
            "gaps_stale": True,  # Stale, but no work to do
            "last_cycle_started_at": two_hours_ago,
        }
        
        plan = build_plan(state, config)
        
        # Fetcher & Scorer: skipped
        assert plan.tasks[0].skipped is True
        assert plan.tasks[1].skipped is True
        
        # GapAnalyzer: running (gaps are stale)
        assert plan.tasks[2].skipped is False
        assert "gaps_stale=true" in plan.tasks[2].reason

        # Verifier: skipped — no fetch, no score, no unverified backlog
        assert plan.tasks[3].agent_name == "Verifier"
        assert plan.tasks[3].skipped is True
    
    def test_verifier_scheduled_after_gap_analyzer_when_fetch_will_run(self):
        """Verifier is the final task when the cycle will fetch new data."""
        config = MockConfig(fetch_interval_hours=6)
        state = {
            "last_fetch_at": None,
            "hours_since_fetch": None,
            "unscored_count": 0,
            "gaps_computed_at": None,
            "gaps_stale": True,
            "last_cycle_started_at": None,
        }
        plan = build_plan(state, config)
        assert plan.tasks[3].agent_name == "Verifier"
        assert plan.tasks[3].skipped is False
        assert "new output" in plan.tasks[3].reason

    def test_verifier_scheduled_when_unverified_backlog_exists(self):
        """Verifier runs even without fetch/score when earlier output is
        still unverified."""
        config = MockConfig(fetch_interval_hours=6)
        two_hours_ago = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        state = {
            "last_fetch_at": two_hours_ago,
            "hours_since_fetch": 2.0,
            "unscored_count": 0,
            "gaps_computed_at": two_hours_ago,
            "gaps_stale": False,
            "unverified_count": 4,
            "last_cycle_started_at": two_hours_ago,
        }
        plan = build_plan(state, config)
        assert plan.tasks[3].agent_name == "Verifier"
        assert plan.tasks[3].skipped is False
        assert "unverified_count=4" in plan.tasks[3].reason

    def test_plan_render_nothing_to_do(self):
        """Test the rendered plan output for 'nothing to do' state."""
        config = MockConfig(fetch_interval_hours=6)
        two_hours_ago = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        state = {
            "last_fetch_at": two_hours_ago,
            "hours_since_fetch": 2.0,
            "unscored_count": 0,
            "gaps_computed_at": two_hours_ago,
            "gaps_stale": False,
            "last_cycle_started_at": two_hours_ago,
        }
        
        plan = build_plan(state, config)
        rendered = plan.render()
        
        # Should show all tasks as skipped with reasons
        assert "X Fetcher" in rendered
        assert "X Scorer" in rendered
        assert "X GapAnalyzer" in rendered
        assert "X Verifier" in rendered
        assert "hours_since_fetch=2.0 < 6" in rendered
        assert "unscored_count=0" in rendered
        assert "gaps_stale=false" in rendered
