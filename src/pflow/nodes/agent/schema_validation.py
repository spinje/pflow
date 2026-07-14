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
    "use_api_key",
})
"""Parameters whose shape is shared by every agent backend."""

CLAUDE_PARAMS: Final[frozenset[str]] = frozenset({
    "allowed_tools",
    "disallowed_tools",
    "max_turns",
    "max_thinking_tokens",
    "sandbox",
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

CODEX_SANDBOX_MODES: Final[tuple[str, ...]] = ("read-only", "workspace-write", "full-access")
"""User-facing Codex sandbox modes (mapped to CLI ``-s`` flags in ``codex_backend``)."""

CODEX_APPROVAL_POLICIES: Final[frozenset[str]] = frozenset({"untrusted", "on-request", "never"})
"""Accepted values for the codex-only ``approval_policy`` parameter."""

_SOURCE_LINE_SUFFIX: Final[str] = "_source_line"


def validate_schema_retries(value: Any) -> int:
    """Resolve the shared ``schema_retries`` count (default 1; range 0-5).

    Shared by ``AgentNode.prep`` and the static validator so ``--validate-only``
    rejects an out-of-range value the same way runtime ``prep`` does. Raises
    ``ValueError`` on a non-integer or out-of-range value.
    """
    if value is None:
        return 1
    try:
        retries = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid schema_retries: {value!r}. Must be an integer between 0 and 5.") from None
    if retries < 0:
        raise ValueError(f"schema_retries cannot be negative (got {retries}).")
    if retries > 5:
        raise ValueError(f"schema_retries cannot exceed 5 (cap to prevent runaway costs; got {retries}).")
    return retries


def validate_claude_sandbox(sandbox: Any) -> dict | None:
    """Validate the Claude ``sandbox`` config dict shape (empty/falsy → ``None``).

    Claude's sandbox is an SDK ``SandboxSettings`` dict — NOT a codex string
    mode. Known keys are type-checked; unknown keys pass through for SDK
    forward-compatibility. Raises ``TypeError`` on a wrong-shaped value.
    """
    if not sandbox:
        return None
    if not isinstance(sandbox, dict):
        raise TypeError(f"sandbox must be a dict, got {type(sandbox).__name__}")
    bool_fields = ("enabled", "autoAllowBashIfSandboxed", "allowUnsandboxedCommands", "enableWeakerNestedSandbox")
    for field in bool_fields:
        if field in sandbox and not isinstance(sandbox[field], bool):
            raise TypeError(f"sandbox['{field}'] must be bool")
    for field in ("network", "ignoreViolations"):
        if field in sandbox and not isinstance(sandbox[field], dict):
            raise TypeError(f"sandbox['{field}'] must be a dict")
    if "excludedCommands" in sandbox and not isinstance(sandbox["excludedCommands"], list):
        raise TypeError("sandbox['excludedCommands'] must be a list")
    return sandbox


def validate_claude_max_turns(max_turns: Any) -> int:
    """Validate the Claude ``max_turns`` (default 50; range 1-100)."""
    if max_turns is None:
        return 50
    try:
        turns = int(max_turns)
        if turns < 1 or turns > 100:
            raise ValueError
        return turns
    except (ValueError, TypeError):
        raise ValueError(f"Invalid max_turns: {max_turns}. Must be integer between 1 and 100.") from None


def validate_claude_max_thinking_tokens(max_thinking_tokens: Any) -> int:
    """Validate the Claude ``max_thinking_tokens`` (default 8000; range 1000-100000)."""
    if max_thinking_tokens is None:
        return 8000
    try:
        tokens = int(max_thinking_tokens)
        if tokens < 1000 or tokens > 100000:
            raise ValueError
        return tokens
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid max_thinking_tokens: {max_thinking_tokens}. Must be integer between 1000 and 100000."
        ) from None


def validate_claude_tool_list(value: Any, param_name: str) -> list | None:
    """Validate a Claude tool-list parameter (empty/falsy → ``None``; non-list raises)."""
    if not value:
        return None
    if not isinstance(value, list):
        raise TypeError(f"{param_name} must be a list, got {type(value).__name__}")
    return value


def validate_codex_sandbox(value: Any) -> str:
    """Validate the Codex ``sandbox`` string mode (default ``workspace-write``)."""
    if value is None:
        return "workspace-write"
    if not isinstance(value, str) or value not in CODEX_SANDBOX_MODES:
        choices = ", ".join(CODEX_SANDBOX_MODES)
        raise ValueError(f"sandbox must be one of: {choices}; got {value!r}")
    return value


def validate_codex_approval_policy(value: Any) -> str | None:
    """Validate the codex-only ``approval_policy`` enum (optional)."""
    if value is not None and (not isinstance(value, str) or value not in CODEX_APPROVAL_POLICIES):
        choices = ", ".join(sorted(CODEX_APPROVAL_POLICIES))
        raise ValueError(f"approval_policy must be one of: {choices}; got {value!r}")
    return value


def validate_codex_add_dirs(value: Any) -> list[str]:
    """Validate the codex-only ``add_dir`` list of non-empty directory strings."""
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(path, str) or not path.strip() for path in value):
        raise TypeError("add_dir must be a list of non-empty directory strings")
    return value.copy()


def validate_codex_profile(value: Any) -> str | None:
    """Validate the codex-only ``profile`` (optional non-empty string)."""
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise TypeError("profile must be a non-empty string")
    return value


class TopLevelObjectViolation(NamedTuple):
    """Reason a schema fails an agent backend's top-level-object requirement.

    ``kind`` lets callers choose message framing without re-parsing ``cause``.
    """

    cause: str
    kind: Literal["non_object_type", "missing_type"]


def is_compiler_source_line_sidecar(key: str, params: dict[str, Any]) -> bool:
    """Return whether ``key`` is compiler metadata for a real fenced parameter.

    The markdown parser records fenced-block line numbers under ``_source_lines``;
    compilation flattens those entries into ``_<param>_source_line`` parameters so
    template errors can point back to the authored block. They are not user-facing
    AgentNode parameters and must not participate in backend allowlist validation.

    Requiring the base parameter to exist keeps the filter precise: a genuine user
    parameter that merely ends in ``_source_line`` is still rejected normally.
    """
    if not (key.startswith("_") and key.endswith(_SOURCE_LINE_SUFFIX)):
        return False
    base = key[1 : -len(_SOURCE_LINE_SUFFIX)]
    return bool(base) and base in params


def validate_use_api_key(value: Any) -> bool:
    """Resolve the shared API-key/provider billing permission to a strict bool.

    Runtime template values may arrive as strings, so Python truthiness is not
    safe here: ``"false"`` must remain false. Accept only the canonical forms
    supported by the pre-existing Claude contract and fail closed otherwise.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no"):
            return False
    raise TypeError(
        f"use_api_key must be true or false, got {type(value).__name__}. Set it to true only when "
        "you intend to permit API-key or configured-provider billing; otherwise omit "
        "it or set it to false."
    )


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
