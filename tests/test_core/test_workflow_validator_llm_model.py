"""Tests for the LLM-model-id branch of validator step 9.

Covers the algorithm in
``WorkflowValidator._validate_node_param_semantics`` → LLM branch:

1. Skip templated ``${...}`` model values.
2. Skip non-canonical providers (e.g. ``openrouter/...``).
3. Reject wrong-type ``model:`` values with ``llm.model-not-string``.
4. Skip absent/empty ``model:`` (compiler handles default).
5. Emit ``MissingApiKeyError`` for canonical provider + missing key.
6. No diagnostic for bundled, valid models.
7. Bare-name normalization handles e.g. ``claude-sonnet-4-5``.
8. Upstream merge for unbundled-but-real models.
9. ``UnknownModelError`` for truly unknown models.
10. ``llm.catalog-unreachable`` INFO when upstream fetch fails.
11. Zero-LLM-node workflows pay zero cost.
12. Sub-workflow nodes surface child diagnostics with provenance.
13. Multiple LLM nodes with same bad config each emit separate diagnostics.
14. Save path runs the same validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.workflow.validator import WorkflowValidator


@pytest.fixture
def reset_validator_latch(monkeypatch: pytest.MonkeyPatch):
    """Reset both validator-side flags so each catalog-check test starts fresh.

    Overrides the autouse ``_block_upstream_cost_map_fetch`` fixture for tests
    that need to exercise the actual catalog-check + ``try_load_upstream_catalog``
    code path. Without this, every test would see the pre-latched "success"
    state and skip the merge call entirely.
    """
    from pflow.core import litellm_runtime

    monkeypatch.setattr(litellm_runtime, "_validator_upstream_attempted", False)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_fetch_succeeded", False)
    return litellm_runtime


def _llm_workflow(model: Any, node_id: str = "n1") -> dict[str, Any]:
    """Minimal IR with a single LLM node."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": node_id,
                "type": "llm",
                "params": {"prompt": "hello", "model": model},
            }
        ],
    }


def _validate(workflow_ir: dict[str, Any]) -> list:
    """Run validator skipping registry-dependent steps for laser focus on step 9."""
    return WorkflowValidator.validate(workflow_ir, skip_node_types=True)


def _no_litellm_imported(real_import_litellm) -> bool:
    """Helper: under the patched import_litellm, check that it was NOT called."""
    return real_import_litellm.call_count == 0


# =========================================================================
# 1. Templated model — defer to runtime
# =========================================================================


def test_templated_model_defers_and_does_not_import_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """``${...}`` skips catalog check; no litellm import fired.

    The data-flow validator may still complain about the template root if
    it doesn't reference a declared input — that's orthogonal to step 9.
    What we pin here is: no llm-validation diagnostic AND no litellm import.
    """
    workflow = _llm_workflow("${input.model}")

    with patch("pflow.core.litellm_runtime.import_litellm") as mock_import:
        diagnostics = _validate(workflow)

    llm_validation_diags = [d for d in diagnostics if (d.context or {}).get("category") == "llm_validation"]
    assert llm_validation_diags == []
    mock_import.assert_not_called()


# =========================================================================
# 2. Non-canonical provider — trust user
# =========================================================================


def test_non_canonical_provider_skips_and_does_not_import_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """``openrouter/...`` isn't in pflow's canonical registry; skip silently."""
    workflow = _llm_workflow("openrouter/anthropic/claude-foo")

    with patch("pflow.core.litellm_runtime.import_litellm") as mock_import:
        diagnostics = _validate(workflow)

    assert diagnostics == []
    mock_import.assert_not_called()


# =========================================================================
# 3. Wrong-type ``model:`` — emit ``llm.model-not-string``
# =========================================================================


@pytest.mark.parametrize(
    "bad_model,expected_type",
    [
        (0, "int"),
        (False, "bool"),
        ([], "list"),
        ({}, "dict"),
    ],
)
def test_wrong_type_model_emits_typed_error(
    monkeypatch: pytest.MonkeyPatch, bad_model: Any, expected_type: str
) -> None:
    """Non-string ``model:`` values fail at validate time with structured context.

    Confirmed: this case bypasses both the compiler's default-injection guard
    (``"model" not in params``) AND the bundled catalog (different type) —
    only the new step 9 LLM branch catches it.
    """
    workflow = _llm_workflow(bad_model)

    with patch("pflow.core.litellm_runtime.import_litellm") as mock_import:
        diagnostics = _validate(workflow)

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert len(errors) == 1
    err = errors[0]
    assert err.id == "llm.model-not-string"
    assert err.context["value_type"] == expected_type
    assert err.source == "validator"
    assert err.node_id == "n1"
    mock_import.assert_not_called()


# =========================================================================
# 4. Empty/absent model — treat as absent
# =========================================================================


@pytest.mark.parametrize("empty_value", [None, ""])
def test_empty_model_treated_as_absent_no_diagnostic(empty_value: Any) -> None:
    """``model: ""`` and ``model: null`` defer to the compiler default."""
    workflow = _llm_workflow(empty_value)
    diagnostics = _validate(workflow)
    assert [d for d in diagnostics if d.severity == Severity.ERROR] == []


def test_model_key_absent_defers_to_compiler() -> None:
    """A workflow with no ``model:`` key at all skips step 9 silently."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "n1", "type": "llm", "params": {"prompt": "hello"}}],
    }
    diagnostics = _validate(workflow)
    assert [d for d in diagnostics if d.severity == Severity.ERROR] == []


# =========================================================================
# 5. Canonical provider + missing key — MissingApiKeyError
# =========================================================================


@pytest.mark.no_fake_llm_keys
def test_canonical_provider_missing_key_emits_missing_api_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``openai/gpt-4o`` with no OPENAI_API_KEY produces the validator-decorated MissingApiKeyError.

    Marker disables the autouse fake-key fixture AND actively scrubs the four
    canonical env vars so the missing-key check fires.
    """
    workflow = _llm_workflow("openai/gpt-4o")

    with patch("pflow.core.litellm_runtime.import_litellm") as mock_import:
        diagnostics = _validate(workflow)

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert len(errors) == 1
    err = errors[0]
    assert err.source == "validator"
    assert err.context["category"] == "llm_validation"
    assert err.context["path"] == "nodes[id=n1].params.model"
    # provider_message is stripped at validate-time (always None pre-call).
    assert "provider_message" not in err.context
    # ``MissingApiKeyError.to_diagnostics()`` carries the env-var hint.
    assert err.context["error_class"] == "MissingApiKeyError"
    assert err.context["kind"] == "missing_key"
    mock_import.assert_not_called()


# =========================================================================
# 6 + 7. Bundled / bare-name normalization — no diagnostic, no fetch
# =========================================================================


def test_bundled_prefixed_model_passes_without_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """``anthropic/claude-sonnet-4-5`` resolves via bundled catalog — no upstream fetch."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    workflow = _llm_workflow("anthropic/claude-sonnet-4-5")

    with patch("pflow.core.litellm_runtime.try_load_upstream_catalog") as mock_load:
        diagnostics = _validate(workflow)

    assert diagnostics == []
    mock_load.assert_not_called()


def test_bare_name_resolves_via_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """``claude-sonnet-4-5`` (bare) maps to anthropic via ``detect_provider`` + bundled lookup.

    Pins the normalize-before-lookup fix: without it, bare names would be
    flagged as Unknown Model when the bundled catalog only has the bare form.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    workflow = _llm_workflow("claude-sonnet-4-5")

    with patch("pflow.core.litellm_runtime.try_load_upstream_catalog") as mock_load:
        diagnostics = _validate(workflow)

    assert diagnostics == []
    mock_load.assert_not_called()


# =========================================================================
# 8. Unbundled-but-real — upstream merge succeeds, no diagnostic
# =========================================================================


def test_unbundled_but_real_model_passes_via_upstream_merge(
    reset_validator_latch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model missing from bundle but present in upstream → catalog merge fills in, no error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()
    # Remove the bundled entry so the catalog miss forces an upstream fetch.
    real_cost = dict(litellm.model_cost)
    real_cost.pop("claude-sonnet-4-5", None)
    real_cost.pop("anthropic/claude-sonnet-4-5", None)
    monkeypatch.setattr(litellm, "model_cost", real_cost, raising=False)

    fetch_count = {"n": 0}

    def fake_get(url, *args, **kwargs):
        fetch_count["n"] += 1
        from unittest.mock import MagicMock

        return MagicMock(
            raise_for_status=lambda: None,
            json=lambda: {
                "claude-sonnet-4-5": {"input_cost_per_token": 3e-6, "litellm_provider": "anthropic", "mode": "chat"},
            },
        )

    import httpx

    monkeypatch.setattr(httpx, "get", fake_get)

    # Real register_model — let it actually merge into our patched dict so
    # subsequent membership reads see the new entry.
    workflow = _llm_workflow("claude-sonnet-4-5")
    diagnostics = _validate(workflow)

    assert diagnostics == []
    assert fetch_count["n"] == 1


# =========================================================================
# 9. Catalog-miss after upstream merge — WARNING (severity-policy choice)
# =========================================================================


def test_catalog_miss_after_upstream_merge_emits_warning(
    reset_validator_latch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upstream fetch succeeds but the model isn't there → WARNING (not ERROR).

    Severity-policy choice: ``litellm.model_cost`` is a pricing catalog, not
    a "this name is callable" registry. Fine-tunes, custom endpoints, and
    brand-new models may be missing from the catalog but still callable at
    runtime. Emitting WARNING preserves the original-bug fix (the warning
    surfaces at validate time before any execution) without blocking
    legitimate workflows on ``--validate-only`` / ``save``.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    import httpx

    def fake_get(url, *args, **kwargs):
        from unittest.mock import MagicMock

        return MagicMock(
            raise_for_status=lambda: None,
            # Well-formed entry per the new shape-validation contract.
            json=lambda: {
                "gpt-4o": {
                    "input_cost_per_token": 5e-6,
                    "litellm_provider": "openai",
                    "mode": "chat",
                }
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    workflow = _llm_workflow("openai/gpt-totally-made-up-9.9")
    diagnostics = _validate(workflow)

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    assert errors == []
    assert len(warnings) == 1
    warn = warnings[0]
    assert warn.source == "validator"
    assert warn.id == "llm.model-not-in-catalog"
    assert warn.context["category"] == "llm_validation"
    assert warn.context["model"] == "openai/gpt-totally-made-up-9.9"
    assert warn.context["provider"] == "openai"
    assert warn.context["reason"] == "not_in_catalog"


# =========================================================================
# 10. Network failure — INFO breadcrumb ``llm.catalog-unreachable``
# =========================================================================


def test_network_failure_emits_info_breadcrumb(reset_validator_latch, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the upstream fetch fails, defer + emit one INFO ``llm.catalog-unreachable``."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    import httpx

    def failing_get(url, *args, **kwargs):
        raise httpx.ConnectError("simulated outage")

    monkeypatch.setattr(httpx, "get", failing_get)

    workflow = _llm_workflow("openai/gpt-totally-made-up-9.9")
    diagnostics = _validate(workflow)

    # No ERROR diagnostic (deferred), one INFO breadcrumb.
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    infos = [d for d in diagnostics if d.severity == Severity.INFO]
    assert errors == []
    assert len(infos) == 1
    info = infos[0]
    assert info.id == "llm.catalog-unreachable"
    assert info.context["deferred_node_ids"] == ["n1"]


# =========================================================================
# 11. Zero LLM nodes — no litellm import at all
# =========================================================================


def test_zero_llm_nodes_does_not_import_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow with only non-LLM nodes pays zero cost.

    ``cache: false`` on the shell node silences the unrelated step-11 cache
    lint warning; the assertion below targets only LLM-validation behavior.
    """
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "s", "type": "shell", "cache": False, "params": {"command": "echo hi"}},
        ],
    }

    with patch("pflow.core.litellm_runtime.import_litellm") as mock_import:
        diagnostics = _validate(workflow)

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert errors == []
    mock_import.assert_not_called()


# =========================================================================
# 12. Sub-workflow with bad model — diagnostic propagates with provenance
# =========================================================================


@pytest.mark.no_fake_llm_keys
def test_sub_workflow_bad_model_surfaces_via_child_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad model inside a sub-workflow surfaces with ``In step 'X' sub-workflow:`` prefix.

    Marker disables the autouse fake-key fixture AND actively scrubs env keys
    so the missing-key check fires.
    """
    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(
        "# Child\n\n"
        "Child workflow with a bad model.\n\n"
        "## Steps\n\n"
        "### llm-node\n\n"
        "Calls llm.\n\n"
        "- type: llm\n"
        "- model: openai/gpt-4o\n"
        "- prompt: hello\n"
    )

    parent_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "child-step",
                "type": "workflow",
                "params": {"workflow": str(child_path)},
            }
        ],
    }

    diagnostics = WorkflowValidator.validate(
        parent_ir, skip_node_types=True, workflow_file=tmp_path / "parent.pflow.md"
    )
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]

    # The child-step's missing-key error should propagate with provenance.
    assert any(
        d.context.get("sub_workflow_step") == "child-step" and d.context.get("category") == "llm_validation"
        for d in errors
    ), (
        f"Expected validator-decorated llm_validation diagnostic from child; got {[(d.message, d.context) for d in errors]}"
    )


# =========================================================================
# 13. Multiple LLM nodes, same bad model — distinct diagnostics
# =========================================================================


def test_multiple_llm_nodes_same_bad_model_emit_distinct_diagnostics(
    reset_validator_latch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two LLM nodes using the same unknown model produce two WARNING diagnostics."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    fetch_count = {"n": 0}

    def fake_get(url, *args, **kwargs):
        fetch_count["n"] += 1
        from unittest.mock import MagicMock

        # Well-formed entry per new shape-validation contract.
        return MagicMock(
            raise_for_status=lambda: None,
            json=lambda: {"some/other-model": {"mode": "chat", "litellm_provider": "openai"}},
        )

    import httpx

    monkeypatch.setattr(httpx, "get", fake_get)

    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "a", "type": "llm", "params": {"prompt": "p", "model": "openai/gpt-bad-9.9"}},
            {"id": "b", "type": "llm", "params": {"prompt": "p", "model": "openai/gpt-bad-9.9"}},
        ],
    }
    diagnostics = _validate(workflow)
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]

    # Two distinct diagnostics (different node_id ⇒ different __hash__).
    assert len(warnings) == 2
    node_ids = sorted({d.node_id for d in warnings})
    assert node_ids == ["a", "b"]
    # Exactly one upstream fetch was made for all nodes combined.
    assert fetch_count["n"] == 1


# =========================================================================
# 14. Save path runs the same validation
# =========================================================================


@pytest.mark.no_fake_llm_keys
def test_save_path_runs_llm_model_validation(tmp_path: Path) -> None:
    """``save_workflow_with_options`` calls ``WorkflowValidator.validate`` and surfaces the same diagnostics.

    Marker disables the autouse fake-key fixture AND actively scrubs env keys
    so the missing-key check fires.
    """
    from pflow.core.exceptions import WorkflowValidationError
    from pflow.core.workflow.save_service import save_workflow_with_options

    markdown_content = (
        "# Bad model workflow\n\n"
        "Demo of save-time validation.\n\n"
        "## Steps\n\n"
        "### call-llm\n\n"
        "Calls an LLM with a bad model.\n\n"
        "- type: llm\n"
        "- model: openai/gpt-4o\n"
        "- prompt: hello\n"
    )

    with pytest.raises(WorkflowValidationError) as exc_info:
        save_workflow_with_options("test-bad-model", markdown_content, force=False)

    # The validator's missing-key error must be present in the wrapped diagnostics.
    diags = exc_info.value.validation_errors
    assert any(
        d.context.get("category") == "llm_validation" and d.context.get("error_class") == "MissingApiKeyError"
        for d in diags
    ), f"Expected llm_validation MissingApiKeyError; got {[(d.message, d.context) for d in diags]}"


@pytest.mark.no_fake_llm_keys
def test_no_fake_llm_keys_marker_scrubs_canonical_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the strengthened marker behavior: env keys ARE absent under the marker.

    The marker was previously a passive disable (just skipping injection).
    A developer's actual shell with real keys could leak through and cause
    missing-key tests to silently pass for the wrong reason. The marker now
    actively scrubs ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``GEMINI_API_KEY``,
    ``GOOGLE_API_KEY`` — proven here by manually setting them BEFORE the
    fixture runs.

    Note: the assertion runs INSIDE the test body, after the fixture has
    applied. The monkeypatch.setenv calls inside the body are a sanity check;
    they don't subvert the fixture (the fixture already ran).
    """
    import os

    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        # Fixture scrubbed pre-test. Inside the body, confirm absence.
        assert var not in os.environ, f"{var} should be scrubbed by no_fake_llm_keys marker, but is set"


# =========================================================================
# 15. Cross-provider false positive guard (review finding W3)
# =========================================================================


def test_cross_provider_bare_name_does_not_silently_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    """``anthropic/gpt-4`` (wrong provider for the bare-name family) MUST emit a WARNING.

    Without the per-entry provider check, the bare form ``gpt-4`` is in
    ``litellm.model_cost`` (bundled under openai) and a naive membership
    test would silently accept the workflow. The new step 9 reads
    ``litellm_provider`` from the catalog entry and rejects the bare-form
    match when it explicitly names a DIFFERENT canonical provider.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    workflow = _llm_workflow("anthropic/gpt-4")

    diagnostics = _validate(workflow)
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]

    assert errors == []
    assert len(warnings) == 1
    warn = warnings[0]
    assert warn.id == "llm.model-not-in-catalog"
    assert warn.context["model"] == "anthropic/gpt-4"
    assert warn.context["provider"] == "anthropic"


def test_correct_provider_bare_name_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """``openai/gpt-4`` (correct provider for bare-name match) passes — sanity guard.

    Pins that the cross-provider check is precise: it rejects ONLY the
    canonical-mismatch case, never legitimate prefixed-name lookups that
    resolve to a bare bundled entry.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    workflow = _llm_workflow("openai/gpt-4")

    diagnostics = _validate(workflow)
    assert [d for d in diagnostics if d.severity == Severity.WARNING] == []
    assert [d for d in diagnostics if d.severity == Severity.ERROR] == []


# =========================================================================
# 16. Case-preserving bare lookup (review finding C1 validation-consistency)
# =========================================================================


def test_mixed_case_model_does_not_lowercase_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Anthropic/Claude-Sonnet-4-5`` (mixed case) does NOT silently pass via lowercased lookup.

    Pins the case-preserving fix: ``model_name_without_provider`` lowercases,
    so without the validator-local ``_strip_provider_prefix_case_preserving``
    helper the mixed-case input would match the lowercase catalog entry at
    validate time but runtime might reject the mixed-case call. WARNING
    surfaces (catalog-miss) rather than silent acceptance.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    workflow = _llm_workflow("Anthropic/Claude-Sonnet-4-5")

    diagnostics = _validate(workflow)
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]

    assert errors == []
    # Catalog-miss WARNING (mixed-case form isn't in any catalog candidate).
    assert any(d.id == "llm.model-not-in-catalog" for d in warnings)


def test_strip_provider_prefix_case_preserving_helper() -> None:
    """Unit test the case-preserving prefix stripper directly."""
    from pflow.core.workflow.validator import WorkflowValidator

    # Case 1: prefixed model — strip provider prefix, preserve suffix case.
    assert (
        WorkflowValidator._strip_provider_prefix_case_preserving("anthropic/Claude-Sonnet-4-5", "anthropic/")
        == "Claude-Sonnet-4-5"
    )
    # Case 2: prefixed with mixed-case prefix — still recognize and strip.
    assert (
        WorkflowValidator._strip_provider_prefix_case_preserving("Anthropic/Claude-Sonnet-4-5", "anthropic/")
        == "Claude-Sonnet-4-5"
    )
    # Case 3: bare name (no prefix) — return unchanged.
    assert (
        WorkflowValidator._strip_provider_prefix_case_preserving("claude-sonnet-4-5", "anthropic/")
        == "claude-sonnet-4-5"
    )
    # Case 4: model with different prefix — return unchanged (not matching).
    assert WorkflowValidator._strip_provider_prefix_case_preserving("openai/gpt-4", "anthropic/") == "openai/gpt-4"
    # Case 5: defensive — mixed-case PREFIX argument still strips correctly.
    # Pins the lower-internally normalization; without it the helper would
    # silently fail to strip if a future caller passes "Anthropic/".
    assert (
        WorkflowValidator._strip_provider_prefix_case_preserving("anthropic/Claude-Sonnet-4-5", "Anthropic/")
        == "Claude-Sonnet-4-5"
    )
