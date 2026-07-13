"""Backend contract for the unified agent node."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AgentResult:
    """Backend-neutral result returned by an agent adapter."""

    result_text: str = ""
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    progress_events: list[dict[str, Any]] = field(default_factory=list)
    structured_output: Any = None
    is_error: bool = False
    error_text: str | None = None


class AgentBackend(Protocol):
    """Operations an agent backend supplies to :class:`AgentNode`."""

    default_model: str | None

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate backend-owned parameters and return prepared values."""

    def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
        """Run one agent turn."""

    def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any] | None:
        """Build options for continuing a prior result, or return ``None``."""

    def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
        """Translate a backend exception into an actionable public error."""

    def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
        """Build backend-specific diagnostic context for a schema soft-fail."""
