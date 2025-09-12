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
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
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
        otherwise falls back to token-based calculation with cache awareness.

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

            # PRIORITY 2: Fall back to token-based calculation with cache awareness
            # Check both model field and prompt_kwargs.model for compatibility
            model = call.get("model") or call.get("prompt_kwargs", {}).get("model", "unknown")
            pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

            # Handle cache tokens (Anthropic SDK)
            cache_creation_tokens = call.get("cache_creation_input_tokens", 0)
            cache_read_tokens = call.get("cache_read_input_tokens", 0)
            regular_input_tokens = call.get("input_tokens", 0)
            output_tokens = call.get("output_tokens", 0)

            # Calculate input cost with cache discounts
            # IMPORTANT: input_tokens from Anthropic already EXCLUDES cache tokens
            # Cache creation costs 25% more than regular input
            # Cache reads cost 90% less than regular input
            if cache_creation_tokens or cache_read_tokens:
                # Anthropic SDK with caching - calculate separately
                # input_tokens already excludes cache tokens (per Anthropic API spec)
                regular_input_cost = (regular_input_tokens / 1_000_000) * pricing["input"]

                # Cache creation tokens (25% premium)
                cache_creation_cost = (cache_creation_tokens / 1_000_000) * pricing["input"] * 1.25

                # Cache read tokens (90% discount)
                cache_read_cost = (cache_read_tokens / 1_000_000) * pricing["input"] * 0.10

                input_cost = regular_input_cost + cache_creation_cost + cache_read_cost
            else:
                # Regular pricing (no caching)
                input_cost = (regular_input_tokens / 1_000_000) * pricing["input"]

            # Output cost remains the same
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
        total_cache_creation = sum(call.get("cache_creation_input_tokens", 0) for call in llm_calls if call)
        total_cache_read = sum(call.get("cache_read_input_tokens", 0) for call in llm_calls if call)

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

            # Aggregate planner tokens including cache tokens
            planner_input = sum(call.get("input_tokens", 0) for call in planner_llm_calls if call)
            planner_output = sum(call.get("output_tokens", 0) for call in planner_llm_calls if call)
            planner_cache_creation = sum(
                call.get("cache_creation_input_tokens", 0) for call in planner_llm_calls if call
            )
            planner_cache_read = sum(call.get("cache_read_input_tokens", 0) for call in planner_llm_calls if call)
            planner_total = planner_input + planner_output

            # Extract unique models used in planner
            # Model should be in the model field directly now
            planner_models = list({call.get("model", "unknown") for call in planner_llm_calls if call})

            planner_metrics = {
                "duration_ms": round(planner_duration, 2) if planner_duration else None,
                "nodes_executed": len(self.planner_nodes),
                "cost_usd": planner_cost,
                "tokens_input": planner_input,
                "tokens_output": planner_output,
                "tokens_total": planner_total,
                "models_used": planner_models,
                "node_timings": self.planner_nodes,
            }

            # Add cache tokens if present
            if planner_cache_creation > 0:
                planner_metrics["cache_creation_tokens"] = planner_cache_creation
            if planner_cache_read > 0:
                planner_metrics["cache_read_tokens"] = planner_cache_read

            metrics["planner"] = planner_metrics

        # Add workflow metrics if present
        if self.workflow_nodes:
            workflow_llm_calls = [c for c in llm_calls if not c.get("is_planner", False)]
            workflow_cost = self.calculate_costs(workflow_llm_calls)

            # Aggregate workflow tokens including cache tokens
            workflow_input = sum(call.get("input_tokens", 0) for call in workflow_llm_calls if call)
            workflow_output = sum(call.get("output_tokens", 0) for call in workflow_llm_calls if call)
            workflow_cache_creation = sum(
                call.get("cache_creation_input_tokens", 0) for call in workflow_llm_calls if call
            )
            workflow_cache_read = sum(call.get("cache_read_input_tokens", 0) for call in workflow_llm_calls if call)
            workflow_total = workflow_input + workflow_output

            # Extract unique models used in workflow
            # Model should be in the model field directly now
            workflow_models = list({call.get("model", "unknown") for call in workflow_llm_calls if call})

            workflow_metrics = {
                "duration_ms": round(workflow_duration, 2) if workflow_duration else None,
                "nodes_executed": len(self.workflow_nodes),
                "cost_usd": workflow_cost,
                "tokens_input": workflow_input,
                "tokens_output": workflow_output,
                "tokens_total": workflow_total,
                "models_used": workflow_models,
                "node_timings": self.workflow_nodes,
            }

            # Add cache tokens if present
            if workflow_cache_creation > 0:
                workflow_metrics["cache_creation_tokens"] = workflow_cache_creation
            if workflow_cache_read > 0:
                workflow_metrics["cache_read_tokens"] = workflow_cache_read

            metrics["workflow"] = workflow_metrics

        # Add total metrics
        total_metrics = {
            "tokens_input": total_input,
            "tokens_output": total_output,
            "tokens_total": total_input + total_output,
            "cost_usd": total_cost,
        }

        # Add cache tokens if present
        if total_cache_creation > 0:
            total_metrics["cache_creation_tokens"] = total_cache_creation
        if total_cache_read > 0:
            total_metrics["cache_read_tokens"] = total_cache_read

        metrics["total"] = total_metrics

        # Return top-level metrics and detailed breakdown
        return {
            "duration_ms": round(total_duration, 2),
            "duration_planner_ms": round(planner_duration, 2) if planner_duration else None,
            "total_cost_usd": total_cost,
            "num_nodes": num_nodes,
            "metrics": metrics,
        }
