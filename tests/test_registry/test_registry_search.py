"""Essential tests for Registry.search() multi-keyword support.

These tests catch critical bugs in the multi-keyword search implementation.
"""

from pflow.registry import Registry


def test_multi_keyword_and_logic(tmp_path):
    """CRITICAL: Multi-keyword search requires ALL keywords to match (AND logic).

    Real bug this catches: Broken AND logic returns nodes matching ANY keyword.
    If this fails, agents get irrelevant results (e.g., searching "github api" returns all github nodes).
    """
    # Create test registry with sample nodes
    registry = Registry(tmp_path / "registry.json")
    test_nodes = {
        "github-create-pr": {
            "interface": {"description": "Create pull requests on GitHub via API"},
        },
        "github-list-repos": {
            "interface": {"description": "List GitHub repositories"},
        },
        "slack-send-message": {
            "interface": {"description": "Send message via Slack API"},
        },
    }
    registry.save(test_nodes)

    # Search with two keywords
    results = registry.search("github api")

    # Should only return nodes matching BOTH keywords
    node_names = [name for name, _, _ in results]
    assert "github-create-pr" in node_names  # Has "github" + "api"
    assert "github-list-repos" not in node_names  # Has "github" but NO "api"
    assert "slack-send-message" not in node_names  # Has "api" but NO "github"


def test_multi_keyword_score_averaging():
    """CRITICAL: Multi-keyword scores are averaged across keywords.

    Real bug this catches: Score calculation broken (sum instead of average, wrong order).
    If this fails, relevance ranking is wrong.
    """
    registry = Registry()

    # Mock a simple registry state
    test_nodes = {
        "github-api-client": {  # Prefix match "github" (90) + name contains "api" (70) → avg 80
            "interface": {"description": "Client for GitHub API"},
        },
        "github-helper": {  # Prefix match "github" (90) + description contains "api" (50) → avg 70
            "interface": {"description": "Helper functions for GitHub api access"},
        },
    }
    registry.save(test_nodes)

    results = registry.search("github api")

    # Verify score ordering (higher scores first)
    scores = [score for _, _, score in results]
    assert scores == sorted(scores, reverse=True), "Results not sorted by score descending"

    # Verify exact scores (both keywords match, averaged)
    assert len(results) == 2
    assert results[0][2] == 80  # github-api-client: (90 + 70) // 2
    assert results[1][2] == 70  # github-helper: (90 + 50) // 2


def test_single_keyword_backward_compatibility():
    """CRITICAL: Single keyword search still works (no regression).

    Real bug this catches: Multi-keyword implementation breaks single keyword.
    If this fails, existing single-keyword searches are broken.
    """
    registry = Registry()

    test_nodes = {
        "github-create-pr": {
            "interface": {"description": "Create pull requests"},
        },
        "github-list-repos": {
            "interface": {"description": "List repositories"},
        },
        "slack-send": {
            "interface": {"description": "Send message"},
        },
    }
    registry.save(test_nodes)

    # Single keyword should work as before
    results = registry.search("github")

    # Should return both github nodes
    node_names = [name for name, _, _ in results]
    assert len(node_names) == 2
    assert "github-create-pr" in node_names
    assert "github-list-repos" in node_names
    assert "slack-send" not in node_names
