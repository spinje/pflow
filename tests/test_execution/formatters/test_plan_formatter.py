"""Unit tests for the --dry-run plan formatter.

These pin text-rendering decisions that are easy to regress without
visible test failures elsewhere: the header phrasing, type-name
translation, nested-aware summary counts, and the recursive
"nothing cached" guard. All are agent-UX contracts.
"""

from __future__ import annotations

from pflow.execution.formatters.plan_formatter import format_plan_json, format_plan_text
from pflow.execution.result import Plan, PlanEntry, PlanSummary


def _summary(**overrides):
    base = {
        "total": 0,
        "cached_count": 0,
        "execute_count": 0,
        "cache_boundary": None,
        "execute_by_type": {},
        "estimated_cost_usd": 0.0,
        "nodes_without_history": 0,
    }
    base.update(overrides)
    return PlanSummary(**base)


def test_format_plan_text_header_uses_basename_not_full_path() -> None:
    """Text header must show the file's basename, not its absolute path."""
    plan = Plan(
        workflow="/absolute/path/to/my-workflow.pflow.md",
        entries=[
            PlanEntry(node_id="a", node_type="ShellNode", status="execute", cause="no_cache_match"),
        ],
        summary=_summary(total=1, execute_count=1, execute_by_type={"ShellNode": 1}),
    )
    out = format_plan_text(plan)
    first_line = out.splitlines()[0]
    assert first_line.startswith("Dry-run for my-workflow.pflow.md"), (
        f"header must lead with 'Dry-run for <basename>', got: {first_line!r}"
    )
    assert "/absolute/path/to/" not in first_line, "full path must not appear in the text header"


def test_format_plan_text_summary_translates_class_names() -> None:
    """Summary type breakdown must use the human-readable tags, not class names."""
    plan = Plan(
        workflow="wf.pflow.md",
        entries=[
            PlanEntry(node_id="a", node_type="LLMNode", status="execute", cause="no_cache_match"),
            PlanEntry(node_id="b", node_type="PythonCodeNode", status="execute", cause="downstream"),
            PlanEntry(node_id="c", node_type="ShellNode", status="execute", cause="downstream"),
        ],
        summary=_summary(
            total=3,
            execute_count=3,
            execute_by_type={"LLMNode": 1, "PythonCodeNode": 1, "ShellNode": 1},
        ),
    )
    out = format_plan_text(plan)
    # Translated tags appear; raw class names do not.
    assert "1 llm" in out and "1 code" in out and "1 shell" in out
    assert "LLMNode" not in out and "PythonCodeNode" not in out and "ShellNode" not in out


def test_format_plan_text_summary_prefers_nested_counts_when_present() -> None:
    """When `_including_nested` fields are set, the summary must use those."""
    plan = Plan(
        workflow="wf.pflow.md",
        entries=[
            PlanEntry(node_id="parent", node_type="ShellNode", status="execute", cause="no_cache_match"),
        ],
        summary=_summary(
            total=1,
            execute_count=1,
            execute_by_type={"ShellNode": 1},
            total_including_nested=5,
            cached_including_nested=2,
            execute_including_nested=3,
            execute_by_type_including_nested={"ShellNode": 1, "LLMNode": 2},
        ),
    )
    out = format_plan_text(plan)
    assert "Summary (including nested):" in out
    assert "2 cached" in out and "3 would execute" in out
    # Type line reflects nested breakdown (LLMNode → llm).
    assert "2 llm" in out
    # Per-level-only phrasing absent.
    assert "Summary:" not in out.replace("Summary (including nested):", "")


def test_format_plan_text_omits_redundant_no_side_effects_line() -> None:
    """The trailing 'No side effects performed.' line is redundant with --dry-run itself."""
    plan = Plan(
        workflow="wf.pflow.md",
        entries=[
            PlanEntry(node_id="a", node_type="ShellNode", status="execute", cause="no_cache_match"),
        ],
        summary=_summary(total=1, execute_count=1, execute_by_type={"ShellNode": 1}),
    )
    assert "No side effects performed." not in format_plan_text(plan)


def test_format_plan_text_nothing_cached_divider_respects_nested_cached_entries() -> None:
    """Top-level 'nothing cached' divider must NOT render when children are cached.

    Edge case: a plan whose top-level entries are all `sub_workflow` entries
    with fully-cached children. Something IS cached, just not at the top
    level. Rendering 'nothing cached — full run' would be misleading.
    """
    child_plan = Plan(
        workflow="child.pflow.md",
        entries=[
            PlanEntry(
                node_id="child-a",
                node_type="ShellNode",
                status="cached",
                cause="hash_match",
                action="default",
                age_sec=10.0,
            ),
        ],
        summary=_summary(total=1, cached_count=1),
    )
    plan = Plan(
        workflow="parent.pflow.md",
        entries=[
            PlanEntry(
                node_id="middle",
                node_type="WorkflowExecutor",
                status="sub_workflow",
                cause="no_cache_match",
                sub_plan=child_plan,
            ),
        ],
        summary=_summary(
            total=1,
            execute_count=1,
            execute_by_type={"WorkflowExecutor": 1},
            total_including_nested=2,
            cached_including_nested=1,
            execute_including_nested=1,
            execute_by_type_including_nested={"WorkflowExecutor": 1},
        ),
    )
    assert "nothing cached" not in format_plan_text(plan)


def test_format_plan_text_nothing_cached_divider_shows_when_truly_empty() -> None:
    """Sanity check the opposite: divider DOES show when nothing is cached anywhere."""
    child_plan = Plan(
        workflow="child.pflow.md",
        entries=[
            PlanEntry(node_id="child-a", node_type="ShellNode", status="execute", cause="downstream"),
        ],
        summary=_summary(total=1, execute_count=1, execute_by_type={"ShellNode": 1}),
    )
    plan = Plan(
        workflow="parent.pflow.md",
        entries=[
            PlanEntry(node_id="top", node_type="ShellNode", status="execute", cause="no_cache_match"),
            PlanEntry(
                node_id="middle",
                node_type="WorkflowExecutor",
                status="sub_workflow",
                cause="downstream",
                sub_plan=child_plan,
            ),
        ],
        summary=_summary(
            total=2,
            execute_count=2,
            execute_by_type={"ShellNode": 1, "WorkflowExecutor": 1},
            total_including_nested=3,
            cached_including_nested=0,
            execute_including_nested=3,
            execute_by_type_including_nested={"ShellNode": 2, "WorkflowExecutor": 1},
        ),
    )
    assert "─── nothing cached — full run ───" in format_plan_text(plan)


def test_format_plan_text_batch_parent_header_includes_items_and_parallel() -> None:
    """Batch sub-workflow parents render the item count and parallel flag."""
    child_plan = Plan(
        workflow="./child.pflow.md",
        entries=[
            PlanEntry(
                node_id="echo",
                node_type="ShellNode",
                status="execute",
                cause="no_cache_match",
                batch_items_cached=1,
                batch_items_total=2,
                last_duration_ms=2300.0,
            )
        ],
        summary=_summary(
            total=2,
            cached_count=1,
            execute_count=1,
            execute_by_type={"ShellNode": 1},
            total_including_nested=2,
            cached_including_nested=1,
            execute_including_nested=1,
            execute_by_type_including_nested={"ShellNode": 1},
            estimated_duration_ms_including_nested=2300.0,
        ),
    )
    plan = Plan(
        workflow="parent.pflow.md",
        entries=[
            PlanEntry(
                node_id="fanout",
                node_type="WorkflowExecutor",
                status="sub_workflow",
                cause="no_cache_match",
                sub_plan=child_plan,
                batch_count=2,
                batch_parallel=True,
            )
        ],
        summary=_summary(
            total=1,
            execute_count=1,
            execute_by_type={"WorkflowExecutor": 1},
            total_including_nested=3,
            cached_including_nested=1,
            execute_including_nested=2,
            execute_by_type_including_nested={"WorkflowExecutor": 1, "ShellNode": 1},
        ),
    )

    out = format_plan_text(plan)

    assert "[workflow './child.pflow.md' \u00d7 2 items, parallel]" in out


def test_format_plan_text_batch_partial_child_shows_fraction_and_stats() -> None:
    """Partial batch cache lines show `M/N would execute` with average stats."""
    plan = Plan(
        workflow="child.pflow.md",
        entries=[
            PlanEntry(
                node_id="echo",
                node_type="ShellNode",
                status="execute",
                cause="no_cache_match",
                batch_items_cached=1,
                batch_items_total=2,
                last_duration_ms=2300.0,
            )
        ],
        summary=_summary(total=2, cached_count=1, execute_count=1, execute_by_type={"ShellNode": 1}),
    )

    out = format_plan_text(plan)

    assert "1/2 would execute" in out
    assert "~2.3s" in out


def test_format_plan_text_batch_all_cached_child_omits_fraction() -> None:
    """All-cached synthetic batch child entries render as normal cached lines."""
    plan = Plan(
        workflow="child.pflow.md",
        entries=[
            PlanEntry(
                node_id="echo",
                node_type="ShellNode",
                status="cached",
                cause="hash_match",
                age_sec=5.0,
                batch_items_cached=2,
                batch_items_total=2,
            )
        ],
        summary=_summary(total=2, cached_count=2, execute_count=0),
    )

    out = format_plan_text(plan)

    assert "(5s ago)" in out
    assert "1/2 would execute" not in out


def test_format_plan_text_nothing_cached_divider_respects_partial_batch_cache() -> None:
    """Partial batch cache counts as cached for the top-level divider guard."""
    child_plan = Plan(
        workflow="child.pflow.md",
        entries=[
            PlanEntry(
                node_id="echo",
                node_type="ShellNode",
                status="execute",
                cause="no_cache_match",
                batch_items_cached=1,
                batch_items_total=2,
                last_duration_ms=2300.0,
            )
        ],
        summary=_summary(
            total=2,
            cached_count=1,
            execute_count=1,
            execute_by_type={"ShellNode": 1},
            total_including_nested=2,
            cached_including_nested=1,
            execute_including_nested=1,
            execute_by_type_including_nested={"ShellNode": 1},
        ),
    )
    plan = Plan(
        workflow="parent.pflow.md",
        entries=[
            PlanEntry(
                node_id="fanout",
                node_type="WorkflowExecutor",
                status="sub_workflow",
                cause="no_cache_match",
                sub_plan=child_plan,
                batch_count=2,
            )
        ],
        summary=_summary(
            total=1,
            execute_count=1,
            execute_by_type={"WorkflowExecutor": 1},
            total_including_nested=3,
            cached_including_nested=1,
            execute_including_nested=2,
            execute_by_type_including_nested={"WorkflowExecutor": 1, "ShellNode": 1},
        ),
    )

    assert "nothing cached" not in format_plan_text(plan)


def test_format_plan_json_exposes_execute_by_type_including_nested() -> None:
    """JSON must expose the nested-type breakdown as a stable agent field."""
    plan = Plan(
        workflow="wf.pflow.md",
        entries=[
            PlanEntry(node_id="a", node_type="LLMNode", status="execute", cause="no_cache_match"),
        ],
        summary=_summary(
            total=1,
            execute_count=1,
            execute_by_type={"LLMNode": 1},
            total_including_nested=3,
            cached_including_nested=0,
            execute_including_nested=3,
            execute_by_type_including_nested={"LLMNode": 2, "ShellNode": 1},
        ),
    )
    payload = format_plan_json(plan)
    # JSON keeps raw class names (stable agent contract, not pretty tags).
    assert payload["summary"]["execute_by_type"] == {"LLMNode": 1}
    assert payload["summary"]["execute_by_type_including_nested"] == {"LLMNode": 2, "ShellNode": 1}


def test_format_plan_json_exposes_batch_fields() -> None:
    """JSON includes batch-specific entry fields when they are present."""
    plan = Plan(
        workflow="wf.pflow.md",
        entries=[
            PlanEntry(
                node_id="fanout",
                node_type="WorkflowExecutor",
                status="sub_workflow",
                cause="no_cache_match",
                batch_count=3,
                batch_parallel=True,
                batch_items_cached=2,
                batch_items_total=3,
            )
        ],
        summary=_summary(total=1, execute_count=1, execute_by_type={"WorkflowExecutor": 1}),
    )

    payload = format_plan_json(plan)

    assert payload["plan"][0]["batch_count"] == 3
    assert payload["plan"][0]["batch_parallel"] is True
    assert payload["plan"][0]["batch_items_cached"] == 2
    assert payload["plan"][0]["batch_items_total"] == 3


def test_format_plan_json_preserves_full_workflow_path() -> None:
    """JSON `workflow` field must carry the full path (stable agent contract)."""
    plan = Plan(
        workflow="/absolute/path/to/wf.pflow.md",
        entries=[
            PlanEntry(node_id="a", node_type="ShellNode", status="execute", cause="no_cache_match"),
        ],
        summary=_summary(total=1, execute_count=1, execute_by_type={"ShellNode": 1}),
    )
    assert format_plan_json(plan)["workflow"] == "/absolute/path/to/wf.pflow.md"
