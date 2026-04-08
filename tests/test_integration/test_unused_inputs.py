"""Integration test for unused input detection in workflow validation.

This test demonstrates the Task 17 Subtask 5 enhancement working in
a realistic scenario where a workflow declares inputs but doesn't use them all.
"""

from pathlib import Path

import pytest

from pflow.core.file_resolver import resolve_file_references
from pflow.core.ir_schema import normalize_ir
from pflow.core.markdown_parser import parse_markdown
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.registry import Registry
from tests.shared.diagnostic_helpers import (
    split_template_diagnostics,
    split_validator_diagnostics,
)
from tests.shared.markdown_utils import write_workflow_file


class MockRegistry(Registry):
    """Mock registry for testing with predefined node metadata."""

    def __init__(self):
        super().__init__()
        # Pre-populate with file node metadata
        self._nodes_metadata = {
            "read-file": {
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "content", "type": "string"}],
                    "parameters": [{"key": "file_path", "type": "string", "required": True}],
                }
            },
            "write-file": {
                "interface": {
                    "inputs": [{"key": "content", "type": "string"}],
                    "outputs": [],
                    "parameters": [
                        {"key": "file_path", "type": "string", "required": True},
                        {"key": "content", "type": "string", "required": False},
                    ],
                }
            },
            "workflow": {
                "interface": {
                    "inputs": [],
                    "outputs": [],
                    "parameters": [
                        {"key": "workflow_name", "type": "string", "required": True},
                        {"key": "params", "type": "dict", "required": False},
                    ],
                }
            },
        }

    def get_nodes_metadata(self, node_types: list[str]) -> dict:
        """Return mock metadata for requested node types."""
        result = {}
        for node_type in node_types:
            if node_type in self._nodes_metadata:
                result[node_type] = self._nodes_metadata[node_type]
        return result


def test_unused_inputs_detected_before_execution(tmp_path):
    """Test that unused inputs are detected during validation before workflow execution."""
    # Create a workflow that declares inputs but doesn't use them all
    workflow_ir = {
        "ir_version": "0.1.0",
        "name": "example-workflow",
        "inputs": {
            "input_file": {
                "type": "string",
                "description": "Path to input file",
                "required": True,
            },
            "output_file": {
                "type": "string",
                "description": "Path to output file",
                "required": True,
            },
            "unused_option": {
                "type": "string",
                "description": "An option that is never used",
                "required": False,
                "default": "default_value",
            },
            "another_unused": {
                "type": "integer",
                "description": "Another unused parameter",
                "required": False,
            },
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"file_path": "${input_file}"},  # Uses input_file
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {
                    "file_path": "${output_file}",  # Uses output_file
                    "content": "${content}",  # Uses node output
                },
            },
        ],
        "edges": [{"from": "reader", "to": "writer"}],
    }

    # Create mock registry with file nodes
    registry = MockRegistry()

    # Validate templates
    initial_params = {
        "input_file": str(tmp_path / "input.txt"),
        "output_file": str(tmp_path / "output.txt"),
        # Note: unused_option and another_unused are not provided but have defaults or are optional
    }

    errors, _warnings = split_template_diagnostics(workflow_ir, initial_params, registry)

    # Should detect the unused inputs
    assert len(errors) == 1
    assert "Declared input(s) never used as template variable" in errors[0].message
    assert "another_unused" in errors[0].message
    assert "unused_option" in errors[0].message

    # The error should list them in sorted order
    assert "another_unused, unused_option" in errors[0].message


def test_workflow_with_all_inputs_used(tmp_path):
    """Test that no errors occur when all declared inputs are used."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "name": "all-inputs-used",
        "inputs": {
            "source_file": {
                "type": "string",
                "description": "Source file path",
                "required": True,
            },
            "dest_file": {
                "type": "string",
                "description": "Destination file path",
                "required": True,
            },
            "backup_file": {
                "type": "string",
                "description": "Backup file path",
                "required": False,
            },
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"file_path": "${source_file}"},
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"file_path": "${dest_file}", "content": "${content}"},
            },
            {
                "id": "backup",
                "type": "write-file",
                "params": {"file_path": "${backup_file}", "content": "${content}"},
            },
        ],
        "edges": [
            {"from": "reader", "to": "writer"},
            {"from": "reader", "to": "backup"},
        ],
    }

    registry = MockRegistry()

    initial_params = {
        "source_file": str(tmp_path / "source.txt"),
        "dest_file": str(tmp_path / "dest.txt"),
        "backup_file": str(tmp_path / "backup.txt"),
    }

    errors, _warnings = split_template_diagnostics(workflow_ir, initial_params, registry)

    # Should have no errors since all inputs are used
    assert len(errors) == 0


def test_unused_inputs_with_nested_workflows(tmp_path):
    """Test unused input detection with nested workflow execution."""
    # Parent workflow with unused input
    parent_workflow = {
        "ir_version": "0.1.0",
        "name": "parent-workflow",
        "inputs": {
            "config_path": {
                "type": "string",
                "description": "Configuration file path",
                "required": True,
            },
            "unused_debug_flag": {
                "type": "boolean",
                "description": "Debug flag that is never used",
                "required": False,
                "default": False,
            },
        },
        "nodes": [
            {
                "id": "read_config",
                "type": "read-file",
                "params": {"file_path": "${config_path}"},
            },
            {
                "id": "nested_workflow",
                "type": "workflow",
                "params": {
                    "workflow_name": "child-workflow",
                    "params": {"data": "${content}"},
                },
            },
        ],
        "edges": [{"from": "read_config", "to": "nested_workflow"}],
    }

    registry = MockRegistry()

    initial_params = {"config_path": str(tmp_path / "config.json")}

    errors, _warnings = split_template_diagnostics(parent_workflow, initial_params, registry)

    # Should detect the unused debug flag
    assert any("unused_debug_flag" in error.message for error in errors)
    assert any("never used as template variable" in error.message for error in errors)


def test_no_false_positive_for_input_used_in_batch_prompt_files(tmp_path: Path) -> None:
    """When a sub-workflow input is referenced inside external .prompt.md files
    loaded via batch items, the validator should NOT report it as unused.

    This is a regression test for the false-positive bug where
    resolve_file_references was not called on child IRs before recursive
    validation, making template variables inside prompt files invisible.
    """
    # 1. Create external prompt files that reference the sub-workflow input
    (tmp_path / "prompt-a.prompt.md").write_text("Analyze emotionally:\n\n${content}")
    (tmp_path / "prompt-b.prompt.md").write_text("Analyze factually:\n\n${content}")

    # 2. Sub-workflow: declares 'content' input, uses it via batch prompt files
    sub_workflow_ir = {
        "inputs": {
            "content": {
                "type": "string",
                "description": "The content to analyze.",
                "required": True,
            },
        },
        "nodes": [
            {
                "id": "analyze",
                "type": "llm",
                "purpose": "Runs analysis prompts in parallel.",
                "params": {"prompt": "${item.prompt}"},
                "batch": {
                    "items": [
                        {"focus": "emotional", "prompt": "./prompt-a.prompt.md"},
                        {"focus": "factual", "prompt": "./prompt-b.prompt.md"},
                    ],
                    "parallel": True,
                },
            },
        ],
    }
    write_workflow_file(sub_workflow_ir, tmp_path / "sub-workflow.pflow.md", title="Sub Workflow")

    # 3. Parent workflow: passes 'text' input into sub-workflow as 'content'
    parent_workflow_ir = {
        "inputs": {
            "text": {
                "type": "string",
                "description": "Text to be analyzed.",
                "required": True,
            },
        },
        "nodes": [
            {
                "id": "analyze",
                "type": "workflow",
                "purpose": "Delegates analysis to sub-workflow.",
                "params": {
                    "workflow": "./sub-workflow.pflow.md",
                    "content": "${text}",
                },
            },
        ],
    }
    write_workflow_file(parent_workflow_ir, tmp_path / "parent-workflow.pflow.md", title="Parent Workflow")

    # 4. Validate the parent workflow (same pipeline as production)
    parent_path = tmp_path / "parent-workflow.pflow.md"
    content = parent_path.read_text()
    result = parse_markdown(content)
    ir = result.ir
    normalize_ir(ir)
    resolve_file_references(ir, tmp_path)

    inputs = ir.get("inputs", {})
    dummy_params = generate_dummy_parameters(inputs)
    dummy_params["_pflow_workflow_file"] = str(parent_path)

    errors, _warnings = split_validator_diagnostics(
        ir,
        extracted_params=dummy_params,
        skip_node_types=True,
        workflow_file=parent_path,
    )

    # No error should mention 'content' being unused in the sub-workflow
    unused_errors = [d for d in errors if "unused" in d.message.lower() or "never used" in d.message.lower()]
    assert unused_errors == [], f"Expected no unused-input errors, but got: {unused_errors}"


def test_genuinely_unused_input_still_caught_alongside_prompt_file_inputs(tmp_path: Path) -> None:
    """When a sub-workflow has BOTH an input used in prompt files AND a genuinely
    unused input, only the unused one should be flagged.

    Guards against over-broad fixes that suppress all unused-input detection
    for sub-workflows with file references.
    """
    # Prompt file uses ${content} but NOT ${debug_mode}
    (tmp_path / "prompt.prompt.md").write_text("Analyze:\n\n${content}")

    sub_workflow_ir = {
        "inputs": {
            "content": {
                "type": "string",
                "description": "Used in prompt file.",
                "required": True,
            },
            "debug_mode": {
                "type": "string",
                "description": "Genuinely unused anywhere.",
                "required": False,
            },
        },
        "nodes": [
            {
                "id": "analyze",
                "type": "llm",
                "purpose": "Runs analysis via batch prompt file.",
                "params": {"prompt": "${item.prompt}"},
                "batch": {
                    "items": [{"prompt": "./prompt.prompt.md"}],
                },
            },
        ],
    }
    write_workflow_file(sub_workflow_ir, tmp_path / "sub.pflow.md", title="Sub Workflow")

    parent_workflow_ir = {
        "inputs": {
            "text": {
                "type": "string",
                "description": "Text to analyze.",
                "required": True,
            },
        },
        "nodes": [
            {
                "id": "run-sub",
                "type": "workflow",
                "purpose": "Delegates to sub-workflow.",
                "params": {
                    "workflow": "./sub.pflow.md",
                    "content": "${text}",
                    "debug_mode": "on",
                },
            },
        ],
    }
    write_workflow_file(parent_workflow_ir, tmp_path / "parent.pflow.md", title="Parent Workflow")

    parent_path = tmp_path / "parent.pflow.md"
    result = parse_markdown(parent_path.read_text())
    ir = result.ir
    normalize_ir(ir)
    resolve_file_references(ir, tmp_path)

    dummy_params = generate_dummy_parameters(ir.get("inputs", {}))
    dummy_params["_pflow_workflow_file"] = str(parent_path)

    errors, _warnings = split_validator_diagnostics(
        ir,
        extracted_params=dummy_params,
        skip_node_types=True,
        workflow_file=parent_path,
    )

    unused_errors = [d for d in errors if "never used" in d.message.lower()]
    # debug_mode IS genuinely unused — must be caught
    assert any("debug_mode" in d.message for d in unused_errors), (
        f"Expected 'debug_mode' to be flagged as unused, but got: {errors}"
    )
    # content is used in the prompt file — must NOT be flagged
    assert not any("content" in d.message for d in unused_errors), (
        f"'content' should not be flagged as unused (it's in the prompt file), but got: {unused_errors}"
    )


def test_missing_prompt_file_in_sub_workflow_reports_validation_error(tmp_path: Path) -> None:
    """When a sub-workflow references a prompt file that does not exist,
    the validator should produce a validation error (not crash).
    """
    # 1. Sub-workflow references nonexistent prompt files
    sub_workflow_ir = {
        "inputs": {
            "content": {
                "type": "string",
                "description": "The content to analyze.",
                "required": True,
            },
        },
        "nodes": [
            {
                "id": "analyze",
                "type": "llm",
                "purpose": "Runs analysis prompts in parallel.",
                "params": {"prompt": "${item.prompt}"},
                "batch": {
                    "items": [
                        {"focus": "emotional", "prompt": "./nonexistent.prompt.md"},
                    ],
                    "parallel": True,
                },
            },
        ],
    }
    write_workflow_file(sub_workflow_ir, tmp_path / "sub-workflow.pflow.md", title="Sub Workflow")

    # 2. Parent workflow
    parent_workflow_ir = {
        "inputs": {
            "text": {
                "type": "string",
                "description": "Text to be analyzed.",
                "required": True,
            },
        },
        "nodes": [
            {
                "id": "analyze",
                "type": "workflow",
                "purpose": "Delegates analysis to sub-workflow.",
                "params": {
                    "workflow": "./sub-workflow.pflow.md",
                    "content": "${text}",
                },
            },
        ],
    }
    write_workflow_file(parent_workflow_ir, tmp_path / "parent-workflow.pflow.md", title="Parent Workflow")

    # 3. Validate the parent workflow
    parent_path = tmp_path / "parent-workflow.pflow.md"
    content = parent_path.read_text()
    result = parse_markdown(content)
    ir = result.ir
    normalize_ir(ir)
    resolve_file_references(ir, tmp_path)

    inputs = ir.get("inputs", {})
    dummy_params = generate_dummy_parameters(inputs)
    dummy_params["_pflow_workflow_file"] = str(parent_path)

    errors, _warnings = split_validator_diagnostics(
        ir,
        extracted_params=dummy_params,
        skip_node_types=True,
        workflow_file=parent_path,
    )

    # Should produce a "not found" error from the file resolver, not a crash
    not_found_errors = [d for d in errors if "not found" in d.message.lower()]
    assert len(not_found_errors) >= 1, (
        f"Expected at least one 'not found' error for the missing prompt file, but got errors: {errors}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
