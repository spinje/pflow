#!/usr/bin/env python3
"""
Integration test for Runtime Validation Feedback Loop

This test demonstrates the complete feedback loop:
1. Planner generates workflow with wrong field names
2. RuntimeValidationNode detects the issues
3. Workflow gets corrected automatically
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from pflow.planning import create_planner_flow
from pflow.core.workflow_manager import WorkflowManager


def create_test_workflow_manager():
    """Create a workflow manager with test data."""
    temp_dir = tempfile.mkdtemp()
    return WorkflowManager(workflows_dir=temp_dir)


def test_runtime_validation_with_retry():
    """Test that runtime validation triggers retry with corrections."""

    print("\n" + "="*70)
    print("INTEGRATION TEST: Runtime Validation Triggers Workflow Correction")
    print("="*70)

    # Create planner flow
    flow = create_planner_flow(wait=0)

    # Set up shared store
    workflow_manager = create_test_workflow_manager()
    shared = {
        "user_input": "fetch github user data and display username",
        "workflow_manager": workflow_manager,
        "stdin_data": None,
        "current_date": "2024-01-01",
    }

    # Mock responses for the planner nodes
    with patch("llm.get_model") as mock_get_model:
        mock_model = Mock()

        # Create response sequence
        responses = [
            # 1. Discovery - no existing workflow
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "found": False,
                    "workflow_name": None,
                    "confidence": 0.1,
                    "reasoning": "No existing workflow"
                }}]
            })),

            # 2. Parameter discovery
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "parameters": {},
                    "stdin_type": None,
                    "reasoning": "No parameters"
                }}]
            })),

            # 3. Requirements analysis
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "is_clear": True,
                    "clarification_needed": None,
                    "steps": ["Fetch GitHub user", "Display username"],
                    "estimated_nodes": 2,
                    "required_capabilities": ["http", "llm"],
                    "complexity_indicators": {"has_conditional": False}
                }}]
            })),

            # 4. Component browsing
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "node_ids": ["http", "write-file"],
                    "workflow_names": [],
                    "reasoning": "Need HTTP for API call and write for output"
                }}]
            })),

            # 5. Planning
            Mock(text=Mock(return_value="## Plan\n**Status**: FEASIBLE\n**Node Chain**: http >> write-file")),

            # 6. FIRST workflow generation (with WRONG field names)
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {
                            "id": "fetch",
                            "type": "http",
                            "params": {"url": "https://api.github.com/users/torvalds"}
                        },
                        {
                            "id": "output",
                            "type": "write-file",
                            "params": {
                                "file_path": "/tmp/output.txt",
                                # WRONG field name - will be detected by runtime validation
                                "content": "Username: ${fetch.response.username}"
                            }
                        }
                    ],
                    "edges": [{"from": "fetch", "to": "output"}],
                    "start_node": "fetch",
                    "inputs": {},
                    "outputs": {}
                }}]
            })),

            # 7. Parameter mapping (first attempt)
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "extracted": {},
                    "missing": [],
                    "confidence": 0.9,
                    "reasoning": "No parameters needed"
                }}]
            })),

            # 8. Metadata generation
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "suggested_name": "github-user-fetch",
                    "description": "Fetch GitHub user data",
                    "search_keywords": ["github", "user", "api"],
                    "capabilities": ["Fetch GitHub data"],
                    "typical_use_cases": ["Get user info"],
                    "declared_inputs": [],
                    "declared_outputs": []
                }}]
            })),

            # After RuntimeValidationNode detects issues and triggers retry:

            # 9. SECOND workflow generation (with CORRECTED field names)
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {
                            "id": "fetch",
                            "type": "http",
                            "params": {"url": "https://api.github.com/users/torvalds"}
                        },
                        {
                            "id": "output",
                            "type": "write-file",
                            "params": {
                                "file_path": "/tmp/output.txt",
                                # CORRECTED field name after runtime feedback
                                "content": "Username: ${fetch.response.login}"
                            }
                        }
                    ],
                    "edges": [{"from": "fetch", "to": "output"}],
                    "start_node": "fetch",
                    "inputs": {},
                    "outputs": {}
                }}]
            })),

            # 10. Parameter mapping (second attempt)
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "extracted": {},
                    "missing": [],
                    "confidence": 0.9,
                    "reasoning": "No parameters needed"
                }}]
            })),

            # 11. Metadata generation (second time)
            Mock(json=Mock(return_value={
                "content": [{"input": {
                    "suggested_name": "github-user-fetch",
                    "description": "Fetch GitHub user data",
                    "search_keywords": ["github", "user", "api"],
                    "capabilities": ["Fetch GitHub data"],
                    "typical_use_cases": ["Get user info"],
                    "declared_inputs": [],
                    "declared_outputs": []
                }}]
            })),
        ]

        mock_model.prompt.side_effect = responses
        mock_get_model.return_value = mock_model

        # Mock registries
        with (
            patch("pflow.planning.context_builder._workflow_manager", workflow_manager),
            patch("pflow.registry.registry.Registry") as MockRegistry1,
            patch("pflow.planning.nodes.Registry") as MockRegistry2,
        ):
            mock_registry = Mock()
            test_registry_data = {
                "http": {"interface": {"inputs": [], "outputs": ["response"], "params": ["url"]}},
                "write-file": {"interface": {"inputs": ["content", "file_path"], "outputs": [], "params": []}}
            }
            mock_registry.load.return_value = test_registry_data
            mock_registry.get_nodes_metadata.side_effect = lambda node_types: {
                nt: test_registry_data.get(nt, {}) for nt in node_types
            }

            MockRegistry1.return_value = mock_registry
            MockRegistry2.return_value = mock_registry

            # Mock the RuntimeValidationNode's exec to simulate detecting missing paths
            with patch("pflow.planning.nodes.RuntimeValidationNode.exec") as mock_runtime_exec:

                call_count = [0]

                def runtime_exec_side_effect(prep_res):
                    call_count[0] += 1

                    if call_count[0] == 1:
                        # First call: Simulate detecting missing template path
                        print("\n   🔍 RuntimeValidationNode (attempt 1):")
                        print("      Executing workflow...")
                        print("      ❌ Detected missing path: ${fetch.response.username}")
                        print("      📝 Available fields: login, id, name, bio, followers...")

                        # Return result indicating we found issues
                        # The post() method will detect these and route to "runtime_fix"
                        return {
                            "ok": True,
                            "shared_after": {
                                "fetch": {
                                    "response": {
                                        "login": "torvalds",
                                        "id": 1024025,
                                        "name": "Linus Torvalds",
                                        # Note: no "username" field!
                                    },
                                    "status_code": 200
                                }
                            },
                            "result": None
                        }
                    else:
                        # Second call: After correction, everything works
                        print("\n   ✅ RuntimeValidationNode (attempt 2):")
                        print("      Executing corrected workflow...")
                        print("      ✓ All template paths valid!")

                        return {
                            "ok": True,
                            "shared_after": {
                                "fetch": {
                                    "response": {
                                        "login": "torvalds",
                                        "id": 1024025,
                                        "name": "Linus Torvalds",
                                    },
                                    "status_code": 200
                                },
                                "output": {
                                    "success": True
                                }
                            },
                            "result": None
                        }

                mock_runtime_exec.side_effect = runtime_exec_side_effect

                print("\n🚀 Starting planner flow with runtime validation...")

                # Run the flow
                flow.run(shared)

                print("\n📊 Flow execution complete!")

                # Verify the flow succeeded
                assert "planner_output" in shared
                result = shared["planner_output"]

                if result["success"]:
                    print("\n✅ SUCCESS: Workflow was generated and corrected!")
                    print(f"   - Runtime attempts: {shared.get('runtime_attempts', 0)}")
                    print(f"   - Final workflow has corrected field names")

                    # Check that we actually went through runtime validation
                    assert shared.get("runtime_attempts", 0) > 0, "Should have triggered runtime validation"
                    assert call_count[0] == 2, f"RuntimeValidationNode should have been called twice, was called {call_count[0]} times"
                else:
                    print(f"\n❌ FAILED: {result.get('error', 'Unknown error')}")
                    raise AssertionError("Workflow generation failed")

    print("\n" + "="*70)
    print("✅ Runtime validation feedback loop successfully demonstrated!")
    print("="*70)


if __name__ == "__main__":
    test_runtime_validation_with_retry()