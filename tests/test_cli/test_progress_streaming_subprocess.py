"""Real-subprocess regression tests for the live progress callback.

These tests intentionally do NOT use ``click.testing.CliRunner``. CliRunner
intercepts ``sys.stderr`` via Click's internal capture machinery, but Python's
``logging`` module holds a reference to the *original* stderr from when
``logging.basicConfig`` ran. That divergence hides exactly the class of bugs
this file guards against:

- ``logger.warning`` from inside a node's ``prep``/``exec``/``post`` writing
  directly to stderr and concatenating onto a partial ``node_id...`` line
  emitted by ``OutputController._handle_node_start``.
- Nested-workflow child progress events writing onto a parent's open partial
  line.

Each test spawns a real ``pflow`` subprocess via ``uv run`` so stderr is a
true file descriptor and the failure modes match what an agent or CI system
would observe.

If you find yourself adding a "logger.warning is fine here" or "click.echo is
fine in the middle of a node" change, please add a regression test alongside
it — these bugs are invisible to ``CliRunner``.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.shared.markdown_utils import ir_to_markdown

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix subprocess test")


def _skip_if_uv_sandbox_panics(result: subprocess.CompletedProcess) -> None:
    """Skip when sandboxed uv panics before pflow starts (CI/dev sandbox quirk)."""
    if result.returncode == 101 and "Attempted to create a NULL object" in (result.stderr or ""):
        pytest.skip("uv subprocess panics in this sandbox before pflow starts")


@pytest.fixture(scope="module")
def subprocess_env(tmp_path_factory, uv_exe):
    """Isolated HOME for subprocess pflow runs (module-scoped to amortize startup)."""
    home = tmp_path_factory.mktemp("home_progress_streaming")
    (home / ".pflow").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)

    # Prime the registry so the first real test isn't paying init cost
    subprocess.run(  # noqa: S603
        [uv_exe, "run", "pflow", "registry", "list", "--json"],
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )

    return env


def _run_pflow(uv_exe: str, env: dict, workflow_path) -> subprocess.CompletedProcess:
    """Run ``pflow <workflow>`` as a real subprocess and return the result."""
    return subprocess.run(  # noqa: S603
        [uv_exe, "run", "pflow", str(workflow_path)],
        capture_output=True,
        text=True,
        shell=False,
        env=env,
    )


class TestRealSubprocessProgressRendering:
    """Subprocess-based regression tests for partial-line corruption modes."""

    def test_failing_shell_node_progress_line_is_clean(self, tmp_path, uv_exe, subprocess_env):
        """A failing shell node must emit ``node_id... ✗ Failed`` as one clean line.

        Regression for the corruption mode where shell.py logged a
        ``logger.warning("Command failed with exit code N")`` from ``post()``,
        which wrote directly to stderr between ``_handle_node_start``'s
        partial-line write and ``_handle_node_complete``'s terminator. The
        captured stderr looked like ``will_fail...WARNING: Command failed
        with exit code 1\\n ✗ Failed`` instead of ``will_fail... ✗ Failed``.

        This is invisible to ``CliRunner`` because pytest's logging fixture
        intercepts the warning before it lands on the captured stream — only
        a true subprocess reproduces the production behavior.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "will_fail",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "exit 1"},
                }
            ],
            "edges": [],
        }
        workflow_file = tmp_path / "fail.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        result = _run_pflow(uv_exe, subprocess_env, workflow_file)
        _skip_if_uv_sandbox_panics(result)

        # The workflow should fail (exit non-zero)
        assert result.returncode != 0, f"expected non-zero exit, got {result.returncode}\nstderr: {result.stderr!r}"

        # The clean terminator must be present as a contiguous substring
        assert "will_fail... ✗ Failed" in result.stderr, (
            "Progress line is corrupted by an interleaved write between "
            "node_start and node_complete (Task 149 / Finding #3 regression).\n"
            f"stderr: {result.stderr!r}"
        )

        # Negative invariants: the corruption shapes we observed historically
        assert "will_fail...WARNING:" not in result.stderr, (
            f"logger.warning text concatenated onto the partial node_id... line.\nstderr: {result.stderr!r}"
        )
        assert "will_fail...Command failed" not in result.stderr, (
            f"Free-form error text concatenated onto the partial node_id... line.\nstderr: {result.stderr!r}"
        )

    def test_nested_workflow_progress_lines_are_not_concatenated(self, tmp_path, uv_exe, subprocess_env):
        """A workflow that calls a sub-workflow must render parent and child cleanly.

        Regression for the rendering mode where ``_handle_node_start`` for a
        ``workflow``-type parent left a partial ``nested_call...`` line, then
        the child engine's own ``_handle_node_start`` events appended their
        partial lines onto it (``nested_call...    inner_a... ✓ 0.5s``).

        After the partial-line tracking fix in ``OutputController``, the child's
        first ``node_start`` terminates the parent's partial line, and the
        parent's ``node_complete`` re-emits a fresh ``  nested_call`` lead-in
        before appending its completion text.
        """
        inner_path = tmp_path / "inner.pflow.md"
        inner_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "inner_a",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo inner_a_done"},
                    },
                    {
                        "id": "inner_b",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo inner_b_done"},
                    },
                ],
                "edges": [],
            })
        )

        outer_path = tmp_path / "outer.pflow.md"
        outer_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "before",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo before"},
                    },
                    {
                        "id": "nested_call",
                        "type": "workflow",
                        "params": {"workflow": str(inner_path)},
                    },
                    {
                        "id": "after",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo after"},
                    },
                ],
                "edges": [],
            })
        )

        result = _run_pflow(uv_exe, subprocess_env, outer_path)
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"workflow failed unexpectedly\nstderr: {result.stderr!r}"

        # Negative invariants: the historical corruption shapes
        # 1. Parent partial line concatenated with child's first start
        assert "nested_call...    inner_a" not in result.stderr, (
            "Nested child progress concatenated onto parent's partial line "
            "(Task 149 / Finding #2 regression).\n"
            f"stderr: {result.stderr!r}"
        )
        assert "nested_call...  " not in result.stderr, (
            "Suspicious whitespace pattern after nested_call partial line — "
            "likely an interleaved child write.\n"
            f"stderr: {result.stderr!r}"
        )

        # Positive invariants: clean rendering
        # The parent should appear on its own line (closed by child's start)
        # AND the parent's completion should be re-emitted attached to its id
        assert "  nested_call...\n" in result.stderr, (
            f"Parent partial line was not closed when child progress started.\nstderr: {result.stderr!r}"
        )
        assert "nested_call ✓" in result.stderr, (
            f"Parent completion line is missing or detached from its node id.\nstderr: {result.stderr!r}"
        )

        # Both children should have rendered cleanly with timing on the same line
        assert "    inner_a... ✓" in result.stderr, (
            f"Child 'inner_a' progress line missing or corrupted.\nstderr: {result.stderr!r}"
        )
        assert "    inner_b... ✓" in result.stderr, (
            f"Child 'inner_b' progress line missing or corrupted.\nstderr: {result.stderr!r}"
        )
