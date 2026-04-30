"""F3.1 — analyze-cache CLI tests.

Locks the exit-code contract from the F3.1 plan section: success → 0 (regardless
of warning severity); validation/parse errors → non-zero; trace not found →
non-zero; conflicting flags → non-zero; internal analyzer crash → non-zero
(NEVER silent empty JSON).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.main import cli


def _write_workflow(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "wf.pflow.md"
    path.write_text(content, encoding="utf-8")
    return path


_MINIMAL_VALID_WORKFLOW = """\
# Test

A minimal valid workflow.

## Steps

### echo

Echo a greeting.

- type: shell

```command
echo hello
```
"""


_LLM_WORKFLOW = """\
# LLM Test

A workflow with an LLM node and a Cache block.

## Inputs

### topic

The topic to analyze.

- type: string

## Cache

```cache
The topic of the analysis:

${topic}
```

## Steps

### review

Summarize the topic.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [topic]

```prompt
Summarize ${topic}.
```
"""


# ---------------------------------------------------------------------------
# Successful invocations — exit 0 regardless of finding severity
# ---------------------------------------------------------------------------


def test_analyze_cache_text_format_default(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path)])
    assert result.exit_code == 0
    assert "Cache Analysis" in result.output


def test_analyze_cache_json_format(tmp_path: Path) -> None:
    """JSON output shape locked. Format-version asserts use the constant +
    consumer rule so a future additive minor bump (1.0 → 1.1) doesn't
    spuriously fail the test."""
    from pflow.core.cache_analysis import JSON_FORMAT_VERSION, JSON_FORMAT_VERSION_MAJOR

    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--format=json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["format_version"] == JSON_FORMAT_VERSION
    assert payload["format_version"].startswith(JSON_FORMAT_VERSION_MAJOR + ".")
    assert "summary" in payload
    assert "warnings" in payload
    assert "cross_workflow" in payload
    # Empty-array contract.
    assert payload["cross_workflow"]["rename_detections"] == []


def test_analyze_cache_with_workflow_having_warnings_still_exits_zero(
    tmp_path: Path,
) -> None:
    """Per DD#36: analytical findings are advisory; ERROR severity findings
    in `warnings[]` do NOT change exit code. Success → 0.

    The `_LLM_WORKFLOW` declares `prompt_cache: [topic]` referencing a small
    string input — total cache content well below Anthropic's 1024-token
    minimum, so `cache.below-min-tokens` MUST fire. If the warning stops
    firing entirely (catalog regression / detection bypass), this test
    surfaces the disappearance instead of silently passing on an empty list.
    """
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--format=json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert any(w["id"] == "cache.below-min-tokens" for w in payload["warnings"]), (
        f"expected cache.below-min-tokens to fire on _LLM_WORKFLOW; "
        f"got warnings={[w['id'] for w in payload['warnings']]}"
    )


# ---------------------------------------------------------------------------
# Failure paths — non-zero exit codes
# ---------------------------------------------------------------------------


def test_workflow_path_not_found(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(tmp_path / "missing.pflow.md")])
    assert result.exit_code != 0


def test_explicit_from_trace_missing_path_exits_nonzero(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "analyze-cache",
            str(workflow_path),
            "--from-trace",
            str(tmp_path / "missing-trace.json"),
        ],
    )
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower() or "not found" in result.output.lower()


def test_explicit_from_trace_invalid_json_exits_nonzero(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)
    bad_trace = tmp_path / "bad.json"
    bad_trace.write_text("{not valid json", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--from-trace", str(bad_trace)])
    assert result.exit_code != 0


def test_conflicting_flags_exits_nonzero(tmp_path: Path) -> None:
    """--from-trace and --no-trace-autoload are mutually exclusive."""
    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)
    trace = tmp_path / "trace.json"
    trace.write_text(
        json.dumps({"format_version": "2.1.0", "workflow_path": str(workflow_path)}),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "analyze-cache",
            str(workflow_path),
            "--from-trace",
            str(trace),
            "--no-trace-autoload",
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or "mutually exclusive" in result.stderr.lower()


def test_internal_analyzer_crash_exits_nonzero_no_silent_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Internal analyzer failures MUST exit non-zero AND not emit JSON to stdout
    (silent-failures rule per F3.1)."""
    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic analyzer crash")

    monkeypatch.setattr("pflow.cli.commands.analyze_cache.analyze", _boom, raising=False)
    # Patch through the module path that the CLI's lazy import binds.
    import pflow.core.cache_analysis

    monkeypatch.setattr(pflow.core.cache_analysis, "analyze", _boom)

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--format=json"])
    assert result.exit_code != 0
    # Output must NEVER contain ``format_version`` on the crash path —
    # that's the silent-failures attractor: emitting empty-but-valid analysis
    # JSON when the analyzer actually crashed. Asserting absence of the
    # signature key directly is tighter than the prior ``json.loads`` dance
    # (which would pass on an empty stdout).
    assert "format_version" not in result.output, "internal crash silently emitted analysis JSON"


# ---------------------------------------------------------------------------
# --all-rows flag
# ---------------------------------------------------------------------------


def test_all_rows_flag_passed_through(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--all-rows"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Inputs are optional (DD#35)
# ---------------------------------------------------------------------------


def test_inputs_are_optional(tmp_path: Path) -> None:
    """Workflow declares input 'topic' but analyze-cache runs without supplying it."""
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path)])
    assert result.exit_code == 0


def test_explicit_inputs_accepted(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "topic=climate change"])
    assert result.exit_code == 0
