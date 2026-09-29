"""Tests for ``pflow.core.litellm_runtime`` — the single LiteLLM import seam.

Covers:
- ``configure_litellm_defaults`` sets ``LITELLM_LOCAL_MODEL_COST_MAP=True``
  when unset.
- ``configure_litellm_defaults`` respects a user-provided value (no overwrite).
- ``import_litellm`` and ``import_litellm_exceptions`` set the env var before
  returning the module.
- ``ensure_model_priced`` merges upstream cost map on first cache miss,
  is idempotent + thread-safe, and degrades silently on fetch failure.
- ``estimate_completion_cost_usd`` routes external token usage through
  LiteLLM's cache-aware pricing and preserves the unknown-model fallback.
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

from pflow.core.litellm_runtime import import_litellm

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


def test_estimate_completion_cost_passes_cache_inclusive_usage_to_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External backends must use LiteLLM's calculator, including cache tiers."""
    from pflow.core.litellm_runtime import estimate_completion_cost_usd, import_litellm

    litellm = import_litellm()
    calls: list[dict] = []

    def fake_cost_per_token(**kwargs):
        calls.append(kwargs)
        return 0.012, 0.003

    monkeypatch.setattr(litellm, "cost_per_token", fake_cost_per_token)

    cost = estimate_completion_cost_usd(
        model="gpt-5.2-codex",
        input_tokens=15_000,
        output_tokens=250,
        cache_creation_input_tokens=100,
        cache_read_input_tokens=10_000,
    )

    assert cost == pytest.approx(0.015)
    assert calls == [
        {
            "model": "gpt-5.2-codex",
            "prompt_tokens": 15_000,
            "completion_tokens": 250,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 10_000,
            "call_type": "completion",
        }
    ]


def test_estimate_completion_cost_uses_bundled_codex_cache_pricing() -> None:
    """Pin the real LiteLLM seam, not only a mocked return value.

    For bundled ``gpt-5.2-codex`` rates, this usage is:
    4,669 uncached input + 9,984 cached input + 5 output tokens.
    """
    from pflow.core.litellm_runtime import estimate_completion_cost_usd

    cost = estimate_completion_cost_usd(
        model="gpt-5.2-codex",
        input_tokens=14_653,
        output_tokens=5,
        cache_read_input_tokens=9_984,
    )

    assert cost == pytest.approx(0.00998795)


def test_estimate_completion_cost_without_model_does_not_import_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inherited Codex CLI model stays unpriced without import overhead."""
    import pflow.core.litellm_runtime as runtime

    monkeypatch.setattr(runtime, "import_litellm", lambda: pytest.fail("LiteLLM must remain lazy"))

    assert runtime.estimate_completion_cost_usd(model=None, input_tokens=100, output_tokens=10) is None


def test_estimate_completion_cost_unknown_model_stays_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catalog misses must not silently turn into a misleading zero-dollar call."""
    import pflow.core.litellm_runtime as runtime

    monkeypatch.setattr(runtime, "get_model_pricing", lambda model: None)
    monkeypatch.setattr(runtime, "import_litellm", lambda: pytest.fail("unpriced model must not be calculated"))

    assert (
        runtime.estimate_completion_cost_usd(
            model="future-codex-model",
            input_tokens=100,
            output_tokens=10,
        )
        is None
    )


def test_estimate_completion_cost_unroutable_priced_model_keeps_stdout_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A priced model LiteLLM cannot route must not print its banner onto stdout.

    ``cost_per_token`` raises for it and LiteLLM ``print()``s "Provider List"
    unless ``suppress_debug_info`` is set — which would corrupt
    ``pflow --output-format json`` on the codex-backend cost path.
    """
    import copy

    import pflow.core.litellm_runtime as runtime

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    catalog = copy.deepcopy(litellm.model_cost)
    catalog["unroutable-provider/model"] = {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}
    monkeypatch.setattr(litellm, "model_cost", catalog, raising=False)

    cost = runtime.estimate_completion_cost_usd(model="unroutable-provider/model", input_tokens=100, output_tokens=10)

    assert cost is None
    assert "Provider List" not in capsys.readouterr().out


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
    """Reset the module-level upstream latches between tests.

    The flags latch True after the first fetch attempt per process. Tests
    that exercise the fetch path must reset them explicitly via monkeypatch
    so the helper actually runs (instead of short-circuiting on the latch).
    Layers on top of ``tests/conftest.py::_block_upstream_cost_map_fetch``
    which pre-sets the flags for all tests — opting back in here means the
    helpers actually enter their fetch branch.

    A merge also writes process-wide LiteLLM state outside ``model_cost``:
    the per-provider ``*_models`` routing sets (copied here, so monkeypatch
    restores the originals) and the ``model_cost`` lookup caches (cleared at
    teardown, since monkeypatch restores the real catalog without telling
    LiteLLM).
    """
    from pflow.core import litellm_runtime

    monkeypatch.setattr(litellm_runtime, "_upstream_attempted", False)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_attempted", False)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_fetch_succeeded", False)
    litellm = import_litellm()
    for name, value in list(vars(litellm).items()):
        if name.endswith("_models") and isinstance(value, set):
            monkeypatch.setattr(litellm, name, set(value))
    yield litellm_runtime
    litellm.utils._invalidate_model_cost_lowercase_map()


def _stub_httpx_get(monkeypatch: pytest.MonkeyPatch, upstream_map: dict, delay: float = 0.0) -> list[str]:
    """Stub ``httpx.get`` to return ``upstream_map`` as JSON after ``delay`` seconds.

    Returns a list that records every URL ``httpx.get`` was called with,
    so tests can assert call count + URL without re-deriving the mock.
    """
    import time

    import httpx

    urls_called: list[str] = []

    def fake_get(url, *args, **kwargs):
        urls_called.append(url)
        time.sleep(delay)
        return MagicMock(
            raise_for_status=lambda: None,
            json=lambda: upstream_map,
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    return urls_called


# LiteLLM 1.86.1's ``get_model_info`` resolves this upstream-only key to the
# bundled entry below — the aliasing that made ``register_model`` overwrite
# the bundled entry and drop the new key (#654).
_ALIASING_UPSTREAM_KEY = "databricks/databricks-claude-opus-4-6"
_ALIASED_BUNDLED_KEY = "databricks/databricks-claude-opus-4"


@pytest.mark.parametrize(
    "merge",
    [
        pytest.param(
            lambda rt: rt.estimate_completion_cost_usd(
                model=_ALIASING_UPSTREAM_KEY, input_tokens=1000, output_tokens=1000
            ),
            id="runtime-ensure_model_priced",
        ),
        pytest.param(lambda rt: rt.try_load_upstream_catalog(), id="validator-try_load_upstream_catalog"),
    ],
)
def test_upstream_merge_adds_aliasing_key_and_leaves_bundled_catalog_identical(
    merge, reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression #654: the merge writes upstream-only keys verbatim and never a bundled entry.

    Runs against the real bundled catalog (copied, so the test can't leak)
    because the defect lives in LiteLLM's key resolution against real
    entries. The payload also revises a bundled entry, which must be ignored.
    """
    import copy

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", copy.deepcopy(litellm.model_cost), raising=False)
    assert _ALIASING_UPSTREAM_KEY not in litellm.model_cost, "LiteLLM now bundles this key; pick another alias."
    # Precondition: LiteLLM resolves the new key to the bundled entry. The
    # lookup also warms get_model_info's lru_cache, which the merge must clear.
    assert litellm.get_model_info(_ALIASING_UPSTREAM_KEY)["key"] == _ALIASED_BUNDLED_KEY
    bundled_before = copy.deepcopy(litellm.model_cost)

    new_entry = {
        "max_tokens": 128000,
        "input_cost_per_token": 1e-6,
        "output_cost_per_token": 2e-6,
        "litellm_provider": "databricks",
        "mode": "chat",
    }
    revised_bundled = {**bundled_before[_ALIASED_BUNDLED_KEY], "input_cost_per_token": 9.99e-6, "mode": "responses"}
    _stub_httpx_get(monkeypatch, {_ALIASING_UPSTREAM_KEY: new_entry, _ALIASED_BUNDLED_KEY: revised_bundled})

    merge(reset_upstream_attempted)

    # Every bundled entry is untouched, and the only addition is the new key.
    assert set(litellm.model_cost) == set(bundled_before) | {_ALIASING_UPSTREAM_KEY}
    assert {k: litellm.model_cost[k] for k in bundled_before} == bundled_before
    # The new key is present with its own values, and LiteLLM's lookups see it.
    assert litellm.model_cost[_ALIASING_UPSTREAM_KEY] == new_entry
    info = litellm.get_model_info(_ALIASING_UPSTREAM_KEY)
    assert (info["key"], info["max_tokens"]) == (_ALIASING_UPSTREAM_KEY, 128000)
    assert reset_upstream_attempted.estimate_completion_cost_usd(
        model=_ALIASING_UPSTREAM_KEY, input_tokens=1000, output_tokens=1000
    ) == pytest.approx(1000 * 1e-6 + 1000 * 2e-6)


def test_upstream_merge_routes_new_bare_model_name_to_its_provider(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare upstream-only name must route to its provider, as bundled bare names do.

    LiteLLM infers the provider of a bare ``claude-*`` name from its
    per-provider model sets, not from ``model_cost``; without the merge
    adding the key there, ``cost_per_token`` raises "LLM Provider NOT
    provided" and the cost silently degrades to ``None``.
    """
    import copy

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", copy.deepcopy(litellm.model_cost), raising=False)
    bare = "claude-pflow-test-654"
    _stub_httpx_get(
        monkeypatch,
        {
            bare: {
                "input_cost_per_token": 3e-6,
                "output_cost_per_token": 4e-6,
                "litellm_provider": "anthropic",
                "mode": "chat",
            }
        },
    )

    cost = reset_upstream_attempted.estimate_completion_cost_usd(model=bare, input_tokens=1000, output_tokens=1000)

    assert cost == pytest.approx(1000 * 3e-6 + 1000 * 4e-6)


def test_ensure_model_priced_no_op_when_model_in_bundled(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bundled-model lookup must not trigger an upstream fetch."""
    from pflow.core.litellm_runtime import ensure_model_priced

    litellm = import_litellm()
    # gemini/gemini-2.5-flash is in the bundled JSON; if LiteLLM ever removes
    # it from the bundle, swap to another known-bundled model.
    assert "gemini/gemini-2.5-flash" in litellm.model_cost, (
        "Pick a different known-bundled model; this one is no longer bundled."
    )
    urls_called = _stub_httpx_get(monkeypatch, {"new/model": {"mode": "chat"}})

    ensure_model_priced("gemini/gemini-2.5-flash")

    assert urls_called == []


def test_ensure_model_priced_fetches_when_model_missing(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing model triggers exactly one fetch of ``litellm.model_cost_map_url`` and merges it."""
    from pflow.core.litellm_runtime import ensure_model_priced

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

    ensure_model_priced("some/brand-new-model")

    # The URL comes from litellm.model_cost_map_url so LITELLM_MODEL_COST_MAP_URL
    # overrides still apply.
    assert urls_called == [litellm.model_cost_map_url]
    assert litellm.model_cost == fake_upstream


def test_ensure_model_priced_idempotent_across_calls(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call with a missing model is a no-op (latch via ``_upstream_attempted``)."""
    from pflow.core.litellm_runtime import ensure_model_priced

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"placeholder/model": {"mode": "chat"}})

    ensure_model_priced("some/brand-new-model")
    ensure_model_priced("another/brand-new-model")
    ensure_model_priced("some/brand-new-model")

    assert len(urls_called) == 1


def test_ensure_model_priced_no_new_models_leaves_catalog_unchanged(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When upstream holds only already-bundled keys, nothing is written and the latch still sets."""
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import ensure_model_priced

    litellm = import_litellm()
    bundled = {"bundled/model": {"input_cost_per_token": 1.0e-7}}
    monkeypatch.setattr(litellm, "model_cost", {"bundled/model": {"input_cost_per_token": 1.0e-7}}, raising=False)
    _stub_httpx_get(monkeypatch, {"bundled/model": {"input_cost_per_token": 9.99e-6}})

    ensure_model_priced("never-going-to-be-found/model")

    assert litellm.model_cost == bundled
    assert litellm_runtime._upstream_attempted is True


def test_ensure_model_priced_silent_on_fetch_failure(
    reset_upstream_attempted,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed upstream fetch (e.g. offline, DNS, GitHub down) must not raise.

    Injects the failure at ``httpx.get`` — the actual network boundary. The
    latch must still set (one attempt per process; no retry storms), the
    debug log must fire for ``--verbose`` visibility, and the catalog stays
    untouched.
    """
    import httpx

    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import ensure_model_priced

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    def failing_get(url, *args, **kwargs):
        raise httpx.ConnectError("simulated network outage")

    monkeypatch.setattr(httpx, "get", failing_get)
    caplog.set_level("DEBUG", logger="pflow.core.litellm_runtime")

    # Must not raise.
    ensure_model_priced("some/brand-new-model")

    assert litellm_runtime._upstream_attempted is True
    assert any("Upstream cost map fetch failed" in record.message for record in caplog.records), (
        f"Expected debug log; got records: {[r.message for r in caplog.records]}"
    )
    assert litellm.model_cost == {}


def test_ensure_model_priced_thread_safe(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent misses collapse to exactly one upstream fetch.

    A slow fetch (50ms) holds the helper's internal lock long enough for the
    other threads to enter ``ensure_model_priced`` and contend. When the
    first thread releases the lock (with ``_upstream_attempted=True`` set),
    the rest see the latch and return. Verifies the lock + double-check
    pattern, not just the latch. Per tests/CLAUDE.md pitfall #15, the delay
    stays under 0.1s.
    """
    from pflow.core.litellm_runtime import ensure_model_priced

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"placeholder/model": {"mode": "chat"}}, delay=0.05)

    threads = [threading.Thread(target=ensure_model_priced, args=("some/brand-new-model",)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(urls_called) == 1


# ---------------------------------------------------------------------------
# try_load_upstream_catalog — validator-side membership check latch
# ---------------------------------------------------------------------------


def test_try_load_upstream_catalog_returns_true_on_first_successful_fetch(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first call with a working network returns True and merges the new entries."""
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    upstream = {"new/model": {"input_cost_per_token": 1e-6, "litellm_provider": "openai", "mode": "chat"}}
    urls_called = _stub_httpx_get(monkeypatch, upstream)

    result = try_load_upstream_catalog()

    assert result is True
    assert urls_called == [litellm.model_cost_map_url]
    assert litellm.model_cost == upstream


def test_try_load_upstream_catalog_returns_true_when_no_new_entries_to_merge(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetch succeeds but every upstream key is already bundled.

    Load-bearing: the function must return True even when there are no
    new entries to merge — the catalog is still usable for membership
    checks — and the bundled entry must stay untouched.
    """
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    bundled_entry = {"input_cost_per_token": 1.0e-7, "litellm_provider": "openai", "mode": "chat"}
    monkeypatch.setattr(litellm, "model_cost", {"bundled/model": dict(bundled_entry)}, raising=False)
    _stub_httpx_get(monkeypatch, {"bundled/model": {"input_cost_per_token": 9e-6}})

    result = try_load_upstream_catalog()

    assert result is True
    assert litellm.model_cost == {"bundled/model": bundled_entry}
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
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    def failing_get(url, *args, **kwargs):
        raise httpx.ConnectError("simulated network outage")

    monkeypatch.setattr(httpx, "get", failing_get)
    caplog.set_level("DEBUG", logger="pflow.core.litellm_runtime")

    result = try_load_upstream_catalog()

    assert result is False
    assert litellm_runtime._validator_upstream_attempted is True
    assert litellm_runtime._validator_upstream_fetch_succeeded is False
    assert litellm.model_cost == {}
    assert any("Validator upstream catalog merge failed" in r.message for r in caplog.records)


def test_try_load_upstream_catalog_idempotent_after_success(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call after a successful fetch returns the cached True without re-fetching."""
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"new/model": {"mode": "chat"}})

    first = try_load_upstream_catalog()
    second = try_load_upstream_catalog()
    third = try_load_upstream_catalog()

    assert first is True and second is True and third is True
    assert len(urls_called) == 1


def test_try_load_upstream_catalog_idempotent_after_failure(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call after a failed fetch returns the cached False — no retry hammering."""
    import httpx

    from pflow.core.litellm_runtime import try_load_upstream_catalog

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
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runtime-side fetch failure does NOT disable validator-side checks.

    Models the cross-coupling bug the separate latch prevents: a long-
    running MCP server whose first ``ensure_model_priced`` call hit a
    transient network failure must not have its validator catalog-check
    permanently disabled for the rest of the process.
    """
    from pflow.core import litellm_runtime
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    # Simulate "runtime path already attempted and failed", validator path fresh.
    monkeypatch.setattr(litellm_runtime, "_upstream_attempted", True)

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"new/model": {"mode": "chat"}})

    result = try_load_upstream_catalog()

    assert result is True
    assert len(urls_called) == 1  # Validator path fetched fresh, independent of runtime latch.


def test_try_load_upstream_catalog_thread_safe(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent calls collapse to exactly one upstream fetch, and all see its success."""
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)
    urls_called = _stub_httpx_get(monkeypatch, {"placeholder/model": {"mode": "chat"}}, delay=0.05)

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

    assert len(urls_called) == 1
    assert results == [True] * 10


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
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

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

        result = try_load_upstream_catalog()
        assert result is False, f"malformed payload {malformed!r} should fail"
        assert litellm.model_cost == {}, f"nothing should be merged for {malformed!r}"


def test_try_load_upstream_catalog_drops_malformed_entries_keeps_well_formed(
    reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mixed payload: well-formed entries get merged, malformed dropped, success returned."""
    from pflow.core.litellm_runtime import try_load_upstream_catalog

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    good = {"input_cost_per_token": 1e-6, "litellm_provider": "openai", "mode": "chat"}
    _stub_httpx_get(monkeypatch, {"good-model": good, "junk-model": "string-value", "empty-dict": {}})

    result = try_load_upstream_catalog()

    assert result is True
    assert litellm.model_cost == {"good-model": good}


def test_ensure_model_priced_drops_malformed_entries(reset_upstream_attempted, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ensure_model_priced`` applies the same shape filter as the validator path.

    Both paths write the shared ``litellm.model_cost``; a runtime-side fetch
    landing first with a malformed payload must not leave junk keys for the
    validator's catalog-membership check to accept.
    """
    from pflow.core.litellm_runtime import ensure_model_priced

    litellm = import_litellm()
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    good = {"input_cost_per_token": 1e-6, "litellm_provider": "openai", "mode": "chat"}
    payload = {
        "good-model": good,
        "junk-string": "not-a-dict",
        "empty-dict": {},
        "no-recognized-fields": {"some_random_field": "value"},
    }
    _stub_httpx_get(monkeypatch, payload)

    ensure_model_priced("some/asked-for-model")

    assert litellm.model_cost == {"good-model": good}


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
    # never mention litellm. The substring check is ~1μs per file and
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
