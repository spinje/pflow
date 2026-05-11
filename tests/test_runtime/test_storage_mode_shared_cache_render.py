"""Skip-marked regression for the documented `storage_mode: shared` race.

Locks the contract from `runtime/CLAUDE.md:194-213`: when a future consumer
reads parent `__pflow_cache_render__` after a parallel batch with
`storage_mode: shared` and a child declaring `## Cache`, the restore order
across worker threads is non-deterministic (last-finished worker wins).

Today this is silent-but-benign — no production consumer reads parent
cache_render post-batch. When a guard lands at `WorkflowEngine.run` entry
(see GH #379), un-skip this test.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason=(
        "Known limitation, GH #379 — add runtime guard at engine.run entry "
        "when storage_mode=shared + parallel batch + child ## Cache combine. "
        "Documented in runtime/CLAUDE.md:194-213."
    )
)
def test_storage_mode_shared_parallel_batch_child_cache_is_rejected_or_warned() -> None:
    """Locks the future-guard contract.

    Expected behavior once the guard lands (per `runtime/CLAUDE.md` race
    documentation):
      - `WorkflowEngine.run` entry detects the unsupported combination
        (storage_mode: shared + parallel batch + child workflow declaring
        `## Cache`).
      - Either rejects loudly with a structured error, or emits a
        `logger.warning` and disables the cache_render install for that
        combination.

    Mutation contract once un-skipped: removing the guard re-introduces
    the silent race condition documented in CLAUDE.md.
    """
    raise AssertionError("Skipped — un-skip when GH #379 guard lands.")
