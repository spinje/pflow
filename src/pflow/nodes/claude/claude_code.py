"""Claude Code Agentic Node - AI-powered development assistant with structured outputs.

This node integrates with Claude Code Python SDK to execute comprehensive development tasks.
When users provide a JSON Schema output_schema, pflow passes it to the SDK's native
structured-output mode and stores the parsed structured_output from the final result.

Interface:
- Params: prompt: str  # The prompt to send to Claude (required)
- Params: output_schema: dict  # JSON Schema for structured outputs (optional)
- Writes: shared["result"]: str|dict  # Free-form text (str), or parsed JSON (dict/list/primitive) when output_schema is set, or raw text on soft schema failure
- Writes: shared["_schema_error"]: str  # Soft-failure message for structured-output mode: set when structured output was unavailable, the SDK reported an error alongside the output, or the schema reference resolved to None (optional)
- Writes: shared["llm_usage"]: dict  # Token usage and execution metadata (empty dict {} if unavailable)
    - model: str  # Model identifier used
    - input_tokens: int  # Total input tokens, including cached prefix
    - uncached_input_tokens: int  # Input tokens not served from cache
    - output_tokens: int  # Output tokens generated
    - total_tokens: int  # Total tokens (input + output); input includes cache
    - cache_creation_input_tokens: int  # Tokens used for cache creation
    - cache_read_input_tokens: int  # Tokens read from cache
    - input_token_accounting: str  # How input_tokens was derived (always "split_cache_fields" for claude-code)
    - cost_usd: float  # Cost in USD from Claude Code SDK
    - duration_ms: int  # Execution time in milliseconds
    - num_turns: int  # Number of conversation turns
    - session_id: str  # Session ID for resuming conversations
    - retries: list  # Schema retry attempts (optional, present only when schema_retries > 0 and retries occurred). Each entry has same structure as main llm_usage.
- Params: cwd: str  # Working directory for Claude (default: os.getcwd())
- Params: model: str  # Claude model identifier (default: claude-sonnet-4-5)
- Params: allowed_tools: list  # Permitted tools (default: None = all tools including Task for subagents)
- Params: disallowed_tools: list  # Tools to deny (default: None = no restrictions). Supports patterns like "Bash(git:*)"
- Params: max_turns: int  # Maximum conversation turns (default: 50)
- Params: max_thinking_tokens: int  # Maximum tokens for reasoning (default: 8000)
- Params: timeout: int  # Execution timeout in seconds (default: 300; max: 3600)
- Params: system_prompt: str  # System instructions for Claude (optional)
- Params: resume: str  # Session ID to resume a previous conversation (optional)
- Params: schema_retries: int  # Number of retry attempts for schema mismatches (default: 1; max: 5; 0 disables both coercion and retry). When the output doesn't match the schema, the node attempts scalar coercion first (e.g., "false" → False for boolean fields), then retries by resuming the session with a corrective prompt.
- Params: sandbox: dict  # Sandbox configuration for command isolation (optional)
    - enabled: bool  # Enable sandbox mode (default: false)
    - autoAllowBashIfSandboxed: bool  # Auto-allow bash when sandboxed (default: false)
    - excludedCommands: list  # Commands that bypass sandbox (e.g., ["docker"])
    - allowUnsandboxedCommands: bool  # Allow model to request unsandboxed execution
    - network: dict  # Network settings (allowLocalBinding, allowUnixSockets, etc.)
- Params: use_api_key: bool  # Bill to ANTHROPIC_API_KEY (Anthropic Console) when true. Default false uses your Claude Pro/Max subscription.

Note: When output_schema is provided, the result is the SDK's parsed structured_output.
Access object values as shared["result"]["key"] in templates: ${node.result.key}
Soft schema failures also write a root-level `shared["__warnings__"][node_id]`
entry so workflow status becomes DEGRADED.
Session ID is available at ${node.llm_usage.session_id} for chaining sessions.
"""

import asyncio
import json
import logging
import os
from collections.abc import Mapping
from typing import Any

from pflow.core.node import Node
from pflow.nodes.claude.schema_validation import (
    TopLevelObjectViolation,
    is_legacy_python_alias_schema,
    top_level_object_violation,
)

# Import Claude Agent SDK (renamed from Claude Code SDK)
try:
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

    # Try to import exceptions, but make them optional for test environments
    try:
        from claude_agent_sdk import (
            ClaudeSDKError,
            CLIConnectionError,
            CLINotFoundError,
            ProcessError,
        )
    except ImportError:
        # In test environments, these might not be available
        CLINotFoundError = None
        CLIConnectionError = None
        ProcessError = None
        ClaudeSDKError = None
except ImportError as e:
    raise ImportError("Claude Agent SDK is not installed. Install with: pip install claude-agent-sdk") from e

# Guard against SDK field renames that would silently break structured output.
# If claude_agent_sdk renames `structured_output`, every schema call would
# otherwise soft-fail with a misleading "model didn't comply" message.
# The ``isinstance(..., dict)`` check upgrades a forgotten test mock
# (auto-``Mock`` with synthetic ``__annotations__``) from an opaque
# ``TypeError`` on ``in`` to this friendly ``ImportError``.
_resolved_annotations = getattr(ResultMessage, "__annotations__", {})
if not isinstance(_resolved_annotations, dict) or "structured_output" not in _resolved_annotations:
    raise ImportError(
        "claude_agent_sdk.types.ResultMessage has no 'structured_output' field. "
        "pflow's Claude Code node requires claude-agent-sdk>=0.2.82 with native "
        "structured output support. Got an incompatible SDK version."
    )

logger = logging.getLogger(__name__)

# Security patterns for bash command validation
DANGEROUS_BASH_PATTERNS = [
    r"rm\s+-rf\s+/",  # Recursive root deletion
    r"rm\s+-rf\s+~",  # Home directory deletion
    r":\(\)\{\s*:\|\s*:\s*&\s*\};",  # Fork bomb
    r">\s*/dev/sd",  # Disk overwrite
    r"chmod\s+777\s+/",  # Overly permissive root
    r"curl.*\|.*sh",  # Remote code execution
    r"wget.*\|.*bash",  # Remote code execution
]

# Restricted directories that should not be used as working directories
RESTRICTED_DIRECTORIES = ["/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/sys", "/proc"]

# Substrings (lowercased) that mark a Claude CLI authentication/billing failure.
# The common auth failure surfaces as a bare Exception whose message carries the
# CLI's error text, so exec_fallback matches on the message to attach
# subscription-vs-API-key remediation (issue #455). A multi-marker OR keeps this
# robust to CLI wording drift; bare numeric codes (401/403) are intentionally
# excluded to avoid false positives on unrelated numbers.
_AUTH_ERROR_MARKERS = (
    "invalid api key",
    "authentication_error",
    "authentication error",
    # "run /login" matches the real not-logged-in result ("Not logged in · Please
    # run /login") without the broad bare "/login" substring, which could match an
    # unrelated /login path mentioned in agent output.
    "run /login",
    "unauthorized",
    "credit balance",
    # Structured HTTP status surfaced by _run_claude_session from the
    # ResultMessage (the SDK drops it from its own exception text). Specific
    # `key=value` form, so no false positives on stray numbers.
    "api_error_status=401",
    "api_error_status=403",
)


def _claude_token_fields(usage: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize Claude SDK usage to pflow's inclusive token contract.

    The Claude SDK reports Anthropic's disjoint model — ``input_tokens`` is the
    UNCACHED count, with ``cache_creation_input_tokens`` / ``cache_read_input_tokens``
    as separate addends. pflow's contract (see ``core/llm_usage.py``) treats
    ``input_tokens`` as the cache-INCLUSIVE total, matching LLMNode. Claude's split is
    always known, so the total is a deterministic sum (no value-based heuristic).
    """
    base_input = usage.get("input_tokens", 0) or 0
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    return {
        "input_tokens": base_input + cache_creation + cache_read,
        "uncached_input_tokens": base_input,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "input_token_accounting": "split_cache_fields",
    }


class ClaudeCodeNode(Node):
    """Claude Code agentic super node for AI-assisted development tasks.

    This node integrates with Claude Code Python SDK to execute comprehensive development tasks.
    When users provide an output_schema, pflow passes the JSON Schema to the SDK's native
    structured-output mode and stores the parsed structured_output.

    Output Schema Format:
        JSON Schema for structured outputs (optional):
        {"type": "object", "properties": {"field": {"type": "string"}}, "required": ["field"]}

        Top-level type must be "object" because the Claude API rejects non-object
        schemas when the SDK wraps output_format as a tool input_schema.

    Interface:
    - Params: prompt: str  # The prompt to send to Claude (required)
    - Params: output_schema: dict  # JSON Schema for structured outputs (optional)
    - Writes: shared["result"]: str|dict  # Free-form text, parsed JSON when output_schema succeeds, or raw text on soft schema failure
    - Writes: shared["_schema_error"]: str  # Soft-failure message for structured-output mode: set when structured output was unavailable, the SDK reported an error alongside the output, or the schema reference resolved to None (optional)
    - Writes: shared["llm_usage"]: dict  # Token usage and execution metadata (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Total input tokens, including cached prefix
        - uncached_input_tokens: int  # Input tokens not served from cache
        - output_tokens: int  # Output tokens generated
        - total_tokens: int  # Total tokens (input + output); input includes cache
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
        - input_token_accounting: str  # How input_tokens was derived (always "split_cache_fields" for claude-code)
        - cost_usd: float  # Cost in USD from Claude Code SDK
        - duration_ms: int  # Execution time in milliseconds
        - num_turns: int  # Number of conversation turns
        - session_id: str  # Session ID for resuming conversations
    - Params: cwd: str  # Working directory for Claude (default: os.getcwd())
    - Params: model: str  # Claude model identifier (default: claude-sonnet-4-5)
    - Params: allowed_tools: list  # Permitted tools (default: None = all tools including Task for subagents)
    - Params: disallowed_tools: list  # Tools to deny (default: None = no restrictions)
    - Params: max_turns: int  # Maximum conversation turns (default: 50)
    - Params: max_thinking_tokens: int  # Maximum tokens for reasoning (default: 8000)
    - Params: timeout: int  # Execution timeout in seconds (default: 300; valid: 30-3600)
    - Params: system_prompt: str  # System instructions for Claude (optional)
    - Params: resume: str  # Session ID to resume a previous conversation (optional)
    - Params: schema_retries: int  # Number of retry attempts for schema mismatches (default: 1; range: 0-5). When the output doesn't match the schema, the node attempts scalar coercion first, then retries by resuming the session. Set to 0 to disable both mechanisms.
    - Params: sandbox: dict  # Sandbox configuration for command isolation (optional)
        - enabled: bool  # Enable sandbox mode (default: false)
        - autoAllowBashIfSandboxed: bool  # Auto-allow bash when sandboxed (default: false)
        - excludedCommands: list  # Commands that bypass sandbox (e.g., ["docker"])
        - allowUnsandboxedCommands: bool  # Allow model to request unsandboxed execution
        - network: dict  # Network settings (allowLocalBinding, allowUnixSockets, etc.)
    - Params: use_api_key: bool  # Bill to ANTHROPIC_API_KEY (Anthropic Console) when true. Default false uses your Claude Pro/Max subscription.

    Authentication:
        By default this node uses your Claude Pro/Max subscription and blanks
        ANTHROPIC_API_KEY for the Claude subprocess, so an ambient key (including
        one stored via `pflow settings set-env`) never silently bills your
        Anthropic Console. os.environ is left untouched, so a sibling llm node
        still reads the key for LiteLLM.

        1. Subscription (default — no per-token charges):
           claude auth login      # Interactive OAuth
           claude setup-token     # Long-lived token for non-interactive/CI

        2. API key (opt in — bills your Anthropic Console per token):
           Set `- use_api_key: true` on the node, with ANTHROPIC_API_KEY in the
           environment (or via `pflow settings set-env ANTHROPIC_API_KEY ...`).

        The SDK automatically runs in headless mode using --output-format json
        and bypasses all permission prompts since workflows run autonomously.

    Note: Result type depends on schema usage:
    - Without schema: String response in ${node_id.result}
    - With schema (success): Dict with fields accessible via ${node_id.result.field_name}
    - With schema (soft failure): Falls back to string in ${node_id.result}, with _schema_error and __warnings__
      at the root warning channel so the workflow status becomes DEGRADED.

    Routing: post() always returns "default". Schema soft-failures DO NOT route through
    `- on-error:` edges — wire schema-validation recovery via inspection of
    ${node._schema_error} or workflow DEGRADED status, not the error edge.

    Example:
        # Basic execution
        shared = {"prompt": "Write a fibonacci function"}
        node = ClaudeCodeNode()
        node.run(shared)  # Result in shared["result"] as string

        # With schema-driven output
        shared = {
            "prompt": "Review this code for security issues",
            "output_schema": {
                "type": "object",
                "properties": {
                    "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "needs_fix": {"type": "boolean"},
                },
                "required": ["risk_level", "issues", "score", "needs_fix"],
            }
        }
        node = ClaudeCodeNode()
        node.run(shared)
        # Success: shared["result"] = {"risk_level": "low", "issues": [...], "score": 8, "needs_fix": False}
        # Access as: shared["result"]["risk_level"], shared["result"]["issues"], etc.
        # Soft schema failure: shared["result"] = raw_text_string, shared["_schema_error"] = error
    """

    def __init__(self) -> None:
        """Initialize with conservative retry settings for expensive API calls."""
        # Only 2 attempts total (1 initial + 1 retry) due to API cost
        super().__init__(max_retries=2, wait=1.0)

    def _validate_prompt(self, prompt: Any) -> str:
        """Validate prompt parameter."""
        if not prompt:
            raise ValueError(
                "Claude Code node requires a 'prompt' parameter. "
                "Use template syntax like '- prompt: ${previous_node.output}' "
                "to wire data from other nodes."
            )
        if not isinstance(prompt, str):
            raise TypeError(f"Prompt must be a string, got {type(prompt).__name__}")
        if len(prompt) > 10000:
            raise ValueError(f"Prompt too long ({len(prompt)} chars). Maximum 10000 characters allowed.")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty or whitespace only.")
        return prompt

    def _validate_schema(self, output_schema: Any) -> dict | None:
        """Validate output_schema parameter.

        - None: no schema requested (returns None)
        - {} (empty): likely a typo; raises with guidance
        - Non-dict: TypeError
        - Legacy Python-alias format: raises with migration guidance
        - Missing or non-"object" top-level type: raises (Anthropic API tool-use limitation)
        - Otherwise: returns as-is; SDK/CLI enforces remaining JSON Schema validity

        The top-level-type check covers both `type: array`/primitives AND schemas
        that omit `type` entirely (top-level oneOf/anyOf/allOf/enum). All four
        return HTTP 400 from the Anthropic API when wrapped as a tool's
        input_schema, verified by Phase 0 (`type: array`/primitives) and the
        oneOf follow-up probe.

        Note on schema typos (e.g. type: "intger"): the Anthropic API silently accepts
        them. Schema typos will result in a soft-fail at runtime (structured_output is
        None) until centralized JSON Schema validation lands in issue #398.
        """
        if output_schema is None:
            return None
        if not isinstance(output_schema, dict):
            raise TypeError(f"output_schema must be a dict (JSON Schema), got {type(output_schema).__name__}")
        if not output_schema:
            raise ValueError(
                "output_schema is an empty dict. Did you forget to populate the schema body? "
                'Use a real JSON Schema (e.g. {"type": "object", "properties": {...}}) '
                "or remove the output_schema field entirely."
            )
        if is_legacy_python_alias_schema(output_schema):
            raise ValueError(
                "output_schema appears to use the legacy Python-alias format "
                '({"field": {"type": "str", ...}}). '
                'Use JSON Schema instead: {"type": "object", "properties": {...}, "required": [...]}. '
                "See docs/reference/nodes/claude-code.mdx for an example."
            )
        # Claude API limitation (verified in Phase 0 + oneOf follow-up): the SDK wraps
        # output_format as a tool's input_schema, and the API rejects any top-level
        # schema that isn't `type: object` with a 400. The shared predicate covers
        # non-"object" types AND combinator-only schemas (oneOf/anyOf/allOf/enum
        # without a top-level type).
        violation = top_level_object_violation(output_schema)
        if violation is not None:
            raise ValueError(self._top_level_object_error(violation))
        return output_schema

    @staticmethod
    def _top_level_object_error(violation: TopLevelObjectViolation) -> str:
        """Format the "top-level type: object" error with case-specific guidance."""
        wrapper_example = (
            'Wrap in an object, e.g. {"type": "object", '
            '"properties": {"result": <your schema>}, "required": ["result"]}. '
            "(The LLM node has no such restriction.)"
        )
        if violation.kind == "missing_type":
            return (
                "output_schema on claude-code nodes must declare top-level type: object "
                f"({violation.cause}). The Anthropic API rejects schemas without a top-level "
                "type:object when the SDK wraps output_format as a tool input_schema — "
                "combinators like oneOf/anyOf/allOf/enum must live inside an object "
                f"wrapper. {wrapper_example}"
            )
        return (
            "output_schema on claude-code nodes must have top-level type: object "
            f"({violation.cause}). "
            "The Anthropic API rejects non-object top-level schemas in tool input_schema "
            f"wrappers. {wrapper_example}"
        )

    def _emit_schema_resolved_null_warning(self, shared: dict[str, Any]) -> None:
        """Warn when ``output_schema`` was declared but resolved to ``None``.

        Same channel as soft-fail warnings — ``shared["__warnings__"][node_id]``
        triggers DEGRADED workflow status. Falls back to ``shared["_schema_error"]``
        when no ``node_id`` is bound (test paths, uncompiled nodes) so the signal
        is never fully lost.
        """
        node_id = getattr(self, "node_id", None)
        msg = (
            "output_schema was declared but resolved to None — Claude Code is running "
            "in free-form mode. If the schema came from an upstream node "
            "(e.g. `output_schema: ${node.schema}`), verify that node produced a "
            "JSON Schema dict. Remove `output_schema:` entirely to silence this warning."
        )
        if node_id is not None:
            shared.setdefault("__warnings__", {})[node_id] = {
                "kind": "claude_code.output_schema_resolved_to_null",
                "text": msg,
                "context": {"node_type": "claude-code"},
            }
        else:
            shared.setdefault("_schema_error", msg)

    def _validate_cwd(self, cwd: str | None) -> str:
        """Validate and normalize working directory."""
        if not cwd:
            return os.getcwd()

        cwd = os.path.expanduser(cwd)
        cwd = os.path.abspath(cwd)

        if not os.path.exists(cwd):
            raise ValueError(f"Working directory does not exist: {cwd}")
        if not os.path.isdir(cwd):
            raise ValueError(f"Working directory is not a directory: {cwd}")

        # Check for restricted directories
        normalized_path = os.path.normpath(cwd)
        if normalized_path in RESTRICTED_DIRECTORIES:
            raise ValueError(f"Restricted directory: {cwd}")
        return cwd

    def _validate_optional_tool_list(self, value: list | None, param_name: str) -> list | None:
        """Validate a tool-list parameter.

        Empty / falsy → ``None`` (SDK default applies — meaning differs by
        caller: ``allowed_tools=None`` opens all tools, ``disallowed_tools=None``
        blocks none). Non-list raises ``TypeError``; otherwise pass through and
        let the SDK reject unknown tool names / patterns.
        """
        if not value:
            return None
        if not isinstance(value, list):
            raise TypeError(f"{param_name} must be a list, got {type(value).__name__}")
        return value

    def _validate_tools(self, allowed_tools: list | None) -> list | None:
        return self._validate_optional_tool_list(allowed_tools, "allowed_tools")

    def _validate_disallowed_tools(self, disallowed_tools: list | None) -> list | None:
        return self._validate_optional_tool_list(disallowed_tools, "disallowed_tools")

    def _validate_max_turns(self, max_turns: Any) -> int:
        """Validate and convert max_turns parameter."""
        default_max_turns = 50
        if max_turns is None:
            return default_max_turns
        try:
            max_turns_int = int(max_turns)
            if max_turns_int < 1 or max_turns_int > 100:
                raise ValueError
            return max_turns_int
        except (ValueError, TypeError):
            raise ValueError(f"Invalid max_turns: {max_turns}. Must be integer between 1 and 100.") from None

    def _validate_max_thinking_tokens(self, max_thinking_tokens: Any) -> int:
        """Validate and convert max_thinking_tokens parameter."""
        default_tokens = 8000
        if max_thinking_tokens is None:
            return default_tokens
        try:
            tokens = int(max_thinking_tokens)
            if tokens < 1000 or tokens > 100000:
                raise ValueError
            return tokens
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid max_thinking_tokens: {max_thinking_tokens}. Must be integer between 1000 and 100000."
            ) from None

    def _validate_timeout(self, timeout: Any) -> int:
        """Validate and convert timeout parameter."""
        default_timeout = 300  # 5 minutes default
        if timeout is None:
            return default_timeout
        try:
            timeout_int = int(timeout)
            if timeout_int < 30 or timeout_int > 3600:
                raise ValueError
            return timeout_int
        except (ValueError, TypeError):
            raise ValueError(f"Invalid timeout: {timeout}. Must be integer between 30 and 3600 seconds.") from None

    def _validate_resume(self, resume: Any) -> str | None:
        """Validate resume session ID parameter."""
        if not resume:
            return None
        if not isinstance(resume, str):
            raise TypeError(f"resume must be a string (session ID), got {type(resume).__name__}")
        return resume

    def _validate_use_api_key(self, value: Any) -> bool:
        """Resolve the use_api_key billing flag to a strict bool.

        Default False blanks ANTHROPIC_API_KEY for the Claude subprocess so it
        uses the Pro/Max subscription; True lets the ambient key bill to Anthropic
        Console. A templated value may arrive as a string (node params are not
        coerced to bool at runtime) — never trust truthiness, since the string
        "false" is truthy and would silently re-enable per-token billing. Accept
        real bools, integer 0/1, and canonical bool-string literals; fail closed
        on anything else.
        """
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        # Accept integer 0/1 (YAML coerces `- use_api_key: 1` to int, and "1"/"0"
        # strings are already accepted). Safe: bool(0)/bool(1) is unambiguous —
        # no truthiness footgun — and 2+ still falls through to fail closed.
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("true", "1", "yes"):
                return True
            if normalized in ("false", "0", "no"):
                return False
        raise TypeError(
            f"use_api_key must be true or false, got {value!r}. Use "
            "'- use_api_key: true' to bill ANTHROPIC_API_KEY to your Anthropic "
            "Console, or omit it to use your Claude Pro/Max subscription."
        )

    def _validate_schema_retries(self, schema_retries: Any) -> int:
        """Validate and convert the schema_retries parameter.

        Only the int() conversion is wrapped in try/except; the range checks live
        OUTSIDE it. The previous version re-classified its own ValueErrors by
        substring-matching their messages ("cannot"/"requires"), which silently
        misfires the moment a message is reworded.

        It also deliberately does NOT couple schema_retries to max_turns. The retry
        loop only runs when an output_schema is set, and prep() already enforces
        max_turns >= 2 in that case — so a max_turns check here was redundant for the
        schema path and wrongly rejected valid no-schema nodes that intentionally cap
        Claude to one turn (where the retry would never fire).

        Args:
            schema_retries: Schema retry attempts parameter (None → default of 1)

        Returns:
            Validated schema_retries count (0-5)

        Raises:
            ValueError: If not an integer in the range 0-5
        """
        default_schema_retries = 1
        if schema_retries is None:
            return default_schema_retries
        try:
            retries_int = int(schema_retries)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid schema_retries: {schema_retries!r}. Must be an integer between 0 and 5."
            ) from None
        if retries_int < 0:
            raise ValueError(f"schema_retries cannot be negative (got {retries_int}).")
        if retries_int > 5:
            raise ValueError(f"schema_retries cannot exceed 5 (cap to prevent runaway costs; got {retries_int}).")
        return retries_int

    def _validate_sandbox(self, sandbox: Any) -> dict | None:
        """Validate sandbox configuration parameter.

        Sandbox settings control command execution isolation via the Claude Agent SDK.
        See: https://platform.claude.com/docs/en/agent-sdk/python#sandbox-configuration

        Args:
            sandbox: Sandbox configuration dict or None

        Returns:
            Validated sandbox dict or None

        Raises:
            TypeError: If sandbox or nested values have wrong types
        """
        if not sandbox:
            return None
        if not isinstance(sandbox, dict):
            raise TypeError(f"sandbox must be a dict, got {type(sandbox).__name__}")

        # Type validation for known keys (pass through unknown for SDK forward compatibility)
        # Boolean fields
        bool_fields = ["enabled", "autoAllowBashIfSandboxed", "allowUnsandboxedCommands", "enableWeakerNestedSandbox"]
        for field in bool_fields:
            if field in sandbox and not isinstance(sandbox[field], bool):
                raise TypeError(f"sandbox['{field}'] must be bool")

        # Dict fields
        dict_fields = ["network", "ignoreViolations"]
        for field in dict_fields:
            if field in sandbox and not isinstance(sandbox[field], dict):
                raise TypeError(f"sandbox['{field}'] must be a dict")

        # List fields
        if "excludedCommands" in sandbox and not isinstance(sandbox["excludedCommands"], list):
            raise TypeError("sandbox['excludedCommands'] must be a list")

        return sandbox

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare Claude Code execution parameters.

        Args:
            shared: Shared store containing prompt and optional schema

        Returns:
            Dictionary with prepared execution parameters

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        # Validate prompt
        prompt = self._validate_prompt(self.params.get("prompt"))

        # Validate optional parameters
        raw_output_schema = self.params.get("output_schema")
        output_schema = self._validate_schema(raw_output_schema)
        # A declared ``output_schema:`` that resolved to None (e.g. templated
        # from an upstream node that returned None) silently disables structured
        # output. Emit a DEGRADED-triggering warning so the workflow author sees
        # it instead of getting a free-form string where they expected a dict.
        if output_schema is None and "output_schema" in self.params and raw_output_schema is None:
            self._emit_schema_resolved_null_warning(shared)
        cwd = self._validate_cwd(self.params.get("cwd"))

        # Get model with fallback
        model = self.params.get("model", "claude-sonnet-4-5")

        # Validate tools (None = all tools available, including Task for subagents)
        allowed_tools = self._validate_tools(self.params.get("allowed_tools"))

        # Validate disallowed tools (None = no restrictions)
        disallowed_tools = self._validate_disallowed_tools(self.params.get("disallowed_tools"))

        # Validate numeric parameters
        max_turns = self._validate_max_turns(self.params.get("max_turns", 50))
        max_thinking_tokens = self._validate_max_thinking_tokens(self.params.get("max_thinking_tokens", 8000))
        if output_schema is not None and max_turns < 2:
            raise ValueError(
                f"max_turns must be >= 2 when output_schema is set (got {max_turns}). "
                "Structured output requires the agent to take at least one turn beyond producing "
                "the final response. Set max_turns to 2 or higher (default is typically sufficient)."
            )
        schema_retries = self._validate_schema_retries(self.params.get("schema_retries"))

        # Get system prompt
        system_prompt = self.params.get("system_prompt", "")

        # Session management
        resume = self._validate_resume(self.params.get("resume"))

        # Timeout (default 300s, configurable for long multi-agent tasks)
        timeout = self._validate_timeout(self.params.get("timeout"))

        # Sandbox configuration for command isolation
        sandbox = self._validate_sandbox(self.params.get("sandbox"))

        # Billing/auth: default False blanks ANTHROPIC_API_KEY so Claude uses the
        # Pro/Max subscription; True lets the ambient key bill to Anthropic Console.
        use_api_key = self._validate_use_api_key(self.params.get("use_api_key"))

        logger.info(f"Prepared Claude Code execution for prompt: {prompt[:100]}...")

        return {
            "prompt": prompt,
            "output_schema": output_schema,
            "cwd": cwd,
            "model": model,
            "allowed_tools": allowed_tools,
            "disallowed_tools": disallowed_tools,
            "max_turns": max_turns,
            "max_thinking_tokens": max_thinking_tokens,
            "system_prompt": system_prompt,
            "resume": resume,
            "timeout": timeout,
            "sandbox": sandbox,
            "use_api_key": use_api_key,
            "schema_retries": schema_retries,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute Claude Code using async-to-sync wrapper.

        NO try/except here - let exceptions bubble up for PocketFlow's retry mechanism!

        Args:
            prep_res: Prepared parameters from prep()

        Returns:
            Dictionary with execution results
        """
        logger.info(f"Executing Claude Code node with model: {prep_res['model']}")

        # Run async code in sync context using asyncio.run()
        # This creates a new event loop for each execution
        result = asyncio.run(self._exec_async(prep_res), debug=False)

        return result

    async def _exec_async(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Async implementation using Claude Code SDK with schema retry support.

        Args:
            prep_res: Prepared parameters

        Returns:
            Dictionary with results to be processed by post(), including retry_metadata
        """
        # Use the user prompt directly. Structured output is enforced by SDK options.
        prompt = prep_res["prompt"]

        # User system prompt passes through unchanged; no schema prompt injection.
        system_prompt = prep_res.get("system_prompt") or ""

        # Build Claude Code options
        options = self._build_claude_options(prep_res, system_prompt)

        logger.debug(f"Using model: {prep_res['model']}, max_turns: {prep_res['max_turns']}")

        # Execute with timeout handling (first attempt)
        exec_res = await self._execute_with_timeout(prompt, options, prep_res)

        # Initialize retry tracking
        output_schema = prep_res.get("output_schema")
        schema_retries = prep_res.get("schema_retries", 1)
        attempts = 0
        coerced_fields_all: list[str] = []
        retry_usages: list[dict[str, Any]] = []
        conforming = False  # Default: non-conforming if no schema or no structured_output

        # Apply coercion and retry loop if output_schema is present AND schema_retries > 0
        # When schema_retries=0, skip both coercion and retry (strict mode per docs)
        if output_schema is not None and schema_retries > 0:
            structured_output = exec_res.get("structured_output")

            # Phase 1: Coercion (if structured_output is present)
            if structured_output is not None:
                coerced, conforming, coerced_fields = self._coerce_structured_output(structured_output, output_schema)
                exec_res["structured_output"] = coerced
                coerced_fields_all.extend(coerced_fields)
            else:
                conforming = False

            # Phase 2: Retry loop (if non-conforming and retries remain)
            while not conforming and attempts < schema_retries:
                # Check if we have a session_id to resume
                metadata = exec_res.get("metadata", {})
                session_id = metadata.get("session_id")

                if not session_id:
                    logger.warning("Cannot retry schema mismatch: no session_id available")
                    break

                attempts += 1
                logger.info(f"Schema retry attempt {attempts}/{schema_retries} for session {session_id}")

                # Build corrective prompt
                schema_json = json.dumps(output_schema, indent=2)
                corrective_prompt = (
                    "Your previous response did not produce output matching the required schema. "
                    f"Reply with ONLY a JSON object matching this schema:\n\n{schema_json}\n\n"
                    "No prose before or after. Only the JSON object."
                )

                # Build retry options with resume=session_id
                # The user's explicit resume param (if set) is in prep_res["resume"],
                # but for the corrective retry we override with the captured session_id
                retry_prep_res = prep_res.copy()
                retry_prep_res["resume"] = session_id
                retry_options = self._build_claude_options(retry_prep_res, system_prompt)

                # Execute retry (wrapped in try to preserve original result on failure)
                try:
                    retry_exec_res = await self._execute_with_timeout(corrective_prompt, retry_options, retry_prep_res)

                    # Record the OUTGOING attempt (the one we are about to replace) for cost
                    # accounting — NOT the incoming one. _store_results builds the main
                    # llm_usage from the FINAL exec_res, so recording the incoming attempt here
                    # would double-count the final attempt and drop the first one entirely.
                    # Recording the outgoing attempt instead keeps main + retries disjoint and
                    # complete: main = final attempt, retries = [attempt 1 .. attempt n-1], so
                    # the aggregator counts every attempt exactly once.
                    outgoing = self._usage_record_from(exec_res, prep_res.get("model", "claude-sonnet-4-5"))
                    if outgoing:
                        retry_usages.append(outgoing)

                    # The retry result becomes the new main result
                    exec_res = retry_exec_res

                    # Apply coercion to the retry result
                    structured_output = exec_res.get("structured_output")
                    if structured_output is not None:
                        coerced, conforming, coerced_fields = self._coerce_structured_output(
                            structured_output, output_schema
                        )
                        exec_res["structured_output"] = coerced
                        coerced_fields_all.extend(coerced_fields)
                    else:
                        conforming = False
                except Exception as e:
                    # Retry failed (timeout, SDK error, etc). The exception fires BEFORE we
                    # record the outgoing attempt or reassign exec_res above, so the pre-retry
                    # result and its usage are preserved intact (no double-count, no loss).
                    logger.warning(f"Schema retry attempt {attempts} failed: {e}. Keeping original result.")
                    conforming = False
                    break

        # Add retry metadata to exec_res for telemetry
        exec_res["retry_metadata"] = {
            "attempts": attempts,
            "coerced_fields": coerced_fields_all,
            "conforming": conforming,
        }

        # Add retry usages for cost tracking
        if retry_usages:
            exec_res["retry_usages"] = retry_usages

        return exec_res

    @staticmethod
    def _usage_record_from(exec_res: dict[str, Any], model: str) -> dict[str, Any] | None:
        """Build a per-attempt usage record from an exec_res's metadata.

        Used to record a superseded attempt into ``llm_usage["retries"]`` when a schema
        retry replaces it, so cost/token/turn accounting stays complete. Returns None
        when the attempt carried no usage (nothing to account for). Mirrors the main
        ``llm_usage`` shape minus ``total_tokens`` (the aggregator recomputes that).
        """
        metadata = exec_res.get("metadata") or {}
        usage = metadata.get("usage") or {}
        if not usage:
            return None
        # Inclusive input_tokens per pflow's contract — REQUIRED here, not just in
        # post(): the retry aggregator (workflow_trace.aggregate_llm_usage_with_retries)
        # sums per-attempt input_tokens, so a uncached-only record here would silently
        # mix inclusive + uncached. total_tokens is intentionally omitted (the
        # aggregator recomputes it from the summed inputs/outputs).
        return {
            **_claude_token_fields(usage),
            "output_tokens": usage.get("output_tokens", 0) or 0,  # None-safe, matching the helper's guards
            "cost_usd": metadata.get("total_cost_usd"),
            "duration_ms": metadata.get("duration_ms"),
            "num_turns": metadata.get("num_turns"),
            "session_id": metadata.get("session_id"),
            "model": model,
        }

    def _build_claude_options(self, prep_res: dict[str, Any], system_prompt: str) -> ClaudeAgentOptions:
        """Build Claude Code options object.

        Args:
            prep_res: Prepared parameters
            system_prompt: System prompt to use

        Returns:
            ClaudeAgentOptions configured for execution
        """
        # Build base options
        options_kwargs: dict[str, Any] = {
            "model": prep_res["model"],
            "max_thinking_tokens": prep_res["max_thinking_tokens"],
            "system_prompt": system_prompt,
            "max_turns": prep_res["max_turns"],
            "cwd": prep_res["cwd"],
            "permission_mode": "bypassPermissions",  # Always bypass prompts in autonomous workflows
        }

        # Only pass allowed_tools if explicitly set (None = all tools including Task for subagents)
        if prep_res["allowed_tools"] is not None:
            options_kwargs["allowed_tools"] = prep_res["allowed_tools"]

        # Only pass disallowed_tools if explicitly set (None = no restrictions)
        if prep_res.get("disallowed_tools") is not None:
            options_kwargs["disallowed_tools"] = prep_res["disallowed_tools"]

        # Add session resumption if provided
        if prep_res["resume"]:
            options_kwargs["resume"] = prep_res["resume"]

        # Native structured output: SDK translates this to --json-schema CLI flag.
        # subprocess_cli.py only wires the exact json_schema wrapper shape.
        if prep_res.get("output_schema"):
            options_kwargs["output_format"] = {
                "type": "json_schema",
                "schema": prep_res["output_schema"],
            }

        # Add sandbox configuration if provided
        if prep_res.get("sandbox") is not None:
            options_kwargs["sandbox"] = prep_res["sandbox"]

        # Default (use_api_key=False): blank ANTHROPIC_API_KEY for THIS subprocess
        # only, so the Claude CLI uses the Pro/Max subscription instead of API/
        # Console billing. The SDK merges options.env OVER the inherited os.environ
        # (subprocess_cli.py), so we must OVERRIDE the key with an empty string —
        # omitting it leaves the inherited (or pflow settings-injected) key intact,
        # since a dict merge cannot delete an inherited key. os.environ is untouched,
        # so a sibling llm node still reads the real key for LiteLLM. See issue #455.
        if not prep_res.get("use_api_key"):
            options_kwargs["env"] = {"ANTHROPIC_API_KEY": ""}

        return ClaudeAgentOptions(**options_kwargs)

    async def _execute_with_timeout(
        self, prompt: str, options: ClaudeAgentOptions, prep_res: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute Claude Code query with timeout handling.

        Args:
            prompt: The prompt to send
            options: Claude Code options
            prep_res: Prepared parameters

        Returns:
            Dictionary with execution results
        """
        # Use configurable timeout from prep_res
        timeout = prep_res["timeout"]

        # Handle timeout at asyncio level (SDK has no timeout parameter)
        timeout_context = getattr(asyncio, "timeout", None)
        if timeout_context is not None:
            # Python 3.11+
            async with timeout_context(timeout):
                return await self._run_claude_session(prompt, options, prep_res)
        else:
            # Python 3.10 fallback
            return await asyncio.wait_for(self._run_claude_session(prompt, options, prep_res), timeout=timeout)

    async def _run_claude_session(
        self, prompt: str, options: ClaudeAgentOptions, prep_res: dict[str, Any]
    ) -> dict[str, Any]:
        """Run the Claude Code session and process messages.

        Args:
            prompt: The prompt to send
            options: Claude Code options
            prep_res: Prepared parameters

        Returns:
            Dictionary with results
        """
        result_text = ""
        tool_uses = []
        message_count = 0
        metadata = {}
        progress_events = []  # Track streaming progress for tracing
        structured_output: Any = None
        is_error_from_sdk = False
        sdk_exception_text: str | None = None
        api_error_status: int | None = None

        try:
            async for message in query(prompt=prompt, options=options):
                message_count += 1
                logger.debug(f"Received message {message_count}: type={type(message).__name__}")

                if isinstance(message, AssistantMessage):
                    text_chunk, tools, events = self._process_assistant_message(message, result_text)
                    result_text += text_chunk
                    tool_uses.extend(tools)
                    progress_events.extend(events)

                elif isinstance(message, ResultMessage):
                    metadata = self._extract_metadata(message)
                    progress_events.append(self._create_completion_event(metadata))
                    if message.result and not result_text:
                        result_text = message.result
                    structured_output = message.structured_output
                    is_error_from_sdk = is_error_from_sdk or message.is_error
                    # HTTP status of an API-level error (e.g. 401/403 auth). The
                    # SDK drops this from the exception it raises, so capture it
                    # here while the ResultMessage is in scope (#455).
                    api_error_status = getattr(message, "api_error_status", None) or api_error_status
        except Exception as exc:
            # The SDK pairs ``ResultMessage(is_error=True)`` with a non-zero CLI
            # exit raised as ``ProcessError``. That single class of exception is
            # the same signal expressed two ways — soft-fail semantics in post()
            # need the prior is_error state preserved instead of re-raising.
            #
            # Connection failures, missing CLI, timeouts and any other Exception
            # subclass must still reach exec_fallback so the user sees the
            # remediation message for that concrete failure mode.
            exc_type_name = type(exc).__name__
            is_process_error = (
                ProcessError is not None and isinstance(exc, ProcessError)
            ) or exc_type_name == "ProcessError"
            if not is_error_from_sdk or not is_process_error:
                enriched = self._enrich_error_result_exception(
                    exc, exc_type_name, is_error_from_sdk, result_text, api_error_status
                )
                if enriched is not None:
                    raise enriched from exc
                raise
            sdk_exception_text = str(exc)
            logger.warning("Claude Code SDK raised after an error ResultMessage: %s", sdk_exception_text)

        # Log results
        self._log_session_results(tool_uses, result_text)

        # Return results to be processed by post()
        return {
            "result_text": result_text,
            "tool_uses": tool_uses,
            "metadata": metadata,
            "progress_events": progress_events,
            "structured_output": structured_output,
            "is_error_from_sdk": is_error_from_sdk,
            "sdk_exception_text": sdk_exception_text,
        }

    def _process_assistant_message(
        self, message: AssistantMessage, current_text: str
    ) -> tuple[str, list[dict], list[dict]]:
        """Process an assistant message and extract content.

        Args:
            message: The AssistantMessage to process
            current_text: Current accumulated text

        Returns:
            Tuple of (text_chunk, tool_uses, progress_events)
        """
        text_chunk = ""
        tool_uses = []
        progress_events = []

        for block in message.content:
            if isinstance(block, TextBlock):
                block_text = block.text
                text_chunk += block_text
                logger.debug(f"  TextBlock ({len(block_text)} chars): {block_text[:100]}...")

                # Track text generation progress
                progress_events.append({
                    "type": "text_chunk",
                    "length": len(block_text),
                    "total_length": len(current_text) + len(text_chunk),
                    "preview": block_text[:100] if block_text else "",
                })

            elif isinstance(block, ToolUseBlock):
                tool_uses.append({
                    "name": block.name,
                    "input": block.input,
                })
                logger.debug(f"  ToolUseBlock: {block.name}")

                # Track tool usage progress
                progress_events.append({
                    "type": "tool_use",
                    "tool": block.name,
                    "input_preview": str(block.input)[:200] if block.input else "",
                })

        return text_chunk, tool_uses, progress_events

    def _extract_metadata(self, message: ResultMessage) -> dict[str, Any]:
        """Extract metadata from a ResultMessage.

        Args:
            message: The ResultMessage containing metadata

        Returns:
            Dictionary with extracted metadata
        """
        metadata = {
            "total_cost_usd": getattr(message, "total_cost_usd", None),
            "duration_ms": getattr(message, "duration_ms", None),
            "duration_api_ms": getattr(message, "duration_api_ms", None),
            "num_turns": getattr(message, "num_turns", None),
            "session_id": getattr(message, "session_id", None),
            "usage": getattr(message, "usage", None),
            "result": getattr(message, "result", None),
            "errors": getattr(message, "errors", None),
            "api_error_status": getattr(message, "api_error_status", None),
            "stop_reason": getattr(message, "stop_reason", None),
        }
        logger.info(
            f"Captured metadata: cost=${metadata['total_cost_usd']}, "
            f"duration={metadata['duration_ms']}ms, turns={metadata['num_turns']}"
        )
        return metadata

    def _create_completion_event(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Create a completion event from metadata.

        Args:
            metadata: The metadata dictionary

        Returns:
            Completion event dictionary
        """
        return {
            "type": "completion",
            "cost": metadata.get("total_cost_usd"),
            "duration_ms": metadata.get("duration_ms"),
            "turns": metadata.get("num_turns"),
        }

    def _log_session_results(self, tool_uses: list[dict], result_text: str) -> None:
        """Log the results of a Claude session.

        Args:
            tool_uses: List of tools used
            result_text: The response text
        """
        # Log tool uses for audit
        if tool_uses:
            logger.info(f"Claude Code used {len(tool_uses)} tools")
            for tool in tool_uses[:5]:  # Log first 5 tools
                logger.debug(f"Tool: {tool['name']}")

        # Log response for debugging
        if result_text:
            logger.debug(f"Received response text ({len(result_text)} chars): {result_text[:200]}...")
        else:
            logger.warning("No response text received from Claude Code")

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store and determine next action.

        Args:
            shared: Shared store
            prep_res: Preparation results
            exec_res: Execution results from exec()

        Returns:
            Always "default" because workflows may not declare explicit error edges
        """
        node_id = getattr(self, "node_id", None)  # set by compiler; see compilation/compiler.py
        self._store_results(shared, prep_res, exec_res, node_id)

        return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Handle execution failures after all retries exhausted.

        Transform SDK exceptions into user-friendly messages.

        Args:
            prep_res: Preparation results
            exc: The exception that caused failure

        Raises:
            ValueError: With user-friendly error message and remediation steps
        """
        error_msg = str(exc)
        exc_type = type(exc).__name__

        logger.error(f"Claude Code execution failed: {error_msg}", exc_info=exc)

        # Handle specific SDK exceptions (check if exception classes are available)
        if (CLINotFoundError is not None and isinstance(exc, CLINotFoundError)) or "CLINotFoundError" in exc_type:
            raise ValueError(
                "Claude Code CLI not installed. Install with: npm install -g @anthropic-ai/claude-code\n"
                f"Original error: {error_msg}"
            ) from None

        if (CLIConnectionError is not None and isinstance(exc, CLIConnectionError)) or "CLIConnectionError" in exc_type:
            raise ValueError(
                "Failed to connect to Claude Code. Check health with: claude doctor\n"
                f"{self._auth_failure_guidance(bool(prep_res.get('use_api_key')))}\n"
                f"Original error: {error_msg}"
            ) from None

        if (ProcessError is not None and isinstance(exc, ProcessError)) or "ProcessError" in exc_type:
            # Extract exit code if available
            exit_code = getattr(exc, "exit_code", "unknown")
            stderr = getattr(exc, "stderr", "")
            raise ValueError(
                f"Claude Code process failed (exit code {exit_code})\n"
                f"Error output: {stderr}\n"
                f"Original error: {error_msg}"
            ) from None

        # Handle timeout
        if isinstance(exc, asyncio.TimeoutError):
            timeout = prep_res.get("timeout", 300)
            raise ValueError(  # noqa: TRY004 - This is a timeout error, not a type error
                f"Claude Code execution timed out after {timeout} seconds. "
                "The task may be too complex or the system may be slow. "
                "Consider increasing timeout or breaking the task into smaller parts."
            ) from None

        # Handle rate limiting
        if "rate limit" in error_msg.lower() or "429" in error_msg:
            raise ValueError(
                f"Claude API rate limit exceeded. Please wait a moment and try again.\nOriginal error: {error_msg}"
            ) from None

        # Authentication/billing failure. The common case arrives as a bare
        # Exception whose message carries the CLI's error text (the SDK rewrites
        # the result-level error before re-raising), so it falls through the typed
        # branches to here. Attach subscription-vs-API-key remediation tailored to
        # the node's billing mode. See issue #455.
        if self._is_auth_error(exc):
            raise ValueError(self._auth_failure_guidance(bool(prep_res.get("use_api_key")))) from None

        # Generic error — pass through the SDK error message directly
        raise ValueError(f"Claude Code execution failed after {self.max_retries} attempts: {error_msg}") from None

    @staticmethod
    def _enrich_error_result_exception(
        exc: Exception,
        exc_type_name: str,
        is_error_from_sdk: bool,
        result_text: str,
        api_error_status: int | None,
    ) -> Exception | None:
        """Recover the real error detail the SDK drops from an error-result.

        When the CLI reports an error result then exits, the SDK raises a *bare*
        Exception whose text is only the result subtype — e.g. an invalid key
        surfaces as "...returned an error result: success" instead of "Invalid
        API key" (#455). Rebuild the message from the real result text / HTTP
        status captured off the ResultMessage so exec_fallback can detect auth
        failures. Returns an enriched exception to raise, or None to re-raise the
        original unchanged. Typed SDK errors (CLIConnectionError, ...) are left
        alone so exec_fallback's typed branches still match.
        """
        if not (is_error_from_sdk and exc_type_name == "Exception"):
            return None
        detail = str(exc)
        if result_text and result_text not in detail:
            detail = f"{detail}: {result_text}"
        if api_error_status is not None:
            detail = f"{detail} [api_error_status={api_error_status}]"
        return RuntimeError(detail) if detail != str(exc) else None

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Heuristically detect a Claude CLI authentication/billing failure.

        The common auth failure surfaces as a bare ``Exception`` whose message
        carries the CLI's error text (the SDK rewrites the result-level error
        before re-raising), so we match on the message string, not the exception
        type. A multi-marker OR keeps this robust to CLI wording drift.
        """
        text = str(exc).lower()
        return any(marker in text for marker in _AUTH_ERROR_MARKERS)

    @staticmethod
    def _auth_failure_guidance(use_api_key: bool) -> str:
        """Build remediation text for an auth failure, tailored to the billing mode."""
        if use_api_key:
            return (
                "Claude Code authentication failed using ANTHROPIC_API_KEY "
                "(use_api_key: true) — the key may be invalid or out of credit.\n"
                "  - Correct ANTHROPIC_API_KEY in your Anthropic Console, or\n"
                "  - Remove `- use_api_key: true` to use your Claude Pro/Max "
                "subscription instead (no per-token charges)."
            )
        return (
            "Claude Code could not authenticate. This node uses your Claude "
            "Pro/Max subscription by default and ignores ANTHROPIC_API_KEY "
            "unless you opt in.\n"
            "  - Recommended: run `claude auth login` (or `claude setup-token` "
            "for non-interactive/CI) to authenticate with your subscription — no "
            "per-token charges.\n"
            "  - Or add `- use_api_key: true` to this node to bill "
            "ANTHROPIC_API_KEY to your Anthropic Console (pay per token)."
        )

    @staticmethod
    def _coerce_structured_output(  # noqa: C901 - Legitimate complexity for multi-type coercion
        structured_output: Any, schema: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, list[str]]:
        """Coerce scalar fields in structured output to match schema types.

        This handles Shape B failures where the agent returns structurally-valid
        output but a scalar field has the wrong type (e.g., {"continue": "false"}
        for a declared boolean). Applies canonical coercion only:
        - boolean: "true"/"false" (case-insensitive, stripped) → True/False
        - integer/number: numeric strings ("3", "3.0") → int/float
        - string: non-string scalar → str()

        Args:
            structured_output: The output to coerce (must be a dict)
            schema: JSON Schema dict with 'properties' and optionally 'required'

        Returns:
            Tuple of (coerced_output, conforming, coerced_fields):
            - coerced_output: New dict with coerced scalar values
            - conforming: True if all top-level scalar types match the schema AND every
              enum/const constraint is satisfied
            - coerced_fields: List of field names that were coerced

        Edge cases (defensive — coerce nothing, never raise):
        - Schema missing 'properties' → unconstrained object: conforming as-is, no coercion
        - Nested/array fields → not coerced; enum/const on them is still checked
        - Extra fields (not in schema) → ignore
        - Missing required fields → mark as non-conforming
        - enum / const → value must be in the allowed set / equal the const, else non-conforming
        - type: ["string", "null"] → coerce only if result matches after coercion
        """
        # Guard: structured_output must be a dict
        if not isinstance(structured_output, dict):
            return structured_output, False, []

        # An object schema without a 'properties' dict is unconstrained (JSON Schema
        # permits it): there are no declared scalar fields to coerce or judge, so a dict
        # output conforms as-is. Returning False here would wrongly mark valid generic-object
        # output non-conforming, trigger a pointless retry, and then drop it to raw text. The
        # non-dict guard above still rejects a genuinely wrong-shaped (non-dict) output.
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return structured_output, True, []

        required = schema.get("required", [])
        coerced = structured_output.copy()  # Shallow copy at top level
        coerced_fields = []
        all_conform = True

        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue

            runtime_value = coerced.get(field_name)
            declared_type = field_schema.get("type")

            # Missing required field → non-conforming (cannot coerce what isn't there)
            if field_name not in coerced and field_name in required:
                all_conform = False
                continue

            # Field not present and not required → skip
            if field_name not in coerced:
                continue

            # Handle type as array (e.g., ["string", "null"])
            type_list = (
                [declared_type]
                if isinstance(declared_type, str)
                else (declared_type if isinstance(declared_type, list) else [])
            )

            # Only recognized SCALAR types are coerced (v1). A field whose declared type is
            # array/object/unknown is accepted as-is — we never reject the whole output for a
            # non-scalar field we don't coerce (a genuine nested mismatch is a Shape-A soft-fail
            # the retry handles). Without this guard, ANY schema with an array/object field would
            # be marked non-conforming and the valid output dropped to a raw-string soft-fail.
            is_scalar_field = any(t in ("boolean", "integer", "number", "string") for t in type_list)

            # If "null" is in type list and runtime is None, accept as conforming
            if (None in type_list or "null" in type_list) and runtime_value is None:
                continue  # Conforming

            # Try to coerce for each type in the list
            coerced_value = runtime_value
            coercion_succeeded = False

            for target_type in type_list:
                if target_type == "null":
                    continue  # Already handled above

                # Boolean coercion
                if target_type == "boolean":
                    if isinstance(runtime_value, bool):
                        coercion_succeeded = True
                        break
                    if isinstance(runtime_value, str):
                        normalized = runtime_value.strip().lower()
                        if normalized == "true":
                            coerced_value = True
                            coercion_succeeded = True
                            break
                        elif normalized == "false":
                            coerced_value = False
                            coercion_succeeded = True
                            break

                # Integer coercion
                elif target_type == "integer":
                    if isinstance(runtime_value, int) and not isinstance(runtime_value, bool):
                        coercion_succeeded = True
                        break
                    # Coerce float to int if it's an integer value (e.g., 5.0 → 5)
                    if isinstance(runtime_value, float) and runtime_value.is_integer():
                        coerced_value = int(runtime_value)
                        coercion_succeeded = True
                        break
                    if isinstance(runtime_value, str):
                        try:
                            # Accept "3" or "3.0" as integers
                            float_val = float(runtime_value)
                            if float_val.is_integer():
                                coerced_value = int(float_val)
                                coercion_succeeded = True
                                break
                        except (ValueError, OverflowError):
                            pass

                # Number coercion
                elif target_type == "number":
                    if isinstance(runtime_value, (int, float)) and not isinstance(runtime_value, bool):
                        coercion_succeeded = True
                        break
                    if isinstance(runtime_value, str):
                        try:
                            coerced_value = float(runtime_value)
                            coercion_succeeded = True
                            break
                        except (ValueError, OverflowError):
                            pass

                # String coercion
                elif target_type == "string":
                    if isinstance(runtime_value, str):
                        coercion_succeeded = True
                        break
                    # Coerce non-string scalars to string (but NOT None - that's non-conforming)
                    # Converting None to "None" string is silent corruption
                    if isinstance(runtime_value, (bool, int, float)):
                        coerced_value = str(runtime_value)
                        coercion_succeeded = True
                        break

            # Apply coercion if it succeeded and value/type changed
            # Note: 5 != 5.0 is False (numerically equal), so also check type
            if coercion_succeeded:
                if coerced_value != runtime_value or type(coerced_value) is not type(runtime_value):
                    coerced[field_name] = coerced_value
                    coerced_fields.append(field_name)
            elif is_scalar_field:
                # A recognized scalar field we could NOT coerce → genuinely non-conforming
                # (triggers retry). Non-scalar/unknown fields fall through as conforming, since
                # scalar coercion is the only thing this pass judges in v1.
                all_conform = False

            # enum / const are the common constrained-string patterns (e.g.
            # risk_level: {enum: [...]}). Type coercion alone can't judge them: a value of
            # the right TYPE but outside the allowed set must be non-conforming so the retry
            # can re-prompt. Checked against the post-coercion value. Scope is deliberately
            # enum + const ONLY — this is not a general JSON Schema validator.
            final_value = coerced.get(field_name)
            field_enum = field_schema.get("enum")
            if (isinstance(field_enum, list) and field_enum and final_value not in field_enum) or (
                "const" in field_schema and final_value != field_schema["const"]
            ):
                all_conform = False

        return coerced, all_conform, coerced_fields

    def _store_results(
        self,
        shared: dict[str, Any],
        prep_res: dict[str, Any],
        exec_res: dict[str, Any],
        node_id: str | None,
    ) -> None:
        """Store results in shared store.

        Result placement rules:
        - No schema: shared["result"] = raw text (str)
        - Schema + structured_output present: shared["result"] = parsed JSON
        - Schema + structured_output missing: soft-fail with raw text, _schema_error, and __warnings__
        - is_error=True + structured_output present: structured_output wins; _schema_error
          set as a soft-fail signal and __warnings__ written (when node_id is bound)

        Lifecycle action: post() always returns "default". Soft-fail signals
        (`_schema_error`, `__warnings__`) communicate the issue without
        triggering on-error routing — a workflow's `- on-error:` edge does
        NOT fire on schema misses or SDK soft-errors.
        """
        result_text = exec_res.get("result_text", "")
        structured_output = exec_res.get("structured_output")
        is_error_from_sdk = exec_res.get("is_error_from_sdk", False)
        has_schema = prep_res.get("output_schema") is not None
        metadata = exec_res.get("metadata", {})
        tool_uses = exec_res.get("tool_uses", [])
        progress_events = exec_res.get("progress_events", [])
        warning_context = self._build_schema_warning_context(prep_res, exec_res)

        # Store progress events for trace visibility (if any)
        if progress_events:
            shared["_claude_progress"] = progress_events
            logger.debug(f"Stored {len(progress_events)} progress events for tracing")

        # Store metadata in standardized llm_usage format
        if metadata:
            usage = metadata.get("usage") or {}

            # Normalize the SDK's disjoint token split into pflow's inclusive
            # contract (input_tokens = total including cached prefix). See
            # _claude_token_fields / core/llm_usage.py.
            token_fields = _claude_token_fields(usage)
            # ``or 0``: an explicit ``output_tokens: None`` from the SDK would slip past
            # the ``, 0`` default (only absent keys default), then crash the total_tokens
            # sum below. Coerce to match _claude_token_fields' None-guards.
            total_output = usage.get("output_tokens", 0) or 0

            shared["llm_usage"] = {
                "model": self.params.get("model", "claude-sonnet-4-5"),
                **token_fields,
                "output_tokens": total_output,
                "total_tokens": token_fields["input_tokens"] + total_output,
                # ClaudeCodeNode mirrors total_cost_usd (Claude SDK convention)
                # into cost_usd at its producer boundary so the rest of the
                # pipeline reads a single key (matching LLMNode/LiteLLM output).
                "cost_usd": metadata.get("total_cost_usd"),
                "duration_ms": metadata.get("duration_ms"),
                "num_turns": metadata.get("num_turns"),
                "session_id": metadata.get("session_id"),
            }

            # Add retry costs if present (Phase 2 — synthetic item pattern)
            retry_usages = exec_res.get("retry_usages", [])
            if retry_usages:
                shared["llm_usage"]["retries"] = retry_usages
                logger.debug(f"Stored {len(retry_usages)} schema retry attempts in llm_usage")

            if metadata.get("total_cost_usd"):
                logger.info(f"Claude Code execution cost: ${metadata['total_cost_usd']}")
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        # Store tool usage for trace visibility
        if tool_uses:
            shared["_claude_tools"] = [
                {
                    "name": tool["name"],
                    "input_summary": str(tool.get("input", ""))[:500],  # Truncated for storage
                }
                for tool in tool_uses
            ]
            logger.debug(f"Stored {len(tool_uses)} tool uses for tracing")

        # If no schema, store text directly
        if not has_schema:
            shared["result"] = result_text
            return

        # Extract retry metadata for soft-fail signaling
        retry_metadata = exec_res.get("retry_metadata", {})
        retry_attempts = retry_metadata.get("attempts", 0)
        conforming = retry_metadata.get("conforming", True)  # Default True when no schema or no retries

        self._store_schema_result(
            shared,
            node_id,
            result_text=result_text,
            structured_output=structured_output,
            is_error_from_sdk=is_error_from_sdk,
            warning_context=warning_context,
            retry_attempts=retry_attempts,
            conforming=conforming,
        )

    def _store_schema_result(
        self,
        shared: dict[str, Any],
        node_id: str | None,
        *,
        result_text: str,
        structured_output: Any,
        is_error_from_sdk: bool,
        warning_context: dict[str, Any],
        retry_attempts: int = 0,
        conforming: bool = True,
    ) -> None:
        """Place result + soft-fail signals on the schema path.

        Branches:
        - structured_output present + no SDK error → success (result only).
        - structured_output present + SDK error → use structured_output but
          record a soft-fail signal so the SDK error isn't silently dropped.
        - structured_output missing → raw text fallback + soft-fail signal.

        Soft-fail signals use ``setdefault("_schema_error", ...)`` (so any
        prior write — like ``_emit_schema_resolved_null_warning`` — wins)
        plus an ``__warnings__[node_id]`` write when ``node_id`` is bound.

        Args:
            retry_attempts: Number of schema retry attempts made (0 = no retries)
            conforming: Whether structured output conforms to schema (Shape B detection)
        """
        # Shape B silent failure: structured_output present but non-conforming after retries
        if structured_output is not None and not conforming and retry_attempts > 0:
            # This is a Shape B failure — the agent returned a dict but with uncoercible
            # scalar types. We attempted retries but they didn't fix it. Fall through to
            # raw text + warning rather than storing the non-conforming dict.
            shared["result"] = result_text
            msg = (
                f"Model returned non-conforming structured output after {retry_attempts} "
                f"{'retry' if retry_attempts == 1 else 'retries'} (Shape B: uncoercible scalar types). "
                "Raw text stored in result. Check JSON Schema type spelling and field values."
            )
            self._emit_soft_fail_signal(
                shared,
                node_id,
                kind="claude_code.schema_not_satisfied_after_retries",
                msg=msg,
                warning_context=warning_context,
                retry_attempts=retry_attempts,
            )
            return

        if structured_output is not None:
            shared["result"] = structured_output
            if is_error_from_sdk:
                self._emit_soft_fail_signal(
                    shared,
                    node_id,
                    kind="claude_code.sdk_error_with_structured_output",
                    msg=(
                        "Claude CLI reported is_error=True but structured_output was produced. "
                        "Using structured_output as result; check provider for partial-response details."
                    ),
                    warning_context=warning_context,
                    retry_attempts=retry_attempts,
                )
            return

        shared["result"] = result_text
        if is_error_from_sdk:
            msg = (
                "Claude CLI reported an error and did not produce structured output. "
                "Raw text stored in result. Check SDK error details and the output_schema."
            )
            kind = "claude_code.sdk_error_no_structured_output"
        else:
            # Base message for schema not satisfied
            # If retry was attempted, adjust the kind and message
            if retry_attempts > 0:
                kind = "claude_code.schema_not_satisfied_after_retries"
                msg = (
                    f"Model did not return structured output matching the schema after {retry_attempts} "
                    f"{'retry' if retry_attempts == 1 else 'retries'}. Raw text stored in result. "
                    "Check JSON Schema type spelling, required fields, and impossible enum/const constraints."
                )
            else:
                kind = "claude_code.schema_not_satisfied"
                msg = (
                    "Model did not return structured output matching the schema. "
                    "Raw text stored in result. Check JSON Schema type spelling, required fields, "
                    "and impossible enum/const constraints."
                )
        self._emit_soft_fail_signal(
            shared, node_id, kind=kind, msg=msg, warning_context=warning_context, retry_attempts=retry_attempts
        )

    @staticmethod
    def _emit_soft_fail_signal(
        shared: dict[str, Any],
        node_id: str | None,
        *,
        kind: str,
        msg: str,
        warning_context: dict[str, Any],
        retry_attempts: int = 0,
    ) -> None:
        """Centralized soft-fail signaling for structured-output mode.

        Writes ``_schema_error`` (via ``setdefault`` so an earlier writer wins)
        and a structured ``__warnings__[node_id]`` entry when ``node_id`` is
        bound. The ``__warnings__`` entry is what flips workflow status to
        ``DEGRADED``; ``_schema_error`` is the fallback signal that survives
        when ``node_id`` is unbound (test paths).

        Args:
            retry_attempts: Number of schema retry attempts made (0 = no retries)
        """
        shared.setdefault("_schema_error", msg)
        if node_id is not None:
            warning_entry: dict[str, Any] = {
                "kind": kind,
                "text": msg,
                "context": warning_context,
            }
            # Include retry attempts in the warning entry if > 0
            if retry_attempts > 0:
                warning_entry["retry_attempts"] = retry_attempts
            shared.setdefault("__warnings__", {})[node_id] = warning_entry

    @staticmethod
    def _build_schema_warning_context(prep_res: dict[str, Any], exec_res: dict[str, Any]) -> dict[str, Any]:
        """Build compact, agent-actionable context for structured-output warnings."""
        output_schema = prep_res.get("output_schema") or {}
        properties = output_schema.get("properties") if isinstance(output_schema, dict) else None
        metadata = exec_res.get("metadata") or {}
        result_text = exec_res.get("result_text") or ""
        return {
            "node_type": "claude-code",
            "schema_properties": list(properties) if isinstance(properties, dict) else [],
            "schema_required": output_schema.get("required") if isinstance(output_schema, dict) else None,
            "result_preview": result_text[:500],
            "sdk_result": metadata.get("result"),
            "sdk_errors": metadata.get("errors"),
            "sdk_error_status": metadata.get("api_error_status"),
            "sdk_stop_reason": metadata.get("stop_reason"),
            "sdk_exception": exec_res.get("sdk_exception_text"),
        }
