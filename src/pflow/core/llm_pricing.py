"""Centralized LLM pricing calculations - single source of truth for all cost calculations.

This module provides the authoritative pricing data and calculation logic for all LLM
models used in pflow. All cost calculations should use this module to ensure consistency.
"""

from typing import Any

# Version tracking for pricing updates
PRICING_VERSION = "2025-12-19"

# Comprehensive model pricing per million tokens
# Prices are in USD per million tokens for input and output
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic models
    "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "anthropic/claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "anthropic/claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "anthropic/claude-sonnet-4-0": {"input": 3.00, "output": 15.00},
    "anthropic/claude-sonnet-4-5": {"input": 3.00, "output": 15.00},  # Same pricing as 4.0
    "anthropic/claude-opus-4-1-20250805": {"input": 15, "output": 75},
    "anthropic/claude-haiku-4-5-20251001": {"input": 1, "output": 5},
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    # OpenAI models
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-5.2-pro": {"input": 21.00, "output": 168.00},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    # Google models (support both short and full format)
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini/gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini/gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash-8b": {"input": 0.0375, "output": 0.15},
    "gemini/gemini-1.5-flash-8b": {"input": 0.0375, "output": 0.15},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini/gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini/gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini/gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini/gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini/gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini/gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
}

# Model aliases mapping - maps common aliases to their canonical names
MODEL_ALIASES = {
    # Anthropic aliases
    "claude-3-opus": "anthropic/claude-3-opus-20240229",
    "claude-3-sonnet": "anthropic/claude-3-sonnet-20240229",
    "claude-3-haiku": "anthropic/claude-3-haiku-20240307",
    "claude-3.5-sonnet": "anthropic/claude-3-5-sonnet-20241022",
    "claude-3.5-haiku": "anthropic/claude-3-5-haiku-latest",
    "claude-haiku-4.5": "claude-haiku-4-5-20251001",
    "claude-4-opus": "anthropic/claude-opus-4-0",
    "claude-4-sonnet": "anthropic/claude-sonnet-4-0",
    "claude-sonnet-4.5": "anthropic/claude-sonnet-4-5",
    "claude-opus-4.1": "anthropic/claude-opus-4-1-20250805",
    # OpenAI aliases
    "4o": "gpt-4o",
    "4o-mini": "gpt-4o-mini",
    "3.5": "gpt-3.5-turbo",
    "chatgpt": "gpt-3.5-turbo",
    "4": "gpt-4",
    "gpt4": "gpt-4",
    "4t": "gpt-4-turbo",
    "4-turbo": "gpt-4-turbo",
    "5.2": "gpt-5.2",
    "gpt5": "gpt-5.2",
    "5.2-pro": "gpt-5.2-pro",
    # Gemini aliases (without prefix)
    "gemini-pro": "gemini/gemini-pro",
    "gemini-1.5-pro": "gemini/gemini-1.5-pro",
    "gemini-1.5-pro-latest": "gemini/gemini-1.5-pro",
    "gemini-1.5-flash": "gemini/gemini-1.5-flash",
    "gemini-1.5-flash-latest": "gemini/gemini-1.5-flash",
    "gemini-1.5-flash-8b": "gemini/gemini-1.5-flash-8b",
    "gemini-1.5-flash-8b-latest": "gemini/gemini-1.5-flash-8b",
    "gemini-2.0-flash": "gemini/gemini-2.0-flash",
    "gemini-2.0-flash-lite": "gemini/gemini-2.0-flash-lite",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    "gemini-2.5-flash": "gemini/gemini-2.5-flash",
    "gemini-2.5-flash-lite": "gemini/gemini-2.5-flash-lite",
    "gemini-3-flash": "gemini/gemini-3-flash-preview",
    "gemini-3-flash-preview": "gemini/gemini-3-flash-preview",
}


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
    # Resolve aliases first
    canonical_model = MODEL_ALIASES.get(model, model)  # Use alias if exists, otherwise use original

    # Get pricing or fail with helpful error
    if canonical_model not in MODEL_PRICING:
        # Check if it's close to a known model (common typos)
        suggestions = [m for m in MODEL_PRICING if model.lower() in m.lower()][:3]

        error_msg = f"Unknown model '{model}' - pricing not available. "
        if suggestions:
            error_msg += f"Did you mean one of: {', '.join(suggestions)}? "
        error_msg += "Please update MODEL_PRICING in llm_pricing.py or use a known model."

        raise ValueError(error_msg)

    pricing: dict[str, float] = MODEL_PRICING[canonical_model]

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
        "pricing_model": canonical_model if canonical_model in MODEL_PRICING else "default",
        "pricing_version": PRICING_VERSION,
    }


def get_model_pricing(model: str) -> dict[str, float]:
    """Get pricing for a specific model.

    Args:
        model: Model identifier (supports aliases)

    Returns:
        Dictionary with "input" and "output" prices per million tokens

    Raises:
        ValueError: If model is not in the pricing table
    """
    # Resolve aliases first
    canonical_model = MODEL_ALIASES.get(model, model)

    # Get pricing or fail with helpful error
    if canonical_model not in MODEL_PRICING:
        # Check if it's close to a known model (common typos)
        suggestions = [m for m in MODEL_PRICING if model.lower() in m.lower()][:3]

        error_msg = f"Unknown model '{model}' - pricing not available. "
        if suggestions:
            error_msg += f"Did you mean one of: {', '.join(suggestions)}? "
        error_msg += "Please update MODEL_PRICING in llm_pricing.py or use a known model."

        raise ValueError(error_msg)

    pricing_data: dict[str, float] = MODEL_PRICING[canonical_model]
    return pricing_data
