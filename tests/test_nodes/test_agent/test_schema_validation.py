"""Tests for the pure predicates in ``pflow.nodes.agent.schema_validation``.

These predicates are imported by both ``AgentNode._validate_schema``
(runtime) and ``WorkflowValidator._validate_agent_params`` (preflight).
Drift-at-the-predicate-level was the motivating risk for extracting them; the
tests below pin behavior at the predicate boundary so changes that alter
acceptance/rejection shape surface here, not via the call-site test files.
"""

from __future__ import annotations

from typing import Any

import pytest

from pflow.nodes.agent.schema_validation import (
    is_compiler_source_line_sidecar,
    is_legacy_python_alias_schema,
    top_level_object_violation,
    validate_use_api_key,
)


class TestCompilerSourceLineSidecar:
    def test_recognizes_metadata_only_when_the_fenced_parameter_exists(self) -> None:
        params = {"prompt": "hello", "_prompt_source_line": 12}

        assert is_compiler_source_line_sidecar("_prompt_source_line", params) is True

    @pytest.mark.parametrize(
        ("key", "params"),
        [
            ("_prompt_source_line", {"_prompt_source_line": 12}),
            ("prompt_source_line", {"prompt_source_line": 12}),
            ("_source_line", {"_source_line": 12}),
            ("_prompt_line", {"prompt": "hello", "_prompt_line": 12}),
        ],
    )
    def test_rejects_lookalikes_and_orphaned_metadata(self, key: str, params: dict[str, Any]) -> None:
        assert is_compiler_source_line_sidecar(key, params) is False


class TestValidateUseApiKey:
    @pytest.mark.parametrize("value", [None, False, 0, "false", "FALSE", " 0 ", "No"])
    def test_accepts_false_forms(self, value: Any) -> None:
        assert validate_use_api_key(value) is False

    @pytest.mark.parametrize("value", [True, 1, "true", "TRUE", " 1 ", "Yes"])
    def test_accepts_true_forms(self, value: Any) -> None:
        assert validate_use_api_key(value) is True

    @pytest.mark.parametrize(
        "value",
        ["", "maybe", "on", "off", 2, -1, 42, [], {}, {"enabled": True}, object()],
    )
    def test_rejects_ambiguous_values_with_backend_neutral_guidance(self, value: Any) -> None:
        with pytest.raises(TypeError, match="use_api_key must be true or false") as exc_info:
            validate_use_api_key(value)

        message = str(exc_info.value)
        assert "provider billing" in message
        assert "Claude" not in message
        assert "Anthropic" not in message
        assert "Codex" not in message
        assert "OpenAI" not in message

    def test_rejected_string_value_is_not_echoed(self) -> None:
        secret_like_value = "sk-secret-value-that-must-not-leak"  # noqa: S105 - redaction sentinel

        with pytest.raises(TypeError) as exc_info:
            validate_use_api_key(secret_like_value)

        assert secret_like_value not in str(exc_info.value)
        assert "got str" in str(exc_info.value)


class TestIsLegacyPythonAliasSchema:
    def test_legacy_flat_field_map_detected(self) -> None:
        schema = {"risk_level": {"type": "str", "description": "high/medium/low"}}
        assert is_legacy_python_alias_schema(schema) is True

    def test_legacy_detection_checks_all_values_not_just_first(self) -> None:
        # First value is non-dict (metadata-style marker); second is legacy shape.
        schema = {"_meta": "comment", "risk": {"type": "str", "description": "..."}}
        assert is_legacy_python_alias_schema(schema) is True

    def test_real_json_schema_with_top_level_type_not_legacy(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        assert is_legacy_python_alias_schema(schema) is False

    def test_real_json_schema_with_combinator_not_legacy(self) -> None:
        schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        assert is_legacy_python_alias_schema(schema) is False

    def test_real_json_schema_with_ref_not_legacy(self) -> None:
        # $ref counts as a JSON Schema marker even without a top-level `type`.
        schema = {"$ref": "#/definitions/Status"}
        assert is_legacy_python_alias_schema(schema) is False

    def test_empty_dict_not_legacy(self) -> None:
        assert is_legacy_python_alias_schema({}) is False

    def test_field_with_canonical_string_type_not_legacy(self) -> None:
        # "string" is the JSON Schema spelling, NOT the Python alias "str".
        # Without a top-level JSON Schema marker, the predicate's only signal
        # is whether values look Python-aliased. "string" doesn't.
        schema = {"my_field": {"type": "string"}}
        assert is_legacy_python_alias_schema(schema) is False


class TestTopLevelObjectViolation:
    def test_top_level_object_returns_none(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        assert top_level_object_violation(schema) is None

    def test_top_level_array_classified_as_non_object_type(self) -> None:
        violation = top_level_object_violation({"type": "array", "items": {"type": "string"}})
        assert violation is not None
        assert violation.kind == "non_object_type"
        assert "'array'" in violation.cause

    def test_top_level_string_classified_as_non_object_type(self) -> None:
        violation = top_level_object_violation({"type": "string", "enum": ["yes", "no"]})
        assert violation is not None
        assert violation.kind == "non_object_type"
        assert "'string'" in violation.cause

    def test_top_level_oneOf_classified_as_missing_type(self) -> None:
        violation = top_level_object_violation({"oneOf": [{"type": "object"}, {"type": "object"}]})
        assert violation is not None
        assert violation.kind == "missing_type"
        assert "oneOf" in violation.cause

    def test_top_level_anyOf_named_in_cause(self) -> None:
        violation = top_level_object_violation({"anyOf": [{"type": "object"}]})
        assert violation is not None
        assert violation.kind == "missing_type"
        assert "anyOf" in violation.cause

    def test_top_level_allOf_named_in_cause(self) -> None:
        violation = top_level_object_violation({"allOf": [{"type": "object"}]})
        assert violation is not None
        assert violation.kind == "missing_type"
        assert "allOf" in violation.cause

    def test_top_level_enum_named_in_cause(self) -> None:
        violation = top_level_object_violation({"enum": ["yes", "no"]})
        assert violation is not None
        assert violation.kind == "missing_type"
        assert "enum" in violation.cause

    def test_no_type_no_combinator(self) -> None:
        violation = top_level_object_violation({"properties": {"x": {"type": "string"}}})
        assert violation is not None
        assert violation.kind == "missing_type"
        assert violation.cause == "no top-level type"

    def test_top_level_const_named_in_cause(self) -> None:
        # Behavioral symmetry with oneOf/anyOf/allOf/enum. ``const`` is in the
        # combinator set; removing it would silently degrade UX (cause string
        # falls back to "no top-level type" instead of naming "const").
        violation = top_level_object_violation({"const": {"x": 1}})
        assert violation is not None
        assert violation.kind == "missing_type"
        assert "const" in violation.cause

    def test_combinator_inside_object_wrapper_accepted(self) -> None:
        # The supported workaround: wrap combinator in an object root.
        schema = {
            "type": "object",
            "properties": {"choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
        }
        assert top_level_object_violation(schema) is None
