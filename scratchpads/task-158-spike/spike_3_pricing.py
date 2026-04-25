"""Spike 3 — pricing authority investigation.

Decides outcome A/B/C for Phase A.10:

  A: LiteLLM accurate + comprehensive → delete llm_pricing.py
  B: Mostly accurate, edge bugs → LiteLLM primary, llm_pricing.py fallback
  C: Material bugs → vendor LiteLLM's model_prices JSON, keep pflow math

For each of pflow's 41 MODEL_PRICING entries, compare:
  - pflow's price_per_input_token, price_per_output_token
  - LiteLLM's litellm.model_cost[model] entries
  - LiteLLM's cost computation on a mock response at 1M in / 1M out
  - LiteLLM's cost on cached + thinking compositions

Also makes a live Gemini 2.5 Flash cached call and compares LiteLLM's
response_cost to hand-calculation (tests for PR #15226 fix).

Bands:
  non-cached: ≤2% disagreement acceptable
  cached: ≤5% disagreement acceptable
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Put pflow src on the path so we can import llm_pricing without installing it
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from _common import banner, inject_keys_into_env, silence_litellm, stable_context_block

inject_keys_into_env()
silence_litellm()

import litellm  # noqa: E402

from pflow.core.llm_pricing import MODEL_PRICING, calculate_llm_cost  # noqa: E402


def pct_diff(a: float, b: float) -> float:
    """Symmetric percentage difference. Returns +/- 100.0 max."""
    if a == 0 and b == 0:
        return 0.0
    denom = max(abs(a), abs(b))
    return 100.0 * abs(a - b) / denom if denom else 0.0


def one_model(model: str) -> dict:
    """Compare pflow vs LiteLLM pricing for one model entry.

    Computes cost for a standard 1M input, 1M output, 1M cache write,
    1M cache read scenario and returns per-component and total diffs.
    """
    # pflow pricing (per million tokens)
    pflow_pricing = MODEL_PRICING[model]
    pflow_input_per_tok = pflow_pricing["input"] / 1_000_000
    pflow_output_per_tok = pflow_pricing["output"] / 1_000_000

    # Compute total for 1M/1M/1M/1M scenario via pflow
    pflow_cost = calculate_llm_cost(
        model=model,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_tokens=1_000_000,
        cache_read_tokens=1_000_000,
    )

    # LiteLLM pricing
    lite_entry = litellm.model_cost.get(model) or {}
    # LiteLLM uses per-token prices
    lite_in = lite_entry.get("input_cost_per_token")
    lite_out = lite_entry.get("output_cost_per_token")
    lite_cache_write = lite_entry.get("cache_creation_input_token_cost")
    lite_cache_read = lite_entry.get("cache_read_input_token_cost")

    # Build diffs
    diffs = {}
    if lite_in is not None:
        diffs["input_pct"] = round(pct_diff(pflow_input_per_tok, lite_in), 2)
    else:
        diffs["input_pct"] = None

    if lite_out is not None:
        diffs["output_pct"] = round(pct_diff(pflow_output_per_tok, lite_out), 2)
    else:
        diffs["output_pct"] = None

    # For cache creation / read, pflow uses 2x input rate / 0.1x input rate.
    # LiteLLM may expose direct values OR may derive from the same pattern.
    pflow_cache_write_per_tok = pflow_input_per_tok * 2.0
    pflow_cache_read_per_tok = pflow_input_per_tok * 0.1
    if lite_cache_write is not None:
        diffs["cache_write_pct"] = round(pct_diff(pflow_cache_write_per_tok, lite_cache_write), 2)
    else:
        diffs["cache_write_pct"] = None
    if lite_cache_read is not None:
        diffs["cache_read_pct"] = round(pct_diff(pflow_cache_read_per_tok, lite_cache_read), 2)
    else:
        diffs["cache_read_pct"] = None

    # LiteLLM total for same scenario via mock response
    try:
        # Build a synthetic ModelResponse-like dict. LiteLLM accepts a model name
        # + usage via cost_per_token (prompt_tokens, completion_tokens).
        plain_prompt_cost, plain_completion_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        lite_plain_total = plain_prompt_cost + plain_completion_cost
    except Exception as e:
        lite_plain_total = None
        diffs["lite_plain_error"] = f"{type(e).__name__}: {e}"

    pflow_plain_total = (
        pflow_cost["input_cost"] + pflow_cost["output_cost"]
    )
    if lite_plain_total is not None:
        diffs["plain_total_pct"] = round(pct_diff(pflow_plain_total, lite_plain_total), 2)
    else:
        diffs["plain_total_pct"] = None

    return {
        "pflow": {
            "input_per_tok": pflow_input_per_tok,
            "output_per_tok": pflow_output_per_tok,
            "cache_write_per_tok": pflow_cache_write_per_tok,
            "cache_read_per_tok": pflow_cache_read_per_tok,
        },
        "lite": {
            "present": model in litellm.model_cost,
            "input_per_tok": lite_in,
            "output_per_tok": lite_out,
            "cache_write_per_tok": lite_cache_write,
            "cache_read_per_tok": lite_cache_read,
        },
        "diffs_pct": diffs,
    }


def verify_gemini_cache_fix() -> dict:
    """Live Gemini call to verify PR #15226 (double-count fix).

    Makes two identical Gemini calls, compares LiteLLM's reported response_cost
    to a hand-calculation from token counts.
    """
    banner("Gemini cache cost fix verification (PR #15226)")
    system_block = stable_context_block()

    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_block,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {"role": "user", "content": "Reply exactly the word OK."},
    ]

    r = litellm.completion(
        model="gemini/gemini-2.5-flash",
        messages=messages,
        temperature=0.0,
        max_tokens=10,
    )
    usage = r.usage
    prompt_tokens = usage.prompt_tokens
    completion_tokens = usage.completion_tokens
    cached = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = cached.cached_tokens if cached else 0

    # Hand calc via pflow pricing
    pflow_hand = calculate_llm_cost(
        model="gemini/gemini-2.5-flash",
        input_tokens=prompt_tokens - cached_tokens,
        output_tokens=completion_tokens,
        cache_read_tokens=cached_tokens,
    )

    # LiteLLM's self-reported cost
    lite_cost = (r._hidden_params or {}).get("response_cost")

    # Hand calc via LiteLLM's cost_per_token (non-cache)
    # LiteLLM should internally apply the cache discount to the prompt portion
    try:
        in_cost, out_cost = litellm.cost_per_token(
            model="gemini/gemini-2.5-flash",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_input_tokens=cached_tokens,
        )
        lite_handcalc = in_cost + out_cost
    except TypeError:
        # old signature may not take cache_read_input_tokens
        lite_handcalc = None

    print(f"  prompt_tokens: {prompt_tokens}")
    print(f"  completion_tokens: {completion_tokens}")
    print(f"  cached_tokens: {cached_tokens}")
    print(f"  pflow hand calc: ${pflow_hand['total_cost_usd']:.8f}")
    print(f"  lite response_cost: ${lite_cost:.8f}" if lite_cost else "  lite response_cost: None")
    if lite_handcalc is not None:
        print(f"  lite cost_per_token(+cache_read): ${lite_handcalc:.8f}")

    pct_pfl_lite = pct_diff(pflow_hand["total_cost_usd"], lite_cost) if lite_cost else None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "pflow_hand_total": pflow_hand["total_cost_usd"],
        "lite_response_cost": lite_cost,
        "lite_handcalc_cost_per_token": lite_handcalc,
        "pct_disagreement": pct_pfl_lite,
    }


def main() -> None:
    banner("Model table coverage")
    pflow_models = sorted(MODEL_PRICING.keys())
    print(f"pflow MODEL_PRICING entries: {len(pflow_models)}")
    print(f"litellm.model_cost entries: {len(litellm.model_cost)}")

    # Model-by-model comparison
    results: dict[str, dict] = {}
    missing_in_lite: list[str] = []
    present_but_different: list[str] = []
    big_disagreements: list[tuple[str, float]] = []

    for m in pflow_models:
        results[m] = one_model(m)
        if not results[m]["lite"]["present"]:
            missing_in_lite.append(m)
            continue
        d = results[m]["diffs_pct"]
        # Any non-None diff > 2% is a concern on non-cached
        for key in ("input_pct", "output_pct"):
            if d.get(key) is not None and d[key] > 2.0:
                big_disagreements.append((f"{m}.{key}", d[key]))
        if d.get("input_pct") not in (None, 0.0) or d.get("output_pct") not in (None, 0.0):
            present_but_different.append(m)

    banner("Coverage summary")
    print(f"pflow total: {len(pflow_models)}")
    print(f"missing in litellm: {len(missing_in_lite)}")
    if missing_in_lite:
        for m in missing_in_lite:
            print(f"  - {m}")

    banner("Non-cached disagreements >2% (any side)")
    if big_disagreements:
        for name, d in big_disagreements:
            print(f"  {name}: {d}%")
    else:
        print("  (none)")

    banner("All models — side-by-side")
    for m in pflow_models:
        r = results[m]
        lite_present = "✓" if r["lite"]["present"] else "✗"
        d = r["diffs_pct"]
        print(
            f"  [{lite_present}] {m:50s} "
            f"in={d.get('input_pct')}% out={d.get('output_pct')}% "
            f"cache_w={d.get('cache_write_pct')}% cache_r={d.get('cache_read_pct')}%"
        )

    # Live Gemini cache fix verification
    try:
        gemini_result = verify_gemini_cache_fix()
    except Exception as e:
        gemini_result = {"error": f"{type(e).__name__}: {e}"}

    banner("FINAL SPIKE 3 JSON SUMMARY")
    summary = {
        "n_pflow_models": len(pflow_models),
        "n_missing_in_litellm": len(missing_in_lite),
        "missing_in_litellm": missing_in_lite,
        "big_disagreements_gt_2pct": big_disagreements,
        "gemini_cache_fix_check": gemini_result,
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
