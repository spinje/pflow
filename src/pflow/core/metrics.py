"""Lightweight metrics collection for pflow execution."""

import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pflow.core.validation_utils import VALIDATION_PLACEHOLDER


def unavailable_models_to_counts(unavailable: Any) -> dict[str, int]:
    """Normalize the JSON ``unavailable_models`` field to ``{name: calls}``.

    Producer emits ``list[{"name": str, "calls": int}]`` (Bundle 7 / F#17
    deferred). Older traces / older callers may pass the legacy ``list[str]``
    shape (no per-model count recorded); both flow through here so the
    ``format_unavailable_models_phrase`` signature stays a single contract
    every consumer site honors. Legacy entries default to ``0`` which the
    renderer treats as "render the bare name, no parenthetical".
    """
    counts: dict[str, int] = {}
    if not isinstance(unavailable, list):
        return counts
    for entry in unavailable:
        if isinstance(entry, dict):
            name = entry.get("name")
            calls = entry.get("calls", 0)
            if isinstance(name, str) and name:
                counts[name] = int(calls) if isinstance(calls, int) else 0
        elif isinstance(entry, str) and entry:
            # Legacy shape: no per-model count recorded. Use 0 so the
            # renderer falls back to the bare-name rendering.
            counts.setdefault(entry, 0)
    return counts


def format_unavailable_models_phrase(
    unavailable_counts: Mapping[str, int],
    unnamed_count: int,
) -> str:
    """Format the "pricing unavailable for: ..." phrase from structured data.

    Top-10% rule: a single producer-side function so the three call sites
    (CLI workflow_output, success formatter, trace report) stay consistent.
    Names real models when present and includes per-model call counts so
    users see at a glance how much pricing data is missing for each
    unpriced model. Surfaces a clear count when calls arrived without a
    recorded model rather than masking them as ``"unknown"``.

    Args:
        unavailable_counts: Mapping of unpriced model name → per-call count.
        unnamed_count: Number of calls that arrived without a recorded model.

    Returns:
        Rendered phrase. Empty string when both inputs are empty/zero.
    """
    parts: list[str] = []
    if unavailable_counts:
        rendered: list[str] = []
        for model, count in sorted(unavailable_counts.items()):
            # Count of 0 means the per-model call tally wasn't recorded
            # (legacy trace shape predating Bundle 7). Render the bare name
            # rather than a confusing "(0 calls)" parenthetical.
            if count <= 0:
                rendered.append(model)
            else:
                rendered.append(f"{model} ({count} call{'s' if count != 1 else ''})")
        parts.append(", ".join(rendered))
    if unnamed_count > 0:
        noun = "call" if unnamed_count == 1 else "calls"
        parts.append(f"{unnamed_count} {noun} without recorded model")
    return "; ".join(parts)


def format_subscription_phrase(subscription: Mapping[str, Any], *, paid_cost: float | None = None) -> str:
    """Render the ``subscription`` block of ``calculate_costs`` for a human cost line.

    ``subscription (3 agent calls) · API-equivalent: $5.9507`` — the billing is
    named so the estimate never reads as observed spend, and the estimate is
    shown instead of a "pricing missing" warning (nothing is missing). Pass
    ``paid_cost`` for a mixed run: when every agent call has an estimate the
    figure becomes the run's ``API-equivalent total`` (paid + estimate).
    Agent calls whose model has no pricing are named, like unpriced API calls.
    """
    calls = int(subscription.get("calls", 0) or 0)
    label = f"subscription ({calls} agent call{'s' if calls != 1 else ''})"
    estimate = subscription.get("api_equivalent_cost_usd")
    missing_phrase = format_unavailable_models_phrase(
        unavailable_models_to_counts(subscription.get("unavailable_models", [])),
        int(subscription.get("unavailable_models_unnamed_count", 0) or 0),
    )
    if not missing_phrase and estimate is not None:
        if paid_cost:
            return f"{label} · API-equivalent total: ${paid_cost + estimate:.4f}"
        return f"{label} · API-equivalent: ${estimate:.4f}"
    if estimate is None:
        return f"{label} · API-equivalent: unavailable (no pricing for: {missing_phrase})"
    return f"{label} · API-equivalent: ${estimate:.4f}+ (partial — no pricing for: {missing_phrase})"


@dataclass
class _ModelTally:
    """Per-model call counts for calls lacking a cost, plus a no-model tally."""

    models: Counter[str] = field(default_factory=Counter)
    unnamed_count: int = 0

    def add(self, model: Any) -> None:
        if isinstance(model, str) and model and model != VALIDATION_PLACEHOLDER:
            self.models[model] += 1
        else:
            self.unnamed_count += 1

    def __bool__(self) -> bool:
        return bool(self.models) or self.unnamed_count > 0

    def as_fields(self) -> dict[str, Any]:
        return {
            "unavailable_models": [{"name": name, "calls": calls} for name, calls in sorted(self.models.items())],
            "unavailable_models_unnamed_count": self.unnamed_count,
        }


@dataclass
class _SubscriptionTally:
    """Subscription-billed (agent-backend) calls and their API-equivalent estimate."""

    calls: int = 0
    api_equivalent_cost: float | None = None
    estimate_missing: _ModelTally = field(default_factory=_ModelTally)

    def add(self, call: Mapping[str, Any]) -> None:
        self.calls += 1
        estimate = call.get("api_equivalent_cost_usd")
        if isinstance(estimate, (int, float)) and not isinstance(estimate, bool):
            self.api_equivalent_cost = (self.api_equivalent_cost or 0.0) + estimate
        else:
            self.estimate_missing.add(call.get("model"))

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "calls": self.calls,
            "api_equivalent_cost_usd": (
                round(self.api_equivalent_cost, 6) if self.api_equivalent_cost is not None else None
            ),
        }
        if self.estimate_missing:
            result.update(self.estimate_missing.as_fields())
        return result


@dataclass
class MetricsCollector:
    """Lightweight metrics aggregation for pflow execution."""

    start_time: float = field(default_factory=time.perf_counter)
    workflow_start: float | None = None
    workflow_end: float | None = None

    # Node execution timings (node_id -> duration_ms)
    workflow_nodes: dict[str, float] = field(default_factory=dict)

    def record_workflow_start(self) -> None:
        """Mark the start of workflow execution."""
        self.workflow_start = time.perf_counter()

    def record_workflow_end(self) -> None:
        """Mark the end of workflow execution."""
        self.workflow_end = time.perf_counter()

    def record_node_execution(self, node_id: str, duration_ms: float) -> None:
        """Record the execution time of a node.

        Args:
            node_id: Unique identifier for the node
            duration_ms: Execution duration in milliseconds
        """
        self.workflow_nodes[node_id] = duration_ms

    @staticmethod
    def calculate_costs(llm_calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Classify and sum the cost of accumulated LLM calls.

        Every non-warmup call lands in exactly one of three states:

        - **paid** — ``cost_usd`` is a number (LiteLLM priced the API call);
          summed into ``total_cost_usd``.
        - **subscription** — the record carries the ``api_equivalent_cost_usd``
          key (only agent backends write it; ``cost_usd`` is ``None`` by design,
          see ``core/CLAUDE.md`` → Cost normalization). Tallied under
          ``subscription``; its estimate is summed separately and never enters
          ``total_cost_usd``.
        - **unpriced** — ``cost_usd`` is ``None`` (or absent) on a record with
          no estimate key: an API call LiteLLM had no pricing for. Listed in
          ``unavailable_models`` and flips ``pricing_available`` to ``False``.

        ``total_cost_usd`` is ``None`` whenever any call's paid cost is
        unobserved (unpriced OR subscription); ``partial_cost_usd`` then carries
        the paid subset. Calls without a recorded ``model`` (or carrying the
        ``__validation_placeholder__`` sentinel) are counted into the
        ``*_unnamed_count`` fields rather than being labelled ``"unknown"``.

        Args:
            llm_calls: List of LLM call data from trace.collect_llm_calls()

        Returns:
            Dict with ``total_cost_usd`` and ``pricing_available``; plus
            ``partial_cost_usd`` when the total is unobserved,
            ``unavailable_models`` (``list[{"name", "calls"}]``) +
            ``unavailable_models_unnamed_count`` when pricing is unavailable, and
            ``subscription`` (``{"calls", "api_equivalent_cost_usd"}`` plus the
            same two ``unavailable_models*`` keys for estimate-less calls) when
            any subscription call ran. Shape is additive within JSON 4.x.
        """
        paid_cost = 0.0
        unpriced = _ModelTally()
        subscription = _SubscriptionTally()

        for call in llm_calls:
            if not call:
                continue

            cost = call.get("cost_usd")
            if cost is not None:
                paid_cost += cost
                continue
            if call.get("is_warmup"):
                continue
            if "api_equivalent_cost_usd" in call:
                subscription.add(call)
            else:
                unpriced.add(call.get("model"))

        result: dict[str, Any] = {"pricing_available": not unpriced}
        if unpriced or subscription.calls:
            result["total_cost_usd"] = None
            result["partial_cost_usd"] = round(paid_cost, 6) if paid_cost > 0 else None
        else:
            result["total_cost_usd"] = round(paid_cost, 6)
        if unpriced:
            result.update(unpriced.as_fields())
        if subscription.calls:
            result["subscription"] = subscription.as_dict()
        return result

    def _calculate_durations(self) -> tuple[float, float | None]:
        """Calculate total and workflow durations.

        Returns:
            Tuple of (total_duration_ms, workflow_duration_ms)
        """
        total_duration = (time.perf_counter() - self.start_time) * 1000

        workflow_duration = None
        if self.workflow_start and self.workflow_end:
            workflow_duration = (self.workflow_end - self.workflow_start) * 1000

        return total_duration, workflow_duration

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
        duration: float | None,
    ) -> dict[str, Any]:
        """Build metrics for workflow execution.

        Args:
            llm_calls: LLM calls for this execution
            node_timings: Node execution timings
            duration: Execution duration in milliseconds

        Returns:
            Dictionary with execution metrics
        """
        cost_data = self.calculate_costs(llm_calls)
        tokens = self._aggregate_token_counts(llm_calls)
        tokens_total = tokens["input"] + tokens["output"]

        # Extract unique models used (drop the "unknown" fallback so genuinely
        # unrecorded model fields don't leak into the displayed model list).
        # Skip warmup entries — the synthetic warmup is infrastructure, not a
        # workflow LLM call. Mirrors _LLMSummaryAccumulator.add_leaf in
        # workflow_trace.py so the CLI's models_used matches the trace JSON's.
        models = sorted({
            m
            for call in llm_calls
            if call and not call.get("is_warmup")
            for m in [call.get("model")]
            if m and m != VALIDATION_PLACEHOLDER
        })

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

    @staticmethod
    def _add_cost_breakdown(total_metrics: dict[str, Any], cost_data: dict[str, Any]) -> None:
        """Copy the cost-state fields of ``calculate_costs`` into the ``total`` metrics."""
        if not cost_data.get("pricing_available", True):
            total_metrics["pricing_available"] = False
            total_metrics["unavailable_models"] = cost_data.get("unavailable_models", [])
            total_metrics["unavailable_models_unnamed_count"] = cost_data.get("unavailable_models_unnamed_count", 0)
        for key in ("partial_cost_usd", "subscription"):
            if cost_data.get(key) is not None:
                total_metrics[key] = cost_data[key]

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
            llm_calls: List of LLM call data from trace.collect_llm_calls()

        Returns:
            Dictionary with top-level metrics and detailed breakdown
        """
        # Calculate durations
        total_duration, workflow_duration = self._calculate_durations()

        # Aggregate total token counts
        total_tokens = self._aggregate_token_counts(llm_calls)

        # Calculate total cost
        cost_data = self.calculate_costs(llm_calls)

        # Count nodes
        num_nodes = len(self.workflow_nodes)

        # Build metrics structure
        metrics = {}

        # Add workflow metrics if present
        if self.workflow_nodes:
            metrics["workflow"] = self._build_execution_metrics(llm_calls, self.workflow_nodes, workflow_duration)

        # Count LLM calls (filters out empty/falsy entries the same way
        # calculate_costs does, so the displayed count never reports phantom
        # invocations). Used by CLI/MCP renderers to surface a "Total LLM
        # calls: N" sibling line under the cost summary (Bundle 7 / F#17).
        total_calls = sum(1 for call in llm_calls if call and not call.get("is_warmup"))

        # Add total metrics
        total_metrics: dict[str, Any] = {
            "tokens_input": total_tokens["input"],
            "tokens_output": total_tokens["output"],
            "tokens_total": total_tokens["input"] + total_tokens["output"],
            "total_calls": total_calls,
            "cost_usd": cost_data.get("total_cost_usd"),
        }

        self._add_cost_breakdown(total_metrics, cost_data)

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
            "total_cost_usd": cost_data.get("total_cost_usd"),
            "num_nodes": num_nodes,
            "metrics": metrics,
        }

        # Add pricing availability info to top-level summary
        if not cost_data.get("pricing_available", True):
            summary["pricing_available"] = False
            summary["unavailable_models"] = cost_data.get("unavailable_models", [])
            summary["unavailable_models_unnamed_count"] = cost_data.get("unavailable_models_unnamed_count", 0)
        if "subscription" in cost_data:
            summary["subscription"] = cost_data["subscription"]

        # Add performance summaries
        self._add_cache_performance(summary, total_tokens)
        self._add_thinking_performance(summary, total_tokens)

        return summary
