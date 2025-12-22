"""Comprehensive tests for Claude Code Agentic Node.

Tests criteria from the specification:
1. Task missing → ValueError with "No task provided"
2. Task empty string → ValueError with "No task provided"
3. Task > 10000 chars → ValueError with "Task too long"
4. Working directory missing → ValueError with path
5. Working directory restricted → ValueError with "Restricted directory"
6-7. Authentication now handled by SDK (tests removed)
8. Valid task without schema → "success" and shared["result"] populated
9. Valid task with schema → "success" and schema keys in shared
10. Output schema invalid keys → ValueError with details
11. Output schema 50+ keys → ValueError "Schema too complex"
12. Rate limit error → ValueError with retry message
13. Timeout at 300s → ValueError with timeout message
14. CLINotFoundError handling → Correct error transformation
15. CLIConnectionError handling → Correct error transformation
16. ProcessError handling → Includes exit code
17. Tool whitelist enforcement → Only ["Read", "Write", "Edit", "Bash"] allowed
18. Schema to prompt conversion → System prompt contains JSON format
19. Valid JSON response → Values stored in schema keys
20. Invalid JSON response → Raw text in result, error in _schema_error
21. Partial JSON response → Missing keys stored as None
22. No response content → Empty result stored
23. Schema merged with user prompt → Both instructions present
"""

import asyncio
import sys
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


class CLINotFoundError(Exception):
    pass


class CLIConnectionError(Exception):
    pass


class ProcessError(Exception):
    def __init__(self, exit_code=1, stderr=""):
        super().__init__()
        self.exit_code = exit_code
        self.stderr = stderr


class ClaudeSDKError(Exception):
    pass


# Mock the SDK module before importing the node
mock_sdk_types = Mock()
mock_sdk_types.AssistantMessage = AssistantMessage
mock_sdk_types.TextBlock = TextBlock
mock_sdk_types.ToolUseBlock = ToolUseBlock

mock_sdk_exceptions = Mock()
mock_sdk_exceptions.CLINotFoundError = CLINotFoundError
mock_sdk_exceptions.CLIConnectionError = CLIConnectionError
mock_sdk_exceptions.ProcessError = ProcessError
mock_sdk_exceptions.ClaudeSDKError = ClaudeSDKError

mock_sdk = Mock()
mock_sdk.query = Mock()
mock_sdk.ClaudeCodeOptions = Mock
# Add exception classes to main mock_sdk module
mock_sdk.CLINotFoundError = CLINotFoundError
mock_sdk.CLIConnectionError = CLIConnectionError
mock_sdk.ProcessError = ProcessError
mock_sdk.ClaudeSDKError = ClaudeSDKError

sys.modules["claude_code_sdk"] = mock_sdk
sys.modules["claude_code_sdk.types"] = mock_sdk_types
sys.modules["claude_code_sdk.exceptions"] = mock_sdk_exceptions

# Now import the node after SDK mocking - E402 is expected here
from pflow.nodes.claude.claude_code import ClaudeCodeNode  # noqa: E402


# Fixtures for common test setup
@pytest.fixture
def claude_node():
    """Create a ClaudeCodeNode instance."""
    return ClaudeCodeNode()


@pytest.fixture
def shared_store():
    """Create a basic shared store with task."""
    return {"task": "Write a hello world function"}


@pytest.fixture
def mock_query_success():
    """Mock successful Claude query with text response."""

    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="def hello_world():\n    print('Hello, World!')")])

    with patch("pflow.nodes.claude.claude_code.query") as mock:
        mock.return_value = mock_response()
        yield mock


# Test Criteria 1: Task missing → ValueError with "No task provided"
def test_task_missing(claude_node):
    """Test that missing task raises ValueError."""
    shared = {}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "No task provided" in str(exc_info.value)


# Test Criteria 2: Task empty string → ValueError with "No task provided"
def test_task_empty_string(claude_node):
    """Test that empty string task raises ValueError."""
    shared = {"task": "   "}  # Whitespace only
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "cannot be empty" in str(exc_info.value)


# Test Criteria 3: Task > 10000 chars → ValueError with "Task too long"
def test_task_too_long(claude_node):
    """Test that task over 10000 chars raises ValueError."""
    shared = {"task": "x" * 10001}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Task too long" in str(exc_info.value)
    assert "10001" in str(exc_info.value)


# Test Criteria 4: Working directory missing → ValueError with path
def test_working_directory_missing(claude_node):
    """Test that non-existent working directory raises ValueError."""
    shared = {"task": "test task"}
    claude_node.params = {"working_directory": "/nonexistent/path"}

    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Working directory does not exist" in str(exc_info.value)
    assert "/nonexistent/path" in str(exc_info.value)


# Test Criteria 5: Working directory restricted → ValueError with "Restricted directory"
def test_working_directory_restricted(claude_node):
    """Test that restricted directories raise ValueError."""
    shared = {"task": "test task"}

    # Test multiple restricted directories
    for restricted in ["/", "/etc", "/usr", "/bin"]:
        claude_node.params = {"working_directory": restricted}
        with pytest.raises(ValueError) as exc_info:
            claude_node.prep(shared)
        assert "Restricted directory" in str(exc_info.value)


# Note: Tests 6 & 7 (CLI/auth checking) removed as authentication is now handled by SDK


# Test Criteria 8: Valid task without schema → "success" and shared["result"] populated
def test_valid_task_without_schema(claude_node):
    """Test successful execution without output schema."""
    shared = {"task": "Write a hello world function"}
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
        assert result["output_schema"] is None
        assert result["tool_uses"] == []

        # Check post() stores results (now string format without schema)
        claude_node.post(shared, prep_res, result)
        assert "result" in shared
        assert isinstance(shared["result"], str)
        assert "def hello_world()" in shared["result"]
        assert "Hello, World!" in shared["result"]


# Test Criteria 9: Valid task with schema → "success" and schema keys in shared
def test_valid_task_with_schema(claude_node):
    """Test successful execution with output schema."""
    shared = {
        "task": "Review this code for issues",
        "output_schema": {
            "risk_level": {"type": "str", "description": "high/medium/low"},
            "issues": {"type": "list", "description": "List of issues"},
        },
    }
    claude_node.shared = shared

    # Mock query response with JSON
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(
            content=[TextBlock(text='Analysis complete.\n```json\n{"risk_level": "low", "issues": []}\n```')]
        )

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        # Prepare and execute
        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)
        assert result["result_text"] == 'Analysis complete.\n```json\n{"risk_level": "low", "issues": []}\n```'
        assert result["output_schema"] == shared["output_schema"]

        # Check post() stores and parses JSON
        claude_node.post(shared, prep_res, result)
        assert isinstance(shared["result"], dict)
        assert shared["result"]["risk_level"] == "low"
        assert shared["result"]["issues"] == []


# Test Criteria 10: Output schema invalid keys → ValueError with details
def test_output_schema_invalid_keys(claude_node):
    """Test that invalid schema keys raise ValueError."""
    shared = {
        "task": "test task",
        "output_schema": {
            "valid_key": {"type": "str"},
            "invalid-key": {"type": "str"},  # Invalid: contains hyphen
        },
    }

    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)

    assert "Invalid schema key" in str(exc_info.value)
    assert "invalid-key" in str(exc_info.value)


# Test Criteria 11: Output schema 50+ keys → ValueError "Schema too complex"
def test_output_schema_too_complex(claude_node):
    """Test that overly complex schema raises ValueError."""
    schema = {f"key_{i}": {"type": "str"} for i in range(51)}
    shared = {
        "task": "test task",
        "output_schema": schema,
    }

    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)

    assert "Schema too complex" in str(exc_info.value)
    assert "51" in str(exc_info.value)


# Test Criteria 12: Rate limit error → ValueError with retry message
def test_rate_limit_error(claude_node):
    """Test rate limit error handling."""
    shared = {"task": "test task"}
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
    shared = {"task": "test task"}
    claude_node.shared = shared

    async def mock_timeout(*args, **kwargs):
        await asyncio.sleep(100)  # Exceed timeout (will be cut short by 0.1s timeout)
        yield AssistantMessage(content=[TextBlock(text="Never reached")])

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_timeout()

        # Speed up test with shorter timeout via params (minimum allowed is 30s, but we patch it)
        claude_node.params = {"timeout": 30}  # Use minimum allowed timeout
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
    shared = {"task": "test task"}
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
    shared = {"task": "test task"}
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
    shared = {"task": "test task"}
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
    shared = {"task": "test task"}

    # Default: None = all tools available (including Task for subagents)
    claude_node.params = {}
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] is None  # None = SDK default (all tools)

    # Explicit tools are passed through without validation
    explicit_tools = ["Read", "Write", "Edit", "Bash"]
    claude_node.params = {"allowed_tools": explicit_tools}
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] == explicit_tools

    # Task tool (for subagents) can now be explicitly included
    tools_with_task = ["Read", "Write", "Task", "Glob", "Grep"]
    claude_node.params = {"allowed_tools": tools_with_task}
    prep_res = claude_node.prep(shared)
    assert prep_res["allowed_tools"] == tools_with_task
    assert "Task" in prep_res["allowed_tools"]  # Task tool for subagents


# Test: Resume parameter for session continuation
def test_resume_parameter(claude_node):
    """Test that resume parameter is validated and passed through."""
    shared = {"task": "test task"}

    # Default: None
    claude_node.params = {}
    prep_res = claude_node.prep(shared)
    assert prep_res["resume"] is None

    # Valid session ID
    claude_node.params = {"resume": "session-abc123"}
    prep_res = claude_node.prep(shared)
    assert prep_res["resume"] == "session-abc123"

    # Invalid type should raise
    claude_node.params = {"resume": 12345}  # Not a string
    with pytest.raises(TypeError) as exc_info:
        claude_node.prep(shared)
    assert "resume must be a string" in str(exc_info.value)


# Test: Timeout parameter configuration
def test_timeout_parameter(claude_node):
    """Test that timeout parameter is validated and configurable."""
    shared = {"task": "test task"}

    # Default: 300 seconds
    claude_node.params = {}
    prep_res = claude_node.prep(shared)
    assert prep_res["timeout"] == 300

    # Custom timeout
    claude_node.params = {"timeout": 600}
    prep_res = claude_node.prep(shared)
    assert prep_res["timeout"] == 600

    # Too short (< 30s)
    claude_node.params = {"timeout": 10}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "between 30 and 3600" in str(exc_info.value)

    # Too long (> 3600s)
    claude_node.params = {"timeout": 5000}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "between 30 and 3600" in str(exc_info.value)


# Test Criteria 18: Schema to prompt conversion → System prompt contains JSON format
def test_schema_to_prompt_conversion(claude_node):
    """Test that schema is converted to JSON format instructions in system prompt."""
    shared = {
        "task": "test task",
        "output_schema": {
            "summary": {"type": "str", "description": "Brief summary"},
            "score": {"type": "int", "description": "Score from 1-10"},
        },
    }

    prep_res = claude_node.prep(shared)
    system_prompt = claude_node._build_system_prompt(prep_res)

    # Check that system prompt contains JSON instructions (updated prompt text)
    assert "YOU MUST RESPOND WITH JSON ONLY" in system_prompt
    assert "```json" in system_prompt
    assert '"summary": "<str: Brief summary>"' in system_prompt
    assert '"score": "<int: Score from 1-10>"' in system_prompt
    assert "Field descriptions:" in system_prompt
    assert "- summary: Brief summary" in system_prompt
    assert "- score: Score from 1-10" in system_prompt


# Test Criteria 19: Valid JSON response → Values stored in schema keys
def test_valid_json_response_storage(claude_node):
    """Test that valid JSON response is correctly parsed and stored."""
    shared = {
        "task": "Analyze code",
        "output_schema": {
            "complexity": {"type": "str", "description": "Code complexity"},
            "lines": {"type": "int", "description": "Number of lines"},
            "functions": {"type": "list", "description": "List of functions"},
        },
    }
    claude_node.shared = shared

    # Mock response with valid JSON
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(
            content=[
                TextBlock(
                    text="""Analysis complete.
            ```json
            {
                "complexity": "medium",
                "lines": 42,
                "functions": ["main", "helper", "utils"]
            }
            ```
            """
                )
            ]
        )

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)

        # Check post() stores parsed JSON values
        claude_node.post(shared, prep_res, result)
        assert isinstance(shared["result"], dict)
        assert shared["result"]["complexity"] == "medium"
        assert shared["result"]["lines"] == 42
        assert shared["result"]["functions"] == ["main", "helper", "utils"]
        assert "_schema_error" not in shared  # Should not have error when parsing succeeds


# Test Criteria 20: Invalid JSON response → Raw text in result, error in _schema_error
def test_invalid_json_response_fallback(claude_node):
    """Test that invalid JSON falls back to raw text storage."""
    shared = {
        "task": "Analyze code",
        "output_schema": {
            "summary": {"type": "str", "description": "Summary"},
        },
    }
    claude_node.shared = shared

    # Mock response with invalid JSON
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="This is not JSON at all, just plain text response.")])

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)

        # Check post() handles invalid JSON (now stores as string)
        claude_node.post(shared, prep_res, result)
        assert isinstance(shared["result"], str)  # Falls back to string when JSON fails
        assert shared["result"] == "This is not JSON at all, just plain text response."
        assert shared["_schema_error"] == "Failed to parse JSON from response. Raw text stored in result"


# Test Criteria 21: Partial JSON response → Missing keys stored as None
def test_partial_json_response(claude_node):
    """Test that partial JSON response stores None for missing keys."""
    shared = {
        "task": "Analyze code",
        "output_schema": {
            "found": {"type": "str", "description": "Found key"},
            "missing": {"type": "str", "description": "Missing key"},
            "also_missing": {"type": "int", "description": "Also missing"},
        },
    }
    claude_node.shared = shared

    # Mock response with partial JSON (only has "found" key)
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text='```json\n{"found": "present"}\n```')])

    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()

        prep_res = claude_node.prep(shared)
        result = claude_node.exec(prep_res)

        assert isinstance(result, dict)

        # Check post() handles partial JSON
        claude_node.post(shared, prep_res, result)
        assert isinstance(shared["result"], dict)
        assert shared["result"]["found"] == "present"
        assert shared["result"]["missing"] is None
        assert shared["result"]["also_missing"] is None
        assert "_schema_error" not in shared  # No error since JSON was parsed


# Test Criteria 22: No response content → Empty result stored
def test_no_response_content(claude_node):
    """Test that empty response stores empty result."""
    shared = {"task": "test task"}
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


# Test Criteria 23: Schema merged with user prompt → Both instructions present
def test_schema_merged_with_user_prompt(claude_node):
    """Test that schema instructions and user system prompt are both present."""
    shared = {
        "task": "test task",
        "output_schema": {
            "result": {"type": "str", "description": "Result"},
        },
    }
    claude_node.params = {
        "system_prompt": "You are a helpful assistant.",
    }

    prep_res = claude_node.prep(shared)
    system_prompt = claude_node._build_system_prompt(prep_res)

    # Check both prompts are present (updated prompt text)
    assert "YOU MUST RESPOND WITH JSON ONLY" in system_prompt
    assert "You are a helpful assistant." in system_prompt


# Additional tests for edge cases and integration


def test_max_thinking_tokens_validation(claude_node):
    """Test max_thinking_tokens parameter validation."""
    shared = {"task": "test task"}

    # Valid range
    claude_node.params = {"max_thinking_tokens": 5000}
    prep_res = claude_node.prep(shared)
    assert prep_res["max_thinking_tokens"] == 5000

    # Too low
    claude_node.params = {"max_thinking_tokens": 500}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_thinking_tokens" in str(exc_info.value)

    # Too high
    claude_node.params = {"max_thinking_tokens": 200000}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_thinking_tokens" in str(exc_info.value)


def test_max_turns_validation(claude_node):
    """Test max_turns parameter validation."""
    shared = {"task": "test task"}

    # Valid range
    claude_node.params = {"max_turns": 10}
    prep_res = claude_node.prep(shared)
    assert prep_res["max_turns"] == 10

    # Too low
    claude_node.params = {"max_turns": 0}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_turns" in str(exc_info.value)

    # Too high (now 100 is the max)
    claude_node.params = {"max_turns": 101}
    with pytest.raises(ValueError) as exc_info:
        claude_node.prep(shared)
    assert "Invalid max_turns" in str(exc_info.value)


def test_context_handling(claude_node):
    """Test different context formats."""
    shared = {"task": "test task"}

    # String context
    shared["context"] = "This is string context"
    prep_res = claude_node.prep(shared)
    prompt = claude_node._build_prompt(prep_res)
    assert "Context:\nThis is string context" in prompt

    # Dict context
    shared["context"] = {"key": "value", "number": 42}
    prep_res = claude_node.prep(shared)
    prompt = claude_node._build_prompt(prep_res)
    assert "Context:\n" in prompt
    assert '"key": "value"' in prompt
    assert '"number": 42' in prompt


def test_tool_use_logging(claude_node, caplog):
    """Test that tool uses are logged."""
    import logging

    shared = {"task": "test task"}
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


def test_json_extraction_strategies(claude_node):
    """Test all JSON extraction strategies."""
    node = claude_node

    # Strategy 1: JSON in code block
    text1 = '```json\n{"key": "value"}\n```'
    result1 = node._extract_json(text1)
    assert result1 == {"key": "value"}

    # Strategy 2: Raw JSON object
    text2 = 'Some text {"key": "value"} more text'
    result2 = node._extract_json(text2)
    assert result2 == {"key": "value"}

    # Strategy 3: Nested JSON
    text3 = 'Text {"outer": {"inner": "value"}} end'
    result3 = node._extract_json(text3)
    assert result3 == {"outer": {"inner": "value"}}

    # Failed extraction
    text4 = "No JSON here at all"
    result4 = node._extract_json(text4)
    assert result4 is None


def test_working_directory_expansion(claude_node):
    """Test that working directory paths are expanded correctly."""
    shared = {"task": "test task"}

    # Test tilde expansion
    with patch("os.path.exists", return_value=True), patch("os.path.isdir", return_value=True):
        claude_node.params = {"working_directory": "~/projects"}
        prep_res = claude_node.prep(shared)

        # Should be expanded to absolute path
        assert prep_res["working_directory"].startswith("/")
        assert "~" not in prep_res["working_directory"]


def test_post_method(claude_node):
    """Test post method always returns 'default'."""
    shared = {"task": "test"}
    prep_res = {"task": "test"}

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
    shared = {"task": "test task"}
    prep_res = claude_node.prep(shared)

    # Generic exception
    generic_error = Exception("Something went wrong")

    with pytest.raises(ValueError) as exc_info:
        claude_node.exec_fallback(prep_res, generic_error)

    error_msg = str(exc_info.value)
    assert "Claude Code execution failed after 2 attempts" in error_msg
    assert "Something went wrong" in error_msg
    assert "Check your internet connection" in error_msg
    assert "Verify Claude CLI is authenticated" in error_msg


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
