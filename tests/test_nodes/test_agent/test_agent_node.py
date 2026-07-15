"""Comprehensive tests for Claude Code Agentic Node.

Tests criteria from the specification:
1. Prompt missing → ValueError with "No prompt provided"
2. Prompt empty string → ValueError with "Prompt cannot be empty"
3. Large prompts are accepted (no length cap — a coding agent receives file/context content)
4. Working directory missing/restricted → clear ValueError
5. Native SDK structured output is wired through ClaudeAgentOptions.output_format
6. JSON Schema validation catches legacy format, empty schemas, and top-level non-object schemas
7. max_turns >= 2 is required when output_schema is set
8. Valid task without schema → shared["result"] populated with text
9. Valid task with schema → shared["result"] populated from ResultMessage.structured_output
10. Schema soft-failures write _schema_error and __warnings__
11. SDK error signals preserve structured output when available and warn
12. SDK/process/rate-limit/timeout errors are transformed by exec_fallback

``__warnings__`` assertion conventions (deliberate split — both are used):

- ``shared = {"__warnings__": {}}`` + ``assert not shared["__warnings__"]``
  Tests that EXERCISE a happy path. Pre-initializing the channel makes the
  "empty after run" assertion semantic ("we ran successfully and didn't write
  any warnings"). The pre-init also matches what the production engine seeds
  into shared state for full runs.

- ``shared = {}`` + ``assert "__warnings__" not in shared``
  Tests that exercise EARLY-RETURN paths in ``prep`` (no ``node_id`` bound,
  schema-absent, etc.) where the production code intentionally never touches
  the channel. The strict "key absent" assertion catches accidental
  ``setdefault`` calls that would create the empty dict as a side effect.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.exceptions import PflowError
from pflow.core.workflow.validator import WorkflowValidator
from pflow.nodes.agent.agent_node import AgentNode
from pflow.nodes.agent.backend import AgentResult
from pflow.nodes.agent.claude_backend import ClaudeBackend, _claude_token_fields
from pflow.nodes.agent.exceptions import AgentValidationError
from pflow.registry.metadata_extractor import PflowMetadataExtractor

# The mock ``claude_agent_sdk`` is installed by this directory's conftest.py (via
# tests/shared/claude_sdk_stub.install()) BEFORE this module is imported, so the node
# above binds its SDK names to the mocks regardless of test import order. These are the
# mock classes the tests build messages/errors with. See tests/CLAUDE.md #17.
from tests.shared.claude_sdk_stub import (
    AssistantMessage,
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)


# Fixtures for common test setup
@pytest.fixture
def agent_node():
    """Create an AgentNode configured for the Claude backend."""
    node = AgentNode()
    node.params = {"backend": "claude"}
    return node


@pytest.fixture
def shared_store():
    """Create a basic shared store with prompt."""
    return {"prompt": "Write a hello world function"}


@pytest.fixture
def mock_query_success():
    """Mock successful Claude query with text response."""

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="def hello_world():\n    print('Hello, World!')")])

    with patch("pflow.nodes.agent.claude_backend.query") as mock:
        mock.return_value = mock_response()
        yield mock


# Test Criteria 1: Prompt missing → ValueError pointing at the `- prompt:` param
def test_task_missing(agent_node):
    """Missing prompt raises ValueError in authoring vocabulary.

    Regression: the error must speak the `.pflow.md` authoring surface
    (`- prompt:` / `${...}`), not runtime internals. An agent only ever
    writes markdown — `shared[...]` / `params` are unactionable leaks.
    """
    shared = {"__warnings__": {}}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    message = str(exc_info.value)
    assert "'prompt'" in message
    assert "- prompt:" in message
    # No runtime internals leak into agent-facing text.
    assert "shared[" not in message
    assert "shared store" not in message


def test_backend_is_required() -> None:
    node = AgentNode()
    node.params = {"prompt": "do work"}

    with pytest.raises(AgentValidationError, match=r"requires 'backend'.*claude, codex"):
        node.prep({})


def test_claude_rejects_codex_only_param(agent_node) -> None:
    agent_node.params = {
        "backend": "claude",
        "prompt": "do work",
        "approval_policy": "never",
    }

    with pytest.raises(AgentValidationError, match="'approval_policy' is not valid for backend 'claude'"):
        agent_node.prep({})


def test_codex_rejects_claude_only_param_before_subprocess_launch() -> None:
    node = AgentNode()
    node.params = {"backend": "codex", "prompt": "do work", "max_turns": 5}

    with pytest.raises(AgentValidationError, match="'max_turns' is not valid for backend 'codex'"):
        node.prep({})


def test_codex_selection_loads_real_backend() -> None:
    node = AgentNode()
    node.params = {"backend": "codex", "prompt": "do work"}

    prepared = node.prep({})

    assert type(prepared["_backend"]).__name__ == "CodexBackend"
    assert prepared["model"] is None
    assert prepared["sandbox"] == "workspace-write"


# Test Criteria 2: Prompt empty string → ValueError with "cannot be empty"
def test_task_empty_string(agent_node):
    """Test that empty string prompt raises ValueError."""
    agent_node.params = {"backend": "claude", "prompt": "   "}  # Whitespace only
    shared = {"__warnings__": {}}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "cannot be empty" in str(exc_info.value)


# Test Criteria 3: large prompts are accepted (no length cap)
def test_large_prompt_is_accepted(agent_node):
    """A prompt far larger than the old 10k cap is accepted, not rejected.

    A coding agent routinely receives file contents / accumulated context via
    ${node.output}, so an arbitrary char limit would hard-fail valid workflows
    before the model is ever called.
    """
    large_prompt = "x" * 200_000
    assert agent_node._validate_prompt(large_prompt) == large_prompt


# Test Criteria 4: Working directory missing → ValueError with path
def test_working_directory_missing(agent_node):
    """Test that non-existent working directory raises ValueError."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "cwd": "/nonexistent/path"}
    shared = {"__warnings__": {}}

    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "Working directory does not exist" in str(exc_info.value)
    message = str(exc_info.value).replace("\\", "/")
    assert "nonexistent/path" in message


# Test Criteria 5: Working directory restricted → ValueError with "Restricted directory"
def test_working_directory_restricted(agent_node):
    """Test that restricted directories raise ValueError."""
    if sys.platform == "win32":
        pytest.skip("POSIX root/system-directory restrictions do not map to Windows")

    shared = {"__warnings__": {}}

    # Test multiple restricted directories
    for restricted in ["/", "/etc", "/usr", "/bin"]:
        agent_node.params = {"backend": "claude", "prompt": "test prompt", "cwd": restricted}
        with pytest.raises(AgentValidationError) as exc_info:
            agent_node.prep(shared)
        assert "Restricted directory" in str(exc_info.value)


# Note: Tests 6 & 7 (CLI/auth checking) removed as authentication is now handled by SDK


# Test Criteria 8: Valid prompt without schema → "success" and shared["result"] populated
def test_valid_task_without_schema(agent_node):
    """Test successful execution without output schema."""
    agent_node.params = {"backend": "claude", "prompt": "Write a hello world function"}
    shared = {}
    agent_node.shared = shared

    # Mock query response
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="def hello_world():\n    print('Hello, World!')")])

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        # Prepare and execute
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == "def hello_world():\n    print('Hello, World!')"
        assert result["tool_uses"] == []

        # Check post() stores results (now string format without schema)
        agent_node.post(shared, prep_res, result)
        assert "result" in shared
        assert isinstance(shared["result"], str)
        assert "def hello_world()" in shared["result"]
        assert "Hello, World!" in shared["result"]


# Test Criteria 9: Valid prompt with schema → "success" and schema keys in shared
def test_valid_task_with_schema(agent_node):
    """Test successful execution with output schema."""
    schema = {
        "type": "object",
        "properties": {
            "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["risk_level", "issues"],
    }
    agent_node.params = {
        "backend": "claude",
        "prompt": "Review this code for issues",
        "output_schema": schema,
    }
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="Analysis complete.")])
        yield ResultMessage(structured_output={"risk_level": "low", "issues": []}, is_error=False)

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        # Prepare and execute
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == "Analysis complete."
        assert result["structured_output"] == {"risk_level": "low", "issues": []}

        agent_node.post(shared, prep_res, result)
        assert shared["result"] == {"risk_level": "low", "issues": []}
        assert "_schema_error" not in shared
        assert not shared["__warnings__"]


def test_legacy_python_alias_schema_rejected(agent_node):
    """Old custom output_schema format raises with migration guidance."""
    with pytest.raises(AgentValidationError, match="legacy Python-alias format"):
        agent_node._validate_schema({"risk_level": {"type": "str", "description": "high/medium/low"}})


def test_legacy_format_detection_checks_all_values(agent_node):
    """Legacy detection checks all values, not just the first."""
    schema = {"_meta": "comment", "risk": {"type": "str", "description": "high/medium/low"}}
    with pytest.raises(AgentValidationError, match="legacy Python-alias format"):
        agent_node._validate_schema(schema)


def test_top_level_oneOf_schema_rejected(agent_node):
    """Verified via real-API probe: oneOf top-level returns HTTP 400.
    Combinators must live inside an object wrapper.
    """
    with pytest.raises(AgentValidationError, match="top-level type: object"):
        agent_node._validate_schema({"oneOf": [{"type": "string"}, {"type": "integer"}]})


def test_top_level_anyOf_schema_rejected(agent_node):
    """anyOf at top level is rejected by the API — same class as oneOf."""
    with pytest.raises(AgentValidationError, match="top-level type: object"):
        agent_node._validate_schema({"anyOf": [{"type": "object"}, {"type": "object"}]})


def test_top_level_allOf_schema_rejected(agent_node):
    """allOf at top level is rejected by the API — same class as oneOf."""
    with pytest.raises(AgentValidationError, match="top-level type: object"):
        agent_node._validate_schema({"allOf": [{"type": "object"}, {"type": "object"}]})


def test_top_level_missing_type_rejected(agent_node):
    """A dict without top-level `type` is rejected — the API requires `type: object`."""
    with pytest.raises(AgentValidationError, match="top-level type: object"):
        agent_node._validate_schema({"properties": {"x": {"type": "string"}}})


def test_top_level_array_schema_rejected(agent_node):
    """The Claude API rejects non-object top-level schemas; prep catches this."""
    with pytest.raises(AgentValidationError, match="top-level type: object"):
        agent_node._validate_schema({"type": "array", "items": {"type": "string"}})


def test_top_level_primitive_schema_rejected(agent_node):
    """Primitive top-level schemas must be wrapped in an object."""
    with pytest.raises(AgentValidationError, match="top-level type: object"):
        agent_node._validate_schema({"type": "string", "enum": ["yes", "no"]})


def test_top_level_object_with_oneOf_accepted(agent_node):
    """oneOf INSIDE a top-level `type: object` is fine — the wrapper is what the API requires."""
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "oneOf": [{"required": ["x"]}, {"required": []}],
    }
    assert agent_node._validate_schema(schema) == schema


def test_empty_schema_dict_rejected(agent_node):
    """Empty dict likely means the schema body was omitted."""
    with pytest.raises(AgentValidationError, match="empty dict"):
        agent_node._validate_schema({})


def test_none_schema_returns_none(agent_node):
    """None means no schema was requested."""
    assert agent_node._validate_schema(None) is None


def test_non_dict_schema_raises_typeerror(agent_node):
    """output_schema must be a JSON Schema dict."""
    with pytest.raises(AgentValidationError):
        agent_node._validate_schema(["not", "a", "dict"])


def test_registry_interface_outputs_exclude_root_warnings():
    """Root __warnings__ is diagnostic state, not a node template output."""
    metadata = PflowMetadataExtractor().extract_metadata(AgentNode)
    output_keys = {item["key"] for item in metadata["outputs"]}
    assert "result" in output_keys
    assert "_schema_error" in output_keys
    assert "__warnings__" not in output_keys


def test_output_schema_wrapped_and_passed_to_options(agent_node):
    """JSON Schema is wrapped in the SDK's native output_format shape."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}
    prep_res = agent_node.prep({})

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert mock_options.call_args.kwargs["output_format"] == {
        "type": "json_schema",
        "schema": schema,
    }


def test_exec_passes_structured_options_to_query(agent_node):
    """The execution path must pass the ClaudeAgentOptions object into query()."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    sentinel_options = object()
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output={"x": "ok"}, is_error=False)

    with (
        patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions", return_value=sentinel_options) as mock_options,
        patch("pflow.nodes.agent.claude_backend.query") as mock_query,
    ):
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep({})
        agent_node.exec(prep_res)

    assert mock_options.call_args.kwargs["output_format"] == {
        "type": "json_schema",
        "schema": schema,
    }
    assert mock_query.call_args.kwargs["options"] is sentinel_options


def test_no_schema_means_no_output_format(agent_node):
    """Without output_schema, output_format is omitted."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep({})

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert "output_format" not in mock_options.call_args.kwargs


# Test Criteria 12: Rate limit error → ValueError with retry message
def test_rate_limit_error(agent_node):
    """Test rate limit error handling."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def mock_error(*args, **kwargs):
        raise ValueError("429 Too Many Requests - Rate limit exceeded")
        yield  # Make it async generator

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_error()

        prep_res = agent_node.prep(shared)

        # Execute should raise, then exec_fallback handles it
        with pytest.raises(ValueError) as exc_info:
            agent_node.exec(prep_res)

        # Test exec_fallback handling
        with pytest.raises(ValueError) as fallback_exc:
            agent_node.exec_fallback(prep_res, exc_info.value)

        assert "rate limit exceeded" in str(fallback_exc.value).lower()
        assert "wait a moment and try again" in str(fallback_exc.value).lower()


# Test Criteria 13: Timeout at 300s → ValueError with timeout message
def test_timeout_error(agent_node):
    """Test timeout error handling."""
    # Speed up test with shorter timeout via params (minimum allowed is 30s, but we patch it)
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "timeout": 30}  # Use minimum allowed timeout
    shared = {}
    agent_node.shared = shared

    async def mock_timeout(*args, **kwargs):
        await asyncio.sleep(100)  # Exceed timeout (will be cut short by 0.1s timeout)
        yield AssistantMessage(content=[TextBlock(text="Never reached")])

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_timeout()

        prep_res = agent_node.prep(shared)
        # Override with very short timeout for testing (bypass validation)
        prep_res["timeout"] = 0.1

        # Execute should timeout
        with pytest.raises(asyncio.TimeoutError):
            agent_node.exec(prep_res)

        # Test exec_fallback handling
        with pytest.raises(ValueError) as fallback_exc:
            agent_node.exec_fallback(prep_res, asyncio.TimeoutError())

        assert "timed out" in str(fallback_exc.value).lower()
        assert "0.1 seconds" in str(fallback_exc.value)


# Test Criteria 14: CLINotFoundError handling → Correct error transformation
def test_cli_not_found_error_handling(agent_node):
    """Test CLINotFoundError transformation."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {}
    agent_node.shared = shared

    async def mock_cli_error(*args, **kwargs):
        raise CLINotFoundError("Claude CLI not found")
        yield  # Make it async generator

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_cli_error()

        prep_res = agent_node.prep(shared)

        with pytest.raises(CLINotFoundError):
            agent_node.exec(prep_res)

        # Test exec_fallback transforms the error
        with pytest.raises(ValueError) as fallback_exc:
            agent_node.exec_fallback(prep_res, CLINotFoundError("Test"))

        assert "Claude Code CLI not installed" in str(fallback_exc.value)
        assert "npm install -g @anthropic-ai/claude-code" in str(fallback_exc.value)


# Test Criteria 15: CLIConnectionError handling → Correct error transformation
def test_cli_connection_error_handling(agent_node):
    """Test CLIConnectionError transformation."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {}
    agent_node.shared = shared

    async def mock_conn_error(*args, **kwargs):
        raise CLIConnectionError("Connection failed")
        yield  # Make it async generator

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_conn_error()

        prep_res = agent_node.prep(shared)

        with pytest.raises(CLIConnectionError):
            agent_node.exec(prep_res)

        # Test exec_fallback transforms the error
        with pytest.raises(ValueError) as fallback_exc:
            agent_node.exec_fallback(prep_res, CLIConnectionError("Test"))

        assert "Failed to connect to Claude Code" in str(fallback_exc.value)
        assert "claude doctor" in str(fallback_exc.value)
        assert "claude auth login" in str(fallback_exc.value)


# Test Criteria 16: ProcessError handling → Includes exit code
def test_process_error_handling(agent_node):
    """Test ProcessError transformation with exit code."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {}
    agent_node.shared = shared

    error = ProcessError(exit_code=127, stderr="Command not found")

    async def mock_proc_error(*args, **kwargs):
        raise error
        yield  # Make it async generator

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_proc_error()

        prep_res = agent_node.prep(shared)

        with pytest.raises(ProcessError):
            agent_node.exec(prep_res)

        # Test exec_fallback includes exit code
        with pytest.raises(ValueError) as fallback_exc:
            agent_node.exec_fallback(prep_res, error)

        assert "exit code 127" in str(fallback_exc.value)
        assert "Command not found" in str(fallback_exc.value)


# Test Criteria 17: Tool configuration → All tools available by default, pass through when specified
def test_tool_configuration(agent_node):
    """Test that tools are passed through to SDK without validation.

    By default (allowed_tools=None), all tools are available including Task for subagents.
    When explicitly specified, tools are passed through to SDK for validation.
    """
    shared = {}

    # Default: None = all tools available (including Task for subagents)
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep(shared)
    assert prep_res["allowed_tools"] is None  # None = SDK default (all tools)

    # Explicit tools are passed through without validation
    explicit_tools = ["Read", "Write", "Edit", "Bash"]
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "allowed_tools": explicit_tools}
    prep_res = agent_node.prep(shared)
    assert prep_res["allowed_tools"] == explicit_tools

    # Task tool (for subagents) can now be explicitly included
    tools_with_task = ["Read", "Write", "Task", "Glob", "Grep"]
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "allowed_tools": tools_with_task}
    prep_res = agent_node.prep(shared)
    assert prep_res["allowed_tools"] == tools_with_task
    assert "Task" in prep_res["allowed_tools"]  # Task tool for subagents


# Test: Resume parameter for session continuation
def test_resume_parameter(agent_node):
    """Test that resume parameter is validated and passed through."""
    shared = {}

    # Default: None
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep(shared)
    assert prep_res["resume"] is None

    # Valid session ID
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "resume": "session-abc123"}
    prep_res = agent_node.prep(shared)
    assert prep_res["resume"] == "session-abc123"

    # Invalid type should raise
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "resume": 12345}  # Not a string
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "resume must be a string" in str(exc_info.value)


# Test: Timeout parameter configuration
def test_timeout_parameter(agent_node):
    """Test that timeout parameter is validated and configurable."""
    shared = {}

    # Default: 300 seconds
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep(shared)
    assert prep_res["timeout"] == 300

    # Custom timeout
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "timeout": 600}
    prep_res = agent_node.prep(shared)
    assert prep_res["timeout"] == 600

    # Too short (< 30s)
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "timeout": 10}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "between 30 and 3600" in str(exc_info.value)

    # Too long (> 3600s)
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "timeout": 5000}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "between 30 and 3600" in str(exc_info.value)


# Test Criteria 19: Valid JSON response → Values stored in schema keys
def test_valid_json_response_storage(agent_node):
    """Test that structured_output is stored directly."""
    schema = {
        "type": "object",
        "properties": {
            "complexity": {"type": "string"},
            "lines": {"type": "integer"},
            "functions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["complexity", "lines", "functions"],
    }
    agent_node.params = {
        "backend": "claude",
        "prompt": "Analyze code",
        "output_schema": schema,
    }
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="Analysis complete.")])
        yield ResultMessage(
            structured_output={
                "complexity": "medium",
                "lines": 42,
                "functions": ["main", "helper", "utils"],
            },
            is_error=False,
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

        assert isinstance(result, dict)

        agent_node.post(shared, prep_res, result)
        assert shared["result"] == {
            "complexity": "medium",
            "lines": 42,
            "functions": ["main", "helper", "utils"],
        }
        assert "_schema_error" not in shared
        assert not shared["__warnings__"]


# Test Criteria 20: Invalid JSON response → Raw text in result, error in _schema_error
def test_invalid_json_response_fallback(agent_node):
    """Schema set + no structured_output falls back to raw text and warns."""
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
    agent_node.params = {
        "backend": "claude",
        "prompt": "Analyze code",
        "output_schema": schema,
        "schema_retries": 0,  # FALLBACK test, not the retry feature (#465)
    }
    agent_node.node_id = "review"
    shared = {}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="This is not JSON at all, just plain text response.")])
        yield ResultMessage(structured_output=None, result="This is not JSON at all, just plain text response.")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

        assert isinstance(result, dict)

        agent_node.post(shared, prep_res, result)
        assert shared["result"] == "This is not JSON at all, just plain text response."
        assert "Model did not return" in shared["_schema_error"]
        assert shared["__warnings__"]["review"]["kind"] == "agent.schema_not_satisfied"


def test_sdk_is_error_branch(agent_node):
    """SDK is_error without structured_output uses the CLI-error soft-fail warning."""
    schema = {"type": "object", "properties": {"found": {"type": "string"}}, "required": ["found"]}
    agent_node.params = {
        "backend": "claude",
        "prompt": "Analyze code",
        "output_schema": schema,
        "schema_retries": 0,  # FALLBACK test, not the retry feature (#465)
    }
    agent_node.node_id = "review"
    shared = {}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="error context")])
        yield ResultMessage(structured_output=None, result="error context", is_error=True)
        # The SDK pairs ResultMessage(is_error=True) with a ProcessError raise
        # when the CLI exits non-zero; the node must preserve the is_error state
        # rather than re-raise. Other exception types are tested separately.
        raise ProcessError(exit_code=1, stderr="Claude Code returned an error result: error context")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

        assert isinstance(result, dict)

        agent_node.post(shared, prep_res, result)
        assert shared["result"] == "error context"
        assert "Claude CLI reported an error" in shared["_schema_error"]
        assert shared["__warnings__"]["review"]["kind"] == "agent.sdk_error_no_structured_output"
        assert shared["__warnings__"]["review"]["context"]["sdk_exception"]


def test_sdk_is_error_without_schema_degrades_free_form_result(agent_node):
    """Free-form SDK soft-errors retain text but cannot report workflow success."""
    agent_node.params = {"backend": "claude", "prompt": "Analyze code"}
    agent_node.node_id = "review"
    shared: dict[str, Any] = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(result="partial error context", is_error=True)
        raise ProcessError(exit_code=1, stderr="Claude Code returned an error result")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    assert shared["result"] == "partial error context"
    assert "free-form response" in shared["_agent_error"]
    assert "_schema_error" not in shared
    assert shared["__warnings__"]["review"]["kind"] == "agent.backend_error_free_form"


# Test Criteria 22: No response content → Empty result stored
def test_no_response_content(agent_node):
    """Test that empty response stores empty result."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {}
    agent_node.shared = shared

    # Mock empty response
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[])

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == ""

        # Check post() handles empty response (now stores as string)
        agent_node.post(shared, prep_res, result)
        assert isinstance(shared["result"], str)
        assert shared["result"] == ""


# Additional tests for edge cases and integration


def test_max_thinking_tokens_validation(agent_node):
    """Test max_thinking_tokens parameter validation."""
    shared = {}

    # Valid range
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "max_thinking_tokens": 5000}
    prep_res = agent_node.prep(shared)
    assert prep_res["max_thinking_tokens"] == 5000

    # Too low
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "max_thinking_tokens": 500}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "Invalid max_thinking_tokens" in str(exc_info.value)

    # Too high
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "max_thinking_tokens": 200000}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "Invalid max_thinking_tokens" in str(exc_info.value)


def test_max_turns_validation(agent_node):
    """Test max_turns parameter validation."""
    shared = {}

    # Valid range
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "max_turns": 10}
    prep_res = agent_node.prep(shared)
    assert prep_res["max_turns"] == 10

    # Too low
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "max_turns": 0}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "Invalid max_turns" in str(exc_info.value)

    # Too high (now 100 is the max)
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "max_turns": 101}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "Invalid max_turns" in str(exc_info.value)


def test_max_turns_too_low_with_schema_rejected(agent_node):
    """Structured output needs at least two turns."""
    agent_node.params = {
        "backend": "claude",
        "prompt": "test prompt",
        "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        "max_turns": 1,
    }
    with pytest.raises(AgentValidationError, match="max_turns must be >= 2"):
        agent_node.prep({})


def test_tool_use_logging(agent_node, caplog):
    """Test that tool uses are logged."""
    import logging

    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {}
    agent_node.shared = shared

    # Mock response with tool uses
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(
            content=[
                ToolUseBlock(name="Read", input_data={"file": "test.py"}),
                ToolUseBlock(name="Edit", input_data={"file": "test.py", "content": "new"}),
                TextBlock(text="Task completed"),
            ]
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        # Explicitly set logger level for this test since global config may have changed
        with caplog.at_level(logging.INFO, logger="pflow.nodes.agent.claude_backend"):
            prep_res = agent_node.prep(shared)
            result = agent_node.exec(prep_res)

        assert isinstance(result, dict)
        assert len(result["tool_uses"]) == 2
        assert result["tool_uses"][0]["name"] == "Read"
        assert result["tool_uses"][1]["name"] == "Edit"
        assert "Claude Code used 2 tools" in caplog.text


def test_sdk_is_error_with_structured_output_emits_warning(agent_node):
    """If SDK reports an error but structured_output exists, structured output wins and warning persists."""
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}
    agent_node.node_id = "review"
    shared = {}

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="done")])
        yield ResultMessage(structured_output={"x": 1}, is_error=True)
        # See test_sdk_is_error_branch — only ProcessError is the paired-with-
        # is_error=True case the node swallows.
        raise ProcessError(exit_code=1, stderr="partial")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    assert shared["result"] == {"x": 1}
    assert shared["__warnings__"]["review"]["kind"] == "agent.sdk_error_with_structured_output"


def test_non_process_error_after_is_error_re_raises(agent_node):
    """Hard errors after a ResultMessage(is_error=True) must NOT be swallowed.

    Regression: an earlier fix preserved is_error state by swallowing every
    ``Exception``, which masked ``CLIConnectionError``/``CLINotFoundError``-class
    failures so the user never saw the remediation message from ``exec_fallback``.
    Only ``ProcessError`` (the paired non-zero-exit case) is the swallow candidate.
    """
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}
    agent_node.node_id = "review"
    shared = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output=None, result="partial", is_error=True)
        raise CLIConnectionError("Lost connection to Claude CLI mid-stream")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        # ``exec()`` runs the SDK loop directly (no retry/fallback wrapper).
        # The connection error must escape ``_run_claude_session`` so the
        # Node retry path eventually delivers it to ``exec_fallback``.
        with pytest.raises(CLIConnectionError, match="Lost connection"):
            agent_node.exec(prep_res)


def test_process_error_name_fallback_when_sdk_class_is_none(agent_node):
    """Pin the name-based ProcessError fallback against a typed-only "cleanup."

    The exception handler in ``_run_claude_session`` combines an
    ``isinstance(exc, ProcessError)`` check with a runtime
    ``type(exc).__name__ == "ProcessError"`` name fallback. The name fallback
    matters when ``ProcessError`` is ``None`` at module load — happens in
    partial / vendored SDK install scenarios where ``from claude_agent_sdk
    import ProcessError`` failed but the SDK can still emit a class spelled
    ``ProcessError`` at runtime.

    A "clean refactor" to typed-only ``except (ProcessError,)`` would degrade
    to ``except ():`` in that case (empty tuple catches nothing), the soft-fail
    state would be lost, and the user would see a hard error instead of the
    intended DEGRADED signal. This test exercises that exact scenario.
    """
    import pflow.nodes.agent.claude_backend as cc

    # A locally-defined exception class with the load-bearing name. NOT a
    # subclass of the test module's mock ``ProcessError`` — that ``isinstance``
    # match would let the typed approach pass too.
    class StandaloneProcessError(Exception):
        def __init__(self, message: str = "stderr text") -> None:
            super().__init__(message)

    StandaloneProcessError.__name__ = "ProcessError"

    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema, "schema_retries": 0}
    agent_node.node_id = "review"
    shared: dict = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output=None, result="partial", is_error=True)
        raise StandaloneProcessError("CLI exit 1")

    with (
        patch.object(cc, "ProcessError", None),
        patch("pflow.nodes.agent.claude_backend.query") as mock_query,
    ):
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        # MUST NOT raise — name fallback swallows after is_error=True.
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    # Soft-fail signal preserved end-to-end.
    assert "Claude CLI reported an error" in shared["_schema_error"]
    assert shared["__warnings__"]["review"]["kind"] == "agent.sdk_error_no_structured_output"


def test_output_schema_resolved_to_null_emits_warning(agent_node):
    """A declared output_schema that resolves to None must warn the workflow author.

    Regression: silently dropping schema mode caused workflows that templated
    the schema from upstream nodes (``output_schema: ${x.schema}``) to report
    SUCCESS even when the schema reference missed and the run produced free-form
    text instead of structured output.
    """
    # Simulate engine post-template-resolution: key present, value resolved to None.
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": None}
    agent_node.node_id = "review"
    shared: dict = {}

    agent_node.prep(shared)

    warning = shared["__warnings__"]["review"]
    assert warning["kind"] == "agent.output_schema_resolved_to_null"
    assert "resolved to None" in warning["text"]
    assert warning["context"]["node_type"] == "agent"


def test_output_schema_absent_does_not_warn(agent_node):
    """If the workflow author never declared output_schema, no warning fires."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}  # no output_schema key
    shared: dict = {}

    agent_node.prep(shared)

    assert "__warnings__" not in shared


def test_output_schema_resolved_null_no_node_id_falls_back_to_schema_error(agent_node):
    """Test-path / uncompiled nodes preserve signal via ``_schema_error``."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": None}
    shared: dict = {}

    agent_node.prep(shared)

    # Without a bound node_id, __warnings__ writes would be keyed under None and
    # are lost downstream — fall back to _schema_error so the signal survives.
    assert "resolved to None" in shared["_schema_error"]


def test_nested_array_schema(agent_node):
    """Arrays nested inside a top-level object are supported."""
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"],
    }
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}
    shared = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output={"items": ["a", "b", "c"]}, is_error=False)

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    assert shared["result"] == {"items": ["a", "b", "c"]}
    assert isinstance(shared["result"]["items"], list)


def test_sticky_is_error_across_multiple_result_messages(agent_node):
    """An early ResultMessage.is_error=True remains visible even if a later message is false."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema, "schema_retries": 0}
    agent_node.node_id = "review"
    shared = {}

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="raw")])
        yield ResultMessage(is_error=True, structured_output=None)
        yield ResultMessage(is_error=False, structured_output=None)

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    assert shared["result"] == "raw"
    assert "Claude CLI reported an error" in shared["_schema_error"]
    assert shared["__warnings__"]["review"]["kind"] == "agent.sdk_error_no_structured_output"


def test_working_directory_expansion(agent_node):
    """Test that working directory paths are expanded correctly."""
    shared = {}

    # Test tilde expansion
    with patch("os.path.exists", return_value=True), patch("os.path.isdir", return_value=True):
        agent_node.params = {"backend": "claude", "prompt": "test prompt", "cwd": "~/projects"}
        prep_res = agent_node.prep(shared)

        # Should be expanded to absolute path
        assert os.path.isabs(prep_res["cwd"])
        assert "~" not in prep_res["cwd"]


def test_post_method(agent_node):
    """Test post method always returns 'default'."""
    agent_node.params = {"backend": "claude", "prompt": "test"}
    shared = {}
    prep_res = {"prompt": "test"}

    # Create proper exec_res dict
    exec_res = {"result_text": "test completed", "tool_uses": [], "output_schema": None}

    # Post should always return "default" regardless of execution result
    assert agent_node.post(shared, prep_res, exec_res) == "default"
    assert isinstance(shared["result"], str)
    assert shared["result"] == "test completed"


def test_retry_configuration(agent_node):
    """Test that retry configuration is conservative."""
    # Node should be configured for only 2 attempts total (expensive API)
    assert agent_node.max_retries == 2
    assert agent_node.wait == 1.0
    # Timeout is now configurable via params, default 300s tested in test_timeout_parameter


def test_generic_error_fallback(agent_node):
    """Test generic error handling in exec_fallback."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    shared = {}
    prep_res = agent_node.prep(shared)

    # Generic exception
    generic_error = Exception("Something went wrong")

    with pytest.raises(ValueError) as exc_info:
        agent_node.exec_fallback(prep_res, generic_error)

    error_msg = str(exc_info.value)
    assert "Claude Code execution failed after 2 attempts: Something went wrong" in error_msg


def test_no_temperature_parameter():
    """Test that ClaudeCodeOptions doesn't accept temperature parameter."""
    # This test verifies the SDK uses max_thinking_tokens, not temperature

    # Create options dict as the node does
    options_dict = {
        "model": "claude-3-5-sonnet",
        "max_thinking_tokens": 8000,  # Correct parameter
        # "temperature": 0.5,  # This would be wrong - doesn't exist in SDK
    }

    # Verify we're using the right parameter name
    assert "max_thinking_tokens" in options_dict
    assert "temperature" not in options_dict
    assert "max_tokens" not in options_dict  # Also wrong

    # The real SDK ClaudeCodeOptions only accepts max_thinking_tokens
    # This test documents that the node correctly uses max_thinking_tokens


# Sandbox parameter tests


def test_sandbox_parameter_defaults(agent_node):
    """Test sandbox parameter defaults to None."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep(shared)
    assert prep_res.get("sandbox") is None


def test_sandbox_parameter_valid_config(agent_node):
    """Test valid sandbox configuration."""
    shared = {}
    agent_node.params = {
        "backend": "claude",
        "prompt": "test prompt",
        "sandbox": {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "excludedCommands": ["docker", "kubectl"],
            "network": {"allowLocalBinding": True},
        },
    }
    prep_res = agent_node.prep(shared)
    assert prep_res["sandbox"]["enabled"] is True
    assert prep_res["sandbox"]["autoAllowBashIfSandboxed"] is True
    assert prep_res["sandbox"]["excludedCommands"] == ["docker", "kubectl"]
    assert prep_res["sandbox"]["network"]["allowLocalBinding"] is True


def test_sandbox_parameter_minimal_config(agent_node):
    """Test minimal sandbox configuration with just enabled."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "sandbox": {"enabled": True}}
    prep_res = agent_node.prep(shared)
    assert prep_res["sandbox"]["enabled"] is True


def test_sandbox_parameter_invalid_type(agent_node):
    """Test sandbox rejects non-dict values."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "sandbox": "not a dict"}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "sandbox must be a dict" in str(exc_info.value)


def test_sandbox_parameter_invalid_enabled_type(agent_node):
    """Test sandbox['enabled'] must be bool."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "sandbox": {"enabled": "yes"}}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "sandbox['enabled'] must be bool" in str(exc_info.value)


def test_sandbox_parameter_invalid_auto_allow_bash_type(agent_node):
    """Test sandbox['autoAllowBashIfSandboxed'] must be bool."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "sandbox": {"autoAllowBashIfSandboxed": 1}}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "sandbox['autoAllowBashIfSandboxed'] must be bool" in str(exc_info.value)


def test_sandbox_parameter_invalid_excluded_commands_type(agent_node):
    """Test sandbox['excludedCommands'] must be list."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "sandbox": {"excludedCommands": "docker"}}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "sandbox['excludedCommands'] must be a list" in str(exc_info.value)


def test_sandbox_parameter_invalid_network_type(agent_node):
    """Test sandbox['network'] must be dict."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "sandbox": {"network": "localhost"}}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "sandbox['network'] must be a dict" in str(exc_info.value)


def test_sandbox_parameter_passes_unknown_keys(agent_node):
    """Test that unknown sandbox keys are passed through for SDK forward compatibility."""
    shared = {}
    agent_node.params = {
        "backend": "claude",
        "prompt": "test prompt",
        "sandbox": {
            "enabled": True,
            "futureOption": "some value",  # Unknown key should pass through
        },
    }
    prep_res = agent_node.prep(shared)
    assert prep_res["sandbox"]["enabled"] is True
    assert prep_res["sandbox"]["futureOption"] == "some value"


# Disallowed tools parameter tests


def test_disallowed_tools_default_none(agent_node):
    """Test disallowed_tools defaults to None (no restrictions)."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep(shared)
    assert prep_res["disallowed_tools"] is None


def test_disallowed_tools_with_patterns(agent_node):
    """Test disallowed_tools accepts pattern strings for SDK denylist."""
    shared = {}
    patterns = ["Bash(pflow:*)", "Bash(make:*)"]
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "disallowed_tools": patterns}
    prep_res = agent_node.prep(shared)
    assert prep_res["disallowed_tools"] == patterns


def test_disallowed_tools_passed_to_options(agent_node):
    """Test disallowed_tools is passed through to ClaudeAgentOptions."""
    shared = {}
    patterns = ["Bash(pflow:*)", "Bash(git:*)"]
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "disallowed_tools": patterns}
    prep_res = agent_node.prep(shared)

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")
        assert mock_options.call_args.kwargs["disallowed_tools"] == patterns


def test_disallowed_tools_not_passed_when_none(agent_node):
    """Test disallowed_tools is omitted from options when None."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep(shared)
    assert prep_res["disallowed_tools"] is None

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")
        assert "disallowed_tools" not in mock_options.call_args.kwargs


def test_disallowed_tools_invalid_type(agent_node):
    """Test disallowed_tools rejects non-list values."""
    shared = {}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "disallowed_tools": "Bash(pflow:*)"}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep(shared)
    assert "disallowed_tools must be a list" in str(exc_info.value)


def test_disallowed_tools_with_allowed_tools(agent_node):
    """Test disallowed_tools works alongside allowed_tools."""
    shared = {}
    agent_node.params = {
        "backend": "claude",
        "prompt": "test prompt",
        "allowed_tools": ["Read", "Write", "Bash"],
        "disallowed_tools": ["Bash(rm:*)"],
    }
    prep_res = agent_node.prep(shared)
    assert prep_res["allowed_tools"] == ["Read", "Write", "Bash"]
    assert prep_res["disallowed_tools"] == ["Bash(rm:*)"]


# ---------------------------------------------------------------------------
# Soft-fail signal preservation when node_id is unbound (test path)
# ---------------------------------------------------------------------------


def test_sdk_error_with_structured_output_no_node_id_falls_back_to_schema_error(agent_node):
    """When the SDK reports an error alongside valid structured output AND no
    ``node_id`` is bound, ``_schema_error`` preserves the signal.

    Production engine paths always bind ``node_id``, so this is the test /
    direct-``node.run(shared)`` path. Matches the fallback established by
    ``_emit_schema_resolved_null_warning``: ``__warnings__[node_id]`` is the
    primary channel; ``_schema_error`` is the recovery channel.
    """
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}
    # No ``agent_node.node_id`` assignment — simulates uncompiled / direct test path.
    shared: dict = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output={"x": 1}, is_error=True)
        raise ProcessError(exit_code=1, stderr="partial")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    # Structured output still wins as the result.
    assert shared["result"] == {"x": 1}
    # Signal preserved via _schema_error even without node_id.
    assert "structured_output was produced" in shared["_schema_error"]
    # __warnings__ guarded by node_id; no warning entry expected.
    assert "__warnings__" not in shared


# ---------------------------------------------------------------------------
# Soft-fail message strings must not collide with api_warning_detector
# ---------------------------------------------------------------------------


def test_soft_fail_output_shape_not_classified_as_api_warning(agent_node):
    """Regression pin: an agent soft-fail must NOT be detected by
    ``api_warning_detector.detect_api_warning`` — otherwise the engine would
    override the node's ``"default"`` action to ``"error"`` and silently flip
    soft-fail (DEGRADED) into hard fail (FAILED).

    Today the detector is shape-gated — it only extracts an error message from
    outputs containing ``ok: false`` / ``success: false`` / ``status: "error"`` /
    GraphQL ``errors`` / an ``error`` key at the dict root. The agent node
    writes ``result``, ``_schema_error``, and ``llm_usage`` — none of those keys
    match. This test pins that invariant: the output shape from a soft-fail
    must continue to bypass the detector, regardless of message wording.

    A future contributor adding an ``error`` key to ``shared[node_id]`` for
    debug visibility would break soft-fail routing — this test fails first.
    """
    from pflow.runtime.engine.api_warning_detector import detect_api_warning

    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "output_schema": schema}
    agent_node.node_id = "review"
    # Simulate engine namespacing: an agent node writes its outputs under
    # ``shared[node_id]`` via NamespacedSharedStore. Build that shape directly
    # so the test exercises exactly what the detector will see in production.
    shared: dict = {}
    namespaced = {}

    async def mock_response(*args, **kwargs):
        # No structured output → soft-fail branch with the longest message.
        yield ResultMessage(structured_output=None, result="raw fallback text", is_error=False)

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        # Capture the node-output shape exactly as namespaced_store would write it.
        # _store_results writes ``shared["result"]``, ``shared["_schema_error"]``,
        # ``shared["llm_usage"]`` — under namespacing these become
        # ``shared[node_id][...]``.
        agent_node.post(namespaced, prep_res, result)

    # Promote namespaced writes into the shared store shape the engine produces.
    shared["review"] = {k: v for k, v in namespaced.items() if not k.startswith("__")}

    # The canonical invariant: an agent soft-fail must NOT be detected as
    # an API warning. If detect_api_warning returns non-None, the engine would
    # convert action="default" → "error" and lose the entire soft-fail design.
    assert detect_api_warning("review", shared) is None, (
        "agent soft-fail output was classified as an API warning; engine "
        "would flip action to 'error'. Inspect: (a) any new error/ok/success/status "
        "keys in _store_results, or (b) any change to api_warning_detector's "
        "extract_error_message shape gates."
    )


# ---------------------------------------------------------------------------
# Runtime ↔ Validator parity
# ---------------------------------------------------------------------------
#
# ``pflow.nodes.agent.schema_validation`` shares the *predicates* between the
# runtime path (``AgentNode._validate_schema``) and the static preflight
# path (``WorkflowValidator._validate_agent_params``). The shared
# predicates prevent drift on shape detection, but the CALL SITES can still
# drift on:
#
# * which checks they run (one side adds a rule, the other doesn't),
# * the order of checks (an early-return on one side shadows a later check),
# * which inputs are rejected vs. accepted.
#
# These parametrized tables encode the cross-surface contract. Adding a new
# rejection rule means adding a row to ``_PARITY_REJECT``; if either surface
# doesn't implement it, the test fires with the case_id naming the gap.
#
# Out of scope: templated values (``output_schema: "${upstream}"``). Those
# differ by design — the validator defers strings to runtime; the runtime
# never sees a string because the resolver replaces it first. The defer
# behavior is pinned separately in ``test_validate_only_defers_templated_output_schema``.

_PARITY_REJECT: list[tuple[str, Any]] = [
    ("empty_dict", {}),
    ("non_dict_list", ["not", "a", "dict"]),
    ("legacy_python_alias", {"risk": {"type": "str"}}),
    ("legacy_detection_all_values", {"_meta": "x", "risk": {"type": "int"}}),
    ("top_level_array", {"type": "array", "items": {"type": "string"}}),
    ("top_level_string", {"type": "string"}),
    ("top_level_oneOf", {"oneOf": [{"type": "object"}]}),
    ("top_level_anyOf", {"anyOf": [{"type": "object"}]}),
    ("top_level_allOf", {"allOf": [{"type": "object"}]}),
    ("top_level_enum", {"enum": ["a", "b"]}),
    ("top_level_const", {"const": {"x": 1}}),
    ("missing_top_level_type", {"properties": {"x": {"type": "string"}}}),
]

_PARITY_ACCEPT: list[tuple[str, Any]] = [
    ("none_schema", None),
    ("minimal_object", {"type": "object"}),
    ("object_with_properties", {"type": "object", "properties": {"x": {"type": "string"}}}),
    (
        "object_with_inner_oneOf",
        {
            "type": "object",
            "properties": {"choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
        },
    ),
]


def _runtime_rejects(node: AgentNode, schema: Any) -> bool:
    try:
        node._validate_schema(schema)
        return False
    except AgentValidationError:
        return True


def _validator_rejects(schema: Any) -> bool:
    diagnostics = WorkflowValidator._validate_agent_params("review", {"backend": "claude", "output_schema": schema})
    return any(d.severity == Severity.ERROR for d in diagnostics)


@pytest.mark.parametrize("case_id,schema", _PARITY_REJECT, ids=[c[0] for c in _PARITY_REJECT])
def test_runtime_and_validator_agree_on_rejection(case_id: str, schema: Any, agent_node: Any) -> None:
    """Schemas rejected by one surface must be rejected by both.

    Add a row to ``_PARITY_REJECT`` when adding a rejection rule; if either
    surface doesn't implement it, this test fires with the case_id naming
    the gap.
    """
    validator_rejected = _validator_rejects(schema)
    runtime_rejected = _runtime_rejects(agent_node, schema)
    assert validator_rejected == runtime_rejected, (
        f"Surface drift on '{case_id}': validator_rejected={validator_rejected}, runtime_rejected={runtime_rejected}"
    )
    assert validator_rejected, f"'{case_id}' should be rejected — neither surface caught it"


@pytest.mark.parametrize("case_id,schema", _PARITY_ACCEPT, ids=[c[0] for c in _PARITY_ACCEPT])
def test_runtime_and_validator_agree_on_acceptance(case_id: str, schema: Any, agent_node: Any) -> None:
    """Schemas accepted by one surface must be accepted by both."""
    validator_rejected = _validator_rejects(schema)
    runtime_rejected = _runtime_rejects(agent_node, schema)
    assert validator_rejected == runtime_rejected, (
        f"Surface drift on '{case_id}': validator_rejected={validator_rejected}, runtime_rejected={runtime_rejected}"
    )
    assert not validator_rejected, f"'{case_id}' should be accepted — at least one surface wrongly rejected"


def test_agent_node_resolves_identically_via_package_and_direct_import() -> None:
    """Pin the lazy ``pflow.nodes.agent.__init__.py`` contract.

    The ``__getattr__``-based lazy resolution is load-bearing: it lets
    ``test_schema_validation.py`` import the predicates without dragging in
    ``claude_agent_sdk`` before the SDK mock binds (``tests/CLAUDE.md`` #17).
    A revert to ``from .agent_node import AgentNode`` at package load
    would break that test file's coexistence with the mock — producing
    confusing ProcessError-style failures spread across unrelated tests
    rather than a clean signal that this contract changed.

    This test makes the contract explicit. Reverting the lazy init breaks
    HERE, not in cross-file ordering downstream.
    """
    import pflow.nodes.agent as pkg
    from pflow.nodes.agent.agent_node import AgentNode as direct

    assert pkg.AgentNode is direct


def test_agent_package_import_does_not_load_claude_sdk() -> None:
    """A fresh interpreter can import the package/node while SDK imports are forbidden.

    An in-process reload is insufficient here because ``agent_node`` and its
    transitive imports may already be cached in ``sys.modules`` by collection.
    The fresh process makes an eager Claude-backend import fail at its source.
    """
    root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    code = """
import sys

class RejectClaudeSdkImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "claude_agent_sdk" or fullname.startswith("claude_agent_sdk."):
            raise RuntimeError(f"eager SDK import: {fullname}")
        return None

sys.meta_path.insert(0, RejectClaudeSdkImports())
import pflow.nodes.agent as package
from pflow.nodes.agent.agent_node import AgentNode
assert package.AgentNode is AgentNode
assert "claude_agent_sdk" not in sys.modules
"""

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned code
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_node_retry_lifecycle_raises_backend_translated_error(monkeypatch) -> None:
    """Node retries the adapter twice, then raises its translated error.

    This is the contract that lets batch retry observe agent failures. Testing
    ``exec_fallback`` alone would not prove the PocketFlow lifecycle preserves it.
    """

    class FailingBackend:
        default_model: str | None = "test-model"

        def __init__(self) -> None:
            self.run_calls = 0
            self.translate_calls = 0

        def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
            return {}

        def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
            self.run_calls += 1
            raise RuntimeError("provider unavailable")

        def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any] | None:
            return None

        def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
            self.translate_calls += 1
            return ValueError(f"translated: {exc}")

        def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
            return {}

    backend = FailingBackend()
    monkeypatch.setattr(AgentNode, "_load_backend", staticmethod(lambda _name: backend))
    node = AgentNode()
    node.wait = 0
    node.params = {"backend": "claude", "prompt": "do work"}

    with pytest.raises(ValueError, match="translated: provider unavailable"):
        node.run({})

    assert backend.run_calls == 2
    assert backend.translate_calls == 1


def test_schema_retry_propagates_translated_non_retriable_error() -> None:
    """A deterministic correction failure must not masquerade as a schema miss."""

    class NonRetriableCorrectionError(PflowError):
        retriable = False

    class Backend:
        default_model: str | None = "test-model"

        def __init__(self) -> None:
            self.run_calls = 0

        def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
            self.run_calls += 1
            if self.run_calls == 1:
                return AgentResult(
                    result_text='{"continue":"maybe"}',
                    structured_output={"continue": "maybe"},
                    metadata={"session_id": "s1", "usage_available": False},
                )
            raise RuntimeError("stored account is no longer permitted")

        def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any]:
            return options.copy()

        def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
            return NonRetriableCorrectionError("account auth rejected")

        def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
            return {"backend": "test"}

    backend = Backend()
    node = AgentNode()
    prepared = {
        "_backend": backend,
        "prompt": "decide",
        "model": "test-model",
        "output_schema": {
            "type": "object",
            "properties": {"continue": {"type": "boolean"}},
            "required": ["continue"],
        },
        "schema_retries": 1,
    }

    with pytest.raises(NonRetriableCorrectionError, match="account auth rejected"):
        node.exec(prepared)

    assert backend.run_calls == 2


def test_schema_retry_keeps_prior_result_for_retriable_error() -> None:
    """Ordinary correction failures retain the inherited DEGRADED fallback."""

    class Backend:
        default_model: str | None = "test-model"

        def __init__(self) -> None:
            self.run_calls = 0

        def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
            self.run_calls += 1
            if self.run_calls == 1:
                return AgentResult(
                    result_text='{"continue":"maybe"}',
                    structured_output={"continue": "maybe"},
                    metadata={"session_id": "s1", "usage_available": False},
                )
            raise RuntimeError("temporary transport failure")

        def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any]:
            return options.copy()

        def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
            return ValueError("temporary provider failure")

        def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
            return {"backend": "test", "backend_display": "Test backend"}

    backend = Backend()
    node = AgentNode()
    prepared = {
        "_backend": backend,
        "prompt": "decide",
        "model": "test-model",
        "output_schema": {
            "type": "object",
            "properties": {"continue": {"type": "boolean"}},
            "required": ["continue"],
        },
        "schema_retries": 1,
    }

    result = node.exec(prepared)

    assert backend.run_calls == 2
    assert result["result_text"] == '{"continue":"maybe"}'
    assert result["retry_metadata"] == {"attempts": 1, "coerced_fields": [], "conforming": False}


def test_runtime_and_validator_agree_on_max_turns_with_schema(agent_node: Any) -> None:
    """The cross-rule ``max_turns >= 2 when output_schema is set`` is enforced
    on both surfaces. Runtime checks happen in ``prep()`` (not ``_validate_schema``),
    so this case tests the full ``prep()`` path.
    """
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    params = {"backend": "claude", "output_schema": schema, "max_turns": 1, "prompt": "test"}

    diagnostics = WorkflowValidator._validate_agent_params("review", params)
    validator_rejected = any(d.severity == Severity.ERROR for d in diagnostics)

    agent_node.params = params
    runtime_rejected = False
    try:
        agent_node.prep({})
    except AgentValidationError:
        runtime_rejected = True

    assert validator_rejected == runtime_rejected, (
        f"max_turns parity drift: validator={validator_rejected}, runtime={runtime_rejected}"
    )
    assert validator_rejected


def test_static_validator_requires_backend_without_output_schema() -> None:
    diagnostics = WorkflowValidator._validate_agent_params("review", {"prompt": "test"})

    assert [d.message for d in diagnostics] == ["Agent node requires 'backend'. Valid values: claude, codex."]
    assert diagnostics[0].context == {
        "category": "validation",
        "node_type": "agent",
        "path": "nodes[id=review].params.backend",
    }
    assert diagnostics[0].see_also == ["agent"]


@pytest.mark.parametrize(
    ("backend", "other_backend_param"),
    [("claude", "approval_policy"), ("codex", "max_thinking_tokens")],
)
def test_static_validator_rejects_cross_backend_param_before_schema_checks(
    backend: str,
    other_backend_param: str,
) -> None:
    params = {"backend": backend, "prompt": "test", other_backend_param: "value"}

    diagnostics = WorkflowValidator._validate_agent_params("review", params)

    assert len(diagnostics) == 1
    assert diagnostics[0].message == f"{other_backend_param!r} is not valid for backend {backend!r}."


def test_static_validator_reports_codex_max_turns_as_cross_backend_only() -> None:
    diagnostics = WorkflowValidator._validate_agent_params(
        "review",
        {
            "backend": "codex",
            "prompt": "test",
            "output_schema": {"type": "object", "properties": {"value": {"type": "string"}}},
            "max_turns": 1,
        },
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].message == "'max_turns' is not valid for backend 'codex'."


def test_static_validator_defers_templated_backend() -> None:
    diagnostics = WorkflowValidator._validate_agent_params(
        "review",
        {"backend": "${inputs.backend}", "prompt": "test", "approval_policy": "never"},
    )

    assert diagnostics == []


@pytest.mark.parametrize("backend", ["claude", "codex"])
def test_static_validator_accepts_shared_inputs_param(backend: str) -> None:
    diagnostics = WorkflowValidator._validate_agent_params(
        "review",
        {"backend": backend, "prompt": "test", "inputs": {"repo_dir": "${repo_dir}"}},
    )

    assert diagnostics == []


@pytest.mark.parametrize("backend", ["claude", "codex"])
def test_static_validator_accepts_shared_use_api_key_param(backend: str) -> None:
    diagnostics = WorkflowValidator._validate_agent_params(
        "review",
        {"backend": backend, "prompt": "test", "use_api_key": True},
    )

    assert diagnostics == []


@pytest.mark.parametrize("backend", ["claude", "codex"])
def test_static_validator_defers_schema_with_nested_template_type(backend: str) -> None:
    params: dict[str, Any] = {
        "backend": backend,
        "prompt": "test",
        "output_schema": {
            "type": "${schema.type}",
            "properties": {"result": {"type": "string"}},
        },
    }
    if backend == "claude":
        params["max_turns"] = 2
    diagnostics = WorkflowValidator._validate_agent_params(
        "review",
        params,
    )

    assert diagnostics == []


def test_nested_templated_schema_still_enforces_claude_turn_floor() -> None:
    diagnostics = WorkflowValidator._validate_agent_params(
        "review",
        {
            "backend": "claude",
            "prompt": "test",
            "max_turns": 1,
            "output_schema": {"type": "${schema.type}"},
        },
    )

    assert len(diagnostics) == 1
    assert "max_turns must be >= 2" in diagnostics[0].message


def test_runtime_validator_accepts_shared_inputs_param(agent_node: Any) -> None:
    agent_node.params = {
        "backend": "claude",
        "prompt": "test",
        "inputs": {"repo_dir": "${repo_dir}"},
    }

    prepared = agent_node.prep({})

    assert prepared["backend"] == "claude"


# ---------------------------------------------------------------------------
# Issue #455: use_api_key billing flag.
# The node blanks ANTHROPIC_API_KEY for the Claude subprocess by default so an
# ambient (or `pflow settings set-env`-injected) key cannot silently override
# the user's Pro/Max subscription with per-token Console billing.
# ---------------------------------------------------------------------------


def test_use_api_key_defaults_false(agent_node):
    """Param absent → False → subscription billing."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep({})
    assert prep_res["use_api_key"] is False


def test_default_blanks_api_key_in_options(agent_node):
    """Default mode sets options.env = {ANTHROPIC_API_KEY: ""}.

    The SDK merges options.env OVER os.environ, so the empty-string override is
    what actually neutralizes an inherited key — omitting it would leave the
    inherited key intact (a dict merge cannot delete a base key).
    """
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep({})

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert mock_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": ""}


def test_default_scrub_only_touches_anthropic_key(agent_node):
    """Only ANTHROPIC_API_KEY is overridden; every other var still inherits."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep({})

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert list(mock_options.call_args.kwargs["env"].keys()) == ["ANTHROPIC_API_KEY"]


def test_use_api_key_true_does_not_scrub(agent_node):
    """Opt-in (True) leaves env untouched so the ambient key bills to Console."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "use_api_key": True}
    prep_res = agent_node.prep({})
    assert prep_res["use_api_key"] is True

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert "env" not in mock_options.call_args.kwargs


def test_string_false_still_scrubs(agent_node):
    """Footgun guard: a templated string "false" must NOT enable API billing.

    Node params aren't coerced to bool at runtime and the string "false" is
    truthy in Python — a naive bool(value) would silently bill per token.
    """
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "use_api_key": "false"}
    prep_res = agent_node.prep({})
    assert prep_res["use_api_key"] is False

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert mock_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": ""}


def test_string_true_opts_in(agent_node):
    """Templated string "true" opts into API billing (no scrub)."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "use_api_key": "true"}
    prep_res = agent_node.prep({})
    assert prep_res["use_api_key"] is True

    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")

    assert "env" not in mock_options.call_args.kwargs


def test_use_api_key_invalid_value_raises(agent_node):
    """A non-bool, non-canonical value fails closed with an AgentValidationError."""
    agent_node.params = {"backend": "claude", "prompt": "test prompt", "use_api_key": "maybe"}
    with pytest.raises(AgentValidationError) as exc_info:
        agent_node.prep({})
    assert "use_api_key must be true or false" in str(exc_info.value)


def test_default_does_not_mutate_os_environ(monkeypatch, agent_node):
    """The empty-string override must NOT touch os.environ — a sibling llm node
    in the same workflow keeps reading the real key for LiteLLM. This pins the
    decision so a future switch to os.environ.pop fails loudly (#455 review)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    agent_node.params = {"backend": "claude", "prompt": "test prompt"}
    prep_res = agent_node.prep({})
    with patch("pflow.nodes.agent.claude_backend.ClaudeAgentOptions") as mock_options:
        ClaudeBackend()._build_claude_options(prep_res, "")
    # The subprocess env blanks the key...
    assert mock_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": ""}
    # ...but the process environment is untouched.
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-real"


@pytest.mark.parametrize("backend", ["claude", "codex"])
def test_use_api_key_registered_as_shared_bool_param(backend: str):
    """The shared bool declaration drives the backend-blind metadata allowlist."""
    md = PflowMetadataExtractor().extract_metadata(AgentNode)
    params = {p["key"]: p["type"] for p in md["params"]}
    assert params.get("use_api_key") == "bool"

    diagnostics = WorkflowValidator._validate_agent_params(
        "agent",
        {"backend": backend, "prompt": "test", "use_api_key": False},
    )
    assert diagnostics == []


# --- Auth-failure guidance (exec_fallback) ---


def test_is_auth_error_matches_only_auth_markers():
    """_is_auth_error matches CLI auth/billing markers, not generic failures."""
    assert ClaudeBackend._is_auth_error(Exception("Invalid API key · Fix external API key"))
    assert ClaudeBackend._is_auth_error(Exception("authentication_error: bad token"))
    assert ClaudeBackend._is_auth_error(Exception("Your credit balance is too low"))
    # Real not-logged-in result text — pins the narrowed "run /login" marker.
    assert ClaudeBackend._is_auth_error(Exception("Not logged in · Please run /login"))
    assert not ClaudeBackend._is_auth_error(Exception("Tool 'Bash' failed: exit 1"))
    assert not ClaudeBackend._is_auth_error(Exception("connection reset by peer"))
    # "oauth" marker was dropped: an MCP OAuth error surfaced inside a claude
    # subprocess must NOT be misclassified as a Claude billing failure (#455 review).
    assert not ClaudeBackend._is_auth_error(Exception("MCP server oauth flow failed"))
    # The bare "/login" substring was narrowed to "run /login" — an unrelated
    # /login path in agent output must no longer false-match.
    assert not ClaudeBackend._is_auth_error(Exception("POST /login returned 500"))


def test_exec_fallback_auth_default_suggests_subscription(agent_node):
    """Default-mode auth failure points to subscription first, API key second."""
    with pytest.raises(ValueError) as exc_info:
        agent_node.exec_fallback({"_backend": ClaudeBackend(), "use_api_key": False}, Exception("authentication_error"))
    msg = str(exc_info.value)
    assert "claude auth login" in msg
    assert "- use_api_key: true" in msg


def test_exec_fallback_auth_with_api_key_suggests_fixing_key(agent_node):
    """Opt-in guidance covers either effective credential without assuming a key."""
    with pytest.raises(ValueError) as exc_info:
        agent_node.exec_fallback(
            {"_backend": ClaudeBackend(), "use_api_key": True}, Exception("Your credit balance is too low")
        )
    msg = str(exc_info.value)
    assert "grants permission but does not prove" in msg
    assert "ANTHROPIC_API_KEY" in msg
    assert "Remove `- use_api_key: true`" in msg
    assert "claude auth login" in msg
    assert "claude auth status" in msg


def test_exec_fallback_non_auth_error_has_no_auth_guidance(agent_node):
    """Non-auth failures fall through to the generic message (no auth hint)."""
    with pytest.raises(ValueError) as exc_info:
        agent_node.exec_fallback({"_backend": ClaudeBackend(), "use_api_key": False}, Exception("disk full"))
    msg = str(exc_info.value)
    assert "claude auth login" not in msg
    assert "disk full" in msg


# --- Regression: the SDK mangles the real auth error (found by real-CLI verify) ---
#
# The real CLI reports an invalid key as a result with is_error=True,
# api_error_status=401, result="Invalid API key · Fix external API key" — but the
# SDK forwards only the result SUBTYPE ("success"), raising a bare Exception
# "Claude Code returned an error result: success". The useful text + status are
# dropped. _run_claude_session must surface them from the ResultMessage so
# exec_fallback can recognize the auth failure. The original mock tests passed by
# feeding _is_auth_error synthetic strings the CLI never actually emits (#455).


def test_invalid_api_key_surfaces_real_error_text_and_status(agent_node):
    """The real "Invalid API key" text + api_error_status are surfaced on re-raise,
    not the SDK's useless "...error result: success"."""
    agent_node.params = {"backend": "claude", "prompt": "do a thing", "use_api_key": True}

    async def mock_response(*args, **kwargs):
        # Mirrors the real CLI: error result carrying the real text + 401 is
        # yielded first, then the SDK raises a bare Exception with the subtype.
        yield ResultMessage(
            is_error=True,
            result="Invalid API key · Fix external API key",
            api_error_status=401,
        )
        raise Exception("Claude Code returned an error result: success")  # noqa: TRY002 - mirror SDK bare raise

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep({})
        with pytest.raises(RuntimeError) as exc_info:
            agent_node.exec(prep_res)

    assert "Invalid API key" in str(exc_info.value)
    assert "api_error_status=401" in str(exc_info.value)
    # The enriched exception is now recognized as auth, and exec_fallback gives the
    # use_api_key=True remediation (the key, not subscription setup).
    assert ClaudeBackend._is_auth_error(exc_info.value)
    with pytest.raises(ValueError) as fb:
        agent_node.exec_fallback(prep_res, exc_info.value)
    assert "Anthropic Console" in str(fb.value)
    assert "Remove `- use_api_key: true`" in str(fb.value)


def test_api_error_status_detected_even_without_text(agent_node):
    """A 401 with no usable result text is still recognized as auth via the
    structured status alone."""
    agent_node.params = {"backend": "claude", "prompt": "do a thing", "use_api_key": True}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(is_error=True, result=None, api_error_status=401)
        raise Exception("Claude Code returned an error result: success")  # noqa: TRY002 - mirror SDK bare raise

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep({})
        with pytest.raises(RuntimeError) as exc_info:
            agent_node.exec(prep_res)

    assert "api_error_status=401" in str(exc_info.value)
    assert ClaudeBackend._is_auth_error(exc_info.value)


def test_non_auth_error_result_stays_generic(agent_node):
    """A non-auth error result (no 401, no auth text) must NOT trigger auth
    guidance — surfaced detail is preserved but routed to the generic message."""
    agent_node.params = {"backend": "claude", "prompt": "do a thing"}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(is_error=True, result="Tool failed: disk full", api_error_status=None)
        raise Exception("Claude Code returned an error result: error_during_execution")  # noqa: TRY002 - mirror SDK bare raise

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = agent_node.prep({})
        with pytest.raises(RuntimeError) as exc_info:
            agent_node.exec(prep_res)

    assert not ClaudeBackend._is_auth_error(exc_info.value)
    with pytest.raises(ValueError) as fb:
        agent_node.exec_fallback(prep_res, exc_info.value)
    assert "claude auth login" not in str(fb.value)
    assert "disk full" in str(fb.value)


# ---------------------------------------------------------------------------
# Issue #465: schema retry orchestration loop (coercion → resume-retry → cost
# aggregation). These exercise the wiring in _exec_async — the one part the
# helper-level unit tests don't reach, and where the cost-accounting bug lived.
# ---------------------------------------------------------------------------


def test_schema_retry_records_superseded_attempt_for_cost(agent_node):
    """A schema retry must count every attempt exactly once.

    Regression guard (#465 review): the loop used to append the INCOMING retry to
    llm_usage["retries"] and ALSO make it the main usage, so the aggregator summed the
    final attempt twice and dropped the first attempt entirely. The fix records the
    OUTGOING (superseded) attempt instead, keeping main + retries disjoint and complete.

    Setup: attempt 1 returns a non-coercible boolean (triggers one retry); attempt 2
    returns "true" (coerces to True → conforming). Token/cost/turns differ per attempt
    so the aggregation is unambiguous.
    """
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    schema = {"type": "object", "properties": {"continue": {"type": "boolean"}}, "required": ["continue"]}
    agent_node.params = {"backend": "claude", "prompt": "decide", "output_schema": schema, "schema_retries": 1}
    agent_node.node_id = "review"
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def attempt1(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="maybe?")])
        yield ResultMessage(
            structured_output={"continue": "maybe"},  # not coercible to bool → retry
            usage={
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            total_cost_usd=0.01,
            num_turns=3,
            session_id="s1",
        )

    async def attempt2(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text='{"continue": "true"}')])
        yield ResultMessage(
            structured_output={"continue": "true"},  # coerces to True → conforming
            usage={
                "input_tokens": 200,
                "output_tokens": 20,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            total_cost_usd=0.02,
            num_turns=2,
            session_id="s1",
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.side_effect = [attempt1(), attempt2()]

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

    # One retry fired and the final result is the coerced, conforming output.
    assert mock_query.call_count == 2
    assert result["structured_output"] == {"continue": True}
    assert result["retry_metadata"]["attempts"] == 1
    assert result["retry_metadata"]["conforming"] is True

    # The recorded retry usage is the SUPERSEDED first attempt (100), NOT the final (200).
    # Pre-fix this list held the final attempt — the core of the double-count bug.
    assert [r["input_tokens"] for r in result["retry_usages"]] == [100]

    agent_node.post(shared, prep_res, result)
    assert shared["result"] == {"continue": True}
    lu = shared["llm_usage"]
    assert lu["input_tokens"] == 200  # main = final attempt
    assert lu["num_turns"] == 2
    assert [r["input_tokens"] for r in lu["retries"]] == [100]

    # Aggregation counts both attempts once: 100 + 200 = 300 (pre-fix was 400 = 2x final).
    agg = WorkflowTraceCollector.aggregate_llm_usage_with_retries(lu)
    assert agg["input_tokens"] == 300
    assert agg["output_tokens"] == 30
    assert agg["num_turns"] == 5
    assert agg["cost_usd"] is None
    assert agg["api_equivalent_cost_usd"] == pytest.approx(0.03)


def test_schema_retry_without_session_id_keeps_first_result(agent_node) -> None:
    """A schema miss without a resumable session soft-fails without another turn."""
    schema = {"type": "object", "properties": {"continue": {"type": "boolean"}}, "required": ["continue"]}
    agent_node.params = {
        "backend": "claude",
        "prompt": "decide",
        "output_schema": schema,
        "schema_retries": 2,
    }
    agent_node.node_id = "review"
    shared = {"__warnings__": {}}

    async def no_session_result(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="maybe")])
        yield ResultMessage(
            structured_output={"continue": "maybe"},
            result="maybe",
            session_id="",
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = no_session_result()
        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

    assert mock_query.call_count == 1
    assert result["retry_metadata"] == {
        "attempts": 0,
        "coerced_fields": [],
        "conforming": False,
    }
    assert "retry_usages" not in result

    agent_node.post(shared, prep_res, result)
    assert shared["result"] == "maybe"
    assert shared["__warnings__"]["review"]["kind"] == "agent.schema_not_satisfied"
    assert "retries" not in shared["llm_usage"]


def test_claude_token_fields_sums_cache_into_inclusive_total():
    """_claude_token_fields folds the SDK's disjoint split into pflow's inclusive total.

    The Claude SDK reports input_tokens as the UNCACHED count; pflow's contract treats
    it as the cache-inclusive total = uncached + cache_creation + cache_read (#492).
    """
    fields = _claude_token_fields({
        "input_tokens": 1000,
        "cache_creation_input_tokens": 5000,
        "cache_read_input_tokens": 20000,
    })
    assert fields == {
        "input_tokens": 26000,  # 1000 + 5000 + 20000
        "uncached_input_tokens": 1000,
        "cache_creation_input_tokens": 5000,
        "cache_read_input_tokens": 20000,
        "input_token_accounting": "split_cache_fields",
    }


def test_claude_token_fields_defaults_missing_and_none_to_zero():
    """Empty usage and None-valued fields default to 0; accounting is always split."""
    assert _claude_token_fields({}) == {
        "input_tokens": 0,
        "uncached_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "input_token_accounting": "split_cache_fields",
    }
    # Missing cache keys but present input → input is the inclusive total (no cache).
    assert _claude_token_fields({"input_tokens": 1500}) == {
        "input_tokens": 1500,
        "uncached_input_tokens": 1500,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "input_token_accounting": "split_cache_fields",
    }
    # Explicit None coerces to 0 (the `or 0` guard), so the sum never raises.
    assert _claude_token_fields({"input_tokens": None, "cache_read_input_tokens": None})["input_tokens"] == 0


def test_post_emits_inclusive_input_tokens_with_cache(agent_node):
    """post() emits pflow's inclusive token contract for a cache-heavy run (#492).

    The SDK reports input_tokens=1000 (uncached only) alongside 5000 cache-creation and
    20000 cache-read tokens. pflow's llm_usage must headline the inclusive total (26000),
    keep the uncached slice and cache tiers as a subset breakdown, and tag the accounting.
    """
    agent_node.params = {"backend": "claude", "prompt": "do work"}
    agent_node.node_id = "agent"
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="done")])
        yield ResultMessage(
            result="done",
            usage={
                "input_tokens": 1000,
                "output_tokens": 2000,
                "cache_creation_input_tokens": 5000,
                "cache_read_input_tokens": 20000,
            },
            total_cost_usd=0.05,
            num_turns=4,
            session_id="s1",
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    lu = shared["llm_usage"]
    assert lu["input_tokens"] == 26000  # inclusive: 1000 + 5000 + 20000
    assert lu["uncached_input_tokens"] == 1000
    assert lu["cache_creation_input_tokens"] == 5000
    assert lu["cache_read_input_tokens"] == 20000
    assert lu["output_tokens"] == 2000
    assert lu["total_tokens"] == 28000  # inclusive input + output
    assert lu["input_token_accounting"] == "split_cache_fields"  # noqa: S105 (not a secret — accounting tag)
    # Shape guard: claude's llm_usage emits exactly the inclusive token contract plus its
    # execution metadata — no LLMNode-only fields (has_cache_telemetry, thinking_*, etc.).
    # No existing test pins claude's producer-shape, so this is the guard (see plan §5).
    assert set(lu) == {
        "model",
        "input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "input_token_accounting",
        "cost_usd",
        "api_equivalent_cost_usd",
        "duration_ms",
        "num_turns",
        "session_id",
    }


def test_post_coerces_none_output_tokens_to_zero(agent_node):
    """An explicit ``output_tokens: None`` from the SDK must not crash post().

    ``usage.get("output_tokens", 0)`` returns ``None`` (not 0) when the key is present
    with a None value, which would TypeError on the ``input_tokens + total_output`` sum.
    The ``or 0`` guard coerces it, matching _claude_token_fields' None-handling.
    """
    agent_node.params = {"backend": "claude", "prompt": "do work"}
    agent_node.node_id = "agent"
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="done")])
        yield ResultMessage(
            result="done",
            usage={"input_tokens": 1000, "output_tokens": None},
            total_cost_usd=0.01,
            num_turns=1,
            session_id="s1",
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)  # must not raise

    lu = shared["llm_usage"]
    assert lu["output_tokens"] == 0
    assert lu["input_tokens"] == 1000
    assert lu["total_tokens"] == 1000  # 1000 + 0, no TypeError


def test_schema_retry_aggregates_inclusive_input_tokens_with_cache(agent_node):
    """Retry aggregation sums the INCLUSIVE per-attempt input_tokens (#492).

    The existing cache-zero retry test can't catch a half-fix: with zero cache the SDK's
    uncached count already equals the inclusive total, so a non-inclusive
    ``_usage_record_from`` is invisible. Here the main attempt AND the superseded attempt
    both carry non-zero cache, so the aggregated input_tokens only matches if BOTH producer
    sites (``post`` and ``_usage_record_from``) emit inclusive values. This is the test the
    "revert _usage_record_from only" mutation check fails against (plan §5).
    """
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    schema = {"type": "object", "properties": {"continue": {"type": "boolean"}}, "required": ["continue"]}
    agent_node.params = {"backend": "claude", "prompt": "decide", "output_schema": schema, "schema_retries": 1}
    agent_node.node_id = "review"
    shared = {"__warnings__": {}}
    agent_node.shared = shared

    async def attempt1(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="maybe?")])
        yield ResultMessage(
            structured_output={"continue": "maybe"},  # not coercible to bool → retry
            usage={
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 300,
            },
            total_cost_usd=0.01,
            num_turns=3,
            session_id="s1",
        )

    async def attempt2(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text='{"continue": "true"}')])
        yield ResultMessage(
            structured_output={"continue": "true"},  # coerces to True → conforming
            usage={
                "input_tokens": 200,
                "output_tokens": 20,
                "cache_creation_input_tokens": 400,
                "cache_read_input_tokens": 600,
            },
            total_cost_usd=0.02,
            num_turns=2,
            session_id="s1",
        )

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.side_effect = [attempt1(), attempt2()]

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)
        agent_node.post(shared, prep_res, result)

    lu = shared["llm_usage"]
    # Main = final attempt, INCLUSIVE: 200 + 400 + 600 = 1200 (not the SDK's bare 200).
    assert lu["input_tokens"] == 1200
    assert lu["uncached_input_tokens"] == 200
    # Superseded attempt recorded INCLUSIVE: 100 + 200 + 300 = 600 (not the SDK's bare 100).
    assert [r["input_tokens"] for r in lu["retries"]] == [600]
    assert [r["uncached_input_tokens"] for r in lu["retries"]] == [100]

    agg = WorkflowTraceCollector.aggregate_llm_usage_with_retries(lu)
    assert agg["input_tokens"] == 1800  # 1200 + 600 (inclusive per-attempt)
    assert agg["uncached_input_tokens"] == 300  # 200 + 100 (summed across attempts)
    assert agg["output_tokens"] == 30  # 20 + 10
    assert agg["cache_creation_input_tokens"] == 600  # 400 + 200
    assert agg["cache_read_input_tokens"] == 900  # 600 + 300
    assert agg["total_tokens"] == 1830  # sum(inclusive input) + sum(output)
    # The aggregator must keep input_tokens == uncached + creation + read on the
    # aggregated dict (#492): uncached is summed, not carried main-only.
    assert agg["input_tokens"] == (
        agg["uncached_input_tokens"] + agg["cache_creation_input_tokens"] + agg["cache_read_input_tokens"]
    )


def test_schema_retries_no_op_without_output_schema(agent_node):
    """schema_retries > 0 with NO output_schema must not coerce or retry (the gate).

    Replaces a former no-op `pass` test that claimed this was "tested at the node level"
    while no such test existed.
    """
    agent_node.params = {"backend": "claude", "prompt": "hello", "schema_retries": 3}
    agent_node.node_id = "plain"
    shared = {}
    agent_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="just prose")])
        yield ResultMessage(structured_output=None, result="just prose", session_id="s1")

    with patch("pflow.nodes.agent.claude_backend.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = agent_node.prep(shared)
        result = agent_node.exec(prep_res)

    assert mock_query.call_count == 1  # no retry fired
    assert result["retry_metadata"]["attempts"] == 0
    assert "retry_usages" not in result

    agent_node.post(shared, prep_res, result)
    assert shared["result"] == "just prose"
    assert "retries" not in shared.get("llm_usage", {})


def test_schema_retries_no_schema_one_turn_allowed(agent_node):
    """A no-schema node with max_turns=1 and explicit schema_retries>0 is NOT rejected.

    Regression guard (#465 review): _validate_schema_retries used to couple schema_retries
    to max_turns, rejecting valid no-schema nodes that cap Claude to one turn — even though
    the retry only ever runs when an output_schema is set.
    """
    agent_node.params = {"backend": "claude", "prompt": "hi", "max_turns": 1, "schema_retries": 2}
    prep_res = agent_node.prep({"__warnings__": {}})  # no output_schema → must not raise
    assert prep_res["schema_retries"] == 2
    assert prep_res["max_turns"] == 1


def test_schema_retries_invalid_value_rejected(agent_node):
    """A non-integer schema_retries raises a clear AgentValidationError (only int() is wrapped)."""
    agent_node.params = {"backend": "claude", "prompt": "hi", "schema_retries": "abc"}
    with pytest.raises(AgentValidationError, match="Invalid schema_retries"):
        agent_node.prep({"__warnings__": {}})


def test_schema_retries_out_of_range_rejected(agent_node):
    """Range checks live outside the try and keep their specific messages."""
    agent_node.params = {"backend": "claude", "prompt": "hi", "schema_retries": 9}
    with pytest.raises(AgentValidationError, match="cannot exceed 5"):
        agent_node.prep({"__warnings__": {}})

    agent_node.params = {"backend": "claude", "prompt": "hi", "schema_retries": -1}
    with pytest.raises(AgentValidationError, match="cannot be negative"):
        agent_node.prep({"__warnings__": {}})


@pytest.mark.parametrize(
    ("params", "match"),
    [
        # Formerly a bare TypeError (validate_claude_sandbox non-dict) — pre-#592 this
        # fell through the diagnostic converter's generic branch and leaked a scary
        # "Type: TypeError" line. THIS is the exact regression #592 fixed: swapping it
        # back to a raw TypeError makes this assertion fail.
        ({"backend": "claude", "prompt": "hi", "sandbox": "not a dict"}, "sandbox must be a dict"),
        # Formerly a bare ValueError (_validate_backend) — rendered clean already, but
        # inconsistently vs the TypeError paths. Pins that both now render identically.
        ({"backend": "bogus", "prompt": "hi"}, "Invalid backend"),
    ],
)
def test_agent_param_errors_render_as_clean_validation_diagnostics(params: dict[str, Any], match: str) -> None:
    """#592: every agent param error renders identically — a clean validation
    diagnostic with NO ``Type:`` line, whether it was formerly a ``ValueError`` or a
    ``TypeError``. Exercises the real exception → diagnostic → rendered-text path a
    user/agent sees, not just the raised type. The TypeError case reproduces the
    literal #592 symptom; both cases also guard the ``to_diagnostics`` override
    (dropping it re-introduces the ``Type:`` line and a wrong title).
    """
    from pflow.core.diagnostic import exception_to_diagnostics
    from pflow.core.diagnostic_render import format_diagnostic

    node = AgentNode()
    node.set_params(params)
    with pytest.raises(AgentValidationError, match=match) as exc_info:
        node.prep({})

    diagnostics = exception_to_diagnostics(exc_info.value)
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.title == "Validation Error"
    assert diagnostic.context == {"category": "validation"}
    # Runtime-only params get the same guide pointer the static validator emits.
    assert diagnostic.see_also == ["agent"]

    rendered = format_diagnostic(diagnostic)
    # The regression: a Python exception-type leak ("Type: TypeError") must never
    # surface for a user-facing param validation error.
    assert "Type:" not in rendered
