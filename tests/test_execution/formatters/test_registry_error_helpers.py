"""Tests for shared probe error construction.

These guard the specific behaviors that regressed during Task 144's baseline
evaluation: available-nodes fallback and node-type-aware enrichment.
"""

from pflow.execution.formatters.registry_error_helpers import (
    build_node_not_found_diagnostic,
    enrich_for_probe,
)


def test_not_found_falls_back_to_available_nodes_when_no_fuzzy_match() -> None:
    """When no fuzzy match exists, show available nodes so agents have something to work with.

    Without this fallback, a typo like 'xyzzy' produces a not-found error
    with zero guidance — the agent has to call registry list separately.
    This exact regression happened during Task 144 implementation.
    """
    d = build_node_not_found_diagnostic("xyzzy", ["shell", "http", "llm", "read-file"])
    similar = (d.context or {}).get("similar_names", [])
    assert len(similar) > 0, "No similar_names — available nodes fallback is broken"
    assert "shell" in similar  # should contain actual available nodes


def test_not_found_prefers_fuzzy_matches_over_full_list() -> None:
    """When fuzzy matches exist, show those — not the full available list."""
    d = build_node_not_found_diagnostic("read", ["read-file", "write-file", "shell", "http"])
    similar = (d.context or {}).get("similar_names", [])
    # "read" is a substring of "read-file" — should find it, not dump all 4 nodes
    assert similar == ["read-file"]


def test_enrich_adds_node_type_as_location() -> None:
    """Probe errors must show the node_type on the At: line.

    The generic exception_to_diagnostics() pipeline doesn't know which node
    was being run. The enrichment adds this context.
    """
    diagnostics = enrich_for_probe(RuntimeError("something failed"), "my-node")
    assert diagnostics[0].node_id == "my-node"


def test_enrich_adds_timeout_specific_suggestions() -> None:
    """Timeout errors should get a timeout-specific suggestion, not generic guidance.

    This was missing in the MCP path before the shared helper was extracted.
    """
    diagnostics = enrich_for_probe(RuntimeError("Connection timeout after 30s"), "fetch")
    suggestions = diagnostics[0].suggestions or []
    assert any("timeout" in s.lower() for s in suggestions), f"No timeout suggestion in: {suggestions}"


def test_enrich_preserves_builtin_suggestions_for_file_errors() -> None:
    """FileNotFoundError already has a good suggestion — don't add a redundant 'registry describe'."""
    diagnostics = enrich_for_probe(FileNotFoundError("input.txt"), "fetch")
    suggestions = diagnostics[0].suggestions or []
    assert any("file path" in s.lower() for s in suggestions)
    assert not any("registry describe" in s for s in suggestions)
