"""Comprehensive tests for Claude Code Agentic Node.

Tests criteria from the specification:
1. Prompt missing → ValueError with "No prompt provided"
2. Prompt empty string → ValueError with "Prompt cannot be empty"
3. Prompt > 10000 chars → ValueError with "Prompt too long"
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
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock, patch

import pytest


# Create mock SDK classes before importing the node
class AssistantMessage:
    def __init__(self, content):
        self.content = content


class TextBlock:
    def __init__(self, text):
        self.text = text


class ToolUseBlock:
    def __init__(self, name, input_data):
        self.name = name
        self.input = input_data


@dataclass
class ResultMessage:
    """Test mock mirroring claude_agent_sdk.types.ResultMessage (v0.2.82+)."""

    subtype: str = "success"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 1
    session_id: str = "test-session"
    total_cost_usd: float | None = None
    usage: dict | None = None
    result: str | None = None
    structured_output: Any = None
    api_error_status: int | None = None


class CLINotFoundError(Exception):
    pass


class CLIConnectionError(Exception):
    pass


class ProcessError(Exception):
    def __init__(self, exit_code=1, stderr=""):
        # ``str(exc)`` returns ``stderr`` so ``_run_claude_session`` captures
        # something meaningful into ``sdk_exception_text`` (the real SDK
        # ProcessError's ``__str__`` is similarly stderr-derived).
        super().__init__(stderr)
        self.exit_code = exit_code
        self.stderr = stderr


class ClaudeSDKError(Exception):
    pass


class QueryError(Exception):
    pass


# Mock the SDK module before importing the node
mock_sdk_types = Mock()
mock_sdk_types.AssistantMessage = AssistantMessage
mock_sdk_types.TextBlock = TextBlock
mock_sdk_types.ToolUseBlock = ToolUseBlock
mock_sdk_types.ResultMessage = ResultMessage

mock_sdk_exceptions = Mock()
mock_sdk_exceptions.CLINotFoundError = CLINotFoundError
mock_sdk_exceptions.CLIConnectionError = CLIConnectionError
mock_sdk_exceptions.ProcessError = ProcessError
mock_sdk_exceptions.ClaudeSDKError = ClaudeSDKError

mock_sdk = Mock()
mock_sdk.query = Mock()
mock_sdk.ClaudeAgentOptions = Mock
# Add exception classes to main mock_sdk module
mock_sdk.CLINotFoundError = CLINotFoundError
mock_sdk.CLIConnectionError = CLIConnectionError
mock_sdk.ProcessError = ProcessError
mock_sdk.ClaudeSDKError = ClaudeSDKError

sys.modules["claude_agent_sdk"] = mock_sdk
sys.modules["claude_agent_sdk.types"] = mock_sdk_types
sys.modules["claude_agent_sdk.exceptions"] = mock_sdk_exceptions

# Now import the node after SDK mocking - E402 is expected here
from pflow.core.diagnostic import Severity  # noqa: E402
from pflow.core.workflow.validator import WorkflowValidator  # noqa: E402
from pflow.nodes.claude.claude_code import ClaudeCodeNode  # noqa: E402
from pflow.registry.metadata_extractor import PflowMetadataExtractor  # noqa: E402


# Fixtures for common test setup
@pytest.fixture
def claude_node():
    """Create a ClaudeCodeNode instance."""
    return ClaudeCodeNode()


@pytest.fixture
def shared_store():
    """Create a basic shared store with prompt."""
    return {"prompt": "Write a hello world function"}


@pytest.fixture
def mock_query_success():
    """Mock successful Claude query with text response."""

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="def hello_world():\n    print('Hello, World!')")])

    with patch("pflow.nodes.claude.claude_code.query") as mock:
        mock.return_value = mock_response()
        yield mock


# Test Criteria 1: Prompt missing → ValueError pointing at the `- prompt:` param
def test_task_missing(claude_node):
    """Missing prompt raises ValueError in authoring vocabulary.

    Regression: the error must speak the `.pflow.md` authoring surface
    (`- prompt:` / `${...}`), not runtime internals. An agent only ever
    writes markdown — `shared[...]` / `params` are unactionable leaks.
    """
    shared = {"__warnings__": {}}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    message = str(exc_info.value)
    assert "'prompt'" in message
    assert "- prompt:" in message
    # No runtime internals leak into agent-facing text.
    assert "shared[" not in message
    assert "shared store" not in message


# Test Criteria 2: Prompt empty string → ValueError with "cannot be empty"
def test_task_empty_string(claude_node):
    """Test that empty string prompt raises ValueError."""
    claude_node.params = {"prompt": "   "}  # Whitespace only
    shared = {"__warnings__": {}}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "cannot be empty" in str(exc_info.value)


# Test Criteria 3: Prompt > 10000 chars → ValueError with "Prompt too long"
def test_task_too_long(claude_node):
    """Test that prompt over 10000 chars raises ValueError."""
    claude_node.params = {"prompt": "x" * 10001}
    shared = {"__warnings__": {}}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Prompt too long" in str(exc_info.value)
    assert "10001" in str(exc_info.value)


# Test Criteria 4: Working directory missing → ValueError with path
def test_working_directory_missing(claude_node):
    """Test that non-existent working directory raises ValueError."""
    claude_node.params = {"prompt": "test prompt", "cwd": "/nonexistent/path"}
    shared = {"__warnings__": {}}

    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Working directory does not exist" in str(exc_info.value)
    assert "/nonexistent/path" in str(exc_info.value)


# Test Criteria 5: Working directory restricted → ValueError with "Restricted directory"
def test_working_directory_restricted(claude_node):
    """Test that restricted directories raise ValueError."""
    shared = {"__warnings__": {}}

    # Test multiple restricted directories
    for restricted in ["/", "/etc", "/usr", "/bin"]:
        claude_node.params = {"prompt": "test prompt", "cwd": restricted}
        with pytest.raises(ValueError) as exc_info:
            claude_node.prep(shared)
        assert "Restricted directory" in str(exc_info.value)


# Note: Tests 6 & 7 (CLI/auth checking) removed as authentication is now handled by SDK


# Test Criteria 8: Valid prompt without schema → "success" and shared["result"] populated
def test_valid_task_without_schema(claude_node):
    """Test successful execution without output schema."""
    claude_node.params = {"prompt": "Write a hello world function"}
    shared = {}
    claude_node.shared = shared

    # Mock query response
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="def hello_world():\n    print('Hello, World!')")])

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        # Prepare and execute
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == "def hello_world():\n    print('Hello, World!')"
        assert result["tool_uses"] == []

        # Check post() stores results (now string format without schema)
        claude_node.post(shared, prep_res, result)
        assert "result" in shared
        assert isinstance(shared["result"], str)
        assert "def hello_world()" in shared["result"]
        assert "Hello, World!" in shared["result"]


# Test Criteria 9: Valid prompt with schema → "success" and schema keys in shared
def test_valid_task_with_schema(claude_node):
    """Test successful execution with output schema."""
    schema = {
        "type": "object",
        "properties": {
            "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["risk_level", "issues"],
    }
    claude_node.params = {
        "prompt": "Review this code for issues",
        "output_schema": schema,
    }
    shared = {"__warnings__": {}}
    claude_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="Analysis complete.")])
        yield ResultMessage(structured_output={"risk_level": "low", "issues": []}, is_error=False)

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        # Prepare and execute
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == "Analysis complete."
        assert result["structured_output"] == {"risk_level": "low", "issues": []}

        claude_node.post(shared, prep_res, result)
        assert shared["result"] == {"risk_level": "low", "issues": []}
        assert "_schema_error" not in shared
        assert not shared["__warnings__"]


def test_legacy_python_alias_schema_rejected(claude_node):
    """Old custom output_schema format raises with migration guidance."""
    with pytest.raises(ValueError, match="legacy Python-alias format"):
        claude_node._validate_schema({"risk_level": {"type": "str", "description": "high/medium/low"}})


def test_legacy_format_detection_checks_all_values(claude_node):
    """Legacy detection checks all values, not just the first."""
    schema = {"_meta": "comment", "risk": {"type": "str", "description": "high/medium/low"}}
    with pytest.raises(ValueError, match="legacy Python-alias format"):
        claude_node._validate_schema(schema)


def test_top_level_oneOf_schema_rejected(claude_node):
    """Verified via real-API probe: oneOf top-level returns HTTP 400.
    Combinators must live inside an object wrapper.
    """
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"oneOf": [{"type": "string"}, {"type": "integer"}]})


def test_top_level_anyOf_schema_rejected(claude_node):
    """anyOf at top level is rejected by the API — same class as oneOf."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"anyOf": [{"type": "object"}, {"type": "object"}]})


def test_top_level_allOf_schema_rejected(claude_node):
    """allOf at top level is rejected by the API — same class as oneOf."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"allOf": [{"type": "object"}, {"type": "object"}]})


def test_top_level_missing_type_rejected(claude_node):
    """A dict without top-level `type` is rejected — the API requires `type: object`."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"properties": {"x": {"type": "string"}}})


def test_top_level_array_schema_rejected(claude_node):
    """The Claude API rejects non-object top-level schemas; prep catches this."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"type": "array", "items": {"type": "string"}})


def test_top_level_primitive_schema_rejected(claude_node):
    """Primitive top-level schemas must be wrapped in an object."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"type": "string", "enum": ["yes", "no"]})


def test_top_level_object_with_oneOf_accepted(claude_node):
    """oneOf INSIDE a top-level `type: object` is fine — the wrapper is what the API requires."""
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "oneOf": [{"required": ["x"]}, {"required": []}],
    }
    assert claude_node._validate_schema(schema) == schema


def test_empty_schema_dict_rejected(claude_node):
    """Empty dict likely means the schema body was omitted."""
    with pytest.raises(ValueError, match="empty dict"):
        claude_node._validate_schema({})


def test_none_schema_returns_none(claude_node):
    """None means no schema was requested."""
    assert claude_node._validate_schema(None) is None


def test_non_dict_schema_raises_typeerror(claude_node):
    """output_schema must be a JSON Schema dict."""
    with pytest.raises(TypeError):
        claude_node._validate_schema(["not", "a", "dict"])


def test_registry_interface_outputs_exclude_root_warnings():
    """Root __warnings__ is diagnostic state, not a node template output."""
    metadata = PflowMetadataExtractor().extract_metadata(ClaudeCodeNode)
    output_keys = {item["key"] for item in metadata["outputs"]}
    assert "result" in output_keys
    assert "_schema_error" in output_keys
    assert "__warnings__" not in output_keys


def test_output_schema_wrapped_and_passed_to_options(claude_node):
    """JSON Schema is wrapped in the SDK's native output_format shape."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    prep_res = claude_node.prep({})

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert mock_options.call_args.kwargs["output_format"] == {
        "type": "json_schema",
        "schema": schema,
    }


def test_exec_passes_structured_options_to_query(claude_node):
    """The execution path must pass the ClaudeAgentOptions object into query()."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    sentinel_options = object()
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output={"x": "ok"}, is_error=False)

    with (
        patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions", return_value=sentinel_options) as mock_options,
        patch("pflow.nodes.claude.claude_code.query") as mock_query,
    ):
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep({})
        claude_node.exec(prep_res)

    assert mock_options.call_args.kwargs["output_format"] == {
        "type": "json_schema",
        "schema": schema,
    }
    assert mock_query.call_args.kwargs["options"] is sentinel_options


def test_no_schema_means_no_output_format(claude_node):
    """Without output_schema, output_format is omitted."""
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep({})

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert "output_format" not in mock_options.call_args.kwargs


# Test Criteria 12: Rate limit error → ValueError with retry message
def test_rate_limit_error(claude_node):
    """Test rate limit error handling."""
    claude_node.params = {"prompt": "test prompt"}
    shared = {"__warnings__": {}}
    claude_node.shared = shared

    async def mock_error(*args, **kwargs):
        raise ValueError("429 Too Many Requests - Rate limit exceeded")
        yield  # Make it async generator

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_error()

        prep_res = claude_node.prep(shared)

        # Execute should raise, then exec_fallback handles it
        with pytest.raises(ValueError) as exc_info:
            claude_node.exec(prep_res)

        # Test exec_fallback handling
        with pytest.raises(ValueError) as fallback_exc:
            claude_node.exec_fallback(prep_res, exc_info.value)

        assert "rate limit exceeded" in str(fallback_exc.value).lower()
        assert "wait a moment and try again" in str(fallback_exc.value).lower()


# Test Criteria 13: Timeout at 300s → ValueError with timeout message
def test_timeout_error(claude_node):
    """Test timeout error handling."""
    # Speed up test with shorter timeout via params (minimum allowed is 30s, but we patch it)
    claude_node.params = {"prompt": "test prompt", "timeout": 30}  # Use minimum allowed timeout
    shared = {}
    claude_node.shared = shared

    async def mock_timeout(*args, **kwargs):
        await asyncio.sleep(100)  # Exceed timeout (will be cut short by 0.1s timeout)
        yield AssistantMessage(content=[TextBlock(text="Never reached")])

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_timeout()

        prep_res = claude_node.prep(shared)
        # Override with very short timeout for testing (bypass validation)
        prep_res["timeout"] = 0.1

        # Execute should timeout
        with pytest.raises(asyncio.TimeoutError):
            claude_node.exec(prep_res)

        # Test exec_fallback handling
        with pytest.raises(ValueError) as fallback_exc:
            claude_node.exec_fallback(prep_res, asyncio.TimeoutError())

        assert "timed out" in str(fallback_exc.value).lower()
        assert "0.1 seconds" in str(fallback_exc.value)


# Test Criteria 14: CLINotFoundError handling → Correct error transformation
def test_cli_not_found_error_handling(claude_node):
    """Test CLINotFoundError transformation."""
    claude_node.params = {"prompt": "test prompt"}
    shared = {}
    claude_node.shared = shared

    async def mock_cli_error(*args, **kwargs):
        raise CLINotFoundError("Claude CLI not found")
        yield  # Make it async generator

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_cli_error()

        prep_res = claude_node.prep(shared)

        with pytest.raises(CLINotFoundError):
            claude_node.exec(prep_res)

        # Test exec_fallback transforms the error
        with pytest.raises(ValueError) as fallback_exc:
            claude_node.exec_fallback(prep_res, CLINotFoundError("Test"))

        assert "Claude Code CLI not installed" in str(fallback_exc.value)
        assert "npm install -g @anthropic-ai/claude-code" in str(fallback_exc.value)


# Test Criteria 15: CLIConnectionError handling → Correct error transformation
def test_cli_connection_error_handling(claude_node):
    """Test CLIConnectionError transformation."""
    claude_node.params = {"prompt": "test prompt"}
    shared = {}
    claude_node.shared = shared

    async def mock_conn_error(*args, **kwargs):
        raise CLIConnectionError("Connection failed")
        yield  # Make it async generator

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_conn_error()

        prep_res = claude_node.prep(shared)

        with pytest.raises(CLIConnectionError):
            claude_node.exec(prep_res)

        # Test exec_fallback transforms the error
        with pytest.raises(ValueError) as fallback_exc:
            claude_node.exec_fallback(prep_res, CLIConnectionError("Test"))

        assert "Failed to connect to Claude Code" in str(fallback_exc.value)
        assert "claude doctor" in str(fallback_exc.value)
        assert "claude auth login" in str(fallback_exc.value)


# Test Criteria 16: ProcessError handling → Includes exit code
def test_process_error_handling(claude_node):
    """Test ProcessError transformation with exit code."""
    claude_node.params = {"prompt": "test prompt"}
    shared = {}
    claude_node.shared = shared

    error = ProcessError(exit_code=127, stderr="Command not found")

    async def mock_proc_error(*args, **kwargs):
        raise error
        yield  # Make it async generator

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_proc_error()

        prep_res = claude_node.prep(shared)

        with pytest.raises(ProcessError):
            claude_node.exec(prep_res)

        # Test exec_fallback includes exit code
        with pytest.raises(ValueError) as fallback_exc:
            claude_node.exec_fallback(prep_res, error)

        assert "exit code 127" in str(fallback_exc.value)
        assert "Command not found" in str(fallback_exc.value)


# Test Criteria 17: Tool configuration → All tools available by default, pass through when specified
def test_tool_configuration(claude_node):
    """Test that tools are passed through to SDK without validation.

    By default (allowed_tools=None), all tools are available including Task for subagents.
    When explicitly specified, tools are passed through to SDK for validation.
    """
    shared = {}

    # Default: None = all tools available (including Task for subagents)
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] is None  # None = SDK default (all tools)

    # Explicit tools are passed through without validation
    explicit_tools = ["Read", "Write", "Edit", "Bash"]
    claude_node.params = {"prompt": "test prompt", "allowed_tools": explicit_tools}
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] == explicit_tools

    # Task tool (for subagents) can now be explicitly included
    tools_with_task = ["Read", "Write", "Task", "Glob", "Grep"]
    claude_node.params = {"prompt": "test prompt", "allowed_tools": tools_with_task}
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] == tools_with_task
    assert "Task" in prep_res["allowed_tools"]  # Task tool for subagents


# Test: Resume parameter for session continuation
def test_resume_parameter(claude_node):
    """Test that resume parameter is validated and passed through."""
    shared = {}

    # Default: None
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep(shared)
    assert prep_res["resume"] is None

    # Valid session ID
    claude_node.params = {"prompt": "test prompt", "resume": "session-abc123"}
    prep_res = claude_node.prep(shared)
    assert prep_res["resume"] == "session-abc123"

    # Invalid type should raise
    claude_node.params = {"prompt": "test prompt", "resume": 12345}  # Not a string
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "resume must be a string" in str(exc_info.value)


# Test: Timeout parameter configuration
def test_timeout_parameter(claude_node):
    """Test that timeout parameter is validated and configurable."""
    shared = {}

    # Default: 300 seconds
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep(shared)
    assert prep_res["timeout"] == 300

    # Custom timeout
    claude_node.params = {"prompt": "test prompt", "timeout": 600}
    prep_res = claude_node.prep(shared)
    assert prep_res["timeout"] == 600

    # Too short (< 30s)
    claude_node.params = {"prompt": "test prompt", "timeout": 10}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "between 30 and 3600" in str(exc_info.value)

    # Too long (> 3600s)
    claude_node.params = {"prompt": "test prompt", "timeout": 5000}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "between 30 and 3600" in str(exc_info.value)


# Test Criteria 19: Valid JSON response → Values stored in schema keys
def test_valid_json_response_storage(claude_node):
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
    claude_node.params = {
        "prompt": "Analyze code",
        "output_schema": schema,
    }
    shared = {"__warnings__": {}}
    claude_node.shared = shared

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

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)

        claude_node.post(shared, prep_res, result)
        assert shared["result"] == {
            "complexity": "medium",
            "lines": 42,
            "functions": ["main", "helper", "utils"],
        }
        assert "_schema_error" not in shared
        assert not shared["__warnings__"]


# Test Criteria 20: Invalid JSON response → Raw text in result, error in _schema_error
def test_invalid_json_response_fallback(claude_node):
    """Schema set + no structured_output falls back to raw text and warns."""
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
    claude_node.params = {
        "prompt": "Analyze code",
        "output_schema": schema,
    }
    claude_node.node_id = "review"
    shared = {}
    claude_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="This is not JSON at all, just plain text response.")])
        yield ResultMessage(structured_output=None, result="This is not JSON at all, just plain text response.")

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)

        claude_node.post(shared, prep_res, result)
        assert shared["result"] == "This is not JSON at all, just plain text response."
        assert "Model did not return" in shared["_schema_error"]
        assert shared["__warnings__"]["review"]["kind"] == "claude_code.schema_not_satisfied"


def test_sdk_is_error_branch(claude_node):
    """SDK is_error without structured_output uses the CLI-error soft-fail warning."""
    schema = {"type": "object", "properties": {"found": {"type": "string"}}, "required": ["found"]}
    claude_node.params = {
        "prompt": "Analyze code",
        "output_schema": schema,
    }
    claude_node.node_id = "review"
    shared = {}
    claude_node.shared = shared

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="error context")])
        yield ResultMessage(structured_output=None, result="error context", is_error=True)
        # The SDK pairs ResultMessage(is_error=True) with a ProcessError raise
        # when the CLI exits non-zero; the node must preserve the is_error state
        # rather than re-raise. Other exception types are tested separately.
        raise ProcessError(exit_code=1, stderr="Claude Code returned an error result: error context")

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)

        claude_node.post(shared, prep_res, result)
        assert shared["result"] == "error context"
        assert "Claude CLI reported an error" in shared["_schema_error"]
        assert shared["__warnings__"]["review"]["kind"] == "claude_code.sdk_error_no_structured_output"
        assert shared["__warnings__"]["review"]["context"]["sdk_exception"]


# Test Criteria 22: No response content → Empty result stored
def test_no_response_content(claude_node):
    """Test that empty response stores empty result."""
    claude_node.params = {"prompt": "test prompt"}
    shared = {}
    claude_node.shared = shared

    # Mock empty response
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[])

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == ""

        # Check post() handles empty response (now stores as string)
        claude_node.post(shared, prep_res, result)
        assert isinstance(shared["result"], str)
        assert shared["result"] == ""


# Additional tests for edge cases and integration


def test_max_thinking_tokens_validation(claude_node):
    """Test max_thinking_tokens parameter validation."""
    shared = {}

    # Valid range
    claude_node.params = {"prompt": "test prompt", "max_thinking_tokens": 5000}
    prep_res = claude_node.prep(shared)
    assert prep_res["max_thinking_tokens"] == 5000

    # Too low
    claude_node.params = {"prompt": "test prompt", "max_thinking_tokens": 500}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_thinking_tokens" in str(exc_info.value)

    # Too high
    claude_node.params = {"prompt": "test prompt", "max_thinking_tokens": 200000}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_thinking_tokens" in str(exc_info.value)


def test_max_turns_validation(claude_node):
    """Test max_turns parameter validation."""
    shared = {}

    # Valid range
    claude_node.params = {"prompt": "test prompt", "max_turns": 10}
    prep_res = claude_node.prep(shared)
    assert prep_res["max_turns"] == 10

    # Too low
    claude_node.params = {"prompt": "test prompt", "max_turns": 0}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_turns" in str(exc_info.value)

    # Too high (now 100 is the max)
    claude_node.params = {"prompt": "test prompt", "max_turns": 101}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_turns" in str(exc_info.value)


def test_max_turns_too_low_with_schema_rejected(claude_node):
    """Structured output needs at least two turns."""
    claude_node.params = {
        "prompt": "test prompt",
        "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        "max_turns": 1,
    }
    with pytest.raises(ValueError, match="max_turns must be >= 2"):
        claude_node.prep({})


def test_tool_use_logging(claude_node, caplog):
    """Test that tool uses are logged."""
    import logging

    claude_node.params = {"prompt": "test prompt"}
    shared = {}
    claude_node.shared = shared

    # Mock response with tool uses
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(
            content=[
                ToolUseBlock(name="Read", input_data={"file": "test.py"}),
                ToolUseBlock(name="Edit", input_data={"file": "test.py", "content": "new"}),
                TextBlock(text="Task completed"),
            ]
        )

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        # Explicitly set logger level for this test since global config may have changed
        with caplog.at_level(logging.INFO, logger="pflow.nodes.claude.claude_code"):
            prep_res = claude_node.prep(shared)
            result = claude_node.exec(prep_res)

        assert isinstance(result, dict)
        assert len(result["tool_uses"]) == 2
        assert result["tool_uses"][0]["name"] == "Read"
        assert result["tool_uses"][1]["name"] == "Edit"
        assert "Claude Code used 2 tools" in caplog.text


def test_sdk_is_error_with_structured_output_emits_warning(claude_node):
    """If SDK reports an error but structured_output exists, structured output wins and warning persists."""
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    claude_node.node_id = "review"
    shared = {}

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="done")])
        yield ResultMessage(structured_output={"x": 1}, is_error=True)
        # See test_sdk_is_error_branch — only ProcessError is the paired-with-
        # is_error=True case the node swallows.
        raise ProcessError(exit_code=1, stderr="partial")

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)
        claude_node.post(shared, prep_res, result)

    assert shared["result"] == {"x": 1}
    assert shared["__warnings__"]["review"]["kind"] == "claude_code.sdk_error_with_structured_output"


def test_non_process_error_after_is_error_re_raises(claude_node):
    """Hard errors after a ResultMessage(is_error=True) must NOT be swallowed.

    Regression: an earlier fix preserved is_error state by swallowing every
    ``Exception``, which masked ``CLIConnectionError``/``CLINotFoundError``-class
    failures so the user never saw the remediation message from ``exec_fallback``.
    Only ``ProcessError`` (the paired non-zero-exit case) is the swallow candidate.
    """
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    claude_node.node_id = "review"
    shared = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output=None, result="partial", is_error=True)
        raise CLIConnectionError("Lost connection to Claude CLI mid-stream")

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        # ``exec()`` runs the SDK loop directly (no retry/fallback wrapper).
        # The connection error must escape ``_run_claude_session`` so the
        # Node retry path eventually delivers it to ``exec_fallback``.
        with pytest.raises(CLIConnectionError, match="Lost connection"):
            claude_node.exec(prep_res)


def test_process_error_name_fallback_when_sdk_class_is_none(claude_node):
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
    import pflow.nodes.claude.claude_code as cc

    # A locally-defined exception class with the load-bearing name. NOT a
    # subclass of the test module's mock ``ProcessError`` — that ``isinstance``
    # match would let the typed approach pass too.
    class StandaloneProcessError(Exception):
        def __init__(self, message: str = "stderr text") -> None:
            super().__init__(message)

    StandaloneProcessError.__name__ = "ProcessError"

    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    claude_node.node_id = "review"
    shared: dict = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output=None, result="partial", is_error=True)
        raise StandaloneProcessError("CLI exit 1")

    with (
        patch.object(cc, "ProcessError", None),
        patch("pflow.nodes.claude.claude_code.query") as mock_query,
    ):
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        # MUST NOT raise — name fallback swallows after is_error=True.
        result = claude_node.exec(prep_res)
        claude_node.post(shared, prep_res, result)

    # Soft-fail signal preserved end-to-end.
    assert "Claude CLI reported an error" in shared["_schema_error"]
    assert shared["__warnings__"]["review"]["kind"] == "claude_code.sdk_error_no_structured_output"


def test_output_schema_resolved_to_null_emits_warning(claude_node):
    """A declared output_schema that resolves to None must warn the workflow author.

    Regression: silently dropping schema mode caused workflows that templated
    the schema from upstream nodes (``output_schema: ${x.schema}``) to report
    SUCCESS even when the schema reference missed and the run produced free-form
    text instead of structured output.
    """
    # Simulate engine post-template-resolution: key present, value resolved to None.
    claude_node.params = {"prompt": "test prompt", "output_schema": None}
    claude_node.node_id = "review"
    shared: dict = {}

    claude_node.prep(shared)

    warning = shared["__warnings__"]["review"]
    assert warning["kind"] == "claude_code.output_schema_resolved_to_null"
    assert "resolved to None" in warning["text"]
    assert warning["context"]["node_type"] == "claude-code"


def test_output_schema_absent_does_not_warn(claude_node):
    """If the workflow author never declared output_schema, no warning fires."""
    claude_node.params = {"prompt": "test prompt"}  # no output_schema key
    shared: dict = {}

    claude_node.prep(shared)

    assert "__warnings__" not in shared


def test_output_schema_resolved_null_no_node_id_falls_back_to_schema_error(claude_node):
    """Test-path / uncompiled nodes preserve signal via ``_schema_error``."""
    claude_node.params = {"prompt": "test prompt", "output_schema": None}
    shared: dict = {}

    claude_node.prep(shared)

    # Without a bound node_id, __warnings__ writes would be keyed under None and
    # are lost downstream — fall back to _schema_error so the signal survives.
    assert "resolved to None" in shared["_schema_error"]


def test_nested_array_schema(claude_node):
    """Arrays nested inside a top-level object are supported."""
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"],
    }
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    shared = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output={"items": ["a", "b", "c"]}, is_error=False)

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)
        claude_node.post(shared, prep_res, result)

    assert shared["result"] == {"items": ["a", "b", "c"]}
    assert isinstance(shared["result"]["items"], list)


def test_sticky_is_error_across_multiple_result_messages(claude_node):
    """An early ResultMessage.is_error=True remains visible even if a later message is false."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    claude_node.node_id = "review"
    shared = {}

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="raw")])
        yield ResultMessage(is_error=True, structured_output=None)
        yield ResultMessage(is_error=False, structured_output=None)

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)
        claude_node.post(shared, prep_res, result)

    assert shared["result"] == "raw"
    assert "Claude CLI reported an error" in shared["_schema_error"]
    assert shared["__warnings__"]["review"]["kind"] == "claude_code.sdk_error_no_structured_output"


def test_working_directory_expansion(claude_node):
    """Test that working directory paths are expanded correctly."""
    shared = {}

    # Test tilde expansion
    with patch("os.path.exists", return_value=True), patch("os.path.isdir", return_value=True):
        claude_node.params = {"prompt": "test prompt", "cwd": "~/projects"}
        prep_res = claude_node.prep(shared)

        # Should be expanded to absolute path
        assert prep_res["cwd"].startswith("/")
        assert "~" not in prep_res["cwd"]


def test_post_method(claude_node):
    """Test post method always returns 'default'."""
    claude_node.params = {"prompt": "test"}
    shared = {}
    prep_res = {"prompt": "test"}

    # Create proper exec_res dict
    exec_res = {"result_text": "test completed", "tool_uses": [], "output_schema": None}

    # Post should always return "default" regardless of execution result
    assert claude_node.post(shared, prep_res, exec_res) == "default"
    assert isinstance(shared["result"], str)
    assert shared["result"] == "test completed"


def test_retry_configuration(claude_node):
    """Test that retry configuration is conservative."""
    # Node should be configured for only 2 attempts total (expensive API)
    assert claude_node.max_retries == 2
    assert claude_node.wait == 1.0
    # Timeout is now configurable via params, default 300s tested in test_timeout_parameter


def test_generic_error_fallback(claude_node):
    """Test generic error handling in exec_fallback."""
    claude_node.params = {"prompt": "test prompt"}
    shared = {}
    prep_res = claude_node.prep(shared)

    # Generic exception
    generic_error = Exception("Something went wrong")

    with pytest.raises(ValueError) as exc_info:
        claude_node.exec_fallback(prep_res, generic_error)

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


def test_sandbox_parameter_defaults(claude_node):
    """Test sandbox parameter defaults to None."""
    shared = {}
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep(shared)
    assert prep_res.get("sandbox") is None


def test_sandbox_parameter_valid_config(claude_node):
    """Test valid sandbox configuration."""
    shared = {}
    claude_node.params = {
        "prompt": "test prompt",
        "sandbox": {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "excludedCommands": ["docker", "kubectl"],
            "network": {"allowLocalBinding": True},
        },
    }
    prep_res = claude_node.prep(shared)
    assert prep_res["sandbox"]["enabled"] is True
    assert prep_res["sandbox"]["autoAllowBashIfSandboxed"] is True
    assert prep_res["sandbox"]["excludedCommands"] == ["docker", "kubectl"]
    assert prep_res["sandbox"]["network"]["allowLocalBinding"] is True


def test_sandbox_parameter_minimal_config(claude_node):
    """Test minimal sandbox configuration with just enabled."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "sandbox": {"enabled": True}}
    prep_res = claude_node.prep(shared)
    assert prep_res["sandbox"]["enabled"] is True


def test_sandbox_parameter_invalid_type(claude_node):
    """Test sandbox rejects non-dict values."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "sandbox": "not a dict"}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "sandbox must be a dict" in str(exc_info.value)


def test_sandbox_parameter_invalid_enabled_type(claude_node):
    """Test sandbox['enabled'] must be bool."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "sandbox": {"enabled": "yes"}}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "sandbox['enabled'] must be bool" in str(exc_info.value)


def test_sandbox_parameter_invalid_auto_allow_bash_type(claude_node):
    """Test sandbox['autoAllowBashIfSandboxed'] must be bool."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "sandbox": {"autoAllowBashIfSandboxed": 1}}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "sandbox['autoAllowBashIfSandboxed'] must be bool" in str(exc_info.value)


def test_sandbox_parameter_invalid_excluded_commands_type(claude_node):
    """Test sandbox['excludedCommands'] must be list."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "sandbox": {"excludedCommands": "docker"}}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "sandbox['excludedCommands'] must be a list" in str(exc_info.value)


def test_sandbox_parameter_invalid_network_type(claude_node):
    """Test sandbox['network'] must be dict."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "sandbox": {"network": "localhost"}}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "sandbox['network'] must be a dict" in str(exc_info.value)


def test_sandbox_parameter_passes_unknown_keys(claude_node):
    """Test that unknown sandbox keys are passed through for SDK forward compatibility."""
    shared = {}
    claude_node.params = {
        "prompt": "test prompt",
        "sandbox": {
            "enabled": True,
            "futureOption": "some value",  # Unknown key should pass through
        },
    }
    prep_res = claude_node.prep(shared)
    assert prep_res["sandbox"]["enabled"] is True
    assert prep_res["sandbox"]["futureOption"] == "some value"


# Disallowed tools parameter tests


def test_disallowed_tools_default_none(claude_node):
    """Test disallowed_tools defaults to None (no restrictions)."""
    shared = {}
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep(shared)
    assert prep_res["disallowed_tools"] is None


def test_disallowed_tools_with_patterns(claude_node):
    """Test disallowed_tools accepts pattern strings for SDK denylist."""
    shared = {}
    patterns = ["Bash(pflow:*)", "Bash(make:*)"]
    claude_node.params = {"prompt": "test prompt", "disallowed_tools": patterns}
    prep_res = claude_node.prep(shared)
    assert prep_res["disallowed_tools"] == patterns


def test_disallowed_tools_passed_to_options(claude_node):
    """Test disallowed_tools is passed through to ClaudeAgentOptions."""
    shared = {}
    patterns = ["Bash(pflow:*)", "Bash(git:*)"]
    claude_node.params = {"prompt": "test prompt", "disallowed_tools": patterns}
    prep_res = claude_node.prep(shared)

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")
        assert mock_options.call_args.kwargs["disallowed_tools"] == patterns


def test_disallowed_tools_not_passed_when_none(claude_node):
    """Test disallowed_tools is omitted from options when None."""
    shared = {}
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep(shared)
    assert prep_res["disallowed_tools"] is None

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")
        assert "disallowed_tools" not in mock_options.call_args.kwargs


def test_disallowed_tools_invalid_type(claude_node):
    """Test disallowed_tools rejects non-list values."""
    shared = {}
    claude_node.params = {"prompt": "test prompt", "disallowed_tools": "Bash(pflow:*)"}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "disallowed_tools must be a list" in str(exc_info.value)


def test_disallowed_tools_with_allowed_tools(claude_node):
    """Test disallowed_tools works alongside allowed_tools."""
    shared = {}
    claude_node.params = {
        "prompt": "test prompt",
        "allowed_tools": ["Read", "Write", "Bash"],
        "disallowed_tools": ["Bash(rm:*)"],
    }
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] == ["Read", "Write", "Bash"]
    assert prep_res["disallowed_tools"] == ["Bash(rm:*)"]


# ---------------------------------------------------------------------------
# Soft-fail signal preservation when node_id is unbound (test path)
# ---------------------------------------------------------------------------


def test_sdk_error_with_structured_output_no_node_id_falls_back_to_schema_error(claude_node):
    """When the SDK reports an error alongside valid structured output AND no
    ``node_id`` is bound, ``_schema_error`` preserves the signal.

    Production engine paths always bind ``node_id``, so this is the test /
    direct-``node.run(shared)`` path. Matches the fallback established by
    ``_emit_schema_resolved_null_warning``: ``__warnings__[node_id]`` is the
    primary channel; ``_schema_error`` is the recovery channel.
    """
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    # No ``claude_node.node_id`` assignment — simulates uncompiled / direct test path.
    shared: dict = {}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(structured_output={"x": 1}, is_error=True)
        raise ProcessError(exit_code=1, stderr="partial")

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)
        claude_node.post(shared, prep_res, result)

    # Structured output still wins as the result.
    assert shared["result"] == {"x": 1}
    # Signal preserved via _schema_error even without node_id.
    assert "structured_output was produced" in shared["_schema_error"]
    # __warnings__ guarded by node_id; no warning entry expected.
    assert "__warnings__" not in shared


# ---------------------------------------------------------------------------
# Soft-fail message strings must not collide with api_warning_detector
# ---------------------------------------------------------------------------


def test_soft_fail_output_shape_not_classified_as_api_warning(claude_node):
    """Regression pin: a claude-code soft-fail must NOT be detected by
    ``api_warning_detector.detect_api_warning`` — otherwise the engine would
    override the node's ``"default"`` action to ``"error"`` and silently flip
    soft-fail (DEGRADED) into hard fail (FAILED).

    Today the detector is shape-gated — it only extracts an error message from
    outputs containing ``ok: false`` / ``success: false`` / ``status: "error"`` /
    GraphQL ``errors`` / an ``error`` key at the dict root. The claude-code node
    writes ``result``, ``_schema_error``, and ``llm_usage`` — none of those keys
    match. This test pins that invariant: the output shape from a soft-fail
    must continue to bypass the detector, regardless of message wording.

    A future contributor adding an ``error`` key to ``shared[node_id]`` for
    debug visibility would break soft-fail routing — this test fails first.
    """
    from pflow.runtime.engine.api_warning_detector import detect_api_warning

    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    claude_node.params = {"prompt": "test prompt", "output_schema": schema}
    claude_node.node_id = "review"
    # Simulate engine namespacing: a claude-code node writes its outputs under
    # ``shared[node_id]`` via NamespacedSharedStore. Build that shape directly
    # so the test exercises exactly what the detector will see in production.
    shared: dict = {}
    namespaced = {}

    async def mock_response(*args, **kwargs):
        # No structured output → soft-fail branch with the longest message.
        yield ResultMessage(structured_output=None, result="raw fallback text", is_error=False)

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)
        # Capture the node-output shape exactly as namespaced_store would write it.
        # _store_results writes ``shared["result"]``, ``shared["_schema_error"]``,
        # ``shared["llm_usage"]`` — under namespacing these become
        # ``shared[node_id][...]``.
        claude_node.post(namespaced, prep_res, result)

    # Promote namespaced writes into the shared store shape the engine produces.
    shared["review"] = {k: v for k, v in namespaced.items() if not k.startswith("__")}

    # The canonical invariant: claude-code soft-fail must NOT be detected as
    # an API warning. If detect_api_warning returns non-None, the engine would
    # convert action="default" → "error" and lose the entire soft-fail design.
    assert detect_api_warning("review", shared) is None, (
        "claude-code soft-fail output was classified as an API warning; engine "
        "would flip action to 'error'. Inspect: (a) any new error/ok/success/status "
        "keys in _store_results, or (b) any change to api_warning_detector's "
        "extract_error_message shape gates."
    )


# ---------------------------------------------------------------------------
# Runtime ↔ Validator parity
# ---------------------------------------------------------------------------
#
# ``pflow.nodes.claude.schema_validation`` shares the *predicates* between the
# runtime path (``ClaudeCodeNode._validate_schema``) and the static preflight
# path (``WorkflowValidator._validate_claude_code_params``). The shared
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


def _runtime_rejects(node: ClaudeCodeNode, schema: Any) -> bool:
    try:
        node._validate_schema(schema)
        return False
    except (ValueError, TypeError):
        return True


def _validator_rejects(schema: Any) -> bool:
    diagnostics = WorkflowValidator._validate_claude_code_params("review", {"output_schema": schema})
    return any(d.severity == Severity.ERROR for d in diagnostics)


@pytest.mark.parametrize("case_id,schema", _PARITY_REJECT, ids=[c[0] for c in _PARITY_REJECT])
def test_runtime_and_validator_agree_on_rejection(case_id: str, schema: Any, claude_node: Any) -> None:
    """Schemas rejected by one surface must be rejected by both.

    Add a row to ``_PARITY_REJECT`` when adding a rejection rule; if either
    surface doesn't implement it, this test fires with the case_id naming
    the gap.
    """
    validator_rejected = _validator_rejects(schema)
    runtime_rejected = _runtime_rejects(claude_node, schema)
    assert validator_rejected == runtime_rejected, (
        f"Surface drift on '{case_id}': validator_rejected={validator_rejected}, runtime_rejected={runtime_rejected}"
    )
    assert validator_rejected, f"'{case_id}' should be rejected — neither surface caught it"


@pytest.mark.parametrize("case_id,schema", _PARITY_ACCEPT, ids=[c[0] for c in _PARITY_ACCEPT])
def test_runtime_and_validator_agree_on_acceptance(case_id: str, schema: Any, claude_node: Any) -> None:
    """Schemas accepted by one surface must be accepted by both."""
    validator_rejected = _validator_rejects(schema)
    runtime_rejected = _runtime_rejects(claude_node, schema)
    assert validator_rejected == runtime_rejected, (
        f"Surface drift on '{case_id}': validator_rejected={validator_rejected}, runtime_rejected={runtime_rejected}"
    )
    assert not validator_rejected, f"'{case_id}' should be accepted — at least one surface wrongly rejected"


def test_claude_code_node_resolves_identically_via_package_and_direct_import() -> None:
    """Pin the lazy ``pflow.nodes.claude.__init__.py`` contract.

    The ``__getattr__``-based lazy resolution is load-bearing: it lets
    ``test_schema_validation.py`` import the predicates without dragging in
    ``claude_agent_sdk`` before the SDK mock binds (``tests/CLAUDE.md`` #17).
    A revert to ``from .claude_code import ClaudeCodeNode`` at package load
    would break that test file's coexistence with the mock — producing
    confusing ProcessError-style failures spread across unrelated tests
    rather than a clean signal that this contract changed.

    This test makes the contract explicit. Reverting the lazy init breaks
    HERE, not in cross-file ordering downstream.
    """
    import pflow.nodes.claude as pkg
    from pflow.nodes.claude.claude_code import ClaudeCodeNode as direct

    assert pkg.ClaudeCodeNode is direct


def test_runtime_and_validator_agree_on_max_turns_with_schema(claude_node: Any) -> None:
    """The cross-rule ``max_turns >= 2 when output_schema is set`` is enforced
    on both surfaces. Runtime checks happen in ``prep()`` (not ``_validate_schema``),
    so this case tests the full ``prep()`` path.
    """
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    params = {"output_schema": schema, "max_turns": 1, "prompt": "test"}

    diagnostics = WorkflowValidator._validate_claude_code_params("review", params)
    validator_rejected = any(d.severity == Severity.ERROR for d in diagnostics)

    claude_node.params = params
    runtime_rejected = False
    try:
        claude_node.prep({})
    except ValueError:
        runtime_rejected = True

    assert validator_rejected == runtime_rejected, (
        f"max_turns parity drift: validator={validator_rejected}, runtime={runtime_rejected}"
    )
    assert validator_rejected


# ---------------------------------------------------------------------------
# Issue #455: use_api_key billing flag.
# The node blanks ANTHROPIC_API_KEY for the Claude subprocess by default so an
# ambient (or `pflow settings set-env`-injected) key cannot silently override
# the user's Pro/Max subscription with per-token Console billing.
# ---------------------------------------------------------------------------


def test_use_api_key_defaults_false(claude_node):
    """Param absent → False → subscription billing."""
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep({})
    assert prep_res["use_api_key"] is False


def test_default_blanks_api_key_in_options(claude_node):
    """Default mode sets options.env = {ANTHROPIC_API_KEY: ""}.

    The SDK merges options.env OVER os.environ, so the empty-string override is
    what actually neutralizes an inherited key — omitting it would leave the
    inherited key intact (a dict merge cannot delete a base key).
    """
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep({})

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert mock_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": ""}


def test_default_scrub_only_touches_anthropic_key(claude_node):
    """Only ANTHROPIC_API_KEY is overridden; every other var still inherits."""
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep({})

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert list(mock_options.call_args.kwargs["env"].keys()) == ["ANTHROPIC_API_KEY"]


def test_use_api_key_true_does_not_scrub(claude_node):
    """Opt-in (True) leaves env untouched so the ambient key bills to Console."""
    claude_node.params = {"prompt": "test prompt", "use_api_key": True}
    prep_res = claude_node.prep({})
    assert prep_res["use_api_key"] is True

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert "env" not in mock_options.call_args.kwargs


def test_string_false_still_scrubs(claude_node):
    """Footgun guard: a templated string "false" must NOT enable API billing.

    Node params aren't coerced to bool at runtime and the string "false" is
    truthy in Python — a naive bool(value) would silently bill per token.
    """
    claude_node.params = {"prompt": "test prompt", "use_api_key": "false"}
    prep_res = claude_node.prep({})
    assert prep_res["use_api_key"] is False

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert mock_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": ""}


def test_string_true_opts_in(claude_node):
    """Templated string "true" opts into API billing (no scrub)."""
    claude_node.params = {"prompt": "test prompt", "use_api_key": "true"}
    prep_res = claude_node.prep({})
    assert prep_res["use_api_key"] is True

    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")

    assert "env" not in mock_options.call_args.kwargs


def test_use_api_key_invalid_value_raises(claude_node):
    """A non-bool, non-canonical value fails closed with a TypeError."""
    claude_node.params = {"prompt": "test prompt", "use_api_key": "maybe"}
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep({})
    assert "use_api_key must be true or false" in str(exc_info.value)


def test_use_api_key_accepts_int_0_and_1(claude_node):
    """Integer 0/1 is accepted (YAML coerces `- use_api_key: 1` to int, and the
    string forms "1"/"0" are already accepted). 2+ still fails closed."""
    v = claude_node._validate_use_api_key
    assert v(1) is True
    assert v(0) is False
    for bad in (2, -1, 42):
        with pytest.raises(TypeError):
            v(bad)


def test_default_does_not_mutate_os_environ(monkeypatch, claude_node):
    """The empty-string override must NOT touch os.environ — a sibling llm node
    in the same workflow keeps reading the real key for LiteLLM. This pins the
    decision so a future switch to os.environ.pop fails loudly (#455 review)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    claude_node.params = {"prompt": "test prompt"}
    prep_res = claude_node.prep({})
    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")
    # The subprocess env blanks the key...
    assert mock_options.call_args.kwargs["env"] == {"ANTHROPIC_API_KEY": ""}
    # ...but the process environment is untouched.
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-real"


def test_use_api_key_registered_as_bool_param():
    """use_api_key is a declared bool param — this drives the validator allow-list."""
    md = PflowMetadataExtractor().extract_metadata(ClaudeCodeNode)
    params = {p["key"]: p["type"] for p in md["params"]}
    assert params.get("use_api_key") == "bool"


# --- Auth-failure guidance (exec_fallback) ---


def test_is_auth_error_matches_only_auth_markers():
    """_is_auth_error matches CLI auth/billing markers, not generic failures."""
    assert ClaudeCodeNode._is_auth_error(Exception("Invalid API key · Fix external API key"))
    assert ClaudeCodeNode._is_auth_error(Exception("authentication_error: bad token"))
    assert ClaudeCodeNode._is_auth_error(Exception("Your credit balance is too low"))
    # Real not-logged-in result text — pins the narrowed "run /login" marker.
    assert ClaudeCodeNode._is_auth_error(Exception("Not logged in · Please run /login"))
    assert not ClaudeCodeNode._is_auth_error(Exception("Tool 'Bash' failed: exit 1"))
    assert not ClaudeCodeNode._is_auth_error(Exception("connection reset by peer"))
    # "oauth" marker was dropped: an MCP OAuth error surfaced inside a claude
    # subprocess must NOT be misclassified as a Claude billing failure (#455 review).
    assert not ClaudeCodeNode._is_auth_error(Exception("MCP server oauth flow failed"))
    # The bare "/login" substring was narrowed to "run /login" — an unrelated
    # /login path in agent output must no longer false-match.
    assert not ClaudeCodeNode._is_auth_error(Exception("POST /login returned 500"))


def test_exec_fallback_auth_default_suggests_subscription(claude_node):
    """Default-mode auth failure points to subscription first, API key second."""
    with pytest.raises(ValueError) as exc_info:
        claude_node.exec_fallback({"use_api_key": False}, Exception("authentication_error"))
    msg = str(exc_info.value)
    assert "claude auth login" in msg
    assert "- use_api_key: true" in msg


def test_exec_fallback_auth_with_api_key_suggests_fixing_key(claude_node):
    """Opt-in auth failure points to the Console key, not subscription setup."""
    with pytest.raises(ValueError) as exc_info:
        claude_node.exec_fallback({"use_api_key": True}, Exception("Your credit balance is too low"))
    msg = str(exc_info.value)
    assert "Anthropic Console" in msg
    assert "Remove `- use_api_key: true`" in msg
    assert "claude auth login" not in msg


def test_exec_fallback_non_auth_error_has_no_auth_guidance(claude_node):
    """Non-auth failures fall through to the generic message (no auth hint)."""
    with pytest.raises(ValueError) as exc_info:
        claude_node.exec_fallback({"use_api_key": False}, Exception("disk full"))
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


def test_invalid_api_key_surfaces_real_error_text_and_status(claude_node):
    """The real "Invalid API key" text + api_error_status are surfaced on re-raise,
    not the SDK's useless "...error result: success"."""
    claude_node.params = {"prompt": "do a thing", "use_api_key": True}

    async def mock_response(*args, **kwargs):
        # Mirrors the real CLI: error result carrying the real text + 401 is
        # yielded first, then the SDK raises a bare Exception with the subtype.
        yield ResultMessage(
            is_error=True,
            result="Invalid API key · Fix external API key",
            api_error_status=401,
        )
        raise Exception("Claude Code returned an error result: success")  # noqa: TRY002 - mirror SDK bare raise

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep({})
        with pytest.raises(RuntimeError) as exc_info:
            claude_node.exec(prep_res)

    assert "Invalid API key" in str(exc_info.value)
    assert "api_error_status=401" in str(exc_info.value)
    # The enriched exception is now recognized as auth, and exec_fallback gives the
    # use_api_key=True remediation (the key, not subscription setup).
    assert ClaudeCodeNode._is_auth_error(exc_info.value)
    with pytest.raises(ValueError) as fb:
        claude_node.exec_fallback(prep_res, exc_info.value)
    assert "Anthropic Console" in str(fb.value)
    assert "Remove `- use_api_key: true`" in str(fb.value)


def test_api_error_status_detected_even_without_text(claude_node):
    """A 401 with no usable result text is still recognized as auth via the
    structured status alone."""
    claude_node.params = {"prompt": "do a thing", "use_api_key": True}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(is_error=True, result=None, api_error_status=401)
        raise Exception("Claude Code returned an error result: success")  # noqa: TRY002 - mirror SDK bare raise

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep({})
        with pytest.raises(RuntimeError) as exc_info:
            claude_node.exec(prep_res)

    assert "api_error_status=401" in str(exc_info.value)
    assert ClaudeCodeNode._is_auth_error(exc_info.value)


def test_non_auth_error_result_stays_generic(claude_node):
    """A non-auth error result (no 401, no auth text) must NOT trigger auth
    guidance — surfaced detail is preserved but routed to the generic message."""
    claude_node.params = {"prompt": "do a thing"}

    async def mock_response(*args, **kwargs):
        yield ResultMessage(is_error=True, result="Tool failed: disk full", api_error_status=None)
        raise Exception("Claude Code returned an error result: error_during_execution")  # noqa: TRY002 - mirror SDK bare raise

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        prep_res = claude_node.prep({})
        with pytest.raises(RuntimeError) as exc_info:
            claude_node.exec(prep_res)

    assert not ClaudeCodeNode._is_auth_error(exc_info.value)
    with pytest.raises(ValueError) as fb:
        claude_node.exec_fallback(prep_res, exc_info.value)
    assert "claude auth login" not in str(fb.value)
    assert "disk full" in str(fb.value)
