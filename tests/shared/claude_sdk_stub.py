"""Mock ``claude_agent_sdk`` for the claude-code node tests.

The real ``claude_agent_sdk`` is installed in the dev/test venv, and
``pflow.nodes.claude.claude_code`` binds its SDK names (``query``, ``ResultMessage``,
``ProcessError``, ...) at IMPORT time via ``from claude_agent_sdk import ...``. Those
names are therefore fixed to whatever is in ``sys.modules`` the first time the node is
imported in a process.

``install()`` puts these mocks into ``sys.modules`` so the node binds to them. It is
called from ``tests/test_nodes/test_claude/conftest.py``, which pytest loads before any
test module in that directory — so the mock is in place before the node is first
imported, regardless of which test file pytest processes first.

Previously this injection lived at module scope inside ``test_claude_code.py`` and
silently broke whenever another test (e.g. ``test_schema_coercion.py``) imported the
node first: the node then bound to the REAL SDK classes, and the mock ``ResultMessage`` /
``ProcessError`` no longer satisfied the node's ``isinstance`` checks. See tests/CLAUDE.md #17.

LOAD-BEARING: ``ResultMessage`` is a real ``@dataclass`` (not an auto-Mock) and is
assigned into the mock ``types`` module BEFORE the ``sys.modules`` injection, because the
node probes ``ResultMessage.__annotations__`` at import time to verify SDK
structured-output support.
"""

import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock


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


def install() -> None:
    """Inject the mock ``claude_agent_sdk`` modules into ``sys.modules``.

    Idempotent and safe to call repeatedly (it re-points the same mock objects). Must
    run before ``pflow.nodes.claude.claude_code`` is first imported in the process.
    """
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
    # Add exception classes to the main mock_sdk module too.
    mock_sdk.CLINotFoundError = CLINotFoundError
    mock_sdk.CLIConnectionError = CLIConnectionError
    mock_sdk.ProcessError = ProcessError
    mock_sdk.ClaudeSDKError = ClaudeSDKError

    sys.modules["claude_agent_sdk"] = mock_sdk
    sys.modules["claude_agent_sdk.types"] = mock_sdk_types
    sys.modules["claude_agent_sdk.exceptions"] = mock_sdk_exceptions
