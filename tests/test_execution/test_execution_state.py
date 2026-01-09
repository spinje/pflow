"""Tests for execution state building utilities.

Tests the build_execution_steps function that creates per-node execution
state summaries for workflow visualization and error reporting.
"""

from pflow.execution.execution_state import build_execution_steps


class TestBuildExecutionSteps:
    """Tests for build_execution_steps function."""

    def test_basic_step_building(self):
        """Should build basic step data from workflow IR and shared storage."""
        workflow_ir = {
            "nodes": [
                {"id": "node1"},
                {"id": "node2"},
            ]
        }
        shared_storage = {
            "__execution__": {
                "completed_nodes": ["node1", "node2"],
                "failed_node": None,
            }
        }
        metrics_summary = None

        steps = build_execution_steps(workflow_ir, shared_storage, metrics_summary)

        assert len(steps) == 2
        assert steps[0]["node_id"] == "node1"
        assert steps[0]["status"] == "completed"
        assert steps[1]["node_id"] == "node2"
        assert steps[1]["status"] == "completed"

    def test_failed_node_status(self):
        """Should mark failed node correctly."""
        workflow_ir = {
            "nodes": [
                {"id": "node1"},
                {"id": "node2"},
            ]
        }
        shared_storage = {
            "__execution__": {
                "completed_nodes": ["node1"],
                "failed_node": "node2",
            }
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert steps[0]["status"] == "completed"
        assert steps[1]["status"] == "failed"

    def test_not_executed_status(self):
        """Should mark nodes not in completed or failed as not_executed."""
        workflow_ir = {
            "nodes": [
                {"id": "node1"},
                {"id": "node2"},
                {"id": "node3"},
            ]
        }
        shared_storage = {
            "__execution__": {
                "completed_nodes": ["node1"],
                "failed_node": "node2",
            }
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert steps[2]["status"] == "not_executed"


class TestBuildExecutionStepsStderr:
    """Tests for stderr detection in build_execution_steps."""

    def test_detects_stderr_with_exit_code_0(self):
        """Should detect stderr when exit_code=0."""
        workflow_ir = {"nodes": [{"id": "shell-node"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["shell-node"], "failed_node": None},
            "shell-node": {
                "stdout": "output",
                "stderr": "Some warning message",
                "exit_code": 0,
            },
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert steps[0]["has_stderr"] is True
        assert steps[0]["stderr"] == "Some warning message"

    def test_no_stderr_flag_when_stderr_empty(self):
        """Should not set has_stderr when stderr is empty."""
        workflow_ir = {"nodes": [{"id": "shell-node"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["shell-node"], "failed_node": None},
            "shell-node": {
                "stdout": "output",
                "stderr": "",
                "exit_code": 0,
            },
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert "has_stderr" not in steps[0]

    def test_no_stderr_flag_when_stderr_whitespace_only(self):
        """Should not set has_stderr when stderr is only whitespace."""
        workflow_ir = {"nodes": [{"id": "shell-node"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["shell-node"], "failed_node": None},
            "shell-node": {
                "stdout": "output",
                "stderr": "   \n\t  ",
                "exit_code": 0,
            },
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert "has_stderr" not in steps[0]

    def test_no_stderr_flag_when_exit_code_nonzero(self):
        """Should not set has_stderr when exit_code is non-zero."""
        workflow_ir = {"nodes": [{"id": "shell-node"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": [], "failed_node": "shell-node"},
            "shell-node": {
                "stdout": "",
                "stderr": "Error message",
                "exit_code": 1,
            },
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        # Node failed, so no has_stderr flag (error is shown via different path)
        assert "has_stderr" not in steps[0]

    def test_no_stderr_flag_for_non_shell_nodes(self):
        """Should not set has_stderr for nodes without exit_code."""
        workflow_ir = {"nodes": [{"id": "llm-node"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["llm-node"], "failed_node": None},
            "llm-node": {
                "response": "Hello!",
                # No exit_code - not a shell node
            },
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert "has_stderr" not in steps[0]

    def test_strips_stderr_whitespace(self):
        """Should strip leading/trailing whitespace from stderr."""
        workflow_ir = {"nodes": [{"id": "shell-node"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["shell-node"], "failed_node": None},
            "shell-node": {
                "stderr": "  Warning message  \n",
                "exit_code": 0,
            },
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert steps[0]["stderr"] == "Warning message"

    def test_multiple_nodes_with_stderr(self):
        """Should detect stderr for multiple nodes."""
        workflow_ir = {
            "nodes": [
                {"id": "shell1"},
                {"id": "shell2"},
                {"id": "shell3"},
            ]
        }
        shared_storage = {
            "__execution__": {
                "completed_nodes": ["shell1", "shell2", "shell3"],
                "failed_node": None,
            },
            "shell1": {"stderr": "Warning 1", "exit_code": 0},
            "shell2": {"stderr": "", "exit_code": 0},  # No stderr
            "shell3": {"stderr": "Warning 3", "exit_code": 0},
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert steps[0].get("has_stderr") is True
        assert steps[0]["stderr"] == "Warning 1"
        assert "has_stderr" not in steps[1]
        assert steps[2].get("has_stderr") is True
        assert steps[2]["stderr"] == "Warning 3"


class TestBuildExecutionStepsCacheAndRepair:
    """Tests for cache and repair flags in build_execution_steps."""

    def test_cache_hit_flag(self):
        """Should set cached flag for nodes in __cache_hits__."""
        workflow_ir = {"nodes": [{"id": "node1"}, {"id": "node2"}]}
        shared_storage = {
            "__execution__": {
                "completed_nodes": ["node1", "node2"],
                "failed_node": None,
            },
            "__cache_hits__": ["node1"],
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert steps[0]["cached"] is True
        assert steps[1]["cached"] is False

    def test_repaired_flag(self):
        """Should set repaired flag for nodes in __modified_nodes__."""
        workflow_ir = {"nodes": [{"id": "node1"}, {"id": "node2"}]}
        shared_storage = {
            "__execution__": {
                "completed_nodes": ["node1", "node2"],
                "failed_node": None,
            },
            "__modified_nodes__": ["node2"],
        }

        steps = build_execution_steps(workflow_ir, shared_storage, None)

        assert "repaired" not in steps[0]
        assert steps[1]["repaired"] is True
