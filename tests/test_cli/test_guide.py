"""Tests for the ``pflow guide`` command and guide composition."""

from __future__ import annotations

from pathlib import Path

import click.testing
import pytest

from pflow.cli.commands.guide import guide_cmd
from pflow.core.prompt_cache_analysis.warning_catalog import CACHE_WARNING_CATALOG
from pflow.guide import (
    GuideError,
    compose_guide,
    detect_topics_from_ir,
    list_topics,
    render_entry_content,
)

# ---------------------------------------------------------------------------
# render_entry_content / no-args fallback
# ---------------------------------------------------------------------------


def test_guide_without_topics_renders_entry_content() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(guide_cmd, [])
    assert result.exit_code == 0
    assert result.output == f"{render_entry_content()}\n"


def test_render_entry_content_is_nonempty() -> None:
    content = render_entry_content()
    assert len(content.strip()) > 100


def test_entry_no_cache_wording_is_memo_specific() -> None:
    content = render_entry_content()
    assert "--no-cache" in content
    assert "Bypass pflow memo-cache reads" in content
    assert "Force fresh execution" not in content


# ---------------------------------------------------------------------------
# list_topics
# ---------------------------------------------------------------------------


def test_list_topics_includes_core_and_nodes() -> None:
    topics = list_topics()
    assert "core" in topics
    assert "http" in topics
    assert "llm" in topics
    assert "code" in topics
    assert "shell" in topics
    assert "file" in topics
    assert "mcp" in topics


def test_list_topics_includes_features() -> None:
    topics = list_topics()
    assert "batch" in topics
    assert "branching" in topics
    assert "sub-workflows" in topics
    assert "prompt-caching" in topics
    assert "caching" not in topics


def test_list_topics_core_is_first() -> None:
    topics = list_topics()
    assert topics[0] == "core"


# ---------------------------------------------------------------------------
# compose_guide — topic mode
# ---------------------------------------------------------------------------


def test_compose_single_topic() -> None:
    result = compose_guide(["http"])
    assert "# HTTP Node" in result
    # No core auto-included
    assert "# pflow Framework" not in result


def test_compose_core_only() -> None:
    result = compose_guide(["core"])
    assert "# pflow Framework" in result


def test_core_no_cache_wording_distinguishes_provider_prompt_cache() -> None:
    result = compose_guide(["core"])
    assert "Provider prompt caching: if many LLM calls reuse the same long context" in result
    assert "pflow analyze-cache workflow.pflow.md" in result
    assert "pflow guide prompt-caching" in result
    assert "`--no-cache` — bypass pflow memo-cache reads" in result
    assert "provider prompt caching may still apply" in result
    assert "does not disable LLM" in result
    assert "all caches" not in result


def test_prompt_caching_guide_documents_allowed_ttl_values() -> None:
    result = compose_guide(["prompt-caching"])
    assert "`1m` through `60m`" in result
    assert "`1h` is accepted as an alias for `60m`" in result
    assert "Omit `ttl`" in result
    assert "default `5m` behavior" in result


def test_caching_topic_alias_resolves_to_prompt_caching() -> None:
    assert compose_guide(["caching"]) == compose_guide(["prompt-caching"])


def test_prompt_caching_guide_does_not_repeat_cached_values_in_quick_start() -> None:
    result = compose_guide(["prompt-caching"])
    assert 'prompt: "Pick a creative direction for the cached concept."' in result
    assert 'prompt: "Pick a creative direction for: ${concept}"' not in result


def test_prompt_caching_guide_code_examples_use_required_annotations() -> None:
    result = compose_guide(["prompt-caching"])
    assert "rubric: str" in result
    assert "dataset: list" in result
    assert "result: list =" in result


def test_prompt_caching_guide_avoids_internal_analyzer_vocabulary() -> None:
    result = compose_guide(["prompt-caching"])
    assert "Tier 2" not in result
    assert "static walkers" not in result
    assert "canonical source:" not in result
    assert "Renames" not in result


def test_prompt_caching_guide_covers_cache_ids_that_link_to_it() -> None:
    """Cache diagnostics that point here should be searchable by exact ID."""
    result = compose_guide(["prompt-caching"])
    for warning_id, spec in CACHE_WARNING_CATALOG.items():
        if "prompt-caching" not in spec.see_also:
            continue
        assert warning_id in result


def test_compose_multiple_topics_preserves_order() -> None:
    result = compose_guide(["batch", "http"])
    batch_pos = result.index("Batch")
    http_pos = result.index("HTTP")
    assert batch_pos < http_pos


def test_compose_no_core_auto_included() -> None:
    """Topic-only calls should NOT auto-include core."""
    result = compose_guide(["http", "llm"])
    # Should have separator between two chunks
    assert "---" in result
    # core.md content should not appear
    assert "Step Order vs Templates" not in result


def test_llm_guide_points_to_prompt_caching_without_duplication() -> None:
    result = compose_guide(["llm"])
    assert "pflow analyze-cache workflow.pflow.md" in result
    assert "pflow guide prompt-caching" in result
    assert "`prompt_cache: [chunk_name]`" in result
    assert "`prewarm: true`" in result
    assert "`1m` through `60m`" not in result


def test_claude_code_guide_documents_structured_output_without_internals() -> None:
    result = compose_guide(["claude-code"])
    assert "# Claude Code Node" in result
    assert "type: claude-code" in result
    assert "top-level `type: object`" in result
    assert "`max_turns` must be at least `2`" in result
    assert "### Parameters" in result
    assert "`output_schema: dict`" in result
    assert "__warnings__" not in result
    assert "structured_output" not in result
    assert "SDK" not in result


def test_compose_deduplicates_topics() -> None:
    result_once = compose_guide(["http"])
    result_twice = compose_guide(["http", "http"])
    # Same content — http only appears once
    assert result_once == result_twice


def test_compose_unknown_topic_raises() -> None:
    with pytest.raises(GuideError, match="Unknown topic 'nonexistent'"):
        compose_guide(["nonexistent"])


def test_compose_unknown_topic_lists_available() -> None:
    with pytest.raises(GuideError, match=r"Available topics:.*http"):
        compose_guide(["nonexistent"])


def test_compose_separator_between_chunks() -> None:
    result = compose_guide(["http", "llm"])
    assert "\n\n---\n\n" in result


# ---------------------------------------------------------------------------
# Read-completeness header + end-marker (topic path only)
# ---------------------------------------------------------------------------


def _end_marker(n: int) -> str:
    return f"⟨END OF GUIDE — {n} section{'' if n == 1 else 's'}⟩"


# Framing only fires above _FRAME_THRESHOLD_BYTES (20KB). `core` (~33KB) is the
# smallest single topic that exceeds it; small topics like `http` stay unframed.


def test_large_topic_output_starts_with_header() -> None:
    """Large topic output leads with the read-completeness header (survives
    preview truncation, which keeps the start)."""
    result = compose_guide(["core"])
    assert result.startswith("> **1 guide section below")
    assert "Read each to the END before building" in result
    # Advises reading the preserved full output, not re-fetching.
    assert "don't re-run this command" in result
    assert "the full text is preserved" in result


def test_large_topic_output_ends_with_marker() -> None:
    result = compose_guide(["core"])
    assert result.rstrip().endswith(_end_marker(1))


def test_small_topic_output_is_not_framed() -> None:
    """A single small topic stays below the truncation-risk threshold and gets
    no header/marker — framing it would be pure overhead."""
    result = compose_guide(["http"])
    assert not result.startswith(">")
    assert "END OF GUIDE" not in result
    assert "Read each to the END" not in result
    # Real content is still present and intact.
    assert "# HTTP Node" in result


def test_marker_count_is_section_count_despite_interface_divider() -> None:
    """A node topic injects its own ``---`` divider for the dynamic interface, so
    a naive divider count over-counts. The marker count must be the resolved topic
    count, proving completeness is divider-independent. ``core http`` exceeds the
    framing threshold and ``http`` contributes an extra interface divider."""
    result = compose_guide(["core", "http"])
    # Dividers: core↔http join + http's interface + the pre-marker divider ≥ 3.
    assert result.count("\n\n---\n\n") >= 3
    # ...but the section count is the number of topics (2), not dividers.
    assert _end_marker(2) in result
    assert _end_marker(3) not in result


def test_multi_topic_marker_count_matches_resolved_topics() -> None:
    result = compose_guide(["core", "http", "llm"])
    assert result.startswith("> **3 guide sections below")
    assert result.rstrip().endswith(_end_marker(3))


def test_marker_count_uses_deduped_topic_count() -> None:
    """Count is the deduped topic count — a repeated topic doesn't inflate it."""
    result = compose_guide(["core", "core"])
    assert result.startswith("> **1 guide section below")
    assert result.rstrip().endswith(_end_marker(1))


def test_header_appears_within_first_kilobyte() -> None:
    """The header must fit inside a typical preview window."""
    result = compose_guide(["core"])
    assert _end_marker(1) in result[:1024]


def test_header_and_marker_pluralization_agree() -> None:
    """The marker text quoted in the header equals the actual trailing line —
    they're generated from one local, so they can't drift on plural."""
    for topics, n in (["core"], 1), (["core", "http"], 2):
        result = compose_guide(topics)
        marker = _end_marker(n)
        # Header quotes the exact marker as the completeness check.
        assert f"reach the last line `{marker}`" in result
        assert result.rstrip().endswith(marker)


def test_no_args_output_has_no_header_or_marker() -> None:
    """The entry path (no args / ``pflow --help``) is untouched."""
    result = compose_guide([])
    assert result == render_entry_content()
    assert "END OF GUIDE" not in result
    assert "Read each to the END" not in result


# ---------------------------------------------------------------------------
# Dynamic node interface injection
# ---------------------------------------------------------------------------


def test_node_topic_includes_dynamic_parameters() -> None:
    """Node topics should include Parameters section from registry."""
    result = compose_guide(["http"])
    assert "### Parameters" in result
    assert "`url: str`" in result


def test_node_topic_includes_dynamic_outputs() -> None:
    """Node topics should include Outputs section from registry."""
    result = compose_guide(["shell"])
    assert "### Outputs" in result
    assert "`stdout: str`" in result


def test_file_topic_shows_both_node_types() -> None:
    """File topic should show read-file and write-file interfaces."""
    result = compose_guide(["file"])
    assert "### read-file" in result
    assert "### write-file" in result


def test_feature_topic_has_no_dynamic_interface() -> None:
    """Feature topics (batch, branching) should not have Parameters/Outputs."""
    result = compose_guide(["batch"])
    assert "### Parameters" not in result
    assert "### Outputs" not in result


def test_mcp_topic_has_no_dynamic_interface() -> None:
    """MCP topic should not have dynamic interface (tools are user-specific)."""
    result = compose_guide(["mcp"])
    assert "### Parameters" not in result
    assert "### Outputs" not in result


# ---------------------------------------------------------------------------
# compose_guide — workflow-ref mode
# ---------------------------------------------------------------------------


def test_compose_from_workflow_file(tmp_path: Path) -> None:
    wf = tmp_path / "test.pflow.md"
    wf.write_text(
        "# Test\n\nA test.\n\n## Steps\n\n### fetch\n\nFetch data.\n\n- type: http\n- url: https://example.com\n"
    )
    result = compose_guide([str(wf)])
    assert "HTTP" in result


def test_compose_from_workflow_detects_multiple_types(tmp_path: Path) -> None:
    wf = tmp_path / "multi.pflow.md"
    wf.write_text(
        "# Multi\n\nA multi-node workflow.\n\n## Steps\n\n"
        "### fetch\n\nFetch.\n\n- type: http\n- url: https://example.com\n\n"
        "### process\n\nProcess.\n\n- type: code\n- inputs:\n    data: ${fetch.response}\n\n"
        "```python code\ndata: dict\nresult: dict = data\n```\n"
    )
    result = compose_guide([str(wf)])
    assert "HTTP" in result
    assert "Code" in result


def test_compose_from_workflow_detects_claude_code(tmp_path: Path) -> None:
    wf = tmp_path / "claude.pflow.md"
    wf.write_text(
        "# Claude\n\nUse Claude Code.\n\n## Steps\n\n"
        "### fix\n\nFix code.\n\n"
        "- type: claude-code\n"
        "- max_turns: 2\n\n"
        "```prompt\nFix the failing test.\n```\n"
    )
    result = compose_guide([str(wf)])
    assert "# Claude Code Node" in result
    assert "### Parameters" in result


def test_compose_from_realistic_workflow_detects_all_topic_types(tmp_path: Path) -> None:
    """Full pipeline test: parse a realistic .pflow.md → detect topics → compose.

    Catches IR format drift — if the parser changes where batch/edges/types
    live in the IR dict, this breaks before the unit tests do (which use
    hand-crafted IR dicts).
    """
    wf = tmp_path / "realistic.pflow.md"
    wf.write_text(
        """\
# Realistic Workflow

A workflow exercising all detection paths.

## Steps

### fetch-data

Fetch data from an API.

- type: http
- url: https://api.example.com/data

### transform

Transform the response.

- type: code
- inputs:
    data: ${fetch-data.response}

```python code
data: dict
result: list = list(data.keys())
```

### save-output

Write results to disk.

- type: write-file
- file_path: /tmp/out.json
- content: ${transform.result}

### notify-each

Notify for each item.

- type: shell
- on-error: handle-error

```shell command
echo "${item}"
```

```yaml batch
items:
  - one
  - two
```

### handle-error

Log the error.

- type: shell
- next: end

```shell command
echo "failed" >&2
```
"""
    )
    result = compose_guide([str(wf)])

    # Node types detected
    assert "HTTP" in result  # http node
    assert "Code" in result  # code node
    assert "File" in result  # write-file → file topic
    assert "Shell" in result  # shell node

    # Features detected
    assert "Batch" in result  # batch config on notify-each
    assert "Error Handling" in result  # on-error edge → error-handling topic


def test_compose_workflow_ref_plus_explicit_topic(tmp_path: Path) -> None:
    wf = tmp_path / "simple.pflow.md"
    wf.write_text(
        "# Simple\n\nSimple.\n\n## Steps\n\n### fetch\n\nFetch.\n\n- type: http\n- url: https://example.com\n"
    )
    result = compose_guide([str(wf), "batch"])
    assert "HTTP" in result
    assert "Batch" in result


def test_compose_workflow_ref_deduplicates_with_explicit(tmp_path: Path) -> None:
    wf = tmp_path / "http-wf.pflow.md"
    wf.write_text("# HTTP WF\n\nHTTP.\n\n## Steps\n\n### fetch\n\nFetch.\n\n- type: http\n- url: https://example.com\n")
    result = compose_guide(["http", str(wf)])
    # http should only appear once (explicit + auto-detected deduplicated)
    assert result.count("# HTTP Node") == 1


def test_compose_nonexistent_workflow_raises(tmp_path: Path) -> None:
    with pytest.raises(GuideError, match="Workflow file not found"):
        compose_guide([str(tmp_path / "nope.pflow.md")])


def test_compose_unparseable_workflow_raises(tmp_path: Path) -> None:
    wf = tmp_path / "broken.pflow.md"
    wf.write_text("not a valid workflow at all")
    with pytest.raises(GuideError, match=r"Failed to parse|No guide topics"):
        compose_guide([str(wf)])


def test_compose_broken_saved_workflow_shows_load_error(tmp_path: Path, isolate_pflow_config: dict) -> None:
    """A saved workflow that exists but is malformed should show the load error,
    not 'Unknown topic'."""
    wf_dir = Path(isolate_pflow_config["workflows_path"]) / "broken-wf"
    wf_dir.mkdir(parents=True)
    (wf_dir / "broken-wf.pflow.md").write_text("---\nname: broken-wf\n---\nnot valid")

    with pytest.raises(GuideError, match="failed to load"):
        compose_guide(["broken-wf"])


# ---------------------------------------------------------------------------
# detect_topics_from_ir
# ---------------------------------------------------------------------------


def test_detect_shell_node() -> None:
    ir = {"nodes": [{"id": "s", "type": "shell", "params": {}}], "edges": []}
    assert "shell" in detect_topics_from_ir(ir)


def test_detect_mcp_node_maps_to_mcp_topic() -> None:
    ir = {"nodes": [{"id": "m", "type": "mcp-slack-SEND", "params": {}}], "edges": []}
    assert "mcp" in detect_topics_from_ir(ir)


def test_detect_file_nodes() -> None:
    ir = {
        "nodes": [
            {"id": "r", "type": "read-file", "params": {}},
            {"id": "w", "type": "write-file", "params": {}},
        ],
        "edges": [],
    }
    topics = detect_topics_from_ir(ir)
    assert "file" in topics
    # Both map to same topic — should appear once
    assert topics.count("file") == 1


def test_detect_workflow_node_maps_to_sub_workflows() -> None:
    ir = {"nodes": [{"id": "w", "type": "workflow", "params": {}}], "edges": []}
    assert "sub-workflows" in detect_topics_from_ir(ir)


def test_detect_batch() -> None:
    ir = {
        "nodes": [{"id": "b", "type": "llm", "params": {}, "batch": {"items": []}}],
        "edges": [],
    }
    topics = detect_topics_from_ir(ir)
    assert "batch" in topics
    assert "llm" in topics


def test_detect_error_handling_via_error_edge() -> None:
    # An `on-error:` edge routes to the error-handling topic, not branching.
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {}},
            {"id": "h", "type": "shell", "params": {}},
        ],
        "edges": [{"from": "a", "to": "h", "action": "error"}],
    }
    topics = detect_topics_from_ir(ir)
    assert "error-handling" in topics
    assert "branching" not in topics


def test_detect_branching_via_named_action() -> None:
    ir = {
        "nodes": [
            {"id": "c", "type": "code", "params": {}},
            {"id": "t", "type": "shell", "params": {}},
        ],
        "edges": [
            {"from": "c", "to": "t", "action": "t"},
            {"from": "c", "to": "t", "action": "default"},
        ],
    }
    assert "branching" in detect_topics_from_ir(ir)


def test_detect_no_branching_for_default_edges_only() -> None:
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {}},
            {"id": "b", "type": "shell", "params": {}},
        ],
        "edges": [{"from": "a", "to": "b", "action": "default"}],
    }
    assert "branching" not in detect_topics_from_ir(ir)


def test_detect_unknown_node_type_ignored() -> None:
    ir = {"nodes": [{"id": "x", "type": "alien-node", "params": {}}], "edges": []}
    assert detect_topics_from_ir(ir) == []


def test_detect_returns_sorted() -> None:
    ir = {
        "nodes": [
            {"id": "s", "type": "shell", "params": {}},
            {"id": "h", "type": "http", "params": {}},
            {"id": "c", "type": "code", "params": {}},
        ],
        "edges": [],
    }
    topics = detect_topics_from_ir(ir)
    assert topics == sorted(topics)


# ---------------------------------------------------------------------------
# detect_topics_from_ir — caching detection (F-03 fix)
# ---------------------------------------------------------------------------


def test_detect_caching_via_top_level_cache_block() -> None:
    """Top-level ``## Cache`` block parses into ``ir["cache"]`` → prompt-caching topic."""
    ir = {
        "nodes": [{"id": "n", "type": "llm", "params": {}}],
        "edges": [],
        "cache": {"ttl": "5m", "items": [{"name": "doc", "var": "doc"}]},
    }
    assert "prompt-caching" in detect_topics_from_ir(ir)
    assert "caching" not in detect_topics_from_ir(ir)


def test_detect_caching_via_prompt_cache() -> None:
    """A node with ``prompt_cache: [...]`` → prompt-caching topic."""
    ir = {
        "nodes": [{"id": "n", "type": "llm", "params": {}, "prompt_cache": ["doc"]}],
        "edges": [],
    }
    assert "prompt-caching" in detect_topics_from_ir(ir)


def test_detect_caching_via_prewarm_true() -> None:
    """A node with ``prewarm: true`` → prompt-caching topic."""
    ir = {
        "nodes": [{"id": "n", "type": "llm", "params": {}, "prewarm": True}],
        "edges": [],
    }
    assert "prompt-caching" in detect_topics_from_ir(ir)


def test_detect_caching_via_prewarm_false_still_fires() -> None:
    """Presence not truthiness: ``prewarm: false`` is opt-OUT of the runtime
    behavior but agent IS engaging with the feature; should still surface
    the guide topic so they can read the docs that explain the opt-out."""
    ir = {
        "nodes": [{"id": "n", "type": "llm", "params": {}, "prewarm": False}],
        "edges": [],
    }
    assert "prompt-caching" in detect_topics_from_ir(ir)


def test_detect_no_caching_for_workflow_without_signals() -> None:
    """Negative case: an LLM workflow with no cache signals → no caching topic."""
    ir = {
        "nodes": [{"id": "n", "type": "llm", "params": {"model": "x"}}],
        "edges": [],
    }
    assert "prompt-caching" not in detect_topics_from_ir(ir)


# ---------------------------------------------------------------------------
# Sub-workflow recursion (F-03 Gap B)
# ---------------------------------------------------------------------------


def _write_pflow(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_compose_walks_into_sub_workflow_files_for_topics(tmp_path: Path) -> None:
    """Parent workflow with a ``workflow:`` node pointing at a child that
    declares prompt caching → parent's ``pflow guide`` surfaces ``prompt-caching``."""
    child = tmp_path / "child.pflow.md"
    _write_pflow(
        child,
        """\
# Child

A child workflow that uses caching.

## Inputs

### doc

A document.

- type: string

## Cache

- ttl: 5m

```cache
[A document][${doc}]
```

## Steps

### summarize

Summarize the doc.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt: Summarize.
- prompt_cache: [doc]
""",
    )
    parent = tmp_path / "parent.pflow.md"
    _write_pflow(
        parent,
        """\
# Parent

Dispatches to a child.

## Steps

### dispatch

Run the child.

- type: workflow
- workflow: ./child.pflow.md
""",
    )
    result = compose_guide([str(parent)])
    assert "Caching" in result, "parent should surface caching topic from child sub-workflow"


def test_compose_handles_cycle_with_warning(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Two workflows that reference each other → no infinite recursion;
    cycle warning emitted to stderr; topic detection completes."""
    a = tmp_path / "a.pflow.md"
    b = tmp_path / "b.pflow.md"
    _write_pflow(
        a,
        """\
# A

A node that references B.

## Steps

### to-b

Dispatch.

- type: workflow
- workflow: ./b.pflow.md
""",
    )
    _write_pflow(
        b,
        """\
# B

A node that references A.

## Steps

### to-a

Dispatch.

- type: workflow
- workflow: ./a.pflow.md
""",
    )
    result = compose_guide([str(a)])
    captured = capsys.readouterr()
    assert "Sub-Workflow" in result
    assert "cycle detected" in captured.err.lower()


def test_compose_fails_soft_on_broken_sub_workflow(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """A parent that references a missing child file → stderr warning, but
    the parent's own detected topics still flow through."""
    parent = tmp_path / "parent.pflow.md"
    _write_pflow(
        parent,
        """\
# Parent

Has a real LLM node and a reference to a missing child.

## Steps

### think

Do something.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt: Hi.

### dispatch

Reference a child that doesn't exist.

- type: workflow
- workflow: ./does-not-exist.pflow.md
""",
    )
    result = compose_guide([str(parent)])
    captured = capsys.readouterr()
    # Parent topic still surfaced
    assert "LLM" in result
    # Warning surfaced for the broken descendant
    assert "skipped sub-workflow" in captured.err.lower()


def test_compose_saved_workflow_walks_sub_workflows(tmp_path: Path, isolate_pflow_config: dict) -> None:
    """The saved-workflow CLI form (`pflow guide my-saved-name`) must also
    walk sub-workflows — F-03 reproduction explicitly covered the saved-name
    invocation, so the fix has to handle both file-path and saved-name."""
    workflows_path = Path(isolate_pflow_config["workflows_path"])
    parent_dir = workflows_path / "parent-of-cache-tree"
    parent_dir.mkdir(parents=True)

    # Child sits inside the saved-workflow folder (bundled dependency)
    _write_pflow(
        parent_dir / "child.pflow.md",
        """\
# Child

Caches a doc.

## Inputs

### doc

A doc.

- type: string

## Cache

- ttl: 5m

```cache
[A doc][${doc}]
```

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt: Summarize.
- prompt_cache: [doc]
""",
    )
    _write_pflow(
        parent_dir / "parent-of-cache-tree.pflow.md",
        """\
---
name: parent-of-cache-tree
---
# Parent

Dispatch to child.

## Steps

### dispatch

Run child.

- type: workflow
- workflow: ./child.pflow.md
""",
    )

    result = compose_guide(["parent-of-cache-tree"])
    assert "Caching" in result, "saved-name CLI form should walk sub-workflows for caching"


def test_compose_real_lyrics_generator_detects_caching() -> None:
    """End-to-end mutation contract: the real Task 159 motivating workflow
    tree (lyrics-generator → song-creator) MUST surface caching now.

    This locks F-03's fix structurally: if a future change loses the
    sub-workflow recursion, this test fails on a real-world fixture (not a
    synthetic one that could drift in shape with the bug)."""
    fixture = (
        Path(__file__).parent.parent.parent
        / ".taskmaster"
        / "tasks"
        / "task_159"
        / "baseline"
        / "_shared"
        / "workflows"
        / "lyrics-generator"
        / "lyrics-generator.pflow.md"
    )
    if not fixture.exists():
        pytest.skip(f"Baseline fixture not present at {fixture}")
    result = compose_guide([str(fixture)])
    assert "Caching" in result


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_guide_single_topic() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(guide_cmd, ["http"])
    assert result.exit_code == 0
    assert "HTTP" in result.output


def test_cli_guide_unknown_topic_exits_nonzero() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(guide_cmd, ["nonexistent-topic"])
    assert result.exit_code == 1


def test_cli_guide_multiple_topics() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(guide_cmd, ["http", "llm", "batch"])
    assert result.exit_code == 0
    assert "HTTP" in result.output
    assert "LLM" in result.output
    assert "Batch" in result.output


# ---------------------------------------------------------------------------
# Content integrity
# ---------------------------------------------------------------------------


def test_all_chunks_exist_and_nonempty() -> None:
    """Every topic returned by list_topics() must have a non-empty file."""

    for topic in list_topics():
        content = compose_guide([topic])
        assert len(content.strip()) > 10, f"Topic '{topic}' has no content"


def test_node_chunks_have_heading() -> None:
    """Node and feature chunks should start with a markdown heading."""
    from pflow.guide import GUIDE_DIR

    for subdir in ("nodes", "features"):
        d = GUIDE_DIR / subdir
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            content = f.read_text(encoding="utf-8")
            assert content.startswith("#"), f"{subdir}/{f.name} missing heading"


# ---------------------------------------------------------------------------
# Reserved names
# ---------------------------------------------------------------------------


def test_topic_names_are_reserved() -> None:
    """All guide topic names should be in RESERVED_WORKFLOW_NAMES."""
    from pflow.core.workflow.save_service import RESERVED_WORKFLOW_NAMES

    for topic in list_topics():
        assert topic in RESERVED_WORKFLOW_NAMES, f"Topic '{topic}' not in RESERVED_WORKFLOW_NAMES"
