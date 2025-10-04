"""Lightweight metrics collection for pflow execution."""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Import pricing from centralized module
from pflow.core.llm_pricing import calculate_llm_cost


@dataclass
class MetricsCollector:
    """Lightweight metrics aggregation for pflow execution."""

    start_time: float = field(default_factory=time.perf_counter)
    planner_start: Optional[float] = None
    planner_end: Optional[float] = None
    workflow_start: Optional[float] = None
    workflow_end: Optional[float] = None

    # Node execution timings (node_id -> duration_ms)
    planner_nodes: dict[str, float] = field(default_factory=dict)
    workflow_nodes: dict[str, float] = field(default_factory=dict)

    def record_planner_start(self) -> None:
        """Mark the start of planner execution."""
        self.planner_start = time.perf_counter()

    def record_planner_end(self) -> None:
        """Mark the end of planner execution."""
        self.planner_end = time.perf_counter()

    def record_workflow_start(self) -> None:
        """Mark the start of workflow execution."""
        self.workflow_start = time.perf_counter()

    def record_workflow_end(self) -> None:
        """Mark the end of workflow execution."""
        self.workflow_end = time.perf_counter()

    def record_node_execution(self, node_id: str, duration_ms: float, is_planner: bool = False) -> None:
        """Record the execution time of a node.

        Args:
            node_id: Unique identifier for the node
            duration_ms: Execution duration in milliseconds
            is_planner: Whether this node is part of planner execution
        """
        if is_planner:
            self.planner_nodes[node_id] = duration_ms
        else:
            self.workflow_nodes[node_id] = duration_ms

    def calculate_costs(self, llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate total cost from accumulated LLM calls.

        Prioritizes actual cost (total_cost_usd) when available,
        otherwise falls back to token-based calculation with cache awareness.

        Args:
            llm_calls: List of LLM call data from shared["__llm_calls__"]

        Returns:
            Dict with total_cost_usd and pricing availability info
        """
        import logging

        logger = logging.getLogger(__name__)
        total_cost = 0.0
        unavailable_models = set()

        for call in llm_calls:
            # Skip empty usage dicts
            if not call:
                continue

            # PRIORITY 1: Use pre-calculated cost if available
            if "total_cost_usd" in call and call["total_cost_usd"] is not None:
                total_cost += call["total_cost_usd"]
                continue

            # PRIORITY 2: Calculate using centralized pricing module
            # Check both model field and prompt_kwargs.model for compatibility
            model = call.get("model") or call.get("prompt_kwargs", {}).get("model", "unknown")

            # Use the centralized calculate_llm_cost function
            try:
                cost_breakdown = calculate_llm_cost(
                    model=model,
                    input_tokens=call.get("input_tokens", 0),
                    output_tokens=call.get("output_tokens", 0),
                    cache_creation_tokens=call.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=call.get("cache_read_input_tokens", 0),
                    thinking_tokens=call.get("thinking_tokens", 0),
                )
                total_cost += cost_breakdown["total_cost_usd"]
            except ValueError as e:
                # Track unknown models but don't crash
                unavailable_models.add(model)
                logger.debug(f"Pricing not available for model '{model}': {e}")

        # Return structured result
        if unavailable_models:
            return {
                "total_cost_usd": None,
                "pricing_available": False,
                "unavailable_models": sorted(unavailable_models),
                "partial_cost_usd": round(total_cost, 6) if total_cost > 0 else None,
            }
        else:
            return {
                "total_cost_usd": round(total_cost, 6),
                "pricing_available": True,
            }

    def _calculate_durations(self) -> tuple[float, Optional[float], Optional[float]]:
        """Calculate total, planner, and workflow durations.

        Returns:
            Tuple of (total_duration_ms, planner_duration_ms, workflow_duration_ms)
        """
        total_duration = (time.perf_counter() - self.start_time) * 1000

        planner_duration = None
        if self.planner_start and self.planner_end:
            planner_duration = (self.planner_end - self.planner_start) * 1000

        workflow_duration = None
        if self.workflow_start and self.workflow_end:
            workflow_duration = (self.workflow_end - self.workflow_start) * 1000

        return total_duration, planner_duration, workflow_duration

    def _aggregate_token_counts(self, llm_calls: list[dict[str, Any]]) -> dict[str, int]:
        """Aggregate token counts from LLM calls.

        Args:
            llm_calls: List of LLM call data

        Returns:
            Dictionary with aggregated token counts
        """
        return {
            "input": sum(call.get("input_tokens", 0) for call in llm_calls if call),
            "output": sum(call.get("output_tokens", 0) for call in llm_calls if call),
            "cache_creation": sum(call.get("cache_creation_input_tokens", 0) for call in llm_calls if call),
            "cache_read": sum(call.get("cache_read_input_tokens", 0) for call in llm_calls if call),
            "thinking": sum(call.get("thinking_tokens", 0) for call in llm_calls if call),
            "thinking_budget": sum(call.get("thinking_budget", 0) for call in llm_calls if call),
        }

    def _build_execution_metrics(
        self,
        llm_calls: list[dict[str, Any]],
        node_timings: dict[str, float],
        duration: Optional[float],
        is_planner: bool,
    ) -> dict[str, Any]:
        """Build metrics for planner or workflow execution.

        Args:
            llm_calls: Filtered LLM calls for this execution type
            node_timings: Node execution timings
            duration: Execution duration in milliseconds
            is_planner: Whether this is for planner metrics

        Returns:
            Dictionary with execution metrics
        """
        cost_data = self.calculate_costs(llm_calls)
        tokens = self._aggregate_token_counts(llm_calls)
        tokens_total = tokens["input"] + tokens["output"]

        # Extract unique models used
        models = list({call.get("model", "unknown") for call in llm_calls if call})

        metrics = {
            "duration_ms": round(duration, 2) if duration else None,
            "nodes_executed": len(node_timings),
            "cost_usd": cost_data.get("total_cost_usd"),
            "tokens_input": tokens["input"],
            "tokens_output": tokens["output"],
            "tokens_total": tokens_total,
            "models_used": models,
            "node_timings": node_timings,
        }

        # Add cache tokens if present
        if tokens["cache_creation"] > 0:
            metrics["cache_creation_tokens"] = tokens["cache_creation"]
        if tokens["cache_read"] > 0:
            metrics["cache_read_tokens"] = tokens["cache_read"]

        # Add thinking tokens if present
        if tokens["thinking"] > 0:
            metrics["thinking_tokens"] = tokens["thinking"]
        if tokens["thinking_budget"] > 0:
            metrics["thinking_budget"] = tokens["thinking_budget"]

        return metrics

    def _add_cache_performance(self, summary: dict[str, Any], total_tokens: dict[str, int]) -> None:
        """Add cache performance metrics to summary if cache was used.

        Args:
            summary: Summary dict to update
            total_tokens: Token counts by type
        """
        cache_total = total_tokens["cache_creation"] + total_tokens["cache_read"]
        if cache_total > 0:
            # Calculate cache efficiency (read tokens as percentage of total cached)
            cache_efficiency = (total_tokens["cache_read"] / cache_total) * 100

            summary["cache_performance"] = {
                "cache_creation_tokens": total_tokens["cache_creation"],
                "cache_read_tokens": total_tokens["cache_read"],
                "cache_efficiency_pct": round(cache_efficiency, 1),
                "cache_total_tokens": cache_total,
            }

    def _add_thinking_performance(self, summary: dict[str, Any], total_tokens: dict[str, int]) -> None:
        """Add thinking performance metrics to summary if thinking tokens were used.

        Args:
            summary: Summary dict to update
            total_tokens: Token counts by type
        """
        if total_tokens["thinking"] > 0 or total_tokens["thinking_budget"] > 0:
            thinking_utilization = 0.0
            if total_tokens["thinking_budget"] > 0:
                thinking_utilization = (total_tokens["thinking"] / total_tokens["thinking_budget"]) * 100

            summary["thinking_performance"] = {
                "thinking_tokens_used": total_tokens["thinking"],
                "thinking_budget_allocated": total_tokens["thinking_budget"],
                "thinking_utilization_pct": round(thinking_utilization, 1),
            }

    def get_summary(self, llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Generate metrics summary for JSON output.

        Args:
            llm_calls: List of LLM call data from shared["__llm_calls__"]

        Returns:
            Dictionary with top-level metrics and detailed breakdown
        """
        # Calculate durations
        total_duration, planner_duration, workflow_duration = self._calculate_durations()

        # Aggregate total token counts
        total_tokens = self._aggregate_token_counts(llm_calls)

        # Calculate total cost
        cost_data = self.calculate_costs(llm_calls)

        # Count nodes
        num_nodes = len(self.planner_nodes) + len(self.workflow_nodes)

        # Build metrics structure
        metrics = {}

        # Add planner metrics if present
        if self.planner_nodes:
            planner_llm_calls = [c for c in llm_calls if c.get("is_planner", False)]
            metrics["planner"] = self._build_execution_metrics(
                planner_llm_calls, self.planner_nodes, planner_duration, is_planner=True
            )

        # Add workflow metrics if present
        if self.workflow_nodes:
            workflow_llm_calls = [c for c in llm_calls if not c.get("is_planner", False)]
            metrics["workflow"] = self._build_execution_metrics(
                workflow_llm_calls, self.workflow_nodes, workflow_duration, is_planner=False
            )

        # Add total metrics
        total_metrics = {
            "tokens_input": total_tokens["input"],
            "tokens_output": total_tokens["output"],
            "tokens_total": total_tokens["input"] + total_tokens["output"],
            "cost_usd": cost_data.get("total_cost_usd"),
        }

        # Add pricing availability info if pricing was unavailable
        if not cost_data.get("pricing_available", True):
            total_metrics["pricing_available"] = False
            total_metrics["unavailable_models"] = cost_data.get("unavailable_models", [])
            if cost_data.get("partial_cost_usd") is not None:
                total_metrics["partial_cost_usd"] = cost_data["partial_cost_usd"]

        # Add cache tokens if present
        if total_tokens["cache_creation"] > 0:
            total_metrics["cache_creation_tokens"] = total_tokens["cache_creation"]
        if total_tokens["cache_read"] > 0:
            total_metrics["cache_read_tokens"] = total_tokens["cache_read"]

        # Add thinking tokens if present
        if total_tokens["thinking"] > 0:
            total_metrics["thinking_tokens"] = total_tokens["thinking"]
        if total_tokens["thinking_budget"] > 0:
            total_metrics["thinking_budget"] = total_tokens["thinking_budget"]

        metrics["total"] = total_metrics

        # Build summary dict
        summary = {
            "duration_ms": round(total_duration, 2),
            "duration_planner_ms": round(planner_duration, 2) if planner_duration else None,
            "total_cost_usd": cost_data.get("total_cost_usd"),
            "num_nodes": num_nodes,
            "metrics": metrics,
        }

        # Add pricing availability info to top-level summary
        if not cost_data.get("pricing_available", True):
            summary["pricing_available"] = False
            summary["unavailable_models"] = cost_data.get("unavailable_models", [])

        # Add performance summaries
        self._add_cache_performance(summary, total_tokens)
        self._add_thinking_performance(summary, total_tokens)

        return summary
