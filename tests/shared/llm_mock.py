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

    def set_response(
        self,
        model: str,
        schema: Any,
        response: dict,
        *,
        cost_usd: Optional[float] = None,
    ) -> None:
        """Configure a response for a (model, schema) pair.

        Args:
            model: Model name, or ``"*"`` for any model.
            schema: Pydantic class OR JSON Schema dict OR None (for text).
            response: Response dict; serialized to JSON for ``AdapterResponse.text``.
            cost_usd: Optional ``cost_usd`` to set on the returned usage dict.
                When ``None`` (default), the mock leaves ``cost_usd: None`` —
                matches production behavior for unknown-pricing models.
        """
        name = _schema_name(schema) or "text"
        key = f"{model}:{name}"
        self._responses[key] = response
        self._costs[key] = cost_usd

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

    def reset(self) -> None:
        """Clear call history and configured responses."""
        self.call_history.clear()
        self.call_history_full.clear()
        self._responses.clear()
        self._costs.clear()

    # The patched function — must mirror llm_client.complete()'s signature.
    def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        attachments: Optional[list] = None,
        schema: Optional[dict] = None,
        reasoning_kwargs: Optional[dict] = None,
        model_options: Optional[dict] = None,
        timeout: Optional[float] = None,
        trace_hook: Optional[Any] = None,
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
        }
        self.call_history.append(record)

        # Untruncated parallel record for cache-structure verification (Phase B/C)
        full_record = dict(record)
        full_record["prompt"] = prompt
        self.call_history_full.append(full_record)

        # Trace hook — fires for tests that exercise trace integration.
        # Mirror adapter: tracing must never break the call.
        if trace_hook is not None:
            with contextlib.suppress(Exception):
                trace_hook({"event": "before_call", "model": model, "prompt": prompt})

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
        usage = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": 50,
            "total_tokens": input_tokens + 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cost_usd": self._get_cost(model, schema),
        }

        response = AdapterResponse(
            text=text,
            usage=usage,
            model=model,
            has_schema=schema is not None,
        )

        if trace_hook is not None:
            with contextlib.suppress(Exception):
                trace_hook({"event": "after_call", "model": model, "response": response})

        return response


def create_mock_llm_client() -> MockLLMClient:
    """Factory function to create a MockLLMClient."""
    return MockLLMClient()
