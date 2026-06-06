"""Unit tests for trace report generator.

Tests the markdown generation functions and directory structure
produced from trace JSON files.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import ReportGenerationError
from pflow.core.trace_io import intern_blobs
from pflow.core.trace_report import (
    _build_batch_item_file,
    _build_batch_item_summary,
    _build_node_file,
    _build_node_summary,
    _build_output_lookup,
    _build_summary,
    _collect_errors,
    _compute_batch_item_cost,
    _compute_event_cost,
    _compute_outlier_threshold,
    _detect_anomalies,
    _detect_batch_item_anomalies,
    _extract_item_label,
    _find_notable_items,
    _format_cost,
    _item_filename,
    _replace_report_dir,
    _slugify_label,
    _suggest_template_fixes,
    generate_report,
    validate_report_output_dir,
)
from tests.shared.trace_fixture_builder import TraceFixtureBuilder

# --- Fixtures ---


def _make_trace(
    nodes: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a minimal valid trace dict."""
    trace: dict[str, Any] = {
        "format_version": "2.0.0",
        "execution_id": "test-exec-id",
        "workflow_name": "test-workflow",
        "start_time": "2026-03-23T10:00:00",
        "end_time": "2026-03-23T10:00:05",
        "duration_ms": 5000.0,
        "final_status": "success",
        "nodes_executed": len(nodes) if nodes else 0,
        "nodes_failed": 0,
        "nodes": nodes or [],
    }
    trace.update(overrides)
    return trace


def _make_event(
    node_id: str = "test-node",
    node_type: str = "TestNode",
    success: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a minimal trace event dict."""
    event: dict[str, Any] = {
        "node_id": node_id,
        "node_type": node_type,
        "duration_ms": 100.0,
        "success": success,
        "timestamp": "2026-03-23T10:00:01",
    }
    event.update(overrides)
    return event


# --- generate_report() ---


class TestGenerateReport:
    def test_nonexistent_trace_returns_none(self, tmp_path: Path) -> None:
        result = generate_report(tmp_path / "nonexistent.json")
        assert result is None

    def test_old_format_rejected(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "old.json"
        trace_file.write_text(json.dumps({"format_version": "1.2.0", "nodes": []}))

        result = generate_report(trace_file, str(tmp_path / "report"))
        assert result is None

    def test_creates_report_directory(self, tmp_path: Path) -> None:
        trace = _make_trace(nodes=[_make_event()])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert report_dir.is_dir()
        assert (report_dir / "summary.md").exists()
        marker = json.loads((report_dir / ".pflow-report.json").read_text())
        assert marker["format"] == "pflow.report"
        assert marker["format_version"] == 1
        assert marker["workflow_name"] == "test-workflow"
        assert marker["trace_path"] == str(trace_file)
        assert marker["trace_format_version"] == "2.0.0"

    def test_creates_per_node_files(self, tmp_path: Path) -> None:
        trace = _make_trace(
            nodes=[
                _make_event(node_id="fetch"),
                _make_event(node_id="transform"),
            ]
        )
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert (report_dir / "01-fetch.md").exists()
        assert (report_dir / "02-transform.md").exists()

    def test_interned_trace_report_renders_resolved_content(self, tmp_path: Path) -> None:
        large_prompt = "REPORT-PROMPT-" + ("x" * 2048)
        trace = _make_trace(nodes=[_make_event(node_id="ask", node_type="LLMNode", llm_prompt=large_prompt)])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(intern_blobs(trace)), encoding="utf-8")

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        node_md = (report_dir / "01-ask.md").read_text(encoding="utf-8")
        assert large_prompt in node_md
        assert "$pflow_blob" not in node_md

    def test_failed_batch_aggregate_report_compacts_error_items(self, tmp_path: Path) -> None:
        payload = "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"
        batch_event = _make_event(
            node_id="fail-batch",
            node_type="ShellNode",
            success=False,
            error="Batch 'fail-batch' failed at item [0]: forced batch failure for oversized-item",
            node_output={
                "count": 1,
                "success_count": 0,
                "error_count": 1,
                "errors": [
                    {
                        "index": 0,
                        "item": {"label": "oversized-item", "payload": payload},
                        "item_summary": {
                            "summary_version": 1,
                            "type": "dict",
                            "label": "oversized-item",
                            "size_chars": len(payload),
                            "sha256": "123456789abc",
                            "summary": "label='oversized-item'; payload=<str 1909 chars sha256=123456789abc>",
                            "truncated": True,
                        },
                        "error": "RuntimeError: forced batch failure for oversized-item",
                    }
                ],
                "batch_metadata": {"execution_mode": "sequential"},
                "results": [],
            },
        )
        trace = _make_trace(
            nodes=[batch_event],
            final_status="failed",
            nodes_failed=1,
            failed_node_ids=["fail-batch"],
        )
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        markdown = (report_dir / "01-fail-batch.md").read_text()
        assert "## Batch Errors" in markdown
        assert "[0] RuntimeError: forced batch failure for oversized-item" in markdown
        assert "label='oversized-item'; payload=<str" in markdown
        assert "PAYLOAD-START" not in markdown
        assert "PAYLOAD-END" not in markdown
        assert "token199" not in markdown
        assert "```json" not in markdown
        assert "## Output" not in markdown

    def test_successful_batch_aggregate_report_surfaces_metadata_no_error_section(self, tmp_path: Path) -> None:
        """A zero-failure batch report must NOT render a "## Batch Errors" section and
        MUST keep its aggregate metadata (count/success_count/error_count/batch_metadata)
        visible in "## Output" (issue #484 companion fix).

        This is the success-case mirror of
        ``test_failed_batch_aggregate_report_compacts_error_items`` and the ONLY guard
        on the ``_has_batch_error_output`` ``and errors`` companion fix. With ``errors``
        now ``[]`` (not ``None``), removing ``and errors`` makes ``_has_batch_error_output``
        return ``True`` for a successful batch, which suppresses these keys from
        ``_format_remaining_node_output``'s "## Output" dump while "## Batch Errors" stays
        empty — so the batch metadata would vanish from the report entirely. The
        ``"success_count" in markdown`` assertion below fails loudly under that regression.
        """
        batch_event = _make_event(
            node_id="ok-batch",
            node_type="ShellNode",
            success=True,
            node_output={
                "count": 2,
                "success_count": 2,
                "error_count": 0,
                "errors": [],
                "batch_metadata": {"execution_mode": "sequential"},
                "results": [{"stdout": "ok-a"}, {"stdout": "ok-b"}],
            },
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        markdown = (report_dir / "01-ok-batch.md").read_text()
        assert "## Batch Errors" not in markdown
        assert "## Output" in markdown
        # The regression catcher: this key is suppressed if `and errors` is removed.
        assert "success_count" in markdown

    def test_batch_node_creates_directory(self, tmp_path: Path) -> None:
        batch_event = _make_event(
            node_id="process",
            batch_items=[
                {"index": 0, "item": "a", "success": True, "duration_ms": 50},
                {"index": 1, "item": "b", "success": True, "duration_ms": 60},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert (report_dir / "01-process").is_dir()
        assert (report_dir / "01-process" / "summary.md").exists()
        assert (report_dir / "01-process" / "item-0-a.md").exists()
        assert (report_dir / "01-process" / "item-1-b.md").exists()

    def test_sub_workflow_batch_creates_item_directories(self, tmp_path: Path) -> None:
        """Batch items with nested events get item directories, not files."""
        batch_event = _make_event(
            node_id="create-songs",
            batch_items=[
                {
                    "index": 0,
                    "item": {"concept": "Song A"},
                    "success": True,
                    "duration_ms": 1000,
                    "events": [
                        _make_event(node_id="write-lyrics"),
                        _make_event(node_id="review"),
                    ],
                },
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        item_dir = report_dir / "01-create-songs" / "item-0-song-a"
        assert item_dir.is_dir()
        assert (item_dir / "summary.md").exists()
        assert (item_dir / "01-write-lyrics.md").exists()
        assert (item_dir / "02-review.md").exists()

    def test_sub_workflow_node_creates_directory(self, tmp_path: Path) -> None:
        """Non-batch sub-workflow events create a directory with child files."""
        event = _make_event(
            node_id="sub-workflow",
            sub_workflow_events=[
                _make_event(node_id="step-1"),
                _make_event(node_id="step-2"),
            ],
        )
        trace = _make_trace(nodes=[event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert (report_dir / "01-sub-workflow").is_dir()
        assert (report_dir / "01-sub-workflow" / "summary.md").exists()
        assert (report_dir / "01-sub-workflow" / "01-step-1.md").exists()
        assert (report_dir / "01-sub-workflow" / "02-step-2.md").exists()

    def test_auto_output_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        trace = _make_trace(nodes=[_make_event()])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, "auto")

        assert report_dir is not None
        assert report_dir == tmp_path / ".pflow" / "reports" / "test-workflow"

    def test_regenerating_report_removes_stale_top_level_pages(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        first_trace_file = tmp_path / "first.json"
        first_trace_file.write_text(
            json.dumps(
                _make_trace(
                    nodes=[
                        _make_event(node_id="fetch"),
                        _make_event(node_id="transform"),
                    ]
                )
            )
        )
        second_trace_file = tmp_path / "second.json"
        second_trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event(node_id="fetch")])))

        generate_report(first_trace_file, str(report_path))
        assert (report_path / "02-transform.md").exists()

        report_dir = generate_report(second_trace_file, str(report_path))

        assert report_dir == report_path
        assert (report_path / "01-fetch.md").exists()
        assert not (report_path / "02-transform.md").exists()

    def test_regenerating_report_removes_stale_nested_pages(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        first_batch = _make_event(
            node_id="batch",
            batch_items=[
                {
                    "index": 0,
                    "item": "a",
                    "success": True,
                    "duration_ms": 50,
                    "events": [
                        _make_event(node_id="child-a"),
                        _make_event(node_id="child-b"),
                    ],
                },
                {
                    "index": 1,
                    "item": "b",
                    "success": True,
                    "duration_ms": 60,
                    "events": [_make_event(node_id="child-c")],
                },
            ],
        )
        second_batch = _make_event(
            node_id="batch",
            batch_items=[
                {
                    "index": 0,
                    "item": "a",
                    "success": True,
                    "duration_ms": 50,
                    "events": [_make_event(node_id="child-a")],
                },
            ],
        )
        first_trace_file = tmp_path / "first.json"
        first_trace_file.write_text(json.dumps(_make_trace(nodes=[first_batch])))
        second_trace_file = tmp_path / "second.json"
        second_trace_file.write_text(json.dumps(_make_trace(nodes=[second_batch])))

        generate_report(first_trace_file, str(report_path))
        assert (report_path / "01-batch" / "item-0-a" / "02-child-b.md").exists()
        assert (report_path / "01-batch" / "item-1-b").exists()

        generate_report(second_trace_file, str(report_path))

        assert (report_path / "01-batch" / "item-0-a" / "01-child-a.md").exists()
        assert not (report_path / "01-batch" / "item-0-a" / "02-child-b.md").exists()
        assert not (report_path / "01-batch" / "item-1-b").exists()

    def test_regenerating_report_handles_leaf_to_container_shape_change(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        first_trace_file = tmp_path / "first.json"
        first_trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event(node_id="process")])))
        second_trace_file = tmp_path / "second.json"
        second_trace_file.write_text(
            json.dumps(
                _make_trace(
                    nodes=[
                        _make_event(
                            node_id="process",
                            sub_workflow_events=[_make_event(node_id="inner")],
                        )
                    ]
                )
            )
        )

        generate_report(first_trace_file, str(report_path))
        assert (report_path / "01-process.md").exists()

        generate_report(second_trace_file, str(report_path))

        assert not (report_path / "01-process.md").exists()
        assert (report_path / "01-process" / "01-inner.md").exists()

    def test_regenerating_report_handles_container_to_leaf_shape_change(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        first_trace_file = tmp_path / "first.json"
        first_trace_file.write_text(
            json.dumps(
                _make_trace(
                    nodes=[
                        _make_event(
                            node_id="process",
                            sub_workflow_events=[_make_event(node_id="inner")],
                        )
                    ]
                )
            )
        )
        second_trace_file = tmp_path / "second.json"
        second_trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event(node_id="process")])))

        generate_report(first_trace_file, str(report_path))
        assert (report_path / "01-process").is_dir()

        generate_report(second_trace_file, str(report_path))

        assert not (report_path / "01-process").exists()
        assert (report_path / "01-process.md").exists()

    def test_explicit_non_empty_unmarked_directory_is_refused(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        report_path.mkdir()
        existing = report_path / "notes.md"
        existing.write_text("do not replace")
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event()])))

        with pytest.raises(ReportGenerationError, match="without \\.pflow-report\\.json"):
            generate_report(trace_file, str(report_path))

        assert existing.read_text() == "do not replace"
        assert not (report_path / "summary.md").exists()

    def test_explicit_invalid_marker_is_refused(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        report_path.mkdir()
        (report_path / ".pflow-report.json").write_text("{not-json")
        existing = report_path / "old.md"
        existing.write_text("old")
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event()])))

        with pytest.raises(ReportGenerationError, match="invalid \\.pflow-report\\.json"):
            generate_report(trace_file, str(report_path))

        assert existing.read_text() == "old"
        assert not (report_path / "summary.md").exists()

    def test_auto_unmarked_existing_directory_is_replaced_for_migration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        report_path = tmp_path / ".pflow" / "reports" / "test-workflow"
        report_path.mkdir(parents=True)
        (report_path / "stale.md").write_text("stale")
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event(node_id="fresh")])))

        report_dir = generate_report(trace_file, "auto")

        assert report_dir == report_path
        assert not (report_path / "stale.md").exists()
        assert (report_path / ".pflow-report.json").exists()
        assert (report_path / "01-fresh.md").exists()

    def test_existing_target_file_is_refused(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report"
        report_path.write_text("not a directory")

        with pytest.raises(ReportGenerationError, match="not a directory"):
            validate_report_output_dir(report_path, allow_unmarked_existing=False)

    def test_existing_symlink_target_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        report_path = tmp_path / "report-link"
        report_path.symlink_to(target, target_is_directory=True)

        with pytest.raises(ReportGenerationError, match="symlink"):
            validate_report_output_dir(report_path, allow_unmarked_existing=False)

    def test_render_failure_preserves_previous_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import pflow.core.trace_report as trace_report_module

        report_path = tmp_path / "report"
        first_trace_file = tmp_path / "first.json"
        first_trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event(node_id="old")])))
        second_trace_file = tmp_path / "second.json"
        second_trace_file.write_text(json.dumps(_make_trace(nodes=[_make_event(node_id="new")])))

        generate_report(first_trace_file, str(report_path))
        old_summary = (report_path / "summary.md").read_text()

        def fail_write_node_files(
            _events: list[dict[str, Any]],
            _parent_dir: Path,
            node_index: int,
        ) -> int:
            _ = node_index
            raise RuntimeError("render exploded")

        monkeypatch.setattr(trace_report_module, "_write_node_files", fail_write_node_files)

        with pytest.raises(RuntimeError, match="render exploded"):
            generate_report(second_trace_file, str(report_path))

        assert (report_path / "summary.md").read_text() == old_summary
        assert (report_path / "01-old.md").exists()
        assert not (report_path / "01-new.md").exists()
        assert not list(tmp_path.glob(".report.tmp-*"))

    def test_replacement_failure_restores_previous_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        report_path = tmp_path / "report"
        report_path.mkdir()
        old_file = report_path / "old.md"
        old_file.write_text("old")
        temp_path = tmp_path / ".report.tmp-test"
        temp_path.mkdir()
        (temp_path / "new.md").write_text("new")

        original_rename = Path.rename

        def fail_second_rename(self: Path, target: str | Path) -> Path:
            if self == temp_path and Path(target) == report_path:
                raise OSError("second rename failed")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", fail_second_rename)

        with pytest.raises(ReportGenerationError, match="Failed to replace report directory"):
            _replace_report_dir(report_path, temp_path)

        assert report_path.is_dir()
        assert (report_path / "old.md").read_text() == "old"
        assert not (report_path / "new.md").exists()
        assert temp_path.exists()


# --- _build_summary() ---


class TestBuildSummary:
    def test_includes_workflow_name(self) -> None:
        trace = _make_trace(workflow_name="my-pipeline")
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "# Execution Report: my-pipeline" in md

    def test_includes_status_and_duration(self) -> None:
        # failed_node_ids present → report generator trusts stored final_status;
        # without it the generator recomputes (legacy-trace path).
        trace = _make_trace(
            final_status="failed",
            duration_ms=12345.0,
            nodes=[_make_event(node_id="failing", success=False, error="boom")],
            failed_node_ids=["failing"],
            nodes_failed=1,
        )
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "- Status: failed" in md
        assert "- Duration: 12.3s" in md

    def test_includes_llm_summary(self) -> None:
        trace = _make_trace(
            llm_summary={
                "total_calls": 5,
                "total_tokens": 12345,
                "total_input_tokens": 3200,
                "total_output_tokens": 9145,
                "models_used": ["gpt-4", "claude"],
            }
        )
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "- LLM calls: 5" in md
        assert "- Tokens: 3,200 in / 9,145 out" in md
        assert "gpt-4" in md
        assert "claude" in md

    def test_agent_calls_label_with_turns_and_cache(self) -> None:
        """claude-code runs render 'Agent calls: N (T turns)', and `in` is the
        true total (uncached + cache-write + cache-read) with a cache-% suffix."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 9,
                "agent_calls": 9,
                "total_num_turns": 104,
                "total_input_tokens": 1743,
                "total_cache_creation_tokens": 153248,
                "total_cache_read_tokens": 1982131,
                "total_output_tokens": 41733,
                "models_used": ["claude-sonnet-4-5"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "- Agent calls: 9 (104 turns)" in md
        # 1,743 + 153,248 + 1,982,131 = 2,137,122 in; 1,982,131 / 2,137,122 ≈ 93%
        assert "- Tokens: 2,137,122 in / 41,733 out  ·  93% of input cached" in md
        assert "LLM calls" not in md

    def test_mixed_agent_and_llm_calls_label(self) -> None:
        """A run with both claude-code and llm nodes surfaces both counts."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 5,
                "agent_calls": 2,
                "total_num_turns": 30,
                "total_input_tokens": 1000,
                "total_output_tokens": 500,
                "models_used": ["claude-sonnet-4-5", "gpt-4"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "- Agent calls: 2 (30 turns) · LLM calls: 3" in md

    def test_empty_llm_summary_omitted(self) -> None:
        """LLM summary with zero calls should not render models/tokens lines."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 0,
                "total_tokens": 0,
                "models_used": [],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "LLM calls" not in md
        assert "Tokens" not in md
        assert "Models" not in md

    def test_llm_summary_without_tokens(self) -> None:
        """LLM summary with calls but zero tokens should omit tokens line."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 1,
                "total_tokens": 0,
                "models_used": ["gpt-4"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "- LLM calls: 1" in md
        assert "Tokens" not in md
        assert "- Models: gpt-4" in md

    def test_pipeline_table(self) -> None:
        trace = _make_trace(
            nodes=[
                _make_event(node_id="fetch", node_type="ShellNode", duration_ms=200),
                _make_event(node_id="process", node_type="LLMNode", success=False, duration_ms=500),
            ]
        )
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "| 1 | fetch | shell | success | 200ms | \u2014 | \u2014 |" in md
        assert "| 2 | process | llm | failed | 500ms | \u2014 | \u2014 |" in md


# --- _build_node_file() ---


class TestBuildNodeFile:
    def test_basic_node(self) -> None:
        event = _make_event(node_id="my-node", node_type="ShellNode", duration_ms=42.5)
        md = _build_node_file(event)
        assert "# my-node" in md
        assert "- Type: ShellNode" in md
        assert "- Time: 42ms" in md
        assert "- Status: success" in md

    def test_cached_node_shows_cached_status(self) -> None:
        event = _make_event(node_id="cached-node", cached=True, duration_ms=0)
        md = _build_node_file(event)
        assert "- Status: success [cached]" in md
        assert "- Time: 0ms" in md

    def test_failed_node_shows_error(self) -> None:
        event = _make_event(success=False, error="Connection refused")
        md = _build_node_file(event)
        assert "- Status: failed" in md
        assert "- Error: Connection refused" in md

    def test_llm_metadata(self) -> None:
        event = _make_event(
            llm_call={
                "model": "gpt-4",
                "input_tokens": 1000,
                "output_tokens": 200,
                "cost_usd": 0.042,
            }
        )
        md = _build_node_file(event)
        assert "- Model: gpt-4" in md
        assert "- Tokens: 1,000 in / 200 out" in md
        assert "- Paid this run: $0.0420" in md

    def test_llm_metadata_shows_turns_and_session(self) -> None:
        # claude-code nodes carry num_turns (agent loop effort) and session_id.
        event = _make_event(
            llm_call={
                "model": "claude-sonnet-4-5",
                "input_tokens": 93,
                "output_tokens": 3477,
                "cost_usd": 0.1957,
                "num_turns": 18,
                "session_id": "7e81004e-5ba2-4c9f",
            }
        )
        md = _build_node_file(event)
        assert "- Turns: 18" in md
        assert "- Session: 7e81004e-5ba2-4c9f" in md

    def test_llm_metadata_omits_turns_and_session_when_absent(self) -> None:
        # llm-node (LiteLLM) calls carry neither field — the lines must not appear.
        event = _make_event(
            llm_call={
                "model": "gpt-4",
                "input_tokens": 1000,
                "output_tokens": 200,
                "cost_usd": 0.042,
            }
        )
        md = _build_node_file(event)
        assert "- Turns:" not in md
        assert "- Session:" not in md

    def test_cached_llm_metadata_uses_source_turns_and_session_labels(self) -> None:
        builder = TraceFixtureBuilder()
        event = builder.cached_llm_event_with_call("draft", cost_usd=0.07)
        event["llm_call"]["num_turns"] = 5
        event["llm_call"]["session_id"] = "cached-session-id"

        md = _build_node_file(event)

        assert "- Source turns: 5" in md
        assert "- Source session: cached-session-id" in md

    def test_cached_llm_metadata_splits_paid_and_historical_cost(self) -> None:
        builder = TraceFixtureBuilder()
        event = builder.cached_llm_event_with_call("draft", cost_usd=0.07)

        md = _build_node_file(event)

        assert "- Status: success [cached]" in md
        assert "- Source model: anthropic/claude-sonnet-4-5" in md
        # `in` is the true total: 1,000 uncached + 950 cache-read = 1,950 (49% cached).
        assert "- Source tokens: 1,950 in / 100 out  ·  49% of input cached" in md
        assert "- Paid this run: $0.0000" in md
        assert "- Historical source cost: $0.0700" in md
        assert "- Cost: $0.0700" not in md

    def test_cached_llm_metadata_omits_historical_cost_when_absent(self) -> None:
        builder = TraceFixtureBuilder()
        event = builder.cached_llm_event_with_call("draft", cost_usd=0.07)
        event["llm_call"]["cost_usd"] = None

        md = _build_node_file(event)

        assert "- Paid this run: $0.0000" in md
        assert "Historical source cost" not in md

    def test_in_process_cached_llm_metadata_uses_non_historical_source_cost_label(self) -> None:
        builder = TraceFixtureBuilder()
        event = builder.cached_llm_event_with_call("draft", cost_usd=0.07, cache_source="in_process")

        md = _build_node_file(event)

        assert "- Paid this run: $0.0000" in md
        assert "- Source call cost: $0.0700" in md
        assert "Historical source cost" not in md

    def test_template_resolutions_prompt(self) -> None:
        event = _make_event(
            template_resolutions={
                "prompt": {
                    "template": "Summarize ${data}",
                    "resolved": "Summarize the quarterly report...",
                },
            }
        )
        md = _build_node_file(event)
        assert "## Prompt" in md
        assert "Summarize the quarterly report..." in md

    def test_llm_prompt_fallback(self) -> None:
        """When no template_resolutions for prompt, falls back to llm_prompt."""
        event = _make_event(llm_prompt="Direct prompt text")
        md = _build_node_file(event)
        assert "## Prompt" in md
        assert "Direct prompt text" in md

    def test_llm_prompt_fallback_renders_blocks_as_json(self) -> None:
        """Block-shaped prewarm prompts render without assuming a flat string."""
        event = _make_event(
            llm_prompt=[
                {"type": "text", "text": "Shared prefix", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "Dynamic suffix"},
            ]
        )
        md = _build_node_file(event)
        assert "## Prompt" in md
        assert "```json" in md
        assert '"cache_control"' in md
        assert "Dynamic suffix" in md

    def test_batch_item_file_renders_llm_prompt_blocks(self) -> None:
        """Per-item report files flow through the same prompt renderer."""
        item = {
            "index": 0,
            "success": True,
            "duration_ms": 12,
            "llm_prompt": [
                {"type": "text", "text": "Shared prefix", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "red"},
            ],
        }
        md = _build_batch_item_file(item, _make_event(node_id="scorer", node_type="LLMNode"))
        assert "## Prompt" in md
        assert "```json" in md
        assert '"cache_control"' in md
        assert "red" in md

    def test_shell_command_resolution(self) -> None:
        event = _make_event(
            template_resolutions={
                "command": {
                    "template": "curl ${url}",
                    "resolved": "curl https://api.example.com",
                },
            }
        )
        md = _build_node_file(event)
        assert "## Command" in md
        assert "curl https://api.example.com" in md

    def test_llm_response(self) -> None:
        event = _make_event(llm_response="Here is the summary...")
        md = _build_node_file(event)
        assert "## Response" in md
        assert "Here is the summary..." in md

    def test_shell_stdout_stderr(self) -> None:
        event = _make_event(node_output={"stdout": "output line", "stderr": "warning line"})
        md = _build_node_file(event)
        assert "## stdout" in md
        assert "output line" in md
        assert "## stderr" in md
        assert "warning line" in md

    def test_empty_stderr_omitted(self) -> None:
        """Empty stderr should not produce a section."""
        event = _make_event(node_output={"stdout": "output line", "stderr": ""})
        md = _build_node_file(event)
        assert "## stdout" in md
        assert "output line" in md
        assert "## stderr" not in md

    def test_empty_stdout_omitted(self) -> None:
        """Empty stdout should not produce a section."""
        event = _make_event(node_output={"stdout": "", "stderr": "error msg"})
        md = _build_node_file(event)
        assert "## stdout" not in md
        assert "## stderr" in md
        assert "error msg" in md

    def test_structured_result(self) -> None:
        event = _make_event(node_output={"result": {"key": "value", "count": 3}})
        md = _build_node_file(event)
        assert "## Result" in md
        assert '"key": "value"' in md

    def test_llm_response_takes_priority_over_node_output(self) -> None:
        """When llm_response exists, node_output is not shown (avoids duplication)."""
        event = _make_event(
            llm_response="LLM said this",
            node_output={"response": "LLM said this", "other": "data"},
        )
        md = _build_node_file(event)
        assert "## Response" in md
        assert "LLM said this" in md
        # node_output's stdout/stderr/result not shown because llm_response path was taken
        assert "## Output" not in md

    def test_code_node_shows_source_and_inputs(self) -> None:
        """Code node report renders the source code and resolved input variables.

        This is the key debugging view for code nodes: see what code ran and
        what data it received. Without this, agents have to re-run the workflow
        with print statements to inspect code node behavior.
        """
        event = _make_event(
            node_id="transform",
            node_type="PythonCodeNode",
            node_params={"code": "result = len(inputs['data'])"},
            template_resolutions={
                "inputs": {
                    "template": {"data": "${fetch.result}"},
                    "resolved": {"data": [1, 2, 3]},
                }
            },
            node_output={"result": 3, "stdout": ""},
        )
        md = _build_node_file(event)
        assert "## Code" in md
        assert "result = len(inputs['data'])" in md
        assert "## Inputs" in md
        assert '"data"' in md
        assert "## Result" in md

    def test_remaining_resolutions_shown_as_catch_all(self) -> None:
        """Template resolutions not matching prompt/command/inputs get a catch-all section."""
        event = _make_event(
            node_id="fetch",
            node_type="HttpNode",
            template_resolutions={
                "url": {"template": "${config.api_url}/users", "resolved": "https://api.example.com/users"},
                "headers": {"template": {"Auth": "${config.token}"}, "resolved": {"Auth": "Bearer xyz"}},
            },
            node_output={"response": {"users": []}},
        )
        md = _build_node_file(event)
        assert "## Resolved Parameters" in md
        assert "api.example.com" in md

    # --- 2.2.0: ## Cached System rendering ---

    def test_cached_system_string_shape_renders_section(self) -> None:
        """Plain-string llm_system renders as text under the section heading."""
        event = _make_event(
            llm_system="You are a helpful assistant.",
            llm_prompt="Answer the question.",
        )
        md = _build_node_file(event)
        assert "## Cached System" in md
        assert "You are a helpful assistant." in md

    def test_cached_system_list_of_blocks_renders_json_block(self) -> None:
        """list[dict] llm_system emits a fenced JSON block preserving the
        ``cache_control`` marker shape so agents can verify it."""
        event = _make_event(
            llm_system=[
                {"type": "text", "text": "Background"},
                {"type": "text", "text": "Reference", "cache_control": {"type": "ephemeral"}},
            ],
            llm_prompt="Answer the question.",
        )
        md = _build_node_file(event)
        assert "## Cached System" in md
        assert "```json" in md
        assert "cache_control" in md
        assert "ephemeral" in md

    def test_cached_system_section_appears_before_prompt_section(self) -> None:
        """API call order is system → user; the report mirrors that order."""
        event = _make_event(
            llm_system="System content",
            template_resolutions={
                "prompt": {"template": "Hi", "resolved": "Hi there"},
            },
        )
        md = _build_node_file(event)
        cached_idx = md.index("## Cached System")
        prompt_idx = md.index("## Prompt")
        assert cached_idx < prompt_idx

    def test_cached_system_with_skipped_chunks(self) -> None:
        """``cache_chunks_skipped`` from llm_call surfaces under the section
        as a single quoted line."""
        event = _make_event(
            llm_system=[{"type": "text", "text": "Reference"}],
            llm_call={"cache_chunks_skipped": ["foo", "bar"]},
        )
        md = _build_node_file(event)
        assert "## Cached System" in md
        assert "Skipped chunks (resolved as ABSENT): foo, bar" in md

    def test_cached_system_omitted_when_field_absent(self) -> None:
        """No ``llm_system`` field → no ``## Cached System`` heading."""
        event = _make_event(
            template_resolutions={"prompt": {"template": "Hi", "resolved": "Hi"}},
        )
        md = _build_node_file(event)
        assert "## Cached System" not in md

    def test_cached_system_no_skipped_chunks_line_when_empty(self) -> None:
        """Empty ``cache_chunks_skipped`` → no skipped-chunks line."""
        event = _make_event(
            llm_system="Plain system",
            llm_call={"cache_chunks_skipped": []},
        )
        md = _build_node_file(event)
        assert "## Cached System" in md
        assert "Skipped chunks" not in md

    def test_cached_system_renders_all_multi_breakpoint_markers(self) -> None:
        """Under multi-breakpoint placement (Anthropic), an LLM event may carry
        multiple ``cache_control`` markers on its system blocks. The report's
        JSON dump must surface every one — agents reading ``pflow report`` rely
        on this to verify which chunks created cache breakpoints.

        Locks the agent-facing surface against future renderer regressions
        (e.g., a renderer that flattened or dedup'd the marker dicts).
        """
        event = _make_event(
            llm_system=[
                {"type": "text", "text": "Stable system", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "Knowledge ref", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "Session ctx", "cache_control": {"type": "ephemeral"}},
            ],
            llm_prompt="Answer.",
        )
        md = _build_node_file(event)
        # All three blocks' markers must round-trip through the JSON dump.
        assert md.count('"cache_control"') == 3


class TestCacheTelemetrySection:
    """Trace report per-call cache telemetry rendering."""

    def test_live_cache_write_folds_into_tokens_line_no_section(self) -> None:
        """A live (non-replay, non-declared) cache no longer emits a divorced
        ``## Cache telemetry`` section — the tiers are part of the input total
        on the Tokens line. cache-write only (0 read) ⇒ no cache-% suffix."""
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 1500,
                "cache_read_input_tokens": 0,
            },
        )
        md = _build_node_file(event)

        assert "## Cache telemetry" not in md
        assert "- Tokens: 1,500 in / 0 out" in md

    def test_live_cache_read_folds_into_tokens_line_with_pct(self) -> None:
        """A live cache-read fold: ``in`` is the total and the cache-read share
        shows as ``% of input cached`` — no separate section."""
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 8062,
            },
        )
        md = _build_node_file(event)

        assert "## Cache telemetry" not in md
        assert "- Tokens: 8,062 in / 0 out  ·  100% of input cached" in md

    def test_omitted_when_no_cache_signal(self) -> None:
        """Plain LLM call without cache activity suppresses the section."""
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_key": "xyz",
                "cache_chunks_skipped": [],
            },
        )
        md = _build_node_file(event)

        assert "## Cache telemetry" not in md

    def test_omitted_when_no_llm_call(self) -> None:
        event = _make_event()
        md = _build_node_file(event)

        assert "## Cache telemetry" not in md

    def test_cached_replay_heading_tag_appears(self) -> None:
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 8062,
                "cache_source": "memo",
                "cache_key": "abc",
                "cache_age_sec": 559.99,
            },
        )
        md = _build_node_file(event)

        assert "## Cache telemetry (cached result reused from prior run)" in md
        assert "Result age: 560s" in md

    def test_cached_replay_heading_tag_does_not_leak_pflow_vocabulary(self) -> None:
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 8062,
                "cache_source": "memo",
                "cache_key": "abc",
                "cache_age_sec": 559.99,
            },
        )
        md = _build_node_file(event)

        assert "memo" not in md.lower()
        assert "in_process" not in md.lower()

    def test_in_process_replay_heading_does_not_claim_prior_run(self) -> None:
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 8062,
                "cache_source": "in_process",
                "cache_key": "abc",
            },
        )
        md = _build_node_file(event)

        assert "## Cache telemetry (cached result reused)" in md
        assert "prior run" not in md
        assert "in_process" not in md

    def test_section_appears_between_cached_system_and_prompt(self) -> None:
        event = _make_event(
            llm_system="System content",
            llm_call={
                "cache_creation_input_tokens": 1500,
                "cache_read_input_tokens": 0,
                "cache_key": "abc",
            },
            template_resolutions={"prompt": {"template": "Hi", "resolved": "Hi there"}},
        )
        md = _build_node_file(event)

        cached_idx = md.index("## Cached System")
        telemetry_idx = md.index("## Cache telemetry")
        prompt_idx = md.index("## Prompt")
        assert cached_idx < telemetry_idx < prompt_idx

    def test_renders_when_chunks_skipped_present(self) -> None:
        event = _make_event(
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_key": "abc",
                "cache_chunks_skipped": ["foo"],
            },
        )
        md = _build_node_file(event)

        assert "## Cache telemetry" in md

    def test_renders_when_cached_system_present_even_with_zero_tokens(self) -> None:
        """When the workflow opted into caching (llm_system present) but the
        provider didn't fire (e.g., sub-threshold), the section must still
        render so agents see the silent no-op."""
        event = _make_event(
            llm_system=[{"type": "text", "text": "Reference"}],
            llm_call={
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_key": "abc",
                "cache_chunks_skipped": [],
            },
        )
        md = _build_node_file(event)

        assert "## Cached System" in md
        assert "## Cache telemetry" in md
        assert "Cache write: 0 tokens" in md
        assert "Cache read: 0 tokens" in md

    def test_cache_tiers_fold_into_tokens_line_in_batch_item_file(self) -> None:
        """Batch per-item files reuse the shared metadata helper, so a live
        cache's tiers land on the item's Tokens line (input total), not in a
        separate section. Pins the contract against future refactors that move
        batch-item rendering off the shared helper."""
        from pflow.core.trace_report import _build_batch_item_file

        parent_event = _make_event(node_id="batch-parent", node_type="LLMNode")
        item = {
            "index": 0,
            "duration_ms": 50,
            "success": True,
            "llm_call": {
                "cache_creation_input_tokens": 1500,
                "cache_read_input_tokens": 0,
            },
        }
        md = _build_batch_item_file(item, parent_event)

        assert "## Cache telemetry" not in md
        assert "- Tokens: 1,500 in / 0 out" in md

    def test_thinking_tokens_renders_in_metadata_when_nonzero(self) -> None:
        event = _make_event(
            llm_call={
                "model": "anthropic/claude-haiku-4-5",
                "input_tokens": 100,
                "output_tokens": 50,
                "thinking_tokens": 1024,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )
        md = _build_node_file(event)

        assert "- Thinking: 1,024 tokens" in md
        assert "## Cache telemetry" not in md

    def test_thinking_tokens_omitted_in_metadata_when_zero(self) -> None:
        event = _make_event(
            llm_call={
                "model": "anthropic/claude-haiku-4-5",
                "input_tokens": 100,
                "output_tokens": 50,
                "thinking_tokens": 0,
            },
        )
        md = _build_node_file(event)

        assert "Thinking" not in md


# --- _build_node_summary() ---


class TestBuildNodeSummary:
    def test_batch_summary_compact(self) -> None:
        """Compact summary: only the failed item in the table, others hidden."""
        event = _make_event(
            node_id="batch-process",
            node_type="ShellNode",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50, "node_output": {"stdout": "ok", "exit_code": 0}},
                {"index": 1, "success": False, "duration_ms": 30},
                {"index": 2, "success": True, "duration_ms": 40, "node_output": {"stdout": "ok", "exit_code": 0}},
            ],
        )
        md = _build_node_summary(event)
        assert "# batch-process" in md
        assert "- Items: 3 (2/3 succeeded)" in md
        # Only the failed item appears in the table
        assert "| 1 | 30ms | \u2014 | failed |" in md
        # Successful items hidden behind count
        assert "| 0 |" not in md
        assert "... and 2 more succeeded" in md

    def test_sub_workflow_summary_has_pipeline_table(self) -> None:
        """Sub-workflow node summary should include a pipeline table of child nodes."""
        event = _make_event(
            node_id="process-title",
            node_type="WorkflowExecutor",
            sub_workflow_events=[
                _make_event(node_id="step-1", node_type="ShellNode", duration_ms=10),
                _make_event(node_id="step-2", node_type="LLMNode", duration_ms=500, success=False),
            ],
        )
        md = _build_node_summary(event)
        assert "## Pipeline" in md
        assert "| 1 | step-1 | shell | success | 10ms | \u2014 | \u2014 |" in md
        assert "| 2 | step-2 | llm | failed | 500ms | \u2014 | \u2014 |" in md


# --- _build_batch_item_file() ---


class TestBuildBatchItemFile:
    def test_basic_item(self) -> None:
        parent = _make_event(node_id="summarize")
        item = {"index": 2, "item": "doc-c", "success": True, "duration_ms": 100}
        md = _build_batch_item_file(item, parent)
        assert "# summarize — doc-c" in md
        assert "- Status: success" in md

    def test_item_with_llm_data(self) -> None:
        parent = _make_event(node_id="analyze")
        item = {
            "index": 0,
            "item": "input",
            "success": True,
            "duration_ms": 500,
            "llm_call": {"model": "gemini-3-flash", "cost_usd": 0.005},
            "llm_prompt": "Analyze this",
            "llm_response": "The analysis shows...",
        }
        md = _build_batch_item_file(item, parent)
        assert "- Model: gemini-3-flash" in md
        assert "## Prompt" in md
        assert "Analyze this" in md
        assert "## Response" in md
        assert "The analysis shows..." in md

    def test_item_with_llm_tokens(self) -> None:
        """Batch item file shows input/output token breakdown."""
        parent = _make_event(node_id="summarize")
        item = {
            "index": 0,
            "item": "doc",
            "success": True,
            "duration_ms": 300,
            "llm_call": {"model": "gpt-4", "input_tokens": 800, "output_tokens": 150, "cost_usd": 0.01},
        }
        md = _build_batch_item_file(item, parent)
        assert "- Tokens: 800 in / 150 out" in md
        assert "- Paid this run: $0.0100" in md

    def test_cached_item_splits_paid_and_historical_cost(self) -> None:
        parent = _make_event(node_id="batch", node_type="LLMNode")
        item = {
            "index": 0,
            "success": True,
            "cached": True,
            "duration_ms": 0,
            "node_output": {"response": "ok"},
            "llm_call": {
                "model": "anthropic/claude-sonnet-4-5",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cost_usd": 0.03,
                "cache_source": "memo",
                "cache_key": "fixture-cache-key",
                "cache_age_sec": 30.0,
            },
        }

        md = _build_batch_item_file(item, parent)

        assert "- Status: success [cached]" in md
        assert "- Source model: anthropic/claude-sonnet-4-5" in md
        assert "- Source tokens: 1,000 in / 100 out" in md
        assert "- Paid this run: $0.0000" in md
        assert "- Historical source cost: $0.0300" in md
        assert "- Cost: $0.0300" not in md

    def test_item_with_template_resolutions(self) -> None:
        parent = _make_event(node_id="process")
        item = {
            "index": 0,
            "item": "x",
            "success": True,
            "duration_ms": 50,
            "template_resolutions": {
                "prompt": {"template": "Process ${item}", "resolved": "Process x"},
            },
        }
        md = _build_batch_item_file(item, parent)
        assert "## Prompt" in md
        assert "Process x" in md

    def test_item_with_node_output_no_llm(self) -> None:
        parent = _make_event(node_id="transform")
        item = {
            "index": 0,
            "item": "data",
            "success": True,
            "duration_ms": 10,
            "node_output": {"result": "transformed-data"},
        }
        md = _build_batch_item_file(item, parent)
        assert "## Result" in md
        assert "transformed-data" in md

    def test_item_with_shell_output(self) -> None:
        """Shell batch items should show structured stdout/stderr, not raw JSON."""
        parent = _make_event(node_id="greet")
        item = {
            "index": 0,
            "item": {"name": "Alice"},
            "success": True,
            "duration_ms": 5,
            "template_resolutions": {
                "command": {"template": 'echo "Hello, ${user.name}"', "resolved": 'echo "Hello, Alice"'},
            },
            "node_output": {
                "stdout": "Hello, Alice",
                "stderr": "",
                "exit_code": 0,
                "command": 'echo "Hello, Alice"',
            },
        }
        md = _build_batch_item_file(item, parent)
        assert "## Command" in md
        assert 'echo "Hello, Alice"' in md
        assert "## stdout" in md
        assert "Hello, Alice" in md
        # Empty stderr should be omitted
        assert "## stderr" not in md
        # Should NOT show raw JSON dump
        assert "exit_code" not in md

    def test_failed_item(self) -> None:
        parent = _make_event(node_id="fetch")
        item = {
            "index": 1,
            "item": "bad-url",
            "success": False,
            "duration_ms": 200,
            "error": "Connection timeout",
        }
        md = _build_batch_item_file(item, parent)
        assert "- Status: failed" in md
        assert "- Error: Connection timeout" in md


# --- _build_batch_item_summary() ---


class TestBuildBatchItemSummary:
    def test_basic(self) -> None:
        item = {"index": 3, "success": True, "duration_ms": 1500}
        md = _build_batch_item_summary(item)
        assert "# Item 3" in md
        assert "- Time: 1.5s" in md
        assert "- Status: success" in md

    def test_with_pipeline_table(self) -> None:
        """Batch item with sub-workflow events should show a pipeline table."""
        item = {
            "index": 0,
            "success": True,
            "duration_ms": 2000,
            "events": [
                _make_event(node_id="write-lyrics", node_type="LLMNode", duration_ms=800),
                _make_event(node_id="review", node_type="LLMNode", duration_ms=600),
            ],
        }
        md = _build_batch_item_summary(item)
        assert "## Pipeline" in md
        assert "| 1 | write-lyrics | llm | success | 800ms | \u2014 | \u2014 |" in md
        assert "| 2 | review | llm | success | 600ms | \u2014 | \u2014 |" in md


# --- _compute_event_cost() ---


class TestComputeEventCost:
    def test_compute_event_cost_no_llm(self) -> None:
        """Event without llm_call returns None."""
        event = _make_event(node_id="shell-step", node_type="ShellNode")
        result = _compute_event_cost(event)
        assert result is None

    def test_compute_event_cost_leaf_llm(self) -> None:
        """Event with direct llm_call returns its cost_usd."""
        event = _make_event(
            node_type="LLMNode",
            llm_call={"model": "gpt-4", "cost_usd": 0.05},
        )
        result = _compute_event_cost(event)
        assert result == pytest.approx(0.05)

    def test_compute_event_cost_batch_items(self) -> None:
        """Batch items with llm_calls sum their costs."""
        event = _make_event(
            node_type="LLMNode",
            batch_items=[
                {"llm_call": {"cost_usd": 0.01}},
                {"llm_call": {"cost_usd": 0.02}},
            ],
        )
        result = _compute_event_cost(event)
        assert result == pytest.approx(0.03)

    def test_compute_event_cost_sub_workflow(self) -> None:
        """Sub-workflow events with llm_calls sum recursively."""
        event = _make_event(
            node_type="WorkflowExecutor",
            sub_workflow_events=[
                _make_event(
                    node_id="inner-llm",
                    node_type="LLMNode",
                    llm_call={"model": "claude", "cost_usd": 0.04},
                ),
            ],
        )
        result = _compute_event_cost(event)
        assert result == pytest.approx(0.04)

    def test_compute_event_cost_nested(self) -> None:
        """Batch items containing sub-workflow events with llm_calls sum correctly."""
        event = _make_event(
            node_type="WorkflowExecutor",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 100,
                    "events": [
                        _make_event(
                            node_id="inner-llm-1",
                            node_type="LLMNode",
                            llm_call={"model": "gpt-4", "cost_usd": 0.01},
                        ),
                        _make_event(
                            node_id="inner-llm-2",
                            node_type="LLMNode",
                            llm_call={"model": "gpt-4", "cost_usd": 0.02},
                        ),
                    ],
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 100,
                    "events": [
                        _make_event(
                            node_id="inner-llm-3",
                            node_type="LLMNode",
                            llm_call={"model": "gpt-4", "cost_usd": 0.03},
                        ),
                    ],
                },
            ],
        )
        result = _compute_event_cost(event)
        # 0.01 + 0.02 + 0.03 = 0.06
        assert result == pytest.approx(0.06)

    def test_compute_batch_item_cost_recurses_into_events(self) -> None:
        """Cost computed on a batch item dict (not parent event).

        This is the path used by _build_node_summary's items table.
        Batch items store child events under "events", not "sub_workflow_events"
        — so they get a dedicated entry point that knows the shape difference.
        """
        batch_item = {
            "index": 0,
            "success": True,
            "duration_ms": 5000,
            "events": [
                _make_event(
                    node_id="write-lyrics",
                    node_type="LLMNode",
                    llm_call={"model": "gpt-4", "cost_usd": 0.15},
                ),
                _make_event(
                    node_id="review",
                    node_type="LLMNode",
                    llm_call={"model": "gpt-4", "cost_usd": 0.24},
                ),
            ],
        }
        result = _compute_batch_item_cost(batch_item)
        assert result == pytest.approx(0.39)


# --- _format_cost() ---
# (Tested indirectly through table tests, but _build_output_lookup also needs direct use)


# --- Cost in tables ---


class TestCostInTables:
    def test_summary_pipeline_table_has_cost_column(self) -> None:
        """Pipeline table in summary includes Cost column with formatted values."""
        trace = _make_trace(
            nodes=[
                _make_event(
                    node_id="ask-llm",
                    node_type="LLMNode",
                    duration_ms=300,
                    llm_call={"model": "gpt-4", "cost_usd": 0.05},
                ),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "| Cost |" in md
        assert "$0.0500" in md

    def test_node_summary_batch_table_has_cost_column(self) -> None:
        """Batch items table includes Cost column."""
        event = _make_event(
            node_id="batch-llm",
            node_type="LLMNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 50,
                    "llm_call": {"model": "gpt-4", "cost_usd": 0.01},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 60,
                    "llm_call": {"model": "gpt-4", "cost_usd": 0.02},
                },
            ],
        )
        md = _build_node_summary(event)
        assert "| Cost |" in md
        assert "$0.0100" in md

    def test_summary_header_shows_total_cost(self) -> None:
        """Summary header includes total cost from llm_summary."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 3,
                "total_tokens": 5000,
                "total_cost_usd": 0.0847,
                "models_used": ["gpt-4"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "Total cost: $0.0847" in md


# --- Error summary ---


class TestErrorSummary:
    def test_summary_shows_error_section(self) -> None:
        """Trace with failed nodes produces an Errors section."""
        trace = _make_trace(
            nodes=[
                _make_event(
                    node_id="fetch",
                    node_type="HttpNode",
                    success=False,
                    error="Connection refused",
                ),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "## Errors" in md
        assert "Connection refused" in md

    def test_summary_no_error_section_on_success(self) -> None:
        """Trace with all successful nodes has no Errors section."""
        trace = _make_trace(
            nodes=[
                _make_event(
                    node_id="step-1",
                    success=True,
                    node_output={"result": "ok"},
                ),
                _make_event(
                    node_id="step-2",
                    success=True,
                    node_output={"result": "done"},
                ),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "## Errors" not in md

    def test_summary_truncates_long_error(self) -> None:
        """Error messages longer than 200 chars are truncated in summary."""
        long_error = "x" * 300
        trace = _make_trace(
            nodes=[
                _make_event(node_id="fail", success=False, error=long_error),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "## Errors" in md
        assert "..." in md
        # Full 300-char error should NOT appear — it's truncated to 200 + "..."
        assert long_error not in md


# --- _detect_anomalies() ---


class TestDetectAnomalies:
    def test_detect_anomalies_empty_llm_response(self) -> None:
        """LLM node with empty string response triggers warning."""
        event = _make_event(
            node_id="summarize",
            node_type="LLMNode",
            success=True,
            node_output={"response": ""},
        )
        warnings = _detect_anomalies([event])
        assert any("LLM response is empty" in w for w in warnings)

    def test_detect_anomalies_empty_stdout(self) -> None:
        """Shell node with empty stdout and exit_code 0 triggers warning."""
        event = _make_event(
            node_id="list-files",
            node_type="ShellNode",
            success=True,
            node_output={"stdout": "", "exit_code": 0},
        )
        warnings = _detect_anomalies([event])
        assert any("stdout is empty" in w for w in warnings)

    def test_detect_anomalies_none_result(self) -> None:
        """Python node with None result triggers warning."""
        event = _make_event(
            node_id="compute",
            node_type="PythonNode",
            success=True,
            node_output={"result": None},
        )
        warnings = _detect_anomalies([event])
        assert any("result is None" in w for w in warnings)

    def test_detect_anomalies_empty_list(self) -> None:
        """Any node with an empty list in a common output key triggers warning."""
        event = _make_event(
            node_id="fetch-items",
            node_type="HttpNode",
            success=True,
            node_output={"response": []},
        )
        warnings = _detect_anomalies([event])
        assert any("empty list" in w for w in warnings)

    def test_detect_anomalies_skips_failed_nodes(self) -> None:
        """Failed nodes should not generate anomaly warnings (shown in Errors)."""
        event = _make_event(
            node_id="broken",
            node_type="LLMNode",
            success=False,
            node_output={"response": ""},
        )
        warnings = _detect_anomalies([event])
        assert len(warnings) == 0


# --- _suggest_template_fixes() ---


class TestSuggestTemplateFixes:
    def test_suggest_template_fix_wrong_field(self) -> None:
        """Suggests correct field when template references a non-existent key."""
        upstream_event = _make_event(
            node_id="fetch",
            node_type="HttpNode",
            success=True,
            node_output={"result": {"issues": [{"id": 1}], "total_count": 5}},
        )
        failed_event = _make_event(
            node_id="process",
            node_type="LLMNode",
            success=False,
            error="Unresolved variables: ${fetch.result.messages}",
        )
        suggestions = _suggest_template_fixes(failed_event, [upstream_event, failed_event])
        assert len(suggestions) >= 1
        # Should mention the failed key
        assert any("messages" in s for s in suggestions)
        # Should list available keys
        assert any("issues" in s for s in suggestions)
        assert any("total_count" in s for s in suggestions)

    def test_suggest_template_fix_no_upstream(self) -> None:
        """No suggestions when upstream node is not found."""
        failed_event = _make_event(
            node_id="process",
            success=False,
            error="Unresolved variables: ${unknown.data}",
        )
        suggestions = _suggest_template_fixes(failed_event, [failed_event])
        assert suggestions == []

    def test_suggest_template_fix_non_template_error(self) -> None:
        """Non-template errors produce no suggestions."""
        failed_event = _make_event(
            node_id="fetch",
            success=False,
            error="Connection timeout",
        )
        suggestions = _suggest_template_fixes(failed_event, [failed_event])
        assert suggestions == []

    def test_suggest_template_fix_from_template_resolutions(self) -> None:
        """Detects unresolved variables from template_resolutions (template == resolved)."""
        upstream_event = _make_event(
            node_id="api",
            node_type="HttpNode",
            success=True,
            node_output={"result": {"data": [1, 2, 3]}},
        )
        failed_event = _make_event(
            node_id="transform",
            node_type="LLMNode",
            success=False,
            error="Unresolved variables: ${api.result.messages}",
            template_resolutions={
                "prompt": {
                    "template": "Use ${api.result.messages}",
                    "resolved": "Use ${api.result.messages}",
                },
            },
        )
        suggestions = _suggest_template_fixes(failed_event, [upstream_event, failed_event])
        assert len(suggestions) >= 1
        assert any("messages" in s for s in suggestions)
        assert any("data" in s for s in suggestions)


# --- Batch item warnings in _build_node_summary() ---


class TestBatchItemWarnings:
    def test_node_summary_shows_item_warnings(self) -> None:
        """Batch items with empty output trigger warnings in node summary."""
        event = _make_event(
            node_id="batch-process",
            node_type="ShellNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 50,
                    "node_output": {},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 60,
                    "node_output": {"result": "good data"},
                },
            ],
        )
        md = _build_node_summary(event)
        assert "## Warnings" in md
        assert "Item 0" in md

    def test_node_summary_no_warnings_when_clean(self) -> None:
        """Batch items with non-empty output produce no warnings."""
        event = _make_event(
            node_id="batch-process",
            node_type="ShellNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 50,
                    "node_output": {"result": "data-a"},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 60,
                    "node_output": {"result": "data-b"},
                },
            ],
        )
        md = _build_node_summary(event)
        assert "## Warnings" not in md

    def test_llm_batch_empty_response_detected(self) -> None:
        """LLM parent type with item having empty response triggers warning."""
        batch_items = [
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {"response": ""}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"response": "good"}},
        ]
        parent = _make_event(node_id="summarize", node_type="LLMNode")
        warnings = _detect_batch_item_anomalies(batch_items, parent)
        assert len(warnings) == 1
        assert "Item 0" in warnings[0]
        assert "LLM response is empty" in warnings[0]

    def test_skips_failed_batch_items(self) -> None:
        """Failed batch items should not generate anomaly warnings."""
        batch_items = [
            {"index": 0, "success": False, "duration_ms": 50, "node_output": {"response": ""}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"response": "good"}},
        ]
        parent = _make_event(node_id="summarize", node_type="LLMNode")
        warnings = _detect_batch_item_anomalies(batch_items, parent)
        assert len(warnings) == 0


class TestTopLevelBatchWarnings:
    """Tests for batch item anomalies surfacing in the top-level summary."""

    def test_top_level_summary_surfaces_batch_item_warnings(self) -> None:
        """A batch event with items producing empty output shows warnings in _build_summary."""
        batch_event = _make_event(
            node_id="batch-llm",
            node_type="LLMNode",
            success=True,
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50, "node_output": {"response": ""}},
                {"index": 1, "success": True, "duration_ms": 60, "node_output": {"response": "good data"}},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        summary = _build_summary(trace)

        assert "## Warnings" in summary
        assert "batch-llm" in summary
        assert "LLM response is empty" in summary


# --- _build_output_lookup() and _collect_errors() direct tests ---
# These are tested indirectly through _build_summary and _suggest_template_fixes,
# but we exercise them directly here to ensure _build_output_lookup and _collect_errors
# are imported (and to validate their standalone behavior).


class TestBuildOutputLookup:
    def test_builds_lookup_from_events(self) -> None:
        """Builds node_id -> node_output mapping from events."""
        events = [
            _make_event(
                node_id="fetch",
                node_output={"result": {"data": "hello"}},
            ),
            _make_event(
                node_id="transform",
                node_output={"result": "done"},
            ),
        ]
        lookup = _build_output_lookup(events)
        assert "fetch" in lookup
        assert lookup["fetch"] == {"result": {"data": "hello"}}
        assert "transform" in lookup

    def test_includes_sub_workflow_children(self) -> None:
        """Sub-workflow child events are indexed in the lookup."""
        events = [
            _make_event(
                node_id="parent",
                node_output={"result": "parent-data"},
                sub_workflow_events=[
                    _make_event(
                        node_id="child-step",
                        node_output={"result": "child-data"},
                    ),
                ],
            ),
        ]
        lookup = _build_output_lookup(events)
        assert "parent" in lookup
        assert "child-step" in lookup
        assert lookup["child-step"] == {"result": "child-data"}


class TestCollectErrors:
    def test_collects_failed_events(self) -> None:
        """Returns only events with success=False."""
        events = [
            _make_event(node_id="ok", success=True),
            _make_event(node_id="fail-1", success=False, error="Error 1"),
            _make_event(node_id="fail-2", success=False, error="Error 2"),
        ]
        errors = _collect_errors(events)
        assert len(errors) == 2
        assert errors[0]["node_id"] == "fail-1"
        assert errors[1]["node_id"] == "fail-2"

    def test_returns_empty_on_all_success(self) -> None:
        """Returns empty list when all events succeed."""
        events = [
            _make_event(node_id="a", success=True),
            _make_event(node_id="b", success=True),
        ]
        errors = _collect_errors(events)
        assert errors == []

    def test_reads_failed_node_ids_when_present(self) -> None:
        """When failed_node_ids is supplied, use it as the authoritative set.

        Ignores per-event success flag for inclusion decision — the list drives it.
        """
        events = [
            _make_event(node_id="x", success=True),  # flag says ok — not in list → excluded
            _make_event(node_id="y", success=False, error="Y-err"),  # in list → included
        ]
        errors = _collect_errors(events, failed_node_ids=["y"])
        assert len(errors) == 1
        assert errors[0]["node_id"] == "y"

    def test_loop_recovery_omits_recovered_node(self) -> None:
        """Node failed on visit 1, succeeded on visit 2 → not in failed_node_ids → omitted.

        Motivating case for GH #240.
        """
        events = [
            _make_event(node_id="maybe-fail", success=False, error="visit 1"),
            _make_event(node_id="maybe-fail", success=True),
        ]
        errors = _collect_errors(events, failed_node_ids=[])
        assert errors == []

    def test_returns_latest_event_per_failed_node(self) -> None:
        """When a node fails on both visits, only the latest event is returned."""
        events = [
            _make_event(node_id="n", success=False, error="visit 1 error"),
            _make_event(node_id="n", success=False, error="visit 2 error"),
        ]
        errors = _collect_errors(events, failed_node_ids=["n"])
        assert len(errors) == 1
        assert errors[0]["error"] == "visit 2 error"

    def test_fallback_per_node_when_list_absent(self) -> None:
        """No failed_node_ids supplied → derive per-node final state from events.

        Back-compat path for traces generated before the #240 fix.
        """
        events = [
            _make_event(node_id="maybe-fail", success=False, error="visit 1"),
            _make_event(node_id="maybe-fail", success=True),  # recovered
        ]
        errors = _collect_errors(events, failed_node_ids=None)
        assert errors == []

    def test_fallback_still_returns_latest_if_node_truly_failed(self) -> None:
        events = [
            _make_event(node_id="n", success=False, error="visit 1 error"),
            _make_event(node_id="n", success=False, error="visit 2 error"),
        ]
        errors = _collect_errors(events, failed_node_ids=None)
        assert len(errors) == 1
        assert errors[0]["error"] == "visit 2 error"


class TestBuildSummaryLoopRecovery:
    """Summary rendering under loop recovery — GH #240 acceptance criteria."""

    def test_loop_recovery_shows_status_success(self) -> None:
        """Trace with visit-1-fail + visit-2-success renders Status: success."""
        events = [
            _make_event(node_id="setup", success=True),
            _make_event(node_id="maybe-fail", success=False, error="exit 9"),
            _make_event(node_id="retry", success=True),
            _make_event(node_id="maybe-fail", success=True),
        ]
        trace = _make_trace(
            nodes=events,
            final_status="success",
            nodes_executed=4,
            nodes_failed=0,
            failed_node_ids=[],
        )
        md = _build_summary(trace, source_path="test")

        assert "- Status: success" in md
        # Errors section must NOT be present for recovered node
        assert "## Errors" not in md

    def test_loop_recovery_pipeline_table_shows_both_visits(self) -> None:
        """Pipeline table is per-visit — both visits of maybe-fail must appear."""
        events = [
            _make_event(node_id="maybe-fail", node_output={"stdout": "oops"}, success=False, error="exit 9"),
            _make_event(node_id="maybe-fail", node_output={"stdout": "ok"}, success=True),
        ]
        trace = _make_trace(
            nodes=events,
            final_status="success",
            nodes_executed=2,
            nodes_failed=0,
            failed_node_ids=[],
        )
        md = _build_summary(trace, source_path="test")

        # Scope count to the pipeline table — anomaly/warning sections can
        # legitimately mention the node for other reasons.
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        assert pipeline.count("maybe-fail") == 2, f"Pipeline section:\n{pipeline}"
        assert "| failed |" in pipeline  # the failed visit's status column
        assert "| success |" in pipeline  # the succeeded visit's status column
        # Errors section must NOT be present — recovered node is not an error.
        assert "## Errors" not in md

    def test_single_failure_still_renders_errors_section(self) -> None:
        """Non-loop single failure — Errors section must still render."""
        events = [
            _make_event(node_id="bad", node_type="ShellNode", success=False, error="exit 1"),
        ]
        trace = _make_trace(
            nodes=events,
            final_status="failed",
            nodes_executed=1,
            nodes_failed=1,
            failed_node_ids=["bad"],
        )
        md = _build_summary(trace, source_path="test")

        assert "- Status: failed" in md
        assert "## Errors" in md
        assert "**bad**" in md

    def test_legacy_trace_status_recomputed_when_failed_node_ids_absent(self) -> None:
        """Pre-fix traces on disk carry ``final_status: "failed"`` for loop recovery
        (old rule was monotonic over events). The report generator must recompute
        the status from events when ``failed_node_ids`` is absent so Status and
        Errors agree — otherwise users see "Status: failed" with zero entries
        under "## Errors".
        """
        events = [
            _make_event(node_id="maybe-fail", success=False, error="visit 1 exit 9"),
            _make_event(node_id="maybe-fail", success=True),
        ]
        # Legacy trace shape: no failed_node_ids, wrong final_status from old rule
        legacy_trace = {
            "format_version": "2.0.0",
            "execution_id": "legacy",
            "workflow_name": "legacy-loop-recovery",
            "start_time": "t0",
            "end_time": "t1",
            "duration_ms": 1.0,
            "final_status": "failed",  # what old code wrote
            "nodes_executed": 2,
            "nodes_failed": 1,  # what old code counted
            # NOTE: no failed_node_ids key
            "nodes": events,
        }
        md = _build_summary(legacy_trace, source_path="test")

        # Recomputed: last event per node wins → maybe-fail is success
        assert "- Status: success" in md
        # And no Errors section because no node's final state is failed
        assert "## Errors" not in md


class TestFormatCost:
    def test_format_cost_none(self) -> None:
        """None cost returns em dash."""
        assert _format_cost(None) == "\u2014"

    def test_format_cost_value(self) -> None:
        """Numeric cost formatted to 4 decimal places with dollar sign."""
        assert _format_cost(0.05) == "$0.0500"
        assert _format_cost(0.0) == "$0.0000"


# --- _extract_item_label() ---


class TestExtractItemLabel:
    def test_string_item(self) -> None:
        assert _extract_item_label({"item": "emotional-depth"}) == "emotional-depth"

    def test_dict_with_name(self) -> None:
        assert _extract_item_label({"item": {"name": "Chorus A", "weight": 3}}) == "Chorus A"

    def test_dict_with_title(self) -> None:
        assert _extract_item_label({"item": {"title": "My Song", "id": 42}}) == "My Song"

    def test_dict_with_label(self) -> None:
        assert _extract_item_label({"item": {"label": "verse-1", "data": "..."}}) == "verse-1"

    def test_dict_priority_name_over_title(self) -> None:
        """name takes priority over title."""
        assert _extract_item_label({"item": {"name": "A", "title": "B"}}) == "A"

    def test_dict_fallback_first_short_string(self) -> None:
        """Falls back to first short string value when no priority key."""
        assert _extract_item_label({"item": {"concept": "Space Travel", "id": 42}}) == "Space Travel"

    def test_dict_skips_urls(self) -> None:
        """URLs are skipped in fallback search."""
        result = _extract_item_label({"item": {"url": "https://example.com", "id": 42}})
        assert result is None

    def test_dict_skips_paths(self) -> None:
        """Absolute paths are skipped in fallback search."""
        result = _extract_item_label({"item": {"path": "/usr/local/bin", "id": 42}})
        assert result is None

    def test_dict_skips_long_strings(self) -> None:
        """Strings >= 80 chars are skipped in fallback search."""
        result = _extract_item_label({"item": {"description": "x" * 80, "id": 42}})
        assert result is None

    def test_no_item_key(self) -> None:
        assert _extract_item_label({"index": 0, "success": True}) is None

    def test_int_item(self) -> None:
        assert _extract_item_label({"item": 42}) is None

    def test_list_item(self) -> None:
        assert _extract_item_label({"item": [1, 2, 3]}) is None

    def test_empty_string(self) -> None:
        assert _extract_item_label({"item": "   "}) is None


# --- _slugify_label() ---


class TestSlugifyLabel:
    def test_basic(self) -> None:
        assert _slugify_label("Emotional Depth") == "emotional-depth"

    def test_special_chars(self) -> None:
        assert _slugify_label("Song #1 (remix)") == "song-1-remix"

    def test_truncation(self) -> None:
        slug = _slugify_label("a" * 50, max_len=40)
        assert len(slug) <= 40

    def test_truncation_at_word_boundary(self) -> None:
        slug = _slugify_label("the-quick-brown-fox-jumps-over-the-lazy-dog-again", max_len=40)
        assert len(slug) <= 40
        assert not slug.endswith("-")

    def test_empty_after_slug(self) -> None:
        assert _slugify_label("!!!") == "unnamed"

    def test_preserves_hyphens_and_numbers(self) -> None:
        assert _slugify_label("item-42-v2") == "item-42-v2"


# --- _item_filename() ---


class TestItemFilename:
    def test_with_string_label(self) -> None:
        assert _item_filename({"index": 0, "item": "chorus"}) == "item-0-chorus.md"

    def test_with_dict_label(self) -> None:
        assert _item_filename({"index": 3, "item": {"name": "My Song!"}}) == "item-3-my-song.md"

    def test_no_label(self) -> None:
        assert _item_filename({"index": 5}) == "item-5.md"

    def test_directory_suffix(self) -> None:
        assert _item_filename({"index": 0, "item": "verse"}, suffix="") == "item-0-verse"


# --- _compute_outlier_threshold() ---


class TestComputeOutlierThreshold:
    def test_too_few_values(self) -> None:
        """Returns None with fewer than 4 values (IQR meaningless)."""
        assert _compute_outlier_threshold([1, 2, 3]) is None

    def test_uniform_distribution(self) -> None:
        """Uniform values have IQR=0, threshold = Q3."""
        threshold = _compute_outlier_threshold([100, 100, 100, 100])
        assert threshold is not None
        assert threshold == 100.0

    def test_detects_outlier(self) -> None:
        """A clearly extreme value exceeds the threshold."""
        # [50, 60, 70, 80] → Q1=55, Q3=75, IQR=20 → threshold=75+30=105
        threshold = _compute_outlier_threshold([50, 60, 70, 80])
        assert threshold is not None
        assert threshold > 50  # normal values below
        assert threshold < 200  # extreme value above

    def test_real_world_batch_timing(self) -> None:
        """Simulates real batch: most items ~100ms, one slow at 800ms."""
        durations = [95, 100, 105, 110, 98, 102, 100, 800]
        threshold = _compute_outlier_threshold(durations)
        assert threshold is not None
        assert threshold < 800  # 800ms should be above the threshold
        assert threshold > 110  # normal values should be below


# --- _find_notable_items() ---


class TestFindNotableItems:
    def test_failed_items_always_notable(self) -> None:
        items = [
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {"stdout": "ok", "exit_code": 0}},
            {"index": 1, "success": False, "duration_ms": 30},
        ]
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 1

    def test_anomaly_items_notable(self) -> None:
        """Items with empty output are notable."""
        items = [
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"stdout": "data", "exit_code": 0}},
        ]
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 0

    def test_all_ok_returns_empty(self) -> None:
        """All successful items with normal output → nothing notable."""
        items = [
            {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
            for i in range(5)
        ]
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 0

    def test_duration_outlier_notable(self) -> None:
        """An item with extreme duration is notable via IQR detection."""
        items = [
            {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
            for i in range(7)
        ]
        # Add one slow item
        items.append({
            "index": 7,
            "success": True,
            "duration_ms": 5000,
            "node_output": {"stdout": "ok", "exit_code": 0},
        })
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 7

    def test_cost_outlier_notable(self) -> None:
        """An item with extreme cost is notable via IQR detection."""
        items = [
            {
                "index": i,
                "success": True,
                "duration_ms": 100,
                "node_output": {"response": "ok"},
                "llm_call": {"model": "gpt-4", "cost_usd": 0.01},
            }
            for i in range(7)
        ]
        # Add one expensive item (10x the rest, well above 4x median)
        items.append({
            "index": 7,
            "success": True,
            "duration_ms": 100,
            "node_output": {"response": "ok"},
            "llm_call": {"model": "gpt-4", "cost_usd": 0.10},
        })
        notable = _find_notable_items(items, _make_event(node_type="LLMNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 7


# --- Compact batch summary ---


class TestCompactBatchSummary:
    def test_all_ok_no_table_shows_stats(self) -> None:
        """When all items succeed normally, no table but shows median time."""
        event = _make_event(
            node_id="batch",
            node_type="ShellNode",
            batch_items=[
                {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
                for i in range(10)
            ],
        )
        md = _build_node_summary(event)
        assert "10/10 succeeded" in md
        assert "## Items" not in md
        assert "Median time: 100ms" in md

    def test_all_ok_shows_total_cost(self) -> None:
        """Compact batch with LLM costs shows total cost in stats."""
        event = _make_event(
            node_id="batch",
            node_type="LLMNode",
            batch_items=[
                {
                    "index": i,
                    "success": True,
                    "duration_ms": 5000,
                    "node_output": {"response": "ok"},
                    "llm_call": {"model": "gpt-4", "cost_usd": 0.01},
                }
                for i in range(10)
            ],
        )
        md = _build_node_summary(event)
        assert "## Items" not in md
        assert "Median time: 5.0s" in md
        assert "Total cost: $0.1000" in md

    def test_one_failure_shows_only_failure(self) -> None:
        """Only the failed item appears in the table."""
        items = [
            {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
            for i in range(5)
        ]
        items[2] = {"index": 2, "success": False, "duration_ms": 50, "error": "exit code 1"}
        event = _make_event(node_id="batch", node_type="ShellNode", batch_items=items)
        md = _build_node_summary(event)
        assert "## Items" in md
        # Items table now uses the same lowercase vocabulary as the pipeline
        # table (success/failed/cached) so readers see one vocabulary across
        # `## Pipeline` and `## Items` in the same report.
        assert "| failed |" in md
        assert "| 2 |" in md
        assert "... and 4 more succeeded" in md
        # Other items not in table
        assert "| 0 |" not in md

    def test_labels_in_table(self) -> None:
        """When items have labels, the Label column appears."""
        event = _make_event(
            node_id="score",
            node_type="LLMNode",
            batch_items=[
                {"index": 0, "item": "depth", "success": False, "duration_ms": 50},
                {"index": 1, "item": "clarity", "success": True, "duration_ms": 60, "node_output": {"response": "ok"}},
            ],
        )
        md = _build_node_summary(event)
        assert "| Label |" in md
        assert "depth" in md

    def test_labeled_filenames_integration(self, tmp_path: Path) -> None:
        """generate_report creates labeled filenames for batch items."""
        batch_event = _make_event(
            node_id="analyze",
            batch_items=[
                {"index": 0, "item": {"name": "Alpha"}, "success": True, "duration_ms": 50},
                {"index": 1, "item": {"name": "Beta"}, "success": True, "duration_ms": 60},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))
        assert report_dir is not None
        assert (report_dir / "01-analyze" / "item-0-alpha.md").exists()
        assert (report_dir / "01-analyze" / "item-1-beta.md").exists()


# --- LLM params in node metadata (Issue 4) ---


class TestLLMParamsInMetadata:
    def test_temperature_shown(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"temperature": 0.4, "prompt": "Hello"},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- temperature: 0.4" in md

    def test_reasoning_effort_shown(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"reasoning_effort": "high"},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- reasoning_effort: high" in md

    def test_system_prompt_truncated(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"system": "x" * 100},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- system: " in md
        assert "..." in md
        assert "x" * 100 not in md

    def test_output_schema_shown(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"output_schema": {"type": "object"}},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- output: structured (schema)" in md

    def test_no_params_no_extra_lines(self) -> None:
        """Shell node with no LLM params shows nothing extra."""
        event = _make_event(node_type="ShellNode", node_params={"command": "echo hi"})
        md = _build_node_file(event)
        assert "temperature" not in md
        assert "reasoning" not in md


# --- Runtime warnings in summary (Issue 5) ---


class TestRuntimeWarningsInSummary:
    def test_runtime_warnings_rendered(self) -> None:
        trace = _make_trace(
            warnings=[
                {
                    "node_id": "score-choruses",
                    "type": "api_warning",
                    "message": "Batch 'score-choruses': 1 error(s) out of 34 items",
                },
            ]
        )
        md = _build_summary(trace)
        assert "## Runtime Warnings" in md
        assert "score-choruses" in md
        assert "1 error(s) out of 34 items" in md

    def test_no_runtime_warnings_no_section(self) -> None:
        trace = _make_trace()
        md = _build_summary(trace)
        assert "## Runtime Warnings" not in md

    def test_multiple_runtime_warnings(self) -> None:
        trace = _make_trace(
            warnings=[
                {"node_id": "node-a", "type": "api_warning", "message": "API error: not found"},
                {"node_id": "node-b", "type": "api_warning", "message": "Batch 'node-b': 2 error(s)"},
            ]
        )
        md = _build_summary(trace)
        assert "node-a" in md
        assert "node-b" in md

    def test_runtime_warning_with_id_and_suggestions_rendered(self) -> None:
        trace = _make_trace(
            warnings=[
                {
                    "node_id": "draft",
                    "id": "cache.below-min-observed",
                    "message": "draft: declared cache did not fire",
                    "suggestions": ["Increase cache content above 1024 tokens."],
                },
            ]
        )
        md = _build_summary(trace)
        assert "[cache.below-min-observed] **draft**: draft: declared cache did not fire" in md
        assert "  - Increase cache content above 1024 tokens." in md


# --- Batch rendering in the pipeline table (per-item explosion) ---


class TestPipelineTableBatchExplosion:
    """The pipeline table renders one row per batch item (no aggregated parent row).

    Replaces the previous TestItemCountsInStatus which encoded the older
    ``ok (M/N)`` parent-row semantic.
    """

    def test_batch_items_exploded_into_rows(self) -> None:
        batch_event = _make_event(
            node_id="process",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50},
                {"index": 1, "success": True, "duration_ms": 60},
                {"index": 2, "success": False, "duration_ms": 30},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        assert "process[0]" in md
        assert "process[1]" in md
        assert "process[2]" in md
        # No aggregated parent row with item counts.
        assert "ok (2/3)" not in md
        assert "| process |" not in md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]

    def test_batch_item_row_has_per_item_status(self) -> None:
        batch_event = _make_event(
            node_id="greet",
            node_type="ShellNode",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50},
                {"index": 1, "success": False, "duration_ms": 60},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        # Pin full row shape — a column-order swap or status-cell swap
        # would fail this assertion. Setting node_type=ShellNode makes the
        # type-tag column deterministic (`shell` rather than the fallback).
        assert "| greet[0] | shell | success |" in pipeline
        assert "| greet[1] | shell | failed |" in pipeline

    def test_non_batch_row_uses_lowercase_status(self) -> None:
        event = _make_event(node_id="fetch", node_type="ShellNode")
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        assert "| success |" in md

    def test_pipeline_table_helper_explodes_batch_items(self) -> None:
        """_format_pipeline_table emits one row per item, not an aggregate row."""
        from pflow.core.trace_report import _format_pipeline_table

        events = [
            _make_event(
                node_id="batch-step",
                batch_items=[
                    {"index": 0, "success": True, "duration_ms": 50},
                    {"index": 1, "success": False, "duration_ms": 60},
                ],
            ),
        ]
        lines: list[str] = []
        _format_pipeline_table(events, lines)
        table = "\n".join(lines)
        assert "batch-step[0]" in table
        assert "batch-step[1]" in table
        assert "ok (1/2)" not in table


class TestWarmupItemReportFiltering:
    """Synthetic batch warmup items (llm_call.is_warmup=True) MUST be filtered
    from user-facing per-batch counts in --report output. The warmup file itself
    is still generated (intentional — useful for cost inspection), but counts
    and anomaly detection treat the batch as having N real items, not N+1.

    Convention documented in src/pflow/runtime/engine/CLAUDE.md → 'Synthetic
    Cache Warmup Item' (8 filtering sites; 3 of them live in trace_report.py).
    """

    def _warmup(self) -> dict[str, Any]:
        return {
            "index": -1,
            "item": "__cache_warmup__",
            "success": True,
            "duration_ms": 2700.0,
            "node_output": {},
            "llm_call": {"model": "anthropic/claude-sonnet-4-5", "cost_usd": 0.015, "is_warmup": True},
        }

    def test_pipeline_table_excludes_warmup_rows(self) -> None:
        """Pipeline table explodes batch items but skips the synthetic warmup."""
        batch_event = _make_event(
            node_id="score-batch",
            batch_items=[
                self._warmup(),
                {"index": 0, "success": True, "duration_ms": 50},
                {"index": 1, "success": True, "duration_ms": 60},
                {"index": 2, "success": True, "duration_ms": 70},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        # Real items show as rows; warmup (index -1) does not.
        assert "score-batch[0]" in pipeline
        assert "score-batch[1]" in pipeline
        assert "score-batch[2]" in pipeline
        assert "score-batch[-1]" not in pipeline
        assert "__cache_warmup__" not in pipeline

    def test_anomaly_detection_skips_warmup(self) -> None:
        """_detect_batch_item_anomalies: empty node_output on warmup is expected
        (warmup has no node output by design); MUST NOT produce a spurious
        'item -1 produced no output' anomaly."""
        batch_items = [
            self._warmup(),  # has empty node_output by design
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {"x": 1}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"x": 2}},
        ]
        parent_event = _make_event(node_id="score-batch", batch_items=batch_items)
        anomalies = _detect_batch_item_anomalies(batch_items, parent_event)
        # The warmup's empty node_output should NOT be reported as an anomaly.
        assert not any("-1" in str(a) or "__cache_warmup__" in str(a) for a in anomalies)

    def test_node_summary_excludes_warmup_from_items_count(self) -> None:
        """_build_node_summary: 'Items: N (N/N succeeded)' counts only real items."""
        event = _make_event(
            node_id="score-batch",
            node_type="LLMNode",
            batch_items=[
                self._warmup(),
                {"index": 0, "success": True, "duration_ms": 50, "node_output": {}},
                {"index": 1, "success": True, "duration_ms": 60, "node_output": {}},
                {"index": 2, "success": True, "duration_ms": 70, "node_output": {}},
            ],
        )
        md = _build_node_summary(event)
        assert "Items: 3 (3/3 succeeded)" in md
        assert "Items: 4" not in md


# --- New summary surfaces: tokens column, halt-line, batch labels, type tag ---


class TestSummaryTokensColumn:
    def test_llm_row_renders_tokens_in_out(self) -> None:
        event = _make_event(
            node_id="ask",
            node_type="LLMNode",
            duration_ms=200,
            llm_call={"model": "gpt-4", "input_tokens": 49, "output_tokens": 1548, "cost_usd": 0.023},
        )
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        assert "| Tokens |" in pipeline
        assert "49 in / 1,548 out" in pipeline

    def test_non_llm_row_renders_em_dash_for_tokens_and_cost(self) -> None:
        event = _make_event(node_id="fetch", node_type="ShellNode", duration_ms=200)
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        # Both Tokens and Cost columns are em-dash for non-LLM rows.
        assert "| fetch | shell | success | 200ms | — | — |" in pipeline


class TestSummaryHaltLine:
    def test_halt_line_present_on_failed_run(self) -> None:
        trace = _make_trace(
            final_status="failed",
            nodes=[
                _make_event(node_id="upstream", success=True),
                _make_event(node_id="synthesize", success=False, error="timed out after 120s"),
            ],
            failed_node_ids=["synthesize"],
            nodes_failed=1,
        )
        md = _build_summary(trace)
        header = md.split("## Pipeline", 1)[0]
        assert "- Halted at: synthesize" in header
        # Pin position: halt-line must sit BETWEEN Status and Duration, so a
        # reader scanning the header lands on it before per-run metrics.
        status_idx = md.find("- Status:")
        halt_idx = md.find("- Halted at:")
        duration_idx = md.find("- Duration:")
        assert 0 <= status_idx < halt_idx < duration_idx, (
            f"Halt-line must appear between Status and Duration; got "
            f"status={status_idx} halt={halt_idx} duration={duration_idx}"
        )

    def test_halt_line_absent_on_success_run(self) -> None:
        trace = _make_trace(
            final_status="success",
            nodes=[_make_event(node_id="only-node", success=True)],
        )
        md = _build_summary(trace)
        assert "- Halted at:" not in md

    def test_halt_line_names_chronologically_last_failed_event(self) -> None:
        """When several events failed, halt-line picks the last-recorded one
        (chronological 'this is where the run stopped'), not the alphabetically
        first failed_node_id."""
        trace = _make_trace(
            final_status="failed",
            nodes=[
                _make_event(node_id="zebra", success=False, error="early failure"),
                _make_event(node_id="alpha", success=False, error="late failure"),
            ],
            failed_node_ids=["alpha", "zebra"],  # sorted alphabetically by the producer
            nodes_failed=2,
        )
        md = _build_summary(trace)
        assert "- Halted at: alpha" in md  # last-recorded, not alphabetically first


class TestPipelineTableBatchLabel:
    def test_batch_label_uses_model_tail(self) -> None:
        batch_event = _make_event(
            node_id="write-drafts",
            node_type="LLMNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "anthropic/claude-sonnet-4-5", "input_tokens": 49, "output_tokens": 100},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "openai/gpt-5.4", "input_tokens": 49, "output_tokens": 100},
                },
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        assert "write-drafts[0] (claude-sonnet-4-5)" in md
        assert "write-drafts[1] (gpt-5.4)" in md

    def test_batch_label_falls_back_to_item_label_when_no_llm(self) -> None:
        batch_event = _make_event(
            node_id="fetch",
            node_type="ShellNode",
            batch_items=[
                {"index": 0, "item": "doc-a", "success": True, "duration_ms": 50},
                {"index": 1, "item": "doc-b", "success": True, "duration_ms": 50},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        assert "fetch[0] (doc-a)" in md
        assert "fetch[1] (doc-b)" in md

    def test_batch_label_handles_non_dict_llm_call_defensively(self) -> None:
        """A synthetic/adversarial trace where ``llm_call`` is not a dict
        must not raise AttributeError. Matches the same guard already in
        ``_row_tokens``.
        """
        batch_event = _make_event(
            node_id="fetch",
            node_type="ShellNode",
            batch_items=[
                # Non-dict llm_call values — defensively skipped.
                {"index": 0, "item": "doc-a", "success": True, "duration_ms": 50, "llm_call": "not-a-dict"},
                {"index": 1, "item": "doc-b", "success": True, "duration_ms": 50, "llm_call": 42},
                {"index": 2, "item": "doc-c", "success": True, "duration_ms": 50, "llm_call": None},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        # Each row falls back to the item-label path; no AttributeError.
        assert "fetch[0] (doc-a)" in md
        assert "fetch[1] (doc-b)" in md
        assert "fetch[2] (doc-c)" in md


class TestPipelineTableSubWorkflow:
    """A ``WorkflowExecutor`` event stays as a SINGLE row in the parent table.

    The renderer guards against exploding sub-workflow children into parent
    rows via the ``not event.get("sub_workflow_events")`` branch in
    ``_format_pipeline_table``. Dropping that guard would silently surface
    every nested node in the parent's pipeline table.
    """

    def test_sub_workflow_event_stays_as_single_row(self) -> None:
        event = _make_event(
            node_id="run-child",
            node_type="WorkflowExecutor",
            duration_ms=500,
            sub_workflow_events=[
                _make_event(node_id="child-shell", node_type="ShellNode", duration_ms=100),
                _make_event(node_id="child-llm", node_type="LLMNode", duration_ms=200),
            ],
        )
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        # Single parent row with the `workflow` type tag and em-dash Tokens
        # (no aggregator exists for sub-workflow tokens at parent level).
        assert "| 1 | run-child | workflow | success |" in pipeline
        assert "| — |" in pipeline
        # Children must NOT appear as rows in the parent table; they live in
        # the nested container summary.md.
        assert "child-shell" not in pipeline
        assert "child-llm" not in pipeline


class TestPipelineTableTypeTag:
    def test_short_tag_replaces_class_name(self) -> None:
        trace = _make_trace(
            nodes=[
                _make_event(node_id="a", node_type="ShellNode"),
                _make_event(node_id="b", node_type="LLMNode"),
                _make_event(node_id="c", node_type="PythonCodeNode"),
                _make_event(node_id="d", node_type="HttpNode"),
            ],
        )
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        assert "| shell |" in pipeline
        assert "| llm |" in pipeline
        assert "| code |" in pipeline
        assert "| http |" in pipeline
        # Raw class names should NOT appear.
        assert "ShellNode" not in pipeline
        assert "LLMNode" not in pipeline


class TestPipelineTableCachedStatus:
    def test_cached_event_status_is_cached(self) -> None:
        event = _make_event(
            node_id="ask",
            node_type="LLMNode",
            duration_ms=10,
            cached=True,
            llm_call={"model": "gpt-4", "input_tokens": 49, "output_tokens": 100, "cost_usd": 0.02},
        )
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        assert "| cached |" in pipeline
        # Tokens still render from the source call on a cached event.
        assert "49 in / 100 out" in pipeline
        # Cost column shows paid-this-run ($0.0000), NOT the historical source
        # cost ($0.02). A regression that leaked llm_call.cost_usd into the
        # cell would surface as $0.0200 here.
        assert "$0.0000" in pipeline
        assert "$0.0200" not in pipeline

    def test_cached_event_with_none_token_fields_does_not_crash(self) -> None:
        """Legacy cached entries may have ``input_tokens: None`` instead of an
        integer. The renderer must not raise ``TypeError`` from ``f"{None:,}"``.
        """
        event = _make_event(
            node_id="legacy-cached",
            node_type="LLMNode",
            duration_ms=10,
            cached=True,
            llm_call={"model": "gpt-4", "input_tokens": None, "output_tokens": None},
        )
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        # Falls back to 0 in / 0 out — the row still renders.
        assert "0 in / 0 out" in pipeline

    def test_cached_and_failed_event_renders_failed_not_cached(self) -> None:
        """``_row_status`` must prefer ``failed`` over ``cached`` when both
        flags are set. The rare (cached, !success) shape should not silently
        mask the failure signal as it did in a prior revision.
        """
        event = _make_event(
            node_id="impossible",
            node_type="LLMNode",
            duration_ms=10,
            cached=True,
            success=False,
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 20},
        )
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        pipeline = md.split("## Pipeline", 1)[1].split("\n## ", 1)[0]
        assert "| failed |" in pipeline
        assert "| cached |" not in pipeline


class TestPipelineTableWarmupOnlyEdgeCase:
    """Warmup-only batches must not emit a header-only `## Pipeline` section.

    The row buffer in `_format_pipeline_table` defers the header until at
    least one row survives the `is_warmup` filter. A regression that hoists
    the header back to the top of the function would surface here.
    """

    def test_warmup_only_batch_omits_pipeline_section_entirely(self) -> None:
        warmup_only = _make_event(
            node_id="prewarm-only",
            node_type="LLMNode",
            duration_ms=100,
            batch_items=[
                {
                    "index": -1,
                    "item": "__cache_warmup__",
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "claude-sonnet-4-5", "is_warmup": True},
                }
            ],
        )
        trace = _make_trace(nodes=[warmup_only])
        md = _build_summary(trace)
        # No header, no separator, no table at all.
        assert "## Pipeline" not in md
        assert "| # | Node | Type | Status | Time | Tokens | Cost |" not in md
