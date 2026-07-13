"""Shared parameter sets and predicates for ``agent`` node validation.

These helpers are shared between the runtime path
(``AgentNode._validate_schema``) and the static preflight path
(``WorkflowValidator._validate_agent_params``). Sharing the predicates
prevents drift between ``--validate-only`` / ``--dry-run`` and runtime
``prep()``.

Error message *framing* (``ValueError`` vs ``Diagnostic``, wrapper-example
text, suggestion lists) intentionally stays at the call site so each caller
can shape the surface appropriately. Issue #398 may consolidate further once
LLM-side validation is added.
"""

from __future__ import annotations

from typing import Any, Final, Literal, NamedTuple

SHARED_PARAMS: Final[frozenset[str]] = frozenset({
    "backend",
    "prompt",
    "inputs",
    "model",
    "cwd",
    "output_schema",
    "resume",
    "timeout",
    "system_prompt",
    "schema_retries",
})
"""Parameters whose shape is shared by every agent backend."""

CLAUDE_PARAMS: Final[frozenset[str]] = frozenset({
    "allowed_tools",
    "disallowed_tools",
    "max_turns",
    "max_thinking_tokens",
    "sandbox",
    "use_api_key",
})
"""Parameters accepted by the Claude backend."""

CODEX_PARAMS: Final[frozenset[str]] = frozenset({
    "approval_policy",
    "add_dir",
    "profile",
    "config",
    "sandbox",
})
"""Parameters accepted by the Codex backend."""

JSON_SCHEMA_MARKERS: Final[frozenset[str]] = frozenset({
    "type",
    "$ref",
    "$schema",
    "oneOf",
    "anyOf",
    "allOf",
    "enum",
    "const",
})
"""Keys that mark a dict as JSON Schema rather than the pre-Task-126 alias format."""

PYTHON_ALIAS_TYPES: Final[frozenset[str]] = frozenset({"str", "int", "bool", "list", "dict", "float"})
"""Python type names that flag the legacy alias format when used as ``type`` values."""

TOP_LEVEL_COMBINATORS: Final[tuple[str, ...]] = ("oneOf", "anyOf", "allOf", "enum", "const")
"""JSON Schema combinator keys that the Anthropic API rejects at the schema root."""


class TopLevelObjectViolation(NamedTuple):
    """Reason a schema fails an agent backend's top-level-object requirement.

    ``kind`` lets callers choose message framing without re-parsing ``cause``.
    """

    cause: str
    kind: Literal["non_object_type", "missing_type"]


def is_legacy_python_alias_schema(schema: dict[str, Any]) -> bool:
    """Return True if ``schema`` uses the pre-Task-126 Python-alias format.

    Heuristic: no JSON Schema marker at the top level AND at least one value
    is a dict whose ``type`` is a Python type name (``str``, ``int``, ...).
    This is the shape the old prompt-injection format used.
    """
    if any(marker in schema for marker in JSON_SCHEMA_MARKERS):
        return False
    return any(isinstance(value, dict) and value.get("type") in PYTHON_ALIAS_TYPES for value in schema.values())


def top_level_object_violation(schema: dict[str, Any]) -> TopLevelObjectViolation | None:
    """Return a violation when ``schema`` doesn't have top-level ``type: object``, else None.

    Both supported backends reject any top-level schema that isn't
    ``type: object``. This covers ``type: array``/primitives and schemas that
    omit ``type`` entirely (for example, a top-level ``oneOf``).
    """
    top_level_type = schema.get("type")
    if top_level_type == "object":
        return None
    if top_level_type is None:
        combinators = sorted(k for k in TOP_LEVEL_COMBINATORS if k in schema)
        cause = (
            f"top-level combinator {combinators[0]!r} with no top-level type" if combinators else "no top-level type"
        )
        return TopLevelObjectViolation(cause=cause, kind="missing_type")
    return TopLevelObjectViolation(cause=f"got type: {top_level_type!r}", kind="non_object_type")
