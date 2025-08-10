#!/usr/bin/env python
"""Debug script to understand what the generator is actually producing."""

import json
import logging

from pflow.planning.nodes import ComponentBrowsingNode, ParameterDiscoveryNode, WorkflowGeneratorNode

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def debug_generation():
    """Test what's actually happening in the generator."""
    shared = {"user_input": "Create an issue triage report for bugs in project-x with high priority"}

    print("\n=== USER INPUT ===")
    print(shared["user_input"])

    # Step 1: Parameter Discovery
    print("\n=== PARAMETER DISCOVERY ===")
    discovery_node = ParameterDiscoveryNode()
    prep_res = discovery_node.prep(shared)
    exec_res = discovery_node.exec(prep_res)
    discovery_node.post(shared, prep_res, exec_res)

    discovered = shared.get("discovered_params", {})
    print(f"Discovered parameters: {json.dumps(discovered, indent=2)}")

    # Step 2: Component Browsing
    print("\n=== COMPONENT BROWSING ===")
    browsing_node = ComponentBrowsingNode()
    prep_res = browsing_node.prep(shared)
    exec_res = browsing_node.exec(prep_res)
    browsing_node.post(shared, prep_res, exec_res)

    components = shared.get("browsed_components", {})
    print(f"Selected node types: {components.get('node_ids', [])}")
    print(f"Selected workflows: {components.get('workflow_names', [])}")

    # Check planning context
    print("\n=== PLANNING CONTEXT (first 500 chars) ===")
    context = shared.get("planning_context", "")
    if isinstance(context, str):
        print(context[:500] + "..." if len(context) > 500 else context)
    else:
        print(f"Context is not a string: {type(context)}")

    # Step 3: Workflow Generation
    print("\n=== WORKFLOW GENERATION ===")
    generator_node = WorkflowGeneratorNode()
    prep_res = generator_node.prep(shared)

    print(f"\nGenerator prep_res keys: {prep_res.keys()}")
    print(f"Planning context available: {bool(prep_res.get('planning_context'))}")
    print(f"Discovered params in prep: {prep_res.get('discovered_params')}")

    exec_res = generator_node.exec(prep_res)
    generator_node.post(shared, prep_res, exec_res)

    workflow = shared["generated_workflow"]

    print("\n=== GENERATED WORKFLOW ===")
    print(f"IR Version: {workflow.get('ir_version')}")
    print(f"Has inputs field: {'inputs' in workflow}")

    print(f"\nInputs defined: {list(workflow.get('inputs', {}).keys())}")

    nodes = workflow.get("nodes", [])
    print(f"\nNodes ({len(nodes)}):")
    for node in nodes:
        print(f"  - {node['id']}: {node['type']}")
        if "$" in str(node.get("params", {})):
            print(f"    Template vars: {[p for p in str(node['params']) if '$' in p]}")

    edges = workflow.get("edges", [])
    print(f"\nEdges ({len(edges)}):")
    for edge in edges:
        print(f"  - {edge['from']} -> {edge['to']}")

    # Check for template variables
    workflow_str = json.dumps(workflow)
    template_count = workflow_str.count("$")
    print(f"\nTemplate variables found: {template_count} occurrences of '$'")

    return workflow


if __name__ == "__main__":
    try:
        workflow = debug_generation()
        print("\n✅ Generation successful")
    except Exception as e:
        print(f"\n❌ Generation failed: {e}")
        import traceback

        traceback.print_exc()
