"""Tests for the ``pflow guide`` command and guide composition."""

from __future__ import annotations

from pathlib import Path

import click.testing
import pytest

from pflow.cli.commands.guide import guide_cmd
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
    assert "# pflow Framework" in result or "pflow" in result.lower()


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


def test_compose_deduplicates_topics() -> None:
    result_once = compose_guide(["http"])
    result_twice = compose_guide(["http", "http"])
    # Same content — http only appears once
    assert result_once == result_twice


def test_compose_unknown_topic_raises() -> None:
    with pytest.raises(GuideError, match="Unknown topic 'nonexistent'"):
        compose_guide(["nonexistent"])


def test_compose_unknown_topic_lists_available() -> None:
    with pytest.raises(GuideError, match="Available topics:.*http"):
        compose_guide(["nonexistent"])


def test_compose_separator_between_chunks() -> None:
    result = compose_guide(["http", "llm"])
    assert "\n\n---\n\n" in result


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
    assert "Branching" in result  # on-error edge


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
    with pytest.raises(GuideError, match="Failed to parse|No guide topics"):
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


def test_detect_branching_via_error_edge() -> None:
    ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {}},
            {"id": "h", "type": "shell", "params": {}},
        ],
        "edges": [{"from": "a", "to": "h", "action": "error"}],
    }
    assert "branching" in detect_topics_from_ir(ir)


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
