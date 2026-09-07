"""Tests for skill canonicalisation."""

import pytest
from edgedash.skills import canonical


@pytest.fixture
def aliases():
    """Sample alias map for testing."""
    return {
        "k8s": "kubernetes",
        "postgres": "postgresql",
        "js": "javascript",
        "node": "node.js",
        "ml": "machine learning",
    }


class TestCanonical:
    def test_lowercase_and_strip(self, aliases):
        """Convert to lowercase and strip whitespace."""
        assert canonical("  PYTHON  ", aliases) == "python"
        assert canonical("JAVA", aliases) == "java"
        assert canonical("  \t  SQL  \n  ", aliases) == "sql"

    def test_parenthetical_drop(self, aliases):
        """Drop parenthetical qualifiers."""
        assert canonical("kubernetes (eks)", aliases) == "kubernetes"
        assert canonical("AWS (amazon web services)", aliases) == "aws"
        assert canonical("Docker (container)", aliases) == "docker"

    def test_internal_whitespace_collapse(self, aliases):
        """Collapse multiple internal spaces to single space."""
        assert canonical("machine   learning", aliases) == "machine learning"
        assert canonical("power    bi", aliases) == "power bi"
        assert canonical("c  ++", aliases) == "c ++"

    def test_alias_mapping(self, aliases):
        """Apply alias map correctly."""
        assert canonical("k8s", aliases) == "kubernetes"
        assert canonical("postgres", aliases) == "postgresql"
        assert canonical("js", aliases) == "javascript"
        assert canonical("node", aliases) == "node.js"
        assert canonical("ml", aliases) == "machine learning"

    def test_no_alias(self, aliases):
        """Return normalized form when no alias exists."""
        assert canonical("python", aliases) == "python"
        assert canonical("docker", aliases) == "docker"
        assert canonical("react", aliases) == "react"

    def test_empty_string(self, aliases):
        """Return empty string for empty input."""
        assert canonical("", aliases) == ""
        assert canonical("   ", aliases) == ""
        assert canonical("\t\n", aliases) == ""

    def test_none_handling(self, aliases):
        """Handle None by returning empty string."""
        assert canonical(None, aliases) == ""

    def test_complex_case(self, aliases):
        """Complex: alias + lowercase + strip + whitespace."""
        assert canonical("  K8S  ", aliases) == "kubernetes"
        assert canonical("  POSTGRES (db)  ", aliases) == "postgresql"
        assert canonical("  JS   (frontend)  ", aliases) == "javascript"

    def test_punctuation_removal(self, aliases):
        """Remove surrounding punctuation."""
        assert canonical('python!', aliases) == "python"
        assert canonical('"java"', aliases) == "java"
        assert canonical('[golang]', aliases) == "golang"
        assert canonical('(rust)', aliases) == "rust"

    def test_numeric_and_special_chars(self, aliases):
        """Handle numeric and special characters correctly."""
        assert canonical("c++", aliases) == "c++"
        assert canonical("c#", aliases) == "c#"
        assert canonical("node.js", aliases) == "node.js"

    def test_empty_alias_map(self):
        """Work with empty alias map."""
        assert canonical("python", {}) == "python"
        assert canonical("K8S", {}) == "k8s"

    def test_case_insensitive_whitespace(self, aliases):
        """Combine case insensitivity with whitespace normalization."""
        result = canonical("  MaChInE   LeArNiNg  ", aliases)
        assert result == "machine learning"

    def test_singletons_not_aliased(self, aliases):
        """Single-word skills without aliases pass through."""
        result = canonical("terraform", aliases)
        assert result == "terraform"
