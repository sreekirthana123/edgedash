"""Tests for gap analyzer agent."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from edgedash.agents.gap_analyzer import GapAnalyzer


@pytest.fixture
def mock_config():
    """Mock config with user skills."""
    config = Mock()
    config.my_skills = ["python", "sql", "tableau", "excel"]
    config.skill_aliases = {
        "k8s": "kubernetes",
        "postgres": "postgresql",
        "js": "javascript",
        "ml": "machine learning",
    }
    config.db_path = ":memory:"
    return config


@pytest.fixture
def mock_storage():
    """Mock storage module."""
    storage = MagicMock()
    storage.get_listings = Mock(return_value=[])
    storage.save_gap_snapshot = Mock()
    return storage


class TestGapAnalyzer:
    def test_run_no_scored_listings(self, mock_config, mock_storage):
        """Return early if no scored listings."""
        analyzer = GapAnalyzer()
        mock_storage.get_listings.return_value = []

        result = analyzer.run(mock_config, mock_storage)

        assert result.status == "ok"
        assert result.records_touched == 0
        assert "no scored listings" in result.notes

    def test_analyse_gaps_single_listing(self, mock_config):
        """Compute gaps for one listing."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 85,
                "extracted": {
                    "required_skills": ["python", "kubernetes", "postgresql"],
                    "nice_to_have": ["docker"],
                },
            }
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        # Should have 2 gaps: kubernetes and postgresql (python and sql are in my_skills)
        assert "kubernetes" in gaps
        assert "postgresql" in gaps
        assert "python" not in gaps
        assert "sql" not in gaps  # mapped from postgresql

        # kubernetes: 1 listing, score 85
        assert gaps["kubernetes"]["listings_blocked"] == 1
        assert gaps["kubernetes"]["opportunity_cost"] == 0.85
        assert gaps["kubernetes"]["mean_score"] == 85.0

    def test_analyse_gaps_multiple_listings(self, mock_config):
        """Compute aggregated opportunity cost across listings."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 90,
                "extracted": {
                    "required_skills": ["kubernetes"],
                    "nice_to_have": [],
                },
            },
            {
                "id": "listing2",
                "fit_score": 80,
                "extracted": {
                    "required_skills": ["kubernetes"],
                    "nice_to_have": [],
                },
            },
            {
                "id": "listing3",
                "fit_score": 40,
                "extracted": {
                    "required_skills": ["kubernetes"],
                    "nice_to_have": [],
                },
            },
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        # kubernetes should aggregate all three
        assert gaps["kubernetes"]["listings_blocked"] == 3
        # opportunity_cost = 0.90 + 0.80 + 0.40 = 2.10
        assert gaps["kubernetes"]["opportunity_cost"] == pytest.approx(2.10, abs=0.01)
        # mean = (90 + 80 + 40) / 3 = 70
        assert gaps["kubernetes"]["mean_score"] == pytest.approx(70.0, abs=0.1)

    def test_analyse_gaps_canonical_mapping(self, mock_config):
        """Skills are canonicalised before comparison."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 85,
                "extracted": {
                    "required_skills": ["k8s", "kubernetes"],  # Both map to "kubernetes"
                    "nice_to_have": [],
                },
            }
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        # Both "k8s" and "kubernetes" should map to same canonical form
        assert "kubernetes" in gaps
        # Should count as 2 separate mentions of same skill
        assert gaps["kubernetes"]["listings_blocked"] == 2
        assert gaps["kubernetes"]["opportunity_cost"] == pytest.approx(1.70, abs=0.01)

    def test_analyse_gaps_nice_to_have_separate(self, mock_config):
        """Nice-to-have skills tracked separately from required."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 80,
                "extracted": {
                    "required_skills": ["kubernetes"],
                    "nice_to_have": ["docker", "kubernetes"],  # kubernetes in both
                },
            }
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        assert gaps["kubernetes"]["listings_blocked"] == 1  # Required count
        assert gaps["kubernetes"]["nice_to_have_count"] == 1  # Nice-to-have count (separate)

    def test_analyse_gaps_user_skills_not_gaps(self, mock_config):
        """Skills matching user's my_skills are not gaps."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 80,
                "extracted": {
                    "required_skills": ["python", "sql", "tableau", "excel"],
                    "nice_to_have": [],
                },
            }
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        # No gaps since all skills in my_skills
        assert len(gaps) == 0

    def test_analyse_gaps_top_examples(self, mock_config):
        """Top 5 example IDs sorted by score descending."""
        analyzer = GapAnalyzer()

        # Create 7 listings with kubernetes gap
        scored_listings = [
            {
                "id": f"listing{i}",
                "fit_score": score,
                "extracted": {
                    "required_skills": ["kubernetes"],
                    "nice_to_have": [],
                },
            }
            for i, score in enumerate([50, 95, 60, 85, 70, 75, 40], 1)
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        # Should have top 5 examples sorted by score (95, 85, 75, 70, 60)
        top_5_ids = gaps["kubernetes"]["example_ids"]
        assert len(top_5_ids) == 5
        # IDs should correspond to scores 95, 85, 75, 70, 60
        assert top_5_ids == ["listing2", "listing4", "listing6", "listing5", "listing3"]

    def test_analyse_gaps_empty_extracted(self, mock_config):
        """Handle listings with missing extracted facts gracefully."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 80,
                "extracted": {},  # Empty extraction (no skills)
            }
        ]

        gaps = analyzer._analyse_gaps(scored_listings, mock_config)

        # Should handle gracefully (no crashes)
        assert isinstance(gaps, dict)
        assert len(gaps) == 0  # No gaps extracted

    def test_run_with_gaps(self, mock_config, mock_storage):
        """Run creates snapshots for found gaps."""
        analyzer = GapAnalyzer()

        scored_listings = [
            {
                "id": "listing1",
                "fit_score": 85,
                "extracted": {
                    "required_skills": ["kubernetes", "docker"],
                    "nice_to_have": [],
                },
            }
        ]

        # Mock storage to return our test data and init_db
        mock_storage.init_db = Mock()
        mock_storage.get_listings.return_value = scored_listings
        mock_storage.get_extraction_cache = Mock(return_value={"required_skills": ["kubernetes", "docker"], "nice_to_have": []})

        result = analyzer.run(mock_config, mock_storage)

        assert result.status == "ok"
        # Should save 2 snapshots (kubernetes and docker are gaps)
        assert result.records_touched == 2
        assert "2 gaps" in result.notes
