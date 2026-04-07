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


def _wait_for_stderr_marker(proc: subprocess.Popen, marker: str, deadline: float) -> bool:
    """Read ``proc.stderr`` line by line until a line containing ``marker`` arrives.

    Returns True if the marker was seen before ``deadline`` (wall-clock time
    from ``time.monotonic()``). Returns False on timeout or on subprocess exit
    without the marker.
    """
    import select
    import time

    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stderr], [], [], 0.1)
        if ready:
            line = proc.stderr.readline()
            if not line:
                return False  # EOF: subprocess exited
            if marker in line:
                return True
        if proc.poll() is not None:
            return False  # Subprocess exited before the marker
    return False


def _unblock_barrier_fifo(barrier_path: str, proc: subprocess.Popen, timeout: float = 2.0) -> None:
    """Open a barrier FIFO for writing to unblock a workflow step reading from it.

    Retries with short sleeps because there's a small race between the parent
    test process observing stderr and the subprocess opening the FIFO for
    read. ENXIO from ``open(O_WRONLY | O_NONBLOCK)`` means "no reader yet";
    we give the subprocess up to ``timeout`` seconds to become a reader and
    bail out early if the subprocess is already dead.
    """
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            fd = os.open(barrier_path, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, b"go\n")
            finally:
                os.close(fd)
            return
        except OSError:
            if proc.poll() is not None:
                return  # Subprocess is dead; nothing to unblock
            time.sleep(0.05)


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

    def test_progress_streams_before_downstream_nodes_complete(self, tmp_path, uv_exe, subprocess_env):
        """Step_0's completion line must be visible on stderr WHILE step_1 is still running.

        This is the *causal* version of the streaming test: instead of measuring
        wall-clock gaps between progress lines (flaky on slow CI), we pin step_1
        in a known-blocked state via a FIFO barrier and assert that step_0's
        completion line has already arrived on stderr at that moment.

        If live streaming works, the test reads ``step_0... ✓`` from the stderr
        pipe while step_1 is blocked in ``cat <barrier_fifo>``, then unblocks
        step_1 so the workflow can finish. If streaming is broken — someone
        re-introduces the TTY gate, adds buffering to click.echo, removes the
        progress callback gate correctly but installs a buffer somewhere else —
        the bytes sit in a buffer that never flushes (because the subprocess
        is blocked on the barrier and has no reason to flush), the readline
        loop times out, and the assertion fails cleanly.

        This is the only test in the suite that proves live streaming works
        end-to-end, which was Task 149's *primary* stated motivation:
        agents running pflow via a Bash tool need to see live per-node
        visibility, not silence followed by a post-hoc summary.

        Cannot be done via ``CliRunner`` (captures everything until exit) or
        via unit tests of ``OutputController`` (mock ``click.echo``). Only a
        real subprocess with a line-buffered stderr pipe can observe whether
        bytes actually flow as nodes complete.
        """
        import time

        # Named pipe that step_1 will read from. Step_1 blocks until the test
        # writes to it. tmp_path is auto-cleaned by pytest.
        barrier = tmp_path / "barrier.fifo"
        os.mkfifo(str(barrier))

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step_0",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo step_0_ran"},
                },
                {
                    # `cat <fifo>` blocks until a writer opens the FIFO for
                    # writing and closes it. The test controls when that happens.
                    "id": "step_1",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": f"cat {barrier}"},
                },
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "barrier.pflow.md"
        workflow_path.write_text(ir_to_markdown(workflow))

        proc = subprocess.Popen(  # noqa: S603
            [uv_exe, "run", "pflow", str(workflow_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered reads so readline returns as data arrives
            env=subprocess_env,
            shell=False,
        )

        try:
            # 10s hard deadline: subprocess startup + fast step_0 execution +
            # callback + click.echo + pipe delivery should complete in ~1-2s.
            # The generous ceiling only matters if streaming is broken — a
            # passing test exits _wait_for_stderr_marker almost immediately.
            step_0_seen = _wait_for_stderr_marker(proc, "step_0... ✓", time.monotonic() + 10.0)

            # If uv panicked in the sandbox, skip cleanly — we recognize the
            # signature after the subprocess has exited.
            if proc.returncode == 101:
                leftover = proc.stderr.read() or ""
                if "Attempted to create a NULL object" in leftover:
                    pytest.skip("uv subprocess panics in this sandbox before pflow starts")

            assert step_0_seen, (
                "step_0's completion line did not arrive on stderr while "
                "step_1 was still blocked on the barrier FIFO. Progress is "
                "buffered instead of streaming live — Task 149's primary "
                "motivation (agents seeing live per-node progress) is broken."
            )
        finally:
            _unblock_barrier_fifo(str(barrier), proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
