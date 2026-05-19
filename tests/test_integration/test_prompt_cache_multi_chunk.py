"""End-to-end test for multi-breakpoint prompt caching.

Drives the committed multi-chunk example through ``WorkflowRunner.run()`` and
asserts that both consumer LLM nodes receive system_blocks with 3 markers
each (Anthropic budget=4, 3 declared chunks → all individual). Locks the
full cross-layer pipeline (parser → engine → prompt_cache → LLMNode →
adapter) against regressions that the unit-level placement tests would
miss.

Reference fixture: ``examples/core/prompt-caching-multi-chunk.pflow.md``.
"""

from __future__ import annotations

from pathlib import Path

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from tests.shared.llm_mock import MockLLMClient

EXAMPLE_FIXTURE = Path(__file__).parent.parent.parent / "examples" / "core" / "prompt-caching-multi-chunk.pflow.md"


def _marker_indices(system_blocks: object) -> tuple[int, ...]:
    """Return 0-based indices of blocks carrying a cache_control marker.

    Empty tuple when system is not a list-of-blocks shape.
    """
    if not isinstance(system_blocks, list):
        return ()
    return tuple(idx for idx, block in enumerate(system_blocks) if isinstance(block, dict) and "cache_control" in block)


def test_multi_chunk_workflow_emits_per_chunk_markers_end_to_end(mock_llm_client: MockLLMClient, monkeypatch) -> None:
    """Run the committed multi-chunk example through WorkflowRunner.

    The fixture declares 3 stable-to-volatile chunks (`system_prompt`,
    `knowledge_ref`, `session_context`) consumed by 2 LLM nodes (`summarize`,
    `translate`), both on `anthropic/claude-haiku-4-5`. Expected after
    execution:

    - Both LLM calls reach the adapter with `system` as a list of 3 blocks.
    - Every block on every call carries a cache_control marker (Anthropic
      budget=4, 3 chunks ≤ budget → all individual per
      `_compute_marker_chunk_indices`).
    """
    # Bypass the runtime below-min strip — echo outputs are tiny; the strip
    # would remove markers and obscure what we're testing. Strip semantics
    # are covered in test_prompt_cache_below_min_runtime.py.
    monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10_000)
    mock_llm_client.set_response("*", None, "ok")

    runner = WorkflowRunner()
    # Mock provides realistic cache telemetry so the observed-tier
    # cache.below-min-observed warning doesn't fire (it would otherwise,
    # because the mock supplies 0 cache_creation_input_tokens by default).
    mock_llm_client.set_response("*", None, "ok", cache_creation_input_tokens=512)
    result = runner.run(
        str(EXAMPLE_FIXTURE),
        {"article": "Solar storms hit Earth.", "session_id": "abc-123"},
        config=RunnerConfig(),
    )
    # The fixture has two informational shell-node-caching hints (not
    # related to multi-marker), so the workflow finishes DEGRADED. We
    # accept that — what we're locking is the LLM-call marker shape.
    assert result.success, f"Workflow should succeed end-to-end: {result.diagnostics}"
    assert result.status.value in {"completed", "success", "degraded"}, result.status

    # Both LLM nodes should have called the adapter exactly once. The example
    # has two consumers (`summarize`, `translate`).
    llm_calls = mock_llm_client.call_history_full
    assert len(llm_calls) == 2, f"Expected 2 LLM calls, got {len(llm_calls)}"

    for call in llm_calls:
        system = call.get("system")
        assert isinstance(system, list), f"Expected list-of-blocks system, got {type(system).__name__}"
        assert len(system) == 3, f"Expected 3 chunk blocks (no user_system), got {len(system)}"
        assert _marker_indices(system) == (0, 1, 2), (
            f"Expected cache_control on all 3 chunks (Anthropic budget=4, 3 ≤ budget), "
            f"got markers at {_marker_indices(system)}"
        )
