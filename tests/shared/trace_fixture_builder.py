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
    ) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 1.0,
            "success": success,
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

    def cached_llm_event(self, node_id: str) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 0.0,
            "success": True,
            "timestamp": "2026-05-02T00:00:00",
            "cached": True,
        }

    def batch_event(self, node_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "node_type": "LLMNode",
            "duration_ms": 1.0,
            "success": all(bool(item.get("success", True)) for item in items),
            "timestamp": "2026-05-02T00:00:00",
            "batch_items": items,
        }

    def workflow_event(
        self,
        node_id: str,
        sub_workflow_events: list[dict[str, Any]],
        *,
        success: bool | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "node_id": node_id,
            "node_type": "WorkflowExecutor",
            "duration_ms": 1.0,
            "success": success
            if success is not None
            else all(bool(child.get("success", True)) for child in sub_workflow_events),
            "timestamp": "2026-05-02T00:00:00",
        }
        if error is not None:
            event["error"] = error
        event["sub_workflow_events"] = sub_workflow_events
        return event

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
            "format_version": "2.1.0",
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
