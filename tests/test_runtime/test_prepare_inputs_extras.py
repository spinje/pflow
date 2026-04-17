"""Tests for undeclared-extras rejection in prepare_inputs (GH #288).

Symmetric with the sub-workflow extras check in
``WorkflowValidator._check_required_inputs`` (task 153). The compiler-layer
check fires at every callsite that compiles: CLI ``run``, MCP
``execute_workflow``, programmatic. ``--validate-only`` is deliberately
structural-only and does not call ``prepare_inputs``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from pflow.runtime.compilation.ir_preparation import prepare_inputs


class TestExtrasRejection:
    """Root-level: keys in provided_params not in declared inputs → error."""

    def test_no_declared_inputs_rejects_any_extra(self):
        """Case A from #288: workflow with no ## Inputs + provided BOGUS → error."""
        errors, _, _ = prepare_inputs({"inputs": {}}, {"BOGUS": "X"})

        assert len(errors) == 1
        msg, path, suggestion = errors[0]
        assert msg == "Unknown input 'BOGUS' — this workflow declares no inputs."
        assert path == "inputs.BOGUS"
        assert "Remove the parameter" in suggestion or "declare it in ## Inputs" in suggestion

    def test_declared_inputs_rejects_unknown_extra(self):
        """Case B from #288: declared 'a' + {a: ok, BOGUS: X} → error naming BOGUS."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "First input", "required": True}}}
        errors, _, _ = prepare_inputs(workflow_ir, {"a": "ok", "BOGUS": "X"})

        extras_errors = [e for e in errors if "Unknown input 'BOGUS'" in e[0]]
        assert len(extras_errors) == 1
        msg, path, suggestion = extras_errors[0]
        assert msg == "Unknown input 'BOGUS' — not declared by this workflow."
        assert path == "inputs.BOGUS"
        # When no fuzzy match, suggestion lists available inputs
        assert "Available inputs: a" in suggestion

    def test_fuzzy_suggestion_for_close_typo(self):
        """Close typo (aa vs a) produces 'Did you mean' suggestion."""
        workflow_ir = {"inputs": {"lyrics": {"type": "string", "description": "Lyrics", "required": True}}}
        errors, _, _ = prepare_inputs(workflow_ir, {"lyrics": "ok", "lyric": "typo"})

        extras = [e for e in errors if "Unknown input 'lyric'" in e[0]]
        assert len(extras) == 1
        _, _, suggestion = extras[0]
        assert "Did you mean 'lyrics'?" in suggestion

    def test_missing_required_and_extra_both_surface(self):
        """Case C from #288: missing required + extra provided → BOTH errors reported."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "Required", "required": True}}}
        errors, _, _ = prepare_inputs(workflow_ir, {"BOGUS": "X"})

        # Aggregated error list should contain both findings (one unknown + one missing)
        assert len(errors) == 2
        messages = [e[0] for e in errors]
        assert any("Unknown input 'BOGUS'" in m for m in messages), messages
        assert any("Workflow requires input 'a'" in m for m in messages), messages

    def test_valid_inputs_produce_no_errors(self):
        """Positive control: providing exactly the declared inputs is not an extra."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "Input A", "required": True}}}
        errors, _, _ = prepare_inputs(workflow_ir, {"a": "value"})
        assert errors == []

    def test_framework_keys_exempted_from_extras_check(self):
        """Internal ``_pflow_*`` keys injected by the Runner/compiler are not extras."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "Input A", "required": True}}}
        # _pflow_workflow_file is injected by Runner before compile (runner.py:141).
        errors, _, _ = prepare_inputs(
            workflow_ir,
            {"a": "value", "_pflow_workflow_file": "/path/to/wf.pflow.md"},
        )
        assert errors == []

    def test_template_resolution_mode_framework_key_exempt(self):
        """Production invariant: ``__template_resolution_mode__`` (injected by
        ``compile_validation.py:165`` before ``prepare_inputs`` runs) must be
        exempted from the extras check. Regressing this breaks every workflow
        compile, so test against the REAL injected key, not a synthetic one."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "Input A", "required": True}}}
        errors, _, _ = prepare_inputs(
            workflow_ir,
            {"a": "value", "__template_resolution_mode__": "strict"},
        )
        assert errors == []

    def test_multiple_extras_all_reported(self):
        """More than one extra → every one surfaces."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "A", "required": True}}}
        errors, _, _ = prepare_inputs(workflow_ir, {"a": "ok", "x": "1", "y": "2", "z": "3"})

        extras_msgs = [e[0] for e in errors if "Unknown input" in e[0]]
        assert len(extras_msgs) == 3
        assert any("'x'" in m for m in extras_msgs)
        assert any("'y'" in m for m in extras_msgs)
        assert any("'z'" in m for m in extras_msgs)

    def test_extras_sorted_deterministically(self):
        """Extras list is emitted in sorted order for deterministic error output."""
        workflow_ir = {"inputs": {"a": {"type": "string", "description": "A", "required": True}}}
        errors, _, _ = prepare_inputs(workflow_ir, {"a": "ok", "zebra": "1", "apple": "2"})

        extras_keys = [e[1].removeprefix("inputs.") for e in errors if "Unknown input" in e[0]]
        assert extras_keys == sorted(extras_keys)


class TestOptionalInputExtras:
    """Optional (non-required) declared inputs are fine; extras not in the declared
    set are still rejected regardless of whether declared ones are required."""

    def test_extra_rejected_even_with_only_optional_declared(self):
        workflow_ir = {
            "inputs": {
                "mode": {
                    "type": "string",
                    "description": "Mode",
                    "required": False,
                    "default": "normal",
                },
            }
        }
        errors, _, _ = prepare_inputs(workflow_ir, {"BOGUS": "X"})

        extras = [e for e in errors if "Unknown input 'BOGUS'" in e[0]]
        assert len(extras) == 1

    def test_optional_declared_provided_is_fine(self):
        workflow_ir = {
            "inputs": {
                "mode": {
                    "type": "string",
                    "description": "Mode",
                    "required": False,
                    "default": "normal",
                },
            }
        }
        errors, _, _ = prepare_inputs(workflow_ir, {"mode": "custom"})
        # No extras error; value passes through as provided (no coercion needed)
        assert not any("Unknown input" in e[0] for e in errors)


class TestValidateOnlyGap:
    """Locked-in regression test documenting the intentional `--validate-only` parity gap.

    `WorkflowRunner.validate()` does NOT call `prepare_inputs`, so the extras
    check added in GH #288 does NOT fire for `pflow <wf> BOGUS=X --validate-only`.
    This is an accepted architectural trade-off from the #288 design discussion:
    extras check lives at the compiler layer (where root missing-required also
    lives), not the validator layer (where sub-workflow extras lives).

    The proper fix is tracked in GH #297 — unify all input-shape checks in
    WorkflowValidator. When that refactor lands, this test should be
    **deliberately flipped** to assert `valid is False` / `len(errors) >= 1`.
    A silent pass/fail flip during an unrelated refactor would indicate the
    parity gap was closed accidentally, not by design.
    """

    def test_validate_only_does_not_catch_root_extras(self):
        """See GH #297. Documents: `--validate-only` is structural, not runtime-shape."""
        from pflow.execution.runner import WorkflowRunner

        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {"a": {"type": "string", "description": "Required input", "required": True}},
            "nodes": [
                {"id": "echo", "type": "shell", "params": {"command": "echo ${a}"}},
            ],
            "edges": [],
        }

        # Extras passed to validate() → currently silent (valid=True). The
        # extras check only fires at compile-time via prepare_inputs.
        result = WorkflowRunner().validate(workflow_ir, params={"a": "ok", "BOGUS": "X"})

        assert result.valid is True, (
            "Extras now caught by --validate-only. This is likely the GH #297 refactor "
            "landing — flip this test to `result.valid is False` with an explicit "
            "Diagnostic check, and delete this docstring."
        )
        assert not any("Unknown input" in d.message for d in result.diagnostics), (
            "A diagnostic for 'Unknown input' appeared — GH #297 may have landed. Flip this test deliberately."
        )


def _skip_uv_sandbox_panic(result: subprocess.CompletedProcess) -> None:
    if result.returncode == 101 and "Attempted to create a NULL object" in (result.stderr or ""):
        pytest.skip("uv subprocess panics in this sandbox before pflow starts")


class TestCliEndToEnd:
    """End-to-end smoke: CLI renders the extras error via the diagnostic pipeline.

    Proves the logic wired through SchemaValidationError → diagnostic_render
    produces the user-facing text from GH #288's motivating cases. The unit
    tests above cover the logic exhaustively; this one verifies the render
    path at the CLI surface.
    """

    _WORKFLOW = """\
# Root with one declared input

## Inputs

### lyrics

The lyrics input.

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

The output.

- source: ${echo.stdout}
"""

    def test_cli_rejects_typo_with_fuzzy_suggestion(self, tmp_path, prepared_subprocess_env):
        """Typo 'lyric' for declared 'lyrics' → 'Did you mean' hint rendered to stderr."""
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(self._WORKFLOW)

        # Clean env to avoid CliRunner-style logger suppression
        env = {k: v for k, v in prepared_subprocess_env.items() if k != "PYTEST_CURRENT_TEST"}
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pflow.cli", str(workflow_file), "lyrics=song", "lyric=typo"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 1, f"expected exit 1, got {result.returncode}\nstderr: {result.stderr!r}"
        assert "Traceback" not in result.stderr
        assert "Unknown input 'lyric'" in result.stderr
        assert "Did you mean 'lyrics'?" in result.stderr
