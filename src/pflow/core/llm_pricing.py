"""Centralized LLM pricing calculations - single source of truth for all cost calculations.

This module provides the authoritative pricing data and calculation logic for all LLM
models used in pflow. All cost calculations should use this module to ensure consistency.
"""

from typing import Any

# Version tracking for pricing updates
PRICING_VERSION = "2025-01-15"

# Comprehensive model pricing per million tokens
# Prices are in USD per million tokens for input and output
MODEL_PRICING = {
    # Anthropic models
    "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "anthropic/claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "anthropic/claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "anthropic/claude-sonnet-4-0": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    # OpenAI models
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    # Google models
    "gemini-1.5-pro": {"input": 3.5, "output": 10.5},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

# Default pricing for unknown models (using gpt-4o-mini as fallback)
DEFAULT_PRICING = {"input": 0.15, "output": 0.60}


def calculate_llm_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    thinking_tokens: int = 0,
) -> dict[str, Any]:
    """Calculate detailed cost breakdown for an LLM call.

    Cost calculation rules:
    - Regular input/output: Standard model rates
    - Cache creation: 2x input rate (100% premium for creating cache)
    - Cache reads: 0.1x input rate (90% discount for using cached content)
    - Thinking tokens: Billed at output rate (same as regular output)

    Args:
        model: Model identifier (e.g., "anthropic/claude-3-5-sonnet-20241022")
        input_tokens: Number of regular input tokens
        output_tokens: Number of regular output tokens
        cache_creation_tokens: Number of tokens used to create cache
        cache_read_tokens: Number of tokens read from cache
        thinking_tokens: Number of thinking/reasoning tokens

    Returns:
        Dictionary with detailed cost breakdown:
        {
            "input_cost": Cost for regular input tokens,
            "output_cost": Cost for regular output tokens,
            "cache_creation_cost": Cost for creating cache (2x rate),
            "cache_read_cost": Cost for reading cache (0.1x rate),
            "thinking_cost": Cost for thinking tokens (output rate),
            "total_cost_usd": Total cost in USD,
            "pricing_model": Model used for pricing,
            "pricing_version": Version of pricing data
        }
    """
    # Get pricing for model or use default
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

    # Calculate each cost component
    # Note: Anthropic's input_tokens already EXCLUDES cache tokens per API spec
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    # Cache creation costs 100% more (2x rate)
    cache_creation_cost = (cache_creation_tokens / 1_000_000) * pricing["input"] * 2.0

    # Cache reads cost 90% less (0.1x rate)
    cache_read_cost = (cache_read_tokens / 1_000_000) * pricing["input"] * 0.1

    # Thinking tokens are billed at output rate
    thinking_cost = (thinking_tokens / 1_000_000) * pricing["output"]

    # Calculate total
    total = input_cost + output_cost + cache_creation_cost + cache_read_cost + thinking_cost

    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "cache_creation_cost": round(cache_creation_cost, 6),
        "cache_read_cost": round(cache_read_cost, 6),
        "thinking_cost": round(thinking_cost, 6),
        "total_cost_usd": round(total, 6),
        "pricing_model": model if model in MODEL_PRICING else "default",
        "pricing_version": PRICING_VERSION,
    }


def get_model_pricing(model: str) -> dict[str, float]:
    """Get pricing for a specific model.

    Args:
        model: Model identifier

    Returns:
        Dictionary with "input" and "output" prices per million tokens
    """
    return MODEL_PRICING.get(model, DEFAULT_PRICING)
