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
from pflow.core.cache_analysis.cost_estimation import ModelPricing
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult


def _word_count(_model: str | None, text: str | None, **_kwargs: Any) -> tuple[int, str]:
    return (len((text or "").split()), "heuristic")


def _patch_pricing(
    monkeypatch: pytest.MonkeyPatch,
    *,
    missing_models: set[str] | None = None,
    missing_chunks: set[str] | None = None,
) -> None:
    """Stub pricing + per-chunk token estimation so the fragmentation detector
    runs end-to-end in pure-greenfield tests without memo data.

    ``missing_models`` makes ``get_model_pricing`` return ``None`` for those
    models (drives "honest-unmeasurable" path).
    ``missing_chunks`` makes ``_estimate_ref_tokens`` return ``None`` for those
    chunk names (drives "any shared chunk None → skip emit" path).
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    cost_module = importlib.import_module("pflow.core.cache_analysis.cost_estimation")
    missing = missing_models or set()
    missing_chunk_set = missing_chunks or set()

    def fake_pricing(model: str) -> ModelPricing | None:
        if model in missing:
            return None
        return ModelPricing(input_rate=1.0, output_rate=1.0, cache_creation_rate=1.25, cache_read_rate=0.1)

    def fake_ref_tokens(chunk: str, **_kwargs: Any) -> int | None:
        return None if chunk in missing_chunk_set else 100

    monkeypatch.setattr(analyze_module, "_input_rate", lambda model: None if model in missing else 1.0)
    monkeypatch.setattr(cost_module, "get_model_pricing", fake_pricing)
    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", fake_ref_tokens)


@pytest.fixture(autouse=True)
def deterministic_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    token_estimation_module = importlib.import_module("pflow.core.cache_analysis.token_estimation")
    monkeypatch.setattr(analyze_module, "estimate_tokens", _word_count)
    # Mirror the patch in token_estimation.py — analyze.py-resident callers
    # see the first; token_estimation.py-resident callers (``_estimate_ref_tokens``,
    # ``_sum_resolved_chunk_tokens``) see the second. Without both, Tier 2 of
    # ``estimate_cacheable_tokens`` calls real ``litellm.token_counter`` and
    # tests that exercise memo-resolved chunk tokenization see non-deterministic
    # values.
    monkeypatch.setattr(token_estimation_module, "estimate_tokens", _word_count)
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
        ],
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


def test_shared_context_undeclared_populates_suggested_block_with_dotted_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 2000)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 1000)
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


def test_sub_workflow_cache_undeclared_emits_for_reused_child_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child workflow with repeated LLM consumers needs its own ## Cache."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
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
            },
            {
                "id": "review-input",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${direction}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    matching = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert len(matching) == 1
    diag = matching[0]
    assert diag.node_id is None
    assert diag.context is not None
    assert diag.context["parent_workflow"] == "parent.pflow.md"
    assert diag.context["child_workflow"] == "<inline>"
    assert diag.context["child_workflow_basename"] == "<inline>"
    assert diag.context["parent_value_expr"] == "creative.direction"
    assert diag.context["child_input_name"] == "direction"
    assert diag.context["node_count"] == 2
    assert diag.context["affected_workflow"] == "<inline>"
    assert "sub-workflows do not inherit" in diag.message


def test_sub_workflow_cache_undeclared_suppresses_when_no_llm_consumers(monkeypatch: pytest.MonkeyPatch) -> None:
    """No child LLM consumers means no child-cache recommendation."""
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
    assert "cache.sub-workflow-cache-undeclared" not in {d.id for d in result.warnings}


def test_sub_workflow_cache_undeclared_suppresses_single_child_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single child LLM consumer has no repeated-read cache leverage."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "branch",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"opaque": "${opaque}"}},
            },
        ]
    }
    child_ir = {
        "nodes": [
            {"id": "llm", "type": "llm", "params": {"prompt": "Process ${opaque}"}},
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )
    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.sub-workflow-cache-undeclared" not in {d.id for d in result.warnings}


def test_sub_workflow_cache_undeclared_emits_for_batch_item_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent batch values can be child-local stable context.

    ``${item.concept}`` changes across parent fanout items, so it is correctly
    ignored by rename/prose-alignment checks. But each child invocation receives
    one concrete ``concept`` input, and repeated child LLM consumers can reuse
    that input through the child's own ``## Cache`` block.

    Mutation test: reintroduce the old ``is_batch_alias_root`` suppression in
    ``_sub_workflow_cache_candidate`` and this warning disappears.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "song-fanout",
                "type": "workflow",
                "params": {
                    "workflow": "./song-child.pflow.md",
                    "inputs": {"concept": "${item.concept}"},
                },
                "batch": {"items": "${concepts}", "as": "item"},
            }
        ]
    }
    child_ir = {
        "nodes": [
            {"id": "draft", "type": "llm", "params": {"prompt": "Draft ${concept}"}},
            {"id": "review", "type": "llm", "params": {"prompt": "Review ${concept}"}},
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/song-child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    found = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert len(found) == 1
    assert found[0].context is not None
    assert found[0].context["parent_value_expr"] == "item.concept"
    assert found[0].context["child_input_name"] == "concept"
    assert found[0].context["affected_workflow"] == "/abs/song-child.pflow.md"
    assert "cache.cross-workflow-rename-detected" not in {d.id for d in result.warnings}


# ---------------------------------------------------------------------------
# Sub-workflow cache declaration recommendations
#
# Each of the tests below drives ``analyze(workflow_ir, ...)`` end-to-end with
# monkeypatched sub-workflow resolution. They MUST NOT construct Diagnostics
# directly — that bypasses the analyzer logic and reproduces Pitfall #19
# (synthetic fixture matches buggy code shape; production code path differs).
# ---------------------------------------------------------------------------


def test_sub_workflow_cache_undeclared_emits_one_diagnostic_per_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One value flowing to N children creates N child-scoped edits."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    # Names match across the boundary (parent_value_expr.last_segment == child_input_name)
    # so this exercises the VALUE-FLOW branch, not the rename branch. Renames
    # have separate detection logic + their own evidence-basis suppression.
    parent_ir = {
        "nodes": [
            {
                "id": "use-brief",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${concept_brief}"},
            },
            {
                "id": "review-emotional",
                "type": "workflow",
                "params": {
                    "workflow": "./review-emotional.pflow.md",
                    "inputs": {"concept_brief": "${concept_brief}"},
                },
            },
            {
                "id": "review-craft",
                "type": "workflow",
                "params": {
                    "workflow": "./review-craft.pflow.md",
                    "inputs": {"concept_brief": "${concept_brief}"},
                },
            },
        ]
    }

    # Both child workflows have repeated LLM consumers of the input.
    child_ir = {
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept_brief}"},
            },
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Score ${concept_brief}"},
            },
        ]
    }
    # Walker calls resolve_sub_workflow per child. The fake returns the same
    # IR but DIFFERENT path each call so the walker labels children distinctly.
    call_count = [0]
    paths = ["/abs/review-emotional.pflow.md", "/abs/review-craft.pflow.md"]

    def fake_resolve(_params: dict[str, Any], _base_path: Path | None) -> SubWorkflowResult:
        path = Path(paths[call_count[0] % len(paths)])
        call_count[0] += 1
        return SubWorkflowResult(child_ir, path, ())

    monkeypatch.setattr(cross_module, "resolve_sub_workflow", fake_resolve)

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    matching = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert [d.context["child_workflow"] for d in matching if d.context] == [
        "/abs/review-craft.pflow.md",
        "/abs/review-emotional.pflow.md",
    ]
    assert all(d.context and d.context["child_input_name"] == "concept_brief" for d in matching)


def test_sub_workflow_cache_undeclared_tracks_child_input_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sub-paths passed to different child inputs produce child-input edits."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    # Use child_input_name == last_segment(parent_value_expr) to avoid the
    # rename branch — names match across the boundary.
    parent_ir = {
        "nodes": [
            {
                "id": "use-concept-root",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${concept}"},
            },
            {
                "id": "child-A",
                "type": "workflow",
                "params": {
                    "workflow": "./child-a.pflow.md",
                    "inputs": {"title": "${concept.title}"},
                },
            },
            {
                "id": "child-B",
                "type": "workflow",
                "params": {
                    "workflow": "./child-b.pflow.md",
                    "inputs": {"core_idea": "${concept.core_idea}"},
                },
            },
        ]
    }

    # Each child consumes the input via its declared name so the LAST segment
    # of parent_value_expr matches child_input_name (no rename).
    child_a_ir = {
        "nodes": [
            {
                "id": "use-title",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Title: ${title}"},
            },
            {
                "id": "review-title",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${title}"},
            },
        ]
    }
    child_b_ir = {
        "nodes": [
            {
                "id": "use-core",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Core: ${core_idea}"},
            },
            {
                "id": "review-core",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${core_idea}"},
            },
        ]
    }
    call_count = [0]

    def fake_resolve(_params: dict[str, Any], _base_path: Path | None) -> SubWorkflowResult:
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            return SubWorkflowResult(child_a_ir, Path("/abs/child-a.pflow.md"), ())
        return SubWorkflowResult(child_b_ir, Path("/abs/child-b.pflow.md"), ())

    monkeypatch.setattr(cross_module, "resolve_sub_workflow", fake_resolve)

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    matching = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert [d.context["child_input_name"] for d in matching if d.context] == ["title", "core_idea"]


def test_parent_cache_declaration_does_not_suppress_child_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent ## Cache blocks are not inherited by sub-workflows."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "cache": {
            "ttl": "5m",
            "items": [
                {
                    "name": "concept",
                    "var": "${concept}",
                    "prose_before": "The concept",
                    "_source_line": 1,
                }
            ],
        },
        "nodes": [
            {
                "id": "use-it",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["concept"],
                "params": {"prompt": "Use ${concept}"},
            },
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            },
        ],
    }
    child_ir = {
        "nodes": [
            {
                "id": "use-concept",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${concept}"},
            },
            {
                "id": "review-concept",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    found = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert len(found) == 1
    assert found[0].context is not None
    assert found[0].context["affected_workflow"] == "/abs/child.pflow.md"
    assert found[0].context["child_input_name"] == "concept"
    from pflow.core.cache_analysis.render_json import render_json

    payload = render_json(result)
    warning = next(w for w in payload["warnings"] if w["id"] == "cache.sub-workflow-cache-undeclared")
    assert warning["suggestions"][0] == "In /abs/child.pflow.md, add a ## Cache chunk for `${concept}`."
    assert warning["suggestions"][1] == "Add `concept` to `prompt_cache:` on the child LLM nodes that reuse it."


def test_child_cache_declaration_suppresses_child_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child-owned ## Cache declaration satisfies the child recommendation."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-heavy",
                "type": "workflow",
                "params": {
                    "workflow": "./heavy.pflow.md",
                    "inputs": {"shared": "${shared}"},
                },
            },
        ]
    }
    heavy_ir = {
        "cache": {"items": [{"name": "shared", "var": "${shared}", "prose_before": "Shared:\n"}]},
        "nodes": [
            {
                "id": "use1",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${shared}"},
            },
            {
                "id": "use2",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Again ${shared}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(heavy_ir, Path("/abs/heavy.pflow.md"), ()),
    )
    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.sub-workflow-cache-undeclared" not in {d.id for d in result.warnings}


def test_child_cache_recommendation_emits_only_for_undeclared_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When one receiving child declares the input, only the missing child is reported."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "declared-child",
                "type": "workflow",
                "params": {"workflow": "./declared.pflow.md", "inputs": {"shared": "${shared}"}},
            },
            {
                "id": "missing-child",
                "type": "workflow",
                "params": {"workflow": "./missing.pflow.md", "inputs": {"shared": "${shared}"}},
            },
        ]
    }
    declared_ir = {
        "cache": {"items": [{"name": "shared", "var": "${shared}", "prose_before": "Shared:\n"}]},
        "nodes": [
            {"id": "use", "type": "llm", "params": {"prompt": "Use ${shared}"}},
            {"id": "review", "type": "llm", "params": {"prompt": "Review ${shared}"}},
        ],
    }
    missing_ir = {
        "nodes": [
            {"id": "use", "type": "llm", "params": {"prompt": "Use ${shared}"}},
            {"id": "review", "type": "llm", "params": {"prompt": "Review ${shared}"}},
        ],
    }
    call_count = [0]

    def fake_resolve(_params: dict[str, Any], _base_path: Path | None) -> SubWorkflowResult:
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            return SubWorkflowResult(declared_ir, Path("/abs/declared.pflow.md"), ())
        return SubWorkflowResult(missing_ir, Path("/abs/missing.pflow.md"), ())

    monkeypatch.setattr(cross_module, "resolve_sub_workflow", fake_resolve)

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    found = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert len(found) == 1
    assert found[0].context is not None
    assert found[0].context["child_workflow"] == "/abs/missing.pflow.md"


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
        lambda *_args, **_kwargs: ({("parent.pflow.md", "gen"): "predicted-key"}, []),
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


def test_discrepancy_ttl_attribution_uses_leaf_workflows_ttl_not_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 9 regression: ``_attribute_root_cause`` reads TTL from the LEAF
    event's workflow IR, not the analyzed root. Mixed parent/child TTLs
    (parent declares ``ttl: 1h``, child declares ``ttl: 5m``) would
    otherwise miss the child's actual ttl_expiry: a 600s cache_age in the
    child looks fresh against parent's 1h window but is expired against
    child's 5m. The analyzer would attribute it to ``unknown`` instead of
    ``ttl_expiry``, giving agents the wrong remediation hint.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"topic": {"type": "string"}},
        "cache": {
            "ttl": "1h",  # Parent declares hour-long cache.
            "items": [{"name": "topic", "var": "topic", "prose_before": "Topic:\n"}],
        },
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"topic": "${topic}"}},
            }
        ],
    }
    child_ir = {
        "cache": {
            "ttl": "5m",  # Child declares the default 5-minute cache.
            "items": [{"name": "topic", "var": "topic", "prose_before": "Topic:\n"}],
        },
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["topic"],
                "params": {"prompt": "Review for ${topic}"},
            }
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "call-child",
                "sub_workflow_events": [
                    {
                        "node_id": "review",
                        "llm_call": {
                            "model": "anthropic/claude-sonnet-4-5",
                            "cache_creation_input_tokens": 100,
                            "cache_read_input_tokens": 0,
                            "cache_age_sec": 600,  # 10m: expired against child 5m, fresh against parent 1h
                            "cache_chunks_skipped": [],
                        },
                    }
                ],
            }
        ],
    )
    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.context is not None
    assert diag.context["root_cause"] == "ttl_expiry", (
        f"Bug 9: expected ttl_expiry against child's 5m TTL; got {diag.context['root_cause']!r}. "
        "Pre-fix the analyzer used the parent's 1h TTL and the 600s cache age looked fresh."
    )


def test_discrepancy_for_sub_workflow_node_carries_child_workflow_path_in_affected_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 6 regression: ``cache.discrepancy`` for a sub-workflow LLM node
    must record the CHILD workflow's path in ``context.affected_workflow``,
    not the analyzed root. Otherwise renderer scope-suppression at
    ``view_helpers.py`` treats the finding as root-scoped and drops the
    ``in <basename>`` suffix that Bug 1's fix adds for cross-workflow per-
    node findings — agents see ``review`` instead of ``review in
    child.pflow.md`` and can't tell which file's ``## Cache`` block to edit.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"topic": "${topic}"}},
            }
        ],
    }
    child_ir = {
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["topic"],
                "params": {"prompt": "Review for ${topic}"},
            }
        ],
        "cache": {"items": [{"name": "topic", "var": "topic", "prose_before": "Topic:\n"}]},
        "inputs": {"topic": {"type": "string"}},
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = _write_trace(
        tmp_path,
        [
            {
                "node_id": "call-child",
                "sub_workflow_events": [
                    {
                        "node_id": "review",
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
    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.node_id == "review"
    assert diag.context is not None
    assert diag.context["affected_workflow"] == str(child_path), (
        f"Bug 6: expected affected_workflow == child path {str(child_path)!r}, "
        f"got {diag.context['affected_workflow']!r} (would be the analyzed root pre-fix)"
    )
    assert diag.context["workflow_path_short"] == "child"


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
        lambda *_args, **_kwargs: ({("parent.pflow.md", "gen"): "shared-key"}, []),
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
        lambda *_args, **_kwargs: ({("parent.pflow.md", "gen"): "predicted-key"}, []),
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
    when the per-workflow compile path raises. They're sibling subclasses of
    ``PflowError`` (not related to ``CompilationError``); the original except
    clause let ``SchemaValidationError`` propagate uncaught and crashed
    ``pflow analyze-cache`` whenever a 2.1.0 trace was auto-loaded for a
    workflow with required-but-malformed inputs (the dominant agent flow).

    Mutation test: drop ``SchemaValidationError`` from the except tuple in
    ``_build_predict_scaffold``; this test fails with an unhandled exception.

    Patches ``compile_workflow`` AT the analyzer's call site
    (``pflow.core.cache_analysis.analyze``) — patching the
    ``pflow.runtime.compile_workflow`` re-export leaks into ``workflow_executor``'s
    cached top-level binding (set at first import of ``pflow.runtime.workflow_executor``)
    and breaks any subsequent test that calls ``WorkflowRunner.run``. Patching
    the lazy import's resolved attribute keeps the patch local to the analyzer.
    """
    from types import SimpleNamespace

    from pflow.core.cache_analysis.analyze import _build_predict_scaffold, _predict_cache_keys
    from pflow.core.cache_analysis.context import AnalysisContext
    from pflow.core.exceptions import SchemaValidationError

    # Inject a SchemaValidationError at the analyzer's compile boundary by
    # replacing _build_predict_scaffold's behavior — same effect as patching
    # compile_workflow but contained to the analyzer (no side-effect on
    # workflow_executor's cached binding).
    def _boom_scaffold(
        _workflow_ir: Any, _params: Any, _memo_cache: Any, workflow_path: str | None
    ) -> tuple[Any, str | None]:
        # Mirror the real shape: scaffold=None + per-workflow error note.
        # The note text format must match production so the assertion stays
        # honest (scaffold's own error message uses `<root>` for None paths).
        label = workflow_path or "<root>"
        return None, (
            f"Discrepancy detection: predicted-key matching for {label} "
            "unavailable (SchemaValidationError); compile failed. Observable-field "
            "attributions still apply."
        )

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_build_predict_scaffold", _boom_scaffold)
    # Reference SchemaValidationError so the docstring's mutation-test claim
    # stays honest (the catch list lives in ``_build_predict_scaffold`` and
    # this test's stub mirrors what production would produce on that catch).
    _ = SchemaValidationError

    class _Stub:
        pass

    workflow_ir: dict[str, Any] = {
        "inputs": {"name": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "go ${name}"},
                "prompt_cache": ["name"],
            }
        ],
        "cache": {"items": [{"name": "name", "var": "name", "prose_before": "N:\n"}]},
    }
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters={"name": "alice"},
        memo_cache=_Stub(),
        workflow_path="x.pflow.md",
    )
    cw_result = SimpleNamespace(irs_by_workflow={"x.pflow.md": workflow_ir}, edges=())

    keys, notes = _predict_cache_keys(cw_result, ctx)
    assert keys == {}
    assert any("predicted-key matching for x.pflow.md unavailable" in n for n in notes)
    assert any("SchemaValidationError" in n for n in notes)
    # Sanity: the real _build_predict_scaffold's catch list still includes
    # SchemaValidationError. Drop it from the production except tuple and this
    # passes (the test's stub doesn't use the real catch), so we also exercise
    # the production helper directly with a synthetic crashing IR.
    bad_ir: dict[str, Any] = {
        "inputs": {"x": {"type": "string", "required": True}},
        # Missing required "x" parameter → compile-time validation fails.
        "nodes": [{"id": "n", "type": "llm", "params": {"prompt": "${x}"}}],
    }
    scaffold, note = _build_predict_scaffold(bad_ir, {}, _Stub(), "bad.pflow.md")
    assert scaffold is None
    assert note is not None
    assert "bad.pflow.md" in note
    assert "compile failed" in note


def test_discrepancy_compile_failure_falls_back_to_observable_only(tmp_path: Path) -> None:
    """When ``compile_workflow`` raises (here: a malformed IR shape that
    fails compile checks), the analyzer catches the exception, appends a
    notes entry, and falls back to observable-only attribution. The
    discrepancy is still emitted via the chunk_skipped observable path.

    Defends: the except clause must be broad enough to cover ValueError
    (and other compile-time exceptions); narrowing back to just
    CompilationError lets analyze() crash entirely on this fixture.
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
    # Per-workflow compile-failure note appended (compile fails before any node).
    assert any("predicted-key matching for bad.pflow.md unavailable" in n for n in result.notes)
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
    # Defends: ``yield from _iter_llm_events(item.get("events", []))`` must
    # recurse into batch-item events; without it, ``inner-llm`` disappears.


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
            affected_workflow="w",
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
            affected_workflow="w",
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

    Defends: every PlanEntry constructor in plan.py must include
    ``cache_key=planned.cache_key``; dropping it from any path makes
    predicted_keys empty, the analyzer falls back to observable-only
    attribution, and ``key_mismatch`` collapses to ``unknown`` root_cause.

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


# ---------------------------------------------------------------------------
# Bug 5 fix — decoupled prediction covers sub-workflow nodes
# ---------------------------------------------------------------------------


def test_predict_cache_keys_includes_sub_workflow_nodes(
    tmp_path: Path,
    isolate_pflow_config: dict[str, Any],
    mock_llm_client: Any,
) -> None:
    """Prediction walks every workflow in cw_result.irs_by_workflow, so
    sub-workflow LLM nodes get cache_keys (Bug 5 fix). Previously
    BFS-downstream entries had cache_key=None and silent-skipped.

    Uses production helpers (``walk_cross_workflow`` + ``_build_parameters_by_workflow``)
    so the parameters_by_workflow keys match what the cross-workflow walker
    produces — a hand-built mapping could pass for the wrong reason if the
    walker's labeling diverges. Runs the parent through ``WorkflowRunner``
    once so the memo cache is populated (the prediction itself doesn't need
    the entries, but a real memo exercises the same memo-aware path the
    analyzer hits in production).
    """
    from pflow.core.cache_analysis.analyze import (
        _build_parameters_by_workflow,
        _predict_cache_keys,
    )
    from pflow.core.cache_analysis.context import AnalysisContext
    from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow
    from pflow.core.markdown_parser import parse_markdown
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner
    from pflow.runtime.cache import MemoizationCache

    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(
        "# Child\n\nReview a draft.\n\n"
        "## Inputs\n\n### draft\n\nThe draft.\n\n- type: string\n\n"
        "## Steps\n\n### review\n\nReview the draft.\n\n"
        "- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nReview ${draft}.\n```\n",
        encoding="utf-8",
    )
    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(
        "# Parent\n\nDraft + review.\n\n"
        "## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n\n"
        "## Steps\n\n### draft\n\nDraft on topic.\n\n"
        "- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nWrite about ${topic}.\n```\n\n"
        "### call-child\n\nReview the draft.\n\n"
        f"- type: workflow\n- workflow: {child_path.resolve()}\n- inputs:\n"
        "    draft: ${draft.response}\n",
        encoding="utf-8",
    )

    # Run once so the memo cache has real entries (exercises the full memo-
    # aware prediction path; prediction itself doesn't strictly require it).
    config = RunnerConfig(trace_enabled=False, cache_enabled=True)
    run_result = WorkflowRunner().run(str(parent_path), {"topic": "compilers"}, config)
    assert run_result.success, f"Setup run failed: {run_result.diagnostics}"

    cache_db = isolate_pflow_config["pflow_dir"] / "cache" / "cache.db"
    memo_cache = MemoizationCache(db_path=cache_db, read_enabled=True)

    parent_ir = parse_markdown(parent_path.read_text(encoding="utf-8")).ir
    parent_label = str(parent_path.resolve())
    cw_result = walk_cross_workflow(
        parent_ir,
        base_path=tmp_path,
        root_workflow_path=parent_label,
    )
    # Sanity-check the production walker's labels — if these diverge, the
    # final assertions could pass for the wrong reason (keys against the
    # wrong workflow_path).
    assert parent_label in cw_result.irs_by_workflow
    child_label = str(child_path.resolve())
    assert child_label in cw_result.irs_by_workflow, f"Expected {child_label!r} in {sorted(cw_result.irs_by_workflow)}"

    parameters_by_workflow = _build_parameters_by_workflow(
        cw_result,
        {"topic": "compilers"},
        parent_label,
        memo_cache=memo_cache,
        trace_data=None,
        base_path=tmp_path,
    )
    ctx = AnalysisContext.build(
        workflow_ir=parent_ir,
        parameters={"topic": "compilers"},
        memo_cache=memo_cache,
        workflow_path=parent_label,
        base_path=tmp_path,
        parameters_by_workflow=parameters_by_workflow,
    )
    keys, _notes = _predict_cache_keys(cw_result, ctx)
    assert (parent_label, "draft") in keys, f"Expected (parent_label, 'draft') in {sorted(keys)}"
    assert (child_label, "review") in keys, f"Expected (child_label, 'review') in {sorted(keys)}"


def test_predict_node_cache_key_returns_none_for_unresolvable_node_output_ref() -> None:
    """When a chunk references ``${some_node.response}`` and ``some_node``
    isn't in memo or parameters, the prediction returns (None, "...") with
    a structured per-node skip reason naming the affected node.

    The chunk is a real upstream-node ref (no static value), so compile
    succeeds (compile validates structure, not template resolvability) but
    ``plan_node`` produces a ``template_exception`` because the upstream
    output isn't in shared. The per-node skip note must name the node so
    the agent can act on it.
    """
    from pflow.core.cache_analysis.analyze import _predict_node_cache_key

    # An ``upstream`` shell node exists (so the chunk's var passes parse-time
    # cache validation) but plan_node has no shared output for it because
    # we never executed it — strict template resolution fails per node.
    workflow_ir: dict[str, Any] = {
        "cache": {
            "items": [
                {"name": "draft", "var": "upstream.response", "prose_before": "D:\n"},
            ]
        },
        "nodes": [
            {
                "id": "upstream",
                "type": "shell",
                "params": {"command": "echo hi"},
            },
            {
                "id": "review",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Review ${upstream.response}."},
                "prompt_cache": ["draft"],
            },
        ],
        "edges": [{"from": "upstream", "to": "review"}],
    }
    cache_key, skip_reason = _predict_node_cache_key(
        node=workflow_ir["nodes"][1],
        workflow_ir=workflow_ir,
        params={},
        memo_cache=None,
        workflow_path="x.pflow.md",
    )
    assert cache_key is None
    assert skip_reason is not None
    # The per-node skip must name the node so agents can act on it.
    assert "x.pflow.md.review" in skip_reason
    assert "template resolution failed" in skip_reason


def test_predict_cache_keys_byte_identical_to_runtime(
    tmp_path: Path,
    isolate_pflow_config: dict[str, Any],
    mock_llm_client: Any,
) -> None:
    """End-to-end byte-identity contract — the analyzer's predicted cache_key
    must match what the runtime wrote to memo for the same inputs. Without
    byte-equality, ``cache.discrepancy`` produces false ``key_mismatch``.

    Drives a small workflow through ``WorkflowRunner`` once, captures the
    runtime cache_key from SQLite, then calls ``_predict_cache_keys`` with
    the same inputs and asserts byte-equality.
    """
    import sqlite3

    from pflow.core.cache_analysis.analyze import _predict_cache_keys
    from pflow.core.cache_analysis.context import AnalysisContext
    from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow
    from pflow.core.markdown_parser import parse_markdown
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner
    from pflow.runtime.cache import MemoizationCache

    workflow_path = tmp_path / "wf.pflow.md"
    workflow_path.write_text(
        "# Byte Identity\n\nSingle-LLM workflow.\n\n"
        "## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n\n"
        "## Steps\n\n### gen\n\nRun the LLM with the topic.\n\n"
        "- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nSummarize ${topic}.\n```\n",
        encoding="utf-8",
    )

    config = RunnerConfig(trace_enabled=False, cache_enabled=True)
    runner = WorkflowRunner()
    result = runner.run(str(workflow_path), {"topic": "alpha"}, config)
    assert result.success, f"Run failed: {result.diagnostics}"

    cache_db = isolate_pflow_config["pflow_dir"] / "cache" / "cache.db"
    conn = sqlite3.connect(cache_db)
    try:
        row = conn.execute(
            "SELECT cache_key FROM cache_entries WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
            ("gen",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    runtime_key = row[0]
    assert runtime_key

    # Now predict with the same inputs and assert byte-equality.
    parsed = parse_markdown(workflow_path.read_text(encoding="utf-8"))
    cw_result = walk_cross_workflow(
        parsed.ir,
        base_path=tmp_path,
        root_workflow_path=str(workflow_path.resolve()),
    )
    memo_cache = MemoizationCache(db_path=cache_db, read_enabled=True)
    ctx = AnalysisContext.build(
        workflow_ir=parsed.ir,
        parameters={"topic": "alpha"},
        memo_cache=memo_cache,
        workflow_path=str(workflow_path.resolve()),
        base_path=tmp_path,
    )
    keys, _notes = _predict_cache_keys(cw_result, ctx)
    predicted_key = keys.get((str(workflow_path.resolve()), "gen"))
    assert predicted_key == runtime_key, (
        f"Byte-identity violated: predicted {predicted_key!r} vs runtime {runtime_key!r}"
    )


def test_analyze_cache_emits_discrepancy_for_sub_workflow_node_via_subprocess(
    tmp_path: Path,
    isolate_pflow_config: dict[str, Any],
    mock_llm_client: Any,
) -> None:
    """End-to-end: a synthesized trace with parent.draft + child.review both
    carrying wrong cache_keys produces TWO ``cache.discrepancy`` entries —
    one per node, each scoped to its own workflow_path. Pre-fix this test
    only emitted ONE discrepancy because child.review's cache_key prediction
    was silently dropped on the BFS-downstream path.
    """
    from pflow.core.cache_analysis.analyze import analyze
    from pflow.core.markdown_parser import parse_markdown
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner
    from pflow.runtime.cache import MemoizationCache

    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(
        "# Child\n\nReview a draft.\n\n"
        "## Inputs\n\n### draft\n\nThe draft.\n\n- type: string\n\n"
        "## Steps\n\n### review\n\nReview the draft.\n\n"
        "- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nReview ${draft}.\n```\n",
        encoding="utf-8",
    )
    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(
        "# Parent\n\nDraft + review.\n\n"
        "## Inputs\n\n### topic\n\nThe topic.\n\n- type: string\n\n"
        "## Steps\n\n### draft\n\nDraft on topic.\n\n"
        "- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nWrite about ${topic}.\n```\n\n"
        "### call-child\n\nReview the draft.\n\n"
        f"- type: workflow\n- workflow: {child_path.resolve()}\n- inputs:\n"
        "    draft: ${draft.response}\n",
        encoding="utf-8",
    )
    # Run once to populate memo (so MemoizationCache exists for analyze).
    config = RunnerConfig(trace_enabled=False, cache_enabled=True)
    runner = WorkflowRunner()
    run_result = runner.run(str(parent_path), {"topic": "alpha"}, config)
    assert run_result.success, f"Run failed: {run_result.diagnostics}"

    # Build a synthetic trace with WRONG cache_keys for both LLM nodes.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": str(parent_path.resolve()),
            "nodes": [
                {
                    "node_id": "draft",
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "cache_key": "WRONG-PARENT-DRAFT-KEY",
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "cache_age_sec": 5,
                        "cache_chunks_skipped": [],
                    },
                },
                {
                    "node_id": "call-child",
                    "sub_workflow_events": [
                        {
                            "node_id": "review",
                            "llm_call": {
                                "model": "anthropic/claude-sonnet-4-5",
                                "cache_key": "WRONG-CHILD-REVIEW-KEY",
                                "cache_creation_input_tokens": 100,
                                "cache_read_input_tokens": 0,
                                "cache_age_sec": 5,
                                "cache_chunks_skipped": [],
                            },
                        }
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    cache_db = isolate_pflow_config["pflow_dir"] / "cache" / "cache.db"
    memo_cache = MemoizationCache(db_path=cache_db, read_enabled=True)
    parent_ir = parse_markdown(parent_path.read_text(encoding="utf-8")).ir
    result = analyze(
        parent_ir,
        parameters={"topic": "alpha"},
        workflow_path=str(parent_path.resolve()),
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=memo_cache,
    )
    discrepancies = [d for d in result.warnings if d.id == "cache.discrepancy"]
    nodes_with_discrepancies = sorted(d.node_id for d in discrepancies if d.node_id)
    assert "draft" in nodes_with_discrepancies, f"Expected parent.draft discrepancy; got {nodes_with_discrepancies}"
    assert "review" in nodes_with_discrepancies, f"Expected child.review discrepancy; got {nodes_with_discrepancies}"


# ---------------------------------------------------------------------------
# CP3 (#3) — Sub-path policy: template-honest default + new consolidate advisory
# ---------------------------------------------------------------------------


def test_template_honest_default_keeps_subpaths_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default behavior: sub-paths of a parent dict are NOT auto-collapsed.

    Workflow uses ``${concept.core_idea}`` and ``${concept.title}`` in two
    different LLM nodes. The suggested ## Cache block lists them as TWO
    chunks (one per template reference) — NOT a single ``${concept}`` root.

    Mutation test: if a future contributor adds an "auto-collapse to root"
    branch in ``_collect_llm_template_references`` or
    ``_populate_suggested_blocks``, this test fails because the chunk count
    drops from 2 to 1 and the chunk identifier changes from ``concept.title``
    to ``concept``. The user-facing contract: pflow suggests caching what
    your prompts actually reference; consolidation is opt-in via
    ``cache.consolidate-to-root-recommended``.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 2000)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 1000)
    workflow_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "About: ${concept.core_idea}"},
            },
            {
                "id": "n2",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Title: ${concept.title}, Idea: ${concept.core_idea}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    # ``concept.core_idea`` is shared by both nodes (qualifies for suggestion);
    # ``concept.title`` is used by only n2 (filtered out by ≥2 rule). Result:
    # exactly one suggested chunk — and crucially, that chunk is the SUB-PATH
    # ``concept.core_idea`` not the auto-collapsed root ``concept``.
    assert len(analysis.suggested_blocks) == 1
    chunks = analysis.suggested_blocks[0].chunks
    chunk_names = [c.name for c in chunks]
    assert chunk_names == ["concept.core_idea"], (
        f"Expected template-honest sub-path; got {chunk_names}. Auto-collapse to root would render ['concept'] instead."
    )


def test_subpath_sort_clusters_siblings_by_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sibling sub-paths of the same root cluster contiguously regardless of
    individual share counts.

    Three sub-paths of ``concept`` (each shared by 2+ nodes) plus one
    independent root ``concept_brief`` (also shared). The suggested block
    must put the three ``concept.*`` chunks ADJACENT, not interleave them
    with ``concept_brief``.

    Mutation test: revert the sort key in ``_populate_suggested_blocks`` to
    drop the root-grouping dimension; this test fails because individual
    share counts scatter ``concept.angle`` away from its siblings.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 2000)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 1000)
    workflow_ir = {
        "inputs": {
            "concept": {"type": "object"},
            "concept_brief": {"type": "string"},
        },
        "nodes": [
            # Every node uses concept.core_idea + concept.title + concept.angle
            # (varying share counts) AND concept_brief.
            {
                "id": f"n{i}",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {
                    "prompt": (
                        "${concept.core_idea} ${concept.title} "
                        + ("${concept.angle} " if i < 2 else "")  # only 2 of 3 use .angle
                        + "${concept_brief}"
                    )
                },
            }
            for i in range(3)
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    assert analysis.suggested_blocks
    chunk_names = [c.name for c in analysis.suggested_blocks[0].chunks]
    # All concept.* siblings appear together (no concept_brief between them).
    concept_subpaths = [c for c in chunk_names if c.startswith("concept.")]
    concept_indexes = [chunk_names.index(c) for c in concept_subpaths]
    assert concept_indexes == sorted(concept_indexes), f"Indexes not contiguous: {concept_indexes}"
    assert concept_indexes[-1] - concept_indexes[0] == len(concept_subpaths) - 1, (
        f"concept.* siblings interleaved with non-siblings: {chunk_names}"
    )


def test_consolidate_to_root_advisory_fires_for_brownfield_subpaths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brownfield: workflow declares sub-path chunks individually below the
    min-cache threshold. Advisory fires telling the agent to consolidate.

    Mutation test: remove the ``_consolidate_to_root_advisories`` call from
    ``analyze()`` or revert the threshold check; this test fails because
    the advisory disappears.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    # Lock min-cache threshold deterministically.
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 100)
    # Sub-paths return 5 tokens each; the root returns 200 tokens.
    monkeypatch.setattr(
        analyze_module,
        "_estimate_ref_tokens",
        lambda ref, **_kw: 200 if ref == "concept" else 5,
    )

    workflow_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {"name": "concept.title", "var": "concept.title", "prose_before": "T:\n"},
                {"name": "concept.core_idea", "var": "concept.core_idea", "prose_before": "C:\n"},
            ]
        },
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept.title", "concept.core_idea"],
                "params": {"prompt": "${concept.title} ${concept.core_idea}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.consolidate-to-root-recommended"]
    assert found, f"advisory missing: ids={[d.id for d in analysis.warnings]}"
    ctx = found[0].context
    assert ctx is not None
    assert ctx["root"] == "concept"
    assert sorted(ctx["sub_paths"]) == ["concept.core_idea", "concept.title"]
    assert ctx["max_subpath_tokens"] == 5
    assert ctx["root_tokens"] == 200
    assert ctx["min_tokens"] == 100


def test_consolidate_to_root_advisory_silent_when_subpath_already_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suppression: at least one sub-path is already large enough to cache on
    its own — the agent's declarations work as intended; no advisory.

    Mutation test: remove the ``if max_subpath >= min_tokens: continue``
    guard; this test fails because the advisory fires despite the sub-path
    being self-sufficient.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 100)
    # core_idea = 200 (above threshold); title = 5; root = 300.
    monkeypatch.setattr(
        analyze_module,
        "_estimate_ref_tokens",
        lambda ref, **_kw: {"concept.core_idea": 200, "concept.title": 5, "concept": 300}.get(ref, 1),
    )

    workflow_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {"name": "concept.core_idea", "var": "concept.core_idea", "prose_before": "C:\n"},
                {"name": "concept.title", "var": "concept.title", "prose_before": "T:\n"},
            ]
        },
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept.core_idea", "concept.title"],
                "params": {"prompt": "${concept.core_idea} ${concept.title}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.consolidate-to-root-recommended"]
    assert not found, f"advisory should NOT fire when a sub-path is above threshold; got {found}"


def test_consolidate_to_root_advisory_silent_when_root_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suppression: even the consolidated root would be below threshold —
    consolidation wouldn't help; ``cache.below-min-tokens`` covers this case.

    Mutation test: remove the ``if root_tokens < min_tokens: continue`` guard;
    this test fails because the advisory fires for a useless consolidation.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 100)
    # All sizes below threshold — consolidation wouldn't help.
    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kw: 30)

    workflow_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {"name": "concept.title", "var": "concept.title", "prose_before": "T:\n"},
                {"name": "concept.core_idea", "var": "concept.core_idea", "prose_before": "C:\n"},
            ]
        },
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept.title", "concept.core_idea"],
                "params": {"prompt": "${concept.title} ${concept.core_idea}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.consolidate-to-root-recommended"]
    assert not found


def test_consolidate_to_root_advisory_silent_when_root_already_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suppression: the root is already declared/used directly. Sub-paths
    alongside the root are a redundancy issue, not a consolidation case.

    Mutation test: remove the ``if root in candidate_set: continue`` guard;
    this test fires the advisory for a redundancy that the agent has
    already partly addressed.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 100)
    monkeypatch.setattr(
        analyze_module,
        "_estimate_ref_tokens",
        lambda ref, **_kw: 200 if ref == "concept" else 5,
    )

    # Brownfield with BOTH root and sub-paths declared — no consolidation case.
    workflow_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {"name": "concept", "var": "concept", "prose_before": "Concept:\n"},
                {"name": "concept.title", "var": "concept.title", "prose_before": "T:\n"},
                {"name": "concept.core_idea", "var": "concept.core_idea", "prose_before": "C:\n"},
            ]
        },
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept", "concept.title", "concept.core_idea"],
                "params": {"prompt": "${concept}"},
            },
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.consolidate-to-root-recommended"]
    assert not found


# ---------------------------------------------------------------------------
# cache.heterogeneous-models-fragment-cache — shared chunks across exact models
# cache.first-call-write-penalty — one exact model writes once, never reads
#
# Detector: ``_detect_model_cache_fragmentation`` in ``analyze.py``.
# ---------------------------------------------------------------------------


def test_fragmentation_fires_for_two_exact_models_sharing_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two exact models declare the same cached chunk. The analyzer warns
    because provider cache namespaces do not cross model boundaries.

    Mutation test: remove the ``len(fragmented_groups) >= 2`` emission branch
    in ``_detect_model_cache_fragmentation``; this test fails because the
    warning disappears.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.heterogeneous-models-fragment-cache"]
    assert found, f"fragmentation warning missing: ids={[d.id for d in analysis.warnings]}"
    ctx = found[0].context
    assert ctx is not None
    assert ctx["model_group_count"] == 2
    assert ctx["shared_chunks"] == ["context"]
    assert {g["model"] for g in ctx["model_groups"]} == {
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-5",
    }


def test_fragmentation_silent_when_single_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: same exact model across nodes shares one cache namespace.

    Mutation test: remove the shared-group count guard; this test fails
    because a homogeneous workflow reports false fragmentation.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.heterogeneous-models-fragment-cache" not in {d.id for d in analysis.warnings}


def test_fragmentation_silent_when_no_chunk_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: different models caching disjoint chunks do not fragment
    one cache opportunity; each model owns independent bytes.

    Mutation test: group only by model and ignore ``_model_groups_with_shared_chunks``;
    this test fails because disjoint chunks emit a false warning.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["a"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["b"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"a": "alpha " * 20, "b": "bravo " * 20}, auto_load_trace=False)
    assert "cache.heterogeneous-models-fragment-cache" not in {d.id for d in analysis.warnings}


def test_fragmentation_skips_heterogeneous_batch_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: ``model: ${item.model}`` rows are excluded because one
    per-call row cannot represent the batch's per-item model distribution.

    Mutation test: remove the ``not row.model_is_heterogeneous`` filter; this
    test fails because the literal heterogeneous row joins the grouping pass.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "batch",
                "type": "llm",
                "model": "${item.model}",
                "batch": {"items": [{"model": "anthropic/claude-haiku-4-5"}], "as": "item"},
                "prompt_cache": ["context"],
                "params": {"prompt": "Batch."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.heterogeneous-models-fragment-cache" not in {d.id for d in analysis.warnings}


def test_fragmentation_skips_when_any_group_cost_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: if any participating model lacks pricing, the analyzer
    skips the savings-bearing warning instead of fabricating dollars.

    Mutation test: remove the ``costs is not None`` guard; this test fails
    because an unpriced model still emits a savings warning.
    """
    _patch_pricing(monkeypatch, missing_models={"anthropic/claude-sonnet-4-5"})
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.heterogeneous-models-fragment-cache" not in {d.id for d in analysis.warnings}


def test_fragmentation_skips_when_shared_chunk_tokens_unmeasurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: if any shared chunk has no resolvable token estimate
    (memo miss in pure greenfield), skip the warning instead of summing the
    smallest row's total cacheable count and overstating savings.

    Mutation test: revert ``_compute_model_group_costs`` to use
    ``min(row.cacheable_tokens_estimated)`` per group; this test fails because
    rows have measurable cacheable tokens even when per-chunk estimation is
    blocked, so the old approximation would still emit.
    """
    _patch_pricing(monkeypatch, missing_chunks={"context"})
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.heterogeneous-models-fragment-cache" not in {d.id for d in analysis.warnings}


def test_fragmentation_suppresses_when_only_one_model_group_meets_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single surviving model namespace is not fragmentation.

    Mutation test: revert the ``len(participating_groups) >= 2`` guard after
    threshold filtering; this test fails with either a KeyError or a false
    fragmentation warning.
    """
    _patch_pricing(monkeypatch)
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(
        analyze_module,
        "get_min_cache_tokens",
        lambda model: 10_000 if model == "anthropic/claude-sonnet-4-5" else 10,
    )
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }

    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)

    assert "cache.heterogeneous-models-fragment-cache" not in {d.id for d in analysis.warnings}


def test_write_penalty_fires_for_single_call_with_declared_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lone exact-model group writes cached bytes with no later same-model
    read to amortize the write premium.

    Mutation test: remove the ``len(group_rows) != 1`` emission branch; this
    test fails because the single-call advisory disappears.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            }
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    found = [d for d in analysis.warnings if d.id == "cache.first-call-write-penalty"]
    assert found, f"write-penalty warning missing: ids={[d.id for d in analysis.warnings]}"
    ctx = found[0].context
    assert ctx is not None
    assert found[0].node_id == "draft"
    assert ctx["model"] == "anthropic/claude-haiku-4-5"
    assert ctx["savings_usd"] > 0


def test_write_penalty_silent_when_declared_cache_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """No first-write premium exists when the provider cache cannot fire.

    Mutation test: remove the threshold gate in ``_single_call_write_penalty``;
    this test fails because a below-threshold declaration still reports
    positive savings from removing a write that never happens.
    """
    _patch_pricing(monkeypatch)
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10_000)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            }
        ],
    }

    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)

    assert "cache.first-call-write-penalty" not in {d.id for d in analysis.warnings}


def test_write_penalty_silent_when_group_size_gt_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: two calls to the same exact model can amortize one write.

    Mutation test: remove the group-size guard; this test fails because every
    homogeneous two-node workflow emits noisy single-call advisories.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.first-call-write-penalty" not in {d.id for d in analysis.warnings}


def test_write_penalty_silent_when_prewarm_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: explicit prewarm means the write is intentional and
    amortized through the batch prewarm path.

    Mutation test: remove the ``prewarm is True`` suppression; this test fails
    because opted-in prewarm nodes report a contradictory write penalty.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prewarm": True,
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            }
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.first-call-write-penalty" not in {d.id for d in analysis.warnings}


def test_write_penalty_silent_for_gemini_implicit_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppression: Gemini's implicit cache has no comparable paid first-write
    penalty, so this advisory would be misleading.

    Mutation test: remove the ``model.startswith("gemini/")`` guard; this
    test fails because Gemini emits an Anthropic-shaped write warning.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            }
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    assert "cache.first-call-write-penalty" not in {d.id for d in analysis.warnings}


def test_fragmentation_and_write_penalty_coemit_when_one_group_has_size_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A singleton model group can be both part of cross-model fragmentation
    and a lone-write penalty.

    Mutation test: change the detector to ``elif`` the two checks; this test
    fails because one of the two independent findings disappears.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft."},
            },
            {
                "id": "revise",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Revise."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Review."},
            },
        ],
    }
    analysis = analyze(workflow_ir, parameters={"context": "stable " * 20}, auto_load_trace=False)
    ids = {d.id for d in analysis.warnings}
    assert "cache.heterogeneous-models-fragment-cache" in ids
    assert "cache.first-call-write-penalty" in ids


# ---------------------------------------------------------------------------
# cache.opaque-prompt — LLM nodes whose prompt is a single var-ref to a code node
#
# Detector: ``_opaque_prompt_warnings`` in ``analyze.py``.
# Two patterns trigger:
#   - Direct: ``prompt: ${some_code.result.field}``.
#   - Through batch alias: ``prompt: ${item.X}`` AND
#     ``batch.items: ${some_code.result}``.
# ---------------------------------------------------------------------------


def test_opaque_prompt_fires_on_batch_alias_through_code_node() -> None:
    """Canonical case: LLM batch consumes ``${item.prompt}``; ``batch.items``
    sources from a ``type: code`` node. Static walkers see one ref → silent.
    Detector points the agent at the refactor.

    Mutation test: remove the ``_resolve_through_batch_alias`` indirection in
    ``_opaque_prompt_warnings`` — this test fails because the direct ``root``
    lookup misses (``item`` isn't a node id; it's a batch alias).
    """
    workflow_ir = {
        "nodes": [
            {"id": "prepare-items", "type": "code", "params": {}},
            {
                "id": "process-items",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": "${prepare-items.result}", "as": "item"},
                "params": {"prompt": "${item.prompt}"},
            },
        ]
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.opaque-prompt")
    assert diag.node_id == "process-items"
    assert diag.context is not None
    assert diag.context["var_ref"] == "item.prompt"
    assert diag.context["upstream_node_id"] == "prepare-items"


def test_opaque_prompt_fires_on_direct_code_node_ref() -> None:
    """Direct case: ``prompt: ${some_code.result}`` (no batch indirection).

    Mutation test: drop the direct ``nodes_by_id.get(root)`` lookup in favor
    of the batch-alias indirection only — this test fails because no batch
    alias is involved.
    """
    workflow_ir = {
        "nodes": [
            {"id": "build-prompt", "type": "code", "params": {}},
            {
                "id": "run",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "${build-prompt.result}"},
            },
        ]
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.opaque-prompt")
    assert diag.node_id == "run"
    assert diag.context is not None
    assert diag.context["var_ref"] == "build-prompt.result"
    assert diag.context["upstream_node_id"] == "build-prompt"


def test_opaque_prompt_silent_when_prompt_has_inline_content() -> None:
    """Negative: prompt contains literal bytes alongside ``${...}``. Static
    walkers can already inspect this — the warning would be noise.

    Mutation test (verified): drop the ``is_simple_template`` check in
    ``_opaque_prompt_warnings`` — this test fires because the leading
    ``${build-prompt.result}`` recovers a real root id even when trailing
    text is present, making every "prefix var-ref + literal tail" pattern a
    false positive.
    """
    workflow_ir = {
        "nodes": [
            {"id": "build-prompt", "type": "code", "params": {}},
            {
                "id": "run",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                # Leading ${X} + trailing literal — the shape that recovers a
                # real root id without the gate (see mutation-test docstring).
                "params": {"prompt": "${build-prompt.result} and then some literal text"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.opaque-prompt" not in {d.id for d in result.warnings}


def test_opaque_prompt_silent_when_upstream_is_not_code_node() -> None:
    """Negative: ``${some-llm.response}`` chains an LLM output into another
    LLM call. Different pattern (LLM chaining), different remediation. The
    opaque-prompt detector intentionally narrows to ``type: code`` upstreams.

    Mutation test: drop the ``upstream_node.get("type") != "code"`` check —
    this test fires on legitimate LLM chaining patterns.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Draft something."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "${draft.response}"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.opaque-prompt" not in {d.id for d in result.warnings}


def test_opaque_prompt_silent_when_root_not_in_workflow() -> None:
    """Negative: ``${some-input}`` where ``some-input`` is a workflow input,
    not a node. Workflow inputs are static values agents can already see.

    Mutation test: emit unconditionally when ``upstream_node is None`` —
    this test fires on every prompt that's just a workflow input passthrough.
    """
    workflow_ir = {
        "inputs": {"some-input": {"type": "string"}},
        "nodes": [
            {
                "id": "run",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "${some-input}"},
            },
        ],
    }
    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.opaque-prompt" not in {d.id for d in result.warnings}
