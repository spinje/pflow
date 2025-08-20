#!/usr/bin/env python
"""Test script to verify temperature fix for GPT models."""

import os
import sys
import tempfile
from pathlib import Path

# Set test model and enable LLM tests
os.environ["PFLOW_TEST_MODEL"] = "gpt-5-nano"
os.environ["RUN_LLM_TESTS"] = "1"

# Add project to path
sys.path.insert(0, "/Users/andfal/projects/pflow")

# Test with a simple discovery case
from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import WorkflowDiscoveryNode


def test_temperature_fix():
    """Test that GPT models work with temperature override."""
    print(f"Testing with model: {os.environ['PFLOW_TEST_MODEL']}")

    # Create temp directory for workflows
    with tempfile.TemporaryDirectory() as tmpdir:
        workflows_dir = Path(tmpdir) / "workflows"
        workflows_dir.mkdir()

        # Create workflow manager
        manager = WorkflowManager(workflows_dir=str(workflows_dir))

        # Save a simple test workflow
        test_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "${file}"}}],
            "edges": [],
            "inputs": {"file": {"type": "string", "required": True}},
        }
        manager.save("simple-read", test_workflow, "Read a file")

        # Test discovery with temperature issue
        node = WorkflowDiscoveryNode()
        shared = {"user_input": "read a file", "workflow_manager": manager}

        try:
            # This would fail without the temperature fix
            prep_res = node.prep(shared)
            print("✅ Prep completed")
            print(f"  Model: {prep_res.get('model_name')}")
            print(f"  Temperature: {prep_res.get('temperature')}")

            # Try exec (this is where the LLM call happens)
            exec_res = node.exec(prep_res)
            print("✅ Exec completed")
            print(f"  Found: {exec_res.get('found')}")
            print(f"  Confidence: {exec_res.get('confidence')}")

            # Check post
            action = node.post(shared, prep_res, exec_res)
            print("✅ Post completed")
            print(f"  Action: {action}")

            print("\n🎉 Temperature fix is working! GPT model handled temperature correctly.")
            return True

        except Exception as e:
            print(f"\n❌ Error: {e}")
            if "temperature" in str(e).lower():
                print("⚠️  Temperature issue detected - fix may not be working")
            return False


if __name__ == "__main__":
    success = test_temperature_fix()
    sys.exit(0 if success else 1)
