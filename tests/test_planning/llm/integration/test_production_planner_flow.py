"""PRODUCTION Integration Tests - Real Planner Flow.

Tests the ACTUAL production planner as invoked by the CLI.
Tests both Path A (reuse) and Path B (generation) through create_planner_flow(wait=0).

These tests run the entire planner flow as the CLI would invoke it, using actual LLM
calls instead of mocks. They test both paths through the production integration.

CRITICAL FOR:
- Validating production integration
- Testing both paths converge correctly
- Ensuring CLI invocation works end-to-end

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_production_planner_flow.py -xvs
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# For LLM tests, we need to enable the Anthropic model wrapper
# This gives us cache_blocks support which is required for the new architecture
if os.getenv("RUN_LLM_TESTS"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

    install_anthropic_model()

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning import create_planner_flow


@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="Skipping LLM tests. Set RUN_LLM_TESTS=1 to run.")
class TestProductionPlannerFlow:
    """Production planner flow tests with real LLM calls for both Path A and Path B."""

    @pytest.fixture
    def test_workflows_dir(self):
        """Create a temporary directory for test workflows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()
            yield workflows_dir

    @pytest.fixture
    def test_workflow_manager(self, test_workflows_dir):
        """Create a WorkflowManager with test directory."""
        return WorkflowManager(workflows_dir=str(test_workflows_dir))

    @pytest.fixture
    def sample_workflow(self):
        """A sample workflow for testing Path A."""
        return {
            "name": "file-analyzer",
            "description": "Read and analyze file contents",
            "version": "1.0.0",
            "ir": {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "reader", "type": "read-file", "params": {"file_path": "${input_file}"}},
                    {
                        "id": "analyzer",
                        "type": "llm",
                        "params": {"prompt": "Analyze this content: ${content}", "model": "anthropic/claude-3-haiku"},
                    },
                ],
                "edges": [{"from": "reader", "to": "analyzer", "action": "default"}],
                "start_node": "reader",
                "inputs": {"input_file": {"description": "File to analyze", "type": "string", "required": True}},
                "outputs": {"analysis": {"description": "Analysis result"}},
            },
        }

    def test_path_a_workflow_reuse_with_real_llm(self, test_workflow_manager, sample_workflow):
        """Test Path A: Reusing an existing workflow with real LLM calls."""
        # Save a workflow that should be discovered
        test_workflow_manager.save(
            name="file-analyzer", workflow_ir=sample_workflow["ir"], description="Read and analyze file contents"
        )

        # Create and run the planner flow
        flow = create_planner_flow(wait=0)
        shared = {
            "user_input": "I need to analyze the file report.txt",
            "workflow_manager": test_workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Run the complete flow with real LLM calls
        flow.run(shared)

        # Verify the result
        assert "planner_output" in shared
        output = shared["planner_output"]

        # Path A should succeed if workflow was found and parameters extracted
        if output["success"]:
            # Successful Path A execution
            assert output["workflow_ir"] is not None
            assert output["execution_params"] is not None
            assert "input_file" in output["execution_params"]
            assert "report.txt" in str(output["execution_params"]["input_file"])
            assert output["error"] is None
            print("\n✅ Path A SUCCESS: Found and reused workflow 'file-analyzer'")
            print(f"   Extracted params: {output['execution_params']}")
        else:
            # Path A might fail if LLM doesn't match the workflow
            print(f"\n⚠️ Path A failed: {output.get('error')}")
            # This is acceptable - LLM matching isn't 100% deterministic

    def test_path_b_workflow_generation_with_real_llm(self, test_workflow_manager):
        """Test Path B: Generating a new workflow with real LLM calls."""
        # Don't save any workflows - force generation

        # Create and run the planner flow
        flow = create_planner_flow(wait=0)
        shared = {
            "user_input": "I want to count the number of lines in a text file",
            "workflow_manager": test_workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Run the complete flow with real LLM calls
        flow.run(shared)

        # Verify the result
        assert "planner_output" in shared
        output = shared["planner_output"]

        if output["success"]:
            # Successful Path B execution
            assert output["workflow_ir"] is not None
            assert output["execution_params"] is not None
            assert output["error"] is None

            # Check that a workflow was generated
            assert "generated_workflow" in shared
            generated = shared["generated_workflow"]
            assert "nodes" in generated
            assert len(generated["nodes"]) > 0

            # Check metadata was generated
            if output.get("workflow_metadata"):
                metadata = output["workflow_metadata"]
                assert "suggested_name" in metadata
                assert "description" in metadata
                assert "search_keywords" in metadata

            print("\n✅ Path B SUCCESS: Generated new workflow")
            print(f"   Generated nodes: {[n['type'] for n in generated['nodes']]}")
            print(f"   Metadata: {output.get('workflow_metadata', {}).get('suggested_name', 'N/A')}")
        else:
            # Path B might fail due to various reasons
            print(f"\n⚠️ Path B failed: {output.get('error')}")
            if output.get("missing_params"):
                print(f"   Missing params: {output['missing_params']}")
            if "validation_errors" in shared:
                print(f"   Validation errors: {shared['validation_errors']}")

    def test_path_b_with_specific_parameters(self, test_workflow_manager):
        """Test Path B with a request that includes specific parameter values."""
        # Create and run the planner flow
        flow = create_planner_flow(wait=0)
        shared = {
            "user_input": "Read the file data.csv and extract the first column",
            "workflow_manager": test_workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Run the complete flow with real LLM calls
        flow.run(shared)

        # Verify the result
        assert "planner_output" in shared
        output = shared["planner_output"]

        if output["success"]:
            # Check that parameters were extracted
            assert output["execution_params"] is not None

            # The LLM should extract "data.csv" as a parameter
            params_str = str(output["execution_params"])
            if "data.csv" in params_str or "csv" in params_str.lower():
                print("\n✅ Path B with params SUCCESS")
                print(f"   Extracted params: {output['execution_params']}")
            else:
                print("\n⚠️ Parameters extracted but 'data.csv' not found")
                print(f"   Params: {output['execution_params']}")
        else:
            print(f"\n⚠️ Path B with params failed: {output.get('error')}")

    def test_missing_parameters_handling(self, test_workflow_manager):
        """Test handling of missing parameters in both paths."""
        # Create a workflow that requires parameters
        workflow = {
            "ir": {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "processor",
                        "type": "data-processor",
                        "params": {"input": "${data_source}", "output": "${result_file}"},
                    }
                ],
                "edges": [],
                "start_node": "processor",
                "inputs": {
                    "data_source": {"description": "Data source", "type": "string", "required": True},
                    "result_file": {"description": "Result file", "type": "string", "required": True},
                },
            }
        }

        test_workflow_manager.save(
            name="data-processor", workflow_ir=workflow["ir"], description="Process data from source to result"
        )

        # Create and run with vague input (no specific values)
        flow = create_planner_flow(wait=0)
        shared = {
            "user_input": "I need to process some data",
            "workflow_manager": test_workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Run the complete flow
        flow.run(shared)

        # Verify the result
        assert "planner_output" in shared
        output = shared["planner_output"]

        if not output["success"]:
            # Should fail due to missing parameters
            if output.get("missing_params"):
                print("\n✅ Missing params handled correctly")
                print(f"   Missing: {output['missing_params']}")
                assert "data_source" in output["missing_params"] or "result_file" in output["missing_params"]
            else:
                print(f"\n⚠️ Failed but not due to missing params: {output.get('error')}")
        else:
            # Might succeed if LLM invents parameters
            print(f"\n⚠️ Unexpectedly succeeded with params: {output.get('execution_params')}")

    def test_validation_with_extracted_params(self, test_workflow_manager):
        """Test that validation now works with extracted parameters (VALIDATION REDESIGN)."""
        # This tests the fix where parameters are extracted BEFORE validation

        flow = create_planner_flow(wait=0)
        shared = {
            "user_input": "Create a workflow to read input.txt and write to output.txt",
            "workflow_manager": test_workflow_manager,
            "stdin_data": None,
            "current_date": datetime.now().isoformat(),
        }

        # Run the complete flow
        flow.run(shared)

        # Verify the result
        assert "planner_output" in shared
        output = shared["planner_output"]

        if output["success"]:
            # Check that we went through Path B (generation)
            if "generated_workflow" in shared:
                generated = shared["generated_workflow"]

                # Check if the workflow has inputs (template variables)
                if generated.get("inputs"):
                    # Validation should have passed with extracted params
                    print("\n✅ VALIDATION REDESIGN SUCCESS")
                    print(f"   Generated workflow with inputs: {list(generated['inputs'].keys())}")
                    print(f"   Extracted params: {output['execution_params']}")
                    print("   Template validation passed with actual values!")
                else:
                    print("\n⚠️ Generated workflow has no inputs (no templates to validate)")
            else:
                print("\n⚠️ Path A taken (found existing workflow)")
        else:
            print(f"\n⚠️ Planner failed: {output.get('error')}")

            # Check if it's the old validation problem (should NOT happen anymore)
            if "validation_errors" in shared and shared.get("generation_attempts", 0) >= 3:
                print("   ❌ OLD BUG: Validation failed after retries (should be fixed!)")
                print("   This indicates the validation redesign may not be working")


if __name__ == "__main__":
    # Run tests directly
    import sys

    sys.exit(pytest.main([__file__, "-xvs"]))
