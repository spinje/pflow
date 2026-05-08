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


def _json_payload(output: str) -> dict:
    """Parse CLI JSON even if a dependency logs before Click captures stdout."""
    start = output.find("{")
    assert start >= 0, output
    return json.loads(output[start:])


_MINIMAL_VALID_WORKFLOW = """\
# Test

A minimal valid workflow.

## Steps

### echo

Echo a greeting.

- type: shell
- cache: false

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


_ORDER_MISMATCH_WORKFLOW = """\
# Order Mismatch

A workflow with an invalid prompt_cache order.

## Inputs

### a

First cached value.

- type: string

### b

Second cached value.

- type: string

## Cache

```cache
A:
${a}

B:
${b}
```

## Steps

### test-call

Summarize both values.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [b, a]

```prompt
Summarize the cached values.
```
"""


_ORDER_MISMATCH_WITH_OVERLAP_WORKFLOW = """\
# Order Mismatch With Overlap

A workflow with invalid prompt_cache order and duplicated cached prompt body refs.

## Inputs

### a

First cached value.

- type: string

### b

Second cached value.

- type: string

## Cache

```cache
A:
${a}

B:
${b}
```

## Steps

### test-call

Summarize both values.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [b, a]

```prompt
Summarize ${a} and ${b}.
```
"""


_MIXED_MODEL_CACHE_WORKFLOW = """\
# Mixed Models

A workflow with two exact models sharing one cached chunk.

## Inputs

### context

Stable context.

- type: string

## Cache

```cache
Context:

${context}
```

## Steps

### draft

Draft from context.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]

```prompt
Draft from the cached context.
```

### review

Review from context.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [context]

```prompt
Review from the cached context.
```
"""


_SINGLE_CALL_CACHE_WORKFLOW = """\
# Single Call Cache

A workflow with one cached LLM call.

## Inputs

### context

Stable context.

- type: string

## Cache

```cache
Context:

${context}
```

## Steps

### draft

Draft from context.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]

```prompt
Draft from the cached context.
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
    """JSON output shape locked."""
    from pflow.core.cache_analysis import JSON_FORMAT_VERSION

    workflow_path = _write_workflow(tmp_path, _MINIMAL_VALID_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--format=json"])
    assert result.exit_code == 0
    payload = _json_payload(result.output)
    # Version-gated contract: ``format_version`` is the first key + matches
    # the package constant. JSON consumers dispatch on
    # ``startswith(MAJOR + ".")`` per ``cache_analysis/__init__.py``.
    assert payload.get("format_version") == JSON_FORMAT_VERSION
    assert "summary" in payload
    assert payload["blocking_errors"] == []
    assert payload["recommended_actions"] == []
    assert "warnings" in payload
    assert "cross_workflow" in payload
    # Empty-array contract.
    assert payload["cross_workflow"]["rename_detections"] == []


def test_analyze_cache_json_error_envelope_on_workflow_not_found(tmp_path: Path) -> None:
    """When ``--format=json`` is set and workflow resolution fails, stdout MUST
    carry a structured error envelope (parseable JSON), not a free-form text
    line. Stderr keeps the human-readable message in parallel.

    Mutation contract: removing the ``json_mode`` branch in ``_emit_error``
    makes this test fail because ``json.loads(result.stdout)`` would parse-fail.
    """
    import json as _json

    runner = CliRunner()
    missing_workflow = tmp_path / "does-not-exist.pflow.md"
    result = runner.invoke(cli, ["analyze-cache", str(missing_workflow), "--format=json"], catch_exceptions=False)
    assert result.exit_code != 0
    # Stdout must be parseable JSON — the agent's primary contract.
    envelope = _json.loads(result.stdout or "{}")
    assert envelope.get("error", {}).get("id") == "analyze-cache.workflow-resolution-failed", envelope
    assert "message" in envelope["error"]
    # Format version included in error envelope so consumers can dispatch
    # the same way as on success.
    assert envelope.get("format_version")


def test_analyze_cache_json_splits_blocking_errors_from_recommended_actions(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _ORDER_MISMATCH_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--format=json"])
    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)

    blocking_ids = [item["warning_id"] for item in payload["blocking_errors"]]
    recommended_ids = [item["warning_id"] for item in payload["recommended_actions"]]
    assert "cache.order-mismatch" in blocking_ids
    assert "cache.order-mismatch" not in recommended_ids
    assert payload["blocking_errors"][0]["rank"] == 1


def test_analyze_cache_json_scopes_validator_findings_to_workflow_path(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _ORDER_MISMATCH_WITH_OVERLAP_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze-cache", str(workflow_path), "--format=json"])
    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)

    scoped_errors = {
        item["warning_id"]: item["scope_workflow"]
        for item in payload["blocking_errors"]
        if item["warning_id"] in {"cache.order-mismatch", "cache.prompt-body-duplicates-cache"}
    }
    assert scoped_errors == {
        "cache.order-mismatch": str(workflow_path),
        "cache.prompt-body-duplicates-cache": str(workflow_path),
    }


def test_analyze_cache_with_workflow_having_warnings_still_exits_zero(
    tmp_path: Path,
) -> None:
    """Warnings (non-blocking) should not affect exit code.

    Post-F-04 fix: provides ``topic=hi`` as a positional param so the
    warning fires from Tier 2 (parameters), not the deleted Tier 3
    heuristic. ``"hi"`` tokenizes well below 1024 (sonnet min).
    """
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    runner = CliRunner()
    # CRITICAL: analyze-cache uses positional `key=value` params via
    # @click.argument("params", nargs=-1) — there is no --inputs flag.
    result = runner.invoke(
        cli,
        ["analyze-cache", str(workflow_path), "topic=hi", "--no-trace-autoload", "--format=json"],
    )
    assert result.exit_code == 0
    payload = _json_payload(result.output)
    assert any(w["id"] == "cache.below-min-tokens" for w in payload["warnings"]), (
        f"expected cache.below-min-tokens to fire on _LLM_WORKFLOW; "
        f"got warnings={[w['id'] for w in payload['warnings']]}"
    )


def test_analyze_cache_json_includes_heterogeneous_model_fragmentation(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _MIXED_MODEL_CACHE_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze-cache", str(workflow_path), "--format=json", f"context={'stable ' * 5000}"],
    )
    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)
    assert any(w["id"] == "cache.heterogeneous-models-fragment-cache" for w in payload["warnings"]), (
        f"expected cache.heterogeneous-models-fragment-cache; got {[w['id'] for w in payload['warnings']]}"
    )


def test_analyze_cache_json_includes_first_call_write_penalty(tmp_path: Path) -> None:
    workflow_path = _write_workflow(tmp_path, _SINGLE_CALL_CACHE_WORKFLOW)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze-cache", str(workflow_path), "--format=json", f"context={'stable ' * 5000}"],
    )
    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)
    assert any(w["id"] == "cache.first-call-write-penalty" for w in payload["warnings"]), (
        f"expected cache.first-call-write-penalty; got {[w['id'] for w in payload['warnings']]}"
    )


def test_analyze_cache_rolls_up_sub_workflow_costs_via_subprocess() -> None:
    """End-to-end fixture: current cost comes from parent + child trace leaves."""
    workflow_path = Path("tests/fixtures/cache_analysis/parent.pflow.md")
    trace_path = Path("tests/fixtures/cache_analysis/parent-child-trace.json")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "analyze-cache",
            str(workflow_path),
            "--from-trace",
            str(trace_path),
            "--format=json",
            "topic=cache analysis",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)
    assert payload["summary"]["actually_paid_usd"] == pytest.approx(0.15)
    child_rollup = payload["summary"]["sub_workflow_rollup"]["per_workflow"][0]
    assert child_rollup["called_by_node_id"] == "call-child"
    assert child_rollup["actually_paid_usd"] == pytest.approx(0.10)


def test_analyze_cache_rolls_up_three_deep_sub_workflow_costs() -> None:
    """3-level workflow tree (parent -> child -> grandchild) — each level has
    one priced LLM call. Verifies that the rollup correctly attributes costs
    across all three levels.

    Original bug context: lyrics-generator song-creator workflow had 41 LLM
    nodes across 3+ depth levels and underreported by ~$0.35 pre-Phase-1
    rollup work. Existing end-to-end coverage tops out at depth 1; this test
    pins the deeper case so a future regression of the per-workflow
    attribution logic surfaces here instead of through a real workflow.
    """
    workflow_path = Path("tests/fixtures/cache_analysis/parent-3deep.pflow.md")
    trace_path = Path("tests/fixtures/cache_analysis/parent-child-grandchild-trace.json")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "analyze-cache",
            str(workflow_path),
            "--from-trace",
            str(trace_path),
            "--format=json",
            "topic=cache analysis",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)

    # summary.actually_paid_usd sums all three priced LLMs: 0.05 + 0.07 + 0.03.
    assert payload["summary"]["actually_paid_usd"] == pytest.approx(0.15)

    rollup = payload["summary"]["sub_workflow_rollup"]
    paths_in_rollup = {entry["workflow_path"] for entry in rollup["per_workflow"]}
    assert any(p.endswith("/child-3deep.pflow.md") for p in paths_in_rollup)
    assert any(p.endswith("/grandchild.pflow.md") for p in paths_in_rollup)

    child_entry = next(e for e in rollup["per_workflow"] if e["workflow_path"].endswith("/child-3deep.pflow.md"))
    grandchild_entry = next(e for e in rollup["per_workflow"] if e["workflow_path"].endswith("/grandchild.pflow.md"))
    # Per-child actually_paid: child's own draft paid 0.07; grandchild's own
    # draft paid 0.03. Child's entry MUST NOT include grandchild's spend
    # (rollup is per-workflow scoped, not cumulative). Pre-rollup-fix this
    # number under-reported / over-reported depending on attribution bug.
    assert child_entry["actually_paid_usd"] == pytest.approx(0.07)
    assert grandchild_entry["actually_paid_usd"] == pytest.approx(0.03)


def test_analyze_cache_does_not_cross_pollinate_subset_groups() -> None:
    """Parent and child both use node id ``draft``; JSON keeps scoped rows separate."""
    workflow_path = Path("tests/fixtures/cache_analysis/parent.pflow.md")
    trace_path = Path("tests/fixtures/cache_analysis/parent-child-trace.json")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "analyze-cache",
            str(workflow_path),
            "--from-trace",
            str(trace_path),
            "--format=json",
            "topic=cache analysis",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json_payload(result.output)
    draft_rows = [row for row in payload["per_call"] if row["node_path"] == "draft"]
    assert len(draft_rows) == 2
    assert len({row["workflow_path"] for row in draft_rows}) == 2
    assert (
        payload["summary"]["sub_workflow_rollup"]["per_workflow"][0]["first_run_with_cache_hypothetical_usd"]
        is not None
    )


def test_analyze_cache_renders_grouped_per_call_table_with_drill_in() -> None:
    """End-to-end text UX: grouped child rows plus drill-in commands."""
    workflow_path = Path("tests/fixtures/cache_analysis/parent.pflow.md")
    trace_path = Path("tests/fixtures/cache_analysis/parent-child-trace.json")
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "analyze-cache",
            str(workflow_path),
            "--from-trace",
            str(trace_path),
            "--all-rows",
            "topic=cache analysis",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "### parent.pflow.md" in result.output
    assert "### child.pflow.md (called by call-child)" in result.output
    assert "## Sub-workflow drill-in" in result.output
    assert "pflow analyze-cache" in result.output


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
