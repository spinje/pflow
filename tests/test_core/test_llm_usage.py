"""Public LLM-usage read helpers.

``input_token_total`` is the read-side counterpart of
``normalize_litellm_usage_tokens`` — it reads a trace ``llm_call`` record's
cache-INCLUSIVE input total back out. Promoted from ``trace_report``'s private
``_input_token_total`` (Task 173) so the report and the live detail panel share
one home; these pin the contract directly on the public function.
"""

from __future__ import annotations

from pflow.core.llm_usage import input_token_total


def test_returns_inclusive_input_and_cache_read() -> None:
    """``input_tokens`` is already cache-INCLUSIVE (every producer writes it that
    way); the helper returns it verbatim and surfaces ``cache_read`` only for the
    cache-% display — it never re-adds the cache tiers."""
    total_in, cache_read = input_token_total({
        "input_tokens": 26000,
        "cache_creation_input_tokens": 5000,
        "cache_read_input_tokens": 20000,
    })
    assert (total_in, cache_read) == (26000, 20000)


def test_falls_back_to_prompt_tokens_for_older_traces() -> None:
    """Older traces recorded ``prompt_tokens`` rather than ``input_tokens``."""
    assert input_token_total({"prompt_tokens": 1200}) == (1200, 0)


def test_coerces_explicit_none_to_zero() -> None:
    """A legacy cached entry can carry an explicit ``None`` (not absent); the
    ``or 0`` guard keeps the return ints so ``f"{n:,}"`` formatting can't raise."""
    assert input_token_total({"input_tokens": None, "cache_read_input_tokens": None}) == (0, 0)


def test_empty_call_is_zeroes() -> None:
    assert input_token_total({}) == (0, 0)
