#!/usr/bin/env python3
"""
TEMPORARY REGISTRY POPULATION SCRIPT FOR MVP

This script manually populates the node registry by scanning the nodes directory.
This is a temporary solution until Task 10 implements proper CLI commands for
registry management (pflow registry list, pflow registry scan, etc.).

Usage:
    python scripts/populate_registry.py

Note: In production, the registry will be populated automatically or via CLI commands.
This script exists only to enable Task 3 testing and early MVP development.

TODO: Remove this script after Task 10 is implemented.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import pflow modules
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.pflow.registry import Registry, scan_for_nodes
except ImportError as e:
    print("Error: Could not import pflow modules. Make sure you've installed the package:")
    print("  pip install -e .")
    print("  or: uv pip install -e .")
    print(f"\nOriginal error: {e}")
    sys.exit(1)


def main():
    """Scan for nodes and populate the registry."""
    # Get the nodes directory relative to script location
    project_root = Path(__file__).parent.parent
    nodes_dir = project_root / "src" / "pflow" / "nodes"

    if not nodes_dir.exists():
        print(f"Error: Nodes directory not found at {nodes_dir}")
        sys.exit(1)

    print("=" * 60)
    print("TEMPORARY REGISTRY POPULATION SCRIPT")
    print("This will be replaced by 'pflow registry' commands in Task 10")
    print("=" * 60)
    print()

    # Automatically discover all subdirectories under nodes/
    # This includes file/, github/, git/, llm/, etc.
    node_directories = []

    # Find all subdirectories (excluding __pycache__)
    for subdir in nodes_dir.iterdir():
        if subdir.is_dir() and subdir.name != "__pycache__" and not subdir.name.startswith("__"):
            node_directories.append(subdir)
            print(f"Found node package: {subdir.name}/")

    # If no subdirectories found, scan the main directory
    # This handles the case where nodes are directly in src/pflow/nodes/
    if not node_directories:
        print("No subdirectories found, scanning main nodes directory")
        node_directories.append(nodes_dir)

    print(f"\nScanning {len(node_directories)} directories for nodes...")

    try:
        # Scan for nodes in all discovered directories
        scan_results = scan_for_nodes(node_directories)

        if not scan_results:
            print("Warning: No nodes found!")
            print("Make sure Task 11 (file nodes) has been implemented.")
            sys.exit(1)

        print(f"\nFound {len(scan_results)} nodes:")
        for node in scan_results:
            print(f"  - {node['name']:20} ({node['class_name']})")

        # Create and update registry
        registry_path = Path.home() / ".pflow" / "registry.json"
        registry = Registry(registry_path)
        registry.update_from_scanner(scan_results)

        print(f"\nRegistry saved to: {registry_path}")

        # Verify by loading
        nodes = registry.load()
        print(f"Registry now contains {len(nodes)} nodes")
        print("\nRegistry population complete! You can now run workflows.")

    except Exception as e:
        print(f"\nError during registry population: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure you've installed the package: pip install -e .")
        print("2. Ensure Task 11 (file nodes) is implemented")
        print("3. Check that nodes inherit from pocketflow.BaseNode")
        sys.exit(1)


if __name__ == "__main__":
    main()
