"""Task 125 — the ``approval:`` field: parser hoist, IR schema, validation, compile.

The field rides the exact ``prewarm``/``cache`` top-level path: hoisted out of
params by the parser (so it never reaches node exec params or the cache hash),
allowlisted in the IR schema (``additionalProperties: False`` on nodes), rejected
on batch hosts by ONE shared rule at BOTH entry points (validator diagnostic +
compiler ``CompilationError``), and landed on ``NodeConfig.approval``.
"""

from __future__ import annotations

from typing import Any

import pytest

from pflow.core.exceptions import CompilationError
from pflow.core.markdown_parser import parse_markdown
from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry
from pflow.runtime import compile_workflow

GATED_MARKDOWN = """# Notify

Send a message after approval.

## Steps

### notify

Post the message.

- type: shell
- command: echo send-it
- approval: required
"""


class TestParserHoist:
    def test_markdown_parsed_gate_preview_has_no_bookkeeping_keys(self):
        # Code-block params carry engine bookkeeping (`_python_source_line`); the
        # approval preview is a display surface and must filter `_`-prefixed keys
        # like every other one (node_output_formatter / trace_report convention).
        from pflow.core.exceptions import GateNotInteractiveError
        from pflow.runtime.engine import WorkflowEngine

        md = (
            "# Gate\n\nGated code step.\n\n## Steps\n\n### calc\n\nCompute a thing.\n\n"
            "- type: code\n- approval: required\n\n```python\nresult: str = 'x'\n```\n"
        )
        compiled = compile_workflow(parse_markdown(md).ir, Registry())
        assert "_python_source_line" in compiled.start_node.params  # the leak source exists
        with pytest.raises(GateNotInteractiveError) as exc_info:
            WorkflowEngine().run(compiled, {})
        assert list(exc_info.value.request.preview) == ["python"]

    def test_approval_is_hoisted_out_of_params(self):
        ir = parse_markdown(GATED_MARKDOWN).ir
        (node,) = ir["nodes"]
        assert node["approval"] == "required"
        assert "approval" not in node["params"]

    def test_workflow_without_approval_has_no_field(self):
        ir = parse_markdown(GATED_MARKDOWN.replace("- approval: required\n", "")).ir
        (node,) = ir["nodes"]
        assert "approval" not in node


def _ir(node: dict[str, Any]) -> dict[str, Any]:
    return {"ir_version": "0.1.0", "nodes": [node], "edges": []}


def _shell(**extra: Any) -> dict[str, Any]:
    return {"id": "n", "type": "shell", "params": {"command": "echo hi"}, **extra}


class TestSchemaAndValidation:
    def test_valid_gate_passes_validation_cleanly(self):
        diagnostics = WorkflowValidator().validate(_ir(_shell(approval="required")))
        assert diagnostics == []

    def test_invalid_enum_value_fails_with_field_path(self):
        diagnostics = WorkflowValidator().validate(_ir(_shell(approval="banana")))
        assert any("approval" in str(d.context.get("path", "")) for d in diagnostics)

    def test_bool_value_gets_the_required_suggestion(self):
        # `- approval: true` is the likeliest agent mistake (YAML coerces to bool);
        # the generic type-arm would steer toward the string "true", which then
        # fails the enum. The approval arm short-circuits both shapes.
        diagnostics = WorkflowValidator().validate(_ir(_shell(approval=True)))
        assert any("approval: required" in s for d in diagnostics for s in (d.suggestions or []))

    def test_batch_host_gate_rejected_by_validator(self):
        node = _shell(approval="required", batch={"items": "${items}", "as": "item"})
        node["params"]["command"] = "echo ${item}"
        diagnostics = WorkflowValidator().validate(_ir(node))
        messages = [d.message for d in diagnostics]
        assert any("not supported on batch steps" in m for m in messages)
        assert any("before or after the batch" in m for m in messages)

    def test_gate_inside_subworkflow_validated_recursively(self, tmp_path):
        # Task 136 recursive validation: a batch-host gate hidden in a CHILD
        # workflow is caught when validating the parent.
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild with an invalid batch gate.\n\n## Steps\n\n"
            "### fan\n\nFan out.\n\n- type: shell\n- command: echo ${item}\n"
            "- approval: required\n"
            "- batch:\n    items: ${items}\n    as: item\n"
        )
        parent_ir = _ir({"id": "sub", "type": "workflow", "params": {"workflow": str(child)}})
        diagnostics = WorkflowValidator().validate(parent_ir, workflow_file=tmp_path / "parent.pflow.md")
        assert any("not supported on batch steps" in d.message for d in diagnostics)


class TestCompiler:
    def test_node_config_carries_approval(self):
        compiled = compile_workflow(_ir(_shell(approval="required")), Registry())
        assert compiled.node_configs["n"].approval is True

    def test_node_config_defaults_to_false(self):
        compiled = compile_workflow(_ir(_shell()), Registry())
        assert compiled.node_configs["n"].approval is False

    def test_non_required_value_is_a_compilation_error(self):
        with pytest.raises(CompilationError, match="approval"):
            compile_workflow(_ir(_shell(approval=True)), Registry())

    def test_batch_host_gate_is_a_compilation_error(self):
        node = _shell(approval="required", batch={"items": "${items}", "as": "item"})
        node["params"]["command"] = "echo ${item}"
        with pytest.raises(CompilationError) as exc_info:
            compile_workflow(_ir(node), Registry())
        rendered = "\n".join(d.message for d in exc_info.value.to_diagnostics())
        assert "not supported on batch steps" in rendered

    def test_workflow_type_node_may_be_gated(self, tmp_path):
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nTrivial child.\n\n## Steps\n\n### s\n\nSay hi.\n\n- type: shell\n- command: echo hi\n"
        )
        ir = _ir({"id": "sub", "type": "workflow", "params": {"workflow": str(child)}, "approval": "required"})
        compiled = compile_workflow(ir, Registry())
        assert compiled.node_configs["sub"].approval is True

    def test_approval_does_not_change_the_cache_config_hash(self):
        # The gate is orthogonal to the node's output — adding it must not
        # invalidate existing memo cache entries.
        from pflow.runtime.engine.instrumentation import compute_config_hash, compute_node_config

        def config_hash(compiled) -> str:
            cfg = compiled.node_configs["n"]
            static = cfg.template_config.static_params if cfg.template_config else compiled.start_node.params
            templates = cfg.template_config.template_params if cfg.template_config else {}
            return compute_config_hash(compute_node_config(cfg.node_type_name, static, templates, cfg.batch_config))

        plain_hash = config_hash(compile_workflow(_ir(_shell()), Registry()))
        gated_hash = config_hash(compile_workflow(_ir(_shell(approval="required")), Registry()))
        assert plain_hash == gated_hash
