#!/usr/bin/env python
"""Debug script to understand the actual flow execution and shared store state."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning import create_planner_flow


def debug_path_a():
    """Debug Path A execution to see what's actually in the shared store."""

    # Create test workflow
    test_workflow = {
        "name": "test-workflow",
        "description": "Test workflow",
        "version": "1.0.0",
        "ir": {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node", "params": {"param": "$input_file"}}],
            "edges": [],
            "start_node": "node1",
            "inputs": {"input_file": {"description": "Input file path", "type": "string", "required": True}},
        },
    }

    # Create test workflow manager
    with tempfile.TemporaryDirectory() as tmpdir:
        test_manager = WorkflowManager(workflows_dir=str(Path(tmpdir) / "workflows"))
        test_manager.save(name="test-workflow", workflow_ir=test_workflow["ir"], description="Test workflow")

        # Create flow
        flow = create_planner_flow()

        # Setup shared store
        shared = {
            "user_input": "run test workflow with input file test.txt",
            "workflow_manager": test_manager,
            "current_date": datetime.now().isoformat(),
        }

        # Mock LLM responses
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Create mock responses
            discovery_response = Mock()
            discovery_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": True,
                            "workflow_name": "test-workflow",
                            "confidence": 0.95,
                            "reasoning": "Found matching workflow",
                        }
                    }
                ]
            }

            param_response = Mock()
            param_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "extracted": {"input_file": "test.txt"},
                            "missing": [],
                            "confidence": 0.9,
                            "reasoning": "Extracted from user input",
                        }
                    }
                ]
            }

            # Set up mock to return responses in order
            mock_model.prompt.side_effect = [
                discovery_response,  # For WorkflowDiscoveryNode
                param_response,  # For ParameterMappingNode
            ]
            mock_get_model.return_value = mock_model

            # Run the flow
            print("Running flow...")
            try:
                flow.run(shared)
            except Exception as e:
                print(f"Flow failed with error: {e}")
                import traceback

                traceback.print_exc()

            # Print the shared store state
            print("\n" + "=" * 50)
            print("SHARED STORE AFTER EXECUTION:")
            print("=" * 50)

            for key, value in sorted(shared.items()):
                if isinstance(value, (dict, list)):
                    print(f"\n{key}:")
                    print(json.dumps(value, indent=2, default=str))
                elif isinstance(value, WorkflowManager):
                    print(f"\n{key}: <WorkflowManager instance>")
                else:
                    print(f"\n{key}: {value}")

            print("\n" + "=" * 50)
            print("IMPORTANT KEYS TO CHECK:")
            print("=" * 50)
            print(f"Has 'extracted_params'? {('extracted_params' in shared)}")
            print(f"Has 'execution_params'? {('execution_params' in shared)}")
            print(f"Has 'planner_output'? {('planner_output' in shared)}")
            print(f"Has 'found_workflow'? {('found_workflow' in shared)}")
            print(f"Has 'generated_workflow'? {('generated_workflow' in shared)}")

            if "planner_output" in shared:
                print("\nPLANNER OUTPUT:")
                print(json.dumps(shared["planner_output"], indent=2, default=str))


if __name__ == "__main__":
    debug_path_a()
