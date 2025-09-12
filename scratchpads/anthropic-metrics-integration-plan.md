# Anthropic SDK Metrics Integration Plan

## Executive Summary

This document provides a complete implementation plan for integrating Anthropic SDK metrics (thinking tokens, cache tokens) into pflow's existing tracing and metrics systems. The good news: **cache token tracking is already implemented** - we just need to apply the correct pricing discounts and enhance the display/analysis.

## Current State Analysis

### ✅ What's Already Working

1. **Cache Token Tracking**: Fields `cache_creation_input_tokens` and `cache_read_input_tokens` are already captured
2. **LLM Usage Accumulation**: The `__llm_calls__` list in shared store accumulates all LLM usage data
3. **Trace Integration**: Full LLM call interception with prompt/response capture
4. **JSON Output**: Comprehensive metrics output with --output-format json
5. **Analysis Tools**: Scripts to convert traces to readable markdown

### ❌ Critical Gaps Identified

1. **No Cache Discount**: Cache read tokens charged at full price (should be 90% cheaper)
2. **No Thinking Tracking**: Thinking content and tokens not captured
3. **No Cache Aggregation**: Cache tokens not summed in metrics summary
4. **No Cache Visualization**: Cache efficiency not shown in traces or analysis

## Implementation Plan

### Phase 1: Update Cost Calculation for Cache Tokens

#### 1.1 Modify `src/pflow/core/metrics.py`

**Current Code (lines 161-176):**
```python
def calculate_costs(self, llm_calls: list[dict]) -> dict[str, float]:
    """Calculate cost breakdown from LLM calls."""
    total_cost = 0.0
    planner_cost = 0.0
    workflow_cost = 0.0

    for call in llm_calls:
        if not call:
            continue

        # Priority 1: Use actual cost if available
        if "total_cost_usd" in call and call["total_cost_usd"] is not None:
            total_cost += call["total_cost_usd"]
            continue

        # Priority 2: Calculate from tokens
        model = call.get("model", "unknown")
        pricing = self.MODEL_PRICING.get(model, self.MODEL_PRICING["gpt-4o-mini"])

        input_tokens = call.get("input_tokens", 0)
        output_tokens = call.get("output_tokens", 0)

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
```

**Updated Code with Cache Discounts:**
```python
def calculate_costs(self, llm_calls: list[dict]) -> dict[str, float]:
    """Calculate cost breakdown from LLM calls with cache-aware pricing."""
    total_cost = 0.0
    planner_cost = 0.0
    workflow_cost = 0.0

    for call in llm_calls:
        if not call:
            continue

        # Priority 1: Use actual cost if available
        if "total_cost_usd" in call and call["total_cost_usd"] is not None:
            total_cost += call["total_cost_usd"]
            if call.get("is_planner", False):
                planner_cost += call["total_cost_usd"]
            else:
                workflow_cost += call["total_cost_usd"]
            continue

        # Priority 2: Calculate from tokens with cache discounts
        model = call.get("model", "unknown")
        pricing = self.MODEL_PRICING.get(model, self.MODEL_PRICING["gpt-4o-mini"])

        # Separate cache tokens from regular input tokens
        base_input_tokens = call.get("input_tokens", 0)
        cache_creation_tokens = call.get("cache_creation_input_tokens", 0)
        cache_read_tokens = call.get("cache_read_input_tokens", 0)
        output_tokens = call.get("output_tokens", 0)

        # Adjust base input tokens (some APIs include cache tokens in total)
        # For Anthropic, input_tokens includes all types, so subtract cache tokens
        if cache_creation_tokens > 0 or cache_read_tokens > 0:
            base_input_tokens = max(0, base_input_tokens - cache_creation_tokens - cache_read_tokens)

        # Calculate costs with appropriate discounts
        base_input_cost = (base_input_tokens / 1_000_000) * pricing["input"]
        cache_creation_cost = (cache_creation_tokens / 1_000_000) * pricing["input"] * 1.25  # 25% premium
        cache_read_cost = (cache_read_tokens / 1_000_000) * pricing["input"] * 0.10  # 90% discount
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        call_cost = base_input_cost + cache_creation_cost + cache_read_cost + output_cost

        total_cost += call_cost
        if call.get("is_planner", False):
            planner_cost += call_cost
        else:
            workflow_cost += call_cost

    return {
        "total": round(total_cost, 6),
        "planner": round(planner_cost, 6),
        "workflow": round(workflow_cost, 6),
    }
```

### Phase 2: Add Thinking Token Tracking

#### 2.1 Update LLM Usage Structure

**Add to `src/pflow/planning/utils/anthropic_structured_client.py`:**
```python
# In prompt_with_thinking and prompt_with_schema methods
metadata = {
    "thinking": thinking_text,
    "thinking_tokens": len(thinking_text) // 4,  # Rough estimate
    "usage": {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "thinking_tokens": response.usage.thinking_tokens if hasattr(response.usage, 'thinking_tokens') else 0,
        "cache_creation_input_tokens": getattr(response.usage, 'cache_creation_input_tokens', 0),
        "cache_read_input_tokens": getattr(response.usage, 'cache_read_input_tokens', 0),
    }
}
```

#### 2.2 Update Node Post Methods

**In PlanningNode and WorkflowGeneratorNode `_exec_with_anthropic` methods:**
```python
# Store enhanced usage data
shared["llm_usage"] = {
    "model": "claude-sonnet-4-20250514",
    "input_tokens": metadata["usage"]["input_tokens"],
    "output_tokens": metadata["usage"]["output_tokens"],
    "thinking_tokens": metadata["usage"].get("thinking_tokens", 0),
    "cache_creation_input_tokens": metadata["usage"].get("cache_creation_input_tokens", 0),
    "cache_read_input_tokens": metadata["usage"].get("cache_read_input_tokens", 0),
    "total_tokens": sum([
        metadata["usage"]["input_tokens"],
        metadata["usage"]["output_tokens"],
        metadata["usage"].get("thinking_tokens", 0)
    ])
}

# Store thinking content for debugging (optional)
if metadata.get("thinking") and self.params.get("store_thinking", False):
    shared["llm_thinking"] = metadata["thinking"]
```

### Phase 3: Enhance Metrics Aggregation

#### 3.1 Update `MetricsCollector.get_summary()` in `src/pflow/core/metrics.py`

**Add cache token aggregation (after line 132):**
```python
def get_summary(self, llm_calls: list[dict] | None = None) -> dict[str, Any]:
    """Get metrics summary with cache token breakdown."""
    # ... existing code ...

    # Aggregate all token types
    total_input = sum(call.get("input_tokens", 0) for call in llm_calls if call)
    total_output = sum(call.get("output_tokens", 0) for call in llm_calls if call)
    total_thinking = sum(call.get("thinking_tokens", 0) for call in llm_calls if call)
    total_cache_creation = sum(call.get("cache_creation_input_tokens", 0) for call in llm_calls if call)
    total_cache_read = sum(call.get("cache_read_input_tokens", 0) for call in llm_calls if call)

    # Calculate cache efficiency
    cache_hit_rate = 0.0
    if total_input > 0 and total_cache_read > 0:
        cache_hit_rate = (total_cache_read / total_input) * 100

    # Calculate cost savings from cache
    if total_cache_read > 0:
        # Rough estimate: cache saves 90% on read tokens
        avg_input_price = 3.0  # Average $/1M tokens
        cache_savings = (total_cache_read / 1_000_000) * avg_input_price * 0.90
    else:
        cache_savings = 0.0

    # Update metrics structure
    metrics["total"]["tokens_input"] = total_input
    metrics["total"]["tokens_output"] = total_output
    metrics["total"]["tokens_thinking"] = total_thinking
    metrics["total"]["cache_tokens_created"] = total_cache_creation
    metrics["total"]["cache_tokens_read"] = total_cache_read
    metrics["total"]["cache_hit_rate"] = round(cache_hit_rate, 1)
    metrics["total"]["cache_savings_usd"] = round(cache_savings, 6)
```

### Phase 4: Update Trace Collection

#### 4.1 Enhance `src/pflow/planning/debug.py` TraceCollector

**Update `record_llm_response_with_data` method (around line 481):**
```python
def record_llm_response_with_data(self, node_name, response_data, response_obj):
    """Record LLM response with enhanced Anthropic metrics."""
    # ... existing code ...

    # Extract enhanced usage data
    if hasattr(response_obj, "usage") and callable(response_obj.usage):
        usage_obj = response_obj.usage()
        if usage_obj:
            # Get Anthropic-specific details
            details = getattr(usage_obj, "details", {}) or {}

            usage_data = {
                "input_tokens": getattr(usage_obj, "input", 0),
                "output_tokens": getattr(usage_obj, "output", 0),
                "thinking_tokens": details.get("thinking_tokens", 0),
                "cache_creation_input_tokens": details.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": details.get("cache_read_input_tokens", 0),
            }

            # Calculate cache efficiency for this call
            if usage_data["cache_read_input_tokens"] > 0:
                cache_efficiency = (usage_data["cache_read_input_tokens"] /
                                  usage_data["input_tokens"] * 100)
                usage_data["cache_efficiency_percent"] = round(cache_efficiency, 1)

            llm_call["tokens"] = usage_data
```

#### 4.2 Update `src/pflow/runtime/workflow_trace.py`

**Add cache metrics to node execution recording (around line 100):**
```python
def record_node_execution(
    self,
    node_id: str,
    node_type: str,
    duration_ms: float,
    success: bool,
    shared_before: dict[str, Any],
    shared_after: dict[str, Any],
    error: str | None = None,
    llm_usage: dict[str, Any] | None = None,
) -> None:
    """Record node execution with cache metrics."""
    # ... existing code ...

    if llm_usage:
        # Include all token types in the trace
        event["llm_call"] = {
            "model": llm_usage.get("model"),
            "input_tokens": llm_usage.get("input_tokens", 0),
            "output_tokens": llm_usage.get("output_tokens", 0),
            "thinking_tokens": llm_usage.get("thinking_tokens", 0),
            "cache_creation_tokens": llm_usage.get("cache_creation_input_tokens", 0),
            "cache_read_tokens": llm_usage.get("cache_read_input_tokens", 0),
            "total_tokens": llm_usage.get("total_tokens", 0),
        }

        # Add cache efficiency if applicable
        if llm_usage.get("cache_read_input_tokens", 0) > 0:
            cache_eff = (llm_usage["cache_read_input_tokens"] /
                        llm_usage["input_tokens"] * 100)
            event["llm_call"]["cache_efficiency"] = round(cache_eff, 1)
```

### Phase 5: Update JSON Output Format

#### 5.1 Enhance JSON metrics in `src/pflow/cli/main.py`

The metrics will automatically include the new fields from `MetricsCollector.get_summary()`:

**New JSON output structure:**
```json
{
  "result": {...},
  "is_error": false,
  "duration_ms": 1234.56,
  "total_cost_usd": 0.001234,
  "cache_savings_usd": 0.0008,  // NEW: Cache discount savings
  "num_nodes": 3,

  "metrics": {
    "planner": {
      "duration_ms": 567.89,
      "nodes_executed": 2,
      "cost_usd": 0.0008,
      "tokens_input": 1500,
      "tokens_output": 200,
      "tokens_thinking": 5000,  // NEW: Thinking tokens
      "cache_tokens_created": 500,  // NEW: Cache creation
      "cache_tokens_read": 800,  // NEW: Cache hits
      "cache_hit_rate": 53.3,  // NEW: Percentage cached
      "models_used": ["claude-sonnet-4-20250514"]
    },
    "workflow": {...},
    "total": {
      "tokens_input": 2300,
      "tokens_output": 300,
      "tokens_thinking": 8000,  // NEW
      "cache_tokens_created": 500,  // NEW
      "cache_tokens_read": 1200,  // NEW
      "cache_hit_rate": 52.2,  // NEW
      "cache_savings_usd": 0.0032,  // NEW
      "cost_usd": 0.001234
    }
  }
}
```

### Phase 6: Update Trace Analysis Scripts

#### 6.1 Enhance `scripts/analyze-trace/analyze.py`

**Update cost calculation with cache awareness (around line 148):**
```python
def calculate_cost(tokens_dict):
    """Calculate cost with cache-aware pricing."""
    input_tokens = tokens_dict.get("input_tokens", 0) / 1000
    output_tokens = tokens_dict.get("output_tokens", 0) / 1000
    thinking_tokens = tokens_dict.get("thinking_tokens", 0) / 1000
    cache_creation = tokens_dict.get("cache_creation_input_tokens", 0) / 1000
    cache_read = tokens_dict.get("cache_read_input_tokens", 0) / 1000

    # Adjust base input tokens
    base_input = max(0, input_tokens - cache_creation - cache_read)

    # Apply appropriate pricing
    base_cost = base_input * 0.003  # $3/1M tokens
    creation_cost = cache_creation * 0.003 * 1.25  # 25% premium
    cache_cost = cache_read * 0.003 * 0.10  # 90% discount
    output_cost = output_tokens * 0.015  # $15/1M tokens
    thinking_cost = thinking_tokens * 0.003  # Same as input pricing

    total_cost = base_cost + creation_cost + cache_cost + output_cost + thinking_cost

    # Calculate savings
    full_price = (input_tokens + thinking_tokens) * 0.003 + output_tokens * 0.015
    savings = full_price - total_cost

    return {
        "total": total_cost,
        "savings": savings,
        "cache_efficiency": (cache_read / (input_tokens + 0.001)) * 100 if cache_read > 0 else 0
    }
```

**Add cache metrics to markdown output:**
```python
def create_node_markdown(node_num: int, call: dict, trace_id: str):
    """Create markdown with cache metrics."""
    # ... existing code ...

    # Add cache efficiency section
    tokens = call.get("tokens", {})
    cache_read = tokens.get("cache_read_input_tokens", 0)
    cache_created = tokens.get("cache_creation_input_tokens", 0)
    thinking = tokens.get("thinking_tokens", 0)

    if cache_read > 0 or cache_created > 0:
        md.append("\n## 🚀 Cache Performance\n")
        if cache_read > 0:
            efficiency = (cache_read / tokens.get("input_tokens", 1)) * 100
            md.append(f"**Cache Hit Rate:** {efficiency:.1f}%  ")
            md.append(f"**Cached Tokens:** {cache_read:,}  ")
            savings = (cache_read / 1000) * 0.003 * 0.90  # 90% discount
            md.append(f"**Cost Savings:** ${savings:.6f}  ")
        if cache_created > 0:
            md.append(f"**Cache Created:** {cache_created:,} tokens  ")

    if thinking > 0:
        md.append("\n## 💭 Thinking Process\n")
        md.append(f"**Thinking Tokens:** {thinking:,}  ")
        md.append(f"**Thinking Cost:** ${(thinking/1000 * 0.003):.6f}  ")

        # Include thinking content if available
        thinking_text = call.get("thinking", "")
        if thinking_text:
            md.append("\n<details>")
            md.append("<summary>View Thinking Process</summary>\n")
            md.append("```")
            md.append(thinking_text[:5000])  # Truncate if too long
            if len(thinking_text) > 5000:
                md.append("\n... (truncated)")
            md.append("```")
            md.append("</details>\n")
```

### Phase 7: Testing

#### 7.1 Create Test for Cache-Aware Cost Calculation

**File: `tests/test_core/test_metrics_cache.py`**
```python
"""Test cache-aware cost calculations in metrics."""

import pytest
from pflow.core.metrics import MetricsCollector

class TestCacheAwareCosts:
    """Test cost calculations with cache tokens."""

    def test_cache_discount_applied(self):
        """Test that cache read tokens get 90% discount."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "model": "anthropic/claude-sonnet-4-0",
                "input_tokens": 10000,  # Total including cache
                "output_tokens": 500,
                "cache_creation_input_tokens": 2000,
                "cache_read_input_tokens": 5000,  # Should be 90% cheaper
                "is_planner": True
            }
        ]

        costs = collector.calculate_costs(llm_calls)

        # Expected calculation:
        # Base input: 3000 tokens (10000 - 2000 - 5000) at $3/1M = $0.000009
        # Cache creation: 2000 tokens at $3.75/1M (25% premium) = $0.0000075
        # Cache read: 5000 tokens at $0.30/1M (90% discount) = $0.0000015
        # Output: 500 tokens at $15/1M = $0.0000075
        # Total: $0.000024

        assert costs["total"] == pytest.approx(0.000024, rel=1e-6)

    def test_cache_efficiency_calculation(self):
        """Test cache hit rate calculation."""
        collector = MetricsCollector()

        llm_calls = [
            {
                "input_tokens": 10000,
                "cache_read_input_tokens": 6000,
                "output_tokens": 500
            },
            {
                "input_tokens": 5000,
                "cache_read_input_tokens": 3000,
                "output_tokens": 300
            }
        ]

        summary = collector.get_summary(llm_calls)

        # Total input: 15000, cache read: 9000
        # Hit rate: 9000/15000 = 60%
        assert summary["metrics"]["total"]["cache_hit_rate"] == 60.0
```

### Phase 8: Documentation

#### 8.1 Update CLAUDE.md

Add a new section about metrics and tracing:

```markdown
## Metrics and Tracing with Anthropic SDK

### Cache Token Tracking
The system tracks and applies appropriate pricing for cached tokens:
- **Cache Creation**: 25% premium over base price
- **Cache Read**: 90% discount from base price
- **Automatic Detection**: Cache tokens extracted from Anthropic responses

### Thinking Token Tracking
When using the Anthropic SDK with thinking enabled:
- Thinking tokens are tracked separately
- Thinking content can be stored for debugging
- Thinking process shown in trace analysis

### Viewing Cache Performance
```bash
# Generate trace with cache metrics
uv run pflow --trace-planner "create a changelog workflow"

# Analyze with cache visualization
./scripts/analyze-trace/latest.sh
```

### JSON Output Enhancements
With `--output-format json`, you get:
- `cache_tokens_created`: Tokens used to create cache
- `cache_tokens_read`: Tokens read from cache
- `cache_hit_rate`: Percentage of input from cache
- `cache_savings_usd`: Money saved from caching
- `tokens_thinking`: Thinking process tokens

### Cost Savings Example
```
First request: $0.045 (full price)
Second request: $0.008 (82% cached, saved $0.037)
Third request: $0.006 (86% cached, saved $0.039)
```
```

## Implementation Timeline

### Day 1: Core Cost Calculation
- Update MetricsCollector with cache-aware pricing
- Add thinking token tracking
- Test cost calculations

### Day 2: Trace Integration
- Update TraceCollector for enhanced metrics
- Update WorkflowTraceCollector
- Test trace generation

### Day 3: Output and Visualization
- Update JSON output format
- Enhance analysis scripts
- Add cache efficiency visualization

### Day 4: Testing and Documentation
- Write comprehensive tests
- Update documentation
- Test with real Anthropic API

## Success Metrics

### Quantitative
- ✅ Cache read tokens get 90% discount in cost calculation
- ✅ Cache hit rate displayed in metrics
- ✅ Thinking tokens tracked separately
- ✅ Cache savings shown in dollars

### Qualitative
- ✅ Users can see cache efficiency in traces
- ✅ Cost savings are transparent
- ✅ Thinking process can be debugged
- ✅ JSON output includes all new metrics

## Summary

This implementation enhances pflow's metrics system to fully support Anthropic's advanced features:

1. **Cache-aware pricing** - Correctly applies 90% discount for cached tokens
2. **Thinking tracking** - Captures reasoning process and tokens
3. **Enhanced visualization** - Shows cache efficiency and savings
4. **Complete integration** - Works with existing trace and JSON output systems

The key insight is that most infrastructure already exists - we just need to:
1. Fix the cost calculation to apply cache discounts
2. Aggregate cache tokens in metrics
3. Display cache efficiency in output

Total implementation effort: ~3-4 days