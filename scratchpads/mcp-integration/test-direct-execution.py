#!/usr/bin/env python
"""Test direct execution of MCP node through pflow runtime."""

import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


def test_mcp_workflow():
    """Test MCP workflow execution directly."""
    print("Testing MCP Workflow Direct Execution")
    print("=" * 60)

    # Create a simple workflow IR
    workflow_ir = {
        "name": "test-mcp",
        "description": "Test MCP tool",
        "nodes": [{"id": "list-dirs", "type": "mcp-filesystem-list_allowed_directories", "params": {}}],
        "edges": [],
    }

    print("\n1. Workflow IR:")
    print(json.dumps(workflow_ir, indent=2))

    # Load registry
    print("\n2. Loading registry...")
    registry = Registry()
    nodes = registry.load()

    # Check if MCP node is registered
    node_type = "mcp-filesystem-list_allowed_directories"
    if node_type in nodes:
        print(f"   ✓ Found {node_type} in registry")
        print(f"   Module: {nodes[node_type]['module']}")
        print(f"   Class: {nodes[node_type]['class_name']}")
    else:
        print(f"   ❌ {node_type} not found in registry!")
        print("   Available MCP nodes:")
        mcp_nodes = [k for k in nodes if k.startswith("mcp-")]
        for node in mcp_nodes[:5]:
            print(f"     - {node}")
        return

    # Compile workflow
    print("\n3. Compiling workflow...")
    try:
        flow = compile_ir_to_flow(workflow_ir, registry)
        print("   ✓ Workflow compiled successfully")
    except Exception as e:
        print(f"   ❌ Compilation failed: {e}")
        import traceback

        traceback.print_exc()
        return

    # Execute workflow
    print("\n4. Executing workflow...")
    shared = {}

    try:
        result = flow.run(shared)
        print(f"   ✓ Execution complete: {result}")
        print("\n5. Shared store contents:")
        for key, value in shared.items():
            value_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            print(f"   {key}: {value_str}")
    except Exception as e:
        print(f"   ❌ Execution failed: {e}")
        import traceback

        traceback.print_exc()


def check_mcp_in_registry():
    """Check what MCP tools are in the registry."""
    print("\nChecking MCP Tools in Registry")
    print("=" * 60)

    registry = Registry()
    nodes = registry.load()

    mcp_nodes = [k for k in nodes if k.startswith("mcp-")]

    if mcp_nodes:
        print(f"Found {len(mcp_nodes)} MCP nodes:")
        for node_name in mcp_nodes[:10]:
            node_info = nodes[node_name]
            print(f"\n  {node_name}:")
            print(f"    Module: {node_info.get('module')}")
            print(f"    Class: {node_info.get('class_name')}")
            if "interface" in node_info:
                desc = node_info["interface"].get("description", "")[:60]
                print(f"    Description: {desc}...")
    else:
        print("No MCP nodes found in registry!")
        print("\nRun these commands to set up MCP:")
        print("  1. pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp")
        print("  2. pflow mcp sync filesystem")


if __name__ == "__main__":
    check_mcp_in_registry()
    print()
    test_mcp_workflow()
