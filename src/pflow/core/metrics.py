"""Lightweight metrics collection for pflow execution."""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Model pricing per million tokens (matching test_prompt_accuracy.py)
MODEL_PRICING = {
    "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "anthropic/claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "anthropic/claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "anthropic/claude-sonnet-4-0": {"input": 3.00, "output": 15.00},
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    "gemini-1.5-pro": {"input": 3.5, "output": 10.5},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

# Default pricing for unknown models (using gpt-4o-mini as fallback)
DEFAULT_PRICING = {"input": 0.15, "output": 0.60}


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

    def calculate_costs(self, llm_calls: list[dict[str, Any]]) -> float:
        """Calculate total cost from accumulated LLM calls.

        Prioritizes actual cost (total_cost_usd) when available,
        otherwise falls back to token-based calculation.

        Args:
            llm_calls: List of LLM call data from shared["__llm_calls__"]

        Returns:
            Total cost in USD
        """
        total_cost = 0.0

        for call in llm_calls:
            # Skip empty usage dicts
            if not call:
                continue

            # PRIORITY 1: Use actual cost if available (e.g., from Claude Code)
            if "total_cost_usd" in call and call["total_cost_usd"] is not None:
                total_cost += call["total_cost_usd"]
                continue

            # PRIORITY 2: Fall back to token-based calculation
            model = call.get("model", "unknown")
            pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

            input_tokens = call.get("input_tokens", 0)
            output_tokens = call.get("output_tokens", 0)

            # Pricing is per million tokens
            input_cost = (input_tokens / 1_000_000) * pricing["input"]
            output_cost = (output_tokens / 1_000_000) * pricing["output"]

            total_cost += input_cost + output_cost

        return round(total_cost, 6)

    def get_summary(self, llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Generate metrics summary for JSON output.

        Args:
            llm_calls: List of LLM call data from shared["__llm_calls__"]

        Returns:
            Dictionary with top-level metrics and detailed breakdown
        """
        # Calculate durations
        total_duration = (time.perf_counter() - self.start_time) * 1000

        planner_duration = None
        if self.planner_start and self.planner_end:
            planner_duration = (self.planner_end - self.planner_start) * 1000

        workflow_duration = None
        if self.workflow_start and self.workflow_end:
            workflow_duration = (self.workflow_end - self.workflow_start) * 1000

        # Aggregate token counts
        total_input = sum(call.get("input_tokens", 0) for call in llm_calls if call)
        total_output = sum(call.get("output_tokens", 0) for call in llm_calls if call)

        # Calculate costs
        total_cost = self.calculate_costs(llm_calls)

        # Count nodes
        num_nodes = len(self.planner_nodes) + len(self.workflow_nodes)

        # Build metrics structure
        metrics = {}

        # Add planner metrics if present
        if self.planner_nodes:
            planner_llm_calls = [c for c in llm_calls if c.get("is_planner", False)]
            planner_cost = self.calculate_costs(planner_llm_calls)

            # Aggregate planner tokens
            planner_input = sum(call.get("input_tokens", 0) for call in planner_llm_calls if call)
            planner_output = sum(call.get("output_tokens", 0) for call in planner_llm_calls if call)
            planner_total = planner_input + planner_output

            # Extract unique models used in planner
            planner_models = list({
                call.get("model", "unknown") for call in planner_llm_calls if call and call.get("model")
            })

            metrics["planner"] = {
                "duration_ms": round(planner_duration, 2) if planner_duration else None,
                "nodes_executed": len(self.planner_nodes),
                "cost_usd": planner_cost,
                "tokens_input": planner_input,
                "tokens_output": planner_output,
                "tokens_total": planner_total,
                "models_used": planner_models,
                "node_timings": self.planner_nodes,
            }

        # Add workflow metrics if present
        if self.workflow_nodes:
            workflow_llm_calls = [c for c in llm_calls if not c.get("is_planner", False)]
            workflow_cost = self.calculate_costs(workflow_llm_calls)

            # Aggregate workflow tokens
            workflow_input = sum(call.get("input_tokens", 0) for call in workflow_llm_calls if call)
            workflow_output = sum(call.get("output_tokens", 0) for call in workflow_llm_calls if call)
            workflow_total = workflow_input + workflow_output

            # Extract unique models used in workflow
            workflow_models = list({
                call.get("model", "unknown") for call in workflow_llm_calls if call and call.get("model")
            })

            metrics["workflow"] = {
                "duration_ms": round(workflow_duration, 2) if workflow_duration else None,
                "nodes_executed": len(self.workflow_nodes),
                "cost_usd": workflow_cost,
                "tokens_input": workflow_input,
                "tokens_output": workflow_output,
                "tokens_total": workflow_total,
                "models_used": workflow_models,
                "node_timings": self.workflow_nodes,
            }

        # Add total metrics
        metrics["total"] = {
            "tokens_input": total_input,
            "tokens_output": total_output,
            "tokens_total": total_input + total_output,
            "cost_usd": total_cost,
        }

        # Return top-level metrics and detailed breakdown
        return {
            "duration_ms": round(total_duration, 2),
            "duration_planner_ms": round(planner_duration, 2) if planner_duration else None,
            "total_cost_usd": total_cost,
            "num_nodes": num_nodes,
            "metrics": metrics,
        }
