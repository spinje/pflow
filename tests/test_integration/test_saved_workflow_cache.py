"""GH #357 regression — saved-library workflows must hit the memo cache on
re-runs despite the frontmatter mutation that ``_update_metadata`` performs
after every successful saved-workflow run.

The bug: ``pflow save`` + the saved-workflow runner append/update frontmatter
fields (``execution_count``, ``last_execution_*``) after every successful run,
growing the frontmatter line count. Because the frontmatter sits at the top of
the file, that growth shifts every body section's source line. The markdown
parser threads those line numbers into node params as ``_<key>_source_line``,
and before the fix the memo cache key absorbed them — so the key drifted on
every run and the saved-library cache never hit.

**Why this needs a templated node.** The ``_*_source_line`` filter lives in
``compute_node_cache_key``, which only sees ``resolved_inputs`` when the node
has a template (the compiler sets ``template_config`` only for nodes carrying
``${...}`` — ``compiler.py``). A no-template node takes a different path
(``resolved_params=None``) where the source line is filtered separately by
``compute_node_config``'s config-hash filter, which predates #357. So the #357
drift only ever manifested for templated nodes — exactly the LLM repro in the
issue. This test uses that repro: an LLM node with a ``${concept}`` prompt.

This is an END-TO-END guard through ``WorkflowManager`` (save + metadata
mutation) AND ``WorkflowRunner`` (resolve → compile → run → memo cache). The
unit tests in ``tests/test_runtime/test_cache.py`` pin the pure
``compute_node_cache_key`` filter; this test pins the integration seam where
the bug actually manifests (tests/CLAUDE.md pitfall #20). Deleting the
``_*_source_line`` filter in ``runtime/cache.py`` turns this test red.
"""

import sqlite3
from pathlib import Path
from typing import Any

from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from tests.shared.markdown_utils import ir_to_markdown

# The issue's exact repro: an LLM node whose prompt carries a ``${concept}``
# template. LLM nodes default to cache_enabled=True, so no ``cache: true`` is
# needed. The autouse ``mock_llm_client`` fixture intercepts the call — no API.
# ``concept`` has a default so both runs resolve the prompt identically; the
# only thing that changes between runs is the frontmatter-driven source line.
_WORKFLOW_IR: dict[str, Any] = {
    "ir_version": "0.1.0",
    "inputs": {
        "concept": {
            "type": "string",
            "required": False,
            "default": "caching",
            "description": "A concept to describe.",
        },
    },
    "nodes": [
        {
            "id": "gen",
            "type": "llm",
            "purpose": "Tell the LLM about the concept in one sentence.",
            "params": {
                "model": "anthropic/claude-haiku-4-5",
                "prompt": "Tell me about ${concept} in one sentence.",
            },
        },
    ],
    "edges": [],
}


def _frontmatter_line_span(path: Path) -> int:
    """Lines occupied by the leading ``---``…``---`` frontmatter block."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", "saved workflow must start with YAML frontmatter"
    return lines.index("---", 1) + 1


def _distinct_cache_keys(db_path: Path, node_id: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        (count,) = conn.execute(
            "SELECT COUNT(DISTINCT cache_key) FROM cache_entries WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        return int(count)
    finally:
        conn.close()


def test_saved_workflow_hits_memo_cache_despite_frontmatter_mutation(
    isolate_pflow_config: dict[str, Any],
) -> None:
    """A saved templated workflow re-run HITs the memo cache even though the
    post-run metadata mutation shifted the cached node's source line (GH #357)."""
    name = "repro-357"
    cache_db = isolate_pflow_config["pflow_dir"] / "cache" / "cache.db"

    wm = WorkflowManager()
    saved_path = Path(wm.save(name, ir_to_markdown(_WORKFLOW_IR, title="Repro 357")))

    runner = WorkflowRunner()
    config = RunnerConfig()  # cache_enabled=True

    # --- Run 1: empty cache → MISS → node executes and writes one entry. ---
    fm_before = _frontmatter_line_span(saved_path)
    result1 = runner.run(name, {}, config, workflow_manager=wm, workflow_name=name)
    assert result1.success, f"first run failed: {result1.errors}"
    assert "gen" not in result1.shared_after.get("__cache_hits__", []), "run 1 must execute, not hit"

    # The bug's trigger: the post-run metadata update grew the frontmatter,
    # which necessarily shifts every body line — and thus gen's
    # ``_prompt_source_line`` — because the parser records absolute file
    # positions. If this assertion ever fails, the test has stopped exercising
    # the source-line drift it exists to guard against.
    fm_after = _frontmatter_line_span(saved_path)
    assert fm_after > fm_before, (
        f"metadata update must grow the frontmatter (was {fm_before}, now {fm_after}); "
        "without growth this test no longer reproduces the GH #357 drift"
    )

    # --- Run 2: same name, larger frontmatter, shifted source line. ---
    result2 = runner.run(name, {}, config, workflow_manager=wm, workflow_name=name)
    assert result2.success, f"second run failed: {result2.errors}"
    assert "gen" in result2.shared_after.get("__cache_hits__", []), (
        "GH #357: saved-workflow re-run must HIT the memo cache despite the frontmatter-driven source-line shift"
    )

    # Core invariant: the cache key did not drift across the two runs.
    assert _distinct_cache_keys(cache_db, "gen") == 1, (
        "expected exactly one memo cache_key for 'gen' across both runs; "
        ">1 means the source-line shift leaked into the cache key again"
    )
