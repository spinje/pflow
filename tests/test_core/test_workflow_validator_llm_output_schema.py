"""Static/runtime parity tests for LLM ``output_schema`` validation."""

from __future__ import annotations

from typing import Any

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.workflow.validator import WorkflowValidator


def _workflow(output_schema: Any) -> dict[str, Any]:
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "params": {"prompt": "answer", "output_schema": output_schema},
            }
        ],
    }


def _schema_errors(output_schema: Any) -> list:
    return [
        diagnostic
        for diagnostic in WorkflowValidator.validate(_workflow(output_schema), skip_node_types=True)
        if diagnostic.severity == Severity.ERROR and (diagnostic.context or {}).get("category") == "llm_validation"
    ]


@pytest.mark.parametrize(
    "output_schema",
    [
        {},
        {"$defs": {"answer": {"type": "string"}}, "$ref": "#/$defs/answer"},
        {"const": {"$ref": "https://schemas.example/not-a-schema-reference"}},
    ],
)
def test_literal_valid_schemas_pass_static_validation(output_schema):
    assert _schema_errors(output_schema) == []


@pytest.mark.parametrize(
    "output_schema",
    [
        "${schema}",
        {"type": "${schema.type}"},
    ],
)
def test_templated_schemas_defer_to_runtime(output_schema):
    assert _schema_errors(output_schema) == []


def test_escape_only_schema_is_checked_as_the_node_receives_it():
    """R6 (Task 170): ``$${t}`` holds no reference — the node receives ``{"type": "${t}"}``,
    so the static check runs on that (the partner ``${schema.type}`` above defers)."""
    errors = _schema_errors({"type": "$${t}"})

    assert len(errors) == 1
    assert errors[0].context["schema_path"] == "$.type"
    assert "'${t}' is not valid" in errors[0].message


@pytest.mark.parametrize(
    ("output_schema", "schema_path"),
    [
        (["not", "a", "schema"], "$"),
        ({"type": "intger"}, "$.type"),
        ({"$schema": "https://example.invalid/draft", "type": "object"}, "$.$schema"),
        ({"$ref": "#/$defs/missing"}, "$.$ref"),
        ({"$ref": "https://schemas.example/external"}, "$.$ref"),
        (
            {"type": "object", "properties": {"result": {"$ref": "#/$defs/missing"}}},
            "$.properties.result.$ref",
        ),
        ({"allOf": [{"$ref": "https://schemas.example/external"}]}, "$.allOf[0].$ref"),
    ],
)
def test_literal_invalid_schemas_emit_llm_configuration_diagnostic(output_schema, schema_path):
    errors = _schema_errors(output_schema)

    assert len(errors) == 1
    diagnostic = errors[0]
    assert diagnostic.title == "LLM Configuration"
    assert diagnostic.source == "validator"
    assert diagnostic.node_id == "ask"
    assert diagnostic.context["path"] == "nodes[id=ask].params.output_schema"
    assert diagnostic.context.get("schema_path") == schema_path
    assert diagnostic.see_also == ["llm"]
