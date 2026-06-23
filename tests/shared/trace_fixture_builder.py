"""Production-shaped trace fixtures for cache-analysis tests."""

from __future__ import annotations

from typing import Any


class TraceFixtureBuilder:
    """Build trace dicts matching ``WorkflowTraceCollector`` event shape."""

    def llm_event(
        self,
        node_id: str,
        *,
        cost_usd: float | None = 0.01,
        input_tokens: int = 1000,
        output_tokens: int = 100,
        model: str = "anthropic/claude-sonnet-4-5",
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        success: bool = True,
        system: str | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Live (non-cached) LLM event matching production shape.

        ``input_tokens`` is the cache-INCLUSIVE total (it includes any cache tiers),
        matching pflow's contract for every producer — see ``core/llm_usage.py``.
        """
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 1.0,
            "status": "success" if success else "failed",
            "timestamp": "2026-05-02T00:00:00",
            "node_output": {"response": "ok"},
            "llm_call": {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": cost_usd,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
            },
            "llm_prompt": "prompt",
            "llm_response": "ok",
        }
        if system is not None:
            event["llm_system"] = system
        return event

    def cached_llm_event_thin(self, node_id: str) -> dict[str, Any]:
        """Bare-minimum cached LLM event — omits node_output / llm_call / node_params.

        Use this ONLY when the test point IS the thin shape (e.g., asserting
        that consumers handle missing-llm_call cached events without crashing).
        For production-shape tests, use ``cached_llm_event_with_call`` — it
        mirrors what ``apply_memo_hit`` + ``_augment_llm_usage_with_cache_metadata``
        actually produce at runtime, and is covered by the parity test at
        ``test_trace_tree.py::test_cached_llm_event_with_call_shape_matches``.
        """
        return {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 0.0,
            "status": "cached",
            "timestamp": "2026-05-02T00:00:00",
        }

    def cached_llm_event_with_call(
        self,
        node_id: str,
        *,
        cost_usd: float = 0.01,
        model: str = "anthropic/claude-sonnet-4-5",
        input_tokens: int = 1000,
        output_tokens: int = 100,
        cache_read_input_tokens: int = 950,
        cache_creation_input_tokens: int = 0,
        cache_source: str = "memo",
        cache_key: str = "fixture-cache-key",
        cache_age_sec: float = 30.0,
        system: str | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Memo-hit LLM event matching production shape.

        Mirrors what ``apply_memo_hit`` + ``_augment_llm_usage_with_cache_metadata``
        + ``_add_llm_data`` produce at runtime: ``cached: true`` AND ``llm_call``
        is populated with the ORIGINAL ``cost_usd`` (the run paid $0 but the
        cache record retains the original spend), plus ``cache_source``,
        ``cache_key``, ``cache_age_sec`` augmented at restore.
        ``node_output.llm_usage`` mirrors ``llm_call``.

        ``input_tokens`` is the cache-INCLUSIVE total (it includes
        ``cache_read_input_tokens`` / ``cache_creation_input_tokens``), matching
        pflow's contract for every producer — see ``core/llm_usage.py``. The
        default 1000/950 means "1000 total of which 950 was a cache read".
        """
        llm_call = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": cost_usd,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_key": cache_key,
            "cache_source": cache_source,
            "cache_age_sec": cache_age_sec,
        }
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 0.0,
            "status": "cached",
            "timestamp": "2026-05-02T00:00:00",
            "node_params": {"model": model},
            "node_output": {"response": "ok", "llm_usage": dict(llm_call)},
            "llm_call": llm_call,
            "llm_prompt": "prompt",
            "llm_response": "ok",
        }
        if system is not None:
            event["llm_system"] = system
        return event

    def batch_event(self, node_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 1.0,
            "status": "failed" if any(item.get("status") == "failed" for item in items) else "success",
            "timestamp": "2026-05-02T00:00:00",
            "batch_items": items,
        }

    def workflow_event(
        self,
        node_id: str,
        sub_workflow_events: list[dict[str, Any]],
        *,
        workflow_path: str,
        success: bool | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Sub-workflow container event.

        ``workflow_path`` is the absolute path of the called child workflow
        (or the relative path used in the parent's ``workflow:`` declaration).
        Recorded in ``node_params.workflow`` matching production trace shape —
        the analyzer reads this for sub-workflow attribution.
        """
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": "WorkflowExecutor",
            "duration_ms": 1.0,
            "status": ("success" if success else "failed")
            if success is not None
            else ("failed" if any(child.get("status") == "failed" for child in sub_workflow_events) else "success"),
            "timestamp": "2026-05-02T00:00:00",
            "node_params": {"workflow": workflow_path},
        }
        if error is not None:
            event["error"] = error
        event["sub_workflow_events"] = sub_workflow_events
        return event

    def heterogeneous_workflow_batch_event(
        self,
        node_id: str,
        items: list[tuple[str, list[dict[str, Any]]]],
    ) -> dict[str, Any]:
        """Heterogeneous workflow batch — each item runs a different child.

        ``items`` is a list of ``(child_workflow_path, sub_events)`` tuples.
        Each batch item carries ``template_resolutions["workflow"]["resolved"]``
        set to the per-item child path. New runtime traces also carry an
        explicit canonical ``workflow_path``; tests add that field when they
        need the new producer shape. Leaving it out here keeps old-trace
        compatibility tests easy to build.
        """
        return {
            "node_id": node_id,
            "node_type": "WorkflowExecutor",
            "duration_ms": 1.0,
            "status": "success",
            "timestamp": "2026-05-02T00:00:00",
            "node_params": {"workflow": "${item.workflow}"},
            "batch_items": [
                {
                    "index": i,
                    "item": {"workflow": child_path},
                    "status": "success",
                    "duration_ms": 0.0,
                    "template_resolutions": {
                        "workflow": {"template": "${item.workflow}", "resolved": child_path},
                    },
                    "events": sub_events,
                }
                for i, (child_path, sub_events) in enumerate(items)
            ],
        }

    def homogeneous_workflow_batch_event(
        self,
        node_id: str,
        *,
        workflow_path: str,
        items: list[tuple[Any, list[dict[str, Any]]]],
        item_input_template: str = "${item}",
    ) -> dict[str, Any]:
        """Homogeneous static workflow batch — N items, ONE child workflow.

        Mirrors the production shape verified against
        ``~/.pflow/debug/workflow-trace-batch-parent-*.json``: parent's
        ``node_params["workflow"]`` carries the RAW IR string (the static
        literal the user wrote, often relative). Each batch_item carries
        ``template_resolutions["inputs"]`` (because ``inputs:`` IS templated
        as ``${item.X}``) but DOES NOT carry
        ``template_resolutions["workflow"]`` — there's no ``workflow:``
        template to resolve.

        ``items`` is a list of ``(item_value, sub_events)`` tuples.
        ``item_input_template`` is the template literal the parent's
        ``inputs:`` block uses (defaults to ``${item}`` for simple item
        passthrough).
        """
        return {
            "node_id": node_id,
            "node_type": "WorkflowExecutor",
            "duration_ms": 1.0,
            "status": "success",
            "timestamp": "2026-05-02T00:00:00",
            "node_params": {"workflow": workflow_path, "inputs": {"input": item_input_template}},
            "batch_items": [
                {
                    "index": i,
                    "item": item_value,
                    "status": "success",
                    "duration_ms": 0.0,
                    "template_resolutions": {
                        "inputs": {
                            "template": {"input": item_input_template},
                            "resolved": {"input": item_value},
                        },
                    },
                    "events": sub_events,
                }
                for i, (item_value, sub_events) in enumerate(items)
            ],
        }

    def trace(
        self,
        workflow_path: str,
        nodes: list[dict[str, Any]],
        *,
        workflow_name: str = "fixture",
        final_status: str | None = None,
        failed_node_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        ids_failed = list(failed_node_ids) if failed_node_ids is not None else []
        status = final_status if final_status is not None else ("failed" if ids_failed else "success")
        return {
            "format_version": "2.2.0",
            "execution_id": "fixture",
            "workflow_name": workflow_name,
            "workflow_path": workflow_path,
            "start_time": "2026-05-02T00:00:00",
            "end_time": "2026-05-02T00:00:01",
            "duration_ms": 1.0,
            "final_status": status,
            "nodes_executed": len(nodes),
            "nodes_failed": len(ids_failed),
            "failed_node_ids": ids_failed,
            "nodes": nodes,
        }
