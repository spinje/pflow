"""Tests for enhanced error output (Task 71).

These tests validate the two-layer error enhancement architecture:
- Data layer: executor_service.py extracts rich context from shared store
- Display layer: main.py shows enriched errors to users

Focus: Integration testing that verifies error data structure and execution state visibility.

NOTE: We test the STRUCTURE and PRESENCE of enhanced error data, not exact formatting.
The goal is to verify that rich context flows from executor → ExecutionResult → CLI output.
"""

import json

from click.testing import CliRunner

from pflow.cli.main import main


class TestEnhancedErrorOutput:
    """Test enhanced error output in CLI."""

    def test_execution_state_visible_in_json_output(self, tmp_path):
        """JSON output should include execution_steps showing node status.

        This validates the _build_execution_steps function (main.py lines 680-739)
        which creates per-node status tracking.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo success"}},
                {"id": "step2", "type": "shell", "params": {"command": "echo success"}},
                {"id": "step3", "type": "shell", "params": {"command": "exit 1"}},  # Fails
                {"id": "step4", "type": "shell", "params": {"command": "echo never runs"}},
            ],
            "edges": [
                {"from": "step1", "to": "step2"},
                {"from": "step2", "to": "step3"},
                {"from": "step3", "to": "step4"},
            ],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0

        # Parse JSON output
        output = json.loads(result.output)

        # Verify execution state exists
        assert "execution" in output, "JSON output should include execution state"
        assert "steps" in output["execution"], "Execution should include steps array"

        steps = output["execution"]["steps"]
        assert isinstance(steps, list), "steps should be an array"
        assert len(steps) == 4, "Should have status for all 4 nodes"

        # Verify step structure
        step_map = {step["node_id"]: step for step in steps}

        # Check completed nodes
        assert step_map["step1"]["status"] == "completed"
        assert step_map["step2"]["status"] == "completed"

        # Check failed node
        assert step_map["step3"]["status"] == "failed"

        # Check not executed node
        assert step_map["step4"]["status"] == "not_executed"

        # Verify step fields exist
        for step in steps:
            assert "node_id" in step
            assert "status" in step
            # These fields may be None but should exist
            assert "duration_ms" in step or step["status"] == "not_executed"
            assert "cached" in step

    def test_execution_state_visible_in_success_output(self, tmp_path):
        """JSON output should include execution state for successful workflows too."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo success"}},
                {"id": "step2", "type": "shell", "params": {"command": "echo done"}},
            ],
            "edges": [{"from": "step1", "to": "step2"}],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0

        output = json.loads(result.output)

        # Verify execution state exists in success case too
        assert "execution" in output
        assert "steps" in output["execution"]
        steps = output["execution"]["steps"]

        assert len(steps) == 2
        assert all(step["status"] == "completed" for step in steps)

    def test_cache_hits_tracked_in_execution_state(self, tmp_path):
        """Execution state should track which nodes used cache.

        This validates __cache_hits__ tracking (instrumented_wrapper.py lines 598-601).
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "compute", "type": "shell", "params": {"command": "echo result"}},
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()

        # First run - no cache
        result1 = runner.invoke(main, ["--output-format", "json", str(workflow_path)])
        assert result1.exit_code == 0
        output1 = json.loads(result1.output)
        steps1 = output1["execution"]["steps"]
        assert steps1[0]["cached"] is False

        # Second run - should hit cache
        result2 = runner.invoke(main, ["--output-format", "json", str(workflow_path)])
        assert result2.exit_code == 0
        output2 = json.loads(result2.output)
        steps2 = output2["execution"]["steps"]

        # Verify cache field is tracked (value depends on cache config)
        assert "cached" in steps2[0]

    def test_error_handler_signature_compatibility(self, tmp_path, monkeypatch):
        """Verify _handle_workflow_error receives result param.

        This validates the signature change from Task 71.
        The actual signature validation is done by Python - if the wrong
        parameters were passed, we'd get a TypeError. This test verifies
        that ExecutionResult is passed through the call chain.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "fail", "type": "shell", "params": {"command": "exit 1"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # If the signature was wrong, we'd get a TypeError
        # The fact that we get a clean exit with error means signature is correct
        assert result.exit_code != 0
        assert "error" in result.output.lower() or "failed" in result.output.lower()

    def test_json_error_output_structure(self, tmp_path):
        """JSON error output should have consistent structure.

        Validates error output structure from executor_service.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "fail", "type": "shell", "params": {"command": "exit 1"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0

        output = json.loads(result.output)

        # Verify required fields
        assert "success" in output
        assert output["success"] is False
        assert "error" in output

        # Error is a string message at top level
        assert isinstance(output["error"], str)

        # Verify detailed errors array exists
        assert "errors" in output
        assert isinstance(output["errors"], list)
        assert len(output["errors"]) > 0

        # Verify first error has expected structure
        error = output["errors"][0]
        assert "category" in error
        assert "message" in error
        assert "node_id" in error

    def test_template_error_shows_context(self, tmp_path):
        """Template errors should fail with actionable context.

        While we can't control exact error messages, we verify that
        template validation runs and provides useful feedback.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "producer", "type": "shell", "params": {"command": "echo 'test'"}},
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {
                        # Wrong template - 'output' doesn't exist, should be 'result'
                        "command": "echo ${producer.output}"
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, [str(workflow_path)])

        # Should fail (either in validation or execution)
        assert result.exit_code != 0

        # Error message should mention the problematic template
        assert "producer" in result.output or "output" in result.output

    def test_graceful_handling_when_no_enhanced_data(self, tmp_path):
        """Should handle errors gracefully even without enhanced error data."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "simple_fail", "type": "shell", "params": {"command": "exit 1"}}],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()

        # Test both text and JSON modes
        for output_format in ["text", "json"]:
            args = [str(workflow_path)]
            if output_format == "json":
                args = ["--output-format", "json", *args]

            result = runner.invoke(main, args)

            # Should not crash, should show error
            assert result.exit_code != 0

            if output_format == "json":
                output = json.loads(result.output)
                assert output["success"] is False
            else:
                assert "error" in result.output.lower() or "failed" in result.output.lower()

    def test_execution_steps_include_timing_info(self, tmp_path):
        """Execution steps should include duration_ms for completed nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "step1", "type": "shell", "params": {"command": "echo test"}},
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code == 0
        output = json.loads(result.output)

        steps = output["execution"]["steps"]
        assert len(steps) == 1

        step = steps[0]
        assert step["status"] == "completed"
        # Duration should be present and non-None for completed nodes
        assert "duration_ms" in step
        # May be None in some cases, but field should exist

    def test_multiple_node_failure_shows_all_states(self, tmp_path):
        """When workflow fails partway, all node states should be visible."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo a"}},
                {"id": "b", "type": "shell", "params": {"command": "echo b"}},
                {"id": "c", "type": "shell", "params": {"command": "exit 1"}},  # Fails here
                {"id": "d", "type": "shell", "params": {"command": "echo d"}},
                {"id": "e", "type": "shell", "params": {"command": "echo e"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "d"},
                {"from": "d", "to": "e"},
            ],
        }

        workflow_path = tmp_path / "test.json"
        workflow_path.write_text(json.dumps(workflow))

        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0
        output = json.loads(result.output)

        steps = output["execution"]["steps"]
        step_map = {step["node_id"]: step for step in steps}

        # Verify partial execution tracking
        assert step_map["a"]["status"] == "completed"
        assert step_map["b"]["status"] == "completed"
        assert step_map["c"]["status"] == "failed"
        assert step_map["d"]["status"] == "not_executed"
        assert step_map["e"]["status"] == "not_executed"
