"""Tests for ``pflow.core.litellm_runtime`` — the single LiteLLM import seam.

Covers:
- ``configure_litellm_defaults`` sets ``LITELLM_LOCAL_MODEL_COST_MAP=True``
  when unset.
- ``configure_litellm_defaults`` respects a user-provided value (no overwrite).
- ``import_litellm`` and ``import_litellm_exceptions`` set the env var before
  returning the module.
- ``ensure_model_priced`` merges upstream cost map on first cache miss,
  is idempotent + thread-safe, and degrades silently on fetch failure.
- Importing the helper module itself does not pull ``litellm`` into
  ``sys.modules`` (lazy-import contract).
- **Meta-test**: no production module under ``src/pflow/`` directly imports
  ``litellm`` or ``litellm.*`` — every site must route through this seam.

The CLI-level lazy-import contract (``pflow.cli.main`` import doesn't load
litellm) is covered separately in ``tests/test_cli/test_lazy_imports.py``.
"""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ENV_VAR = "LITELLM_LOCAL_MODEL_COST_MAP"


def test_configure_sets_env_var_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import configure_litellm_defaults

    configure_litellm_defaults()

    assert os.environ.get(ENV_VAR) == "True"


def test_configure_respects_user_provided_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # User opts back into remote pricing — pflow must not override.
    monkeypatch.setenv(ENV_VAR, "False")

    from pflow.core.litellm_runtime import configure_litellm_defaults

    configure_litellm_defaults()

    assert os.environ.get(ENV_VAR) == "False"


def test_configure_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import configure_litellm_defaults

    configure_litellm_defaults()
    configure_litellm_defaults()
    configure_litellm_defaults()

    assert os.environ.get(ENV_VAR) == "True"


def test_configure_silences_litellm_logger() -> None:
    # LiteLLM 1.86+ emits WARNING-level botocore/bedrock stream-preload noise at
    # import time; configure_litellm_defaults must raise the logger to CRITICAL
    # *before* import so those messages never reach stderr. Capture/restore the
    # original level so this assertion doesn't leak state to other tests.
    litellm_logger = logging.getLogger("LiteLLM")
    original_level = litellm_logger.level
    try:
        litellm_logger.setLevel(logging.NOTSET)

        from pflow.core.litellm_runtime import configure_litellm_defaults

        configure_litellm_defaults()

        assert litellm_logger.level == logging.CRITICAL
    finally:
        litellm_logger.setLevel(original_level)


def test_import_litellm_sets_env_var_and_returns_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()

    assert os.environ.get(ENV_VAR) == "True"
    # Returned module is the real litellm package
    assert litellm.__name__ == "litellm"
    # Sanity: model_cost was populated at import time
    assert isinstance(getattr(litellm, "model_cost", None), dict)


def test_import_litellm_exceptions_returns_exceptions_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import import_litellm_exceptions

    exc_mod = import_litellm_exceptions()

    assert os.environ.get(ENV_VAR) == "True"
    assert exc_mod.__name__ == "litellm.exceptions"
    # Sanity: a known exception class exists
    assert hasattr(exc_mod, "AuthenticationError")


# ---------------------------------------------------------------------------
# ensure_model_priced — hybrid bundled-first, upstream-on-miss cost map
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_upstream_attempted(monkeypatch: pytest.MonkeyPatch):
    """Reset the module-level ``_upstream_attempted`` flag between tests.

    The flag latches True after the first fetch attempt per process. Tests
    that exercise the fetch path must reset it explicitly via monkeypatch
    so the helper actually runs (instead of short-circuiting on the latch).
    Layers on top of ``tests/conftest.py::_block_upstream_cost_map_fetch``
    which pre-sets the flag to True for all tests — opting back in here
    means the helper actually enters its fetch branch.

    Also resets the validator-side latch pair so tests exercising
    ``try_load_upstream_catalog`` start with a fresh state regardless of
    test ordering.
    """
    from pflow.core import litellm_runtime

    monkeypatch.setattr(litellm_runtime, "_upstream_attempted", False)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_attempted", False)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_fetch_succeeded", False)
    return litellm_runtime


def _stub_httpx_get(monkeypatch: pytest.MonkeyPatch, upstream_map: dict) -> list[str]:
    """Stub ``httpx.get`` to return ``upstream_map`` as JSON.

    Returns a list that records every URL ``httpx.get`` was called with,
    so tests can assert call count + URL without re-deriving the mock.
    """
    import httpx

    urls_called: list[str] = []

    def fake_get(url, *args, **kwargs):
        urls_called.append(url)
        return MagicMock(
            raise_for_status=lambda: None,
            json=lambda: upstream_map,
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    return urls_called


def test_ensure_model_priced_no_op_when_model_in_bundled(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bundled-model lookup must not trigger an upstream fetch."""
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    # gemini/gemini-2.5-flash is in the bundled JSON (verified in scratchpad
    # session; if LiteLLM ever removes it from the bundle, swap to another
    # known-bundled model).
    assert "gemini/gemini-2.5-flash" in litellm.model_cost, (
        "Pick a different known-bundled model; this one is no longer bundled."
    )

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    ensure_model_priced("gemini/gemini-2.5-flash")

    assert mock_register.call_count == 0


def test_ensure_model_priced_fetches_when_model_missing(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing model triggers exactly one ``httpx.get`` + one ``register_model(dict)``.

    Verifies the dict-form is used (NOT the URL form). The URL form would
    short-circuit through ``litellm.get_model_cost_map`` and return the
    bundled backup unchanged because ``LITELLM_LOCAL_MODEL_COST_MAP=True``
    is set by pflow.
    """
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    fake_upstream = {
        "some/brand-new-model": {
            "input_cost_per_token": 1.5e-6,
            "output_cost_per_token": 9e-6,
            "litellm_provider": "gemini",
            "mode": "chat",
        },
    }
    urls_called = _stub_httpx_get(monkeypatch, fake_upstream)

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    ensure_model_priced("some/brand-new-model")

    # 1. httpx.get was called with litellm.model_cost_map_url so env-var
    #    overrides (LITELLM_MODEL_COST_MAP_URL) still apply.
    assert urls_called == [litellm.model_cost_map_url]
    # 2. register_model was called with the dict (not the URL).
    assert mock_register.call_count == 1
    assert mock_register.call_args[0][0] == fake_upstream


def test_ensure_model_priced_idempotent_across_calls(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call with a missing model is a no-op (latch via ``_upstream_attempted``)."""
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    # Stub with a non-empty dict so the empty-dict guard in the helper
    # doesn't trip and skip register_model.
    urls_called = _stub_httpx_get(monkeypatch, {"placeholder/model": {"mode": "chat"}})

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    ensure_model_priced("some/brand-new-model")
    ensure_model_priced("another/brand-new-model")
    ensure_model_priced("some/brand-new-model")

    # Exactly one fetch + one register despite three calls. The latch
    # prevents both the HTTP call and the register from repeating.
    assert len(urls_called) == 1
    assert mock_register.call_count == 1


def test_ensure_model_priced_preserves_bundled_prices_during_merge(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: bundled prices MUST survive an upstream merge.

    ``litellm.register_model`` internally does
    ``model_cost.setdefault(key, {}).update(value)`` per entry — which
    overwrites any existing key's fields with upstream values. Without
    explicit filtering, a single first-miss fetch could shift the
    *bundled* price of every model upstream happened to revise.

    This test asserts that when upstream ships a different price for a
    model already in ``litellm.model_cost``, the bundled price stays put
    AND ``register_model`` is called only with the new-key subset. Pins
    the "bundled-first determinism" half of the documented contract.
    """
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    # Simulated bundled snapshot: one priced model with deterministic cost.
    bundled_price = 1.0e-7
    monkeypatch.setattr(
        litellm,
        "model_cost",
        {
            "bundled/model": {
                "input_cost_per_token": bundled_price,
                "output_cost_per_token": 5.0e-7,
                "litellm_provider": "openai",
                "mode": "chat",
            },
        },
        raising=False,
    )

    # Upstream ships a DIFFERENT price for the bundled key + a new key.
    upstream = {
        "bundled/model": {
            "input_cost_per_token": 9.99e-6,  # very different — would obviously corrupt determinism
            "output_cost_per_token": 9.99e-6,
            "litellm_provider": "openai",
            "mode": "chat",
        },
        "new-only/model": {
            "input_cost_per_token": 2.0e-6,
            "output_cost_per_token": 3.0e-6,
            "litellm_provider": "openai",
            "mode": "chat",
        },
    }
    _stub_httpx_get(monkeypatch, upstream)

    register_calls: list[dict] = []

    def recording_register(upstream_map: dict) -> None:
        register_calls.append(upstream_map)
        # Simulate register_model's mutation contract on the FILTERED map
        # so the post-call model_cost reflects what production would see.
        for k, v in upstream_map.items():
            litellm.model_cost.setdefault(k, {}).update(v)

    monkeypatch.setattr(litellm, "register_model", recording_register)

    ensure_model_priced("new-only/model")

    # 1. Bundled price is UNTOUCHED — the upstream revision did not leak in.
    assert litellm.model_cost["bundled/model"]["input_cost_per_token"] == bundled_price, (
        "Upstream price leaked into bundled key — register_model received "
        "an unfiltered map, violating the bundled-first determinism contract."
    )
    # 2. register_model received ONLY the new-key subset.
    assert len(register_calls) == 1
    assert register_calls[0] == {"new-only/model": upstream["new-only/model"]}


def test_ensure_model_priced_skips_register_when_no_new_models(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When upstream contains only already-bundled keys, register_model is skipped.

    Avoids a no-op call that would still spam stderr per LiteLLM entry.
    The latch still sets so we don't re-fetch.
    """
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(
        litellm,
        "model_cost",
        {"bundled/model": {"input_cost_per_token": 1.0e-7}},
        raising=False,
    )
    # Upstream has the same key (or any subset of bundled) — nothing new.
    _stub_httpx_get(monkeypatch, {"bundled/model": {"input_cost_per_token": 9.99e-6}})

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    ensure_model_priced("never-going-to-be-found/model")

    # register_model was not called at all.
    assert mock_register.call_count == 0
    # Latch is set — no retry on subsequent calls.
    assert litellm_runtime._upstream_attempted is True


def test_ensure_model_priced_silent_on_fetch_failure(
    reset_upstream_attempted,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed upstream fetch (e.g. offline, DNS, GitHub down) must not raise.

    Injects the failure at ``httpx.get`` — the actual network boundary —
    rather than at ``register_model``. This exercises the same code path
    a user would hit on a real network outage. The latch must still set
    (one attempt per process; no retry storms), the debug log must fire
    for ``--verbose`` visibility, and ``register_model`` must NOT be called
    (we never got the upstream data, so there's nothing to register).
    """
    import httpx

    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    def failing_get(url, *args, **kwargs):
        raise httpx.ConnectError("simulated network outage")

    monkeypatch.setattr(httpx, "get", failing_get)

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    caplog.set_level("DEBUG", logger="pflow.core.litellm_runtime")

    # Must not raise.
    ensure_model_priced("some/brand-new-model")

    # Latch is set even on failure — we don't retry indefinitely.
    assert litellm_runtime._upstream_attempted is True
    # Debug log captures the failure for --verbose visibility.
    assert any("Upstream cost map fetch failed" in record.message for record in caplog.records), (
        f"Expected debug log; got records: {[r.message for r in caplog.records]}"
    )
    # No upstream data ever made it to register_model.
    assert mock_register.call_count == 0


def test_ensure_model_priced_thread_safe(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent calls collapse to exactly one ``register_model`` invocation.

    A slow ``register_model`` (50ms) holds the helper's internal lock long
    enough for other threads to enter ``ensure_model_priced`` and contend.
    When the first thread releases the lock (with ``_upstream_attempted=True``
    set), the remaining threads acquire one-at-a-time, see the latch, and
    return without calling ``register_model``. Verifies the lock + double-
    check pattern, not just the latch.

    ``httpx.get`` is stubbed too so we don't fire real HTTP from the
    one thread that wins the race.
    """
    import time

    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    # Non-empty stub to bypass the helper's empty-dict guard.
    _stub_httpx_get(monkeypatch, {"placeholder/model": {"mode": "chat"}})

    call_count = 0
    call_lock = threading.Lock()

    def slow_register(upstream_map):
        nonlocal call_count
        # 50ms is enough wall-clock for 9 other threads to enqueue on the
        # helper's _UPSTREAM_LOCK before we increment and return. Per
        # tests/CLAUDE.md pitfall #15, kept under 0.1s.
        time.sleep(0.05)
        with call_lock:
            call_count += 1

    monkeypatch.setattr(litellm, "register_model", slow_register)

    threads = [threading.Thread(target=ensure_model_priced, args=("some/brand-new-model",)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert call_count == 1


# ---------------------------------------------------------------------------
# try_load_upstream_catalog — validator-side membership check latch
# ---------------------------------------------------------------------------


def test_try_load_upstream_catalog_returns_true_on_first_successful_fetch(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first call with a working network returns True and registers new entries."""
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    upstream = {"new/model": {"input_cost_per_token": 1e-6, "litellm_provider": "openai", "mode": "chat"}}
    urls_called = _stub_httpx_get(monkeypatch, upstream)

    register_calls: list[dict] = []

    def recording_register(upstream_map: dict) -> None:
        register_calls.append(upstream_map)

    monkeypatch.setattr(litellm, "register_model", recording_register)

    result = try_load_upstream_catalog()

    assert result is True
    assert urls_called == [litellm.model_cost_map_url]
    assert register_calls == [upstream]


def test_try_load_upstream_catalog_returns_true_when_no_new_entries_to_merge(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetch succeeds but every upstream key is already bundled.

    Load-bearing: the function must return True even when there are no
    new entries to register. The catalog is still usable for membership
    checks. ``register_model`` MUST NOT be called (no-op fetch).
    """
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(
        litellm,
        "model_cost",
        {"bundled/model": {"input_cost_per_token": 1.0e-7, "litellm_provider": "openai", "mode": "chat"}},
        raising=False,
    )
    _stub_httpx_get(monkeypatch, {"bundled/model": {"input_cost_per_token": 9e-6}})

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    result = try_load_upstream_catalog()

    assert result is True
    assert mock_register.call_count == 0
    # Latch is set + success status recorded for subsequent calls.
    assert litellm_runtime._validator_upstream_attempted is True
    assert litellm_runtime._validator_upstream_fetch_succeeded is True


def test_try_load_upstream_catalog_returns_false_on_network_failure(
    reset_upstream_attempted,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Network failure returns False, sets failure latch, does not raise."""
    import httpx

    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    def failing_get(url, *args, **kwargs):
        raise httpx.ConnectError("simulated network outage")

    monkeypatch.setattr(httpx, "get", failing_get)

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    caplog.set_level("DEBUG", logger="pflow.core.litellm_runtime")

    result = try_load_upstream_catalog()

    assert result is False
    assert litellm_runtime._validator_upstream_attempted is True
    assert litellm_runtime._validator_upstream_fetch_succeeded is False
    assert mock_register.call_count == 0
    assert any("Validator upstream catalog merge failed" in r.message for r in caplog.records)


def test_try_load_upstream_catalog_idempotent_after_success(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call after a successful fetch returns the cached True without re-fetching."""
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"new/model": {"mode": "chat"}})

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    first = try_load_upstream_catalog()
    second = try_load_upstream_catalog()
    third = try_load_upstream_catalog()

    assert first is True and second is True and third is True
    assert len(urls_called) == 1
    assert mock_register.call_count == 1


def test_try_load_upstream_catalog_idempotent_after_failure(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call after a failed fetch returns the cached False — no retry hammering."""
    import httpx

    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    call_counter = {"n": 0}

    def failing_get(url, *args, **kwargs):
        call_counter["n"] += 1
        raise httpx.ConnectError("simulated network outage")

    monkeypatch.setattr(httpx, "get", failing_get)

    first = try_load_upstream_catalog()
    second = try_load_upstream_catalog()
    third = try_load_upstream_catalog()

    assert first is False and second is False and third is False
    # Only ONE network attempt despite three calls.
    assert call_counter["n"] == 1


def test_try_load_upstream_catalog_independent_from_runtime_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime-side fetch failure does NOT disable validator-side checks.

    Models the cross-coupling bug the separate latch prevents: a long-
    running MCP server whose first ``ensure_model_priced`` call hit a
    transient network failure must not have its validator catalog-check
    permanently disabled for the rest of the process.
    """
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    # Simulate "runtime path already attempted and failed", validator path fresh.
    monkeypatch.setattr(litellm_runtime, "_upstream_attempted", True)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_attempted", False)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_fetch_succeeded", False)

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"new/model": {"mode": "chat"}})

    mock_register = MagicMock()
    monkeypatch.setattr(litellm, "register_model", mock_register)

    result = try_load_upstream_catalog()

    assert result is True
    assert len(urls_called) == 1  # Validator path fetched fresh, independent of runtime latch.


def test_try_load_upstream_catalog_thread_safe(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent calls collapse to exactly one register_model invocation."""
    import time

    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    _stub_httpx_get(monkeypatch, {"placeholder/model": {"mode": "chat"}})

    call_count = 0
    call_lock = threading.Lock()

    def slow_register(upstream_map):
        nonlocal call_count
        time.sleep(0.05)
        with call_lock:
            call_count += 1

    monkeypatch.setattr(litellm, "register_model", slow_register)

    results: list[bool] = []
    results_lock = threading.Lock()

    def runner():
        r = try_load_upstream_catalog()
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=runner) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert call_count == 1
    assert all(r is True for r in results)


def test_try_load_upstream_catalog_rejects_malformed_payload(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-entry shape validation: payloads with values that are not dicts
    containing at least one recognized field are rejected.

    Defends against silent-failure class where a malformed upstream JSON
    (single string per key, integer values, missing fields) would still
    register junk entries and latch the validator as "catalog merged
    successfully" — subsequent membership checks would silently report
    the workflow's model as known when the registered entry is garbage.
    """
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    # All-malformed payloads must set fetch_succeeded=False.
    for malformed in [
        {"gpt-4": "string-instead-of-dict"},
        {"gpt-4": 42},
        {"gpt-4": []},
        {"gpt-4": {}},  # empty dict — no recognized field
        {"gpt-4": {"random_field": "value"}},  # dict, but no recognized field
    ]:
        litellm_runtime._validator_upstream_attempted = False
        litellm_runtime._validator_upstream_fetch_succeeded = False
        _stub_httpx_get(monkeypatch, malformed)
        mock_register = MagicMock()
        monkeypatch.setattr(litellm, "register_model", mock_register)

        result = try_load_upstream_catalog()
        assert result is False, f"malformed payload {malformed!r} should fail"
        assert mock_register.call_count == 0, f"register_model should not be called for {malformed!r}"


def test_try_load_upstream_catalog_drops_malformed_entries_keeps_well_formed(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mixed payload: well-formed entries get registered, malformed dropped, success returned."""
    from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    payload = {
        "good-model": {"input_cost_per_token": 1e-6, "litellm_provider": "openai", "mode": "chat"},
        "junk-model": "string-value",  # malformed — should be dropped
        "empty-dict": {},  # malformed — should be dropped
    }
    _stub_httpx_get(monkeypatch, payload)
    register_calls: list[dict] = []

    def recording_register(upstream_map: dict) -> None:
        register_calls.append(upstream_map)

    monkeypatch.setattr(litellm, "register_model", recording_register)

    result = try_load_upstream_catalog()

    assert result is True
    assert len(register_calls) == 1
    assert "good-model" in register_calls[0]
    assert "junk-model" not in register_calls[0]
    assert "empty-dict" not in register_calls[0]


def test_ensure_model_priced_drops_malformed_entries(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ensure_model_priced`` MUST apply the same shape filter as the validator path.

    Without this, a runtime-side fetch landing first with malformed payload
    would register junk entries into ``litellm.model_cost``. The validator's
    catalog-membership check then has a residual silent-accept window for
    those junk keys (closed in defense by tightening the non-dict fallback
    to return False, but the registration side is the primary defense).
    """
    from pflow.core.litellm_runtime import ensure_model_priced, import_litellm

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    payload = {
        "good-model": {"input_cost_per_token": 1e-6, "litellm_provider": "openai", "mode": "chat"},
        "junk-string": "not-a-dict",
        "empty-dict": {},
        "no-recognized-fields": {"some_random_field": "value"},
    }
    _stub_httpx_get(monkeypatch, payload)

    register_calls: list[dict] = []

    def recording_register(upstream_map: dict) -> None:
        register_calls.append(upstream_map)
        for k, v in upstream_map.items():
            litellm.model_cost.setdefault(k, {}).update(v)

    monkeypatch.setattr(litellm, "register_model", recording_register)

    ensure_model_priced("some/asked-for-model")

    # register_model received ONLY the well-formed entry.
    assert len(register_calls) == 1
    assert "good-model" in register_calls[0]
    assert "junk-string" not in register_calls[0]
    assert "empty-dict" not in register_calls[0]
    assert "no-recognized-fields" not in register_calls[0]
    # Catalog ends up with only the well-formed key registered.
    assert "good-model" in litellm.model_cost
    assert "junk-string" not in litellm.model_cost
    assert "empty-dict" not in litellm.model_cost


def test_validator_catalog_check_rejects_non_dict_entry_defense_in_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense-in-depth: validator's non-dict fallback returns False.

    Even if a future code path bypasses ``_filter_well_formed_upstream_entries``
    and registers junk, the validator's ``_catalog_form_known_for_provider``
    must NOT silently accept a non-dict catalog entry. Pins the hardened
    fallback (changed from "best-effort accept" to "reject as unknown").
    """
    from pflow.core.litellm_runtime import import_litellm
    from pflow.core.workflow.validator import WorkflowValidator

    litellm = import_litellm()
    # Manually inject a junk entry (bypassing the filter) to simulate the
    # residual silent-accept window the fallback now closes.
    monkeypatch.setattr(litellm, "model_cost", {"openai/gpt-fake-junk": "not-a-dict"}, raising=False)

    # Function-private helper still callable for direct unit test.
    canonical = {"openai", "anthropic", "gemini"}
    result = WorkflowValidator._catalog_form_known_for_provider(litellm, canonical, "openai/gpt-fake-junk", "openai")

    assert result is False, "non-dict catalog entry must NOT pass the membership check"


@pytest.mark.e2e
def test_importing_helper_module_does_not_import_litellm(
    uv_exe: str,
    prepared_subprocess_env: dict[str, str],
) -> None:
    """The helper itself must stay lightweight — only ``importlib.import_module``
    inside helper functions touches litellm, never module-scope import.

    Subprocess test to guarantee a clean ``sys.modules`` baseline regardless
    of what the parent test process has already imported. Uses the same
    ``uv run python -c ...`` pattern as ``tests/test_cli/test_lazy_imports.py``
    so both lazy-import contracts (helper-level here, CLI-level there) run
    under identical isolation.
    """
    code = (
        "import sys\n"
        "import pflow.core.litellm_runtime  # noqa: F401\n"
        "leaked = [k for k in sys.modules if k == 'litellm' or k.startswith('litellm.')]\n"
        "assert not leaked, f'litellm leaked into sys.modules via helper import: {leaked}'\n"
    )
    result = subprocess.run(  # noqa: S603 — fixture-controlled args, mirrors test_lazy_imports.py
        [uv_exe, "run", "python", "-c", code],
        env=prepared_subprocess_env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"


# ---------------------------------------------------------------------------
# Meta-test: enforce the single-seam contract via AST scan.
# ---------------------------------------------------------------------------

# Modules under src/pflow/ allowed to mention ``litellm`` in their imports.
# This is the seam itself — and even there the import is via
# ``importlib.import_module(...)``, which is a function call (not an Import
# node) so the AST scan ignores it. Keeping the path in the allowlist makes
# the intent explicit and survives a future refactor that adds a direct
# import inside the helper.
_ALLOWED_DIRECT_LITELLM_IMPORTERS: frozenset[str] = frozenset({
    "src/pflow/core/litellm_runtime.py",
})


def test_no_direct_litellm_imports_in_production_code() -> None:
    """All production litellm imports must route through ``litellm_runtime``.

    Walks every ``.py`` file under ``src/pflow/`` and AST-parses it to find
    ``import litellm`` / ``import litellm.X`` / ``from litellm import ...`` /
    ``from litellm.X import ...`` statements (top-level OR inside function
    bodies). Any hit outside the allowlist fails the test with a fix hint.

    This blocks regressions of the issue-#384 fix: a future change that adds
    a bare ``import litellm`` somewhere bypasses ``configure_litellm_defaults``
    and re-introduces the network-fetch determinism bug.

    Caught: ``import litellm``, ``import litellm.exceptions``,
            ``from litellm import X``, ``from litellm.X import Y``.
    Allowed: ``importlib.import_module("litellm")`` (function call, not Import
            node — the helper's escape hatch).
    """
    repo_root = _find_repo_root()
    src_root = repo_root / "src" / "pflow"
    assert src_root.is_dir(), f"expected src/pflow/ at {src_root}"

    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel_path = py_file.relative_to(repo_root).as_posix()
        if rel_path in _ALLOWED_DIRECT_LITELLM_IMPORTERS:
            continue
        violations.extend(_scan_one_file(py_file, rel_path))

    if violations:
        violations_block = "\n".join(violations)
        pytest.fail(
            "Direct litellm imports found in production code. Route them through "
            "pflow.core.litellm_runtime instead:\n\n"
            "  from pflow.core.litellm_runtime import import_litellm  # or import_litellm_exceptions\n"
            "  litellm = import_litellm()\n\n"
            "This applies the LITELLM_LOCAL_MODEL_COST_MAP=True default so the "
            "model-pricing map loads deterministically offline (see GH #384).\n\n"
            f"Offending sites:\n{violations_block}"
        )


def _scan_one_file(py_file: Path, rel_path: str) -> list[str]:
    """Return any direct-litellm-import violations found in ``py_file``."""
    source = py_file.read_text(encoding="utf-8")
    # Text prefilter: AST parsing is ~1ms per file but most pflow files
    # never mention litellm. The substring check is ~1µs per file and
    # cuts the scan from ~250ms to ~50ms. Conservative — matches any
    # mention (comments/strings/identifiers), then the AST scan filters
    # those out by structure.
    if "litellm" not in source:
        return []
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as exc:
        pytest.fail(f"{rel_path}: failed to parse — {exc}")

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_litellm_module(alias.name):
                    found.append(f"  {rel_path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and _is_litellm_module(node.module or ""):
            names = ", ".join(a.name for a in node.names)
            found.append(f"  {rel_path}:{node.lineno}: from {node.module} import {names}")
    return found


def _is_litellm_module(name: str) -> bool:
    return name == "litellm" or name.startswith("litellm.")


def _find_repo_root() -> Path:
    """Walk up from this file until we find ``pyproject.toml`` — the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError(f"could not locate repo root (no pyproject.toml above {here})")
