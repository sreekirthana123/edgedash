from datetime import datetime, timezone
from unittest.mock import patch

from edgedash.query.tools import TOOLS, seniority_distribution


def test_seniority_distribution_shape_and_clamping():
    with patch(
        "edgedash.query.tools.storage.get_last_passing_cycle",
        return_value={"timestamp": "2026-09-05T00:00:00+00:00"},
    ), patch(
        "edgedash.query.tools.storage.get_seniority_distribution",
        return_value=[
            {"seniority": "mid", "listing_count": 4},
            {"seniority": "senior", "listing_count": 2},
        ],
    ) as read_distribution:
        result = seniority_distribution(
            999,
            db_path="test.db",
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert "seniority_distribution" in TOOLS
    assert isinstance(result["rows"], list)
    assert all(isinstance(row, dict) for row in result["rows"])
    assert result["summary"] == "Seniority breakdown over the last 90 days."
    assert read_distribution.call_args.args[1] == "2026-06-08T00:00:00+00:00"