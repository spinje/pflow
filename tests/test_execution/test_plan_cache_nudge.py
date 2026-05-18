"""F3.3 — `--dry-run` cache nudge integration.

Locks the contract:

- A workflow with cache opportunities → plan.diagnostics contains the
  ``cache.opportunities-available`` Diagnostic.
- A workflow with no opportunities → no nudge (silent).
- The nudge follows the locked text format (singular/plural pluralization
  + dollar/percent format).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def _write_workflow(tmp_path: Path, content: str, name: str = "wf.pflow.md") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


_WORKFLOW_NO_OPPORTUNITIES = """\
# Plain shell workflow

A workflow with no LLM nodes — no cache opportunities exist.

## Steps

### echo

Echo a greeting.

- type: shell

```command
echo hello
```
"""


_WORKFLOW_WITH_LLM = """\
# Workflow with cache opportunities

A workflow with an LLM node that emits cache.below-min-predicted.

## Inputs

### topic

Topic to summarize.

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
Provide a concise summary.
```
"""


def test_silent_when_no_opportunities(tmp_path: Path) -> None:
    """Workflow with zero cache opportunities → no nudge appears in diagnostics."""
    workflow_path = _write_workflow(tmp_path, _WORKFLOW_NO_OPPORTUNITIES)
    runner = WorkflowRunner()
    plan = runner.plan(str(workflow_path), {}, RunnerConfig())
    nudge_ids = [d.id for d in plan.diagnostics if d.id == "cache.opportunities-available"]
    # Silent — no nudge.
    assert nudge_ids == []


def test_nudge_appears_when_opportunities_exist(tmp_path: Path) -> None:
    """Workflow with cache.below-min-predicted triggers the nudge."""
    workflow_path = _write_workflow(tmp_path, _WORKFLOW_WITH_LLM)
    runner = WorkflowRunner()
    plan = runner.plan(str(workflow_path), {"topic": "climate"}, RunnerConfig())
    nudges = [d for d in plan.diagnostics if d.id == "cache.opportunities-available"]
    assert len(nudges) == 1
    nudge = nudges[0]
    # Locked message format prefix.
    assert nudge.message.startswith("Cache: ")
    assert "design opportunit" in nudge.message
    # Suggestions list points at analyze-cache CLI.
    assert nudge.suggestions == ["Run 'pflow analyze-cache' for details."]


def test_nudge_failure_does_not_break_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nudge generation is advisory — analyzer crashes must NEVER fail dry-run."""
    workflow_path = _write_workflow(tmp_path, _WORKFLOW_WITH_LLM)

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic analyzer crash")

    # Monkeypatch the analyze function used by the nudge builder.
    import pflow.core.cache_analysis

    monkeypatch.setattr(pflow.core.cache_analysis, "analyze", _boom)

    runner = WorkflowRunner()
    # Should NOT raise.
    plan = runner.plan(str(workflow_path), {"topic": "climate"}, RunnerConfig())
    # Plan still built; nudge is silently absent.
    assert plan is not None
    nudge_ids = [d.id for d in plan.diagnostics if d.id == "cache.opportunities-available"]
    assert nudge_ids == []
