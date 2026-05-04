"""Mutation contract decorator: optional documentation for tests defending a specific production line.

A test decorated with ``@mutation_contract`` claims that reverting a specific
production line will cause the test to fail. The decorator is **documentation
that doesn't lie** — it carries machine-readable metadata (file, line, revert
substring, expected failure) so future readers can find the production seam
the test defends without scanning the assertion.

Use it on tests that defend architectural invariants (cache walker policy,
projection vs actually-paid split, workflow-scope keying). Skip it on routine
assertions where the assertion + production code path are obvious.

The verifier ``scripts/check_mutation_contracts.py`` (run via
``make mutation-audit``) re-executes the contract on demand: revert the line,
run the test, assert failure. It is an **audit tool**, not a per-PR quality
gate — operational data shows it catches line-shift drift after refactors
more than real test rot. See ``tests/CLAUDE.md`` Pitfall #19 for positioning
and cost-benefit analysis.

A "Mutation contract:" docstring claim WITHOUT this decorator is rejected
at pytest collection time (``conftest.py`` enforces alignment). The docstring
narrative and the decorator metadata are paired — claiming one obligates the
other.

Usage::

    @mutation_contract(
        file="src/pflow/core/trace_tree.py",
        line=215,
        revert='if event.get("cached") and event.get("llm_call") is None',
        expected_failure="cost_for_node degrades to (None, 'unavailable')",
    )
    def test_cost_for_node_cached_event_returns_zero_trace() -> None:
        ...

The ``revert`` string MUST be a unique substring on ``line`` of ``file``. The
verifier replaces the entire matched line with
``<indent>pass  # MUTATED: <original>`` (preserving indent so the surrounding
block doesn't break). It then runs the decorated test and asserts the test
fails (mutation caught). The file is always restored.

Limitations:

- Single-line mutations only. Multi-line ``if/else`` or ``def`` headers
  are out of scope. If commenting the matched line creates a syntax error,
  pytest reports collection error (exit code 2) — the verifier still treats
  that as a "test failed" because the mutation was rejected by the runtime,
  even if not by the assertion.
- Indentation is preserved so mutating one branch of an ``if`` inside a
  function doesn't break unrelated code.
- The decorator is a no-op at runtime (just attaches a frozen dataclass to
  the function). pytest discovers the test normally; the contract metadata
  is read by the verifier script via ``func._mutation_contract``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T", bound=Callable)


@dataclass(frozen=True)
class MutationContract:
    """Machine-readable mutation contract metadata."""

    file: str
    line: int
    revert: str
    expected_failure: str


def mutation_contract(
    *,
    file: str,
    line: int,
    revert: str,
    expected_failure: str,
) -> Callable[[T], T]:
    """Attach a mutation contract to a test. No-op at runtime.

    Verified by ``scripts/check_mutation_contracts.py`` (mechanical).

    Args:
        file: Path to production file (relative to repo root).
        line: 1-based line number of the line to mutate.
        revert: Unique substring on that line. Verifier confirms it appears
            and replaces the entire line with ``<indent>pass  # MUTATED: ...``.
        expected_failure: Human-readable description of how the test fails
            (purely informational — read by the verifier's pretty output).
    """
    contract = MutationContract(
        file=file,
        line=line,
        revert=revert,
        expected_failure=expected_failure,
    )

    def decorator(func: T) -> T:
        func._mutation_contract = contract  # type: ignore[attr-defined]
        return func

    return decorator


__all__ = ["MutationContract", "mutation_contract"]
