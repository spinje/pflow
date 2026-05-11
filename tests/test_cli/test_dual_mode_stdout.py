"""Integration tests for stdout output routing (`stdout: true` marker + TTY-gated label).

Mirrors ``test_dual_mode_stdin.py``. Covers the redirect UX bug (naked
``Workflow output (desc):`` label when stdout is redirected) and the
multi-output silent-drop bug (declared outputs vanishing without warning).

These tests use real subprocesses because:
- ``CliRunner`` always reports ``isatty() = False``, which can't distinguish
  "stdout is a pipe" from "stdout is a file" from "stdout is a terminal".
- Subprocess pipes let us verify that the label is suppressed on redirect
  while the payload is intact on stdout.
- The ambiguity error path goes through the full CLI exit-code and stderr
  rendering pipeline, which ``CliRunner`` handles but fragilely.

See `tests/test_cli/test_workflow_output_handling.py` for in-process unit
tests of the selection logic itself.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.shared.markdown_utils import ir_to_markdown


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


@pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
@pytest.mark.e2e
class TestStdoutRedirectLabel:
    """When stdout is not a TTY, the ``Workflow output (desc):`` label is suppressed."""

    def test_single_output_label_suppressed_when_stdout_redirected(self, tmp_path, prepared_subprocess_env):
        """Single declared output + pipe/redirect → no label, value on stdout."""
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"greeting": {"description": "The greeting", "source": "${hello.stdout}"}},
            "nodes": [
                {
                    "id": "hello",
                    "type": "shell",
                    "params": {"command": "echo CANARY_REDIRECT_VALUE"},
                }
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow([str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert "CANARY_REDIRECT_VALUE" in result.stdout
        # The naked label must not appear on stderr when stdout is captured
        assert "Workflow output" not in result.stderr, (
            f"Label should be TTY-gated; stderr still has it:\n{result.stderr}"
        )

    def test_stdout_marker_routes_to_stdout_on_redirect(self, tmp_path, prepared_subprocess_env):
        """Multi-output with ``stdout: true`` on one → only that one on stdout."""
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "primary": {
                    "description": "Primary result",
                    "source": "${primary_node.stdout}",
                    "stdout": True,
                },
                "metadata": {
                    "description": "Secondary metadata",
                    "source": "${meta_node.stdout}",
                },
            },
            "nodes": [
                {
                    "id": "primary_node",
                    "type": "shell",
                    "params": {"command": "echo PRIMARY_MARKED_VALUE"},
                },
                {
                    "id": "meta_node",
                    "type": "shell",
                    "params": {"command": "echo METADATA_VALUE"},
                },
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow([str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert "PRIMARY_MARKED_VALUE" in result.stdout
        assert "METADATA_VALUE" not in result.stdout, "Only the marked output should stream to stdout; metadata leaked"
        # And no label on stderr (redirected stdout)
        assert "Workflow output" not in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
@pytest.mark.e2e
class TestMultiOutputAmbiguity:
    """Multi-declared outputs + no marker + no ``-o`` → warn and emit first."""

    def test_multi_output_no_marker_text_mode_warns_and_emits_first(self, tmp_path, prepared_subprocess_env):
        """Text mode + 2 outputs + no marker + no ``-o`` → exit 0, first on stdout, warning on stderr."""
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "Alpha", "source": "${a.stdout}"},
                "beta": {"description": "Beta", "source": "${b.stdout}"},
            },
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo ALPHA_VAL"}},
                {"id": "b", "type": "shell", "params": {"command": "echo BETA_VAL"}},
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow([str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        # First declared output reaches stdout; the other does NOT
        assert "ALPHA_VAL" in result.stdout
        assert "BETA_VAL" not in result.stdout
        # Warning on stderr names both outputs and the three escape hatches
        assert "Workflow declares 2 outputs" in result.stderr
        assert "alpha" in result.stderr
        assert "beta" in result.stderr
        assert "stdout: true" in result.stderr
        assert "-o" in result.stderr
        assert "--output-format json" in result.stderr

    def test_multi_output_no_marker_print_mode_suppresses_warning(self, tmp_path, prepared_subprocess_env):
        """``-p`` suppresses the multi-output warning, matching Task 134's auto-detect behavior."""
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "Alpha", "source": "${a.stdout}"},
                "beta": {"description": "Beta", "source": "${b.stdout}"},
            },
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo ALPHA_VAL"}},
                {"id": "b", "type": "shell", "params": {"command": "echo BETA_VAL"}},
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow(["-p", str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0
        assert "ALPHA_VAL" in result.stdout
        assert "Workflow declares" not in result.stderr

    def test_multi_output_no_marker_json_mode_succeeds(self, tmp_path, prepared_subprocess_env):
        """Regression: ambiguity error is text-mode-only; JSON emits all outputs.

        PR #257 made ``--output-format`` and ``-p`` orthogonal. The stdout
        marker is a text-mode routing hint and must not gate JSON output.
        """
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "Alpha", "source": "${a.stdout}"},
                "beta": {"description": "Beta", "source": "${b.stdout}"},
            },
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo A_VAL"}},
                {"id": "b", "type": "shell", "params": {"command": "echo B_VAL"}},
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow(["--output-format", "json", str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["result"]["alpha"] == "A_VAL"
        assert payload["result"]["beta"] == "B_VAL"

    def test_multi_output_o_flag_bypasses_ambiguity(self, tmp_path, prepared_subprocess_env):
        """``-o <name>`` at the call site resolves ambiguity without error."""
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "Alpha", "source": "${a.stdout}"},
                "beta": {"description": "Beta", "source": "${b.stdout}"},
            },
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo ALPHA_SELECTED"}},
                {"id": "b", "type": "shell", "params": {"command": "echo BETA_IGNORED"}},
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow(["-o", "alpha", str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert "ALPHA_SELECTED" in result.stdout
        assert "BETA_IGNORED" not in result.stdout

    def test_o_flag_overrides_stdout_marker(self, tmp_path, prepared_subprocess_env):
        """``-o`` wins over ``stdout: true`` — regression guard for the top of the precedence chain.

        The documented precedence is ``-o`` > marker > single-implicit > first
        + warn. A future refactor that moved marker-selection ahead of the
        ``-o`` check would silently demote caller override. This test locks
        the ordering so that reordering breaks it loudly.
        """
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "Marked", "source": "${a.stdout}", "stdout": True},
                "beta": {"description": "Unmarked", "source": "${b.stdout}"},
            },
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo ALPHA_VAL"}},
                {"id": "b", "type": "shell", "params": {"command": "echo BETA_VAL"}},
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow(["-o", "beta", str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert "BETA_VAL" in result.stdout, (
            "-o beta must win over stdout: true on alpha — caller override is the top of the precedence chain"
        )
        assert "ALPHA_VAL" not in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="Unix pipe test")
@pytest.mark.e2e
class TestStdoutValidator:
    """The validator enforces at-most-one ``stdout: true`` per workflow."""

    def test_multiple_stdout_markers_rejected_at_validation(self, tmp_path, prepared_subprocess_env):
        """Two outputs both marked → ``--validate-only`` fails with named outputs."""
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {
                    "description": "Alpha",
                    "source": "${a.stdout}",
                    "stdout": True,
                },
                "beta": {
                    "description": "Beta",
                    "source": "${b.stdout}",
                    "stdout": True,
                },
            },
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo A"}},
                {"id": "b", "type": "shell", "params": {"command": "echo B"}},
            ],
        }
        workflow_file = tmp_path / "wf.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow(["--validate-only", str(workflow_file)], prepared_subprocess_env)
        _skip_uv_sandbox_panic(result)

        assert result.returncode != 0, (
            f"Validator should reject two stdout markers.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "stdout" in combined
        assert "alpha" in combined
        assert "beta" in combined


if __name__ == "__main__":
    # Allow `python tests/test_cli/test_dual_mode_stdout.py` for quick iteration.
    pytest.main([__file__, "-xvs"])
