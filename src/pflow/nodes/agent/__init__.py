"""Unified agent node package.

``AgentNode`` is loaded lazily via ``__getattr__`` so importing the
``schema_validation`` submodule (or any other lightweight submodule) doesn't
eagerly drag in ``claude_agent_sdk``. Backend modules are imported only after
the node selects a backend at runtime.
"""

from typing import TYPE_CHECKING, Any

__all__ = ["AgentNode"]

if TYPE_CHECKING:  # static type checkers see the symbol; runtime stays lazy
    from .agent_node import AgentNode


def __getattr__(name: str) -> Any:
    if name == "AgentNode":
        from .agent_node import AgentNode

        return AgentNode
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
