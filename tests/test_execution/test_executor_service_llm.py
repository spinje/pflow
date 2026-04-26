"""End-to-end LLM diagnostic propagation tests.

These tests exercise the full runtime chain:

LLMNode -> shared store -> mark_node_failed -> __failures__ ->
executor_service.build_error_list -> ExecutionResult diagnostics.
"""

import pytest

from pflow.core.exceptions import InvalidRequestError, MissingApiKeyError, UnknownModelError
from pflow.core.llm_client import AdapterResponse
from pflow.core.llm_client import complete as real_complete
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.runtime.node_state import FAILURE_CATEGORY_LLM


def _llm_workflow_ir(params: dict | None = None) -> dict:
    node_params = {
        "model": "anthropic/foo",
        "prompt": "Reply with a short answer.",
    }
    if params:
        node_params.update(params)
    return {
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "params": node_params,
            }
        ],
        "edges": [],
    }


@pytest.mark.parametrize(
    ("error", "expected_context"),
    [
        (
            UnknownModelError(
                "Unknown model: anthropic/foo",
                model="anthropic/foo",
                reason="unknown_name",
                provider_message="model 'anthropic/foo' was retired on 2026-01-01",
            ),
            {
                "error_class": "UnknownModelError",
                "model": "anthropic/foo",
                "reason": "unknown_name",
                "provider_message": "model 'anthropic/foo' was retired on 2026-01-01",
            },
        ),
        (
            MissingApiKeyError(
                "API key required for model: anthropic/foo",
                model="anthropic/foo",
                kind="missing_key",
                provider_message="Quota exceeded for free tier",
            ),
            {
                "error_class": "MissingApiKeyError",
                "model": "anthropic/foo",
                "kind": "missing_key",
                "provider_message": "Quota exceeded for free tier",
            },
        ),
        (
            InvalidRequestError(
                "Provider rejected the request: bad schema",
                model="anthropic/foo",
                provider_message="Property 'foo' is required but missing",
            ),
            {
                "error_class": "InvalidRequestError",
                "model": "anthropic/foo",
                "provider_message": "Property 'foo' is required but missing",
            },
        ),
    ],
)
def test_llm_call_error_context_reaches_runner_diagnostics(monkeypatch, error, expected_context):
    def fail_complete(**kwargs):
        raise error

    monkeypatch.setattr("pflow.nodes.llm.llm.complete", fail_complete)

    result = WorkflowRunner().run(_llm_workflow_ir(), {}, RunnerConfig())

    assert result.success is False
    assert result.errors, "expected LLM failure diagnostic"

    context = result.errors[0].context or {}
    assert context["category"] == FAILURE_CATEGORY_LLM
    for key, expected_value in expected_context.items():
        assert context[key] == expected_value

    failure = result.shared_after["__failures__"]["ask"]
    assert failure["category"] == FAILURE_CATEGORY_LLM
    node_output = failure["data"]
    assert node_output["error_class"] == expected_context["error_class"]
    for key, expected_value in expected_context.items():
        assert node_output["_diagnostic_context"][key] == expected_value


def test_llm_response_parse_error_context_reaches_runner_diagnostics(monkeypatch):
    def complete_with_invalid_json(**kwargs):
        model = kwargs.get("model", "anthropic/foo")
        return AdapterResponse(
            text="not valid json",
            usage={
                "model": model,
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "cost_usd": 0.0001,
            },
            model=model,
            has_schema=True,
        )

    monkeypatch.setattr("pflow.nodes.llm.llm.complete", complete_with_invalid_json)

    result = WorkflowRunner().run(
        _llm_workflow_ir({
            "output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            }
        }),
        {},
        RunnerConfig(),
    )

    assert result.success is False
    assert result.errors, "expected parse failure diagnostic"

    context = result.errors[0].context or {}
    assert context["category"] == FAILURE_CATEGORY_LLM
    assert context["error_class"] == "LLMResponseParseError"
    assert context["model"] == "anthropic/foo"

    failure = result.shared_after["__failures__"]["ask"]
    assert failure["category"] == FAILURE_CATEGORY_LLM
    node_output = failure["data"]
    assert node_output["response"] == "not valid json"
    assert node_output["error_class"] == "LLMResponseParseError"
    assert node_output["_diagnostic_context"]["error_class"] == "LLMResponseParseError"
    assert node_output["_diagnostic_context"]["model"] == "anthropic/foo"


def test_real_litellm_exception_provider_message_reaches_runner_diagnostics(monkeypatch):
    """End-to-end: real LiteLLM exception -> seam -> WorkflowRunner -> errors[].context.

    The other tests in this file hand-construct typed pflow exceptions and
    monkeypatch them onto ``pflow.nodes.llm.llm.complete``. They prove the
    pipeline preserves a typed exception's context — but bypass the
    ``_classify_litellm_error`` seam that's supposed to populate
    ``provider_message`` from the upstream LiteLLM exception's text.

    This test exercises the full chain: a real ``litellm.completion`` raise
    (mocked one layer below the autouse mock) flows through
    ``_classify_litellm_error`` -> typed pflow exception with
    ``provider_message`` -> ``LLMNode._call_llm`` catch ->
    ``_error_dict_from_exception`` -> ``_propagate_error_to_shared`` ->
    ``mark_node_failed`` -> ``executor_service._enrich_error_from_node_output``
    -> ``ExecutionResult.errors[i].context["provider_message"]``.

    A regression dropping ``provider_message`` in any of those layers would
    pass the existing unit tests on either side and break the central UX
    promise: agents reading the diagnostic JSON get the provider's actionable
    text (the WHY) alongside pflow's wrapped framing (the WHAT). Pinning the
    full chain here is the single end-to-end guard for that promise.
    """
    import litellm.exceptions

    # Override the autouse mock binding for LLMNode so the real adapter runs.
    # The autouse fixture replaced ``pflow.nodes.llm.llm.complete`` with
    # ``MockLLMClient.complete``; restoring the real ``complete`` makes
    # LLMNode go through ``_classify_litellm_error``. Patching
    # ``litellm.completion`` (one layer below) provides the upstream exception.
    monkeypatch.setattr("pflow.nodes.llm.llm.complete", real_complete)

    raw_provider_text = "Quota exceeded for free tier; upgrade at https://billing.example/"
    monkeypatch.setattr(
        "litellm.completion",
        lambda **kwargs: (_ for _ in ()).throw(
            litellm.exceptions.AuthenticationError(
                message=raw_provider_text,
                model="anthropic/foo",
                llm_provider="anthropic",
            )
        ),
    )

    result = WorkflowRunner().run(_llm_workflow_ir(), {}, RunnerConfig())

    assert result.success is False
    assert result.errors, "expected LLM failure diagnostic"

    # Diagnostic.message is the pflow-wrapped framing (WHAT). The exact
    # wording isn't asserted to avoid brittleness; the structural assertions
    # below cover the contract.
    context = result.errors[0].context or {}
    assert context["category"] == FAILURE_CATEGORY_LLM
    assert context["error_class"] == "MissingApiKeyError"
    assert context["kind"] == "missing_key"
    assert context["model"] == "anthropic/foo"
    # The crux: provider_message preserves the raw upstream text end-to-end.
    # The whole point of the field — agents reading JSON get the WHY.
    assert raw_provider_text in context["provider_message"]

    # The shared-store half mirrors the same context (lifted by
    # executor_service._enrich_error_from_node_output, which the runtime
    # path depends on).
    failure = result.shared_after["__failures__"]["ask"]
    assert raw_provider_text in failure["data"]["_diagnostic_context"]["provider_message"]
