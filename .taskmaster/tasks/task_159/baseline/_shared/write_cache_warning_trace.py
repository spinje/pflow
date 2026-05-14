#!/usr/bin/env python3
"""Write small trace fixtures for below-min warning catalog baselines."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MODEL = "anthropic/claude-sonnet-4-5"
PROVIDER_NOTE = "cache_control markers will silently no-op at the provider"


def _llm_call(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    call: dict[str, Any] = {
        "model": MODEL,
        "input_tokens": 24,
        "output_tokens": 5,
        "total_tokens": 29,
        "cost_usd": 0.0001,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "has_cache_telemetry": True,
    }
    if extra:
        call.update(extra)
    return call


def _trace(
    workflow_path: str, nodes: list[dict[str, Any]], warnings: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "format_version": "2.3.0",
        "execution_id": "baseline-fixture",
        "workflow_name": "below-min-baseline",
        "workflow_path": workflow_path,
        "start_time": "2026-05-14T00:00:00",
        "end_time": "2026-05-14T00:00:01",
        "duration_ms": 1.0,
        "final_status": "degraded" if warnings else "success",
        "nodes_executed": len(nodes),
        "nodes_failed": 0,
        "failed_node_ids": [],
        "nodes": nodes,
    }
    if warnings:
        trace["warnings"] = warnings
    return trace


def _event(node_id: str, llm_call: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": "LLMNode",
        "duration_ms": 1.0,
        "success": True,
        "timestamp": "2026-05-14T00:00:00",
        "node_output": {"response": "ok", "llm_usage": llm_call},
        "llm_call": llm_call,
        "llm_prompt": "Summarize.",
        "llm_response": "ok",
    }


def _warning(warning_id: str, *, node_id: str, workflow_path: str, cacheable_tokens: int) -> dict[str, Any]:
    context = {
        "affected_workflow": workflow_path,
        "model": MODEL,
        "min_tokens": 1024,
        "cacheable_tokens": cacheable_tokens,
        "provider_note": PROVIDER_NOTE,
        "category": "cache_warning",
        "path": f"nodes[id={node_id}].prompt_cache",
    }
    if warning_id == "cache.prewarm-disabled-below-min":
        context["alias"] = "item"
        context["path"] = f"nodes[id={node_id}]"
    return {
        "severity": "warning",
        "message": warning_id,
        "source": "cache_analyzer",
        "id": warning_id,
        "title": "Cache Warning",
        "node_id": node_id,
        "context": context,
    }


def _observed(workflow_path: str) -> dict[str, Any]:
    node_id = "summarize"
    return _trace(
        workflow_path,
        [_event(node_id, _llm_call())],
        [_warning("cache.below-min-observed", node_id=node_id, workflow_path=workflow_path, cacheable_tokens=0)],
    )


def _rendered(workflow_path: str) -> dict[str, Any]:
    node_id = "summarize"
    return _trace(
        workflow_path,
        [_event(node_id, _llm_call({"cache_skipped_reason": "below_min"}))],
        [_warning("cache.below-min-rendered", node_id=node_id, workflow_path=workflow_path, cacheable_tokens=5)],
    )


def _prewarm_disabled(workflow_path: str) -> dict[str, Any]:
    node_id = "score"
    return _trace(
        workflow_path,
        [_event(node_id, _llm_call({"prewarm_disabled_reason": "below_min"}))],
        [
            _warning(
                "cache.prewarm-disabled-below-min",
                node_id=node_id,
                workflow_path=workflow_path,
                cacheable_tokens=5,
            )
        ],
    )


def _conditional(workflow_path: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index in range(4):
        call = _llm_call({"cache_skipped_reason": "below_min"} if index in {0, 1} else None)
        items.append({
            "index": index,
            "success": True,
            "duration_ms": 1.0,
            "timestamp": "2026-05-14T00:00:00",
            "node_output": {"response": "ok", "llm_usage": call},
            "llm_call": call,
            "llm_prompt": f"Item {index}",
            "llm_response": "ok",
        })
    return _trace(
        workflow_path,
        [
            {
                "node_id": "score",
                "node_type": "LLMNode",
                "duration_ms": 4.0,
                "success": True,
                "timestamp": "2026-05-14T00:00:00",
                "batch_items": items,
            }
        ],
    )


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: write_cache_warning_trace.py <observed|rendered|prewarm-disabled|conditional> <workflow> <out>",
            file=sys.stderr,
        )
        return 2
    mode, workflow_path, output_path = argv[1:]
    builders = {
        "observed": _observed,
        "rendered": _rendered,
        "prewarm-disabled": _prewarm_disabled,
        "conditional": _conditional,
    }
    if mode not in builders:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    Path(output_path).write_text(json.dumps(builders[mode](workflow_path), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
