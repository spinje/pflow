"""Tests for the canonical workflow input/output type vocabulary."""

import pytest

from pflow.core.types import CANONICAL_TYPES, TypeSpec, TypeVocabularyError


class TestTypeSpecParse:
    def test_parse_legal_types(self) -> None:
        for type_name in CANONICAL_TYPES:
            parsed = TypeSpec.parse(type_name)
            assert parsed == TypeSpec(type_name)
            assert str(parsed) == type_name

    @pytest.mark.parametrize(
        ("raw", "canonical"),
        [
            ("str", "string"),
            ("int", "integer"),
            ("float", "number"),
            ("bool", "boolean"),
            ("list", "array"),
        ],
    )
    def test_parse_rejects_python_aliases(self, raw: str, canonical: str) -> None:
        with pytest.raises(TypeVocabularyError, match=f"Use '{canonical}' instead of '{raw}'"):
            TypeSpec.parse(raw)

    def test_parse_rejects_dict_with_wildcard_hint(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("dict")

        message = str(exc_info.value)
        assert "Use 'object' instead of 'dict'" in message
        assert "Use 'any'" in message

    def test_parse_rejects_parameterized_generics(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("list[str]")
        assert "Parameterized generics not supported" in str(exc_info.value)
        # suggestions_list entry must be self-contained — carries both the canonical
        # replacement AND the 'generics not supported' reason, so JSON/CLI consumers
        # get a full explanation in the single suggestion (not just the bare 'Use array').
        assert len(exc_info.value.suggestions_list) == 1
        assert "Use 'array'" in exc_info.value.suggestions_list[0]
        assert "parameterized generics not supported" in exc_info.value.suggestions_list[0].lower()

        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("dict[str, int]")
        assert "Parameterized generics not supported" in str(exc_info.value)
        assert "Use 'object'" in exc_info.value.suggestions_list[0]
        assert "parameterized generics not supported" in exc_info.value.suggestions_list[0].lower()

    def test_parse_rejects_null(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("null")
        assert "Use 'any'" in str(exc_info.value)
        assert "union syntax" in str(exc_info.value).lower()
        # Parity with alias errors: null rejection must carry a pasteable suggestion
        # in suggestions_list so JSON/MCP consumers get the same structured shape.
        assert exc_info.value.suggestions_list == ["Use 'any' if the value may be None"]

    def test_parse_rejects_unknown_with_fuzzy_suggestion(self) -> None:
        with pytest.raises(TypeVocabularyError, match="Did you mean 'string'"):
            TypeSpec.parse("strin")

    def test_parse_rejects_unknown_no_fuzzy_match(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("zzz")
        assert "Valid types:" in str(exc_info.value)
        assert "Did you mean" not in str(exc_info.value)

    def test_parse_rejects_uppercase(self) -> None:
        with pytest.raises(TypeVocabularyError):
            TypeSpec.parse("String")

    def test_parse_strips_whitespace(self) -> None:
        assert TypeSpec.parse("  object  ") == TypeSpec("object")


class TestTypeSpecAccepts:
    def test_string_accepts_str_only(self) -> None:
        spec = TypeSpec("string")
        assert spec.accepts("x") is True
        assert spec.accepts(1) is False
        assert spec.accepts({}) is False
        assert spec.accepts(None) is False

    def test_integer_accepts_int_rejects_bool(self) -> None:
        spec = TypeSpec("integer")
        assert spec.accepts(5) is True
        assert spec.accepts(5.5) is False
        assert spec.accepts(True) is False

    def test_number_accepts_int_and_float_rejects_bool(self) -> None:
        spec = TypeSpec("number")
        assert spec.accepts(5) is True
        assert spec.accepts(5.5) is True
        assert spec.accepts(True) is False

    def test_boolean_accepts_bool_only(self) -> None:
        spec = TypeSpec("boolean")
        assert spec.accepts(True) is True
        assert spec.accepts(1) is False

    def test_object_accepts_dict_only(self) -> None:
        spec = TypeSpec("object")
        assert spec.accepts({}) is True
        assert spec.accepts([]) is False
        assert spec.accepts("x") is False
        assert spec.accepts(1) is False

    def test_array_accepts_list_only(self) -> None:
        spec = TypeSpec("array")
        assert spec.accepts([]) is True
        assert spec.accepts({}) is False
        assert spec.accepts("x") is False

    def test_any_accepts_everything(self) -> None:
        spec = TypeSpec("any")
        for value in ({}, [], "x", 1, True, 1.5, None):
            assert spec.accepts(value) is True


class TestTypeSpecIsWildcard:
    def test_any_is_wildcard(self) -> None:
        assert TypeSpec("any").is_wildcard() is True

    def test_others_are_not_wildcard(self) -> None:
        for type_name in CANONICAL_TYPES:
            if type_name == "any":
                continue
            assert TypeSpec(type_name).is_wildcard() is False


class TestTypeSpecToJsonSchema:
    def test_simple_types(self) -> None:
        assert TypeSpec("string").to_json_schema() == {"type": "string"}

    def test_any_returns_empty_dict(self) -> None:
        assert TypeSpec("any").to_json_schema() == {}


class TestTypeSpecRoundtrip:
    def test_str_roundtrip(self) -> None:
        for type_name in CANONICAL_TYPES:
            assert str(TypeSpec.parse(type_name)) == type_name

    def test_equality_and_hash(self) -> None:
        left = TypeSpec.parse("object")
        right = TypeSpec.parse("object")
        assert left == right
        assert {left: "ok"}[right] == "ok"


class TestTypeVocabularyErrorFields:
    def test_structured_fields_on_alias_error(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("str")

        error = exc_info.value
        assert error.offending == "str"
        # Alias errors carry the canonical via suggestions_list (known-fix channel),
        # not similar_names (reserved for typo / "Did you mean" cases).
        assert error.similar_names == []
        assert error.available_fields == list(CANONICAL_TYPES)
        assert error.available_fields_label == "types"
        assert error.suggestions_list == ["Use 'string' instead of 'str'"]

    def test_structured_fields_on_dict_alias_includes_two_suggestions(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("dict")

        assert exc_info.value.suggestions_list == [
            "Use 'object' if the value is a dict: - type: object",
            "Use 'any' if the value can be any type: - type: any",
        ]

    def test_structured_fields_on_fuzzy_match(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("strin")
        assert exc_info.value.similar_names == ["string"]

    def test_structured_fields_on_unknown(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("foobar")
        assert exc_info.value.similar_names == []

    def test_case_sensitive_use_capital_u(self) -> None:
        with pytest.raises(TypeVocabularyError) as exc_info:
            TypeSpec.parse("str")
        assert "Use '" in str(exc_info.value)
