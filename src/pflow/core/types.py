"""Canonical workflow input/output type vocabulary for authored workflows.

This module defines the Surface 1 (S1) type system for workflow-authored
``## Inputs`` / ``## Outputs`` declarations. It intentionally differs from the
Python annotation vocabulary used inside code blocks and node Interface
docstrings.

The Claude Code node's ``output_schema`` is a deliberate fourth surface that
continues to use Python-aliased names (``str``, ``int``, ``bool``, ``list``,
``dict``). Those names are embedded literally into LLM prompt construction by
``nodes/claude/claude_code.py::_build_schema_prompt`` — migrating them would
change the LLM's instruction wording. Not in scope for the S1 vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, NoReturn

from pflow.core.suggestion_utils import find_similar_items

CANONICAL_TYPES: Final[tuple[str, ...]] = (
    "string",
    "number",
    "integer",
    "boolean",
    "array",
    "object",
    "any",
)

PYTHON_ALIASES_AT_S1: Final[dict[str, str]] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


@dataclass
class TypeVocabularyError(ValueError):
    """Raised when an authored workflow uses an invalid S1 type name."""

    message: str
    offending: str
    similar_names: list[str] = field(default_factory=list)
    available_fields: list[str] = field(default_factory=lambda: list(CANONICAL_TYPES))
    available_fields_label: str = "types"
    suggestions_list: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class TypeSpec:
    """Canonical representation of a workflow-authored S1 type.

    ``accepts()`` follows strict JSON-Schema-style semantics for future callers:
    ``integer`` rejects ``True`` even though Python treats ``bool`` as an
    ``int`` subclass. This intentionally differs from the Python-side code-node
    annotation semantics.
    """

    name: str

    def __post_init__(self) -> None:
        if self.name not in CANONICAL_TYPES:
            raise ValueError(f"TypeSpec.name must be in {CANONICAL_TYPES}, got {self.name!r}")

    @classmethod
    def parse(cls, raw: str) -> TypeSpec:
        """Parse an authored workflow type string into a canonical TypeSpec."""
        if not isinstance(raw, str):
            raise TypeVocabularyError("Type must be a non-empty string", offending=repr(raw))

        stripped = raw.strip()
        if not stripped:
            raise TypeVocabularyError("Type must be a non-empty string", offending=raw)

        if "[" in stripped:
            _raise_parameterized_generic_error(raw, stripped)

        if any(char.isspace() for char in stripped):
            raise TypeVocabularyError(
                "Whitespace not allowed inside type names.",
                offending=raw,
            )

        if stripped in CANONICAL_TYPES:
            return cls(stripped)

        if stripped in PYTHON_ALIASES_AT_S1:
            _raise_alias_error(raw, stripped)

        if stripped == "null":
            raise TypeVocabularyError(
                "Use 'any' if the value may be None — it accepts null alongside other values. "
                "(Nullable-only types require union syntax, which pflow does not yet support.)",
                offending=raw,
                suggestions_list=["Use 'any' if the value may be None"],
            )

        _raise_unknown_type_error(raw, stripped)

    def accepts(self, value: Any) -> bool:
        """Return whether a Python value satisfies this type."""
        if self.name == "any":
            return True
        if self.name == "string":
            return isinstance(value, str)
        if self.name == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if self.name == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if self.name == "boolean":
            return isinstance(value, bool)
        if self.name == "array":
            return isinstance(value, list)
        if self.name == "object":
            return isinstance(value, dict)
        return False

    def is_wildcard(self) -> bool:
        """Return True only for the explicit wildcard type."""
        return self.name == "any"

    def to_json_schema(self) -> dict[str, str]:
        """Return a minimal JSON Schema representation for this type."""
        if self.name == "any":
            return {}
        return {"type": self.name}

    def __str__(self) -> str:
        return self.name


def _raise_parameterized_generic_error(raw: str, stripped: str) -> NoReturn:
    """Raise the canonical error for unsupported parameterized generics."""
    base = stripped.split("[", 1)[0].strip()
    if base in PYTHON_ALIASES_AT_S1:
        canonical = PYTHON_ALIASES_AT_S1[base]
        suggestion = (
            f"Use '{canonical}' — parameterized generics not supported at `## Inputs` / `## Outputs` (got {raw!r})"
        )
    elif base in CANONICAL_TYPES:
        suggestion = f"Use '{base}' — parameterized generics not supported at `## Inputs` / `## Outputs` (got {raw!r})"
    else:
        suggestion = (
            f"Use the base type — parameterized generics not supported at `## Inputs` / `## Outputs` (got {raw!r})"
        )

    raise TypeVocabularyError(
        f"Parameterized generics not supported in `## Inputs` / `## Outputs`. Got: {raw!r}. {suggestion}.",
        offending=raw,
        suggestions_list=[suggestion],
    )


def _raise_alias_error(raw: str, stripped: str) -> NoReturn:
    """Raise the canonical error for deprecated Python aliases at S1.

    Alias errors carry the canonical replacement via ``suggestions_list`` — the
    "known fix" channel. ``similar_names`` is reserved for genuinely uncertain
    typo cases (fuzzy match on unknown names) where "Did you mean" framing fits.
    """
    canonical = PYTHON_ALIASES_AT_S1[stripped]
    if stripped == "dict":
        raise TypeVocabularyError(
            "Use 'object' instead of 'dict'. Use 'any' if the value can be any type.",
            offending=raw,
            suggestions_list=[
                "Use 'object' if the value is a dict: - type: object",
                "Use 'any' if the value can be any type: - type: any",
            ],
        )

    suggestion = f"Use '{canonical}' instead of '{stripped}'"
    raise TypeVocabularyError(
        suggestion,
        offending=raw,
        suggestions_list=[suggestion],
    )


def _raise_unknown_type_error(raw: str, stripped: str) -> NoReturn:
    """Raise the canonical error for unknown S1 types."""
    similar_names = find_similar_items(
        stripped,
        list(CANONICAL_TYPES),
        method="fuzzy",
        cutoff=0.6,
        max_results=1,
    )
    if similar_names:
        closest = similar_names[0]
        raise TypeVocabularyError(
            f"Unknown type '{stripped}'. Did you mean '{closest}'? Valid types: {', '.join(CANONICAL_TYPES)}",
            offending=raw,
            similar_names=similar_names,
        )

    raise TypeVocabularyError(
        f"Unknown type '{stripped}'. Valid types: {', '.join(CANONICAL_TYPES)}",
        offending=raw,
    )
