"""Claude Code Agentic Node package.

``ClaudeCodeNode`` is loaded lazily via ``__getattr__`` so importing the
``schema_validation`` submodule (or any other lightweight submodule) doesn't
eagerly drag in ``claude_agent_sdk``. The test suite injects an SDK mock at
module load time (see ``tests/CLAUDE.md`` pitfall #17); an eager re-export
here would resolve the real SDK before the mock binds.
"""

from typing import TYPE_CHECKING, Any

__all__ = ["ClaudeCodeNode"]

if TYPE_CHECKING:  # static type checkers see the symbol; runtime stays lazy
    from .claude_code import ClaudeCodeNode


def __getattr__(name: str) -> Any:
    if name == "ClaudeCodeNode":
        from .claude_code import ClaudeCodeNode

        return ClaudeCodeNode
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
