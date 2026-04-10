"""Test output source validation in WorkflowValidator."""

from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_validator_diagnostics


class TestOutputSourceValidation:
    """Test output source validation functionality."""

    def test_valid_output_source_node_id_only(self):
        """✅ Valid: Output references node ID without specific key."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
            "outputs": {"result": {"source": "node1", "description": "Node output"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

    def test_valid_output_source_with_dot_notation(self):
        """✅ Valid: Output references node with output key."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
            "outputs": {"result": {"source": "node1.stdout", "description": "Shell stdout"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_valid_output_source_with_nested_path(self):
        """✅ Valid: Output references nested output path (multiple dots)."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "mcp", "params": {}}],
            "edges": [],
            "outputs": {"deep": {"source": "node1.result.data.items", "description": "Nested"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_invalid_output_source_nonexistent_node(self):
        """❌ Invalid: Output references node that doesn't exist."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "outputs": {"result": {"source": "nonexistent.output"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 1
        assert "nonexistent" in errors[0].message.lower()
        assert "result" in errors[0].message
        assert "non-existent source" in errors[0].message.lower()

    def test_invalid_output_source_shows_available_nodes(self):
        """❌ Invalid: Error message includes available nodes for debugging."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "fetch", "type": "read-file", "params": {}},
                {"id": "process", "type": "llm", "params": {}},
            ],
            "edges": [{"from": "fetch", "to": "process"}],
            "outputs": {"result": {"source": "missing"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 1
        assert "missing" in errors[0].message
        assert errors[0].context is not None
        assert errors[0].context.get("available_fields_label") == "sources"
        assert "fetch" in errors[0].context.get("available_fields", [])
        assert "process" in errors[0].context.get("available_fields", [])

    def test_valid_output_without_source_field(self):
        """✅ Valid: Output without source field is allowed."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "outputs": {"result": {"description": "No source specified", "type": "string"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_valid_output_with_template_input_field_access(self):
        """✅ Valid: Template referencing declared input field passes.

        Bug prevented: Validator rejects ${input.field} as non-existent node (GH #247).
        Without this test: Can't use ${data.field} in outputs when data is a declared input.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "inputs": {"data": {"type": "dict", "description": "A dict with a field"}},
            "outputs": {"result": {"source": "${data.field}"}},
        }

        errors, _ = split_validator_diagnostics(workflow, None, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_valid_plain_source_references_declared_input(self):
        """✅ Valid: Plain source referencing declared input passes.

        Bug prevented: Plain data.field rejected when data is a declared input.
        Without this test: Only template ${data.field} works, plain data.field doesn't.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "inputs": {"data": {"type": "dict", "description": "A dict"}},
            "outputs": {"result": {"source": "data.field"}},
        }

        errors, _ = split_validator_diagnostics(workflow, None, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_multiple_outputs_mixed_validity(self):
        """❌ Invalid: Multiple outputs, some valid, some invalid."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node1", "type": "shell", "params": {}},
                {"id": "node2", "type": "llm", "params": {}},
            ],
            "edges": [],
            "outputs": {
                "valid1": {"source": "node1.stdout"},  # ✅ Valid
                "valid2": {"source": "node2"},  # ✅ Valid
                "invalid1": {"source": "fake.output"},  # ❌ Invalid
                "invalid2": {"source": "missing"},  # ❌ Invalid
            },
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 2
        # Check both invalid outputs are caught
        assert any("invalid1" in d.message and "fake" in d.message for d in errors)
        assert any("invalid2" in d.message and "missing" in d.message for d in errors)

    def test_output_source_case_sensitive(self):
        """❌ Invalid: Node IDs are case-sensitive."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "MyNode", "type": "shell", "params": {}}],
            "edges": [],
            "outputs": {"result": {"source": "mynode.output"}},  # Wrong case
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 1
        assert "mynode" in errors[0].message.lower()

    def test_empty_outputs_is_valid(self):
        """✅ Valid: Workflow with no outputs is valid."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "outputs": {},  # No outputs
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_missing_outputs_key_is_valid(self):
        """✅ Valid: Workflow without outputs key is valid."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            # No "outputs" key at all
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_empty_source_string_is_invalid(self):
        """❌ Invalid: Empty source string should error."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "outputs": {"result": {"source": ""}},  # Empty string
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 1
        assert "empty" in errors[0].message.lower()

    def test_whitespace_only_source_is_invalid(self):
        """❌ Invalid: Whitespace-only source string should error."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "shell", "params": {}}],
            "edges": [],
            "outputs": {"result": {"source": "   "}},  # Whitespace only
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 1
        assert "empty" in errors[0].message.lower()

    def test_real_world_workflow_with_valid_outputs(self):
        """✅ Valid: Real-world workflow with multiple valid output sources."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fetch_data",
                    "type": "http",
                    "params": {"url": "https://api.example.com/data"},
                },
                {"id": "process", "type": "llm", "params": {"prompt": "Analyze this"}},
                {"id": "save", "type": "write-file", "params": {"file_path": "output.txt"}},
            ],
            "edges": [{"from": "fetch_data", "to": "process"}, {"from": "process", "to": "save"}],
            "outputs": {
                "raw_data": {"source": "fetch_data.body", "description": "Raw API response"},
                "analysis": {"source": "process.response", "description": "LLM analysis"},
                "file_path": {"source": "save.file_path", "description": "Saved file location"},
            },
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        assert len(errors) == 0

    def test_validation_with_no_nodes_but_outputs(self):
        """❌ Invalid: Workflow with outputs but no nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [],  # No nodes
            "edges": [],
            "outputs": {"result": {"source": "node1.output"}},
        }

        errors, _ = split_validator_diagnostics(workflow, {}, Registry(), skip_node_types=True)
        # Should have at least one error (output references non-existent node)
        assert len(errors) >= 1
        assert any("node1" in d.message for d in errors)
