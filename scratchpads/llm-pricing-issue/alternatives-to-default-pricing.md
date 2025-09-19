# Alternatives to Default Pricing for Unknown Models

## The Problem
Currently, when we encounter an unknown model, we fall back to a default price (gpt-4o-mini rates). This is dangerous because:
- New expensive models would be severely underpriced
- New cheap models would be overpriced
- Users have no visibility into pricing errors
- Could lead to significant financial discrepancies

## Option 1: Fail Fast with Clear Error
**Approach**: Raise an exception when encountering unknown models
```python
def get_model_pricing(model: str) -> dict[str, float]:
    canonical_model = MODEL_ALIASES.get(model, model)
    if canonical_model not in MODEL_PRICING:
        raise ValueError(
            f"Unknown model '{model}' - pricing not available. "
            f"Please update MODEL_PRICING in llm_pricing.py or use a known model."
        )
    return MODEL_PRICING[canonical_model]
```

**Pros**:
- ✅ No silent failures
- ✅ Forces us to keep pricing updated
- ✅ Users know immediately something is wrong

**Cons**:
- ❌ Workflows might break when new models are released
- ❌ Requires manual updates for every new model

## Option 2: Warning with Default
**Approach**: Use default but emit a clear warning
```python
import warnings

def get_model_pricing(model: str) -> dict[str, float]:
    canonical_model = MODEL_ALIASES.get(model, model)
    if canonical_model not in MODEL_PRICING:
        warnings.warn(
            f"Model '{model}' not in pricing table. Using default pricing "
            f"(${DEFAULT_PRICING['input']}/{DEFAULT_PRICING['output']} per M tokens). "
            f"Actual costs may vary significantly!",
            UserWarning
        )
        return DEFAULT_PRICING
    return MODEL_PRICING[canonical_model]
```

**Pros**:
- ✅ Workflows continue to run
- ✅ Users are notified of potential pricing issues
- ✅ Non-breaking for existing workflows

**Cons**:
- ❌ Warnings might be missed
- ❌ Still using incorrect pricing

## Option 3: Model Provider-Based Estimates
**Approach**: Use provider-specific pricing tiers
```python
PROVIDER_DEFAULTS = {
    "anthropic/": {"input": 3.00, "output": 15.00},  # Assume mid-tier
    "gpt-": {"input": 5.00, "output": 15.00},        # Assume GPT-4 tier
    "gemini/": {"input": 0.30, "output": 1.20},      # Assume mid-tier
    "o1": {"input": 15.00, "output": 60.00},         # Reasoning models expensive
}

def get_model_pricing(model: str) -> dict[str, float]:
    canonical_model = MODEL_ALIASES.get(model, model)
    if canonical_model in MODEL_PRICING:
        return MODEL_PRICING[canonical_model]

    # Try to guess based on provider
    for prefix, pricing in PROVIDER_DEFAULTS.items():
        if canonical_model.startswith(prefix):
            warnings.warn(f"Using estimated {prefix}* pricing for '{model}'")
            return pricing

    # Complete unknown
    raise ValueError(f"Cannot estimate pricing for '{model}'")
```

**Pros**:
- ✅ Better estimates than single default
- ✅ Provider patterns are somewhat predictable

**Cons**:
- ❌ Still guessing
- ❌ Could be very wrong for outlier models

## Option 4: Zero-Cost with Explicit Warning
**Approach**: Set unknown models to zero cost, forcing awareness
```python
def get_model_pricing(model: str) -> dict[str, float]:
    canonical_model = MODEL_ALIASES.get(model, model)
    if canonical_model not in MODEL_PRICING:
        logger.error(f"PRICING ERROR: Model '{model}' has no pricing data - showing $0 cost")
        return {"input": 0.0, "output": 0.0}
    return MODEL_PRICING[canonical_model]
```

**Pros**:
- ✅ Makes pricing errors VERY obvious
- ✅ No risk of overcharging
- ✅ Forces users to notice and report

**Cons**:
- ❌ No cost tracking for new models
- ❌ Might miss costs entirely

## Option 5: External Pricing Service
**Approach**: Query pricing from an external source (API or file)
```python
def fetch_latest_pricing():
    # Could check a GitHub repo, API, or local config file
    try:
        response = requests.get("https://api.example.com/llm-pricing")
        return response.json()
    except:
        return None

CACHED_EXTERNAL_PRICING = fetch_latest_pricing()

def get_model_pricing(model: str) -> dict[str, float]:
    canonical_model = MODEL_ALIASES.get(model, model)

    # Check local first
    if canonical_model in MODEL_PRICING:
        return MODEL_PRICING[canonical_model]

    # Check external cache
    if CACHED_EXTERNAL_PRICING and canonical_model in CACHED_EXTERNAL_PRICING:
        return CACHED_EXTERNAL_PRICING[canonical_model]

    # Fail
    raise ValueError(f"No pricing available for '{model}'")
```

**Pros**:
- ✅ Always up-to-date
- ✅ No manual updates needed

**Cons**:
- ❌ External dependency
- ❌ Network requirements
- ❌ Complexity

## Recommendation

**For MVP/Current State**: Option 1 (Fail Fast) or Option 2 (Warning with Default)
- Simple to implement
- Makes issues visible
- No external dependencies

**Long-term**: Option 5 (External Pricing) or maintain a more comprehensive pricing table
- Could maintain a community pricing file on GitHub
- Regular updates through PRs
- pflow could check for updates periodically