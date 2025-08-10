#!/usr/bin/env python3
"""Debug script to examine the planning context sent to WorkflowGeneratorNode's LLM.

This script creates a test scenario and captures the actual planning context
that gets sent to the LLM to understand what node parameter information is included.
"""

import sys
import os
from pathlib import Path

# Add src to path to import pflow modules
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))

from pflow.planning.nodes import WorkflowGeneratorNode, ComponentBrowsingNode
from pflow.planning.context_builder import build_planning_context
from pflow.registry import Registry


def main():
    """Debug the planning context for WorkflowGeneratorNode."""

    print("=== DEBUGGING PLANNING CONTEXT FOR WORKFLOW GENERATOR ===\n")

    # Test case: user wants to read a file and process it
    user_input = "read the file data.csv and analyze it with an LLM"

    print(f"User Input: {user_input}\n")

    # Step 1: Simulate ComponentBrowsingNode selecting relevant nodes
    print("Step 1: Simulating ComponentBrowsingNode selection...")

    # Load registry to see what nodes are available
    registry = Registry()
    registry_metadata = registry.load()

    print(f"Total nodes in registry: {len(registry_metadata)}")

    # Simulate ComponentBrowsingNode selecting read-file and llm nodes
    selected_node_ids = ["read-file", "llm"]
    selected_workflow_names = []  # No workflows for this test

    print(f"Selected nodes: {selected_node_ids}")
    print(f"Selected workflows: {selected_workflow_names}\n")

    # Step 2: Build the planning context that would be sent to WorkflowGeneratorNode
    print("Step 2: Building planning context...")

    planning_context = build_planning_context(
        selected_node_ids=selected_node_ids,
        selected_workflow_names=selected_workflow_names,
        registry_metadata=registry_metadata
    )

    if isinstance(planning_context, dict) and "error" in planning_context:
        print(f"ERROR building planning context: {planning_context}")
        return

    print(f"Planning context length: {len(planning_context)} characters\n")

    # Step 3: Analyze the planning context content
    print("Step 3: Analyzing planning context content...")
    print("=" * 80)
    print(planning_context)
    print("=" * 80)

    # Step 4: Look for specific parameter information
    print("\nStep 4: Analyzing parameter information...\n")

    # Check if file_path parameter is mentioned for read-file
    if "file_path" in planning_context:
        print("✅ 'file_path' parameter found in context")
        # Find all occurrences
        lines = planning_context.split('\n')
        for i, line in enumerate(lines):
            if "file_path" in line:
                print(f"  Line {i+1}: {line.strip()}")
    else:
        print("❌ 'file_path' parameter NOT found in context")

    # Check what parameters are documented for read-file
    print("\n--- Parameters for read-file node ---")
    lines = planning_context.split('\n')
    in_read_file_section = False
    in_parameters_section = False

    for line in lines:
        if "### read-file" in line:
            in_read_file_section = True
            print(f"Found read-file section at line: {line}")
        elif in_read_file_section and line.startswith("### ") and "read-file" not in line:
            # Moved to next section
            in_read_file_section = False
            in_parameters_section = False
        elif in_read_file_section:
            if "**Parameters**" in line:
                in_parameters_section = True
                print(f"Parameters section: {line}")
            elif in_parameters_section and line.startswith("- "):
                print(f"Parameter: {line}")
            elif in_parameters_section and line.strip() == "":
                # End of parameters section
                in_parameters_section = False

    # Check what parameters are documented for llm node
    print("\n--- Parameters for llm node ---")
    in_llm_section = False
    in_parameters_section = False

    for line in lines:
        if "### llm" in line:
            in_llm_section = True
            print(f"Found llm section at line: {line}")
        elif in_llm_section and line.startswith("### ") and "llm" not in line:
            # Moved to next section
            in_llm_section = False
            in_parameters_section = False
        elif in_llm_section:
            if "**Parameters**" in line:
                in_parameters_section = True
                print(f"Parameters section: {line}")
            elif in_parameters_section and line.startswith("- "):
                print(f"Parameter: {line}")
            elif in_parameters_section and line.strip() == "":
                # End of parameters section
                in_parameters_section = False

    # Step 5: Test WorkflowGeneratorNode prep() method directly
    print("\n" + "="*80)
    print("Step 5: Testing WorkflowGeneratorNode.prep() directly...")

    # Create a test shared store like the planner would have
    shared_store = {
        "user_input": user_input,
        "planning_context": planning_context,
        "browsed_components": {
            "node_ids": selected_node_ids,
            "workflow_names": selected_workflow_names,
            "reasoning": "Selected for testing"
        },
        "discovered_params": {"filename": "data.csv"},  # Mock discovered params
        "validation_errors": [],
        "generation_attempts": 0
    }

    # Create WorkflowGeneratorNode and call prep
    generator = WorkflowGeneratorNode()
    prep_result = generator.prep(shared_store)

    print(f"WorkflowGeneratorNode prep() result keys: {list(prep_result.keys())}")
    print(f"Planning context in prep result: {len(prep_result.get('planning_context', ''))} chars")

    # Check if planning context matches what we built
    if prep_result.get('planning_context') == planning_context:
        print("✅ Planning context matches between direct build and node prep")
    else:
        print("❌ Planning context differs between direct build and node prep")
        print(f"Direct: {len(planning_context)} chars")
        print(f"Node prep: {len(prep_result.get('planning_context', ''))} chars")

    print("\n=== SUMMARY ===")
    print(f"1. Planning context is {len(planning_context)} characters long")
    print(f"2. Contains 'file_path': {'YES' if 'file_path' in planning_context else 'NO'}")
    print(f"3. Contains 'Parameters': {'YES' if '**Parameters**' in planning_context else 'NO'}")
    print(f"4. Selected nodes: {selected_node_ids}")

    if "file_path" not in planning_context:
        print("\n❌ PROBLEM IDENTIFIED:")
        print("The planning context does not include parameter specifications like 'file_path'.")
        print("This explains why the LLM doesn't know to use template variables for node parameters.")
    else:
        print("\n✅ Parameter information appears to be included in the context.")


if __name__ == "__main__":
    main()
