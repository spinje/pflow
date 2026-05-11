"""Tests for cache reference / order / non-LLM-type validation in data_flow.py
(Task 159 B2.3).

The validator runs through ``validate_data_flow`` so it picks up at both entry
points (save-time ``WorkflowValidator`` and compile-time ``compile_validation``).
This file tests the new ``_validate_cache_block`` rules:

  - ``cache.order-mismatch`` — per-node ``prompt_cache:`` out of declaration order.
  - ``cache.invalid-on-non-llm`` — combined-diagnostic shape (V6 fix): ONE
    diagnostic per offending node listing ALL invalid fields, not one per field.
  - ``cache.unused-chunk`` — declared chunk that no node references.
  - Reference-resolution errors — ``prompt_cache: [unknown]`` and ``${batch-scoped}``
    in cache items, flowed through the existing diagnostic pipeline.
  - Defensive shape skip on the compile path (V5 fix).
"""

from __future__ import annotations

import logging

import pytest

from pflow.core.diagnostic import CACHE_FAILURE_CATEGORY, CACHE_WARNING_CATEGORY, Severity
from pflow.core.workflow.data_flow import validate_data_flow


def _shell_node(node_id: str = "shell-1", **extras) -> dict:
    """Helper: build a minimal-but-valid shell node IR dict with optional extras."""
    node = {"id": node_id, "type": "shell", "params": {"command": "echo hi"}}
    node.update(extras)
    return node


def _llm_node(node_id: str = "llm-1", **extras) -> dict:
    """Helper: build a minimal-but-valid llm node IR dict with optional extras."""
    node = {
        "id": node_id,
        "type": "llm",
        "params": {"prompt": "do thing", "model": "anthropic/claude-sonnet-4-5"},
    }
    node.update(extras)
    return node


def _ir(nodes: list[dict], cache: dict | None = None, inputs: dict | None = None) -> dict:
    """Build a workflow IR dict for validate_data_flow."""
    ir: dict = {"ir_version": "0.1.0", "nodes": nodes}
    if cache is not None:
        ir["cache"] = cache
    if inputs is not None:
        ir["inputs"] = inputs
    return ir


# ------------------------------------------------------------------------------
# cache.order-mismatch
# ------------------------------------------------------------------------------


def test_order_mismatch_emits_exact_message_format() -> None:
    """The error message uses the spec-locked four-line format with bare-identifier
    bracketed lists (NOT Python repr quoted form)."""
    ir = _ir(
        nodes=[
            _llm_node("write-lyrics", prompt_cache=["concept_brief", "concept"]),
        ],
        inputs={
            "concept": {"type": "string", "required": True},
            "concept_brief": {"type": "string", "required": True},
        },
        cache={
            "items": [
                {"name": "concept", "var": "concept", "prose_before": ""},
                {"name": "concept_brief", "var": "concept_brief", "prose_before": ""},
            ],
        },
    )
    diagnostics = validate_data_flow(ir)
    order_errors = [d for d in diagnostics if d.id == "cache.order-mismatch"]
    assert len(order_errors) == 1
    diag = order_errors[0]
    assert diag.severity == Severity.ERROR
    assert diag.source == "validator"
    assert diag.node_id == "write-lyrics"
    # Spec-locked message format (bare identifiers, exact whitespace).
    # ``expected:`` shows the subset reordered to match ## Cache declaration —
    # the exact replacement to write. Renamed from ``declared:`` for clarity
    # (the line shows the subset, not the full ## Cache block).
    assert diag.message == (
        "Node 'write-lyrics' prompt_cache order doesn't match ## Cache declaration\n"
        "  expected:  [concept, concept_brief]\n"
        "  you wrote: [concept_brief, concept]\n"
        "  fix:       reorder the `prompt_cache:` field to match ## Cache declaration order"
    )
    # Structured context preserves the typed lists alongside formatted strings.
    assert diag.context["declared"] == ["concept", "concept_brief"]
    assert diag.context["actual"] == ["concept_brief", "concept"]
    assert diag.context["category"] == CACHE_FAILURE_CATEGORY


def test_order_correct_does_not_emit_order_mismatch() -> None:
    """No order-mismatch when declaration order is preserved."""
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=["a", "b", "c"])],
        inputs={"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": "string"}},
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
                {"name": "c", "var": "c", "prose_before": ""},
            ],
        },
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.order-mismatch"]


def test_order_subset_in_declaration_order_does_not_emit() -> None:
    """A node may reference a SUBSET of cache items; subset must be in declaration order."""
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=["a", "c"])],  # skips b
        inputs={"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": "string"}},
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
                {"name": "c", "var": "c", "prose_before": ""},
            ],
        },
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.order-mismatch"]


# ------------------------------------------------------------------------------
# cache.invalid-on-non-llm — V6 combined-diagnostic shape
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_type, type_specific_params",
    [
        ("shell", {"command": "echo x"}),
        ("http", {"url": "https://example.com"}),
        ("file", {"path": "data/x.txt", "mode": "read"}),
        ("python", {"code": "result = 1"}),
        ("workflow", {"workflow": "child", "inputs": {}}),
    ],
)
def test_prompt_cache_on_non_llm_node_rejected(node_type: str, type_specific_params: dict) -> None:
    """Each non-LLM node type rejects ``prompt_cache:`` with cache.invalid-on-non-llm."""
    ir = _ir(
        nodes=[
            {
                "id": "x",
                "type": node_type,
                "params": type_specific_params,
                "prompt_cache": ["concept"],
            },
            _llm_node("filler"),  # so cache items are referenced; not strictly needed
        ],
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
        inputs={"concept": {"type": "string"}},
    )
    diagnostics = validate_data_flow(ir)
    invalid = [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert len(invalid) == 1
    diag = invalid[0]
    assert diag.severity == Severity.ERROR
    assert diag.source == "validator"
    assert diag.node_id == "x"
    assert diag.context["invalid_fields"] == ["prompt_cache"]
    assert diag.context["category"] == CACHE_FAILURE_CATEGORY
    # Locked hint phrasing
    assert "type: llm" in " ".join(diag.suggestions or [])


def test_llm_type_positive_control_does_not_emit_invalid_on_non_llm() -> None:
    """Type:llm + prompt_cache must NOT emit cache.invalid-on-non-llm."""
    ir = _ir(
        nodes=[_llm_node("ok", prompt_cache=["concept"])],
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
        inputs={"concept": {"type": "string"}},
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]


def test_combined_diagnostic_lists_all_invalid_fields() -> None:
    """V6 fix: when BOTH prompt_cache AND prewarm are declared on a non-LLM node,
    emit ONE diagnostic with ``context["invalid_fields"] == ["prompt_cache", "prewarm"]``,
    not one per field."""
    ir = _ir(
        nodes=[
            {
                "id": "x",
                "type": "shell",
                "params": {"command": "echo x"},
                "prompt_cache": ["concept"],
                "prewarm": True,
            }
        ],
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
        inputs={"concept": {"type": "string"}},
    )
    diagnostics = validate_data_flow(ir)
    invalid = [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert len(invalid) == 1
    assert invalid[0].context["invalid_fields"] == ["prompt_cache", "prewarm"]
    # Both field names appear in the message
    assert "prompt_cache" in invalid[0].message
    assert "prewarm" in invalid[0].message


def test_only_prewarm_on_non_llm_emits_single_diagnostic() -> None:
    """``prewarm: true`` alone (no ``prompt_cache:``) on a non-LLM node still rejects."""
    ir = _ir(nodes=[_shell_node(prewarm=True)])
    diagnostics = validate_data_flow(ir)
    invalid = [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert len(invalid) == 1
    assert invalid[0].context["invalid_fields"] == ["prewarm"]


def test_missing_type_field_does_not_emit_cache_invalid_on_non_llm() -> None:
    """Schema-required ``type`` missing — the invalid-on-non-llm rule must NOT fire
    (the structural error from missing-required-type surfaces separately)."""
    ir = _ir(
        nodes=[
            # Intentionally no "type" field. Schema rejects upstream; data_flow's
            # cache.invalid-on-non-llm rule must NOT fire to avoid rendering "type: ".
            {"id": "x", "params": {}, "prompt_cache": ["x"]},
        ]
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]


def test_malformed_type_field_does_not_emit_cache_invalid_on_non_llm() -> None:
    """``type: ["llm"]`` (list, not string) is a structural error — cache rule
    must isinstance-gate on string to avoid firing for the wrong reason."""
    ir = _ir(
        nodes=[
            {"id": "x", "type": ["llm"], "params": {}, "prompt_cache": ["x"]},
        ]
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]


# ------------------------------------------------------------------------------
# cache.unused-chunk
# ------------------------------------------------------------------------------


def test_unused_chunk_emits_warning() -> None:
    """A chunk declared in ## Cache that no node references → cache.unused-chunk warning."""
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=["a"])],
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "unused_b", "var": "unused_b", "prose_before": ""},
            ],
        },
        inputs={"a": {"type": "string"}, "unused_b": {"type": "string"}},
    )
    diagnostics = validate_data_flow(ir)
    unused = [d for d in diagnostics if d.id == "cache.unused-chunk"]
    assert len(unused) == 1
    assert unused[0].severity == Severity.WARNING
    assert "unused_b" in unused[0].message
    assert unused[0].context["chunk_name"] == "unused_b"
    assert unused[0].context["category"] == CACHE_WARNING_CATEGORY


def test_unused_chunk_not_emitted_when_all_referenced() -> None:
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=["a", "b"])],
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
            ],
        },
        inputs={"a": {"type": "string"}, "b": {"type": "string"}},
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.unused-chunk"]


# ------------------------------------------------------------------------------
# Reference-resolution errors (no cache.* id — flow through validation pipeline)
# ------------------------------------------------------------------------------


def test_undeclared_chunk_in_prompt_cache_emits_resolution_error() -> None:
    """``prompt_cache: [unknown]`` referencing a name not in ## Cache items → ERROR
    with similar-names hint."""
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=["unknwon"])],  # typo
        cache={
            "items": [
                {"name": "unknown", "var": "unknown", "prose_before": ""},
            ],
        },
        inputs={"unknown": {"type": "string"}},
    )
    diagnostics = validate_data_flow(ir)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR and "unknwon" in d.message]
    assert errors
    diag = errors[0]
    # Should suggest the closest match
    assert any("unknown" in s for s in (diag.suggestions or []))


def test_batch_scoped_chunk_var_rejected() -> None:
    """``${item.X}`` in a cache chunk's var → ERROR (batch-scoped references aren't
    stable across calls, so they're invalid in ## Cache per spec)."""
    ir = _ir(
        nodes=[
            {
                "id": "batch-step",
                "type": "llm",
                "params": {"prompt": "p", "model": "anthropic/claude-sonnet-4-5"},
                "batch": {"items": [{"x": "1"}, {"x": "2"}], "as": "item"},
            },
        ],
        cache={
            "items": [
                {"name": "item.x", "var": "item.x", "prose_before": ""},
            ],
        },
    )
    diagnostics = validate_data_flow(ir)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR and "batch" in d.message.lower()]
    assert errors


# ------------------------------------------------------------------------------
# Defensive shape skip on the compile path (V5 fix)
# ------------------------------------------------------------------------------


def test_malformed_prompt_cache_on_llm_node_skips_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """The compile path bypasses jsonschema (it uses minimal validate_ir_structure),
    so ``prompt_cache: 5`` (wrong type) on a type:llm node must NOT raise here.
    Instead, log a warning and skip semantic checks for that node — the deeper
    error surfaces at NodeConfig construction.

    On the validator path, jsonschema (step 1) catches the shape error and
    short-circuits before reaching here. Either way, no cache.* diagnostic is
    emitted for shape errors — that's the V5 single-source-of-truth contract.
    """
    caplog.set_level(logging.WARNING, logger="pflow.core.workflow.data_flow")
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=5)]  # malformed: not a list
    )
    # No exception raised
    diagnostics = validate_data_flow(ir)
    # No cache.invalid-on-non-llm because type IS llm
    assert not [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    # Logger warning recorded
    assert any("malformed prompt_cache shape" in record.message for record in caplog.records)


def test_malformed_prewarm_on_llm_node_skips_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pflow.core.workflow.data_flow")
    ir = _ir(
        nodes=[_llm_node("x", prewarm=1)]  # int, not bool — bool is a subclass of int so use isinstance(x, bool)
    )
    diagnostics = validate_data_flow(ir)
    assert not [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert any("malformed prewarm shape" in record.message for record in caplog.records)


def test_non_llm_rejection_runs_BEFORE_shape_skip(caplog: pytest.LogCaptureFixture) -> None:
    """STEP-1 ordering: a type:shell node with malformed prompt_cache MUST emit
    cache.invalid-on-non-llm — the non-LLM rejection is shape-agnostic and fires
    BEFORE the defensive shape skip."""
    caplog.set_level(logging.WARNING, logger="pflow.core.workflow.data_flow")
    ir = _ir(
        nodes=[
            {
                "id": "x",
                "type": "shell",
                "params": {"command": "echo x"},
                "prompt_cache": 5,  # malformed AND non-LLM
            }
        ]
    )
    diagnostics = validate_data_flow(ir)
    invalid = [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert len(invalid) == 1, (
        f"Non-LLM rejection should fire on shape-malformed nodes — got {len(invalid)} diagnostics. "
        f"If shape skip ran first, the structured error would be silently dropped."
    )


def test_malformed_top_level_cache_block_skips_top_level_checks(caplog: pytest.LogCaptureFixture) -> None:
    """Top-level ``cache: 5`` (wrong type): skip cross-references / unused-chunk /
    batch-scoped checks, but per-node ``cache.invalid-on-non-llm`` still fires
    because it's independent of top-level cache shape."""
    caplog.set_level(logging.WARNING, logger="pflow.core.workflow.data_flow")
    ir: dict = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "x",
                "type": "shell",
                "params": {"command": "echo x"},
                "prompt_cache": ["chunk"],
            }
        ],
        "cache": 5,  # wrong type
    }
    diagnostics = validate_data_flow(ir)
    # Per-node check still fires
    invalid = [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert len(invalid) == 1
    # Top-level checks skipped — no unused-chunk, no resolution errors against cache.items
    assert not [d for d in diagnostics if d.id == "cache.unused-chunk"]
    # Single logger warning recorded for top-level skip
    assert any("malformed shape" in record.message for record in caplog.records)


# ------------------------------------------------------------------------------
# Empty / absent prompt_cache states
# ------------------------------------------------------------------------------


def test_duplicate_chunk_in_prompt_cache_emits_error() -> None:
    """``prompt_cache: [a, a]`` (same chunk listed twice) emits an actionable error.

    Mirrors the parser's per-block duplicate-${var} rule. Without this check,
    the chunk would render twice into the system prompt — wasted tokens and a
    silent semantic shift the author likely didn't intend.
    """
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=["a", "a", "b"])],
        inputs={"a": {"type": "string"}, "b": {"type": "string"}},
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
            ],
        },
    )
    diagnostics = validate_data_flow(ir)
    dup_errors = [d for d in diagnostics if "more than once" in d.message]
    assert len(dup_errors) == 1
    diag = dup_errors[0]
    assert diag.severity == Severity.ERROR
    assert diag.node_id == "x"
    assert diag.context["duplicates"] == ["a"]
    # Order error must NOT also fire (would be noise on top of duplicates).
    assert not [d for d in diagnostics if d.id == "cache.order-mismatch"]


def test_empty_prompt_cache_list_does_not_error() -> None:
    """``prompt_cache: []`` is equivalent to absence (DD#5) — no errors."""
    ir = _ir(
        nodes=[_llm_node("x", prompt_cache=[])],
    )
    diagnostics = validate_data_flow(ir)
    cache_diagnostics = [d for d in diagnostics if d.id and d.id.startswith("cache.")]
    assert not cache_diagnostics


def test_absent_prompt_cache_does_not_error() -> None:
    """No ``prompt_cache:`` field — node opts out of declared LLM caching, no errors."""
    ir = _ir(nodes=[_llm_node("x")])
    diagnostics = validate_data_flow(ir)
    cache_diagnostics = [d for d in diagnostics if d.id and d.id.startswith("cache.")]
    assert not cache_diagnostics


# ------------------------------------------------------------------------------
# V6 sub-workflow dedup tripwire
# ------------------------------------------------------------------------------


def test_parser_to_validator_pipeline_emits_order_mismatch(tmp_path) -> None:
    """Pattern 2 integration test: parse a real ``.pflow.md`` and run
    ``WorkflowValidator.validate()`` end-to-end.

    Hand-built IR fixtures (used by every other test in this file) test
    ``_validate_cache_block`` against a synthetic IR shape. They CAN'T catch:
      - Parser → IR shape drift (``cache.items`` field naming, ``_source_line``
        injection, ``prompt_cache:`` top-level extraction).
      - Schema → validator interaction (whether the schema rejects before
        ``_validate_cache_block`` runs, or vice versa).
      - Validator step ordering when other passes run first.

    Locks the parser-emitted IR shape against ``cache.order-mismatch`` firing
    correctly in the canonical workflow shape. If the parser changes how it
    populates ``cache.items[i].name`` or ``prompt_cache:`` extraction, this
    test fails with a clear signal.
    """
    from pflow.core.markdown_parser import parse_markdown
    from pflow.core.workflow.validator import WorkflowValidator

    workflow_path = tmp_path / "order-mismatch.pflow.md"
    workflow_path.write_text(
        "# Order Mismatch\n\n"
        "Workflow with prompt_cache: in wrong order.\n\n"
        "## Inputs\n\n"
        "### concept\n\nConcept input.\n\n- type: string\n- required: true\n\n"
        "### concept_brief\n\nBrief input.\n\n- type: string\n- required: true\n\n"
        "## Cache\n\n"
        "```cache\nThe concept:\n${concept}\n\nThe brief:\n${concept_brief}\n```\n\n"
        "## Steps\n\n"
        "### llm-step\n\nLLM with reversed prompt_cache.\n\n"
        "- type: llm\n"
        "- prompt_cache: [concept_brief, concept]\n"
        "- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nPrompt body referencing ${concept} and ${concept_brief}.\n```\n"
    )

    ir = parse_markdown(workflow_path.read_text()).ir
    ir.setdefault("ir_version", "0.1.0")
    diagnostics = WorkflowValidator.validate(ir, workflow_file=workflow_path)

    order_errors = [d for d in diagnostics if d.id == "cache.order-mismatch"]
    assert len(order_errors) == 1, (
        f"Expected one cache.order-mismatch through the parser→validator pipeline; "
        f"got: {[(d.id, d.message[:60]) for d in diagnostics]}"
    )
    assert order_errors[0].context["declared"] == ["concept", "concept_brief"]
    assert order_errors[0].context["actual"] == ["concept_brief", "concept"]


def test_v6_subworkflow_invalid_on_non_llm_via_real_validator(tmp_path) -> None:
    """V6 combined-diagnostic dedup contract — REAL parent → child propagation path.

    Replaces the earlier synthetic ``deduplicate_diagnostics`` test (which was a
    tautology: hashing two diagnostics with the same id necessarily collapses
    them — the test was testing the hash function, not the propagation path).

    Drives a real parent ``.pflow.md`` that invokes a real child ``.pflow.md``
    (which contains a non-LLM node with both ``prompt_cache:`` and ``prewarm:``
    declared) through ``WorkflowValidator.validate()``. The validator runs
    ``_validate_cache_block`` on both parent and child IRs, then
    ``_add_child_provenance`` wraps the child's diagnostics with parent context
    before merging into the parent's diagnostic list.

    Contract: the merged diagnostic list contains ONE
    ``cache.invalid-on-non-llm`` for the offending child node — id-keyed
    identity correctly handles the parent's recursive validation that walks
    the child IR before provenance wrapping happens.
    """
    from pflow.core.markdown_parser import parse_markdown
    from pflow.core.workflow.validator import WorkflowValidator

    child_path = tmp_path / "child-bad-non-llm.pflow.md"
    child_path.write_text(
        "# Child Bad Non-LLM\n\n"
        "Child workflow with a non-LLM node declaring prompt_cache + prewarm.\n\n"
        "## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n"
        "### bad-step\n\n"
        "Non-LLM node with cache fields.\n\n"
        "- type: shell\n"
        "- prompt_cache: [topic]\n"
        "- prewarm: true\n\n"
        '```shell command\necho "${topic}"\n```\n'
    )
    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(
        "# Parent\n\n"
        "Calls a child whose validation fails on cache.invalid-on-non-llm.\n\n"
        "## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n"
        "### invoke-child\n\n"
        "Call the broken child.\n\n"
        "- type: workflow\n"
        f"- workflow: ./{child_path.name}\n"
        "- inputs:\n"
        "    topic: ${topic}\n"
    )

    # Drive the standard WorkflowValidator path (mirrors `pflow validate-only`).
    parent_ir = parse_markdown(parent_path.read_text()).ir
    parent_ir.setdefault("ir_version", "0.1.0")
    diagnostics = WorkflowValidator.validate(parent_ir, workflow_file=parent_path)

    invalid = [d for d in diagnostics if d.id == "cache.invalid-on-non-llm"]
    assert len(invalid) == 1, (
        f"Expected exactly one cache.invalid-on-non-llm diagnostic from the parent→child "
        f"propagation path; got {len(invalid)}. Diagnostics: "
        f"{[(d.severity, d.id, d.node_id, d.message[:60]) for d in diagnostics]}"
    )
    diag = invalid[0]
    # Provenance prefix is applied (child diagnostic was wrapped via
    # _add_child_provenance with the parent's invocation step id).
    assert diag.message.startswith("In step 'invoke-child' sub-workflow:"), (
        f"Expected provenance prefix; got message: {diag.message!r}"
    )
    # The offending node's identity is preserved across propagation.
    assert diag.node_id == "bad-step"
    assert diag.context["invalid_fields"] == ["prompt_cache", "prewarm"]


# ------------------------------------------------------------------------------
# Task 159 follow-up — prompt-body / prompt_cache overlap detection
# ------------------------------------------------------------------------------


def _llm_node_with_prompt(node_id: str, prompt: str, **extras: object) -> dict:
    """Helper: LLM node with a custom prompt body (overlap tests need to
    control the prompt template — the default _llm_node uses 'do thing'
    which has no template refs)."""
    node = {
        "id": node_id,
        "type": "llm",
        "params": {"prompt": prompt, "model": "anthropic/claude-sonnet-4-5"},
    }
    node.update(extras)  # type: ignore[arg-type]
    return node


def test_full_path_overlap_emits_consolidated_duplicates_error() -> None:
    """``prompt_cache: [concept]`` + ``${concept}`` in body -> 1x ERROR with
    consolidated overlapping_pairs list."""
    ir = _ir(
        nodes=[_llm_node_with_prompt("write", "Use ${concept} to write.", prompt_cache=["concept"])],
        inputs={"concept": {"type": "string"}},
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    dups = [d for d in diagnostics if d.id == "cache.prompt-body-duplicates-cache"]
    assert len(dups) == 1
    diag = dups[0]
    assert diag.severity == Severity.ERROR
    assert diag.source == "validator"
    assert diag.node_id == "write"
    assert diag.context["category"] == CACHE_FAILURE_CATEGORY
    assert diag.context["overlapping_pairs"] == [{"chunk_name": "concept", "body_ref": "concept"}]
    assert diag.context["affected_workflow"] == "t.pflow.md"


def test_subpath_overlap_cached_parent_warns() -> None:
    """Cache ``[concept]`` + body ``${concept.title}`` → WARNING with direction='cache_contains_body'."""
    ir = _ir(
        nodes=[_llm_node_with_prompt("write", "Title: ${concept.title}.", prompt_cache=["concept"])],
        inputs={"concept": {"type": "string"}},
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    shadows = [d for d in diagnostics if d.id == "cache.prompt-body-shadows-cache"]
    assert len(shadows) == 1
    diag = shadows[0]
    assert diag.severity == Severity.WARNING
    assert diag.context["shadowing_pairs"] == [
        {"chunk_name": "concept", "body_ref": "concept.title", "direction": "cache_contains_body"}
    ]


def test_subpath_overlap_cached_child_warns() -> None:
    """Cache ``[concept.title]`` + body ``${concept}`` → WARNING with direction='body_contains_cache'."""
    ir = _ir(
        nodes=[_llm_node_with_prompt("write", "Concept: ${concept}.", prompt_cache=["concept.title"])],
        inputs={"concept": {"type": "string"}},
        cache={"items": [{"name": "concept.title", "var": "concept.title", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    shadows = [d for d in diagnostics if d.id == "cache.prompt-body-shadows-cache"]
    assert len(shadows) == 1
    pairs = shadows[0].context["shadowing_pairs"]
    assert pairs == [{"chunk_name": "concept.title", "body_ref": "concept", "direction": "body_contains_cache"}]


def test_no_overlap_silent() -> None:
    """Cache ``[concept]`` + body ``${other_input}`` → no overlap diagnostic."""
    ir = _ir(
        nodes=[_llm_node_with_prompt("write", "Use ${other}.", prompt_cache=["concept"])],
        inputs={"concept": {"type": "string"}, "other": {"type": "string"}},
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    overlap_ids = {"cache.prompt-body-duplicates-cache", "cache.prompt-body-shadows-cache"}
    assert not [d for d in diagnostics if d.id in overlap_ids]


def test_batch_scoped_body_ref_ignored() -> None:
    """``${item.concept}`` on a batch node → no overlap diagnostic (batch refs
    are filtered before path comparison)."""
    ir = _ir(
        nodes=[
            {
                "id": "batch-write",
                "type": "llm",
                "params": {
                    "prompt": "Per item: ${item.concept}.",
                    "model": "anthropic/claude-sonnet-4-5",
                },
                "prompt_cache": ["concept"],
                "batch": {"items": "${items}", "as": "item"},
            }
        ],
        inputs={"concept": {"type": "string"}, "items": {"type": "array"}},
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    overlap_ids = {"cache.prompt-body-duplicates-cache", "cache.prompt-body-shadows-cache"}
    assert not [d for d in diagnostics if d.id in overlap_ids]


def test_multiple_chunks_one_node_consolidates_to_single_diagnostic() -> None:
    """``prompt_cache: [a, b]`` + body has BOTH ``${a}`` and ``${b}`` → ONE
    ERROR diagnostic with overlapping_pairs listing BOTH pairs.

    Regression-pin for the ``Diagnostic.__hash__`` collapse problem: emitting
    two separate diagnostics with the same (severity, source, node_id, id)
    tuple would silently dedup into one and lose the second pair's detail.
    """
    ir = _ir(
        nodes=[
            _llm_node_with_prompt(
                "write",
                "Mix ${a} and ${b} together.",
                prompt_cache=["a", "b"],
            )
        ],
        inputs={"a": {"type": "string"}, "b": {"type": "string"}},
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
            ]
        },
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    dups = [d for d in diagnostics if d.id == "cache.prompt-body-duplicates-cache"]
    assert len(dups) == 1
    pairs = dups[0].context["overlapping_pairs"]
    pair_set = {(p["chunk_name"], p["body_ref"]) for p in pairs}
    assert pair_set == {("a", "a"), ("b", "b")}


def test_undeclared_chunk_suppresses_overlap() -> None:
    """``prompt_cache: [missing]`` (not in ## Cache items) → only the existing
    ``cache.undeclared-chunk`` ERROR fires; overlap check is suppressed because
    suppressing here keeps the actionable error from being buried."""
    ir = _ir(
        nodes=[
            _llm_node_with_prompt("write", "Use ${concept}.", prompt_cache=["missing"]),
        ],
        inputs={"concept": {"type": "string"}},
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    overlap_ids = {"cache.prompt-body-duplicates-cache", "cache.prompt-body-shadows-cache"}
    assert not [d for d in diagnostics if d.id in overlap_ids]


def test_overlap_combines_with_unused_chunk() -> None:
    """Overlap on chunk ``a`` + chunk ``b`` declared but unused → 1 ERROR + 1
    unused-WARNING; the two findings are orthogonal."""
    ir = _ir(
        nodes=[_llm_node_with_prompt("write", "Use ${a}.", prompt_cache=["a"])],
        inputs={"a": {"type": "string"}, "b": {"type": "string"}},
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
            ]
        },
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert len([d for d in diagnostics if d.id == "cache.prompt-body-duplicates-cache"]) == 1
    assert len([d for d in diagnostics if d.id == "cache.unused-chunk"]) == 1


def test_overlap_does_not_fire_when_order_mismatch_present() -> None:
    """Order-mismatch suppression precedence (V5): when prompt_cache order
    diverges from ## Cache, the overlap check still runs (all_resolved=True),
    so both diagnostics fire — agents fix order AND duplication in one pass."""
    ir = _ir(
        nodes=[
            _llm_node_with_prompt(
                "write",
                "${a} ${b}",
                prompt_cache=["b", "a"],  # wrong order
            )
        ],
        inputs={"a": {"type": "string"}, "b": {"type": "string"}},
        cache={
            "items": [
                {"name": "a", "var": "a", "prose_before": ""},
                {"name": "b", "var": "b", "prose_before": ""},
            ]
        },
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert [d for d in diagnostics if d.id == "cache.order-mismatch"]
    assert [d for d in diagnostics if d.id == "cache.prompt-body-duplicates-cache"]


def test_three_way_coalesce_each_operand_checked() -> None:
    """``${a ?? b ?? c}`` with cache ``[a, c]`` → ERROR with overlapping pairs
    for each operand that resolves to a cached chunk."""
    ir = _ir(
        nodes=[
            _llm_node_with_prompt(
                "write",
                "Pick: ${concept ?? primary_brief ?? fallback_brief}.",
                prompt_cache=["concept", "fallback_brief"],
            )
        ],
        inputs={
            "concept": {"type": "string"},
            "primary_brief": {"type": "string"},
            "fallback_brief": {"type": "string"},
        },
        cache={
            "items": [
                {"name": "concept", "var": "concept", "prose_before": ""},
                {"name": "fallback_brief", "var": "fallback_brief", "prose_before": ""},
            ]
        },
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    dups = [d for d in diagnostics if d.id == "cache.prompt-body-duplicates-cache"]
    assert len(dups) == 1
    pairs = dups[0].context["overlapping_pairs"]
    pair_set = {(p["chunk_name"], p["body_ref"]) for p in pairs}
    assert pair_set == {("concept", "concept"), ("fallback_brief", "fallback_brief")}


def test_external_prompt_file_resolved_at_save_then_overlap_detected(tmp_path) -> None:
    """Pattern 2 integration test: write a real prompt file with ``${concept}``,
    point ``params.prompt`` at the file, drive through save_workflow_with_options
    → ERROR fires because the save path now resolves file references before
    validation.

    Regression-pin for the save-path file-resolution wiring (the ACTUAL gap
    that motivated this work — CLI / --validate-only / MCP execute paths
    already resolve at the IR-load boundary).
    """
    from pflow.core.exceptions import WorkflowValidationError
    from pflow.core.workflow.save_service import save_workflow_with_options

    prompt_file = tmp_path / "creative-direction.prompt.md"
    prompt_file.write_text("Use the concept ${concept} to draft a song.")

    workflow_file = tmp_path / "song-creator.pflow.md"
    workflow_file.write_text(
        "# Song Creator\n\n"
        "Demonstrates external prompt + cache overlap.\n\n"
        "## Inputs\n\n### concept\n\nThe concept.\n\n- type: string\n- required: true\n\n"
        "## Cache\n\n"
        "```cache\nThe concept:\n${concept}\n```\n\n"
        "## Steps\n\n"
        "### draft\n\nDraft via external prompt with overlap.\n\n"
        "- type: llm\n"
        "- prompt: ./creative-direction.prompt.md\n"
        "- prompt_cache: [concept]\n"
        "- model: anthropic/claude-sonnet-4-5\n"
    )

    with pytest.raises(WorkflowValidationError) as excinfo:
        save_workflow_with_options(
            "song-creator-overlap-test",
            workflow_file.read_text(),
            source_path=workflow_file,
        )
    diagnostic_ids = {d.id for d in (excinfo.value.validation_errors or [])}
    assert "cache.prompt-body-duplicates-cache" in diagnostic_ids, (
        f"Expected save-path file-resolution to expose overlap; got ids={diagnostic_ids}"
    )


@pytest.mark.e2e
def test_cli_save_subprocess_with_overlap_exits_nonzero(tmp_path, uv_exe, prepared_subprocess_env) -> None:
    """Pattern 4 subprocess regression test for the save-path file-resolution wiring.

    Drives the real ``pflow save`` CLI command against a workflow that uses an
    EXTERNAL prompt file containing ``${concept}`` plus a node-level
    ``prompt_cache: [concept]``. Without the save-path file resolution wired in
    (``save_service._resolve_for_validation``), the validator sees
    ``params.prompt = './...md'`` and the overlap check finds nothing — save
    succeeds and the bug ships. With the wiring, save exits non-zero and stderr
    carries the catalog-id ``cache.prompt-body-duplicates-cache``.

    The Pattern 2 test above (``test_external_prompt_file_resolved_at_save_...``)
    exercises the API but bypasses the CLI surface; this test is the regression
    pin for that surface specifically.
    """
    import subprocess

    prompt_file = tmp_path / "creative-direction.prompt.md"
    prompt_file.write_text("Use the concept ${concept} to draft a song.")

    workflow_file = tmp_path / "song-creator.pflow.md"
    workflow_file.write_text(
        "# Song Creator\n\n"
        "Demonstrates external prompt + cache overlap.\n\n"
        "## Inputs\n\n### concept\n\nThe concept.\n\n- type: string\n- required: true\n\n"
        "## Cache\n\n"
        "```cache\nThe concept:\n${concept}\n```\n\n"
        "## Steps\n\n"
        "### draft\n\nDraft via external prompt with overlap.\n\n"
        "- type: llm\n"
        "- prompt: ./creative-direction.prompt.md\n"
        "- prompt_cache: [concept]\n"
        "- model: anthropic/claude-sonnet-4-5\n"
    )

    completed = subprocess.run(  # noqa: S603 — fixture-controlled args, mirrors the established subprocess CLI test pattern
        [
            uv_exe,
            "run",
            "pflow",
            "save",
            str(workflow_file),
            "--name",
            "song-creator-cli-overlap-test",
            "--force",
        ],
        capture_output=True,
        text=True,
        env=prepared_subprocess_env,
        timeout=60,
    )
    assert completed.returncode != 0, (
        f"Expected non-zero exit when save detects prompt-body / cache overlap. "
        f"stdout: {completed.stdout!r}\nstderr: {completed.stderr!r}"
    )
    combined = completed.stdout + completed.stderr
    assert "cache.prompt-body-duplicates-cache" in combined, (
        f"Expected the catalog id 'cache.prompt-body-duplicates-cache' in CLI output; got:\n"
        f"stdout: {completed.stdout!r}\nstderr: {completed.stderr!r}"
    )


def test_byte_identical_to_make_diagnostic_output() -> None:
    """The validator's emission for the new IDs MUST match what
    ``make_diagnostic`` would produce on the catalog. Severity, source,
    category, and the path follow from the catalog spec — drift would be a
    silent regression on agent-facing prose.

    Single test; both IDs covered via a parametrized loop inside.
    """
    from pflow.core.cache_analysis.warning_catalog import CACHE_WARNING_CATALOG

    overlap_ids = ("cache.prompt-body-duplicates-cache", "cache.prompt-body-shadows-cache")
    for warning_id in overlap_ids:
        spec = CACHE_WARNING_CATALOG[warning_id]
        # Drive a producer that emits the right kind of overlap.
        if warning_id == "cache.prompt-body-duplicates-cache":
            ir = _ir(
                nodes=[_llm_node_with_prompt("n", "Use ${x}.", prompt_cache=["x"])],
                inputs={"x": {"type": "string"}},
                cache={"items": [{"name": "x", "var": "x", "prose_before": ""}]},
            )
        else:
            ir = _ir(
                nodes=[_llm_node_with_prompt("n", "Field: ${x.field}.", prompt_cache=["x"])],
                inputs={"x": {"type": "string"}},
                cache={"items": [{"name": "x", "var": "x", "prose_before": ""}]},
            )
        diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
        diag = next(d for d in diagnostics if d.id == warning_id)

        assert diag.severity == spec.severity, warning_id
        assert diag.source == spec.source, warning_id
        assert diag.context["category"] == spec.category, warning_id
        # Path uses the catalog template format
        assert diag.context["path"] == spec.path_template.format(node_id="n"), warning_id
        # Required keys present in context
        required_keys = {k for k, _ in spec.required_context_keys if k != "node_id"}
        assert required_keys <= set(diag.context.keys()), (warning_id, diag.context.keys(), required_keys)


def test_overlap_does_not_fire_when_prompt_empty() -> None:
    """No prompt body → nothing to overlap → no diagnostic."""
    ir = _ir(
        nodes=[
            {
                "id": "n",
                "type": "llm",
                "params": {"prompt": "", "model": "anthropic/claude-sonnet-4-5"},
                "prompt_cache": ["concept"],
            }
        ],
        inputs={"concept": {"type": "string"}},
        cache={"items": [{"name": "concept", "var": "concept", "prose_before": ""}]},
    )
    diagnostics = validate_data_flow(ir, workflow_path="t.pflow.md")
    overlap_ids = {"cache.prompt-body-duplicates-cache", "cache.prompt-body-shadows-cache"}
    assert not [d for d in diagnostics if d.id in overlap_ids]


# ------------------------------------------------------------------------------
# Task 159 Stage 2 follow-up — llm.thinking-temperature-mismatch
#
# Anthropic API requires temperature=1.0 whenever extended thinking is enabled.
# pflow translates ``reasoning_effort: low/medium/high/...`` to
# ``thinking: {"type": "enabled", ...}`` for Anthropic models in
# ``llm_client._translate_reasoning_for_litellm``. Catching the offending
# composition at validate-time spares the agent the runtime BadRequestError.
#
# Empirically verified across Opus 4.1/4.5/4.7, Sonnet 4.5/4.6, Haiku 4.5
# (uniform behavior — Anthropic treats this as a single API rule across the
# extended-thinking model family). See task 159 Stage 2 follow-up handoff.
# ------------------------------------------------------------------------------


def _llm_node_with_thinking(node_id: str, **params) -> dict:
    """Helper: LLM node with custom params (for thinking+temp tests)."""
    full_params = {"prompt": "do thing"}
    full_params.update(params)
    return {"id": node_id, "type": "llm", "params": full_params}


def test_thinking_temperature_mismatch_fires_on_anthropic_low_effort_low_temp() -> None:
    """The canonical positive case: Anthropic model + reasoning_effort: low +
    temperature: 0.3 → ERROR diagnostic with all required context populated."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "score-choruses",
                model="anthropic/claude-haiku-4-5",
                reasoning_effort="low",
                temperature=0.3,
            )
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    matched = [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]
    assert len(matched) == 1
    diag = matched[0]
    assert diag.severity == Severity.ERROR
    assert diag.source == "validator"
    assert diag.node_id == "score-choruses"
    assert diag.title == "LLM Configuration"
    assert diag.see_also == ["llm"]
    # Spec-locked message format.
    assert diag.message == (
        "Node 'score-choruses': temperature 0.3 conflicts with "
        "reasoning_effort 'low' on model anthropic/claude-haiku-4-5 — "
        "Anthropic requires temperature=1.0 when extended thinking is enabled."
    )
    # Both fix paths surfaced.
    assert diag.suggestions is not None
    assert any("temperature: 1.0" in s for s in diag.suggestions)
    assert any("reasoning_effort: none" in s for s in diag.suggestions)
    # Structured context preserves typed values.
    assert diag.context["model"] == "anthropic/claude-haiku-4-5"
    assert diag.context["reasoning_effort"] == "low"
    assert diag.context["temperature"] == 0.3
    assert diag.context["affected_workflow"] == "t.pflow.md"
    assert diag.context["path"] == "nodes[id=score-choruses].params.temperature"


@pytest.mark.parametrize(
    "effort",
    ["minimal", "low", "medium", "high", "xhigh"],
)
def test_thinking_temperature_mismatch_fires_for_every_thinking_effort(effort: str) -> None:
    """Every reasoning_effort that pflow translates to ``thinking: enabled``
    (per ``EFFORT_RATIOS`` in ``llm_reasoning_map``) trips the validator when
    paired with non-1.0 temperature on Anthropic."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="anthropic/claude-sonnet-4-5",
                reasoning_effort=effort,
                temperature=0.5,
            )
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert any(d.id == "llm.thinking-temperature-mismatch" for d in diags)


def test_thinking_temperature_mismatch_silent_when_reasoning_effort_is_none() -> None:
    """``reasoning_effort: none`` disables thinking → no conflict regardless of
    temperature."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="anthropic/claude-haiku-4-5",
                reasoning_effort="none",
                temperature=0.3,
            )
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_silent_when_temperature_is_one() -> None:
    """Explicit ``temperature: 1.0`` matches Anthropic's requirement → silent.
    Tested with both int and float to guard against subtle equality bugs."""
    for temp in (1, 1.0):
        ir = _ir(
            nodes=[
                _llm_node_with_thinking(
                    "n",
                    model="anthropic/claude-haiku-4-5",
                    reasoning_effort="low",
                    temperature=temp,
                )
            ],
        )
        diags = validate_data_flow(ir, workflow_path="t.pflow.md")
        assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_silent_when_temperature_omitted() -> None:
    """No declared ``temperature`` → LLMNode default is 1.0 → no conflict.

    This is the agent's natural fallthrough when they only set reasoning_effort
    and trust the default. The validator MUST stay silent here; firing would
    be agent-noise on the common case.
    """
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="anthropic/claude-haiku-4-5",
                reasoning_effort="low",
            )
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


@pytest.mark.parametrize(
    "model",
    [
        "gemini/gemini-2.5-flash",
        "gemini/gemini-3-flash-preview",
        "openai/gpt-5",
        "openai/o3-mini",
    ],
)
def test_thinking_temperature_mismatch_silent_on_non_anthropic(model: str) -> None:
    """The Anthropic temp=1 rule does not apply to Gemini/OpenAI; their
    reasoning APIs follow different rules (Gemini accepts non-1 temperature
    with thinking_budget; OpenAI's o-series ignores temperature entirely)."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model=model,
                reasoning_effort="low",
                temperature=0.3,
            )
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_silent_when_model_is_templated() -> None:
    """Templated ``model: ${m}`` → defer to runtime (the validator can't
    resolve the provider statically)."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="${m}",
                reasoning_effort="low",
                temperature=0.3,
            )
        ],
        inputs={"m": {"type": "string"}},
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_silent_when_effort_is_templated() -> None:
    """Templated ``reasoning_effort: ${e}`` → defer to runtime."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="anthropic/claude-haiku-4-5",
                reasoning_effort="${e}",
                temperature=0.3,
            )
        ],
        inputs={"e": {"type": "string"}},
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_silent_when_temperature_is_templated() -> None:
    """Templated ``temperature: ${t}`` (string literal) → defer to runtime."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="anthropic/claude-haiku-4-5",
                reasoning_effort="low",
                temperature="${t}",
            )
        ],
        inputs={"t": {"type": "number"}},
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_silent_on_non_llm_node() -> None:
    """Shell node with reasoning_effort/temperature in params would be
    nonsensical, but the validator should not trip — only LLM nodes are
    in scope."""
    ir = _ir(
        nodes=[
            {
                "id": "n",
                "type": "shell",
                "params": {
                    "command": "echo hi",
                    "reasoning_effort": "low",
                    "temperature": 0.3,
                    "model": "anthropic/claude-haiku-4-5",
                },
            }
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert not [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]


def test_thinking_temperature_mismatch_works_with_bare_anthropic_prefix() -> None:
    """Bare ``claude-...`` (no ``anthropic/`` prefix) is detected as Anthropic
    via ``detect_provider``'s bare-prefix path. The check must work on it too.
    """
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                "n",
                model="claude-sonnet-4-5",
                reasoning_effort="low",
                temperature=0.3,
            )
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    assert any(d.id == "llm.thinking-temperature-mismatch" for d in diags)


def test_thinking_temperature_mismatch_emits_one_diagnostic_per_node() -> None:
    """Multi-node case: each offending node gets its own ERROR (so the agent
    sees all 11 violations at once when reverting lyrics-generator
    workarounds, not just the first)."""
    ir = _ir(
        nodes=[
            _llm_node_with_thinking(
                f"n{i}",
                model="anthropic/claude-haiku-4-5",
                reasoning_effort="low",
                temperature=0.5,
            )
            for i in range(3)
        ],
    )
    diags = validate_data_flow(ir, workflow_path="t.pflow.md")
    matched = [d for d in diags if d.id == "llm.thinking-temperature-mismatch"]
    assert len(matched) == 3
    assert {d.node_id for d in matched} == {"n0", "n1", "n2"}


@pytest.mark.e2e
def test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero(
    tmp_path, uv_exe, prepared_subprocess_env
) -> None:
    """Pattern 4 subprocess regression: drive the real ``pflow save`` CLI
    against a workflow with the offending composition. Without the validator
    wiring (data_flow.py → save_service → CLI), the workflow saves and the
    runtime crash is the agent's first signal. With the wiring, save exits
    non-zero and stderr carries the catalog ID.
    """
    import subprocess

    workflow_file = tmp_path / "thinking-temp-conflict.pflow.md"
    workflow_file.write_text(
        "# Thinking-temp test\n\n"
        "Anthropic model with reasoning_effort + non-1 temperature.\n\n"
        "## Inputs\n\n### question\n\nThe question.\n\n- type: string\n- required: true\n\n"
        "## Steps\n\n"
        "### answer\n\nAnswer with thinking on a low temperature.\n\n"
        "- type: llm\n"
        "- model: anthropic/claude-haiku-4-5\n"
        "- reasoning_effort: low\n"
        "- temperature: 0.3\n"
        "- prompt: ${question}\n"
    )

    completed = subprocess.run(  # noqa: S603 — fixture-controlled args, mirrors the established subprocess CLI test pattern
        [
            uv_exe,
            "run",
            "pflow",
            "save",
            str(workflow_file),
            "--name",
            "thinking-temp-conflict-test",
            "--force",
        ],
        capture_output=True,
        text=True,
        env=prepared_subprocess_env,
        timeout=60,
    )
    assert completed.returncode != 0, (
        f"Expected non-zero exit when save detects thinking+temperature conflict. "
        f"stdout: {completed.stdout!r}\nstderr: {completed.stderr!r}"
    )
    combined = completed.stdout + completed.stderr
    assert "llm.thinking-temperature-mismatch" in combined, (
        f"Expected the catalog id 'llm.thinking-temperature-mismatch' in CLI output; got:\n"
        f"stdout: {completed.stdout!r}\nstderr: {completed.stderr!r}"
    )
