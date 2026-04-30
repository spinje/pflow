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
    diag = next(d for d in result.warnings if d.id == "cache.shared-context-undeclared")
    assert diag.node_id == "child-call"
    assert diag.context is not None
    assert diag.context["shared_chunks"] == ["direction"]
    assert diag.context["affected_workflow"] == "parent.pflow.md"


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
