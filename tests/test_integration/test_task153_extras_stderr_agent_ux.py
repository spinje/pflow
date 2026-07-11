"""Subprocess regression guard for the task 153 extras-diagnostic render.

The in-memory ``TestUndeclaredExtras`` tests lock the ``Diagnostic`` shape
(message text, ``suggestions``, ``context.available_fields``). They do NOT
verify that the shared render pipeline surfaces all of that through real stderr
when an agent runs ``pflow`` from a terminal.

Why a subprocess test is the right tool here: per ``tests/CLAUDE.md`` §10,
CliRunner masks ``logger.*`` writes to the original stderr fd and hides
partial-line corruption. The run path surfaces diagnostics on stderr via the
same pipeline affected by those failure modes. Any future change to
``format_diagnostic`` or the diagnostic render dispatch could silently drop
the fuzzy suggestion, the ``available_fields`` block, or the
``(passed via inputs: dict)`` qualifier for this specific diagnostic
combination — in-memory tests stay green while the agent-UX regresses.

This is the ONE subprocess test for task 153's agent-UX contract. Keep it
focused on the render surface (run-path stderr, the more regression-prone
route); in-memory shape assertions belong in
``tests/test_core/test_sub_workflow_validation.py::TestUndeclaredExtras``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

CHILD_PFLOW_MD = """\
# Child

Child that declares lyrics as its only input.

## Inputs

### lyrics

Lyrics string.

- type: string
- required: true

## Steps

### echo

Echo the lyrics.

- type: shell

```shell command
echo "lyrics=${lyrics}"
```

## Outputs

### out

What echo produced.

- source: ${echo.stdout}
"""

PARENT_WITH_TYPO = """\
# Parent with a typo in inputs

Parent passes `lyric` (typo) instead of `lyrics`.

## Steps

### call

Call the child with a typo'd input key.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    lyrics: ok
    lyric: TYPO

## Outputs

### out

Child output.

- source: ${call.out}
"""


@pytest.mark.e2e
class TestExtrasDiagnosticStderrAgentUX:
    """Guard that the task-153 extras diagnostic renders correctly through the
    full CLI → format_diagnostic → stderr pipeline."""

    def test_extras_diagnostic_renders_with_fuzzy_suggestion_and_available_fields(
        self, tmp_path: Path, prepared_subprocess_env: dict[str, str]
    ) -> None:
        """Running ``pflow <parent>`` on a workflow with a typo in ``inputs:``
        must surface, on stderr:

        - The core message identifying the undeclared key.
        - The ``(passed via inputs: dict)`` qualifier that localises the fault.
        - The fuzzy 'Did you mean' suggestion (agent's recovery signal).
        - The ``Available declared inputs`` structured block.
        - Non-zero exit code.

        Mutation-verify: if any of the four stderr markers drops out, this
        test fails and the agent-UX regression is caught in CI.
        """
        (tmp_path / "child.pflow.md").write_text(CHILD_PFLOW_MD, encoding="utf-8")
        parent = tmp_path / "parent.pflow.md"
        parent.write_text(PARENT_WITH_TYPO, encoding="utf-8")

        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pflow.cli", str(parent)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            shell=False,
            cwd=str(tmp_path),
            env=prepared_subprocess_env,
        )

        # Agents parse exit code before stderr — lock it first.
        assert completed.returncode != 0, (
            f"pflow must exit non-zero when inputs: dict contains undeclared keys; "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

        stderr = completed.stderr

        # Core message — identifies WHAT went wrong.
        assert "does not declare input 'lyric'" in stderr, (
            f"Core 'does not declare input' message missing from stderr:\n{stderr}"
        )

        # Wording that localises the fault to the inputs dict, not elsewhere.
        assert "(passed via inputs: dict)" in stderr, (
            f"Inputs-dict qualifier missing — agent can't tell where the fault is:\n{stderr}"
        )

        # Fuzzy suggestion — the agent's primary recovery signal.
        assert "Did you mean 'lyrics'" in stderr, (
            f"Fuzzy 'Did you mean lyrics' suggestion missing from stderr:\n{stderr}"
        )

        # Structured block naming the declared inputs.
        assert "Available declared inputs" in stderr, (
            f"Structured 'Available declared inputs' block missing from stderr:\n{stderr}"
        )
        assert "lyrics" in stderr, f"Declared input 'lyrics' must appear in the available-fields list:\n{stderr}"
