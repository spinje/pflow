"""LLM-level mock for testing without API calls.

This module currently provides TWO parallel mocks — they coexist during
Task 158 Phase A.4-A.7 while callers migrate from the llm-library path
to the new pflow-owned LiteLLM adapter:

* ``MockLLMModel`` / ``MockGetModel`` — legacy. Patches ``llm.get_model``.
  Used by tests that have not yet been migrated to the new adapter.
* ``MockLLMClient`` — new. Patches ``pflow.core.llm_client.complete``.
  Returns ``AdapterResponse`` instances directly (not ``Mock`` objects).

Both share the same ``_DEFAULT_RESPONSES`` table and the same exact-match
→ wildcard → schema-default → fallback resolution chain so workflow-discovery
tests behave identically through the migration. ``MockLLMModel`` is removed
in Phase A.8 once all callers use the adapter.
"""

import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import Mock

from pflow.core.llm_client import AdapterResponse

# Shared default responses for known schemas — keyed by schema NAME (Pydantic
# class __name__ or JSON Schema "title"). Both MockLLMModel and MockLLMClient
# read from this table so behavior is identical across the migration.
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


class MockLLMModel:
    """Mock LLM model that simulates the llm library's Model interface."""

    def __init__(self, model_name: str, mock_get_model: "MockGetModel"):
        self.model_name = model_name
        self._mock_get_model = mock_get_model
        self._default_response = {
            "found": False,
            "workflow_name": None,
            "confidence": 0.5,
            "reasoning": "Mock response",
        }

    def prompt(self, prompt: str, schema: Optional[type] = None, temperature: float = 0.0, **kwargs) -> Mock:
        """Simulate LLM prompt method."""
        # Record the call
        call_record = {
            "model": self.model_name,
            "prompt": prompt[:500] if len(prompt) > 500 else prompt,  # Truncate long prompts
            "schema": schema.__name__ if schema else None,
            "temperature": temperature,
            "kwargs": kwargs,
        }
        self._mock_get_model.call_history.append(call_record)

        # Get configured response or use default
        response_data = self._mock_get_model.get_response(self.model_name, schema)

        # Create mock response object
        response = Mock()

        # CRITICAL: text() must return JSON string for ALL responses
        # Our refactored parse_structured_response() uses text(), not json()
        response_text = json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)
        response.text = Mock(return_value=response_text)

        # Also provide json() for backward compatibility (some tests may still use it)
        if schema:
            # Structured response with nested format (old format, kept for compatibility)
            nested_response = {"content": [{"input": response_data}]}
            response.json.return_value = nested_response
        else:
            # Text response
            response.json.return_value = response_data

        # Add usage tracking as a method (matching llm library)
        usage_data = Mock()
        # LLMNode expects .input and .output properties
        usage_data.input = len(prompt.split())
        usage_data.output = 50  # Arbitrary for mock
        usage_data.details = {}  # Empty details dict
        response.usage = Mock(return_value=usage_data)

        return response


class MockGetModel:
    """Mock for llm.get_model function."""

    def __init__(self):
        self.call_history = []
        self._responses = {}
        # Reads from the shared _DEFAULT_RESPONSES table at the top of this
        # module so MockLLMClient and MockLLMModel stay in lockstep.
        self._default_responses = _DEFAULT_RESPONSES

    def __call__(self, model_name: str) -> MockLLMModel:
        """Return a mock model when get_model is called."""
        return MockLLMModel(model_name, self)

    def set_response(self, model: str, schema: Optional[Any], response: dict):
        """Configure response for specific model and schema combination.

        Args:
            model: Model name, or "*" for wildcard matching any model
            schema: Pydantic schema class, or None for text responses
            response: Response dict to return
        """
        key = f"{model}:{schema.__name__ if schema else 'text'}"
        self._responses[key] = response

    def get_response(self, model: str, schema: Optional[type]) -> dict:
        """Get configured response or default.

        Resolution order:
        1. Exact model+schema match
        2. Wildcard model match (*:schema)
        3. Schema-based default (_default_responses)
        4. Final fallback
        """
        schema_name = schema.__name__ if schema else "text"
        key = f"{model}:{schema_name}"

        # Check for specific configuration
        if key in self._responses:
            return self._responses[key]

        # Check for wildcard model configuration
        wildcard_key = f"*:{schema_name}"
        if wildcard_key in self._responses:
            return self._responses[wildcard_key]

        # Use schema-based default if available
        if schema and schema.__name__ in self._default_responses:
            return self._default_responses[schema.__name__]

        # Final fallback
        return {"response": "mock response"}

    def reset(self):
        """Reset mock state for test isolation."""
        self.call_history.clear()
        self._responses.clear()


def create_mock_get_model() -> MockGetModel:
    """Factory function to create a mock get_model."""
    return MockGetModel()


# --- New mock for the pflow LiteLLM adapter (Task 158 Phase A.4+) ----------


@dataclass
class MockLLMClient:
    """Mock for ``pflow.core.llm_client.complete``.

    Drop-in replacement: same signature, returns ``AdapterResponse`` instances
    directly (not ``Mock`` objects, unlike the legacy ``MockLLMModel``).

    Resolution chain mirrors ``MockGetModel`` exactly so workflow-discovery
    tests behave identically through the migration: exact model+schema
    match → wildcard model match → ``_DEFAULT_RESPONSES`` schema default
    → ``{"response": "mock response"}`` fallback.

    ``call_history`` keeps the legacy 500-char prompt truncation (several
    existing tests assert against the boundary). ``call_history_full`` is
    parallel and untruncated, added here so future cache-structure tests
    (Phase B/C) can verify full message assembly.
    """

    call_history: list[dict] = field(default_factory=list)
    call_history_full: list[dict] = field(default_factory=list)
    _responses: dict[str, dict] = field(default_factory=dict)

    def set_response(self, model: str, schema: Any, response: dict) -> None:
        """Configure a response for a (model, schema) pair.

        Args:
            model: Model name, or ``"*"`` for any model.
            schema: Pydantic class OR JSON Schema dict OR None (for text).
            response: Response dict; serialized to JSON for ``AdapterResponse.text``.
        """
        name = _schema_name(schema) or "text"
        self._responses[f"{model}:{name}"] = response

    def get_response(self, model: str, schema: Any) -> dict:
        """Resolve a configured or default response.

        Same resolution chain as ``MockGetModel.get_response``.
        """
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

    def reset(self) -> None:
        """Clear call history and configured responses."""
        self.call_history.clear()
        self.call_history_full.clear()
        self._responses.clear()

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

        # Build AdapterResponse with a usage dict that matches the adapter's
        # stable shape. Token counts are arbitrary mock values — tests that
        # care about specific values should set their own response.
        # NOTE: cost_usd is intentionally NOT populated. The real adapter reads
        # it from LiteLLM's `_hidden_params["response_cost"]`, which we can't
        # reasonably mock. Letting it stay absent means
        # `enrich_llm_usage_with_cost` computes a real cost from the
        # MODEL_PRICING table — which is what existing tests rely on for
        # historical-cost propagation through the memo cache.
        input_tokens = max(1, len(prompt.split()))
        usage = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": 50,
            "total_tokens": input_tokens + 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
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
