"""Test the unified WorkflowValidator."""

from unittest.mock import patch

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry
from tests.shared.diagnostic_helpers import (
    split_template_diagnostics,
    split_validator_diagnostics,
)

# Note: Removed autouse fixture that was modifying user's registry.
# The global test isolation in tests/conftest.py now ensures tests use
# temporary registry paths, and nodes are auto-discovered as needed.


@pytest.fixture
def registry_with_nodes():
    """Create a registry with required nodes for validation tests.

    The Registry class automatically discovers core nodes when load() is called
    on an empty registry, so we just need to create and load it.
    """
    registry = Registry()
    # This will trigger auto-discovery if the registry doesn't exist yet
    registry.load()
    return registry


class TestWorkflowValidator:
    """Test unified validation orchestration."""

    def test_complete_validation_all_checks(self, registry_with_nodes):
        """Test that all validation types run for valid workflow."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "${input_file}"}},
                {"id": "n2", "type": "llm", "params": {"prompt": "${n1.content}"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "inputs": {"input_file": {"type": "string", "required": True}},
        }

        errors, _warnings = split_validator_diagnostics(
            workflow, extracted_params={"input_file": "test.txt"}, registry=registry_with_nodes, skip_node_types=True
        )

        # Valid workflow should have no errors
        assert errors == []

    def test_structural_validation_errors(self):
        """Test that structural errors are caught."""
        workflow = {
            # Missing required ir_version
            "nodes": [{"id": "n1", "type": "test"}],
            "edges": [],
        }

        errors, _warnings = split_validator_diagnostics(workflow)

        assert len(errors) > 0
        assert any("ir_version" in d.message for d in errors)

    def test_unresolved_batch_template_produces_only_schema_error(self, registry_with_nodes):
        """Regression guard for issue #237.

        ``batch: ${items}`` is a schema violation (``batch`` must be an object,
        not a string). Before the short-circuit, the data-flow and template
        validators crashed on the malformed IR and their defensive wrappers
        produced two additional misleading errors alongside the real schema
        error — three errors for one root cause.

        After #237: structural validation fails, pipeline short-circuits,
        exactly one actionable error reaches the user.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    "params": {"command": "echo ${item.name}"},
                    "batch": "${items}",
                }
            ],
            "edges": [],
            "inputs": {"items": {"type": "array", "default": [{"name": "a"}]}},
        }

        errors, _warnings = split_validator_diagnostics(
            workflow,
            extracted_params={"items": [{"name": "a"}]},
            registry=registry_with_nodes,
        )

        assert len(errors) == 1, (
            f"Expected exactly 1 schema error (short-circuit), got {len(errors)}: {[e.message for e in errors]}"
        )
        diagnostic = errors[0]
        assert "object" in diagnostic.message.lower()
        assert (diagnostic.context or {}).get("path") == "nodes[0].batch"

    def test_data_flow_validation_errors(self):
        """Test that data flow errors are caught."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n2", "type": "test", "params": {"data": "${n1.output}"}},
                {"id": "n1", "type": "test", "params": {}},
            ],
            "edges": [
                {"from": "n2", "to": "n1"}  # Wrong order!
            ],
            "inputs": {},
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        assert len(errors) > 0
        assert any("after" in d.message for d in errors)

    def test_multiple_stdin_inputs_validation_error(self):
        """Test that multiple stdin: true inputs are caught.

        Only one input can receive piped stdin data. This validation ensures
        early error detection during static validation (--validate-only)
        rather than only at runtime.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
            "inputs": {
                "data1": {"type": "string", "required": True, "stdin": True},
                "data2": {"type": "string", "required": True, "stdin": True},
            },
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        assert len(errors) > 0
        assert any("stdin" in d.message.lower() for d in errors)
        assert any("data1" in d.message for d in errors)
        assert any("data2" in d.message for d in errors)

    def test_single_stdin_input_valid(self):
        """Test that a single stdin: true input is valid."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {"data": "${data}"}}],
            "edges": [],
            "inputs": {
                "data": {"type": "string", "required": True, "stdin": True},
            },
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        # Should not have stdin-related errors
        assert not any("stdin" in d.message.lower() for d in errors)

    def test_multiple_stdout_outputs_validation_error(self):
        """Multiple outputs marked stdout: true → validator error.

        Mirrors the stdin at-most-one invariant. The error message must name
        all offending outputs so the user knows which ones to fix.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
            "outputs": {
                "a": {"source": "${n1.out}", "stdout": True},
                "b": {"source": "${n1.out}", "stdout": True},
            },
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        stdout_diag = next(d for d in errors if "stdout" in d.message.lower())
        assert "a" in stdout_diag.message and "b" in stdout_diag.message

    def test_single_stdout_output_valid(self):
        """A single output marked stdout: true is valid."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
            "outputs": {
                "a": {"source": "${n1.out}", "stdout": True},
                "b": {"source": "${n1.out}"},
            },
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        # Should not flag stdout when only one output carries the marker
        assert not any("stdout" in d.message.lower() and "multiple" in d.message.lower() for d in errors)

    def test_no_stdout_marker_is_valid(self):
        """Omitting the stdout marker does not fail validation — runtime decides."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
            "outputs": {
                "a": {"source": "${n1.out}"},
                "b": {"source": "${n1.out}"},
            },
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        assert not any("stdout" in d.message.lower() for d in errors)

    def test_template_validation_errors(self, registry_with_nodes):
        """Test that template errors are caught when params provided."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "read-file", "params": {"file_path": "${missing_param}"}}],
            "edges": [],
            "inputs": {"missing_param": {"type": "string", "required": True}},
        }

        # With extracted_params but missing the required param
        errors, _warnings = split_validator_diagnostics(
            workflow,
            extracted_params={},  # Empty params
            registry=registry_with_nodes,
        )

        assert len(errors) > 0
        assert any("missing_param" in d.message for d in errors)

    def test_skip_template_validation_without_params(self):
        """Test that template validation is skipped without extracted_params."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {"file_path": "${missing_param}"}}],
            "edges": [],
            "inputs": {"missing_param": {"type": "string"}},
        }

        # Without extracted_params - should skip template validation
        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        # Should not have template errors
        assert not any("missing_param" in d.message for d in errors)

    def test_node_type_validation_errors(self, registry_with_nodes):
        """Test that unknown node types are caught."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "unknown-node-type", "params": {}}],
            "edges": [],
            "inputs": {},
        }

        # With node type validation enabled
        errors, _warnings = split_validator_diagnostics(workflow, registry=registry_with_nodes, skip_node_types=False)

        assert len(errors) > 0
        assert any("Unknown node type" in d.message for d in errors)
        assert any("unknown-node-type" in d.message for d in errors)

    def test_workflow_node_type_bypasses_registry(self, registry_with_nodes):
        """Test that 'workflow' type is accepted without registry lookup.

        The 'workflow' type is handled specially by the compiler (not registered
        in the node registry). The validator must not reject it as unknown.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "workflow",
                    "params": {
                        "workflow": "./child.pflow.md",
                    },
                },
            ],
            "edges": [],
            "inputs": {},
        }

        errors, _warnings = split_validator_diagnostics(workflow, registry=registry_with_nodes, skip_node_types=False)

        # Should not have "Unknown node type" for workflow
        assert not any("Unknown node type" in d.message for d in errors)

    def test_workflow_auto_outputs_resolve_in_templates(self, tmp_path, registry_with_nodes):
        """Workflow nodes auto-expose child's declared outputs for template validation.

        When a workflow node references a child .pflow.md file that declares
        ## Outputs, the template validator should resolve references to those
        outputs without errors (e.g., ${process.result}).
        """
        # Create child workflow with declared outputs
        child_content = """# Child

## Outputs

### result

- source: ${step.stdout}

## Steps

### step

Do something.

- type: shell
- command: echo hello
"""
        child_file = tmp_path / "child.pflow.md"
        child_file.write_text(child_content, encoding="utf-8")

        # Parent workflow references child and uses its output
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "process",
                    "type": "workflow",
                    "params": {"workflow": str(child_file)},
                },
                {
                    "id": "use_output",
                    "type": "shell",
                    "params": {"command": "echo ${process.result}"},
                },
            ],
            "edges": [{"from": "process", "to": "use_output"}],
        }

        # The template validator should resolve ${process.result} successfully
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry_with_nodes)

        template_errors = [d for d in errors if "process" in d.message and "result" in d.message]
        assert len(template_errors) == 0, f"Unexpected errors for workflow output: {template_errors}"

    def test_workflow_dynamic_outputs_no_false_errors(self, registry_with_nodes):
        """Workflow nodes with unresolvable references should not produce false errors.

        When a workflow node references a saved workflow name that can't be loaded
        at validation time, the validator marks the node as dynamic and accepts
        any output reference from it.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "process",
                    "type": "workflow",
                    "params": {"workflow": "some-saved-workflow"},
                },
                {
                    "id": "use_output",
                    "type": "shell",
                    "params": {"command": "echo ${process.anything}"},
                },
            ],
            "edges": [{"from": "process", "to": "use_output"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry_with_nodes)

        # Dynamic workflow should NOT produce errors for any output reference
        template_errors = [d for d in errors if "process" in d.message and "anything" in d.message]
        assert len(template_errors) == 0, f"False errors for dynamic workflow output: {template_errors}"

    def test_skip_node_types_for_mocks(self, registry_with_nodes):
        """Test selective validation skipping for mock nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "mock-node", "params": {"data": "test"}}],
            "edges": [],
            "inputs": {},
        }

        # With node type validation - should fail
        errors_with_validation, _ = split_validator_diagnostics(
            workflow, registry=registry_with_nodes, skip_node_types=False
        )
        assert any("Unknown node type" in d.message for d in errors_with_validation)

        # Without node type validation - should pass
        errors_without_validation, _ = split_validator_diagnostics(
            workflow, registry=registry_with_nodes, skip_node_types=True
        )
        assert not any("Unknown node type" in d.message for d in errors_without_validation)

    def test_accumulates_all_error_types(self, registry_with_nodes):
        """Test that all error types are collected."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "unknown-node", "params": {"data": "${n2.output}"}},
                {"id": "n2", "type": "another-unknown", "params": {"data": "${missing_input}"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],  # Wrong order for data flow
            "inputs": {},
        }

        errors, _warnings = split_validator_diagnostics(workflow, extracted_params={}, registry=registry_with_nodes)

        # Should have multiple error types
        assert len(errors) >= 3
        # Node type errors
        assert any("Unknown node type" in d.message and "unknown-node" in d.message for d in errors)
        assert any("Unknown node type" in d.message and "another-unknown" in d.message for d in errors)
        # Data flow error
        assert any(("forward" in d.message.lower() or "after" in d.message.lower()) for d in errors)
        # Template error
        assert any("missing_input" in d.message for d in errors)

    def test_circular_dependency_detection(self):
        """Test that circular dependencies are caught."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "test", "params": {"data": "${b.output}"}},
                {"id": "b", "type": "test", "params": {"data": "${a.output}"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},  # Creates cycle
            ],
            "inputs": {},
        }

        errors, _warnings = split_validator_diagnostics(workflow, skip_node_types=True)

        assert len(errors) > 0
        assert any("Circular dependency" in d.message for d in errors)

    def test_valid_complex_workflow(self, registry_with_nodes, monkeypatch):
        """Test that a complex valid workflow passes all checks."""
        # OPENAI_API_KEY satisfies the new step-9 LLM model-id preflight for
        # the ``openai/gpt-4`` node below; without it the validator would
        # correctly flag this as a missing-key error.
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "fetch",
                    "type": "http",
                    "params": {
                        "url": "${api_url}",
                        "method": "GET",
                    },
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {
                        "prompt": "Analyze this response: ${fetch.response}",
                        "model": "openai/gpt-4",
                    },
                },
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {
                        "file_path": "${output_file}",
                        "content": "${analyze.response}",
                    },
                },
            ],
            "edges": [
                {"from": "fetch", "to": "analyze"},
                {"from": "analyze", "to": "write"},
            ],
            "inputs": {
                "api_url": {"type": "string", "required": True},
                "output_file": {"type": "string", "required": True},
            },
        }

        errors, _warnings = split_validator_diagnostics(
            workflow,
            extracted_params={
                "api_url": "https://api.example.com/data",
                "output_file": "report.md",
            },
            registry=registry_with_nodes,
            skip_node_types=True,
        )

        # Should pass all validations
        assert errors == []


class TestStructuralWrapperDiagnostic:
    """The lone surviving defensive ``except Exception`` wrapper lives in
    ``_validate_structure`` because ``validate_ir`` calls the third-party
    ``jsonschema`` library. Downstream validators ran on our own code and
    their wrappers were deleted (issue #237) — producer bugs there now
    propagate to the outer CLI/MCP exception boundary, which converts them
    to structured Diagnostics via ``exception_to_diagnostics``.

    The structural wrapper must NOT set ``context['exception_type']`` —
    that key is runtime-only and would render as ``Type: X`` (making a
    validation error look like an unhandled runtime crash).
    """

    def test_structural_wrapper_diagnostic_has_no_exception_type(self) -> None:
        with patch("pflow.core.ir_schema.validate_ir", side_effect=RuntimeError("boom")):
            diagnostics = WorkflowValidator._validate_structure({"ir_version": "0.1.0", "nodes": []})

        assert len(diagnostics) == 1
        diagnostic = diagnostics[0]
        assert diagnostic.severity == Severity.ERROR
        assert "Unexpected error during structural validation" in diagnostic.message
        assert "boom" in diagnostic.message
        assert "exception_type" not in (diagnostic.context or {})


class TestValidatorProducerStructure:
    """Lock in the structured contract for rich outer-validator producers."""

    def test_unknown_node_type_diagnostic_preserves_structure(self, registry_with_nodes) -> None:
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "shel", "params": {"command": "echo hi"}}],
            "edges": [],
        }

        errors, _warnings = split_validator_diagnostics(
            workflow_ir,
            registry=registry_with_nodes,
            skip_node_types=False,
        )

        assert len(errors) == 1
        diagnostic = errors[0]
        assert diagnostic.severity == Severity.ERROR
        assert diagnostic.node_id == "n1"
        assert diagnostic.context is not None
        assert diagnostic.context.get("path") == "nodes[0].type"
        assert diagnostic.context.get("node_type") == "shel"

    def test_unknown_node_type_does_not_double_report_with_templates_enabled(self, registry_with_nodes) -> None:
        """When templates run before node-type validation, an unknown node type
        must produce exactly ONE rich diagnostic (from V6), not a duplicate.

        Two independent mechanisms now enforce this:
        1. ``_register_node_outputs_from_registry`` silently skips unknown types
           so ``validate_workflow_templates`` returns cleanly; the rich V6
           diagnostic comes exclusively from ``_validate_node_types`` (step 5).
        2. If (1) ever regresses and raises, the exception would propagate to
           the outer CLI/MCP boundary rather than being absorbed into a
           duplicate generic "Template validation error" (issue #237 removed
           the wrappers that used to produce that shape).
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "shel", "params": {"command": "echo hi"}},
            ],
            "edges": [],
        }

        # Pass extracted_params={} to force step 4 (template validation) to run
        # BEFORE step 5 (node type validation) — this is the call path the fix
        # addresses. Before the fix, this produced 2 errors (1 generic template
        # wrapper + 1 rich unknown-node-type); after the fix, only the rich one.
        errors, _warnings = split_validator_diagnostics(
            workflow_ir,
            extracted_params={},
            registry=registry_with_nodes,
            skip_node_types=False,
        )

        # Exactly one error — the rich one from _validate_node_types, no duplicate
        # generic "Template validation error" from the wrapper catching a ValueError.
        assert len(errors) == 1, (
            f"Expected exactly 1 error (the rich V6 diagnostic), got {len(errors)}: {[e.message for e in errors]}"
        )
        diagnostic = errors[0]
        assert diagnostic.node_id == "n1"
        assert "Unknown node type" in diagnostic.message
        # Must be the structured V6 diagnostic, not the generic template wrapper
        assert diagnostic.context is not None
        assert diagnostic.context.get("path") == "nodes[0].type"
        assert "Template validation error" not in diagnostic.message

    def test_empty_output_source_diagnostic_preserves_path(self) -> None:
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
            "outputs": {"result": {"source": ""}},
            "edges": [],
        }

        errors = WorkflowValidator._validate_output_sources(workflow_ir)

        assert len(errors) == 1
        diagnostic = errors[0]
        assert diagnostic.context is not None
        assert diagnostic.context.get("path") == "outputs.result.source"

    def test_output_source_missing_node_preserves_structure(self) -> None:
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "producer", "type": "shell", "params": {"command": "echo hi"}}],
            "outputs": {"result": {"source": "producre"}},
            "edges": [],
        }

        errors = WorkflowValidator._validate_output_sources(workflow_ir)

        assert len(errors) == 1
        diagnostic = errors[0]
        assert diagnostic.context is not None
        assert diagnostic.context.get("path") == "outputs.result.source"
        assert "producer" in diagnostic.context.get("available_fields", [])
        assert diagnostic.context.get("available_fields_label") == "sources"
        assert diagnostic.context.get("similar_names")
        assert any("producer" in name for name in diagnostic.context["similar_names"])

    def test_output_source_template_missing_node_preserves_structure(self) -> None:
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "producer", "type": "shell", "params": {"command": "echo hi"}}],
            "outputs": {"result": {"source": "${producre.stdout}"}},
            "edges": [],
        }

        errors = WorkflowValidator._validate_output_sources(workflow_ir)

        assert len(errors) == 1
        diagnostic = errors[0]
        assert diagnostic.title == "Template Error"
        assert diagnostic.context is not None
        assert diagnostic.context.get("template") == "${producre.stdout}"
        assert "producer" in diagnostic.context.get("available_fields", [])
        assert diagnostic.context.get("similar_names")
        assert diagnostic.suggestions


class TestUnknownMcpNodeSyncHint:
    """Bundle 7 / F#22: when an unknown ``mcp-<server>-<tool>`` node type
    matches a configured MCP server that has zero synced tools, the validator
    emits a ``pflow mcp sync <server>`` suggestion instead of a fuzzy-match.

    The diagnostic ``message`` MUST remain ``Unknown node type: '<type>'`` —
    several downstream tests pin that exact string. Only ``suggestions`` and
    ``context`` change.
    """

    def _make_workflow(self, node_type: str) -> dict:
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": node_type, "params": {}}],
            "edges": [],
            "inputs": {},
        }

    def test_unknown_mcp_node_type_with_registered_server_zero_tools_suggests_sync(self, registry_with_nodes) -> None:
        workflow_ir = self._make_workflow("mcp-my-server-some-tool")

        with (
            patch(
                "pflow.mcp.manager.MCPServerManager.list_servers",
                return_value=["my-server"],
            ),
            patch(
                "pflow.mcp.registrar.MCPRegistrar.list_registered_tools",
                return_value=[],
            ),
        ):
            errors, _warnings = split_validator_diagnostics(
                workflow_ir,
                registry=registry_with_nodes,
                skip_node_types=False,
            )

        unknown_errors = [d for d in errors if "Unknown node type" in d.message]
        assert len(unknown_errors) == 1
        diagnostic = unknown_errors[0]
        assert diagnostic.suggestions == [
            "Run 'pflow mcp sync my-server' to discover tools for the 'my-server' MCP server."
        ]
        assert diagnostic.context is not None
        assert diagnostic.context.get("mcp_server") == "my-server"
        assert diagnostic.context.get("mcp_sync_required") is True

    def test_unknown_mcp_node_type_with_registered_server_with_synced_tools_falls_through_to_fuzzy_match(
        self, registry_with_nodes
    ) -> None:
        workflow_ir = self._make_workflow("mcp-my-server-some-tool")

        with (
            patch(
                "pflow.mcp.manager.MCPServerManager.list_servers",
                return_value=["my-server"],
            ),
            patch(
                "pflow.mcp.registrar.MCPRegistrar.list_registered_tools",
                return_value=["mcp-my-server-existing-tool"],
            ),
        ):
            errors, _warnings = split_validator_diagnostics(
                workflow_ir,
                registry=registry_with_nodes,
                skip_node_types=False,
            )

        unknown_errors = [d for d in errors if "Unknown node type" in d.message]
        assert len(unknown_errors) == 1
        diagnostic = unknown_errors[0]
        assert diagnostic.context is not None
        assert "mcp_sync_required" not in diagnostic.context
        assert "mcp_server" not in diagnostic.context
        # Sync hint text must not appear when sync-hint path didn't fire.
        if diagnostic.suggestions is not None:
            assert all("pflow mcp sync" not in s for s in diagnostic.suggestions)

    def test_unknown_mcp_node_type_with_unregistered_server_falls_through(self, registry_with_nodes) -> None:
        workflow_ir = self._make_workflow("mcp-not-a-server-tool")

        # list_servers returns a server, but it doesn't match the parsed server
        # name from the node_type. _parse_mcp_node_type will raise (no matching
        # server in the configured list) → helper returns None.
        with patch(
            "pflow.mcp.manager.MCPServerManager.list_servers",
            return_value=["some-other-server"],
        ):
            errors, _warnings = split_validator_diagnostics(
                workflow_ir,
                registry=registry_with_nodes,
                skip_node_types=False,
            )

        unknown_errors = [d for d in errors if "Unknown node type" in d.message]
        assert len(unknown_errors) == 1
        diagnostic = unknown_errors[0]
        assert diagnostic.context is not None
        assert "mcp_sync_required" not in diagnostic.context
        if diagnostic.suggestions is not None:
            assert all("pflow mcp sync" not in s for s in diagnostic.suggestions)

    def test_unknown_non_mcp_node_type_unaffected(self, registry_with_nodes) -> None:
        """Non-MCP unknown types short-circuit on ``startswith('mcp-')``.
        The sync-hint branch must NOT fire, the existing fuzzy-match path runs
        instead (with no MCP-aware context fields added).
        """
        workflow_ir = self._make_workflow("shll")  # not MCP-shaped

        errors, _warnings = split_validator_diagnostics(
            workflow_ir,
            registry=registry_with_nodes,
            skip_node_types=False,
        )

        unknown_errors = [d for d in errors if "Unknown node type" in d.message]
        assert len(unknown_errors) == 1
        diagnostic = unknown_errors[0]
        assert diagnostic.context is not None
        assert "mcp_sync_required" not in diagnostic.context
        assert "mcp_server" not in diagnostic.context
        if diagnostic.suggestions is not None:
            assert all("pflow mcp sync" not in s for s in diagnostic.suggestions)

    def test_unknown_mcp_node_type_with_unparseable_name_falls_through(self, registry_with_nodes) -> None:
        """A node type like ``mcp-`` doesn't parse (fewer than 3 dash-segments)
        → ``_parse_mcp_node_type`` raises ``CompilationError`` → helper
        returns None → validator emits the diagnostic without the sync hint.
        """
        workflow_ir = self._make_workflow("mcp-")

        errors, _warnings = split_validator_diagnostics(
            workflow_ir,
            registry=registry_with_nodes,
            skip_node_types=False,
        )

        unknown_errors = [d for d in errors if "Unknown node type" in d.message]
        assert len(unknown_errors) == 1
        diagnostic = unknown_errors[0]
        assert diagnostic.context is not None
        assert "mcp_sync_required" not in diagnostic.context
        if diagnostic.suggestions is not None:
            assert all("pflow mcp sync" not in s for s in diagnostic.suggestions)

    def test_mcp_sync_hint_helper_returns_none_on_mcp_infrastructure_exception(self, registry_with_nodes) -> None:
        """If MCP infrastructure raises (e.g. corrupted config, settings load
        failure), the helper must swallow the error and the validator must
        continue running. The diagnostic still gets emitted without the
        sync hint.
        """
        workflow_ir = self._make_workflow("mcp-some-server-some-tool")

        with patch(
            "pflow.mcp.manager.MCPServerManager.list_servers",
            side_effect=RuntimeError("config corrupted"),
        ):
            errors, _warnings = split_validator_diagnostics(
                workflow_ir,
                registry=registry_with_nodes,
                skip_node_types=False,
            )

        unknown_errors = [d for d in errors if "Unknown node type" in d.message]
        assert len(unknown_errors) == 1
        diagnostic = unknown_errors[0]
        assert diagnostic.context is not None
        assert "mcp_sync_required" not in diagnostic.context
        if diagnostic.suggestions is not None:
            assert all("pflow mcp sync" not in s for s in diagnostic.suggestions)

    def test_mcp_sync_hint_does_not_change_diagnostic_message(self, registry_with_nodes) -> None:
        """Locks the message-string contract that pre-existing tests depend on
        (e.g. test_cache_analysis_analyze.py, test_cache_analysis_renderers.py,
        test_validation_before_execution.py). Both code branches — sync hint
        fired and not fired — must produce the exact same message format.
        """
        # Branch A: sync hint fires (registered server, zero tools)
        workflow_a = self._make_workflow("mcp-my-server-some-tool")
        with (
            patch(
                "pflow.mcp.manager.MCPServerManager.list_servers",
                return_value=["my-server"],
            ),
            patch(
                "pflow.mcp.registrar.MCPRegistrar.list_registered_tools",
                return_value=[],
            ),
        ):
            errors_a, _ = split_validator_diagnostics(workflow_a, registry=registry_with_nodes, skip_node_types=False)

        # Branch B: sync hint does NOT fire (server not registered)
        workflow_b = self._make_workflow("mcp-other-server-tool")
        with patch(
            "pflow.mcp.manager.MCPServerManager.list_servers",
            return_value=["something-else"],
        ):
            errors_b, _ = split_validator_diagnostics(workflow_b, registry=registry_with_nodes, skip_node_types=False)

        msgs_a = [d.message for d in errors_a if "Unknown node type" in d.message]
        msgs_b = [d.message for d in errors_b if "Unknown node type" in d.message]
        assert msgs_a == ["Unknown node type: 'mcp-my-server-some-tool'"]
        assert msgs_b == ["Unknown node type: 'mcp-other-server-tool'"]


class TestReservedLiteralNames:
    """Optional A: inputs/node IDs named true/false/null are unreachable in
    templates (${true} → literal), so the validator must reject them loudly."""

    def test_input_named_true_is_rejected(self):
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
            "inputs": {"true": {"type": "string"}},
        }
        errors, _ = split_validator_diagnostics(workflow, skip_node_types=True)
        assert any("reserved literal keyword" in d.message for d in errors)
        assert any("'true'" in d.message for d in errors)

    def test_node_named_false_is_rejected(self):
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "false", "type": "test", "params": {}}],
            "edges": [],
        }
        errors, _ = split_validator_diagnostics(workflow, skip_node_types=True)
        assert any("reserved literal keyword" in d.message for d in errors)
        assert any("'false'" in d.message for d in errors)

    def test_input_named_null_is_rejected(self):
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
            "inputs": {"null": {"type": "string"}},
        }
        errors, _ = split_validator_diagnostics(workflow, skip_node_types=True)
        assert any("reserved literal keyword" in d.message for d in errors)

    def test_ordinary_names_are_not_rejected(self):
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "is_true", "type": "test", "params": {}}],
            "edges": [],
            "inputs": {"truthy_value": {"type": "string"}},
        }
        errors, _ = split_validator_diagnostics(workflow, skip_node_types=True)
        assert not any("reserved literal keyword" in d.message for d in errors)
