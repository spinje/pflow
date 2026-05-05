"""LLM-level mock for testing without API calls.

The sole mock is ``MockLLMClient``, which patches
``pflow.core.llm_client.complete`` (and each consumer module's binding) and
returns ``AdapterResponse`` instances directly.
"""

import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from pflow.core.llm_client import AdapterResponse

# Shared default responses for known schemas — keyed by schema NAME (Pydantic
# class __name__ or JSON Schema "title"). MockLLMClient reads from this table
# so workflow-discovery tests get sensible defaults without explicit setup.
_DEFAULT_RESPONSES: dict[str, dict] = {
    "WorkflowDecision": {
        "found": False,
        "workflow_name": None,
        "confidence": 0.3,
        "reasoning": "No exact match found",
    },
    "ComponentSelection": {
        "node_ids": ["read-file", "write-file"],
        "workflow_names": [],
        "reasoning": "Selected basic file nodes",
    },
    "ParameterDiscovery": {"parameters": {}, "stdin_type": None, "reasoning": "No parameters found"},
    "ParameterExtraction": {
        "extracted": {},
        "missing": [],
        "confidence": 0.8,
        "reasoning": "Parameters extracted",
    },
    "FlowIR": {
        "ir_version": "0.1.0",
        "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "{{input_file}}"}}],
        "edges": [],
        "start_node": "read",
        "inputs": {"input_file": {"type": "string", "description": "Input file path"}},
        "outputs": {},
    },
    "WorkflowMetadata": {
        "suggested_name": "test-workflow",
        "description": "A test workflow",
        "search_keywords": ["test"],
        "capabilities": ["testing"],
        "typical_use_cases": ["unit tests"],
    },
    "FilteredFields": {
        "included_fields": ["field0", "field1", "field2"],
        "reasoning": "Default mock: kept first 3 fields",
    },
}


def _schema_name(schema: Any) -> Optional[str]:
    """Extract a schema's name for default-response lookup.

    Accepts either a Pydantic class (legacy callers) or a JSON Schema dict
    (new callers using ``Class.model_json_schema()``). Returns the class
    name / dict ``title``, or None if neither shape is recognized.
    """
    if schema is None:
        return None
    # Pydantic class: has __name__
    if hasattr(schema, "__name__"):
        return schema.__name__
    # JSON Schema dict: convention is to put the original class name in 'title'
    if isinstance(schema, dict):
        title = schema.get("title")
        if isinstance(title, str):
            return title
    return None


@dataclass
class MockLLMClient:
    """Mock for ``pflow.core.llm_client.complete``.

    Drop-in replacement: same signature, returns ``AdapterResponse`` instances
    directly (no ``Mock`` callables — the dataclass shape is part of the
    contract).

    Resolution chain: exact ``model+schema`` match → wildcard ``*+schema``
    match → ``_DEFAULT_RESPONSES`` schema default → ``{"response": "mock
    response"}`` fallback.

    Cost reporting:
        ``cost_usd`` defaults to ``None`` in the returned usage dict. This
        matches production behavior when LiteLLM has no pricing data for a
        model (custom endpoints, brand-new models, Ollama). Tests that need
        a specific cost should pass ``cost_usd=`` to ``set_response`` —
        making the test self-documenting about what cost it expects.

    ``call_history`` keeps the legacy 500-char prompt truncation (several
    existing tests assert against the boundary). ``call_history_full`` is
    parallel and untruncated, added here so future cache-structure tests
    (Phase B/C) can verify full message assembly.
    """

    call_history: list[dict] = field(default_factory=list)
    call_history_full: list[dict] = field(default_factory=list)
    _responses: dict[str, dict] = field(default_factory=dict)
    _costs: dict[str, Optional[float]] = field(default_factory=dict)
    _warnings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Task 159 C1.2: per-(model,schema) cache-token staging. Production
    # callers populate via ``set_response`` so cache-hit scenarios surface at
    # the test seam. Parallel-dict pattern matching ``_costs`` / ``_warnings``.
    _cache_creation_tokens: dict[str, int] = field(default_factory=dict)
    _cache_read_tokens: dict[str, int] = field(default_factory=dict)

    def set_response(
        self,
        model: str,
        schema: Any,
        response: Any,
        *,
        cost_usd: Optional[float] = None,
        warnings: list[dict[str, Any]] | None = None,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        """Configure a response for a (model, schema) pair.

        **Full-replacement contract** — each call OVERWRITES every staged
        field for the (model, schema) key, including fields not passed in
        this call. Args you don't specify revert to their defaults
        (``cost_usd=None``, ``warnings=[]``, ``cache_creation_input_tokens=0``,
        ``cache_read_input_tokens=0``). To layer changes across calls, pass
        ALL the fields you want preserved on every call. Mirrors pytest's
        ``MagicMock.return_value`` semantics — calls are full replacements,
        not merges.

        Args:
            model: Model name, or ``"*"`` for any model.
            schema: Pydantic class OR JSON Schema dict OR None (for text).
            response: Response dict; serialized to JSON for ``AdapterResponse.text``.
            cost_usd: Optional ``cost_usd`` to set on the returned usage dict.
                When ``None`` (default), the mock leaves ``cost_usd: None`` —
                matches production behavior for unknown-pricing models.
            warnings: Optional structured adapter warnings (each entry has
                ``kind``, ``text``, and ``context``). Defaults to ``[]``.
            cache_creation_input_tokens: Stage the cache-write token count
                for the returned ``usage`` dict. Default ``0`` matches the
                pre-Task-159 mock behavior. Used by C-phase rendering tests
                + E.1 trace-format tests that assert on cache telemetry.
            cache_read_input_tokens: Stage the cache-read token count for
                the returned ``usage`` dict. Default ``0``.
        """
        name = _schema_name(schema) or "text"
        key = f"{model}:{name}"
        self._responses[key] = response
        self._costs[key] = cost_usd
        self._warnings[key] = list(warnings or [])
        self._cache_creation_tokens[key] = cache_creation_input_tokens
        self._cache_read_tokens[key] = cache_read_input_tokens

    def get_response(self, model: str, schema: Any) -> dict:
        """Resolve a configured or default response."""
        name = _schema_name(schema) or "text"

        # 1. Exact model+schema match
        exact = self._responses.get(f"{model}:{name}")
        if exact is not None:
            return exact

        # 2. Wildcard model match
        wildcard = self._responses.get(f"*:{name}")
        if wildcard is not None:
            return wildcard

        # 3. Schema-based default
        if name != "text" and name in _DEFAULT_RESPONSES:
            return _DEFAULT_RESPONSES[name]

        # 4. Final fallback
        return {"response": "mock response"}

    def _get_cost(self, model: str, schema: Any) -> Optional[float]:
        """Resolve the configured cost for a (model, schema) pair.

        Returns ``None`` when no cost was set for the matching key — matches
        production behavior for unknown-pricing models.
        """
        name = _schema_name(schema) or "text"
        if f"{model}:{name}" in self._costs:
            return self._costs[f"{model}:{name}"]
        if f"*:{name}" in self._costs:
            return self._costs[f"*:{name}"]
        return None

    def _get_warnings(self, model: str, schema: Any) -> list[dict[str, Any]]:
        """Resolve configured warnings for a (model, schema) pair."""
        name = _schema_name(schema) or "text"
        if f"{model}:{name}" in self._warnings:
            return list(self._warnings[f"{model}:{name}"])
        if f"*:{name}" in self._warnings:
            return list(self._warnings[f"*:{name}"])
        return []

    def _get_cache_creation(self, model: str, schema: Any) -> int:
        """Resolve staged cache-write token count for a (model, schema) pair."""
        name = _schema_name(schema) or "text"
        if f"{model}:{name}" in self._cache_creation_tokens:
            return self._cache_creation_tokens[f"{model}:{name}"]
        if f"*:{name}" in self._cache_creation_tokens:
            return self._cache_creation_tokens[f"*:{name}"]
        return 0

    def _get_cache_read(self, model: str, schema: Any) -> int:
        """Resolve staged cache-read token count for a (model, schema) pair."""
        name = _schema_name(schema) or "text"
        if f"{model}:{name}" in self._cache_read_tokens:
            return self._cache_read_tokens[f"{model}:{name}"]
        if f"*:{name}" in self._cache_read_tokens:
            return self._cache_read_tokens[f"*:{name}"]
        return 0

    def reset(self) -> None:
        """Clear call history and configured responses."""
        self.call_history.clear()
        self.call_history_full.clear()
        self._responses.clear()
        self._costs.clear()
        self._warnings.clear()
        self._cache_creation_tokens.clear()
        self._cache_read_tokens.clear()

    # The patched function — must mirror llm_client.complete()'s signature.
    def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: Optional[str | list[dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        attachments: Optional[list] = None,
        schema: Optional[dict] = None,
        reasoning_kwargs: Optional[dict] = None,
        model_options: Optional[dict] = None,
        timeout: Optional[float] = None,
        trace_hook: Optional[Any] = None,
        user_message_blocks: Optional[list[dict[str, Any]]] = None,
    ) -> AdapterResponse:
        """Record the call and return a mocked AdapterResponse.

        The trace hook (when provided) is invoked with ``before_call`` and
        ``after_call`` events to mirror the real adapter's contract — this
        lets trace-related tests work against the mock.
        """
        # Record (truncated) — preserve the 500-char boundary that several
        # existing tests assert against.
        truncated = prompt[:500] if len(prompt) > 500 else prompt
        record = {
            "model": model,
            "prompt": truncated,
            "system": system,
            "schema": _schema_name(schema),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "attachments": attachments,
            "reasoning_kwargs": reasoning_kwargs,
            "model_options": model_options,
            "timeout": timeout,
            "user_message_blocks": user_message_blocks,
        }
        self.call_history.append(record)

        # Untruncated parallel record for cache-structure verification (Phase B/C)
        full_record = dict(record)
        full_record["prompt"] = prompt
        self.call_history_full.append(full_record)

        # Trace hook — fires for tests that exercise trace integration.
        # Mirror adapter: tracing must never break the call. The ``system``
        # field carries the effective system content (str / list[dict] /
        # None) so trace 2.2.0 ``llm_system`` capture works against the mock.
        if trace_hook is not None:
            with contextlib.suppress(Exception):
                trace_hook({"event": "before_call", "model": model, "prompt": prompt, "system": system})

        # Resolve response
        response_data = self.get_response(model, schema)
        text = json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)

        # Build AdapterResponse with a usage dict matching the adapter's
        # stable shape. Token counts are arbitrary mock values — tests that
        # care about specific values should set their own response.
        # ``cost_usd`` is ``None`` unless the test set one via
        # ``set_response(..., cost_usd=...)``. Mirrors production behavior
        # for unknown-pricing models (LiteLLM returns None there too).
        input_tokens = max(1, len(prompt.split()))
        # Mirror the adapter's stable usage shape exactly. ``thinking_tokens``
        # / ``thinking_budget`` default to 0 (matching non-reasoning calls);
        # tests that need specific reasoning-token values can construct an
        # AdapterResponse directly via monkeypatch.
        usage = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": 50,
            "total_tokens": input_tokens + 50,
            "cache_creation_input_tokens": self._get_cache_creation(model, schema),
            "cache_read_input_tokens": self._get_cache_read(model, schema),
            "thinking_tokens": 0,
            "thinking_budget": 0,
            "cost_usd": self._get_cost(model, schema),
        }

        response = AdapterResponse(
            text=text,
            usage=usage,
            model=model,
            has_schema=schema is not None,
            warnings=self._get_warnings(model, schema),
        )

        if trace_hook is not None:
            with contextlib.suppress(Exception):
                trace_hook({"event": "after_call", "model": model, "response": response})

        return response


def create_mock_llm_client() -> MockLLMClient:
    """Factory function to create a MockLLMClient."""
    return MockLLMClient()
