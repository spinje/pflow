"""Unit tests for the below-min prompt-cache detectors."""

from pflow.core.cache_analysis.below_min_tokens_detector import (
    BatchPrewarmBelowMinEvidence,
    BelowMinTokensEvidence,
    detect,
    detect_batch_prewarm_below_min,
    is_below_min_cache,
    is_likely_below_min_cache,
)
from pflow.core.llm_capabilities import CONSERVATIVE_FLOOR


def _evidence(**overrides: object) -> BelowMinTokensEvidence:
    kwargs = {
        "node_id": "draft",
        "model": "anthropic/claude-sonnet-4-5",
        "declared_prompt_cache": ["concept"],
    }
    kwargs.update(overrides)
    return BelowMinTokensEvidence(**kwargs)  # type: ignore[arg-type]


def test_no_prompt_cache_returns_none() -> None:
    assert detect(_evidence(declared_prompt_cache=[])) is None


def test_empty_model_returns_none() -> None:
    assert detect(_evidence(model="")) is None


def test_predicted_tokens_at_or_above_threshold_returns_none() -> None:
    assert detect(_evidence(estimated_tokens=1024, estimated_data_source="estimator")) is None


def test_predicted_tokens_below_threshold_returns_finding() -> None:
    finding = detect(_evidence(estimated_tokens=512, estimated_data_source="estimator"))

    assert finding is not None
    assert finding.node_id == "draft"
    assert finding.evidence_kind == "predicted"
    assert finding.cacheable_tokens == 512
    assert finding.min_tokens == 1024


def test_predicted_trace_source_returns_none() -> None:
    assert detect(_evidence(estimated_tokens=512, estimated_data_source="trace")) is None


def test_predicted_missing_or_zero_estimate_returns_none() -> None:
    assert detect(_evidence(estimated_tokens=None, estimated_data_source="estimator")) is None
    assert detect(_evidence(estimated_tokens=0, estimated_data_source="estimator")) is None


def test_observed_requires_explicit_has_observed_flag() -> None:
    assert (
        detect(
            _evidence(
                observed_creation_tokens=0,
                observed_read_tokens=0,
                estimated_tokens=None,
                estimated_data_source=None,
            )
        )
        is None
    )


def test_observed_cache_activity_returns_none() -> None:
    assert detect(_evidence(has_observed=True, observed_creation_tokens=10, observed_read_tokens=0)) is None
    assert detect(_evidence(has_observed=True, observed_creation_tokens=0, observed_read_tokens=10)) is None


def test_observed_zero_cache_activity_returns_finding() -> None:
    finding = detect(_evidence(has_observed=True, observed_creation_tokens=0, observed_read_tokens=0))

    assert finding is not None
    assert finding.evidence_kind == "observed"
    assert finding.cacheable_tokens == 0


def test_observed_tier_wins_over_predicted_data() -> None:
    finding = detect(
        _evidence(
            has_observed=True,
            observed_creation_tokens=0,
            observed_read_tokens=0,
            estimated_tokens=5000,
            estimated_data_source="estimator",
        )
    )

    assert finding is not None
    assert finding.evidence_kind == "observed"


def test_provider_notes_are_provider_specific() -> None:
    anthropic = detect(_evidence(model="anthropic/claude-sonnet-4-5", estimated_tokens=512))
    gemini = detect(_evidence(model="gemini/gemini-2.5-pro", estimated_tokens=512))
    openai = detect(_evidence(model="openai/gpt-5", estimated_tokens=512))
    unknown = detect(_evidence(model="custom/model", estimated_tokens=512))

    assert anthropic is not None
    assert "cache_control markers" in anthropic.provider_note
    assert gemini is not None
    assert "implicit cache may still apply" in gemini.provider_note
    assert openai is not None
    assert openai.provider_note == ""
    assert unknown is not None
    assert unknown.provider_note == ""


# ---------------------------------------------------------------------------
# detect_batch_prewarm_below_min — analyzer-only counterpart for prewarm
# declarations whose static prefix is below the provider minimum.
# ---------------------------------------------------------------------------


def _prewarm_evidence(**overrides: object) -> BatchPrewarmBelowMinEvidence:
    kwargs = {
        "node_id": "score",
        "model": "anthropic/claude-sonnet-4-5",
        "prefix_tokens": 512,
        "batch_alias": "item",
    }
    kwargs.update(overrides)
    return BatchPrewarmBelowMinEvidence(**kwargs)  # type: ignore[arg-type]


def test_prewarm_below_min_prefix_under_threshold_returns_finding() -> None:
    finding = detect_batch_prewarm_below_min(_prewarm_evidence(prefix_tokens=512))

    assert finding is not None
    assert finding.node_id == "score"
    assert finding.prefix_tokens == 512
    assert finding.min_tokens == 1024
    assert finding.batch_alias == "item"
    assert "cache_control markers" in finding.provider_note


def test_prewarm_below_min_prefix_at_threshold_returns_none() -> None:
    assert detect_batch_prewarm_below_min(_prewarm_evidence(prefix_tokens=1024)) is None


def test_prewarm_below_min_prefix_above_threshold_returns_none() -> None:
    assert detect_batch_prewarm_below_min(_prewarm_evidence(prefix_tokens=4096)) is None


def test_prewarm_below_min_zero_or_negative_prefix_returns_none() -> None:
    """Zero-prefix is the ``cache.prewarm-no-prefix`` case; conflating them
    would double-emit. The detector defends against bad callers."""
    assert detect_batch_prewarm_below_min(_prewarm_evidence(prefix_tokens=0)) is None
    assert detect_batch_prewarm_below_min(_prewarm_evidence(prefix_tokens=-1)) is None


def test_prewarm_below_min_empty_model_returns_none() -> None:
    assert detect_batch_prewarm_below_min(_prewarm_evidence(model="")) is None


def test_prewarm_below_min_provider_notes_are_provider_specific() -> None:
    anthropic = detect_batch_prewarm_below_min(_prewarm_evidence(model="anthropic/claude-sonnet-4-5"))
    gemini = detect_batch_prewarm_below_min(_prewarm_evidence(model="gemini/gemini-2.5-flash"))
    openai = detect_batch_prewarm_below_min(_prewarm_evidence(model="openai/gpt-5"))

    assert anthropic is not None
    assert "cache_control markers" in anthropic.provider_note
    assert gemini is not None
    assert "implicit cache may still apply" in gemini.provider_note
    assert openai is not None
    assert openai.provider_note == ""


def test_prewarm_below_min_threshold_varies_by_model() -> None:
    """Sonnet-4-5 is 1024; Opus-4-7 is 4096. A 2048-token prefix is above
    one and below the other — verifies threshold lookup is not hardcoded."""
    sonnet = detect_batch_prewarm_below_min(_prewarm_evidence(model="anthropic/claude-sonnet-4-5", prefix_tokens=2048))
    opus = detect_batch_prewarm_below_min(_prewarm_evidence(model="anthropic/claude-opus-4-7", prefix_tokens=2048))

    assert sonnet is None
    assert opus is not None
    assert opus.min_tokens == 4096


# ---------------------------------------------------------------------------
# is_below_min_cache vs is_likely_below_min_cache (Bundle 5: predicate split)
# ---------------------------------------------------------------------------


def test_is_below_min_cache_returns_false_when_tokens_is_none() -> None:
    """CLAIM variant: no opinion without token evidence."""
    assert is_below_min_cache("anthropic/claude-sonnet-4-5", None) is False
    assert is_below_min_cache("", None) is False
    assert is_below_min_cache(None, None) is False


def test_is_below_min_cache_returns_false_for_empty_or_none_model() -> None:
    """CLAIM variant: don't claim below-min without a known model.

    Heterogeneous-batch rows carry ``model=""``. Emitting a "below
    {empty}'s {X}-token minimum" message would be agent-hostile, so the
    predicate stays silent.
    """
    assert is_below_min_cache("", 500) is False
    assert is_below_min_cache("", 0) is False
    assert is_below_min_cache(None, 500) is False


def test_is_below_min_cache_compares_against_get_min_for_known_model() -> None:
    # Sonnet-4-5 min is 1024.
    assert is_below_min_cache("anthropic/claude-sonnet-4-5", 500) is True
    assert is_below_min_cache("anthropic/claude-sonnet-4-5", 1023) is True
    assert is_below_min_cache("anthropic/claude-sonnet-4-5", 1024) is False
    assert is_below_min_cache("anthropic/claude-sonnet-4-5", 2000) is False


def test_is_likely_below_min_cache_returns_false_when_tokens_is_none() -> None:
    """SUPPRESSION variant: no opinion without token evidence."""
    assert is_likely_below_min_cache("anthropic/claude-sonnet-4-5", None) is False
    assert is_likely_below_min_cache("", None) is False
    assert is_likely_below_min_cache(None, None) is False


def test_is_likely_below_min_cache_uses_conservative_floor_for_empty_model() -> None:
    """SUPPRESSION variant: treat empty/unknown model as conservative-floor.

    The asymmetry with ``is_below_min_cache`` matters for heterogeneous-
    batch rows: at suppression-gate sites, we'd rather suppress a
    recommendation that might not pay off than emit one against an
    unknown floor.
    """
    # Conservative floor is the safe pessimistic threshold (4096 today).
    assert is_likely_below_min_cache("", CONSERVATIVE_FLOOR - 1) is True
    assert is_likely_below_min_cache("", 0) is True
    assert is_likely_below_min_cache("", CONSERVATIVE_FLOOR) is False
    assert is_likely_below_min_cache("", CONSERVATIVE_FLOOR + 1000) is False
    # None model behaves the same as empty.
    assert is_likely_below_min_cache(None, CONSERVATIVE_FLOOR - 1) is True
    assert is_likely_below_min_cache(None, CONSERVATIVE_FLOOR) is False


def test_is_likely_below_min_cache_matches_known_model_threshold() -> None:
    """For a known model, both predicates compare against
    ``get_min_cache_tokens`` (which returns the model-specific threshold)."""
    # Sonnet-4-5 min is 1024; the model-specific compare wins over the floor.
    assert is_likely_below_min_cache("anthropic/claude-sonnet-4-5", 1023) is True
    assert is_likely_below_min_cache("anthropic/claude-sonnet-4-5", 1024) is False


def test_predicates_only_disagree_on_empty_model_branch() -> None:
    """Lock the asymmetry contract: identical for known model, opposite for
    empty model on sub-floor token counts. Regression for the Bundle 5
    split; mutation-testing the docstring examples."""
    # Identical: known model.
    for tokens in (0, 500, 1024, 2048, 4096, 8000):
        assert is_below_min_cache("anthropic/claude-sonnet-4-5", tokens) == is_likely_below_min_cache(
            "anthropic/claude-sonnet-4-5", tokens
        )
    # Asymmetric: empty model + sub-floor tokens.
    assert is_below_min_cache("", 500) is False
    assert is_likely_below_min_cache("", 500) is True
    # Symmetric again: empty model + above-floor tokens (neither flags).
    assert is_below_min_cache("", CONSERVATIVE_FLOOR + 1) is False
    assert is_likely_below_min_cache("", CONSERVATIVE_FLOOR + 1) is False
