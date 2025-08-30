"""Utilities for setting up registry in tests."""

from pathlib import Path

from pflow.registry.registry import Registry
from pflow.registry.scanner import scan_for_nodes


def ensure_test_registry() -> Registry:
    """Ensure a test registry exists with all nodes from src/pflow/nodes.

    This function sets up the registry before tests run, so it's available
    even in isolated filesystems.

    Returns:
        Registry instance with nodes loaded
    """
    registry = Registry()

    # Always populate for tests to ensure consistency
    src_path = Path(__file__).parent.parent.parent / "src"
    nodes_dir = src_path / "pflow" / "nodes"

    if nodes_dir.exists():
        scan_results = scan_for_nodes([nodes_dir])
        registry.update_from_scanner(scan_results)

    return registry
