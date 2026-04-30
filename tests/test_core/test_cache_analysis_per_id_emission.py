"""Production-shaped emission tests for cache analyzer warning IDs.

Each test drives ``analyze(...)`` end-to-end rather than constructing
Diagnostics directly. Dotted-path references are intentional: prior cache
analysis tests that used only bare inputs missed production bugs around
full-path chunk names.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_analysis.analyze import analyze
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult


def _word_count(_model: str | None, text: str | None, **_kwargs: Any) -> tuple[int, str]:
    return (len((text or "").split()), "heuristic")


@pytest.fixture(autouse=True)
def deterministic_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "estimate_tokens", _word_count)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: None)


def test_batch_prewarm_recommended_fires_only_when_prewarm_absent() -> None:
    prefix = "stable " * 100
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": str(i)} for i in range(34)], "as": "item"},
                "params": {"prompt": prefix + "${item.text}"},
            }
        ]
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.batch-prewarm-recommended")
    assert diag.context is not None
    assert diag.context["batch_size"] == 34
    assert diag.context["prefix_tokens_estimated"] == 100
    assert diag.context["savings_pct"] == 89

    workflow_ir["nodes"][0]["prewarm"] = False
    opted_out = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.batch-prewarm-recommended" not in {d.id for d in opted_out.warnings}


def test_dynamic_before_static_uses_full_path_cache_names() -> None:
    stable_suffix = "rubric " * 50
    workflow_ir = {
        "cache": {
            "items": [
                {
                    "name": "creative-direction.response",
                    "var": "creative-direction.response",
                    "prose_before": "Direction:\n",
                }
            ]
        },
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["creative-direction.response"],
                "params": {
                    "prompt": (
                        f"Dynamic: ${{user_input}}\nDirection: ${{creative-direction.response}}\n{stable_suffix}"
                    )
                },
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.dynamic-before-static")
    assert diag.context is not None
    assert diag.context["dynamic_ref"] == "user_input"
    assert diag.context["cacheable_tokens"] >= 50


def test_dynamic_before_static_treats_coalesce_as_static_when_any_operand_is_declared() -> None:
    workflow_ir = {
        "cache": {
            "items": [
                {"name": "creative-direction.response", "var": "creative-direction.response", "prose_before": "D:\n"}
            ]
        },
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["creative-direction.response"],
                "params": {"prompt": "${creative-direction.response ?? fallback}\n" + ("stable " * 60)},
            }
        ],
    }
    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.dynamic-before-static" not in {d.id for d in result.warnings}


def test_padding_advisory_uses_dotted_path_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    workflow_ir = {
        "cache": {
            "items": [
                {"name": "concept", "var": "concept", "prose_before": "concept " * 20},
                {
                    "name": "concept-brief.response",
                    "var": "concept-brief.response",
                    "prose_before": "brief " * 20,
                },
                {"name": "scorer.response", "var": "scorer.response", "prose_before": "score " * 20},
            ]
        },
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "priced/model",
                "prompt_cache": ["scorer.response"],
                "params": {"prompt": "review ${scorer.response}"},
            },
            {
                "id": "rewrite",
                "type": "llm",
                "model": "priced/model",
                "prompt_cache": ["concept-brief.response", "scorer.response"],
                "params": {"prompt": "rewrite ${concept-brief.response}"},
            },
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    advisories = [d for d in result.warnings if d.id == "cache.padding-advisory"]
    assert {d.node_id for d in advisories} == {"review", "rewrite"}
    review = next(d for d in advisories if d.node_id == "review")
    assert review.context is not None
    assert review.context["current_subset"] == ["scorer.response"]
    assert review.context["suggested_subset"] == ["concept", "concept-brief.response", "scorer.response"]


def test_shared_context_undeclared_populates_suggested_block_with_dotted_path() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Use ${concept-brief.response} and ${concept}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Review ${concept-brief.response} and ${concept}."},
            },
        ]
    }

    result = analyze(workflow_ir, workflow_path="song.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.shared-context-undeclared")
    assert diag.context is not None
    assert diag.context["shared_chunks"] == ["concept", "concept-brief.response"]
    assert len(result.suggested_blocks) == 1
    block = result.suggested_blocks[0]
    assert [chunk.name for chunk in block.chunks] == ["concept", "concept-brief.response"]
    assert block.chunks[1].var == "${concept-brief.response}"
    assert block.per_node_assignments == {
        "draft": ["concept", "concept-brief.response"],
        "review": ["concept", "concept-brief.response"],
    }


def test_cross_workflow_prose_mismatch_fires_for_dotted_path(monkeypatch: pytest.MonkeyPatch) -> None:
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "cache": {
            "items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "Parent prose\n"}]
        },
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"direction": "${creative.direction}"}},
            }
        ],
    }
    child_ir = {
        "cache": {
            "items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "Child prose\n"}]
        },
        "nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}],
    }

    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.cross-workflow-prose-mismatch")
    assert diag.context is not None
    assert diag.context["chunk_name"] == "creative.direction"
    assert diag.context["parent_prose"] == "Parent prose\n"
    assert diag.context["child_prose"] == "Child prose\n"


def test_cross_workflow_value_flow_uses_parent_node_id_for_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    # Parent has an LLM node that references ${creative.direction} AND a child
    # workflow call that passes the same value through. Child has its own LLM
    # node referencing the input. Bug E fix counts these accurately:
    # parent_count=1 + child_count=1 → node_count=2.
    parent_ir = {
        "nodes": [
            {
                "id": "use-direction",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${creative.direction}"},
            },
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"direction": "${creative.direction}"}},
            },
        ]
    }
    child_ir = {
        "nodes": [
            {
                "id": "use-input",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${direction}"},
            }
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.shared-context-undeclared")
    assert diag.node_id == "child-call"  # CRIT-5 dedup boundary
    assert diag.context is not None
    assert diag.context["shared_chunks"] == ["direction"]
    assert diag.context["affected_workflow"] == "parent.pflow.md"
    # Bug E fix — node_count is the COUNT of LLM nodes referencing the value
    # (parent's ``use-direction`` + child's ``use-input``), not the hardcoded 2.
    assert diag.context["node_count"] == 2


def test_cross_workflow_value_flow_suppresses_when_no_llm_consumers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug E regression — when neither side has LLM nodes referencing the
    value, declaring it in ## Cache wouldn't help (no consumers to share
    with). The warning is suppressed rather than rendering the misleading
    "2 LLM nodes share static context..." message that the hardcoded count
    used to produce.

    Mutation test: revert ``node_count = parent_count + child_count`` to the
    hardcoded ``2``; this test fails (warning fires for shell-only workflows).
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"direction": "${creative.direction}"}},
            }
        ]
    }
    child_ir = {"nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}]}
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )
    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    # No cache.shared-context-undeclared warning fires for the cross-workflow
    # path when neither side has LLM consumers.
    assert all(not (d.id == "cache.shared-context-undeclared" and d.node_id == "child-call") for d in result.warnings)


# ---------------------------------------------------------------------------
# #362 — cache.cross-workflow-rename-detected evidence-basis suppression
#
# Mutation test contract for these: comment out either suppression branch in
# ``analyze.py::_build_cross_workflow_findings`` and the matching test fails
# with a clear assertion. The two branches together encode the principle
# "predictive warnings about state comparisons fire only when the state to
# compare against actually exists" (no batch-iteration substitution; at
# least one side has ``## Cache``).
# ---------------------------------------------------------------------------


def test_rename_warning_suppressed_for_batch_alias_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """``${item}`` is the iteration variable for a batch sub-workflow call;
    ``parent passes 'item' as input named 'source'`` is iteration-variable
    substitution, not a logical rename. The detector must suppress.

    Mutation test: comment out ``if edge.is_batch_alias_root: continue`` in
    analyze.py and this test fails — the rename warning fires on every
    batch-sub-workflow boundary in the lyrics-generator workflow (~6 false
    positives per parent run).
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    # Parent has a batch sub-workflow call; even with ## Cache declared (so
    # Suppression 2 doesn't fire), the batch-alias suppression must still
    # block the warning.
    parent_ir = {
        "cache": {"items": [{"name": "x", "var": "x", "prose_before": "x:\n"}]},
        "nodes": [
            {
                "id": "fetch",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"source": "${item}"}},
                "batch": {"items": "${urls}", "parallel": True},
            }
        ],
    }
    child_ir = {"inputs": {"source": {"type": "string"}}, "nodes": []}
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    rename_diags = [d for d in result.warnings if d.id == "cache.cross-workflow-rename-detected"]
    assert rename_diags == [], (
        f"Batch alias edge produced rename warning(s): {rename_diags}. "
        "Suppression 1 (batch_alias_root) should block this; check is_batch_alias_root or analyze.py emission gate."
    )


def test_rename_warning_suppressed_for_dotted_batch_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """``${item.field}`` is also an iteration-variable reference (root segment
    is the batch alias). Same suppression applies."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "cache": {"items": [{"name": "x", "var": "x", "prose_before": "x:\n"}]},
        "nodes": [
            {
                "id": "process",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"target": "${item.url}"}},
                "batch": {"items": "${records}", "parallel": True},
            }
        ],
    }
    child_ir = {"inputs": {"target": {"type": "string"}}, "nodes": []}
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    rename_diags = [d for d in result.warnings if d.id == "cache.cross-workflow-rename-detected"]
    assert rename_diags == []


def test_rename_warning_suppressed_when_neither_side_has_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real rename (different stable identifiers across boundary) should NOT
    fire when neither parent nor child declares ``## Cache``. The warning's
    premise — diverging prose labels would break byte-level cache match — is
    hypothetical without ``## Cache`` declarations to compare against.

    Mutation test: comment out the
    ``if not parent_has_cache and not child_has_cache: continue`` branch and
    this test fails — the warning fires on every cross-workflow rename in
    greenfield workflows (~17 false positives on lyrics-generator).
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {
                    "workflow": "./child.pflow.md",
                    "inputs": {"creative_brief": "${concept_brief}"},
                },
            }
        ]
    }
    child_ir = {"inputs": {"creative_brief": {"type": "string"}}, "nodes": []}
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    rename_diags = [d for d in result.warnings if d.id == "cache.cross-workflow-rename-detected"]
    assert rename_diags == [], (
        f"Rename without ## Cache on either side should be suppressed; got: {rename_diags}. "
        "The warning's premise is hypothetical without state to compare against."
    )


def test_rename_warning_FIRES_when_parent_has_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same rename, but parent declares ``## Cache`` — now the warning IS
    actionable (agent can align prose labels) and must fire.

    Locks the positive case so the suppression doesn't over-block.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "cache": {"items": [{"name": "concept_brief", "var": "concept_brief", "prose_before": "Brief:\n"}]},
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {
                    "workflow": "./child.pflow.md",
                    "inputs": {"creative_brief": "${concept_brief}"},
                },
            }
        ],
    }
    child_ir = {"inputs": {"creative_brief": {"type": "string"}}, "nodes": []}
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    rename_diags = [d for d in result.warnings if d.id == "cache.cross-workflow-rename-detected"]
    assert len(rename_diags) == 1, (
        f"Expected exactly 1 rename warning when parent has ## Cache; got {len(rename_diags)}. "
        "Over-suppression — the gate should NOT block when state exists to compare against."
    )
    assert rename_diags[0].context is not None
    assert rename_diags[0].context["parent_value_expr"] == "concept_brief"
    assert rename_diags[0].context["child_input_name"] == "creative_brief"


def test_rename_warning_FIRES_when_child_has_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same rename, parent has no ``## Cache`` but child does — warning still
    fires because the child's prose label could end up diverging from a
    future parent declaration."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {
                    "workflow": "./child.pflow.md",
                    "inputs": {"creative_brief": "${concept_brief}"},
                },
            }
        ]
    }
    child_ir = {
        "cache": {"items": [{"name": "creative_brief", "var": "creative_brief", "prose_before": "Brief:\n"}]},
        "inputs": {"creative_brief": {"type": "string"}},
        "nodes": [],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    rename_diags = [d for d in result.warnings if d.id == "cache.cross-workflow-rename-detected"]
    assert len(rename_diags) == 1


def _write_trace(tmp_path: Path, events: list[dict[str, Any]], *, format_version: str = "2.1.0") -> Path:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": format_version,
            "workflow_path": "parent.pflow.md",
            "nodes": events,
        }),
        encoding="utf-8",
    )
    return trace_path


def test_discrepancy_fires_for_ttl_expiry_with_implicit_default(tmp_path: Path) -> None:
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 301,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )

    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.context is not None
    assert diag.context["root_cause"] == "ttl_expiry"
    assert diag.context["affected_invocations"] == 1


def test_discrepancy_fires_for_chunk_skipped_with_dotted_path(tmp_path: Path) -> None:
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 10,
                    "cache_chunks_skipped": ["creative.direction"],
                },
            }
        ],
    )

    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.context is not None
    assert diag.context["root_cause"] == "chunk_skipped"
    assert diag.context["skipped_chunk"] == "creative.direction"


def test_discrepancy_fires_for_key_mismatch_when_prediction_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(
        analyze_module,
        "_predict_cache_keys",
        lambda *_args, **_kwargs: ({"gen": "predicted-key"}, []),
    )
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_key": "actual-key",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 10,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )

    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.context is not None
    assert diag.context["root_cause"] == "key_mismatch"
    assert diag.context["predicted_cache_key"] == "predicted-key"
    assert diag.context["actual_cache_key"] == "actual-key"


def test_discrepancy_silent_when_trace_is_2_0(tmp_path: Path) -> None:
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 301,
                    "cache_chunks_skipped": [],
                },
            }
        ],
        format_version="2.0.0",
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    assert "cache.discrepancy" not in {d.id for d in result.warnings}


def test_discrepancy_recurses_into_sub_workflow_events(tmp_path: Path) -> None:
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "parent",
                "sub_workflow_events": [
                    {
                        "node_id": "child-gen",
                        "llm_call": {
                            "model": "anthropic/claude-sonnet-4-5",
                            "cache_creation_input_tokens": 100,
                            "cache_read_input_tokens": 0,
                            "cache_age_sec": 301,
                            "cache_chunks_skipped": [],
                        },
                    }
                ],
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.node_id == "child-gen"


# ---------------------------------------------------------------------------
# Discrepancy edge cases — production-shaped boundaries (review-fidelity 6)
# ---------------------------------------------------------------------------


def test_discrepancy_silent_when_actual_matches_prediction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When predicted_key == actual_key (cache healthy), no discrepancy fires.

    Mutation-test guard for the in-agreement gate at ``analyze.py:1143``.
    Flipping ``< 5`` to ``> 95`` would emit cache.discrepancy on every
    healthy run.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(
        analyze_module,
        "_predict_cache_keys",
        lambda *_args, **_kwargs: ({"gen": "shared-key"}, []),
    )
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_key": "shared-key",
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 1000,
                    "cache_age_sec": 30,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )

    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    assert "cache.discrepancy" not in {d.id for d in result.warnings}


def test_discrepancy_skips_when_cache_disengaged_and_no_chunks_skipped(tmp_path: Path) -> None:
    """When cache_creation==0 AND cache_read==0 AND no chunks_skipped, the
    cache wasn't engaged at all; no discrepancy possible.

    Mutation-test guard: removing this gate would emit phantom unknowns
    on every non-cache trace event.
    """
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 10,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    assert "cache.discrepancy" not in {d.id for d in result.warnings}


def test_discrepancy_FIRES_when_cache_disengaged_BUT_chunks_skipped(tmp_path: Path) -> None:
    """A node that DECLARED prompt_cache: but had a chunk skipped at runtime
    (branch absent) can have BOTH zero create/read AND a populated
    cache_chunks_skipped list — exactly what chunk_skipped attribution was
    designed for.

    Mutation-test guard: reverting the ``and not chunks_skipped`` term in
    the disengaged-cache gate makes this test fail (chunk_skipped goes
    silent).
    """
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 10,
                    "cache_chunks_skipped": ["concept-brief.response"],
                },
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.context is not None
    assert diag.context["root_cause"] == "chunk_skipped"
    assert diag.context["skipped_chunk"] == "concept-brief.response"


def test_discrepancy_skips_predicted_key_match_when_compile_fails_no_inputs(tmp_path: Path) -> None:
    """D11-A path: when params={} and the workflow declares inputs, the
    analyzer suppresses predicted-key matching (would produce false
    key_mismatch on every input-referencing node) and emits a notes entry.
    Observable signals (here: TTL expiry) still attribute correctly.
    """
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_key": "actual-from-trace",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 301,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [],
    }

    # Use a non-None memo_cache so we exercise the params-empty branch
    # (memo_cache=None short-circuits earlier with a different note).
    class _Stub:
        pass

    result = analyze(
        workflow_ir,
        workflow_path="parent.pflow.md",
        trace_path=trace_path,
        memo_cache=_Stub(),
    )
    # TTL-expiry attribution still fires (observable-only path).
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.context is not None
    assert diag.context["root_cause"] == "ttl_expiry"
    assert diag.context["predicted_cache_key"] is None
    # The notes entry surfacing why predicted-key matching was skipped.
    assert any("predicted-key matching skipped" in n and "weren't supplied" in n for n in result.notes)


def test_discrepancy_emits_silent_skip_note_when_no_predicted_key_and_no_signal(
    tmp_path: Path,
) -> None:
    """When predicted_keys is empty (D11-A) AND a trace event has cache
    engaged but no observable signal (no chunks_skipped, age <= TTL), the
    analyzer silently can't attribute. The new silent-skip note surfaces
    the count so agents see the coverage gap.

    Mutation-test guard: removing the ``silent_skip_no_predicted_key += 1``
    or the trailing notes append makes this test fail.
    """
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "downstream-node",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 50,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )
    # Workflow declares an input but the analyzer sees params={} → D11-A
    # path → predicted_keys empty → silent skip on the trace event.
    workflow_ir = {"inputs": {"topic": {"type": "string"}}, "nodes": []}

    class _Stub:
        pass

    result = analyze(
        workflow_ir,
        workflow_path="parent.pflow.md",
        trace_path=trace_path,
        memo_cache=_Stub(),
    )
    # No discrepancy emitted (no observable signal).
    assert "cache.discrepancy" not in {d.id for d in result.warnings}
    # But the silent-skip note IS emitted, with the right count.
    assert any("skipped attribution for 1 trace event(s)" in n and "no predicted cache_key" in n for n in result.notes)


def test_discrepancy_emits_no_silent_skip_note_for_non_cache_workflow(tmp_path: Path) -> None:
    """For workflows with no cache opportunities (all events have
    cache_create=cache_read=0 and no chunks_skipped), the disengaged-cache
    gate skips them BEFORE the silent-skip counter — so no spurious note.

    This is the regression that the BFS-downstream-count-by-plan-walking
    approach would have produced. Counting silent skips at the actual
    decision point (event walking) avoids it.
    """
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "non-cache-llm",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 50,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    assert not any("skipped attribution for" in n for n in result.notes)


def test_discrepancy_predicted_label_distinguishes_match_mismatch_and_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug F regression — ``predicted_label`` distinguishes the three planner
    prediction states. The prior implementation rendered all "predicted_key
    not None" cases as "predicted hit_ratio 100%" — falsely implying a
    measured hit ratio when actually it's a binary "did the planner produce
    a cache_key" signal that may or may not match the trace's actual key.

    This test exercises three discrepancy emissions and verifies each gets
    the correct label in its rendered message.

    Mutation test: revert ``_compute_predicted_label`` to always return
    ``"hit"``; the mismatched-key + miss assertions fail.
    """
    from pflow.core.cache_analysis.analyze import _compute_predicted_label

    # Helper logic — direct unit assertions on the predicate function.
    assert _compute_predicted_label("abc", "abc") == "hit"
    assert _compute_predicted_label("abc", "def") == "hit (bytes diverged at runtime)"
    assert _compute_predicted_label(None, "abc") == "miss"
    assert _compute_predicted_label(None, None) == "miss"

    # End-to-end check: the rendered message uses the label, not "hit_ratio N%".
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(
        analyze_module,
        "_predict_cache_keys",
        lambda *_args, **_kwargs: ({"gen": "predicted-key"}, []),
    )
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_key": "actual-key",  # ≠ predicted-key
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 10,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    # Rendered message uses the label — NOT "hit_ratio 100%".
    assert "predicted hit (bytes diverged at runtime)" in diag.message
    assert "hit_ratio" not in diag.message
    # JSON consumers still see the binary predicted_pct.
    assert diag.context is not None
    assert diag.context["predicted_pct"] == 100
    assert diag.context["predicted_label"] == "hit (bytes diverged at runtime)"


def test_predict_cache_keys_catches_schema_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug A regression — ``_predict_cache_keys`` must catch ``SchemaValidationError``
    in addition to ``CompilationError`` / ``WorkflowValidationError``. They're
    sibling subclasses of ``PflowError``, not related; the original except clause
    let ``SchemaValidationError`` propagate uncaught and crashed
    ``pflow analyze-cache`` whenever a 2.1.0 trace was auto-loaded for a
    workflow with required-but-malformed inputs (the dominant agent flow).

    Mutation test: drop ``SchemaValidationError`` from the except tuple in
    ``_predict_cache_keys``; this test fails with an unhandled exception.
    """
    from pflow.core.cache_analysis.analyze import _predict_cache_keys
    from pflow.core.exceptions import SchemaValidationError

    # Inject a SchemaValidationError at the compile_workflow boundary.
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise SchemaValidationError("Validation error at inputs.name: empty", path="inputs.name")

    monkeypatch.setattr("pflow.runtime.compile_workflow", _boom)

    class _Stub:
        pass

    # Pass non-empty parameters so Decision 1 (params={} + declared inputs) doesn't fire.
    keys, notes = _predict_cache_keys(
        workflow_ir={"inputs": {"name": {"type": "string"}}, "nodes": []},
        parameters={"name": "alice"},
        memo_cache=_Stub(),
        workflow_path="x.pflow.md",
    )
    assert keys == {}
    assert any("predicted-key matching unavailable" in n for n in notes)
    assert any("SchemaValidationError" in n for n in notes)


def test_discrepancy_compile_failure_falls_back_to_observable_only(tmp_path: Path) -> None:
    """When ``compile_workflow`` raises (here: a malformed IR shape that
    fails compile checks), the analyzer catches the exception, appends a
    notes entry, and falls back to observable-only attribution. The
    discrepancy is still emitted via the chunk_skipped observable path.

    Mutation-test: narrowing the except clause back to just CompilationError
    won't cover the ValueError this fixture triggers — analyze() would
    crash entirely and this test would fail.
    """
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "gen",
                "llm_call": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_age_sec": 10,
                    "cache_chunks_skipped": ["concept"],
                },
            }
        ],
    )
    # This IR has no ``inputs`` declaration so D11-A doesn't fire, but
    # the malformed batch shape (string instead of dict) triggers a
    # ValueError downstream of compile_workflow during planning.
    bad_ir = {
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "params": {"prompt": "hi"},
                "batch": "not-a-dict-or-list",
            }
        ]
    }

    class _Stub:
        pass

    result = analyze(
        bad_ir,
        workflow_path="bad.pflow.md",
        trace_path=trace_path,
        memo_cache=_Stub(),
    )
    # The compile-failure note is appended.
    assert any("predicted-key matching unavailable" in n for n in result.notes)
    # Observable-only attribution still fires (chunk_skipped is observable).
    diag = next((d for d in result.warnings if d.id == "cache.discrepancy"), None)
    assert diag is not None
    assert diag.context is not None
    assert diag.context["root_cause"] == "chunk_skipped"


# ---------------------------------------------------------------------------
# Cross-workflow B.2/B.3 negative fixtures (review-fidelity W11)
# ---------------------------------------------------------------------------


def test_cross_workflow_prose_mismatch_silent_when_prose_byte_equal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative fixture for B.2: when parent and child declare the same
    chunk name with byte-equal prose_before, NO prose-mismatch fires.

    Mutation-test guard: removing the byte-comparison gate
    (``parent_prose != child_prose``) at ``_cross_workflow_prose_mismatches``
    would emit prose-mismatch on every shared chunk — this test fails.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "cache": {
            "items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "Same prose\n"}]
        },
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"direction": "${creative.direction}"}},
            }
        ],
    }
    child_ir = {
        "cache": {
            "items": [{"name": "creative.direction", "var": "creative.direction", "prose_before": "Same prose\n"}]
        },
        "nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.cross-workflow-prose-mismatch" not in {d.id for d in result.warnings}


def test_cross_workflow_prose_mismatch_suppressed_by_rename_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DD#26 invariant: when a rename is detected on the same edge, the
    rename diagnostic takes precedence and prose-mismatch is suppressed —
    even if the prose differs byte-for-byte.

    Mutation-test guard: removing the ``if edge.is_rename: continue`` gate
    in ``_cross_workflow_prose_mismatches`` would emit BOTH rename AND
    prose-mismatch on the same edge — this test fails.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    # Parent passes ``${concept_brief}`` to child as ``creative_brief``
    # (rename detected via tail-comparison) AND the child cache block has
    # different prose for the same chunk name.
    parent_ir = {
        "cache": {"items": [{"name": "concept_brief", "var": "concept_brief", "prose_before": "Parent prose\n"}]},
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"creative_brief": "${concept_brief}"}},
            }
        ],
    }
    child_ir = {
        "cache": {"items": [{"name": "concept_brief", "var": "concept_brief", "prose_before": "Different prose\n"}]},
        "nodes": [{"id": "noop", "type": "shell", "params": {"command": "echo ok"}}],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    ids = {d.id for d in result.warnings}
    # Rename fires.
    assert "cache.cross-workflow-rename-detected" in ids
    # Prose-mismatch is suppressed by the rename precedence.
    assert "cache.cross-workflow-prose-mismatch" not in ids


# ---------------------------------------------------------------------------
# `_iter_llm_events` walker — load-bearing structural tests (review-fidelity W4)
# ---------------------------------------------------------------------------


def test_iter_llm_events_includes_cached_events() -> None:
    """The walker must yield cached events — that's the whole reason it
    exists separately from ``_collect_llm_calls_from_events`` (which skips
    cached for cost aggregation).
    """
    from pflow.core.cache_analysis.analyze import _iter_llm_events

    events = [
        {
            "node_id": "memoized-llm",
            "cached": True,
            "llm_call": {"model": "anthropic/claude-sonnet-4-5", "cache_creation_input_tokens": 0},
        }
    ]
    yielded = list(_iter_llm_events(events))
    assert len(yielded) == 1
    assert yielded[0][0] == "memoized-llm"
    assert yielded[0][1].get("cached") is True


def test_iter_llm_events_recurses_into_batch_items() -> None:
    """Batch items have nested ``events`` lists for sub-workflow events
    PER ITEM — easy to miss this nested-recursion path. Without it,
    discrepancy detection would skip every batched LLM call inside a
    batch sub-workflow.
    """
    from pflow.core.cache_analysis.analyze import _iter_llm_events

    events = [
        {
            "node_id": "batch-parent",
            "batch_items": [
                {
                    "node_id": "batch-parent",
                    "events": [
                        {
                            "node_id": "inner-llm",
                            "llm_call": {"model": "anthropic/claude-sonnet-4-5"},
                        }
                    ],
                },
                {
                    "node_id": "batch-parent",
                    "llm_call": {"model": "anthropic/claude-sonnet-4-5"},  # flat-batch case
                },
            ],
        }
    ]
    yielded = [(node_id, ev) for node_id, ev in _iter_llm_events(events)]
    yielded_node_ids = [y[0] for y in yielded]
    # Should include BOTH the inner sub-workflow LLM and the flat-batch LLM.
    assert "inner-llm" in yielded_node_ids
    # Mutation-test: removing ``yield from _iter_llm_events(item.get("events", []))``
    # makes ``inner-llm`` disappear from the yields.


# ---------------------------------------------------------------------------
# `_aggregate_and_cap_discrepancies` — coverage for CRIT-4 (review-fidelity W5)
# ---------------------------------------------------------------------------


def test_aggregator_groups_by_node_and_root_cause_with_affected_invocations() -> None:
    """Three discrepancies for the same (node_id, root_cause) collapse into
    one diagnostic with affected_invocations=3. Different root_cause stays
    separate.

    Mutation-test guard for the dataclasses.replace defensive pattern:
    using in-place mutation (``representative.context["..."] = ...``) would
    leak ``affected_invocations`` to other diagnostics in the same group
    when ``make_diagnostic`` shares context refs.
    """
    from pflow.core.cache_analysis.analyze import _aggregate_and_cap_discrepancies
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diags = [
        make_diagnostic(
            "cache.discrepancy",
            node_id="gen",
            trace_path="t",
            predicted_pct=100,
            predicted_label="hit",
            actual_pct=0,
            root_cause="ttl_expiry",
            root_cause_summary="x",
            affected_workflow="w",
        )
        for _ in range(3)
    ]
    diags.append(
        make_diagnostic(
            "cache.discrepancy",
            node_id="gen",
            trace_path="t",
            predicted_pct=100,
            predicted_label="hit",
            actual_pct=0,
            root_cause="key_mismatch",
            root_cause_summary="y",
        )
    )

    notes: list[str] = []
    aggregated = _aggregate_and_cap_discrepancies(diags, max_total=20, notes=notes)
    assert len(aggregated) == 2
    assert aggregated[0].context is not None
    assert aggregated[0].context["affected_invocations"] == 3
    assert aggregated[0].context["root_cause"] == "ttl_expiry"
    assert aggregated[1].context is not None
    assert aggregated[1].context["affected_invocations"] == 1
    assert aggregated[1].context["root_cause"] == "key_mismatch"
    # Cap not engaged — no truncation note.
    assert notes == []


def test_aggregator_caps_at_max_total_and_notes_truncation() -> None:
    """When the number of unique (node_id, root_cause) groups exceeds
    max_total, the cap engages and a notes entry surfaces the suppressed
    count. Without the note, agents see a silently-truncated discrepancy
    list.
    """
    from pflow.core.cache_analysis.analyze import _aggregate_and_cap_discrepancies
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diags = [
        make_diagnostic(
            "cache.discrepancy",
            node_id=f"node-{i}",
            trace_path="t",
            predicted_pct=100,
            predicted_label="hit",
            actual_pct=0,
            root_cause="key_mismatch",
            root_cause_summary="x",
        )
        for i in range(25)
    ]
    notes: list[str] = []
    aggregated = _aggregate_and_cap_discrepancies(diags, max_total=20, notes=notes)
    assert len(aggregated) == 20
    assert any("5 additional group(s) suppressed by cap" in n for n in notes)


def test_aggregator_does_not_mutate_shared_context_refs() -> None:
    """``make_diagnostic`` may share context dicts; aggregator must use
    ``dataclasses.replace`` so the merged ``affected_invocations`` doesn't
    leak to siblings (which would silently misreport invocation counts).
    """
    from pflow.core.cache_analysis.analyze import _aggregate_and_cap_discrepancies

    shared_context = {"category": "cache_advisory", "root_cause": "ttl_expiry"}
    from pflow.core.diagnostic import Diagnostic, Severity

    d1 = Diagnostic(
        severity=Severity.INFO,
        source="cache_analyzer",
        id="cache.discrepancy",
        message="x",
        node_id="gen",
        context=shared_context,
    )
    d2 = Diagnostic(
        severity=Severity.INFO,
        source="cache_analyzer",
        id="cache.discrepancy",
        message="y",
        node_id="gen",
        context=shared_context,
    )
    aggregated = _aggregate_and_cap_discrepancies([d1, d2], max_total=20, notes=None)
    # Shared dict must NOT have ``affected_invocations`` written to it.
    assert "affected_invocations" not in shared_context
    # The aggregated diagnostic carries the merged context separately.
    assert aggregated[0].context is not None
    assert aggregated[0].context["affected_invocations"] == 2


# ---------------------------------------------------------------------------
# Integration test: replaces the mocked `_predict_cache_keys` test
# (review-fidelity Critical 1)
# ---------------------------------------------------------------------------


def test_discrepancy_key_mismatch_via_real_planner_consumption(
    tmp_path: Path,
    isolate_pflow_config: dict[str, Any],
    mock_llm_client: Any,
) -> None:
    """End-to-end test that drives the C.2 architectural pivot through
    production code: real engine populates cache_key in memo, real
    ``build_plan`` predicts cache_key from current params, the analyzer
    consumes both and emits ``key_mismatch`` when they diverge.

    Mutation-test: dropping ``cache_key=planned.cache_key`` from any
    PlanEntry constructor in plan.py makes predicted_keys empty, the
    analyzer falls back to observable-only attribution, and this test
    fails (no key_mismatch diagnostic; root_cause is ``unknown`` instead).

    No monkeypatch of ``_predict_cache_keys`` — the whole point is the
    planner-consumption path is real.
    """
    import sqlite3

    from pflow.core.cache_analysis.analyze import analyze as _analyze
    from pflow.core.markdown_parser import parse_markdown
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner
    from pflow.runtime.cache import MemoizationCache

    workflow_path = tmp_path / "wf.pflow.md"
    workflow_path.write_text(
        "# Cache Mismatch Test\n\n"
        "Single-LLM workflow whose cache_key depends on ${topic}. "
        "We run with topic=A, then ask the analyzer to predict for topic=B.\n\n"
        "## Inputs\n\n"
        "### topic\n\n"
        "The topic to summarize.\n\n"
        "- type: string\n\n"
        "## Steps\n\n"
        "### gen\n\n"
        "Run the LLM with the topic.\n\n"
        "- type: llm\n"
        "- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\n"
        "Summarize ${topic}.\n"
        "```\n",
        encoding="utf-8",
    )

    # Run 1 with topic=A — engine populates the memo cache. The autouse
    # mock_llm_client fixture handles the LLM call; we don't need a real
    # API key.
    config = RunnerConfig(trace_enabled=False, cache_enabled=True)
    runner = WorkflowRunner()
    result_1 = runner.run(str(workflow_path), {"topic": "A"}, config)
    assert result_1.success, f"Run 1 failed: {result_1.diagnostics}"

    # Read engine's actual cache_key from SQLite — same pattern as the
    # extended test_plan_drift parity test. The MemoizationCache lives at
    # ``~/.pflow/cache/cache.db`` and the conftest's ``isolate_pflow_config``
    # patches ``Path.home()`` to ``tmp_path``, so this resolves under the
    # isolated config dir.
    cache_db = isolate_pflow_config["pflow_dir"] / "cache" / "cache.db"
    assert cache_db.exists(), f"Memo cache should exist at {cache_db}"
    conn = sqlite3.connect(cache_db)
    try:
        row = conn.execute(
            "SELECT cache_key FROM cache_entries WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
            ("gen",),
        ).fetchone()
        actual_engine_key = row[0] if row else None
    finally:
        conn.close()
    assert actual_engine_key is not None, "Engine should have populated a cache row for 'gen'"

    # Build a synthetic 2.1.0 trace recording the engine's cache_key.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": str(workflow_path.resolve()),
            "nodes": [
                {
                    "node_id": "gen",
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "cache_key": actual_engine_key,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "cache_age_sec": 5,
                        "cache_chunks_skipped": [],
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    # Now invoke analyze() with DIFFERENT params — planner predicts a
    # different cache_key from the same workflow + new params.
    parsed = parse_markdown(workflow_path.read_text(encoding="utf-8"))
    memo_cache = MemoizationCache(db_path=cache_db, read_enabled=True)
    cache_analysis = _analyze(
        parsed.ir,
        parameters={"topic": "B"},
        workflow_path=str(workflow_path.resolve()),
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=memo_cache,
    )

    diag = next((d for d in cache_analysis.warnings if d.id == "cache.discrepancy"), None)
    assert diag is not None, (
        f"Expected cache.discrepancy via planner-consumption; got {[d.id for d in cache_analysis.warnings]}"
    )
    assert diag.context is not None
    assert diag.context["root_cause"] == "key_mismatch", (
        f"Expected key_mismatch; got {diag.context['root_cause']!r}. "
        "If predicted_cache_key is None, planner→PlanEntry propagation drifted."
    )
    assert diag.context["predicted_cache_key"] is not None
    assert diag.context["predicted_cache_key"] != actual_engine_key
    assert diag.context["actual_cache_key"] == actual_engine_key
