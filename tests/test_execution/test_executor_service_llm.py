"""End-to-end LLM diagnostic propagation tests.

These tests exercise the full runtime chain:

LLMNode -> shared store -> mark_node_failed -> __failures__ ->
executor_service.build_error_list -> ExecutionResult diagnostics.
"""

import pytest

from pflow.core.exceptions import InvalidRequestError, MissingApiKeyError, UnknownModelError
from pflow.core.llm_client import AdapterResponse
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
            ),
            {
                "error_class": "UnknownModelError",
                "model": "anthropic/foo",
                "reason": "unknown_name",
            },
        ),
        (
            MissingApiKeyError(
                "API key required for model: anthropic/foo",
                model="anthropic/foo",
                kind="missing_key",
            ),
            {
                "error_class": "MissingApiKeyError",
                "model": "anthropic/foo",
                "kind": "missing_key",
            },
        ),
        (
            InvalidRequestError(
                "Provider rejected the request: bad schema",
                model="anthropic/foo",
            ),
            {
                "error_class": "InvalidRequestError",
                "model": "anthropic/foo",
                "provider_message": "Provider rejected the request: bad schema",
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
