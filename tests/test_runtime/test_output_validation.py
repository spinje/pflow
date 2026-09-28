"""Tests for workflow output validation in the compiler.

Compile-only callers (web UI pre-flight, cache-key prediction, programmatic
``compile_workflow``) never run the IR schema, so ``_validate_outputs`` must
reject a sourceless output itself (issue #628).
"""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import SchemaValidationError
from pflow.runtime import compile_workflow
from pflow.runtime.compilation.compile_validation import _validate_outputs


def _ir(outputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "ir_version": "0.1.0",
        "nodes": [{"id": "n1", "type": "test-node", "params": {}}],
        "edges": [],
        "outputs": outputs,
    }


class TestOutputValidation:
    """Test the _validate_outputs function."""

    def test_no_outputs_declared(self):
        _validate_outputs({"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test-node"}]})

    def test_sourced_outputs_pass(self):
        _validate_outputs(_ir({"result": {"source": "${n1.result}"}, "raw": {"source": "n1"}}))

    def test_invalid_output_name(self):
        """Output names with shell special characters raise SchemaValidationError."""
        with pytest.raises(SchemaValidationError) as exc_info:
            _validate_outputs(_ir({"my$output": {"source": "${n1.result}"}}))

        assert "Invalid output name 'my$output'" in str(exc_info.value)

    @pytest.mark.parametrize(
        "output_spec",
        [{"description": "No source"}, {"description": "Empty source line", "source": None}, "plain string"],
        ids=["missing", "null", "not-a-section"],
    )
    def test_output_without_source_raises(self, output_spec: Any):
        """A sourceless output would silently produce nothing at runtime, so compilation rejects it."""
        with pytest.raises(SchemaValidationError) as exc_info:
            _validate_outputs(_ir({"ok": {"source": "${n1.result}"}, "summary": output_spec}))

        error = exc_info.value
        assert error.path == "outputs.summary"
        assert "Output 'summary' has no source" in error.message
        assert "- source: ${node_id.output_key}" in (error.suggestion or "")


class TestOutputValidationIntegration:
    """Test output validation as part of compile_workflow."""

    @pytest.fixture
    def registry(self) -> Mock:
        registry = Mock()
        registry.load.return_value = {"test-node": {"module": "test", "class_name": "ExampleNode"}}
        registry.get_nodes_metadata.return_value = {"test-node": {"interface": {"outputs": []}}}
        return registry

    @patch("pflow.runtime.compilation.compiler.import_node_class")
    def test_compile_with_hyphenated_output_names(self, mock_import, registry):
        mock_import.return_value = type("ExampleNode", (Mock,), {})

        workflow = compile_workflow(_ir({"valid-name": {"source": "${n1.result}"}}), registry)

        assert workflow is not None

    @patch("pflow.runtime.compilation.compiler.import_node_class")
    def test_compile_rejects_output_without_source(self, mock_import, registry):
        mock_import.return_value = type("ExampleNode", (Mock,), {})

        with pytest.raises(SchemaValidationError, match="Output 'summary' has no source"):
            compile_workflow(_ir({"summary": {"description": "Never populated"}}), registry)
