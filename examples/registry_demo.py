#!/usr/bin/env python3
"""Demonstration of the pflow Registry functionality."""

import json
from pathlib import Path

from pflow.registry import Registry, scan_for_nodes


def main():
    """Demonstrate Registry usage."""
    print("=== pflow Registry Demo ===\n")

    # Get the nodes directory
    project_root = Path(__file__).parent.parent
    nodes_dir = project_root / "src" / "pflow" / "nodes"

    print(f"1. Scanning for nodes in: {nodes_dir}")
    scan_results = scan_for_nodes([nodes_dir])
    print(f"   Found {len(scan_results)} nodes")

    # Create a registry instance
    registry_path = Path.home() / ".pflow" / "registry.json"
    registry = Registry(registry_path)

    print(f"\n2. Updating registry at: {registry_path}")
    registry.update_from_scanner(scan_results)

    # Load and display
    print("\n3. Loading registry contents:")
    nodes = registry.load()

    for name, metadata in sorted(nodes.items()):
        print(f"\n   Node: {name}")
        print(f"   - Module: {metadata['module']}")
        print(f"   - Class: {metadata['class_name']}")
        print(f"   - Docstring: {metadata['docstring'][:50]}...")

    print("\n4. Registry JSON structure preview:")
    print(json.dumps(next(iter(nodes.items())) if nodes else {}, indent=2))

    print("\n✅ Registry demo complete!")
    print(f"   Registry saved to: {registry_path}")
    print(f"   Total nodes registered: {len(nodes)}")


if __name__ == "__main__":
    main()
