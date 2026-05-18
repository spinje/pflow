"""Tests for WorkflowRunner — the shared execution pipeline entry point.

Verifies that validation gates compilation (spec 9b) and that a valid
workflow runs through the full pipeline producing structured results.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
from pflow.core.workflow.status import WorkflowStatus
from pflow.core.workflow.validator import WorkflowValidator
from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner, _synthesize_inline_workflow_id


def test_validation_error_prevents_compilation():
    """When a workflow has a cycle, validation should fail and compilation should never be called.

    Spec 9b: validation errors must block the pipeline before compilation.
    The cycle between nodes a and b (mutual data dependency + mutual edges)
    is caught by data flow validation (Kahn's algorithm in build_execution_order).
    """
    workflow_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "echo ${b.stdout}"}},
            {"id": "b", "type": "shell", "params": {"command": "echo ${a.stdout}"}},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    }

    with patch("pflow.runtime.compile_workflow") as mock_compile:
        result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert isinstance(result, ExecutionResult)
    assert result.success is False
    assert len(result.errors) > 0

    # The error message should mention the circular dependency.
    # CycleError produces "Circular dependency detected involving nodes: a, b"
    # which is wrapped as "Data flow error: Circular dependency detected..."
    # and then surfaced through WorkflowValidationError → _exception_to_result.
    error_text = str(result.errors).lower()
    assert "circular" in error_text or "cycle" in error_text, f"Expected cycle/circular error, got: {result.errors}"

    # Compilation must NOT have been called — validation blocks it.
    mock_compile.assert_not_called()


def test_successful_workflow_runs_through_full_pipeline():
    """A valid single-node shell workflow should execute and return structured results.

    This is a real integration test — it runs an actual shell command and
    verifies the full pipeline: resolution, validation, compilation, execution.
    """
    workflow_ir = {
        "nodes": [
            {"id": "test", "type": "shell", "params": {"command": "echo runner-test"}},
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert "runner-test" in result.shared_after["test"]["stdout"]
    assert result.trace is not None
    assert result.metrics is not None


def test_llm_structured_warning_survives_runner_pipeline(mock_llm_client):
    """E2E: structured LLM warnings render as text and preserve context.

    LLMNode stores adapter warnings in ``__warnings__`` as dicts so JSON
    consumers can inspect ``kind``/``context``. The runner must normalize that
    shape instead of treating the dict itself as the Diagnostic message.
    """
    warning = {
        "kind": "llm_empty_response_reasoning",
        "text": (
            "Empty response from gemini/gemini-3-flash-preview "
            "(finish_reason=length, 13 tokens consumed). "
            "Increase max_tokens, or lower reasoning_effort."
        ),
        "context": {
            "model": "gemini/gemini-3-flash-preview",
            "finish_reason": "length",
            "output_tokens": 13,
            "thinking_tokens": 13,
            "thinking_budget": 0,
        },
    }

    mock_llm_client.set_response("*", None, "", cost_usd=0.0001, warnings=[warning])

    workflow_ir = {
        "nodes": [
            {
                "id": "think",
                "type": "llm",
                "params": {
                    "model": "gemini/gemini-3-flash-preview",
                    "prompt": "Reply with exactly OK.",
                    "max_tokens": 16,
                },
            }
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is True
    assert result.status == WorkflowStatus.DEGRADED
    assert result.shared_after["__warnings__"]["think"] == warning

    runtime_warning = next(w for w in result.warnings if w.node_id == "think")
    assert runtime_warning.message == warning["text"]
    assert "{'kind':" not in runtime_warning.message
    assert runtime_warning.context["type"] == "api_warning"
    assert runtime_warning.context["category"] == "llm_warning"
    assert runtime_warning.context["kind"] == "llm_empty_response_reasoning"
    assert runtime_warning.context["model"] == "gemini/gemini-3-flash-preview"


def test_runtime_warning_diagnostic_passes_through_without_api_warning_wrapping() -> None:
    diagnostic = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.below-min-observed",
        node_id="ask",
        message="ask: declared cache did not fire",
        suggestions=["Increase cache content above 1024 tokens."],
        context={"category": "cache_warning"},
    )
    runner = WorkflowRunner()

    warnings = runner._extract_runtime_warnings({"__warnings__": {"ask": diagnostic}})

    assert warnings == [diagnostic]
    assert warnings[0].id == "cache.below-min-observed"
    assert warnings[0].suggestions == ["Increase cache content above 1024 tokens."]
    assert warnings[0].context == {"category": "cache_warning"}


def test_runtime_warning_diagnostic_missing_node_id_gets_store_key() -> None:
    diagnostic = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.below-min-observed",
        message="declared cache did not fire",
    )
    runner = WorkflowRunner()

    warnings = runner._extract_runtime_warnings({"__warnings__": {"ask": diagnostic}})

    assert warnings[0].node_id == "ask"


def test_llm_declared_cache_zero_provider_tokens_emits_catalog_warning(mock_llm_client, monkeypatch) -> None:
    # Bypass the runtime pre-dispatch strip so this test isolates the
    # post-call observed-tier path. Strip behavior is exercised in
    # tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py.
    monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10_000)
    mock_llm_client.set_response(
        "*",
        None,
        "ok",
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    workflow_ir = {
        "inputs": {"small_doc": {"type": "string"}},
        "cache": {"items": [{"name": "small_doc", "var": "small_doc", "prose_before": "Small doc:\n"}]},
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "prompt_cache": ["small_doc"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize briefly."},
            }
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {"small_doc": "short"}, RunnerConfig())

    warning = result.shared_after["__warnings__"]["ask"]
    assert isinstance(warning, Diagnostic)
    assert warning.id == "cache.below-min-observed"
    assert warning.context is not None
    assert result.status == WorkflowStatus.DEGRADED
    assert any(w.id == "cache.below-min-observed" for w in result.warnings)


def test_llm_declared_cache_observed_cache_activity_suppresses_catalog_warning(mock_llm_client, monkeypatch) -> None:
    # Bypass the runtime pre-dispatch strip so this test isolates the
    # post-call observed-tier path. Strip behavior is exercised in
    # tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py.
    monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10_000)
    mock_llm_client.set_response(
        "*",
        None,
        "ok",
        cache_creation_input_tokens=1024,
        cache_read_input_tokens=0,
    )
    workflow_ir = {
        "inputs": {"small_doc": {"type": "string"}},
        "cache": {"items": [{"name": "small_doc", "var": "small_doc", "prose_before": "Small doc:\n"}]},
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "prompt_cache": ["small_doc"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize briefly."},
            }
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {"small_doc": "short"}, RunnerConfig())

    assert not result.shared_after.get("__warnings__")
    assert result.status == WorkflowStatus.SUCCESS


@pytest.mark.trace_files
def test_llm_rendered_below_min_warning_reaches_trace_json(mock_llm_client, monkeypatch) -> None:
    """Production runner path must serialize runtime cache-strip evidence.

    Node-level tests prove ``LLMNode`` strips the marker. This locks the
    runner/trace handoff: ``llm_usage.cache_skipped_reason`` and the
    catalog-backed runtime warning both survive into trace JSON.
    """
    monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10)
    mock_llm_client.set_response(
        "*",
        None,
        "ok",
        cache_creation_input_tokens=None,
        cache_read_input_tokens=None,
    )
    workflow_ir = {
        "inputs": {"small_doc": {"type": "string"}},
        "cache": {"items": [{"name": "small_doc", "var": "small_doc", "prose_before": "Small doc:\n"}]},
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "prompt_cache": ["small_doc"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize briefly."},
            }
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {"small_doc": "short"}, RunnerConfig())

    assert result.success is True
    assert result.trace is not None
    trace_path = result.trace.save_to_file()
    trace_data = json.loads(trace_path.read_text(encoding="utf-8"))

    llm_call = trace_data["nodes"][0]["llm_call"]
    assert llm_call["cache_skipped_reason"] == "below_min"
    assert any(warning.get("id") == "cache.below-min-rendered" for warning in trace_data["warnings"])


@pytest.mark.trace_files
def test_batch_prewarm_disabled_below_min_reaches_trace_json(mock_llm_client) -> None:
    """Production runner path must serialize prewarm-disabled runtime evidence."""
    mock_llm_client.set_response(
        "*",
        None,
        "ok",
        cache_creation_input_tokens=None,
        cache_read_input_tokens=None,
    )
    workflow_ir = {
        "inputs": {"items": {"type": "array"}},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "prewarm": True,
                "batch": {"items": "${items}", "as": "item"},
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Short stable prefix.\n\nItem: ${item.text}",
                },
            }
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(
        workflow_ir,
        {"items": [{"text": "one"}, {"text": "two"}]},
        RunnerConfig(),
    )

    assert result.success is True
    assert result.trace is not None
    trace_path = result.trace.save_to_file()
    trace_data = json.loads(trace_path.read_text(encoding="utf-8"))

    batch_items = trace_data["nodes"][0]["batch_items"]
    assert {item["llm_call"]["prewarm_disabled_reason"] for item in batch_items} == {"below_min"}
    assert any(warning.get("id") == "cache.prewarm-disabled-below-min" for warning in trace_data["warnings"])


@pytest.mark.trace_files
def test_exception_trace_preserves_prior_runtime_cache_warnings(mock_llm_client, monkeypatch) -> None:
    """Runtime warnings emitted before a later exception must reach trace warnings."""
    monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10)
    mock_llm_client.set_response(
        "*",
        None,
        "ok",
        cache_creation_input_tokens=None,
        cache_read_input_tokens=None,
    )
    workflow_ir = {
        "inputs": {"small_doc": {"type": "string"}},
        "cache": {"items": [{"name": "small_doc", "var": "small_doc", "prose_before": "Small doc:\n"}]},
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "prompt_cache": ["small_doc"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize briefly."},
            }
        ],
        "outputs": {"broken": {"source": "${ask.missing_field}", "description": "forces post-run failure"}},
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {"small_doc": "short"}, RunnerConfig())

    assert result.success is False
    assert result.trace is not None
    assert any(warning.id == "cache.below-min-rendered" for warning in result.warnings)
    trace_path = result.trace.save_to_file()
    trace_data = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace_data["nodes"][0]["llm_call"]["cache_skipped_reason"] == "below_min"
    assert any(warning.get("id") == "cache.below-min-rendered" for warning in trace_data["warnings"])


def test_llm_empty_response_warning_overwrites_cache_miss_observation(mock_llm_client) -> None:
    adapter_warning = {
        "kind": "llm_empty_response_reasoning",
        "text": "Empty response from model.",
        "context": {"model": "anthropic/claude-sonnet-4-5"},
    }
    mock_llm_client.set_response(
        "*",
        None,
        "",
        warnings=[adapter_warning],
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    workflow_ir = {
        "inputs": {"small_doc": {"type": "string"}},
        "cache": {"items": [{"name": "small_doc", "var": "small_doc", "prose_before": "Small doc:\n"}]},
        "nodes": [
            {
                "id": "ask",
                "type": "llm",
                "prompt_cache": ["small_doc"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize briefly."},
            }
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {"small_doc": "short"}, RunnerConfig())

    assert result.shared_after["__warnings__"]["ask"] == adapter_warning


def test_emit_observed_below_min_cache_warning_skips_when_no_provider_telemetry() -> None:
    """When the adapter returned no usage at all and ``LLMNode.post()`` set
    ``shared["llm_usage"] = {}`` (line 977 / "adapter failed completely"),
    ``_emit_observed_below_min_cache_warning`` MUST skip rather than fabricate
    a "did not fire" observation. Mirrors the analyzer's honest-unmeasurable
    convention used by ``_estimate_ref_tokens`` and ``_compute_fragmentation_costs``.

    Tested directly at the helper level because the runtime pipeline always
    routes the missing-usage case through ``shared["llm_usage"] = {}`` —
    the mock can't easily simulate ``AdapterResponse(usage=None)`` without
    additional plumbing, and ``cache_telemetry=False`` on the mock just
    omits cache keys (which ``LLMNode.post()`` then normalizes to zero, a
    legitimate "cache didn't fire" case the guard correctly does NOT skip).

    Mutation test: revert the missing-telemetry guard in
    ``_emit_observed_below_min_cache_warning``; this test fails because the
    helper falls through to ``detect()`` with both fields defaulting to 0
    and writes a false-positive observed-tier finding.
    """
    from types import MappingProxyType

    from pflow.core.cache_render import CacheRenderContext
    from pflow.nodes.llm.llm import _emit_observed_below_min_cache_warning

    cache_ctx = CacheRenderContext(
        cache_block=None,
        subset=("small_doc",),
        prewarm=False,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    shared: dict[str, object] = {
        "__pflow_cache_render__": MappingProxyType({"ask": cache_ctx}),
        "_pflow_workflow_file": "/abs/x.pflow.md",
    }

    _emit_observed_below_min_cache_warning(
        shared=shared,
        node_id="ask",
        model="anthropic/claude-sonnet-4-5",
        llm_usage={},
    )

    assert "__warnings__" not in shared


def test_emit_observed_below_min_skips_when_provider_returned_no_cache_telemetry() -> None:
    """Reviewer Finding 2: when a provider returns usage but no cache telemetry
    (e.g. cold OpenAI calls have no ``cache_creation_input_tokens`` /
    ``cache_read_input_tokens`` fields), the runtime guard must skip rather
    than treat ``0+0`` as evidence the cache failed.

    Pre-fix: ``LLMNode.post()`` synthesized the cache keys defaulting to 0,
    so the guard ``not in llm_usage`` check was structurally ineffective.
    Fix: ``has_cache_telemetry`` boolean carries presence/absence through
    the runtime → trace boundary; the guard checks it directly.

    Mutation contract: revert the guard to the ``not in llm_usage`` check
    OR set ``has_cache_telemetry=True`` in the fixture; this test fails
    because ``cache.below-min-observed`` is incorrectly emitted.
    """
    from types import MappingProxyType

    from pflow.core.cache_render import CacheRenderContext
    from pflow.nodes.llm.llm import _emit_observed_below_min_cache_warning

    cache_ctx = CacheRenderContext(
        cache_block=None,
        subset=("small_doc",),
        prewarm=False,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )
    shared: dict[str, object] = {
        "__pflow_cache_render__": MappingProxyType({"ask": cache_ctx}),
        "_pflow_workflow_file": "/abs/x.pflow.md",
    }

    # Faithful "OpenAI cold call" shape: meaningful input_tokens, cache
    # fields synthesized to 0 because the provider didn't expose them.
    # ``has_cache_telemetry=False`` is the load-bearing absence signal.
    _emit_observed_below_min_cache_warning(
        shared=shared,
        node_id="ask",
        model="openai/gpt-4o",
        llm_usage={
            "model": "openai/gpt-4o",
            "input_tokens": 5000,
            "uncached_input_tokens": 5000,
            "output_tokens": 200,
            "total_tokens": 5200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "has_cache_telemetry": False,
            "input_token_accounting": "total_includes_cache",
        },
    )

    assert "__warnings__" not in shared, (
        "Provider returned no cache telemetry — observed-tier detection must skip "
        "rather than emit a false-positive cache.below-min-observed warning."
    )


def test_validator_called_exactly_once():
    """WorkflowValidator.validate must be called exactly once per runner.run().

    Task 138 eliminated dual validation (CLI + compiler both validating).
    This guards against regression — if validate is called twice, this fails.
    """
    workflow_ir = {
        "nodes": [
            {"id": "test", "type": "shell", "params": {"command": "echo once"}},
        ],
        "edges": [],
    }

    with patch.object(WorkflowValidator, "validate", wraps=WorkflowValidator.validate) as mock_validate:
        result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is True
    assert mock_validate.call_count == 1, f"Expected exactly 1 validation call, got {mock_validate.call_count}"


def test_declared_defaults_applied_without_user_params():
    """Workflow with declared input defaults should use them when user provides nothing.

    Tests the full novel pipeline: _fill_declared_defaults (placeholders for validation)
    → _strip_placeholders (clean before compilation) → prepare_inputs (applies real defaults).
    If any step is wrong, the default value won't appear in the output.
    """
    workflow_ir = {
        "inputs": {
            "greeting": {"type": "string", "default": "hello-from-default", "description": "A greeting"},
        },
        "nodes": [
            {"id": "greet", "type": "shell", "params": {"command": "echo ${greeting}"}},
        ],
        "edges": [],
    }

    # Empty params — the default should be applied by the Runner/compiler pipeline
    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is True, f"Expected success, got errors: {result.errors}"
    assert "hello-from-default" in result.shared_after["greet"]["stdout"]


def test_user_params_override_declared_defaults():
    """User-provided values must not be clobbered by declared defaults.

    _fill_declared_defaults has an `if name not in params` guard. This test
    ensures a user's explicit value survives through the full pipeline.
    """
    workflow_ir = {
        "inputs": {
            "greeting": {"type": "string", "default": "hello-from-default", "description": "A greeting"},
        },
        "nodes": [
            {"id": "greet", "type": "shell", "params": {"command": "echo ${greeting}"}},
        ],
        "edges": [],
    }

    # User provides their own value — should override the default
    result = WorkflowRunner().run(workflow_ir, {"greeting": "user-override"}, RunnerConfig())

    assert result.success is True, f"Expected success, got errors: {result.errors}"
    assert "user-override" in result.shared_after["greet"]["stdout"]
    assert "hello-from-default" not in result.shared_after["greet"]["stdout"]


class TestExceptionToResultCategorization:
    """Regression tests for _exception_to_result error categorization."""

    def _run(self, exception):
        """Helper to call _exception_to_result with minimal args."""
        runner = WorkflowRunner()
        return runner._exception_to_result(exception, 0.0, None)

    def test_valueerror_with_node_annotation_is_execution_failure(self):
        """ValueError from node execution (annotated) -> execution_failure."""
        exc = ValueError("HTTP timeout connecting to api.example.com")
        exc._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "execution_failure"
        assert result.errors[0].node_id == "fetch-data"

    def test_valueerror_without_annotation_is_validation(self):
        """ValueError from pre-execution (no annotation) -> validation."""
        exc = ValueError("Invalid parameter format")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "validation"
        assert result.errors[0].node_id is None

    def test_schema_validation_error_preserves_fields(self):
        """SchemaValidationError (replacing duck-type hack) preserves path and suggestions."""
        exc = SchemaValidationError("bad field", path="nodes[0].type", suggestion="Use 'shell'")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "validation"
        assert result.errors[0].source == "validation"
        assert (result.errors[0].context or {}).get("path") == "nodes[0].type"
        assert result.errors[0].suggestions == ["Use 'shell'"]

    def test_markdown_parse_error_preserves_line_and_suggestions(self):
        """MarkdownParseError extracts .line and .suggestions into error dict."""
        exc = MarkdownParseError("bad syntax", line=42, suggestion="Add ## Steps")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "parse_error"
        assert (result.errors[0].context or {}).get("line") == 42
        assert result.errors[0].suggestions == ["Add ## Steps"]

    def test_markdown_parse_error_with_node_annotation(self):
        """MarkdownParseError from nested workflow propagates node_id."""
        exc = MarkdownParseError("bad syntax", line=5)
        exc._pflow_node_id = "load-sub-workflow"  # type: ignore[attr-defined]
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "parse_error"
        assert result.errors[0].node_id == "load-sub-workflow"
        assert (result.errors[0].context or {}).get("line") == 5

    def test_markdown_parse_error_omits_none_fields(self):
        """MarkdownParseError with None line/suggestions doesn't write None values."""
        exc = MarkdownParseError("bad syntax")
        result = self._run(exc)
        assert (result.errors[0].context or {}).get("category") == "parse_error"
        assert "line" not in (result.errors[0].context or {})
        assert result.errors[0].suggestions is None

    def test_workflow_validation_error_warnings_survive_via_kwarg(self):
        """WorkflowValidationError.validation_warnings round-trips through
        the exception-to-result boundary (PR #244 review Warning #3 follow-up).

        Before the fix, warnings were smuggled via a dynamic
        ``_pflow_validation_warnings`` attribute with ``# type: ignore[attr-defined]``.
        After the fix, they're a first-class constructor kwarg on
        ``WorkflowValidationError``, and ``_exception_to_result`` reads
        ``exception.validation_warnings`` to include them in the final
        ExecutionResult.diagnostics list.
        """
        from pflow.core.diagnostic import Diagnostic, Severity
        from pflow.core.exceptions import WorkflowValidationError

        error = Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            message="structural failure",
        )
        warning = Diagnostic(
            severity=Severity.WARNING,
            source="validator",
            message="cache lint: shell node without template inputs",
            node_id="fetch",
        )
        exc = WorkflowValidationError(
            validation_errors=[error],
            validation_warnings=[warning],
        )
        result = self._run(exc)

        # Error survives via to_diagnostics() pass-through
        assert any(d.severity == Severity.ERROR and "structural failure" in d.message for d in result.diagnostics)
        # Warning survives via the validation_warnings kwarg reader
        assert any(d.severity == Severity.WARNING and "cache lint" in d.message for d in result.diagnostics), (
            f"Expected warning to survive exception boundary, got: {result.diagnostics}"
        )


def test_node_valueerror_categorized_as_execution_failure():
    """E2E: ValueError raised inside a node gets 'execution_failure', not 'validation'.

    This tests the full chain: engine.run() → node raises ValueError →
    engine annotates _pflow_node_id → runner._exception_to_result →
    ExecutionResult with category 'execution_failure'.

    Before Task 141, ALL ValueErrors got category 'validation' — including
    node execution errors like HTTP timeouts and API failures. The fix uses
    _pflow_node_id (set by the engine on any exception from a running node)
    as a discriminator.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "bad-node",
                "type": "code",
                "params": {
                    "code": 'result: str = ""\nraise ValueError("simulated API failure")',
                },
            },
        ],
        "edges": [],
    }

    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    assert result.success is False
    assert len(result.errors) == 1
    error = result.errors[0]
    category = (error.context or {}).get("category")
    assert category == "execution_failure", (
        f"Expected 'execution_failure' but got '{category}'. "
        f"This means the engine's _pflow_node_id annotation or the "
        f"runner's ValueError dispatch is broken."
    )
    assert error.node_id == "bad-node"


def test_child_parser_warning_survives_prep_failure(tmp_path: Path):
    """Child parser warnings should survive child prep failures and reach the result."""
    child_workflow = tmp_path / "child.pflow.md"
    child_workflow.write_text(
        "# Child\n\n"
        "## Input\n\n"
        "Typo section heading.\n\n"
        "## Inputs\n\n"
        "### required_value\n\n"
        "Required input.\n\n"
        "- type: string\n"
        "- required: true\n\n"
        "## Steps\n\n"
        "### run\n\n"
        "Use the input.\n\n"
        "- type: shell\n"
        "- cache: false\n"
        "- command: echo ${required_value}\n",
        encoding="utf-8",
    )

    parent_workflow = tmp_path / "parent.pflow.md"
    parent_workflow.write_text(
        f"# Parent\n\n## Steps\n\n### child\n\nRun child.\n\n- type: workflow\n- workflow: {child_workflow}\n",
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(parent_workflow), {}, RunnerConfig())

    assert result.success is False
    assert any(diagnostic.severity == Severity.ERROR for diagnostic in result.diagnostics)
    parser_warnings = [
        diagnostic
        for diagnostic in result.diagnostics
        if diagnostic.severity == Severity.WARNING and diagnostic.source == "parser"
    ]
    assert len(parser_warnings) == 1
    assert "## Input" in parser_warnings[0].message


def test_sibling_child_parser_warnings_not_collapsed_by_dedup(tmp_path: Path):
    """Two children with identical parser warnings must both survive deduplication.

    Regression test for: parser warnings from sibling sub-workflows had the same
    (severity, source, node_id, message) hash when node_id was None and the typo
    appeared on the same line number, causing deduplicate_diagnostics() to drop one.
    Fix: _propagate_child_parser_warnings adds parent node_id and workflow path
    as provenance, making the two diagnostics distinguishable.
    """
    for name in ("child_a", "child_b"):
        (tmp_path / f"{name}.pflow.md").write_text(
            f"# {name}\n\n"
            "## Input\n\n"  # same typo, same line number in both
            "Typo section.\n\n"
            "## Steps\n\n"
            f"### run-{name}\n\n"
            "Does a thing.\n\n"
            "- type: shell\n"
            "- cache: false\n"
            "- command: echo hello\n",
            encoding="utf-8",
        )

    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        "# Parent\n\n## Steps\n\n"
        f"### step-a\n\nRun child A.\n\n- type: workflow\n- workflow: {tmp_path / 'child_a.pflow.md'}\n\n"
        f"### step-b\n\nRun child B.\n\n- type: workflow\n- workflow: {tmp_path / 'child_b.pflow.md'}\n",
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(parent), {}, RunnerConfig())

    parser_warnings = [d for d in result.diagnostics if d.severity == Severity.WARNING and d.source == "parser"]
    # Both children's parser warnings must survive — not collapsed by dedup
    assert len(parser_warnings) == 2, (
        f"Expected 2 parser warnings (one per child), got {len(parser_warnings)}: "
        f"{[w.message for w in parser_warnings]}"
    )
    # Each should identify its parent step via provenance
    messages = [w.message for w in parser_warnings]
    assert any("step-a" in m for m in messages)
    assert any("step-b" in m for m in messages)


def test_child_cache_lint_warning_propagates_to_parent_validation(tmp_path: Path):
    """Cache-lint warnings from child workflows must reach parent validate-only output.

    Regression test for: _validate_sub_workflows() discarded _child_warnings from
    recursive WorkflowValidator.validate() calls, so cache-lint warnings from children
    never reached the parent.
    """
    child = tmp_path / "child.pflow.md"
    child.write_text(
        "# Child\n\n## Steps\n\n"
        "### static-shell\n\n"
        "Runs a command with no template inputs.\n\n"
        "- type: shell\n"
        "- command: git branch --show-current\n",  # no templates, no cache:false → lint warning
        encoding="utf-8",
    )

    parent = tmp_path / "parent.pflow.md"
    parent.write_text(
        f"# Parent\n\n## Steps\n\n### child-step\n\nRun child.\n\n- type: workflow\n- workflow: {child}\n",
        encoding="utf-8",
    )

    vresult = WorkflowRunner().validate(str(parent), {})

    assert vresult.valid is True
    warnings = vresult.warnings
    cache_warnings = [w for w in warnings if "cache" in w.message.lower() or "template inputs" in w.message.lower()]
    assert cache_warnings, (
        f"Expected child cache-lint warning in parent validation, got warnings: {[w.message for w in warnings]}"
    )
    # Should include provenance about which sub-workflow produced it
    assert any("child" in w.message.lower() or "child-step" in (w.node_id or "") for w in cache_warnings)


def test_extract_runtime_warnings_preserves_structured_diagnostic():
    """Regression for post-review Fix #6: _extract_runtime_warnings used to discard
    the structured Diagnostic already built by runtime/engine/template_errors.py
    and emit a canned hint instead. Post-fix, the structured Diagnostic is passed
    through with severity downgraded to WARNING, preserving per-ref classification
    and peer suggestions.

    This is a unit-level test of _extract_runtime_warnings — we construct the
    exact shared_store shape that runtime/engine/template_resolution.py produces
    in permissive mode and verify the pass-through behavior. A full end-to-end
    permissive test is harder because pre-execution validation also catches
    undefined references.
    """
    from pflow.core.diagnostic import Severity
    from pflow.runtime.engine.template_errors import build_template_error_diagnostic

    # Build the structured Diagnostic the same way template_resolution.py does
    # when a permissive-mode template fails to resolve at runtime.
    shared_store_for_diag = {
        "fallback": {"stdout": "peer-value"},
        "__execution__": {
            "completed_nodes": ["fallback"],
            "node_actions": {"fallback": "default"},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        },
    }
    structured_diag = build_template_error_diagnostic(
        "command",
        "${missing_upstream.value}",
        shared_store_for_diag,
        node_id="consumer",
    )

    # This is the exact shape template_resolution.py:406-411 writes:
    permissive_shared_store = {
        "__template_errors__": {
            "consumer": {
                "message": structured_diag.message,
                "unresolved": ["command"],
                "template": "${missing_upstream.value}",
                "diagnostic": structured_diag,
            }
        },
    }

    runner = WorkflowRunner()
    warnings = runner._extract_runtime_warnings(permissive_shared_store)

    template_warnings = [w for w in warnings if w.context and w.context.get("category") == "template_error"]
    assert template_warnings, (
        f"Expected a structured template_error warning, got: {[(w.severity, w.message, w.context) for w in warnings]}"
    )

    warning = template_warnings[0]
    assert warning.severity == Severity.WARNING
    assert warning.node_id == "consumer"
    # Structured context preserved — this is the part that used to be dropped
    refs = warning.context.get("unresolved_references") or []
    assert refs, "Expected unresolved_references in warning context"
    assert any(r.get("root") == "missing_upstream" for r in refs)
    # Legacy canned suggestion must NOT appear
    if warning.suggestions:
        assert not any("Fix unresolved template references" in s for s in warning.suggestions)


def test_extract_runtime_warnings_handles_type_validation_diagnostic():
    """Every ``__template_errors__`` entry must carry a structured Diagnostic,
    including the type_validation path. Pre-fix, template_resolution.py wrote
    type errors with only ``{"message", "type", "param"}`` — no ``diagnostic``
    key — and ``_extract_runtime_warnings`` had a legacy canned-hint fallback
    branch for that shape. Post-fix, template_resolution.py attaches a
    structured Diagnostic at the source site and the runner's legacy fallback
    is gone.
    """
    from pflow.core.diagnostic import Diagnostic, Severity

    type_diagnostic = Diagnostic(
        severity=Severity.ERROR,
        message="Parameter 'command' expected str but got dict",
        node_id="shell_node",
        source="runtime",
        context={
            "category": "template_error",
            "type": "type_validation",
            "param": "command",
        },
    )
    permissive_shared_store = {
        "__template_errors__": {
            "shell_node": {
                "message": type_diagnostic.message,
                "type": "type_validation",
                "param": "command",
                "diagnostic": type_diagnostic,
            }
        },
    }

    runner = WorkflowRunner()
    warnings = runner._extract_runtime_warnings(permissive_shared_store)

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.severity == Severity.WARNING
    assert warning.node_id == "shell_node"
    assert "expected str but got dict" in warning.message
    # The warning carries the category so consumers can filter by type.
    assert warning.context.get("category") == "template_error"
    assert warning.context.get("type") == "type_validation"


def test_extract_runtime_warnings_skips_entries_without_diagnostic():
    """Defensive guard: if a producer writes to ``__template_errors__`` without
    attaching a structured Diagnostic (contract violation), the runner skips
    the entry and logs a warning rather than silently rendering a lossy
    one-line fallback. This protects against a regression where a new producer
    forgets the Diagnostic and the user gets a degraded warning with no
    structured info.
    """
    permissive_shared_store = {
        "__template_errors__": {
            "consumer": {
                "message": "legacy entry without structured diagnostic",
                "unresolved": ["command"],
            }
        },
    }

    runner = WorkflowRunner()
    warnings = runner._extract_runtime_warnings(permissive_shared_store)

    assert warnings == [], "Entries without a structured Diagnostic must be skipped"


def test_exception_annotations_survive_full_pipeline():
    """E2E: _pflow_* annotations set by the engine and template resolution
    survive through the runner's _exception_to_result and land in the
    ExecutionResult.

    This is the enforcement test for the annotation preservation contract
    documented in engine/CLAUDE.md. If a future change introduces
    ``raise X from e`` in the annotation path, this test catches the
    regression by verifying the structured context reaches the result.

    Annotations verified:
    - _pflow_node_id (engine.py) → result.errors[0].node_id
    - _pflow_shared_store (runner.py) → result.shared_after is populated
    - _pflow_template_diagnostic (template_resolution.py) → structured
      Diagnostic with unresolved_references in result.errors
    - _pflow_partial_resolutions (template_resolution.py) → trace event
      has partial template_resolutions (tested in test_trace_integration)
    """
    # Two nodes: producer outputs stdout as a string. Consumer references
    # ${producer.stdout} (resolves) and ${producer.stdout.nested} (fails
    # at runtime — can't traverse into a plain string). Pre-execution
    # validation passes because "stdout" is a known shell output, but
    # runtime resolution raises a strict-mode ValueError with all
    # _pflow_* annotations attached.
    workflow_ir = {
        "nodes": [
            {
                "id": "producer",
                "type": "shell",
                "params": {"command": "echo hello"},
            },
            {
                "id": "consumer",
                "type": "shell",
                "params": {
                    "command": "${producer.stdout}",
                    "cwd": "${producer.stdout.nested}",
                },
            },
        ],
        "edges": [{"from": "producer", "to": "consumer"}],
    }

    result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

    # Must fail
    assert result.success is False

    # _pflow_node_id survived → error diagnostic has node_id
    assert result.errors, "Expected at least one error diagnostic"
    error = result.errors[0]
    assert error.node_id == "consumer", (
        f"Expected node_id='consumer' from _pflow_node_id annotation, got '{error.node_id}'"
    )

    # _pflow_shared_store survived → shared_after is populated with
    # producer's output and __failures__ archive
    assert result.shared_after, "Expected populated shared_after from _pflow_shared_store annotation"
    assert "producer" in result.shared_after, "Expected producer's output in shared_after"
    assert "__failures__" in result.shared_after, "Expected __failures__ in shared_after"
    assert "consumer" in result.shared_after["__failures__"], "Expected consumer in __failures__"

    # _pflow_template_diagnostic survived → error has structured context
    # with unresolved_references (not a flat string)
    ctx = error.context or {}
    assert ctx.get("category") == "template_error", (
        f"Expected category='template_error' from _pflow_template_diagnostic, got '{ctx.get('category')}'"
    )
    refs = ctx.get("unresolved_references")
    assert refs, "Expected unresolved_references in error context — _pflow_template_diagnostic annotation was lost"
    assert any(r.get("root") == "producer" and r.get("status") == "path_error" for r in refs), (
        f"Expected path_error reference to 'producer' in unresolved_references, got: {refs}"
    )


# ---------------------------------------------------------------------------
# Inline workflow cache scoping (L2 fix)
#
# Inline runs (dict, content-string, MCP-inline) historically wrote rows with
# `workflow_path = NULL` to the memo cache. SQL `WHERE workflow_path = NULL`
# matches zero rows, so `get_latest_for_node` would fall back to unscoped
# lookup and pool history across unrelated inline workflows that happened to
# share node IDs. `_synthesize_inline_workflow_id` gives each distinct inline
# IR its own scope without requiring a filesystem path.
# ---------------------------------------------------------------------------


def test_synthesize_inline_workflow_id_is_stable_for_same_ir():
    """Same IR → same synthetic id. Cache reads must resolve deterministically."""
    ir = {
        "nodes": [{"id": "a", "type": "shell", "params": {"command": "echo a"}}],
        "edges": [],
    }
    assert _synthesize_inline_workflow_id(ir) == _synthesize_inline_workflow_id(ir)


def test_synthesize_inline_workflow_id_differs_across_distinct_ir():
    """Distinct IRs → distinct ids. Prevents cross-workflow pollution."""
    ir_a = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo a"}}], "edges": []}
    ir_b = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo b"}}], "edges": []}
    assert _synthesize_inline_workflow_id(ir_a) != _synthesize_inline_workflow_id(ir_b)


def test_synthesize_inline_workflow_id_uses_ir_hash_prefix():
    """Identifier format is stable-contract: 'ir-hash:<hex>'. Agents may parse it."""
    ir = {"nodes": [], "edges": []}
    assert _synthesize_inline_workflow_id(ir).startswith("ir-hash:")


def test_inline_dict_run_scopes_cache_to_ir_hash():
    """Running a dict IR injects a synthetic `ir-hash:` scope into the shared store.

    This is the load-bearing integration test for the L2 fix: without the
    synthesis, `_pflow_workflow_file` would be absent and the memo cache
    would write NULL → downstream `get_latest_for_node` scoped lookups
    silently pool across unrelated inline workflows.

    The exact hash bytes depend on IR normalization (which adds ir_version,
    normalizes edges, etc.), so the test asserts on structure rather than a
    pre-computed value — stability and distinctness are covered by the
    helper's direct unit tests above.
    """
    ir = {
        "nodes": [{"id": "only", "type": "shell", "params": {"command": "echo hello"}}],
        "edges": [],
    }
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.success, f"Fresh inline run failed: {result.errors}"

    workflow_file = result.shared_after.get("_pflow_workflow_file")
    assert workflow_file is not None, "Inline run must inject _pflow_workflow_file"
    assert workflow_file.startswith("ir-hash:"), f"Inline run must use synthetic ir-hash id, got: {workflow_file!r}"
    # md5 hex is 32 chars; full identifier is 'ir-hash:' (8) + 32 = 40
    assert len(workflow_file) == 40, f"Unexpected id length: {workflow_file!r}"


def test_caller_injected_workflow_file_preserved():
    """Callers pre-injecting _pflow_workflow_file keep their value — runner uses setdefault.

    MCP server and CLI pre-inject file paths today. The runner must not
    overwrite. Without `setdefault`, the runner would clobber the caller's
    value with an IR hash even on file/library runs that flow through MCP.
    """
    ir = {
        "nodes": [{"id": "only", "type": "shell", "params": {"command": "echo hello"}}],
        "edges": [],
    }
    caller_path = "/absolute/path/caller/injected.pflow.md"
    params = {"_pflow_workflow_file": caller_path}

    result = WorkflowRunner().run(ir, params, RunnerConfig())
    assert result.success, f"Run failed: {result.errors}"
    assert result.shared_after["_pflow_workflow_file"] == caller_path
