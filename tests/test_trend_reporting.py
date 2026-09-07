"""Tests for gap trend reporting."""

import pytest
from unittest.mock import Mock, patch
from io import StringIO
from edgedash.gaps import print_gaps_trend


def test_trend_no_snapshots(capsys):
    """Handle case with no snapshots."""
    config = Mock()
    config.db_path = ":memory:"
    
    with patch('edgedash.gaps.storage.get_all_gap_snapshots_by_date', return_value=[]):
        print_gaps_trend(config)
        captured = capsys.readouterr()
        assert "No gap snapshots found" in captured.out


def test_trend_single_snapshot(capsys):
    """Handle case with only one snapshot."""
    config = Mock()
    config.db_path = ":memory:"
    
    snapshot = (
        "run123",
        "2026-09-03T17:00:00+00:00",
        [
            {"skill": "python", "opportunity_cost": 1.5},
            {"skill": "kubernetes", "opportunity_cost": 1.2},
        ]
    )
    
    with patch('edgedash.gaps.storage.get_all_gap_snapshots_by_date', return_value=[snapshot]):
        print_gaps_trend(config)
        captured = capsys.readouterr()
        assert "Only 1 snapshot available" in captured.out
        assert "Need at least 2 to show a trend" in captured.out


def test_trend_two_snapshots(capsys):
    """Show trend with two snapshots."""
    config = Mock()
    config.db_path = ":memory:"
    
    # Latest snapshot
    latest = (
        "abc12345",
        "2026-09-03T18:00:00+00:00",
        [
            {"skill": "python", "opportunity_cost": 2.0},
            {"skill": "kubernetes", "opportunity_cost": 1.8},
            {"skill": "docker", "opportunity_cost": 0.5},
        ]
    )
    
    # Earliest snapshot
    earliest = (
        "xyz67890",
        "2026-09-03T17:00:00+00:00",
        [
            {"skill": "python", "opportunity_cost": 1.5},
            {"skill": "kubernetes", "opportunity_cost": 1.2},
            {"skill": "java", "opportunity_cost": 0.8},
        ]
    )
    
    with patch('edgedash.gaps.storage.get_all_gap_snapshots_by_date', return_value=[latest, earliest]):
        print_gaps_trend(config)
        captured = capsys.readouterr()
        
        # Should show header with snapshot count and run IDs
        assert "Comparing 2 snapshots" in captured.out
        assert "Earliest :" in captured.out
        assert "Latest" in captured.out  # May have spacing variants
        assert "abc12345" in captured.out or "abc1234" in captured.out  # First 8 chars of latest
        assert "xyz67890" in captured.out or "xyz6789" in captured.out  # First 8 chars of earliest
        
        # Should show column headers
        assert "EARLY" in captured.out
        assert "LATEST" in captured.out
        assert "ΔCOST" in captured.out
        assert "Δ%" in captured.out
        assert "NOTE" in captured.out
        
        # Should show trend for current top 10
        assert "python" in captured.out
        assert "kubernetes" in captured.out
        assert "docker" in captured.out
        
        # Should show change values
        assert "+0.50" in captured.out or "+0.5" in captured.out  # python: 2.0 - 1.5
        
        # Should show footer with delta definitions
        assert "ΔCOST = latest opportunity cost minus earliest" in captured.out
        assert "Δ% = percentage change" in captured.out
