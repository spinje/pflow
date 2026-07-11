"""Drift guard for the committed React-Flow contract fixtures.

The web suite's no-information-loss invariant (``web/src/graph/lossless.test.ts``)
runs over REAL renderer output committed under ``web/src/test/fixtures/contracts/``
— the defense against hand-built web fixtures silently encoding bug-compatible
shapes (the literal-batch invisibility class, 2026-06-11). That defense only
holds while the committed JSON IS the live renderer's output: this test fails
loudly the moment they diverge (a renderer/contract change, or an edit to one of
the three fixture workflows), so the web tests can never keep passing against a
stale contract shape.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.react_flow_contracts._generate import CONTRACT_DIR, WORKFLOWS, render_contract

_REGEN = "uv run python -m tests.fixtures.react_flow_contracts._generate"


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_committed_contract_fixture_matches_live_renderer(name: str) -> None:
    path = CONTRACT_DIR / f"{name}.json"
    assert path.exists(), f"missing committed fixture {path} — regenerate: {_REGEN}"
    committed = json.loads(path.read_text(encoding="utf-8"))
    live = render_contract(name)
    assert committed == live, (
        f"web/src/test/fixtures/contracts/{name}.json no longer matches the live renderer "
        f"(contract change, or {WORKFLOWS[name]} was edited). Regenerate: {_REGEN}"
    )
