"""Production-shaped emission tests for cache analyzer warning IDs.

Each test drives ``analyze(...)`` end-to-end rather than constructing
Diagnostics directly. Dotted-path references are intentional: prior cache
analysis tests that used only bare inputs missed production bugs around
full-path chunk names.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_analysis.analyze import CrossWorkflowInputContribution, analyze
from pflow.core.cache_analysis.cost_estimation import ModelPricing
from pflow.core.cache_analysis.render_json import render_json
from pflow.core.cache_analysis.render_text import render_text
from pflow.core.file_resolver import resolve_file_references
from pflow.core.markdown_parser import parse_markdown
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult
from pflow.core.workflow.validator import WorkflowValidator


def _iter_llm_events(events: list[dict[str, Any]]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Walk trace events recursively, including cached events.

    Test-only helper. Was previously at ``analyze.py:2991`` with no production
    callers (documented in ``cache_analysis/CLAUDE.md`` as dead production
    code after the per-call rendering migration to
    ``TraceTree.iter_llm_leaves``). Relocated here in the post-review sweep
    since the only consumers are the 2 structural tests in this file.
    """
    from pflow.core.trace_tree import TraceTree

    tree = TraceTree(events=tuple(events), format_version="2.1")
    for leaf in tree.iter_llm_leaves(descend_cached_subtrees=True):
        if leaf.tier == "sub_workflow_descendant":
            yield leaf.event_node_id, dict(leaf.event)
        else:
            yield leaf.owner_node_id, dict(leaf.event)


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


def test_batch_prewarm_recommended_fires_only_when_prewarm_absent(tmp_path: Path) -> None:
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    prefix = "stable " * 100
    workflow_path = str(tmp_path / "batch-prewarm.pflow.md")
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
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=workflow_path,
                nodes=[
                    builder.batch_event(
                        "score",
                        [
                            {
                                "index": index,
                                "success": True,
                                "llm_call": {
                                    "model": "anthropic/claude-sonnet-4-5",
                                    "input_tokens": 200,
                                    "output_tokens": 5,
                                    "total_tokens": 205,
                                    "cost_usd": 0.01,
                                },
                            }
                            for index in range(34)
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )

    result = analyze(workflow_ir, workflow_path=workflow_path, trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.batch-prewarm-recommended")
    assert diag.context is not None
    assert diag.context["batch_size"] == 34
    assert diag.context["prefix_tokens_estimated"] == 100
    assert diag.context["savings_pct"] == 89
    assert "cache.batch-prewarm-lower-bound-recommended" not in {d.id for d in result.warnings}

    workflow_ir["nodes"][0]["prewarm"] = False
    opted_out = analyze(workflow_ir, workflow_path=workflow_path, trace_path=trace_path, memo_cache=None)
    assert "cache.batch-prewarm-recommended" not in {d.id for d in opted_out.warnings}


def test_batch_prewarm_lower_bound_recommended_fires_when_measurable_prefix_clears_min() -> None:
    """Unresolved refs inside the prefix no longer suppress all prewarm advice.

    The measurable stable bytes clear the provider minimum; the unresolved
    upstream ref is named so the agent knows what to verify with ``--report``.
    Mutation contract: restore the exact-or-nothing
    ``prefix_tokens is None -> return []`` gate; this test fails because the
    lower-bound diagnostic disappears.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": "a"}, {"text": "b"}, {"text": "c"}], "as": "item"},
                "params": {"prompt": ("stable " * 20) + "${missing.context}\n${item.text}"},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    warning_ids = {warning.id for warning in result.warnings}
    assert "cache.batch-prewarm-recommended" not in warning_ids
    assert "cache.batch-prewarm-lower-bound-recommended" in warning_ids
    diag = next(warning for warning in result.warnings if warning.id == "cache.batch-prewarm-lower-bound-recommended")
    assert diag.context is not None
    assert diag.context["measurable_tokens"] >= 10
    assert diag.context["unresolved_refs"] == ["missing.context"]
    text = render_text(result)
    assert "savings at least unknown" in text
    assert "--report" in text


def test_batch_prewarm_lower_bound_recommended_silent_when_measurable_prefix_below_min() -> None:
    """A lower-bound below the provider minimum proves no actionable prewarm
    advice yet; unresolved refs may help, but the analyzer cannot count them
    without a real run.

    Mutation contract: emit whenever unresolved refs exist; this test fails
    because the lower-bound diagnostic appears for a sub-threshold prefix.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": "short ${missing.context}\n${item.text}"},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    warning_ids = {warning.id for warning in result.warnings}
    assert "cache.batch-prewarm-lower-bound-recommended" not in warning_ids
    assert "cache.batch-prewarm-recommended" not in warning_ids


def test_batch_prewarm_below_min_fires_when_prefix_truncated_below_provider_min() -> None:
    """Prewarm declared but the static prefix tokenizes below the provider
    minimum — the cache marker will silently no-op at the provider. Fresh
    agent reading ``analyze-cache`` output today sees ``100% cache ratio``;
    this warning is what corrects that.

    Detector reads ``get_min_cache_tokens`` from ``llm_capabilities`` (NOT
    the analyzer-patched stub at 10), so the real Sonnet-4-5 threshold of
    1024 applies. A ~5-token prefix is honestly below it.
    """
    prefix = "tiny "  # 1 word → 1 token under the deterministic word-count tokenizer
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": [{"text": "a"}, {"text": "b"}, {"text": "c"}, {"text": "d"}], "as": "item"},
                "params": {"prompt": prefix + "${item.text}"},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.batch-prewarm-below-min")
    assert diag.context is not None
    assert diag.context["model"] == "anthropic/claude-sonnet-4-5"
    assert diag.context["min_tokens"] == 1024
    assert diag.context["prefix_tokens"] < 1024
    assert diag.context["prefix_tokens"] > 0
    assert diag.context["batch_alias"] == "item"
    # Anthropic provider note flows through to the rendered message.
    assert "cache_control markers" in diag.message


def test_batch_prewarm_below_min_silent_when_prefix_meets_provider_min() -> None:
    """A 2000-token prefix on Sonnet (1024 min) is above the threshold — the
    cache marker will fire at the provider, no warning needed."""
    prefix = "stable " * 2000  # well above 1024 under word-count tokenizer
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": prefix + "${item.text}"},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.batch-prewarm-below-min" not in {d.id for d in result.warnings}


def test_batch_prewarm_below_min_silent_when_prewarm_not_declared() -> None:
    """Without ``prewarm: true``, the boundary-classification check doesn't
    run — this warning is specifically for declared-prewarm batches whose
    prefix won't actually fire."""
    prefix = "tiny "
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": prefix + "${item.text}"},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    assert "cache.batch-prewarm-below-min" not in {d.id for d in result.warnings}


def test_batch_prewarm_below_min_silent_when_first_per_item_at_position_zero() -> None:
    """Position-zero per-item ref is the ``cache.prewarm-no-prefix`` case;
    the two warnings are mutually exclusive on ``first_per_item_position``.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": "${item.text}\nScore this."},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    warning_ids = {d.id for d in result.warnings}
    assert "cache.prewarm-no-prefix" in warning_ids
    assert "cache.batch-prewarm-below-min" not in warning_ids


def test_batch_prewarm_below_min_silent_when_declared_prompt_cache_present() -> None:
    """When ``## Cache`` is declared and the node has ``prompt_cache:``,
    prewarm writes the declared chunk once via the serialized first call.
    The prompt-body prefix length is irrelevant to whether caching fires —
    the declared chunk is what gets cached. ``cache.below-min-tokens``
    handles the declared-cache path (and would fire if the declared chunk
    were below min, which is a separate scenario). The new ID stays silent.
    """
    short_prefix = "tiny "
    workflow_ir = {
        "cache": {"items": [{"name": "ctx", "var_expr": "ctx"}]},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "prompt_cache": ["ctx"],
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": short_prefix + "${item.text}"},
            }
        ],
        "inputs": {"ctx": {"type": "string"}},
    }

    result = analyze(
        workflow_ir,
        parameters={"ctx": "x"},
        workflow_path="x.pflow.md",
        auto_load_trace=False,
        memo_cache=None,
    )
    assert "cache.batch-prewarm-below-min" not in {d.id for d in result.warnings}


def test_inputs_indirection_keeps_batch_prefix_projection_but_suppresses_unmeasurable_recommendation() -> None:
    """Mutation contract: removing prompt-ref dealiasing loses batch_prefix evidence.

    The ranked recommendation is intentionally suppressed in greenfield mode
    because the dynamic tail contains a per-item alias with no representative
    value. The row-level prefix projection still proves dealiasing works.
    """
    fixture = Path(__file__).parents[1] / "fixtures" / "cache_analysis" / "inputs_indirection_batch.pflow.md"
    workflow_ir = parse_markdown(fixture.read_text(encoding="utf-8")).ir

    result = analyze(
        workflow_ir,
        parameters={},
        workflow_path=str(fixture),
        auto_load_trace=False,
        memo_cache=None,
    )

    warning_ids = {warning.id for warning in result.warnings}
    assert "cache.batch-prewarm-recommended" not in warning_ids
    row = next(row for row in result.per_call if row.node_path == "score")
    assert row.cacheable_data_source == "batch_prefix"
    assert row.cacheable_tokens_estimated is not None
    assert row.cacheable_tokens_estimated > 0


def test_batch_static_tail_after_dynamic_emits_recommended_action() -> None:
    stable_tail = "rubric " * 20
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": "a"}, {"text": "b"}, {"text": "c"}], "as": "item"},
                "params": {"prompt": f"${{item.text}}\n{stable_tail}"},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.dynamic-before-static")
    assert diag.context is not None
    assert diag.context["dynamic_ref"] == "item.text"
    assert diag.context["affected_calls"] == 3
    assert diag.context["detection_mode"] == "batch_static_tail"
    rendered = render_text(result, all_rows=True)
    assert "## Recommended actions" in rendered
    assert "Dynamic ref blocks caching on score" in rendered


def test_batch_static_tail_after_dynamic_matches_alias_bracket_form() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [[{"text": "a"}], [{"text": "b"}]], "as": "item"},
                "params": {"prompt": "${item[0].text}\n" + ("rubric " * 20)},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.dynamic-before-static")
    assert diag.context is not None
    assert diag.context["dynamic_ref"] == "item[0].text"


def test_batch_static_tail_after_dynamic_suppresses_below_threshold() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": "${item.text}\n" + ("rubric " * 5)},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)

    assert "cache.dynamic-before-static" not in {d.id for d in result.warnings}


def test_batch_static_tail_after_dynamic_does_not_count_later_template_refs_as_stable() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": [{"text": "a"}, {"text": "b"}], "as": "item"},
                "params": {"prompt": "${item.text}\n" + ("small " * 5) + "${item.other}\n" + ("tiny " * 4)},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)

    assert "cache.dynamic-before-static" not in {d.id for d in result.warnings}


def test_dynamic_before_static_not_guessed_for_repeated_non_batch_shape() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "select",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "${context}\n" + ("stable judging rubric " * 20)},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)

    assert "cache.dynamic-before-static" not in {d.id for d in result.warnings}


def test_dynamic_before_static_uses_full_path_cache_names(tmp_path: Path) -> None:
    """Mutation contract: comparing only root names treats the declared
    ``creative-direction.response`` chunk as dynamic. The memo entry is
    load-bearing after honest-region tokenization: without it the suffix is
    unmeasurable and the warning correctly suppresses instead of fabricating
    literal ``${creative-direction.response}`` bytes.
    """
    from pflow.runtime.cache import MemoizationCache

    stable_suffix = "rubric " * 50
    memo_cache = MemoizationCache(db_path=tmp_path / "cache.db")
    memo_cache.put(
        cache_key="creative-direction-key",
        node_id="creative-direction",
        workflow_path="x.pflow.md",
        action="default",
        output={"response": "resolved direction " * 5000},
    )
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

    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=memo_cache)
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


def test_dynamic_before_static_treats_indirected_declared_chunk_as_static() -> None:
    """Mutation contract: comparing raw prompt aliases to declared chunks emits a false warning."""
    workflow_ir = {
        "cache": {"items": [{"name": "extract.response", "var": "extract.response", "prose_before": "Extract:\n"}]},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["extract.response"],
                "params": {
                    "inputs": {"data": "${extract.response}"},
                    "prompt": "${data}\n" + ("stable " * 60),
                },
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
    assert diag.context["child_workflow"] == "<inline>"
    assert diag.context["child_workflow_basename"] == "<inline>"
    assert diag.context["affected_input_count"] == 1
    assert diag.context["affected_workflow"] == "<inline>"
    input_info = diag.context["inputs"][0]
    assert input_info["parent_workflow"] == "parent.pflow.md"
    assert input_info["parent_value_expr"] == "creative.direction"
    assert input_info["child_input_name"] == "direction"
    assert input_info["consumer_node_ids_csv"] == "`use-input`, `review-input`"
    assert diag.context["case"] == "refactor"
    assert "Monitor:" in diag.message
    # N-7 honest-unmeasurable: no memo, no trace, model unpriced. ``savings_usd``
    # MUST be None — never fabricate. Mutation contract: change
    # ``_project_sub_workflow_cache_savings`` to return ``0.0`` instead of None
    # when grounding is missing → this fails.
    assert diag.context["savings_usd"] is None


def test_sub_workflow_cache_undeclared_savings_populated_from_memo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-7 (Cluster C): when the parent's value lives in memo and the affected
    child rows are priced, ``savings_usd`` projects a positive figure.

    Mutation contract: revert ``_project_sub_workflow_cache_savings`` to always
    return None → this fails.
    """
    from pflow.runtime.cache import MemoizationCache

    # The autouse ``deterministic_tokens`` fixture patches ``_input_rate`` to
    # always return None for determinism — override locally to exercise the
    # priced path. Mirrors the pattern at line 178 etc.
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${creative.direction}"}},
            },
        ]
    }
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    # Seed memo for the parent's flowing value. The ref ``creative.direction``
    # roots on node id ``creative``; the analyzer's memo lookup retrieves the
    # full output dict and applies the dotted-path tail.
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        cache_key="creative-key",
        node_id="creative",
        workflow_path="parent.pflow.md",
        action="default",
        output={"direction": "shared concept content " * 200},
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=cache)
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0


def test_sub_workflow_cache_undeclared_savings_populated_from_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-7 (Cluster C): when memo is empty but trace recorded the parent's
    output, the analyzer falls back to trace data for the token estimate. This
    closes the first-encounter case (agent runs ``pflow analyze-cache --from-trace``
    without prior ``pflow run`` to populate memo).

    Mutation contract: drop the trace fallback in ``_estimate_parent_value_tokens``
    → this fails (savings drops to None because memo is empty).
    """
    # See sibling test for the rationale on overriding the autouse fixture.
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${creative.direction}"}},
            },
        ]
    }
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    # Synthetic trace with the parent's recorded ``node_output`` for ``creative``
    # under the parent workflow path. The analyzer's trace-fallback walker
    # filters on ``(workflow_path, node_id)`` to find this event.
    import json as _json
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = Path(tmpdir) / "trace.json"
        trace_path.write_text(
            _json.dumps({
                "format_version": "2.2.0",
                "workflow_path": "parent.pflow.md",
                "final_status": "success",
                "nodes": [
                    {
                        "node_id": "creative",
                        "node_type": "LLMNode",
                        "node_output": {"direction": "shared concept content " * 200},
                        "duration_ms": 100,
                        "success": True,
                        "cached": False,
                    },
                    {
                        "node_id": "child-call",
                        "node_type": "WorkflowNode",
                        "duration_ms": 200,
                        "success": True,
                        "cached": False,
                        "sub_workflow_events": [
                            {
                                "node_id": "draft",
                                "llm_call": {
                                    "model": "gemini/gemini-2.5-flash",
                                    "input_tokens": 100,
                                    "output_tokens": 1,
                                },
                            },
                            {
                                "node_id": "review",
                                "llm_call": {
                                    "model": "gemini/gemini-2.5-flash",
                                    "input_tokens": 100,
                                    "output_tokens": 1,
                                },
                            },
                        ],
                    },
                ],
            }),
            encoding="utf-8",
        )

        result = analyze(
            parent_ir,
            workflow_path="parent.pflow.md",
            auto_load_trace=False,
            memo_cache=None,
            trace_path=trace_path,
        )
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0


def test_sub_workflow_cache_undeclared_savings_populated_from_workflow_node_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-7 follow-up: when the parent value is a workflow-input passthrough
    (e.g. ``${concept}`` where ``concept`` is the parent's own workflow
    input rather than a node output), neither memo nor the by-node-id trace
    walker finds the value — there is no node in the parent that produces
    ``concept``. The resolved value is recorded on the parent's workflow-node
    event under ``node_params['inputs'][child_input_name]`` (engine flow:
    ``node.params = merged_params`` after ``resolve_templates``, then
    ``record_trace(node.params)``). This closes the lyrics-generator canonical
    case where ``concept`` flows parent → child → grandchild as an input.

    Mutation contract: drop the third tier in ``_estimate_parent_value_tokens``
    (the ``_resolve_input_at_workflow_node_invocation`` call) → this fails
    (savings drops to None because no node id ``concept`` exists for Tier 2 to
    walk to, and no memo is provided).
    """
    # See sibling test for the rationale on overriding the autouse fixture.
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            },
        ],
        # Declare ``concept`` as a workflow input so the parent_value_expr
        # ``concept`` doesn't accidentally root on a same-named node.
        "inputs": {"concept": {"type": "string"}},
    }
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    # Synthetic trace shaped like a real workflow-input passthrough:
    # the parent has a child-call workflow node whose ``node_params['inputs']``
    # carries the resolved value for ``concept``. Crucially, NO event for a
    # node id ``concept`` exists — that's the whole point: input passthrough
    # means the value isn't a node output, so Tier 2 cannot find it.
    import json as _json
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = Path(tmpdir) / "trace.json"
        trace_path.write_text(
            _json.dumps({
                "format_version": "2.2.0",
                "workflow_path": "parent.pflow.md",
                "final_status": "success",
                "nodes": [
                    {
                        "node_id": "child-call",
                        "node_type": "WorkflowExecutor",
                        "duration_ms": 100,
                        "success": True,
                        "cached": False,
                        # Engine records ``node.params`` post-template-resolution.
                        # The resolved value of ${concept} lives here, keyed by
                        # the child input name (``concept``).
                        "node_params": {
                            "workflow": "./child.pflow.md",
                            "inputs": {"concept": "shared concept content " * 200},
                        },
                        "sub_workflow_events": [
                            {
                                "node_id": "draft",
                                "llm_call": {
                                    "model": "gemini/gemini-2.5-flash",
                                    "input_tokens": 100,
                                    "output_tokens": 1,
                                },
                            },
                            {
                                "node_id": "review",
                                "llm_call": {
                                    "model": "gemini/gemini-2.5-flash",
                                    "input_tokens": 100,
                                    "output_tokens": 1,
                                },
                            },
                        ],
                    },
                ],
            }),
            encoding="utf-8",
        )

        result = analyze(
            parent_ir,
            workflow_path="parent.pflow.md",
            auto_load_trace=False,
            memo_cache=None,
            trace_path=trace_path,
        )
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0


def test_sub_workflow_cache_undeclared_savings_none_when_unpriced_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-7 honest-unmeasurable: even with memo populated, an unpriced model
    means we can't compute savings. Returns None — never fabricate.

    The autouse ``deterministic_tokens`` fixture patches ``_input_rate`` to
    always return None, simulating an unpriced model regardless of the
    declared name. The mutation contract: drop the ``if rate is None: return
    None`` guard in ``_estimate_token_savings_usd`` → this fails.
    """
    from pflow.runtime.cache import MemoizationCache

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${creative.direction}"}},
            },
        ]
    }
    # ``mock-fake-model`` is intentionally absent from LiteLLM's pricing table.
    child_ir = {
        "nodes": [
            {"id": "draft", "type": "llm", "model": "mock-fake-model", "params": {"prompt": "Draft ${concept}"}},
            {"id": "review", "type": "llm", "model": "mock-fake-model", "params": {"prompt": "Review ${concept}"}},
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        cache_key="creative-key",
        node_id="creative",
        workflow_path="parent.pflow.md",
        action="default",
        output={"direction": "shared concept content " * 200},
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=cache)
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is None


def test_sub_workflow_cache_undeclared_savings_populated_from_workflow_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 0: current workflow parameters estimate sub-workflow boundary tokens.

    No trace or memo entry is needed. Mutation contract: drop the
    ``_resolve_value_in_workflow_parameters`` call from
    ``_estimate_parent_value_tokens`` and this falls back to unavailable
    savings.
    """
    from pflow.runtime.cache import MemoizationCache

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
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
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        parameters={"concept": "shared concept content " * 200},
        auto_load_trace=False,
        memo_cache=MemoizationCache(db_path=tmp_path / "cache.db"),
    )
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0
    assert diag.context["case"] == "actionable"


def test_sub_workflow_cache_undeclared_parameters_win_over_memo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current parameters must beat stale memo for the same input root."""
    from pflow.runtime.cache import MemoizationCache

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
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
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        cache_key="concept-key",
        node_id="concept",
        workflow_path="parent.pflow.md",
        action="default",
        output={"response": "short"},
    )

    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        parameters={"concept": "long current content " * 500},
        auto_load_trace=False,
        memo_cache=cache,
    )
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    # The short memo value would produce a tiny figure. This locks the tier
    # order to "parameters before memo" without depending on exact pricing
    # implementation details beyond the local _input_rate patch.
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 1000.0


def test_sub_workflow_cache_undeclared_savings_populated_via_walker_propagated_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 0 uses walker-propagated parameters for non-root boundaries."""
    from pflow.runtime.cache import MemoizationCache

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    root_ir = {
        "inputs": {"shared": {"type": "string"}},
        "nodes": [
            {
                "id": "call-middle",
                "type": "workflow",
                "params": {"workflow": "./middle.pflow.md", "inputs": {"shared": "${shared}"}},
            },
        ],
    }
    middle_ir = {
        "inputs": {"shared": {"type": "string"}},
        "nodes": [
            {
                "id": "call-leaf",
                "type": "workflow",
                "params": {"workflow": "./leaf.pflow.md", "inputs": {"shared": "${shared}"}},
            },
        ],
    }
    leaf_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${shared}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${shared}"},
            },
        ],
    }

    def fake_resolve(params: dict[str, Any], _base_path: Path | None) -> SubWorkflowResult:
        workflow = params.get("workflow")
        if workflow == "./middle.pflow.md":
            return SubWorkflowResult(middle_ir, Path("/abs/middle.pflow.md"), ())
        if workflow == "./leaf.pflow.md":
            return SubWorkflowResult(leaf_ir, Path("/abs/leaf.pflow.md"), ())
        raise AssertionError(f"unexpected workflow path {workflow!r}")

    monkeypatch.setattr(cross_module, "resolve_sub_workflow", fake_resolve)

    result = analyze(
        root_ir,
        workflow_path="root.pflow.md",
        parameters={"shared": "propagated shared content " * 200},
        auto_load_trace=False,
        memo_cache=MemoizationCache(db_path=tmp_path / "cache.db"),
    )
    matching = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert len(matching) == 1
    diag = matching[0]
    assert diag.context is not None
    assert diag.context["inputs"][0]["parent_workflow"] == "/abs/middle.pflow.md"
    assert diag.context["child_workflow"] == "/abs/leaf.pflow.md"
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0


def test_sub_workflow_cache_undeclared_below_threshold_warns_and_drops_savings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the parent value's tokens are definitively below the child model's
    minimum cache threshold, declaring the chunk as-recommended wouldn't
    activate caching. The diagnostic surfaces a body-prose warning AND drops
    ``savings_usd`` to None — declaring the chunk alone is a dead-end action;
    the agent needs to declare AND increase content.

    Mutation contract: drop the threshold check in ``_below_threshold_clause``
    (e.g., return ``""`` unconditionally) → this fails (clause becomes empty,
    savings populates instead of None).
    """
    from pflow.runtime.cache import MemoizationCache

    # Override the autouse ``deterministic_tokens`` fixture: it patches
    # ``_input_rate`` to None (we need priced path so the threshold guard is
    # the SOLE reason savings is None) and ``get_min_cache_tokens`` to 10
    # (we need a value larger than the fixture's tokenized size so 200 tokens
    # are below threshold).
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 1000)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${creative.direction}"}},
            },
        ]
    }
    # ``"shared " * 200`` → 200 tokens under the autouse word-count tokenizer.
    # With the threshold raised to 1000 above, 200 < 1000 → below-threshold
    # path fires.
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        cache_key="creative-key",
        node_id="creative",
        workflow_path="parent.pflow.md",
        action="default",
        output={"direction": "shared " * 200},
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=cache)
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    # Savings dropped because caching won't fire as-stated — content is below threshold.
    assert diag.context["savings_usd"] is None
    assert diag.context["case"] == "refactor"
    # Rendered message includes plain-English threshold context so text consumers see it.
    assert "below" in diag.message
    assert "minimum" in diag.message


def test_sub_workflow_cache_undeclared_above_threshold_keeps_savings_and_no_clause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion to the below-threshold test: when content clears the model's
    minimum cache threshold, savings populates and the warning clause stays
    empty. This locks the threshold check's positive branch.

    Mutation contract: invert the threshold comparison (``tokens < threshold``
    → ``tokens >= threshold``) → this fails (clause becomes non-empty,
    savings drops to None).
    """
    from pflow.runtime.cache import MemoizationCache

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${creative.direction}"}},
            },
        ]
    }
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        cache_key="creative-key",
        node_id="creative",
        workflow_path="parent.pflow.md",
        action="default",
        # ~600 word-tokens under the autouse tokenizer; default autouse
        # threshold (10) is well below this so the threshold check passes.
        output={"direction": "shared concept content " * 200},
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=cache)
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0
    assert diag.context["case"] == "actionable"
    # No warning prose leaked into the rendered message.
    assert "below" not in diag.message


def test_sub_workflow_cache_undeclared_unmeasurable_keeps_clause_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the parent value is unmeasurable (memo + trace + invocation site
    all empty), preserve the existing ``"savings unavailable"`` rendering —
    don't attach a threshold warning we can't substantiate. Honest unmeasurable:
    only emit the warning when there is positive evidence the cache won't fire.

    Mutation contract: emit the threshold clause unconditionally (drop the
    ``tokens is None`` guard in ``_below_threshold_clause``) → this fails (the
    empty-clause assertion below trips).
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${creative.direction}"}},
            },
        ]
    }
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    # No memo, no trace, no parent invocation site → tokens is None.
    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is None
    assert diag.context["case"] == "refactor"
    # Existing rendering preserved: the body message has no threshold warning.
    assert "Monitor:" in diag.message


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
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept}"},
            },
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
    assert found[0].context["inputs"][0]["parent_value_expr"] == "item.concept"
    assert found[0].context["inputs"][0]["child_input_name"] == "concept"
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
    assert all(d.context and d.context["inputs"][0]["child_input_name"] == "concept_brief" for d in matching)


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
    assert [d.context["inputs"][0]["child_input_name"] for d in matching if d.context] == ["title", "core_idea"]


def test_parent_cache_declaration_does_not_suppress_child_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent ## Cache blocks are not inherited by sub-workflows."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "ir_version": "0.1.0",
        # Declare ``concept`` as a workflow input so the ## Cache chunk
        # resolves cleanly. Without this, the un-IDed cache resolution
        # validator would emit an additional diagnostic that analyze-cache
        # now correctly surfaces (per spec § "Validation Location").
        "inputs": {"concept": {"type": "string"}},
        "cache": {
            "ttl": "5m",
            "items": [
                {
                    # Parser invariant: ``name == var`` (both bare; no
                    # ``${}`` wrapping). See ``markdown_parser._build_cache_dict``.
                    "name": "concept",
                    "var": "concept",
                    "prose_before": "The concept",
                    "_source_line": 1,
                }
            ],
        },
        "nodes": [
            {
                "id": "use-it",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {
                    "model": "anthropic/claude-haiku-4-5",
                    "prompt": "Use ${concept}",
                },
            },
            {
                "id": "child-call",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            },
        ],
    }
    child_ir = {
        "ir_version": "0.1.0",
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "use-concept",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-haiku-4-5",
                    "prompt": "Use ${concept}",
                },
            },
            {
                "id": "review-concept",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-haiku-4-5",
                    "prompt": "Review ${concept}",
                },
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
    assert found[0].context["inputs"][0]["child_input_name"] == "concept"
    from pflow.core.cache_analysis.render_json import render_json

    payload = render_json(result)
    warning = next(w for w in payload["warnings"] if w.get("id") == "cache.sub-workflow-cache-undeclared")
    assert warning["suggestions"] == ["Edit: /abs/child.pflow.md"]
    assert any("Cross-workflow projections require trace evidence" in note for note in result.notes)


def test_cross_workflow_projection_populates_row_and_recommendation_for_single_consumer_many_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trace-backed total invocations, not structural consumer count, gates the
    row projection and the matching recommendation.

    Mutation contract: restore the old ``len(child_node_ids) >= 2`` gate in
    the recommendation constructor or remove the row candidate builder; this
    test fails because a 1-consumer/2-call boundary either loses the
    recommendation or falls back to unavailable per-call attribution.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "use-concept",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Use ${concept}"},
            }
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_type": "WorkflowExecutor",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"concept": "shared concept content " * 20},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "use-concept",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 1,
                            },
                        },
                        {
                            "node_id": "use-concept",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 1,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    row = next(
        row for row in result.per_call if row.workflow_path == str(child_path) and row.node_path == "use-concept"
    )
    assert row.cacheable_data_source == "cross_workflow_projection"
    assert row.cacheable_tokens_estimated == 60
    assert row.cross_workflow_inputs == (
        CrossWorkflowInputContribution(
            child_input_name="concept",
            tokens_per_call=60,
            model="anthropic/claude-haiku-4-5",
            parent_value_expr="concept",
        ),
    )
    assert any(d.id == "cache.sub-workflow-cache-undeclared" for d in result.warnings)


def test_cross_workflow_projection_sums_multiple_inputs_on_one_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple undeclared cross-workflow inputs are independent prefix chunks;
    the row should show their per-call sum.

    Mutation contract: change the row projection combinator from ``sum`` to
    ``max``; this test fails because the row drops from 50 to 30 tokens.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"a": "${a}", "b": "${b}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${a} and ${b}"},
            }
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"a": "alpha " * 30, "b": "beta " * 20},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "review",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 200,
                                "output_tokens": 1,
                            },
                        },
                        {
                            "node_id": "review",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 200,
                                "output_tokens": 1,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    row = next(row for row in result.per_call if row.workflow_path == str(child_path) and row.node_path == "review")
    assert row.cacheable_data_source == "cross_workflow_projection"
    assert row.cacheable_tokens_estimated == 50
    assert row.cross_workflow_inputs == (
        CrossWorkflowInputContribution(
            child_input_name="a", tokens_per_call=30, model="anthropic/claude-haiku-4-5", parent_value_expr="a"
        ),
        CrossWorkflowInputContribution(
            child_input_name="b", tokens_per_call=20, model="anthropic/claude-haiku-4-5", parent_value_expr="b"
        ),
    )


def test_cross_workflow_projection_skips_unreached_conditional_consumer_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aggregate boundary reuse can pass even when one consumer is unreached,
    but only rows observed in the trace should show cross-workflow projections.

    Mutation contract: append the row candidate to every structural consumer
    instead of only observed consumers; this test fails because the unreached
    ``review`` row claims a ``could_cache`` value for a branch that did not run.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept}"},
            },
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_type": "WorkflowExecutor",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"concept": "shared concept content " * 20},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "draft",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 1,
                            },
                        },
                        {
                            "node_id": "draft",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 1,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    draft = next(row for row in result.per_call if row.workflow_path == str(child_path) and row.node_path == "draft")
    review = next(row for row in result.per_call if row.workflow_path == str(child_path) and row.node_path == "review")
    assert draft.cacheable_data_source == "cross_workflow_projection"
    assert draft.cacheable_tokens_estimated == 60
    assert review.did_not_execute_in_trace is True
    assert review.cacheable_data_source != "cross_workflow_projection"
    assert review.cross_workflow_inputs == ()


def test_cross_workflow_projection_uses_strictest_child_model_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A boundary must clear the strictest provider minimum across child
    consumers before any row claims a cross-workflow projection.

    Mutation contract: change the threshold gate from ``max(child_models)`` to
    the first child model; this test fails because the low-threshold first node
    admits a projection that the stricter second node could not cache.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda model: 100 if model == "strict/model" else 10)
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {"id": "draft", "type": "llm", "model": "low/model", "params": {"prompt": "Draft ${concept}"}},
            {"id": "review", "type": "llm", "model": "strict/model", "params": {"prompt": "Review ${concept}"}},
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_type": "WorkflowExecutor",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"concept": "short shared content " * 10},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "draft",
                            "llm_call": {"model": "low/model", "input_tokens": 100, "output_tokens": 1},
                        },
                        {
                            "node_id": "review",
                            "llm_call": {"model": "strict/model", "input_tokens": 100, "output_tokens": 1},
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    child_rows = [row for row in result.per_call if row.workflow_path == str(child_path)]
    assert {row.node_path for row in child_rows} == {"draft", "review"}
    assert all(row.cacheable_data_source != "cross_workflow_projection" for row in child_rows)


def test_sub_workflow_cache_undeclared_groups_multiple_inputs_per_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two undeclared inputs into one child should produce one grouped action.

    Mutation contract: restore per-input emission and this test fails with two
    diagnostics instead of one child-scoped diagnostic.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"a": "${a}", "b": "${b}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${a} and ${b}"},
            }
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module, "resolve_sub_workflow", lambda _p, _b: SubWorkflowResult(child_ir, child_path, ())
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"a": "alpha " * 30, "b": "beta " * 20},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "review",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 200,
                                "output_tokens": 1,
                            },
                        },
                        {
                            "node_id": "review",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 200,
                                "output_tokens": 1,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    diagnostics = [d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared"]
    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.context is not None
    assert diag.context["affected_input_count"] == 2
    assert diag.context["case"] == "actionable"
    assert [item["child_input_name"] for item in diag.context["inputs"]] == ["a", "b"]
    assert "Two values flow in" in diag.message


def test_sub_workflow_cache_undeclared_case_model_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-call cache prefix above 1,024 but below the current model threshold
    gets model-switch guidance, not a misleading unavailable-savings dead end.

    Mutation contract: revert to cohort-total threshold gating (per_call x
    call_count) and this test still passes (cohort > 1024 < 2000), but the
    sibling ``test_sub_workflow_case_uses_per_call_not_cohort`` fails because
    it engineers a case where per-call < 1024 but cohort > 1024.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 2000)
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"a": "${a}", "b": "${b}"}},
            }
        ],
    }
    child_ir = {
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${a} ${b}"},
            }
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )
    trace_path = tmp_path / "trace.json"
    # Two inputs sized so per-call sum lands between 1024 (MODEL_SWITCH_BAND)
    # and 2000 (mocked strictest threshold). 1500 reps x "alpha " ≈ 1500 tokens
    # each input → ~3000 tokens per call → model_switch range.
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"a": "alpha " * 750, "b": "beta " * 750},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "review",
                            "llm_call": {"model": "gemini/gemini-2.5-flash", "input_tokens": 200, "output_tokens": 1},
                        },
                        {
                            "node_id": "review",
                            "llm_call": {"model": "gemini/gemini-2.5-flash", "input_tokens": 200, "output_tokens": 1},
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    # Override the mocked threshold for THIS test so the per-call prefix lands
    # in the model_switch band [1024, threshold). Set threshold = 4096.
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 4096)

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["case"] == "model_switch"
    assert diag.context["savings_usd"] is None
    assert "Switch model" in diag.message
    assert "anthropic/claude-sonnet-4-5" in diag.message


def test_sub_workflow_cache_undeclared_case_uses_per_call_not_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The threshold gate compares PER-CALL cache prefix bytes, NOT cohort.

    pflow emits one cache_control marker on the last cached block per call.
    The provider checks ``min_cache_tokens`` against the per-call prefix —
    multiplying by call count doesn't help the provider activate caching.

    Regression: an earlier implementation stored ``per_call x call_count`` as
    ``cumulative_tokens`` and gated on it, silently misclassifying low-per-call
    high-call-count cases as ``actionable`` or ``model_switch`` when caching
    won't actually fire.

    Mutation contract: switch the gate back to cohort x call_count (multiply
    per_call_prefix_tokens by call count before comparing to threshold) and
    this test fails with case=actionable/model_switch instead of refactor.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    # Threshold = 4096, MODEL_SWITCH_BAND = 1024.
    # We engineer: per-call ~500 tokens (below 1024 → refactor under correct math),
    # 10 calls in trace → cohort ~5000 (above 4096 → buggy "actionable").
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 4096)
    parent_ir = {
        "inputs": {"a": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"a": "${a}"}},
            }
        ],
    }
    child_ir = {
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${a}"},
            }
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )
    # ~250 reps x "alpha " is ~250-300 tokens per call (below 1024). 10 trace
    # events give cohort ~2500-3000 (above 1024, would falsely trigger
    # model_switch under cohort gating).
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"a": "alpha " * 250},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "review",
                            "llm_call": {"model": "gemini/gemini-2.5-flash", "input_tokens": 300, "output_tokens": 1},
                        }
                    ]
                    * 10,
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    # Per-call ~250-300 tokens; threshold 4096; MODEL_SWITCH_BAND 1024.
    # Correct classification: per_call < 1024 → refactor.
    # Buggy (cohort) classification: per_call * 10 > 1024 → model_switch.
    assert diag.context["case"] == "refactor", (
        f"Expected refactor (per-call check), got {diag.context['case']}. "
        "The threshold gate is using cohort tokens instead of per-call prefix."
    )
    assert diag.context["savings_usd"] is None


def test_sub_workflow_cache_undeclared_case_unmeasurable_no_resolved_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If no child consumer model resolves, the recommendation should say so."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
        "inputs": {"concept": {"type": "string"}},
    }
    child_ir = {
        "nodes": [
            {"id": "draft", "type": "llm", "model": "${model}", "params": {"prompt": "Draft ${concept}"}},
            {"id": "review", "type": "llm", "model": "${model}", "params": {"prompt": "Review ${concept}"}},
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["case"] == "unmeasurable"
    assert "no consumer node has a resolved model" in diag.message


def test_sub_workflow_cache_undeclared_emits_cleanup_hint_when_body_uses_subpath(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subpath body refs would shadow the newly declared child cache chunk, so
    the recommendation must tell the agent what to clean before declaring.

    Mutation contract: remove ``cleanup_hint_clause`` construction or drop the
    "OR rewrite to literal text" alternative; this test fails on the rendered
    context strings.
    """
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
        "inputs": {"concept": {"type": "object"}},
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept.title}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept.core_idea}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        parameters={"concept": {"title": "title " * 100, "core_idea": "idea " * 100}},
        auto_load_trace=False,
        memo_cache=None,
    )

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert "Prompt-body templates to remove and per-consumer cache prefix" in diag.message
    assert "`${concept.title}`" in diag.message
    assert "`${concept.core_idea}`" in diag.message
    assert [item["child_input_name"] for item in diag.context["inputs"]] == ["concept", "concept"]
    assert [item["child_cache_ref"] for item in diag.context["inputs"]] == [
        "concept.core_idea",
        "concept.title",
    ]
    refs_by_cache_ref = {item["child_cache_ref"]: item["template_var_refs_by_node"] for item in diag.context["inputs"]}
    assert refs_by_cache_ref == {
        "concept.core_idea": {"review": ["concept.core_idea"]},
        "concept.title": {"draft": ["concept.title"]},
    }
    text = render_text(result)
    assert "Do not cache full objects like `concept`" in text
    assert "${concept.title}" in text
    assert "${concept.core_idea}" in text
    assert "`${concept}`" not in text


def test_sub_workflow_cache_undeclared_direct_root_use_remains_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct root prompt use still recommends the child input root."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {"id": "draft", "type": "llm", "params": {"prompt": "Draft ${concept}"}},
            {"id": "review", "type": "llm", "params": {"prompt": "Review ${concept}"}},
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert [item["child_cache_ref"] for item in diag.context["inputs"]] == ["concept"]
    assert [item["parent_cache_ref"] for item in diag.context["inputs"]] == ["concept"]
    assert "Do not cache full objects" not in render_text(result)


def test_sub_workflow_cache_candidate_carries_parent_prose_from_matching_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parent prose is copied only when the parent chunk name exactly matches."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_prose = "Concept brief:\nUse the palette and narrator framing from the parent workflow.\n"
    parent_ir = {
        "inputs": {"concept_brief": {"type": "string"}},
        "cache": {"items": [{"name": "concept_brief", "var": "concept_brief", "prose_before": parent_prose}]},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept_brief": "${concept_brief}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept_brief": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept_brief}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept_brief}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    input_info = diag.context["inputs"][0]
    # JSON-side context keeps the full untruncated parent prose so machine
    # consumers can compare bytes against the parent's `## Cache` block.
    assert input_info["parent_prose"] == parent_prose
    assert input_info["parent_prose_origins_differ"] is False
    text = render_text(result)
    # Text rendering shows a 40-char single-line preview, then a blank line,
    # then the `${var}` line. Mutation contracts:
    #   * Drop truncation in `_exact_child_cache_block_content` and the
    #     untruncated suffix "framing from the parent workflow." reappears.
    #   * Re-introduce the blank-line filter in `_indent_message` and the
    #     prose-to-var blank line disappears (regex fails).
    assert "Concept brief: Use the palette and" in text
    assert "framing from the parent workflow." not in text
    assert re.search(
        r"Concept brief: Use the palette and[^\n]*\.\.\.\n\s*\n\s*\$\{concept_brief\}",
        text,
    )
    assert "parent_prose" not in text


def test_sub_workflow_cache_candidate_omits_parent_prose_for_subpath_when_parent_caches_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root parent prose must not be copied onto a narrower child subpath."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {
                    "name": "concept",
                    "var": "concept",
                    "prose_before": "The full concept object, including fields the child does not use:\n",
                }
            ]
        },
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept.core_idea}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept.core_idea}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        parameters={"concept": {"core_idea": "idea " * 400, "unused": "unused " * 400}},
        auto_load_trace=False,
        memo_cache=None,
    )

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    input_info = diag.context["inputs"][0]
    assert input_info["child_cache_ref"] == "concept.core_idea"
    assert input_info["parent_cache_ref"] == "concept.core_idea"
    assert input_info["parent_prose"] == ""
    assert "The full concept object" not in render_text(result)


def test_sub_workflow_cache_candidate_omits_prose_when_multiple_origins_disagree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguous parent prose is flagged in JSON instead of choosing a winner."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept_a": {"type": "string"}, "concept_b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "concept_a", "var": "concept_a", "prose_before": "Concept A:\n"},
                {"name": "concept_b", "var": "concept_b", "prose_before": "Concept B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "call-child-a",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept_a}"}},
            },
            {
                "id": "call-child-b",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept_b}"}},
            },
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
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

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    input_info = diag.context["inputs"][0]
    assert input_info["parent_prose"] == ""
    assert input_info["parent_prose_origins_differ"] is True
    text = render_text(result)
    assert "Concept A" not in text
    assert "Concept B" not in text


def test_sub_workflow_cache_undeclared_mixed_root_and_subpath_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Root use by one node must not collapse a subpath-only node to root."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "headline",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Headline ${concept.title}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    by_ref = {item["child_cache_ref"]: item for item in diag.context["inputs"]}
    assert sorted(by_ref) == ["concept", "concept.title"]
    assert by_ref["concept"]["consumer_node_ids"] == ["draft"]
    assert by_ref["concept.title"]["consumer_node_ids"] == ["headline"]


def test_sub_workflow_cache_undeclared_maps_renamed_parent_subpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent-side token resolution follows the child suffix through renames."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"song": {"type": "object"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${song.concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept.title}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept.title}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        parameters={"song": {"concept": {"title": "title " * 30, "unused": "unused " * 1000}}},
        auto_load_trace=False,
        memo_cache=None,
    )

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    input_info = diag.context["inputs"][0]
    assert input_info["child_cache_ref"] == "concept.title"
    assert input_info["parent_cache_ref"] == "song.concept.title"
    assert input_info["tokens_estimated"] is not None
    assert input_info["tokens_estimated"] < 100


def test_sub_workflow_cache_undeclared_trace_fallback_resolves_child_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trace fallback tokenizes the used child suffix, not the full invocation input."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"song": {"type": "object"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${song.concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept.title}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${concept.title}"},
            },
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_type": "WorkflowExecutor",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"concept": {"title": "title " * 30, "unused": "unused " * 1000}},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "draft",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 1,
                            },
                        },
                        {
                            "node_id": "review",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 1,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    input_info = diag.context["inputs"][0]
    assert input_info["child_cache_ref"] == "concept.title"
    assert input_info["parent_cache_ref"] == "song.concept.title"
    assert input_info["tokens_estimated"] is not None
    assert input_info["tokens_estimated"] < 100


def test_cross_workflow_projection_uses_child_subpath_contribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-call projection uses the actual child cache ref, not the full input root."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {
            "items": [
                {
                    "name": "concept.title",
                    "var": "concept.title",
                    "prose_before": "Title only:\nParent-side label to preserve across workflows.\n",
                }
            ]
        },
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Draft ${concept.title}"},
            }
        ],
    }
    child_path = Path("/abs/child.pflow.md")
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "parent.pflow.md",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "call-child",
                    "node_type": "WorkflowExecutor",
                    "node_params": {
                        "workflow": "./child.pflow.md",
                        "inputs": {"concept": {"title": "title " * 1100, "unused": "unused " * 5000}},
                    },
                    "sub_workflow_events": [
                        {
                            "node_id": "draft",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 6000,
                                "output_tokens": 1,
                            },
                        },
                        {
                            "node_id": "draft",
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 6000,
                                "output_tokens": 1,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    row = next(row for row in result.per_call if row.workflow_path == str(child_path) and row.node_path == "draft")
    assert row.cacheable_data_source == "cross_workflow_projection"
    assert row.cacheable_tokens_estimated is not None
    assert row.cacheable_tokens_estimated < 2_000
    assert row.cross_workflow_inputs == (
        CrossWorkflowInputContribution(
            child_input_name="concept",
            child_cache_ref="concept.title",
            parent_value_expr="concept",
            parent_cache_ref="concept.title",
            parent_prose="Title only:\nParent-side label to preserve across workflows.\n",
            tokens_per_call=row.cacheable_tokens_estimated,
            model="anthropic/claude-haiku-4-5",
        ),
    )
    payload = render_json(result)
    child_row = next(item for item in payload["per_call"] if item["workflow_path"] == str(child_path))
    assert child_row["cross_workflow_inputs"] == [
        {
            "child_input_name": "concept",
            "child_cache_ref": "concept.title",
            "parent_value_expr": "concept",
            "parent_cache_ref": "concept.title",
            "parent_prose": "Title only:\nParent-side label to preserve across workflows.\n",
            "tokens_per_call": row.cacheable_tokens_estimated,
            "model": "anthropic/claude-haiku-4-5",
        }
    ]


def test_sub_workflow_cache_undeclared_params_inputs_cleanup_uses_prompt_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`params.inputs` dealiasing should cache the source ref and clean the alias."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"inputs": {"title": "${concept.title}"}, "prompt": "Draft ${title}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"inputs": {"title": "${concept.title}"}, "prompt": "Review ${title}"},
            },
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    input_info = diag.context["inputs"][0]
    assert input_info["child_cache_ref"] == "concept.title"
    assert input_info["template_var_refs_by_node"] == {"draft": ["title"], "review": ["title"]}


def test_sub_workflow_cache_declaration_coverage_is_path_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declared ancestors suppress descendants without confusing similar names."""
    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "inputs": {"concept": {"type": "object"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${concept}"}},
            }
        ],
    }
    child_ir = {
        "inputs": {"concept": {"type": "object"}},
        "cache": {"items": [{"name": "concept.title", "var": "${concept.title}", "prose_before": ""}]},
        "nodes": [
            {"id": "title-a", "type": "llm", "params": {"prompt": "A ${concept.title}"}},
            {"id": "title-b", "type": "llm", "params": {"prompt": "B ${concept.title}"}},
            {"id": "body-a", "type": "llm", "params": {"prompt": "A ${concept.body}"}},
            {"id": "body-b", "type": "llm", "params": {"prompt": "B ${concept.body}"}},
            {"id": "suffix-a", "type": "llm", "params": {"prompt": "A ${concept.title_suffix}"}},
            {"id": "suffix-b", "type": "llm", "params": {"prompt": "B ${concept.title_suffix}"}},
            {"id": "other-a", "type": "llm", "params": {"prompt": "A ${conceptual.title}"}},
            {"id": "other-b", "type": "llm", "params": {"prompt": "B ${conceptual.title}"}},
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, Path("/abs/child.pflow.md"), ()),
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    refs = [item["child_cache_ref"] for item in diag.context["inputs"]]
    assert "concept.title" not in refs
    assert "concept.body" in refs
    assert "concept.title_suffix" in refs
    assert "conceptual.title" not in refs


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
                            "cache_chunks_skipped": ["topic"],
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
    assert diag.context["root_cause"] == "chunk_skipped"


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
                            "cache_chunks_skipped": ["concept"],
                        },
                    }
                ],
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    diag = next(d for d in result.warnings if d.id == "cache.discrepancy")
    assert diag.node_id == "child-gen"
    assert diag.context is not None
    assert diag.context["root_cause"] == "chunk_skipped"


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
    """When no actual cache key and no chunks were skipped, no discrepancy possible.

    Mutation-test guard: removing the missing-key gate would emit phantom
    key_mismatch diagnostics on trace events with no comparable actual key.
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


def test_discrepancy_silently_skips_when_actual_key_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: trace events lacking cache_key are skipped rather than
    emitting false-positive key_mismatch with actual_key=None.

    Mutation contract: revert the ``actual_key is None`` clause of the gate
    and this emits a key_mismatch with predicted_key set, actual_key=None.
    """
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
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_chunks_skipped": [],
                },
            }
        ],
    )
    result = analyze({"nodes": []}, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)
    assert "cache.discrepancy" not in {d.id for d in result.warnings}


def test_attribute_root_cause_returns_chunk_skipped_for_truthy_chunks() -> None:
    """Sanity guard: ``_attribute_root_cause`` keeps the two-branch shape."""
    from pflow.core.cache_analysis.analyze import _attribute_root_cause

    root_cause, summary, suggestion, extra = _attribute_root_cause(chunks_skipped=["X"])
    assert root_cause == "chunk_skipped"
    assert "X" in summary
    assert "X" in suggestion
    assert extra == {"skipped_chunk": "X"}


def test_attribute_root_cause_returns_key_mismatch_for_falsy_chunks() -> None:
    from pflow.core.cache_analysis.analyze import _attribute_root_cause

    root_cause, summary, suggestion, extra = _attribute_root_cause(chunks_skipped=None)
    assert root_cause == "key_mismatch"
    assert "Upstream value changed" in summary
    assert "re-run analyze-cache" in suggestion
    assert extra == {}


def test_predict_cache_keys_pads_partial_walker_params_no_schema_failure_note(tmp_path: Path) -> None:
    """Bug 3 regression — when the cross-workflow walker resolves SOME but
    not all of a sub-workflow's declared inputs (e.g. an input that flows
    from an upstream sub-workflow output), the discrepancy stage must NOT
    emit a "workflow failed to compile (SchemaValidationError)" Note for
    that sub-workflow. The walker's partial params get padded with the
    standard ``"__validation_placeholder__"`` for missing required slots
    so compile succeeds; per-node prediction is skipped silently for any
    node whose templates touch a padded slot.

    Mutation contract: revert ``_predict_one_workflow``'s call to
    ``_pad_inputs_for_prediction`` (pass raw walker params straight to
    ``_build_predict_scaffold``) and ``compile_workflow`` raises
    ``SchemaValidationError("Workflow requires input 'analyses'")`` for
    the missing slot. The scaffold's broad catch then debug-logs and
    returns None — but the OLD code path that paired that failure with a
    user-facing Note via ``_format_fidelity_skip_note`` is gone, so the
    test would only catch the regression if the padding were restored
    AND a Note were emitted. Concretely: this test fails if a future
    edit reintroduces a ``notes.append(...)`` on scaffold failure.
    """
    from types import SimpleNamespace

    from pflow.core.cache_analysis.analyze import _predict_cache_keys
    from pflow.core.cache_analysis.context import AnalysisContext
    from pflow.runtime.cache import MemoizationCache

    # Sub-workflow that declares two required inputs. Walker resolves
    # only one (``brief``); ``analyses`` flows from an upstream node and
    # is left empty by the walker. Mirrors the lyrics-generator
    # ``concept-chooser`` case exactly (which was the source of Bug 3).
    # Each node uses its input via the cache mechanism (``prompt_cache:``)
    # — referencing it both inline and via cache trips the validator's
    # ``cache.prompt-body-duplicates-cache`` rule.
    workflow_ir: dict[str, Any] = {
        "inputs": {
            "brief": {"type": "string", "required": True},
            "analyses": {"type": "any", "required": True},
        },
        "cache": {
            "items": [
                {"name": "brief", "var": "brief", "prose_before": "B:\n"},
                {"name": "analyses", "var": "analyses", "prose_before": "A:\n"},
            ]
        },
        "nodes": [
            {
                "id": "use-brief",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Apply the brief shown above."},
                "prompt_cache": ["brief"],
            },
            {
                "id": "use-analyses",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Apply the analyses shown above."},
                "prompt_cache": ["analyses"],
            },
        ],
        "edges": [{"from": "use-brief", "to": "use-analyses"}],
    }
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters={"brief": "real brief content from upstream"},
        memo_cache=MemoizationCache(db_path=tmp_path / "cache.db"),
        workflow_path="x.pflow.md",
    )
    cw_result = SimpleNamespace(irs_by_workflow={"x.pflow.md": workflow_ir}, edges=())

    keys, notes = _predict_cache_keys(cw_result, ctx)
    # The misleading SchemaValidationError Note must not appear — this is
    # the whole point of the fix.
    assert not any("SchemaValidationError" in n for n in notes), f"unexpected: {notes!r}"
    assert not any("failed to compile" in n for n in notes), f"unexpected: {notes!r}"
    # ``use-brief`` references only walker-resolved ``brief`` → predicted.
    # ``use-analyses`` references the padded ``analyses`` → silently skipped.
    assert ("x.pflow.md", "use-brief") in keys, f"expected use-brief in {sorted(keys)}"
    assert ("x.pflow.md", "use-analyses") not in keys, f"unexpected use-analyses in {sorted(keys)}"


def test_build_predict_scaffold_silent_on_compile_failure() -> None:
    """Bug 3 contract — when ``compile_workflow`` raises despite the
    unified validator's earlier pass, the scaffold returns ``None`` and
    emits no user-facing Note. Failures here only fire for compiler-
    internal bugs the validator missed; debug logging keeps them
    traceable without polluting agent output.

    Mutation contract: restore ``notes.append(_format_fidelity_skip_note(...))``
    on scaffold-failure paths (the pre-fix shape) and the negative
    assertions below fail.
    """
    from pflow.core.cache_analysis.analyze import _build_predict_scaffold

    class _Stub:
        pass

    # Required input ``x`` with empty params — compile raises
    # SchemaValidationError. After the fix, this is reachable only when
    # callers bypass ``_pad_inputs_for_prediction`` (production never
    # does); the scaffold still degrades silently.
    bad_ir: dict[str, Any] = {
        "inputs": {"x": {"type": "string", "required": True}},
        "nodes": [{"id": "n", "type": "llm", "params": {"prompt": "${x}"}}],
    }
    scaffold = _build_predict_scaffold(bad_ir, {}, _Stub(), "bad.pflow.md")
    assert scaffold is None


def test_pad_inputs_for_prediction_preserves_walker_values_and_marks_missing() -> None:
    """Padding helper: walker-resolved values pass through unchanged; only
    missing declared inputs get the placeholder. Returned ``dummied_keys``
    names exactly the slots that received a placeholder.

    Mutation contract: change the ``if key not in padded`` guard to
    unconditionally overwrite, and walker values get clobbered — the
    discrepancy stage's predicted cache_keys would never match the trace.
    """
    from pflow.core.cache_analysis.analyze import _pad_inputs_for_prediction

    declared = {
        "brief": {"type": "string", "required": True},
        "analyses": {"type": "any", "required": True},
        "top_n": {"type": "integer", "required": False, "default": 4},
    }
    known = {"brief": "real value from upstream"}
    padded, dummied = _pad_inputs_for_prediction(known, declared)
    assert padded["brief"] == "real value from upstream"  # walker value preserved
    assert padded["analyses"] == "__validation_placeholder__"
    assert padded["top_n"] == "__validation_placeholder__"
    assert dummied == frozenset({"analyses", "top_n"})


def test_node_references_any_detects_cache_chunk_chain() -> None:
    """A node taints when its ``prompt_cache:`` references a chunk whose
    ``var`` traces to a dummied input — even if the node has no inline
    template ref to the dummied input. This is the lyrics-generator
    concept-chooser shape: ``cache.prompt-body-duplicates-cache``
    forbids inlining the var in the prompt body, so the only path from
    node to dummied input is via the cache chunk's ``var``.

    Mutation contract: drop the ``prompt_cache`` check from
    ``_node_references_any`` and ``use-analyses`` is no longer detected
    as tainted — its predicted cache_key carries the placeholder bytes
    and never matches the trace.
    """
    from pflow.core.cache_analysis.analyze import _dummied_cache_chunks, _node_references_any

    workflow_ir = {
        "cache": {
            "items": [
                {"name": "brief", "var": "brief", "prose_before": "B:\n"},
                {"name": "analyses", "var": "analyses", "prose_before": "A:\n"},
            ]
        },
    }
    dummied_keys = frozenset({"analyses"})
    dummied_chunks = _dummied_cache_chunks(workflow_ir, dummied_keys)
    assert dummied_chunks == frozenset({"analyses"})

    use_brief = {
        "id": "use-brief",
        "type": "llm",
        "params": {"prompt": "Apply the brief above."},
        "prompt_cache": ["brief"],
    }
    use_analyses = {
        "id": "use-analyses",
        "type": "llm",
        "params": {"prompt": "Apply the analyses above."},
        "prompt_cache": ["analyses"],
    }
    assert _node_references_any(use_brief, dummied_keys, dummied_chunks) is False
    assert _node_references_any(use_analyses, dummied_keys, dummied_chunks) is True


def test_node_references_any_detects_inline_template_ref() -> None:
    """A node also taints when its IR contains a ``${var}`` template ref
    whose root is in ``dummied_keys``. Covers the second path to taint
    (the first is ``prompt_cache`` → cache chunk → var); both must be
    checked because either alone is sufficient for the predicted
    cache_key to carry placeholder bytes.

    Mutation contract: drop the ``_walk_strings`` loop in
    ``_node_references_any`` and code-block inputs (``inputs: x: ${k}``)
    that reference dummied keys go undetected.
    """
    from pflow.core.cache_analysis.analyze import _node_references_any

    code_node = {
        "id": "build-items",
        "type": "code",
        "params": {"code": "items = raw"},
        "inputs": {"raw": "${analyses}"},
    }
    assert _node_references_any(code_node, frozenset({"analyses"}), frozenset()) is True
    # Coalesce: any operand referencing a dummied root taints.
    coalesce_node = {
        "id": "n",
        "type": "llm",
        "params": {"prompt": "${analyses ?? brief}"},
    }
    assert _node_references_any(coalesce_node, frozenset({"analyses"}), frozenset()) is True
    # No refs to dummied roots → not tainted.
    safe_node = {
        "id": "n",
        "type": "llm",
        "params": {"prompt": "${brief}"},
    }
    assert _node_references_any(safe_node, frozenset({"analyses"}), frozenset()) is False


def test_build_predict_scaffold_injects_pflow_workflow_file() -> None:
    """The scaffold must inject ``_pflow_workflow_file`` into compile
    params so relative file refs in child workflows resolve against the
    workflow's directory instead of CWD — matches
    ``WorkflowValidator._validate_one_child_call``'s pattern.

    Mutation contract: drop the injection and ``@./file.ext`` refs in
    sub-workflows resolve against CWD, silently misresolving for any
    workflow not under the current directory.
    """
    from pflow.core.cache_analysis.analyze import _build_predict_scaffold
    from pflow.runtime.cache import MemoizationCache

    workflow_ir: dict[str, Any] = {
        "inputs": {"name": {"type": "string"}},
        "nodes": [
            {
                "id": "n",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "hi"},
            }
        ],
        "edges": [],
    }
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        cache = MemoizationCache(db_path=Path(tmp) / "cache.db")
        scaffold = _build_predict_scaffold(workflow_ir, {"name": "alice"}, cache, "x.pflow.md")
        assert scaffold is not None
        assert scaffold.shared.get("_pflow_workflow_file") == "x.pflow.md"


def test_discrepancy_compile_failure_falls_back_to_observable_only(tmp_path: Path) -> None:
    """When ``compile_workflow`` raises (here: a malformed batch shape that
    triggers a ValueError downstream of compile), the discrepancy stage
    silently degrades — no user-facing Note — and observable-field
    attribution (chunk_skipped) still emits the ``cache.discrepancy``
    diagnostic.

    Bug 3 contract: the pre-fix code emitted a "Cache fidelity check
    skipped for bad.pflow.md: workflow failed to compile (ValueError)"
    Note for every compile failure during prediction, including for
    workflows that ran fine end-to-end. The fix downgrades all scaffold
    failures to a debug log; observable attribution is now the sole
    agent-facing signal for this case.

    Mutation contract: restore the ``notes.append(...)`` on scaffold
    failure (pre-fix shape) and the negative assertions below fail.
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
    # This IR has no ``inputs`` declaration so the cold-skip gate doesn't
    # fire, but the malformed batch shape (string instead of dict)
    # triggers a ValueError downstream of compile_workflow during
    # planning.
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
    # No user-facing compile-failure Note (Bug 3 fix: silent degradation).
    assert not any("Cache fidelity check skipped for bad.pflow.md" in n for n in result.notes), (
        f"unexpected compile-failure note: {result.notes!r}"
    )
    assert not any("failed to compile" in n for n in result.notes), f"unexpected compile-failure note: {result.notes!r}"
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
# `_aggregate_sub_workflow_cache_candidates_by_child` — tie-break determinism
# ---------------------------------------------------------------------------


def test_aggregate_sub_workflow_cache_candidates_tie_breaks_on_parent_workflow() -> None:
    """When two parents in different workflows share the same parent_node_id
    and reach the same (child_workflow, child_input_name), the tie-break must
    be deterministic on the full ``(parent_node_id, parent_workflow)`` tuple
    — NOT dict-insertion-order.

    Mutation contract: removing ``parent_workflow`` from the comparison tuple
    at ``analyze.py::_aggregate_sub_workflow_cache_candidates_by_child`` makes this test
    insertion-order-dependent. With both candidates passed in either order,
    the deterministic-by-tuple version always picks the lex-smaller
    parent_workflow. The pre-fix code returned whichever was first seen.
    """
    from pflow.core.cache_analysis.analyze import (
        _aggregate_sub_workflow_cache_candidates_by_child,
        _SubWorkflowCacheCandidate,
    )

    candidate_a = _SubWorkflowCacheCandidate(
        parent_workflow="alpha-parent.pflow.md",
        parent_value_expr="${concept}",
        parent_node_id="main",  # SAME id as candidate_b
        line_in_parent=10,
        child_workflow="child.pflow.md",
        child_input_name="concept",
        child_count=2,
        child_node_ids=("a", "b"),
    )
    candidate_b = _SubWorkflowCacheCandidate(
        parent_workflow="zulu-parent.pflow.md",
        parent_value_expr="${concept}",
        parent_node_id="main",  # SAME id as candidate_a
        line_in_parent=20,
        child_workflow="child.pflow.md",
        child_input_name="concept",
        child_count=2,
        child_node_ids=("a", "b"),
    )

    # Either order in → same winner out (alpha-parent < zulu-parent lex).
    forward = _aggregate_sub_workflow_cache_candidates_by_child([candidate_a, candidate_b])
    reversed_ = _aggregate_sub_workflow_cache_candidates_by_child([candidate_b, candidate_a])

    assert len(forward) == 1
    assert len(reversed_) == 1
    assert forward[0].candidates[0].parent_workflow == "alpha-parent.pflow.md"
    assert reversed_[0].candidates[0].parent_workflow == "alpha-parent.pflow.md", (
        "tie-break drift: dict-insertion-order won instead of lex-smallest "
        "parent_workflow. Did the (parent_node_id, parent_workflow) tuple "
        "comparison get reverted?"
    )


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
            root_cause="key_mismatch",
            root_cause_summary="x",
            suggestion="x",
            affected_workflow="w",
        )
        for _ in range(3)
    ]
    diags.append(
        make_diagnostic(
            "cache.discrepancy",
            node_id="gen",
            root_cause="chunk_skipped",
            root_cause_summary="y",
            suggestion="y",
            affected_workflow="w",
            skipped_chunk="concept",
        )
    )

    notes: list[str] = []
    aggregated = _aggregate_and_cap_discrepancies(diags, max_total=20, notes=notes)
    assert len(aggregated) == 2
    assert aggregated[0].context is not None
    assert aggregated[0].context["affected_invocations"] == 3
    assert aggregated[0].context["root_cause"] == "key_mismatch"
    assert aggregated[1].context is not None
    assert aggregated[1].context["affected_invocations"] == 1
    assert aggregated[1].context["root_cause"] == "chunk_skipped"
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
            root_cause="key_mismatch",
            root_cause_summary="x",
            suggestion="x",
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

    shared_context = {"category": "cache_advisory", "root_cause": "key_mismatch"}
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
    # Fix 8 follow-up: plain-English framing via ``_format_fidelity_skip_note``.
    assert "Cache fidelity check skipped for x.pflow.md.review" in skip_reason
    assert "template reference couldn't be resolved" in skip_reason
    assert "depends on a runtime value" in skip_reason


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

    Mutation test: remove the inline ``_chunks_shared_with_other_group`` filter
    inside ``_detect_cache_fragmentation_by``; this test fails because disjoint
    chunks emit a false warning.
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

    Mutation test: revert ``_compute_fragmentation_costs`` to use
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
# cache.system-prompts-fragment-cache — shared chunks across distinct system:
# prompts
#
# Detector: ``_detect_system_cache_fragmentation`` in ``analyze.py``.
# Generalized engine: ``_detect_cache_fragmentation_by``.
# Sibling: ``cache.heterogeneous-models-fragment-cache``.
# ---------------------------------------------------------------------------


def test_system_fragmentation_fires_for_two_distinct_system_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two LLM nodes share a cache chunk and model but declare different
    ``system:`` instructions. The analyzer warns because cross-node cache
    sharing requires uniform system content.

    Mutation test: remove the ``len(fragmented_groups) < 2`` and
    ``len(participating_groups) < 2`` guards in
    ``_detect_cache_fragmentation_by``; degenerate cases can then emit as
    fragmentation. This test pins the positive path, and the suppression
    tests below pin the guards.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are an emotional reviewer.", "prompt": "Review."},
            },
        ],
    }

    analysis = analyze(workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False)

    found = [d for d in analysis.warnings if d.id == "cache.system-prompts-fragment-cache"]
    assert found, f"system-fragmentation warning missing: ids={[d.id for d in analysis.warnings]}"
    ctx = found[0].context
    assert ctx is not None
    assert ctx["system_group_count"] == 2
    assert ctx["shared_chunks"] == ["context"]
    assert {entry["system_preview"] for entry in ctx["system_groups"]} == {
        "You are a lyricist.",
        "You are an emotional reviewer.",
    }
    assert ctx["node_ids_csv"] == "draft, review"
    assert ctx["savings_usd"] > 0


def test_system_fragmentation_silent_when_uniform_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical ``system:`` strings form one bucket, so shared chunks are not
    fragmented by system prompt.

    Mutation test: change ``bucket_key = key or ""`` to a per-row value in
    ``_detect_cache_fragmentation_by``; identical system strings split into
    separate buckets and this test fails with a false warning.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "You are a lyricist.", "prompt": "Review."},
            },
        ],
    }

    analysis = analyze(workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False)

    assert "cache.system-prompts-fragment-cache" not in {d.id for d in analysis.warnings}


def test_system_fragmentation_silent_when_no_chunk_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct systems with disjoint cache chunks do not fragment one shared
    cache opportunity.

    Mutation test: remove the ``_chunks_shared_with_other_group`` predicate
    inside ``_detect_cache_fragmentation_by``. Every group then looks
    fragmented, so this test fails with a warning on disjoint chunks.
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
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["a"],
                "params": {"system": "You are a lyricist.", "prompt": "Draft."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["b"],
                "params": {"system": "You are an emotional reviewer.", "prompt": "Review."},
            },
        ],
    }

    analysis = analyze(
        workflow_ir,
        parameters={"a": "alpha " * 200, "b": "bravo " * 200},
        auto_load_trace=False,
    )

    assert "cache.system-prompts-fragment-cache" not in {d.id for d in analysis.warnings}


def test_system_fragmentation_skips_when_groups_have_heterogeneous_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A system group with mixed exact models defers to model-fragmentation.

    A and B share ``system: "X"`` but use different models; C has
    ``system: "Y"``. Fixing system alone would not unlock sharing while the
    model namespace still splits the cache.

    Mutation test: change ``_homogeneous_model_for_system_group`` to return an
    arbitrary model from the group. The system warning then fires in a workflow
    whose dominant fragmentation cause is model namespace splitting.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "node-a",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "X", "prompt": "A."},
            },
            {
                "id": "node-b",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "X", "prompt": "B."},
            },
            {
                "id": "node-c",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "Y", "prompt": "C."},
            },
        ],
    }

    analysis = analyze(workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False)

    ids = {d.id for d in analysis.warnings}
    assert "cache.system-prompts-fragment-cache" not in ids
    assert "cache.heterogeneous-models-fragment-cache" in ids


def test_system_fragmentation_fires_when_one_node_has_no_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent ``system:`` and declared ``system:`` render different prefix
    bytes, so they are separate cache namespaces.

    Mutation test: make ``_system_fragmentation_key`` read the wrong IR key,
    such as ``system_prompt``. Both rows then look absent and this warning
    disappears.
    """
    _patch_pricing(monkeypatch)
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}]},
        "nodes": [
            {
                "id": "with-system",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"system": "X", "prompt": "A."},
            },
            {
                "id": "without-system",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "B."},
            },
        ],
    }

    analysis = analyze(workflow_ir, parameters={"context": "stable " * 200}, auto_load_trace=False)

    assert "cache.system-prompts-fragment-cache" in {d.id for d in analysis.warnings}


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


# ---------------------------------------------------------------------------
# Reviewer-finding regressions (scratchpads/task159-pr-review-20260507.md)
# ---------------------------------------------------------------------------


def test_analyze_cache_surfaces_undeclared_prompt_cache_chunk_error() -> None:
    """Reviewer Finding 1: a typo in ``prompt_cache:`` referencing an
    undeclared cache chunk must surface as a blocking error in
    ``analyze-cache``, not be silently dropped.

    Pre-fix the analyzer's validator adapter let only catalog-IDed diagnostics
    through. ``_make_undeclared_chunk_diagnostic``
    is intentionally un-IDed (per spec § "Stable Warning ID Catalog") but
    spec § "Validation Location" requires both ``pflow run`` AND
    ``pflow analyze-cache`` to surface it. The new filter passes paths
    matching ``cache.*`` or ``.prompt_cache``.

    Mutation contract: reverting ``analyze.py::_run_full_validation`` to call
    ``validate_data_flow`` with the cache-only filter makes this test fail
    because the typo error is silently dropped.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"concept": {"type": "string"}},
        "cache": {
            "ttl": "5m",
            "items": [
                {"name": "concept", "var": "concept", "prose_before": "The concept", "_source_line": 1},
            ],
        },
        "nodes": [
            {
                "id": "use-it",
                "type": "llm",
                # Intentional typo: ``conept`` vs declared ``concept``.
                "prompt_cache": ["conept"],
                "params": {
                    "model": "anthropic/claude-haiku-4-5",
                    "prompt": "Use the concept context.",
                },
            }
        ],
    }
    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    error_msgs = [d.message for d in result.warnings if d.severity.value == "error"]
    assert any("undeclared cache chunk 'conept'" in msg for msg in error_msgs), (
        f"Undeclared chunk error should surface in analyze-cache output. Saw: {[d.id for d in result.warnings]}"
    )


def test_analyze_cache_surfaces_batch_scoped_reference_in_cache_block() -> None:
    """Reviewer Finding 1: a batch-scoped ``${item.X}`` reference inside
    ``## Cache`` must surface as a blocking error in ``analyze-cache``.

    Mutation contract: reverting ``analyze.py::_run_full_validation`` to call
    ``validate_data_flow`` with the cache-only filter makes this test fail
    because the batch-scoped error is dropped.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"items_list": {"type": "array"}},
        "cache": {
            "ttl": "5m",
            # Hand-construct an item whose var is batch-scoped (``item.value``).
            # The parser would reject this at parse-time, but this fixture
            # bypasses the parser to drive the validator directly — same shape
            # an in-memory IR construction or programmatic builder might
            # produce. The downstream contract is: validate_data_flow rejects
            # it, and analyze-cache surfaces the rejection.
            "items": [
                {"name": "item.value", "var": "item.value", "prose_before": "Item:", "_source_line": 1},
            ],
        },
        "nodes": [
            {
                "id": "fan-out",
                "type": "llm",
                "batch": {"items": "${items_list}", "as": "item"},
                "params": {
                    "model": "anthropic/claude-haiku-4-5",
                    "prompt": "Process ${item.value}",
                },
            }
        ],
    }
    result = analyze(workflow_ir, workflow_path="x.pflow.md", auto_load_trace=False, memo_cache=None)
    error_msgs = [d.message for d in result.warnings if d.severity.value == "error"]
    assert any("batch-scoped" in msg for msg in error_msgs), (
        "Batch-scoped reference in ## Cache should surface as error. "
        f"Saw: {[(d.id, d.severity.value, d.message[:60]) for d in result.warnings]}"
    )


# ---------------------------------------------------------------------------
# cache.prompt-cache-incomplete
# ---------------------------------------------------------------------------


def _partial_prompt_cache_workflow(
    *,
    prompts: tuple[str, str] = ("Use ${a} and ${b}.", "Reuse ${a} and ${b}."),
    cache_items: list[dict[str, str]] | None = None,
    prompt_cache: list[str] | None = None,
    second_prompt_cache: list[str] | None = None,
    batch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first_node: dict[str, Any] = {
        "id": "one",
        "type": "llm",
        "prompt_cache": prompt_cache if prompt_cache is not None else ["a"],
        "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": prompts[0]},
    }
    if batch is not None:
        first_node["batch"] = batch
    return {
        "inputs": {
            "a": {"type": "string"},
            "b": {"type": "string"},
            "concept": {"type": "object"},
            "items": {"type": "array"},
        },
        "cache": {
            "items": cache_items
            or [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            first_node,
            {
                "id": "two",
                "type": "llm",
                "prompt_cache": second_prompt_cache if second_prompt_cache is not None else ["a"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": prompts[1]},
            },
        ],
    }


def _partial_diag(workflow_ir: dict[str, Any], **kwargs: Any) -> tuple[Any, Any]:
    result = analyze(
        workflow_ir,
        parameters=kwargs.pop(
            "parameters",
            {
                "a": "alpha " * 20,
                "b": "bravo " * 20,
                "concept": {"title": "Title", "body": "Body"},
            },
        ),
        workflow_path=kwargs.pop("workflow_path", "partial.pflow.md"),
        auto_load_trace=False,
        memo_cache=None,
        **kwargs,
    )
    return next((d for d in result.warnings if d.id == "cache.prompt-cache-incomplete"), None), result


def test_partial_prompt_cache_declaration_emits_per_node_grouped_advisory() -> None:
    diag, _result = _partial_diag(_partial_prompt_cache_workflow())
    assert diag is not None
    assert diag.context is not None
    assert diag.context["affected_node_count"] == 2
    assert diag.context["node_findings"][0]["missing_chunks"] == ["b"]
    assert "First, remove" in diag.suggestions[1]


def test_partial_prompt_cache_groups_multiple_affected_nodes_in_single_diagnostic() -> None:
    diag, _result = _partial_diag(_partial_prompt_cache_workflow())
    assert diag is not None
    assert diag.context is not None
    assert [item["node_id"] for item in diag.context["node_findings"]] == ["one", "two"]


def test_partial_prompt_cache_corrected_list_preserves_declaration_order() -> None:
    workflow_ir = _partial_prompt_cache_workflow(
        cache_items=[
            {"name": "b", "var": "b", "prose_before": "B:\n"},
            {"name": "a", "var": "a", "prose_before": "A:\n"},
        ],
        prompt_cache=["a"],
        second_prompt_cache=["a"],
    )
    diag, _result = _partial_diag(workflow_ir)
    assert diag is not None
    assert diag.context is not None
    assert diag.context["node_findings"][0]["corrected_prompt_cache"] == ["b", "a"]


def test_partial_prompt_cache_matches_var_but_suggests_name_for_diverged_ir() -> None:
    """Direct-IR-only: parsed .pflow.md locks name == var, but analyzer handles divergence."""
    workflow_ir = _partial_prompt_cache_workflow(
        prompts=("Use ${source.value}.", "Reuse ${source.value}."),
        cache_items=[
            {"name": "stable-source", "var": "source", "prose_before": "S:\n"},
            {"name": "declared", "var": "a", "prose_before": "A:\n"},
        ],
        prompt_cache=["declared"],
        second_prompt_cache=["declared"],
    )
    diag, _result = _partial_diag(workflow_ir, parameters={"source": {"value": "x " * 20}, "a": "a " * 20})
    assert diag is not None
    assert diag.context is not None
    assert diag.context["node_findings"][0]["missing_chunks"] == ["stable-source"]
    assert diag.context["node_findings"][0]["corrected_prompt_cache"] == ["stable-source", "declared"]


def test_partial_prompt_cache_root_aware_match_handles_subpath_refs() -> None:
    workflow_ir = _partial_prompt_cache_workflow(
        prompts=("Use ${concept.title} and ${a}.", "Reuse ${concept.body} and ${a}."),
        cache_items=[
            {"name": "a", "var": "a", "prose_before": "A:\n"},
            {"name": "concept", "var": "concept", "prose_before": "Concept:\n"},
        ],
        prompt_cache=["a"],
        second_prompt_cache=["a"],
    )
    diag, _result = _partial_diag(workflow_ir)
    assert diag is not None
    assert diag.context is not None
    assert diag.context["node_findings"][0]["missing_chunks"] == ["concept"]


def test_partial_prompt_cache_skips_when_only_one_node_references() -> None:
    workflow_ir = _partial_prompt_cache_workflow(prompts=("Use ${a} and ${b}.", "Only ${a}."))
    diag, _result = _partial_diag(workflow_ir)
    assert diag is None


def test_partial_prompt_cache_skips_when_no_cache_block() -> None:
    workflow_ir = _partial_prompt_cache_workflow()
    workflow_ir.pop("cache")
    diag, _result = _partial_diag(workflow_ir)
    assert diag is None


def test_partial_prompt_cache_skips_when_batch_scoped_ref_only() -> None:
    workflow_ir = _partial_prompt_cache_workflow(
        prompts=("Use ${item.b}.", "Reuse ${item.b}."),
        cache_items=[
            {"name": "b", "var": "item.b", "prose_before": "B:\n"},
            {"name": "a", "var": "a", "prose_before": "A:\n"},
        ],
        batch={"items": [{"b": "x"}, {"b": "y"}], "as": "item"},
    )
    diag, _result = _partial_diag(workflow_ir)
    assert diag is None


def test_partial_prompt_cache_below_threshold_keeps_advisory_drops_savings() -> None:
    diag, _result = _partial_diag(_partial_prompt_cache_workflow(), parameters={"a": "a", "b": "b"})
    assert diag is not None
    assert diag.context is not None
    assert diag.context["savings_usd"] is None
    assert "below" in diag.context["below_threshold_clause"]


def test_partial_prompt_cache_includes_prompt_body_cleanup_hint() -> None:
    diag, _result = _partial_diag(_partial_prompt_cache_workflow())
    assert diag is not None
    assert diag.context is not None
    assert diag.context["node_findings"][0]["prompt_body_cleanup"] == ["a", "b"]
    assert "Remove from prompt body" in diag.context["node_findings_block"]


def test_partial_prompt_cache_cleanup_covers_body_contains_cache_overlap_kind() -> None:
    workflow_ir = _partial_prompt_cache_workflow(
        prompts=("Use ${concept} and ${concept.title}.", "Reuse ${concept} and ${concept.title}."),
        cache_items=[
            {"name": "a", "var": "a", "prose_before": "A:\n"},
            {"name": "concept.title", "var": "concept.title", "prose_before": "Title:\n"},
        ],
        prompt_cache=["a"],
        second_prompt_cache=["a"],
    )
    diag, _result = _partial_diag(workflow_ir)
    assert diag is not None
    assert diag.context is not None
    assert "concept" in diag.context["node_findings"][0]["prompt_body_cleanup"]


def test_partial_prompt_cache_below_threshold_does_not_reduce_rerun_cost() -> None:
    diag, result = _partial_diag(_partial_prompt_cache_workflow(), parameters={"a": "a", "b": "b"})
    assert diag is not None
    assert diag.context is not None
    assert diag.context["savings_usd"] is None
    assert all(row.cacheable_data_source != "batch_prefix" for row in result.per_call)


def test_partial_prompt_cache_validator_round_trip_zero_diagnostics_post_edit() -> None:
    workflow_ir = _partial_prompt_cache_workflow()
    diag, _result = _partial_diag(workflow_ir)
    assert diag is not None
    for node in workflow_ir["nodes"]:
        node["prompt_cache"] = ["a", "b"]
        node["params"]["prompt"] = "Use the cached context."
    diagnostics = WorkflowValidator.validate(workflow_ir=workflow_ir, extracted_params={})
    cache_diags = [d for d in diagnostics if d.id and d.id.startswith("cache.")]
    assert cache_diags == []


def test_partial_prompt_cache_heterogeneous_models_per_node_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    def fake_min(model: str) -> int:
        return 1000 if "sonnet" in model else 10

    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", fake_min)
    workflow_ir = _partial_prompt_cache_workflow()
    workflow_ir["nodes"][1]["params"]["model"] = "anthropic/claude-haiku-4-5"
    diag, _result = _partial_diag(workflow_ir, parameters={"a": "a " * 200, "b": "b " * 20})
    assert diag is not None
    assert diag.context is not None
    assert diag.context["savings_usd"] is None
    assert "one:" in diag.context["below_threshold_clause"]


def test_partial_prompt_cache_node_findings_dict_has_documented_keys() -> None:
    diag, _result = _partial_diag(_partial_prompt_cache_workflow())
    assert diag is not None
    assert diag.context is not None
    assert set(diag.context["node_findings"][0]) == {
        "node_id",
        "missing_chunks",
        "missing_chunks_csv",
        "corrected_prompt_cache",
        "corrected_prompt_cache_inline",
        "prompt_body_cleanup",
        "prompt_body_cleanup_csv",
        "rep_model",
        "missing_chunks_tokens",
    }


def test_partial_prompt_cache_emits_once_per_workflow_regardless_of_dynamic_batch_item_count() -> None:
    workflow_ir = _partial_prompt_cache_workflow(batch={"items": "${items}", "as": "row"})
    diag, result = _partial_diag(workflow_ir, parameters={"a": "a " * 20, "b": "b " * 20, "items": [1, 2, 3]})
    assert diag is not None
    assert [d.id for d in result.warnings].count("cache.prompt-cache-incomplete") == 1


def test_partial_prompt_cache_external_prompt_md_file_resolved_at_analyzer_time(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Use ${a} and ${b}.", encoding="utf-8")
    workflow_ir = _partial_prompt_cache_workflow(prompts=(str(prompt_file), "Reuse ${a} and ${b}."))
    resolve_file_references(workflow_ir, tmp_path)

    diag, _result = _partial_diag(workflow_ir)

    assert diag is not None
    assert diag.context is not None
    assert diag.context["node_findings"][0]["missing_chunks"] == ["b"]


def test_partial_prompt_cache_suppressed_when_consolidate_to_root_covers_same_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)

    def fake_ref_tokens(ref: str, **_kwargs: Any) -> int | None:
        return 100 if ref == "concept" else 5

    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", fake_ref_tokens)
    workflow_ir = _partial_prompt_cache_workflow(
        prompts=(
            "Use ${concept.title} and ${concept.body}.",
            "Reuse ${concept.title} and ${concept.body}.",
        ),
        cache_items=[
            {"name": "concept.title", "var": "concept.title", "prose_before": "Title:\n"},
            {"name": "concept.body", "var": "concept.body", "prose_before": "Body:\n"},
        ],
        prompt_cache=["concept.title"],
        second_prompt_cache=["concept.title"],
    )

    diag, result = _partial_diag(workflow_ir)

    assert any(d.id == "cache.consolidate-to-root-recommended" for d in result.warnings)
    assert diag is None


def test_partial_prompt_cache_renderer_handles_many_affected_nodes() -> None:
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
                "id": f"node-{idx}",
                "type": "llm",
                "prompt_cache": ["a"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Use ${a} and ${b}."},
            }
            for idx in range(6)
        ],
    }

    _diag, result = _partial_diag(workflow_ir)
    rendered = render_text(result, all_rows=True)

    assert "Prompt-cache incomplete" in rendered
    assert rendered.count("Set prompt_cache: [a, b]") == 6
    # The catalog template for ``cache.prompt-cache-incomplete`` embeds
    # ``\n\n`` between the intro prose and the per-node findings block.
    # Mutation contract: restore ``if line.strip()`` in ``_indent_message``
    # and the blank-but-indented line between intro and findings disappears,
    # collapsing "missing the 0.1x input-cost reuse." onto "Affected nodes:"
    # with only one newline. This regex demands at least one whitespace-only
    # line in between. End-to-end lock for the renderer change.
    assert re.search(
        r"missing the 0\.1x input-cost reuse\.\n[ \t]*\n[ \t]*Affected nodes:",
        rendered,
    )
