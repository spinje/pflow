"""Tests for the CLI error boundary at PflowCLI.invoke().

The boundary catches PflowError subclasses escaping subcommand callbacks
and routes them through output_error() → format_diagnostic() so CLI
errors render structured diagnostics instead of Python tracebacks.

See GH #292 and tests/test_cli/CLAUDE.md for test patterns.
"""

from __future__ import annotations

import subprocess
import sys

import click
import pytest
from click.testing import CliRunner

from tests.conftest import set_isolated_home

# Invalid workflow: output "out" has no description paragraph between the
# heading and the `- source:` param. parse_markdown raises MarkdownParseError
# at line 23 ("Entity 'out' (line 23) is missing a description.").
PARSE_ERROR_WORKFLOW = """\
# Bug Repro

## Inputs

### x

A message.

- type: string
- required: true

## Steps

### echo

Echo it.

- type: shell
- command: echo "${x}"

## Outputs

### out

- source: ${echo.stdout}
"""


def _skip_uv_sandbox_panic(result: subprocess.CompletedProcess) -> None:
    """Skip when the uv subprocess panics in a restricted sandbox."""
    if result.returncode == 101 and "Attempted to create a NULL object" in (result.stderr or ""):
        pytest.skip("uv subprocess panics in this sandbox before pflow starts")


def _run_pflow(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run pflow via the in-repo Python module, capturing both streams."""
    # Don't inherit PYTEST_CURRENT_TEST — causes configure_logging to short-circuit
    # and partial-line filters to skip install. See tests/CLAUDE.md #10.
    clean_env = {k: v for k, v in env.items() if k != "PYTEST_CURRENT_TEST"}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pflow.cli", *args],
        capture_output=True,
        text=True,
        env=clean_env,
        timeout=60,
    )


def _save_broken_workflow(home_dir, name: str) -> None:
    """Write PARSE_ERROR_WORKFLOW as a saved workflow under HOME/.pflow/workflows/."""
    workflow_dir = home_dir / ".pflow" / "workflows" / name
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / f"{name}.pflow.md").write_text(PARSE_ERROR_WORKFLOW)


@pytest.mark.e2e
class TestDescribeParseError:
    """Primary guards for GH #292 — pflow describe must not crash with a traceback."""

    def test_describe_parse_error_renders_via_diagnostic_pipeline(self, tmp_path, prepared_subprocess_env):
        """pflow describe <workflow-with-parse-error> renders a structured diagnostic, not a traceback."""
        env = dict(prepared_subprocess_env)
        set_isolated_home(env, tmp_path)
        (tmp_path / ".pflow").mkdir(exist_ok=True)
        _save_broken_workflow(tmp_path, "__boundary_parse_err")

        result = _run_pflow(["describe", "__boundary_parse_err"], env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 1, f"expected exit 1, got {result.returncode}\nstderr: {result.stderr!r}"
        assert "Traceback" not in result.stderr, (
            f"Boundary must catch PflowError; stderr still has a traceback:\n{result.stderr}"
        )
        # Structured diagnostic markers
        assert "Parse Error" in result.stderr, f"missing 'Parse Error' title:\n{result.stderr}"
        assert "line 23" in result.stderr, f"missing source line ref:\n{result.stderr}"
        # Suggestion block surfaced (from MarkdownParseError.suggestion)
        assert "Add a text paragraph" in result.stderr, f"missing suggestion block:\n{result.stderr}"

    def test_history_also_uses_boundary_for_parse_errors(self, tmp_path, prepared_subprocess_env):
        """Architectural check: boundary is not describe-specific.

        pflow history (a sibling command that also calls WorkflowManager.load())
        must render the same structured diagnostic. Protects against anyone
        later wiring per-command handlers and silently regressing the boundary.
        """
        env = dict(prepared_subprocess_env)
        set_isolated_home(env, tmp_path)
        (tmp_path / ".pflow").mkdir(exist_ok=True)
        _save_broken_workflow(tmp_path, "__boundary_history_err")

        result = _run_pflow(["history", "__boundary_history_err"], env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "Parse Error" in result.stderr
        assert "line 23" in result.stderr

    def test_describe_and_validate_only_produce_same_diagnostic(self, tmp_path, prepared_subprocess_env):
        """Symmetry guard: describe and file --validate-only produce the same diagnostic content.

        For parse errors, resolve_workflow() raises MarkdownParseError BEFORE
        --validate-only's pipeline takes effect, so both commands hit
        PflowCLI.invoke → display_exception_text → format_diagnostic. This
        test verifies the group boundary renders consistently for both
        entry points. (It does NOT exercise validate-only's
        format_validation_failure rendering — that path is unreachable for
        parse errors because resolve_workflow short-circuits.)

        Locks in Change 2: preserving structured diagnostics through
        WorkflowValidationError.validation_errors reaches both paths
        identically.
        """
        env = dict(prepared_subprocess_env)
        set_isolated_home(env, tmp_path)
        (tmp_path / ".pflow").mkdir(exist_ok=True)
        _save_broken_workflow(tmp_path, "__boundary_symmetry")

        # Also write a copy as a standalone file for the --validate-only path
        standalone = tmp_path / "standalone.pflow.md"
        standalone.write_text(PARSE_ERROR_WORKFLOW)

        describe_result = _run_pflow(["describe", "__boundary_symmetry"], env)
        validate_result = _run_pflow([str(standalone), "--validate-only"], env)
        _skip_uv_sandbox_panic(describe_result)
        _skip_uv_sandbox_panic(validate_result)

        assert describe_result.returncode == 1
        assert validate_result.returncode == 1

        # The rendered diagnostic body must match. Both paths use the same
        # MarkdownParseError.to_diagnostics() → format_diagnostic() pipeline.
        for marker in (
            "Error: Parse Error",
            "Entity 'out' (line 23) is missing a description.",
            "At: line 23",
            "Add a text paragraph between the heading and the parameters",
        ):
            assert marker in describe_result.stderr, f"describe missing '{marker}':\n{describe_result.stderr}"
            assert marker in validate_result.stderr, f"validate missing '{marker}':\n{validate_result.stderr}"


class TestBoundaryNarrowCatch:
    """Negative control: the boundary catches PflowError only, not generic Exception.

    Genuine bugs (RuntimeError, AssertionError) must still produce tracebacks
    for debugging. Uses CliRunner for in-process assertion because we're
    testing control flow (exception propagation), not stderr coherence.
    """

    def test_cli_boundary_does_not_catch_runtime_error(self):
        """A non-PflowError raised by a subcommand must propagate out of the CLI."""
        from pflow.cli.main import cli

        @click.command(name="__test_runtime_error__")
        def raiser() -> None:
            raise RuntimeError("genuine bug — must not be swallowed")

        cli.add_command(raiser)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["__test_runtime_error__"], catch_exceptions=True)

            # CliRunner captures the uncaught exception in result.exception.
            # If the boundary incorrectly widened to `except Exception`, this
            # would be None and exit_code would be 1 via the boundary path.
            assert result.exception is not None, (
                f"RuntimeError should have propagated — boundary must not catch it.\noutput: {result.output}"
            )
            assert isinstance(result.exception, RuntimeError)
            assert "genuine bug" in str(result.exception)
        finally:
            cli.commands.pop("__test_runtime_error__", None)

    def test_cli_boundary_catches_pflow_error(self):
        """Positive control: an arbitrary PflowError raised by a subcommand is caught."""
        from pflow.cli.main import cli
        from pflow.core.exceptions import WorkflowNotFoundError

        @click.command(name="__test_pflow_error__")
        def raiser() -> None:
            raise WorkflowNotFoundError("imaginary-workflow")

        cli.add_command(raiser)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["__test_pflow_error__"], catch_exceptions=True)

            # Boundary caught → no uncaught exception, clean exit 1, rendered output
            assert result.exception is None or isinstance(result.exception, SystemExit), (
                f"Boundary should have caught PflowError; exception={result.exception!r}"
            )
            assert result.exit_code == 1
            # output + stderr both captured into result.output by CliRunner
            assert "Workflow Not Found" in result.output or "imaginary-workflow" in result.output
        finally:
            cli.commands.pop("__test_pflow_error__", None)


@pytest.mark.e2e
class TestRunCommandUnchanged:
    """Regression guard: run has its own boundary; the group boundary must not interfere."""

    def test_run_shell_failure_still_renders_via_own_pipeline(self, tmp_path, prepared_subprocess_env):
        """A failing shell workflow still routes through run's output_error() with full context."""
        workflow_content = """\
# Fail

## Steps

### boom

Runs a failing command.

- type: shell

```shell command
exit 1
```

## Outputs

### out

The stdout.

- source: ${boom.stdout}
"""
        workflow_file = tmp_path / "fail.pflow.md"
        workflow_file.write_text(workflow_content, encoding="utf-8")

        result = _run_pflow([str(workflow_file), "--no-trace"], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        stderr = result.stderr or ""
        assert result.returncode != 0, f"workflow should fail:\nstdout: {result.stdout}\nstderr: {stderr}"
        assert "Traceback" not in stderr, f"run should not traceback:\n{stderr}"
        # Assertions below are run-pipeline-specific — the group boundary
        # (PflowCLI.invoke) would never emit these. They prove run's own
        # output_error() path fired, not a fallthrough to the boundary.
        assert "Executing workflow" in stderr, (
            f"run's execution-progress line missing — likely group boundary caught the error instead of run's pipeline:\n{stderr}"
        )
        assert "Shell details:" in stderr, (
            f"category-aware shell rendering missing — failed-node diagnostic not routed through run's executor_service:\n{stderr}"
        )
        assert "At: node 'boom'" in stderr, f"node-specific attribution missing:\n{stderr}"
