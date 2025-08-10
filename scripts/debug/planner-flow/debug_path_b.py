"""Debug script to understand Path B workflow generation issues.

This script runs the planner with detailed logging to see:
1. What workflow is generated
2. What validation errors occur
3. Whether errors are fed back to the LLM
4. What parameters are extracted
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning import create_planner_flow

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _print_path_b_results(shared):
    """Helper function to print Path B results."""
    # 2. Show the generated workflow
    generated = shared["generated_workflow"]
    print("\n📋 GENERATED WORKFLOW:")
    print(json.dumps(generated, indent=2))

    # 3. Check generation attempts (retries)
    attempts = shared.get("generation_attempts", 1)
    print(f"\n🔄 Generation attempts: {attempts}")

    # 4. Check validation errors
    if "validation_errors" in shared:
        print("\n❌ VALIDATION ERRORS (fed to retry):")
        for error in shared["validation_errors"]:
            print(f"  - {error}")

    # 5. Check discovered parameters (hints for generation)
    if "discovered_params" in shared:
        print("\n💡 DISCOVERED PARAMS (hints):")
        print(json.dumps(shared["discovered_params"], indent=2))

    # 6. Check extracted parameters (actual values)
    if "extracted_params" in shared:
        print("\n📦 EXTRACTED PARAMS (actual values):")
        print(json.dumps(shared["extracted_params"], indent=2))

    # 7. Check missing parameters
    if "missing_params" in shared:
        print("\n⚠️ MISSING PARAMS:")
        for param in shared["missing_params"]:
            print(f"  - {param}")


def debug_path_b_generation():
    """Debug Path B workflow generation with detailed output."""

    print("\n" + "=" * 80)
    print("PATH B DEBUG: Workflow Generation")
    print("=" * 80)

    # Create test workflow manager
    with tempfile.TemporaryDirectory() as tmpdir:
        workflows_dir = Path(tmpdir) / "workflows"
        workflows_dir.mkdir()
        workflow_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        # Test input that should trigger Path B
        user_input = "Read the file data.csv and extract the first column"
        print(f"\n📝 USER INPUT: '{user_input}'")
        print("-" * 80)

        # Create and run the planner flow
        flow = create_planner_flow()
        shared = {
            "user_input": user_input,
            "workflow_manager": workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Run the complete flow
        print("\n🚀 Running planner flow...")
        flow.run(shared)

        # Examine the results
        print("\n" + "=" * 80)
        print("RESULTS ANALYSIS")
        print("=" * 80)

        # 1. Check which path was taken
        if "found_workflow" in shared:
            print("\n✅ Path A taken (found existing workflow)")
        elif "generated_workflow" in shared:
            print("\n✅ Path B taken (generated new workflow)")
            _print_path_b_results(shared)

        # 8. Final planner output
        output = shared.get("planner_output", {})
        print("\n📊 PLANNER OUTPUT:")
        print(f"  Success: {output.get('success')}")
        if output.get("error"):
            print(f"  Error: {output['error']}")
        if output.get("workflow_metadata"):
            print(f"  Metadata: {output['workflow_metadata'].get('suggested_name')}")

        # 9. Analyze workflow structure issues
        if "generated_workflow" in shared:
            analyze_workflow_issues(shared["generated_workflow"], user_input)

        return shared


def _analyze_inputs(workflow):
    """Helper to analyze workflow inputs."""
    unused_inputs = []
    if "inputs" in workflow:
        print("\n📥 DECLARED INPUTS:")
        for name, spec in workflow["inputs"].items():
            print(f"  - {name}: {spec.get('type', 'unknown')} (required: {spec.get('required', False)})")

        # Check if inputs are used in nodes
        print("\n🔍 TEMPLATE VARIABLE USAGE:")
        for input_name in workflow["inputs"]:
            template_var = f"${input_name}"
            workflow_str = json.dumps(workflow)
            # Count occurrences (should be at least 2: once in inputs, once in params)
            occurrences = workflow_str.count(template_var)
            if occurrences <= 1:
                unused_inputs.append(input_name)
                print(f"  ❌ ${input_name} - UNUSED (only in inputs declaration)")
            else:
                print(f"  ✅ ${input_name} - Used {occurrences - 1} times in nodes")

        if unused_inputs:
            print("\n⚠️ PROBLEM: Declared inputs not used as template variables!")
            print("  The workflow declares inputs but doesn't use them in node params.")
            print("  This causes validation to fail.")
    return unused_inputs


def _analyze_outputs(workflow):
    """Helper to analyze workflow outputs."""
    if "outputs" in workflow:
        print("\n📤 DECLARED OUTPUTS:")
        for name, spec in workflow["outputs"].items():
            print(f"  - {name}: {spec}")

        # Check if outputs reference valid node outputs
        print("\n🔍 OUTPUT REFERENCES:")
        for output_name, output_ref in workflow["outputs"].items():
            if isinstance(output_ref, str) and output_ref.startswith("$"):
                node_ref = output_ref.split(".")[0][1:]  # Remove $ and get node ID
                node_exists = any(n["id"] == node_ref for n in workflow.get("nodes", []))
                if node_exists:
                    print(f"  ✅ {output_name} -> {output_ref}")
                else:
                    print(f"  ❌ {output_name} -> {output_ref} (node '{node_ref}' not found)")
            elif isinstance(output_ref, dict):
                print(f"  * {output_name}: {output_ref.get('description', 'no description')}")


def analyze_workflow_issues(workflow, user_input):
    """Analyze what's wrong with the generated workflow."""
    print("\n" + "=" * 80)
    print("WORKFLOW ANALYSIS")
    print("=" * 80)

    # Check inputs
    unused_inputs = _analyze_inputs(workflow)

    # Check outputs
    _analyze_outputs(workflow)

    # Check nodes
    print("\n🔧 NODES:")
    for node in workflow.get("nodes", []):
        print(f"  - {node['id']} ({node['type']})")
        if "params" in node:
            for param, value in node["params"].items():
                if isinstance(value, str) and value.startswith("$"):
                    print(f"    • {param} = {value}")

    # Suggest fixes
    print("\n💡 SUGGESTED FIXES:")
    if unused_inputs:
        print("  1. Either use the declared inputs as template variables in node params")
        print("  2. Or remove the unused inputs from the inputs declaration")
        print("  3. Example: If 'csv_file_path' is declared, use '$csv_file_path' in a node param")

    # Check if user input values were extracted
    print("\n🎯 USER INPUT ANALYSIS:")
    print(f"  User said: '{user_input}'")
    print("  Specific values mentioned:")
    if "data.csv" in user_input:
        print("    - 'data.csv' (file name)")
    if "first column" in user_input:
        print("    - 'first column' (specific instruction)")
    print("\n  These values should be extracted as parameters, not hardcoded in workflow")


def debug_retry_mechanism():
    """Debug the retry mechanism to see if errors are fed back."""
    print("\n" + "=" * 80)
    print("RETRY MECHANISM DEBUG")
    print("=" * 80)

    # Create a test that should fail validation
    with tempfile.TemporaryDirectory() as tmpdir:
        workflows_dir = Path(tmpdir) / "workflows"
        workflows_dir.mkdir()
        workflow_manager = WorkflowManager(workflows_dir=str(workflows_dir))

        user_input = "Count the number of lines in a text file"
        print(f"\n📝 USER INPUT: '{user_input}'")

        flow = create_planner_flow()
        shared = {
            "user_input": user_input,
            "workflow_manager": workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Hook into the shared store to track retries
        original_run = flow.run
        retry_count = [0]

        def tracked_run(shared_store):
            # Track each time generator runs
            if "generation_attempts" in shared_store:
                attempt = shared_store["generation_attempts"]
                if attempt > retry_count[0]:
                    retry_count[0] = attempt
                    print(f"\n🔄 RETRY {attempt}: Generator called again")
                    if "validation_errors" in shared_store:
                        print("  Errors fed to generator:")
                        for error in shared_store["validation_errors"]:
                            print(f"    - {error}")
            return original_run(shared_store)

        flow.run = tracked_run
        flow.run(shared)

        print("\n📊 FINAL STATS:")
        print(f"  Total attempts: {shared.get('generation_attempts', 1)}")
        print(f"  Final success: {shared.get('planner_output', {}).get('success')}")

        return shared


if __name__ == "__main__":
    print("Starting Path B debugging...\n")

    # Debug normal generation
    shared1 = debug_path_b_generation()

    # Debug retry mechanism
    print("\n" + "=" * 80)
    shared2 = debug_retry_mechanism()

    print("\n" + "=" * 80)
    print("DEBUGGING COMPLETE")
    print("=" * 80)
