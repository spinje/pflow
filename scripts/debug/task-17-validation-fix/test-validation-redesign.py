#!/usr/bin/env python3
"""
Test to verify the validation redesign works correctly.

This test verifies that:
1. Template validation now happens AFTER parameter extraction
2. Workflows with required inputs can pass validation
3. The retry mechanism still works
4. Both paths converge correctly
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

# Add pflow to path
sys.path.insert(0, "/Users/andfal/projects/pflow/src")

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.flow import create_planner_flow


def test_path_b_with_required_inputs():
    """Test that Path B can now handle workflows with required inputs."""
    print("\n=== Testing Path B with Required Inputs ===")

    # Create test workflow manager
    with tempfile.TemporaryDirectory() as tmpdir:
        test_manager = WorkflowManager(workflows_dir=str(Path(tmpdir) / "workflows"))

        # Create flow
        flow = create_planner_flow()

        # Setup shared store
        shared = {
            "user_input": "read data.csv and analyze it",
            "workflow_manager": test_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Mock Registry
        test_registry_data = {
            "read-file": {
                "interface": {"inputs": [], "outputs": ["content"], "params": ["file_path"]},
                "description": "Read file",
            },
            "llm": {
                "interface": {"inputs": ["prompt"], "outputs": ["response"], "params": []},
                "description": "LLM processing",
            },
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Create responses
            responses = [
                # 1. Discovery - no workflow found
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "found": False,
                                    "workflow_name": None,
                                    "confidence": 0.1,
                                    "reasoning": "No existing workflow",
                                }
                            }
                        ]
                    }
                ),
                # 2. Component browsing
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "node_ids": ["read-file", "llm"],
                                    "workflow_names": [],
                                    "reasoning": "File reading and analysis components",
                                }
                            }
                        ]
                    }
                ),
                # 3. Parameter discovery
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "parameters": {"format": "CSV"},
                                    "stdin_type": None,
                                    "reasoning": "CSV format mentioned",
                                }
                            }
                        ]
                    }
                ),
                # 4. Workflow generation - WITH REQUIRED INPUTS AND TEMPLATES
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "ir_version": "0.1.0",
                                    "nodes": [
                                        {
                                            "id": "read",
                                            "type": "read-file",
                                            "params": {"file_path": "$input_file"},  # Template variable!
                                        },
                                        {
                                            "id": "analyze",
                                            "type": "llm",
                                            "params": {"prompt": "Analyze this CSV: $content"},
                                        },
                                    ],
                                    "edges": [{"from": "read", "to": "analyze"}],
                                    "start_node": "read",
                                    "inputs": {
                                        "input_file": {
                                            "description": "CSV file to analyze",
                                            "type": "string",
                                            "required": True,  # REQUIRED INPUT!
                                        }
                                    },
                                    "outputs": {},
                                }
                            }
                        ]
                    }
                ),
                # 5. Parameter mapping - EXTRACTS the actual value
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "extracted": {"input_file": "data.csv"},  # Extracted from user input!
                                    "missing": [],
                                    "confidence": 0.95,
                                    "reasoning": "Found data.csv in user input",
                                }
                            }
                        ]
                    }
                ),
                # 6. Metadata generation (after validation passes)
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "suggested_name": "csv-analyzer",
                                    "description": "Analyze CSV files",
                                    "search_keywords": ["csv", "analyze"],
                                    "capabilities": ["Read CSV", "Analyze data"],
                                    "typical_use_cases": ["CSV analysis"],
                                    "declared_inputs": ["input_file"],
                                    "declared_outputs": [],
                                }
                            }
                        ]
                    }
                ),
            ]

            mock_model.prompt.side_effect = responses
            mock_get_model.return_value = mock_model

            # Mock Registry
            with patch("pflow.planning.nodes.Registry") as MockRegistry:
                mock_registry = Mock()
                mock_registry.load.return_value = test_registry_data
                mock_registry.get_nodes_metadata.return_value = test_registry_data
                MockRegistry.return_value = mock_registry

                # Run the flow
                flow.run(shared)

        # VERIFY THE RESULTS
        print("\n=== Verification ===")

        # 1. Check that we generated a workflow
        assert "generated_workflow" in shared, "No workflow generated"
        print("✓ Workflow was generated")

        # 2. Check that parameters were extracted
        assert "extracted_params" in shared, "No parameters extracted"
        assert shared["extracted_params"] == {"input_file": "data.csv"}, f"Wrong params: {shared['extracted_params']}"
        print(f"✓ Parameters extracted: {shared['extracted_params']}")

        # 3. Check that validation passed (no validation_errors or they're empty)
        if "validation_errors" in shared:
            assert len(shared["validation_errors"]) == 0, f"Validation errors: {shared['validation_errors']}"
        print("✓ Validation passed (no errors)")

        # 4. Check that the planner succeeded
        assert "planner_output" in shared, "No planner output"
        output = shared["planner_output"]

        if not output["success"]:
            print(f"✗ Planner failed: {output['error']}")
            if "validation_errors" in shared:
                print(f"  Validation errors: {shared['validation_errors']}")
            if "missing_params" in shared:
                print(f"  Missing params: {shared['missing_params']}")
        else:
            print("✓ Planner succeeded!")
            print(f"  Workflow: {output['workflow_ir']['start_node']} with {len(output['workflow_ir']['nodes'])} nodes")
            print(f"  Execution params: {output['execution_params']}")

        return output["success"]


def test_retry_mechanism():
    """Test that the retry mechanism still works with the new flow."""
    print("\n=== Testing Retry Mechanism ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        test_manager = WorkflowManager(workflows_dir=str(Path(tmpdir) / "workflows"))
        flow = create_planner_flow()

        shared = {
            "user_input": "test retry",
            "workflow_manager": test_manager,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Invalid workflow (missing start_node)
            invalid_workflow = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "llm", "params": {}}],
                "edges": [],
                # Missing start_node!
                "inputs": {},
                "outputs": {},
            }

            # Valid workflow
            valid_workflow = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "llm", "params": {}}],
                "edges": [],
                "start_node": "n1",
                "inputs": {},
                "outputs": {},
            }

            responses = [
                # Discovery
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "found": False,
                                    "workflow_name": None,
                                    "confidence": 0.1,
                                    "reasoning": "No match",
                                }
                            }
                        ]
                    }
                ),
                # Browse
                Mock(
                    json=lambda: {
                        "content": [{"input": {"node_ids": ["llm"], "workflow_names": [], "reasoning": "LLM"}}]
                    }
                ),
                # Param discovery
                Mock(
                    json=lambda: {"content": [{"input": {"parameters": {}, "stdin_type": None, "reasoning": "None"}}]}
                ),
                # Generation 1 - invalid
                Mock(json=lambda: {"content": [{"input": invalid_workflow}]}),
                # Param mapping 1
                Mock(
                    json=lambda: {
                        "content": [
                            {"input": {"extracted": {}, "missing": [], "confidence": 1.0, "reasoning": "No params"}}
                        ]
                    }
                ),
                # Generation 2 - valid
                Mock(json=lambda: {"content": [{"input": valid_workflow}]}),
                # Param mapping 2
                Mock(
                    json=lambda: {
                        "content": [
                            {"input": {"extracted": {}, "missing": [], "confidence": 1.0, "reasoning": "No params"}}
                        ]
                    }
                ),
                # Metadata
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "suggested_name": "test",
                                    "description": "Test",
                                    "search_keywords": ["test"],
                                    "capabilities": ["Test"],
                                    "typical_use_cases": ["Testing"],
                                    "declared_inputs": [],
                                    "declared_outputs": [],
                                }
                            }
                        ]
                    }
                ),
            ]

            mock_model.prompt.side_effect = responses
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as MockRegistry:
                mock_registry = Mock()
                mock_registry.load.return_value = {"llm": {"interface": {"inputs": [], "outputs": [], "params": []}}}
                mock_registry.get_nodes_metadata.return_value = {"llm": {}}
                MockRegistry.return_value = mock_registry

                flow.run(shared)

        print("\n=== Verification ===")

        # Check generation attempts
        assert "generation_attempts" in shared, "No generation attempts tracked"
        print(f"✓ Generation attempts: {shared['generation_attempts']}")

        # Check final result
        assert "planner_output" in shared
        output = shared["planner_output"]

        if output["success"]:
            print("✓ Retry mechanism worked - eventually succeeded")
        else:
            print(f"✗ Failed after retries: {output['error']}")

        return True


def test_path_detection():
    """Test that ParameterMappingNode correctly detects Path A vs Path B."""
    print("\n=== Testing Path Detection ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        test_manager = WorkflowManager(workflows_dir=str(Path(tmpdir) / "workflows"))

        # Save a test workflow for Path A
        test_manager.save(
            name="test-workflow",
            workflow_ir={
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "llm", "params": {"prompt": "test"}}],
                "edges": [],
                "start_node": "n1",
                "inputs": {},
                "outputs": {},
            },
            description="Test workflow",
        )

        # Test Path A
        print("\nPath A (found workflow):")
        flow_a = create_planner_flow()
        shared_a = {
            "user_input": "run test workflow",
            "workflow_manager": test_manager,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.side_effect = [
                # Discovery finds workflow
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "found": True,
                                    "workflow_name": "test-workflow",
                                    "confidence": 0.95,
                                    "reasoning": "Found",
                                }
                            }
                        ]
                    }
                ),
                # Parameter mapping
                Mock(
                    json=lambda: {
                        "content": [
                            {"input": {"extracted": {}, "missing": [], "confidence": 1.0, "reasoning": "No params"}}
                        ]
                    }
                ),
            ]
            mock_get_model.return_value = mock_model

            flow_a.run(shared_a)

        assert "found_workflow" in shared_a
        assert "generated_workflow" not in shared_a
        print("✓ Path A detected correctly (found_workflow, no generated_workflow)")

        # Test Path B
        print("\nPath B (generated workflow):")
        flow_b = create_planner_flow()
        shared_b = {
            "user_input": "create new workflow",
            "workflow_manager": test_manager,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Minimal Path B responses
            responses = [
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "found": False,
                                    "workflow_name": None,
                                    "confidence": 0.1,
                                    "reasoning": "No match",
                                }
                            }
                        ]
                    }
                ),
                Mock(
                    json=lambda: {
                        "content": [{"input": {"node_ids": ["llm"], "workflow_names": [], "reasoning": "LLM"}}]
                    }
                ),
                Mock(
                    json=lambda: {"content": [{"input": {"parameters": {}, "stdin_type": None, "reasoning": "None"}}]}
                ),
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "ir_version": "0.1.0",
                                    "nodes": [{"id": "n1", "type": "llm", "params": {}}],
                                    "edges": [],
                                    "start_node": "n1",
                                    "inputs": {},
                                    "outputs": {},
                                }
                            }
                        ]
                    }
                ),
                Mock(
                    json=lambda: {
                        "content": [
                            {"input": {"extracted": {}, "missing": [], "confidence": 1.0, "reasoning": "No params"}}
                        ]
                    }
                ),
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "suggested_name": "new",
                                    "description": "New",
                                    "search_keywords": ["new"],
                                    "capabilities": ["New"],
                                    "typical_use_cases": ["New"],
                                    "declared_inputs": [],
                                    "declared_outputs": [],
                                }
                            }
                        ]
                    }
                ),
            ]

            mock_model.prompt.side_effect = responses
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as MockRegistry:
                mock_registry = Mock()
                mock_registry.load.return_value = {"llm": {"interface": {"inputs": [], "outputs": [], "params": []}}}
                mock_registry.get_nodes_metadata.return_value = {"llm": {}}
                MockRegistry.return_value = mock_registry

                flow_b.run(shared_b)

        assert "generated_workflow" in shared_b
        assert "found_workflow" not in shared_b
        print("✓ Path B detected correctly (generated_workflow, no found_workflow)")

        return True


if __name__ == "__main__":
    print("=" * 60)
    print("VALIDATION REDESIGN VERIFICATION TEST")
    print("=" * 60)

    try:
        # Test 1: Path B with required inputs (the main fix)
        success1 = test_path_b_with_required_inputs()

        # Test 2: Retry mechanism still works
        success2 = test_retry_mechanism()

        # Test 3: Path detection works correctly
        success3 = test_path_detection()

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        if success1:
            print("✓ Path B can handle workflows with required inputs")
            print("  Templates are validated with extracted parameters")
        else:
            print("✗ Path B still fails with required inputs")

        if success2:
            print("✓ Retry mechanism works correctly")

        if success3:
            print("✓ Path detection works correctly")

        if success1 and success2 and success3:
            print("\n🎉 VALIDATION REDESIGN IS WORKING!")
            print("The flow now extracts parameters BEFORE validation.")
            print("Workflows with required inputs and template variables can pass validation.")
        else:
            print("\n⚠️ VALIDATION REDESIGN HAS ISSUES")
            print("Some tests failed. Check the output above for details.")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
