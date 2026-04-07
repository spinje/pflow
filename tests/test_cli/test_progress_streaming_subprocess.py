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
        parent's ``node_complete`` re-emits a fresh ``  nested_call...`` lead-in
        (with the same trailing dots as the original ``node_start`` so
        structured stderr parsers see one canonical format) before appending
        its completion text.
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
        # Re-emitted lead-in keeps the same `node_id...` shape as the original
        # node_start so structured stderr parsers see one canonical format.
        assert "nested_call... ✓" in result.stderr, (
            f"Parent completion line is missing or detached from its node id.\nstderr: {result.stderr!r}"
        )

        # Both children should have rendered cleanly with timing on the same line
        assert "    inner_a... ✓" in result.stderr, (
            f"Child 'inner_a' progress line missing or corrupted.\nstderr: {result.stderr!r}"
        )
        assert "    inner_b... ✓" in result.stderr, (
            f"Child 'inner_b' progress line missing or corrupted.\nstderr: {result.stderr!r}"
        )

    def test_parallel_batch_sub_workflow_renders_coherent_per_item_blocks(self, tmp_path, uv_exe, subprocess_env):
        """Parallel batch where each item runs a sub-workflow must render each
        item's child events as a coherent atomic block — not interleaved with
        other items' events.

        Regression for the race condition where multiple worker threads
        concurrently fired ``node_start``/``node_complete`` events on the
        shared ``OutputController`` while the sub-workflow's child engine
        ran inside each batch item. The race produced semantically-wrong
        rendering: completion text could attach to the wrong node's
        partial line because ``_partial_line_open`` only tracked *whether*
        a partial was open, not *which node's*. With N concurrent workers
        running identical sub-workflows (same child node names), label
        swaps were silent — agents reading stderr saw "child_a finished"
        when actually child_b finished.

        After the per-worker buffering fix in
        ``batch_executor.py::_execute_parallel.process_item``, each worker
        accumulates its child engine's events into a per-thread buffer.
        The main thread (``_collect_parallel_results``) drains the buffer
        through the real callback as one atomic block per item — coherent
        per-item transcripts in completion order, no interleaving.

        This test runs 4 items in parallel, each executing a sub-workflow
        with two children (child_a, child_b). Without the fix, the 8 child
        completion lines could appear in any order. With the fix, they
        must form 4 consecutive (child_a, child_b) pairs.
        """
        # Inner sub-workflow: two distinguishable child nodes that run fast
        inner_path = tmp_path / "inner.pflow.md"
        inner_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "child_a",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo child_a_done"},
                    },
                    {
                        "id": "child_b",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo child_b_done"},
                    },
                ],
                "edges": [],
            })
        )

        # Parent workflow: parallel batch over 4 items, each runs the inner workflow
        outer_path = tmp_path / "outer.pflow.md"
        outer_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "process_items",
                        "type": "workflow",
                        "batch": {
                            "items": ["alpha", "beta", "gamma", "delta"],
                            "as": "item",
                            "parallel": True,
                            "max_concurrent": 4,
                        },
                        "params": {"workflow": str(inner_path)},
                    },
                ],
                "edges": [],
            })
        )

        result = _run_pflow(uv_exe, subprocess_env, outer_path)
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"workflow failed unexpectedly\nstderr: {result.stderr!r}"

        stderr = result.stderr

        # Extract child completion lines in the order they appear on stderr.
        # We look for "child_a..." or "child_b..." with a green checkmark
        # (the completion terminator). Order is the rendering order — what
        # an agent grep'ing stderr would actually see.
        child_lines = [
            line for line in stderr.split("\n") if ("child_a..." in line or "child_b..." in line) and "✓" in line
        ]

        # 4 items x 2 children = 8 completion lines expected
        assert len(child_lines) == 8, (
            f"Expected 8 child completion lines (4 items x 2 children), found {len(child_lines)}.\n"
            f"Lines: {child_lines}\nFull stderr:\n{stderr}"
        )

        # Coherent per-item blocks: pairs must alternate (child_a, child_b),
        # (child_a, child_b), ... — never (child_a, child_a) which would
        # mean two items' child_a events appeared back-to-back.
        for i in range(0, 8, 2):
            assert "child_a..." in child_lines[i], (
                f"Position {i} (item #{i // 2}): expected child_a (start of pair), got {child_lines[i]!r}\n"
                f"This means a different item's events interleaved with this one — the per-worker "
                f"buffering in batch_executor.py::process_item is broken.\n"
                f"Full child line sequence:\n  " + "\n  ".join(child_lines)
            )
            assert "child_b..." in child_lines[i + 1], (
                f"Position {i + 1} (item #{i // 2}): expected child_b (end of pair), got {child_lines[i + 1]!r}\n"
                f"This means child_a's pair-mate is from a different item — atomic-block drain "
                f"in _collect_parallel_results is broken.\n"
                f"Full child line sequence:\n  " + "\n  ".join(child_lines)
            )

        # Negative invariant: no concatenated/corrupted lines
        for line in child_lines:
            # Each child line must contain exactly one node id (no concatenation)
            assert not ("child_a" in line and "child_b" in line), (
                f"Line contains BOTH child_a and child_b — concatenation corruption.\n"
                f"Line: {line!r}\nFull stderr:\n{stderr}"
            )

    def test_verbose_mode_keeps_cli_diagnostics_off_stdout(self, tmp_path, uv_exe, subprocess_env):
        """``pflow -v foo.pflow.md`` must NOT emit any ``cli:`` diagnostic
        lines on stdout. They belong on stderr per the GH #194 routing
        rule (data → stdout, diagnostics → stderr).

        Pre-existing bug surfaced by Task 149's #194 fix: before the fix,
        all output went to stderr in non-TTY mode, so the ``cli:``
        diagnostics were lost in stderr noise. After the fix, data lives
        on stdout — and any ``cli:`` line missing ``err=True`` mixes with
        workflow data, breaking ``pflow -v foo | jq``.

        Catches any future regression where someone adds a ``cli:`` echo
        without ``err=True`` (a common slip).
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo_data",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo VERBOSE_STDOUT_CANARY"},
                },
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "verbose.pflow.md"
        workflow_path.write_text(ir_to_markdown(workflow))

        result = subprocess.run(  # noqa: S603
            [uv_exe, "run", "pflow", "-v", str(workflow_path)],
            capture_output=True,
            text=True,
            shell=False,
            env=subprocess_env,
        )
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"workflow failed unexpectedly\nstderr: {result.stderr!r}"

        # The data canary must be on stdout (GH #194 invariant)
        assert "VERBOSE_STDOUT_CANARY" in result.stdout

        # No `cli:` diagnostic lines on stdout — they pollute pipes to jq
        cli_lines_on_stdout = [line for line in result.stdout.split("\n") if line.startswith("cli:")]
        assert cli_lines_on_stdout == [], (
            "`-v` mode emitted `cli:` diagnostic line(s) on stdout — they belong on stderr.\n"
            f"Polluting lines: {cli_lines_on_stdout}\nFull stdout:\n{result.stdout}"
        )

        # And the verbose `cli:` lines should actually be on stderr (proves
        # the test isn't passing because the lines were silently dropped)
        cli_lines_on_stderr = [line for line in result.stderr.split("\n") if line.startswith("cli:")]
        assert cli_lines_on_stderr, (
            f"`-v` mode produced no `cli:` diagnostics at all — verbose mode appears broken.\nstderr:\n{result.stderr}"
        )

    def test_nested_parallel_batch_recursive_buffering(self, tmp_path, uv_exe, subprocess_env):
        """Parallel batch where each item runs a sub-workflow that ITSELF
        runs a parallel batch must produce coherent rendering at every
        nesting level.

        Strengthens the #6 per-worker buffering coverage. The implementation
        is recursive by construction: when a worker thread (running an
        inner sub-workflow) hits its OWN parallel batch, the inner batch's
        ``process_item`` installs ANOTHER buffering wrapper on its
        sub-items' shared store. The inner buffer captures the deepest
        events; the inner drain (running in the worker thread that's
        single-threaded for this nesting level) flushes them into the
        outer worker's buffer; the outermost main thread eventually
        drains the outer buffer to the real OutputController.

        I claimed this works via mental tracing in the #6 analysis but
        didn't write a test. This is the regression guard.
        """
        # Innermost workflow: 2 leaf nodes
        innermost_path = tmp_path / "innermost.pflow.md"
        innermost_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "leaf_x",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo x"},
                    },
                    {
                        "id": "leaf_y",
                        "type": "shell",
                        "cache": False,
                        "params": {"command": "echo y"},
                    },
                ],
                "edges": [],
            })
        )

        # Middle workflow: parallel batch over the innermost workflow
        middle_path = tmp_path / "middle.pflow.md"
        middle_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "inner_batch",
                        "type": "workflow",
                        "batch": {
                            "items": ["one", "two"],
                            "as": "item",
                            "parallel": True,
                            "max_concurrent": 2,
                        },
                        "params": {"workflow": str(innermost_path)},
                    },
                ],
                "edges": [],
            })
        )

        # Outer workflow: parallel batch over the middle workflow
        outer_path = tmp_path / "outer.pflow.md"
        outer_path.write_text(
            ir_to_markdown({
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "outer_batch",
                        "type": "workflow",
                        "batch": {
                            "items": ["alpha", "beta"],
                            "as": "item",
                            "parallel": True,
                            "max_concurrent": 2,
                        },
                        "params": {"workflow": str(middle_path)},
                    },
                ],
                "edges": [],
            })
        )

        result = _run_pflow(uv_exe, subprocess_env, outer_path)
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"nested parallel batch workflow failed unexpectedly\nstderr: {result.stderr!r}"

        stderr = result.stderr

        # Total leaf events expected: 2 outer items x 2 inner items x 2 leaves = 8
        leaf_lines = [
            line for line in stderr.split("\n") if ("leaf_x..." in line or "leaf_y..." in line) and "✓" in line
        ]
        assert len(leaf_lines) == 8, (
            f"Expected 8 leaf completion lines (2 outer x 2 inner x 2 leaves), found {len(leaf_lines)}.\n"
            f"Lines: {leaf_lines}\nFull stderr:\n{stderr}"
        )

        # Each leaf line must contain ONLY one node id (no concatenation
        # corruption from interleaved worker writes at any nesting level)
        for line in leaf_lines:
            assert not ("leaf_x" in line and "leaf_y" in line), (
                f"Leaf line contains both leaf_x and leaf_y — concatenation at some nesting level.\n"
                f"Line: {line!r}\nFull stderr:\n{stderr}"
            )

        # Coherent atomic blocks: at the deepest level, each innermost
        # invocation produces (leaf_x, leaf_y) as a consecutive pair.
        # 4 innermost invocations total = 4 pairs.
        for i in range(0, 8, 2):
            assert "leaf_x..." in leaf_lines[i], (
                f"Position {i} (innermost #{i // 2}): expected leaf_x, got {leaf_lines[i]!r}\n"
                f"Recursive buffering broken at some nesting level.\n"
                f"Full leaf sequence:\n  " + "\n  ".join(leaf_lines)
            )
            assert "leaf_y..." in leaf_lines[i + 1], (
                f"Position {i + 1} (innermost #{i // 2}): expected leaf_y, got {leaf_lines[i + 1]!r}\n"
                f"Recursive buffering broken at some nesting level.\n"
                f"Full leaf sequence:\n  " + "\n  ".join(leaf_lines)
            )

    def test_only_with_last_node_emits_indicator(self, tmp_path, uv_exe, subprocess_env):
        """``pflow foo --only target`` where ``target`` is the LAST node must
        emit the ``--only`` mode confirmation on stderr.

        Sub-issue 8a from Task 149's code review: the previous gate
        ``if only_node and nodes_skipped > 0:`` hid the indicator when
        nothing was skipped (because the target was the last node, or
        downstream branches were conditional and didn't run anyway).
        Result: rendered output was byte-identical to a full run; agents
        doing iterative debugging couldn't disambiguate.

        Verified with a real subprocess to catch any CLI rendering
        regression including any future change that re-introduces the
        ``> 0`` gate or moves the indicator to a code path that's gated
        by a verbosity flag.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step_a",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo a"},
                },
                {
                    "id": "step_b",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo b"},
                },
                {
                    "id": "last_step",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo c"},
                },
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "only_last.pflow.md"
        workflow_path.write_text(ir_to_markdown(workflow))

        # Use --only on the LAST node so nodes_skipped == 0
        result = subprocess.run(  # noqa: S603
            [uv_exe, "run", "pflow", str(workflow_path), "--only", "last_step"],
            capture_output=True,
            text=True,
            shell=False,
            env=subprocess_env,
        )
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"workflow failed unexpectedly\nstderr: {result.stderr!r}"

        # The mode confirmation MUST appear on stderr — without this,
        # the run is indistinguishable from a full run.
        assert "⤷ Stopped after 'last_step' (--only)" in result.stderr, (
            "Sub-issue 8a regression: --only confirmation missing when target was the last node.\n"
            f"stderr:\n{result.stderr}"
        )
        # Short form: no "0 remaining" or "N remaining" since 0 nodes were skipped
        assert "remaining" not in result.stderr, (
            f"Short form expected (0 nodes skipped) but found 'remaining' suffix.\nstderr:\n{result.stderr}"
        )

    def test_print_mode_with_only_emits_indicator(self, tmp_path, uv_exe, subprocess_env):
        """``pflow -p foo --only target`` must emit the ``--only`` mode
        confirmation on stderr even though ``-p`` suppresses the rest of
        the summary.

        Sub-issue 8b from Task 149's code review: ``-p`` mode previously
        suppressed the entire summary block including the ``--only``
        line. Result: ``pflow -p foo --only target`` produced 0 bytes on
        stderr, leaving agents iteratively debugging with -p + --only
        unable to detect that the run was constrained.

        ``--only`` is a mode signal, not a summary detail. Mode flags
        survive verbosity flags. This matches the convention of
        ``make -k``, ``pytest --maxfail``, ``rsync --dry-run``,
        ``apt-get --simulate``, ``kubectl --dry-run``, etc.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step_a",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo first"},
                },
                {
                    "id": "step_b",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo PRINT_ONLY_CANARY"},
                },
                {
                    "id": "step_c",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo never"},
                },
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "print_only.pflow.md"
        workflow_path.write_text(ir_to_markdown(workflow))

        result = subprocess.run(  # noqa: S603
            [uv_exe, "run", "pflow", "-p", str(workflow_path), "--only", "step_b"],
            capture_output=True,
            text=True,
            shell=False,
            env=subprocess_env,
        )
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"workflow failed unexpectedly\nstderr: {result.stderr!r}"

        # stdout: data from step_b (the --only target)
        assert "PRINT_ONLY_CANARY" in result.stdout, (
            f"Workflow output missing from stdout in -p + --only mode.\nstdout: {result.stdout!r}"
        )

        # stderr: ONLY the --only mode confirmation, nothing else
        # (no "Executing workflow", no "Workflow completed", no progress lines)
        assert "⤷ Stopped after 'step_b' (--only)" in result.stderr, (
            "Sub-issue 8b regression: --only mode confirmation missing in -p mode.\n"
            "Mode flags must survive verbosity flags.\n"
            f"stderr:\n{result.stderr}"
        )
        assert "Executing workflow" not in result.stderr, (
            f"-p mode should suppress 'Executing workflow' header.\nstderr:\n{result.stderr}"
        )
        assert "Workflow completed" not in result.stderr, (
            f"-p mode should suppress completion summary.\nstderr:\n{result.stderr}"
        )

    def test_print_mode_without_only_stays_silent(self, tmp_path, uv_exe, subprocess_env):
        """REGRESSION GUARD: ``-p`` mode without ``--only`` must remain silent
        on stderr.

        Confirms the --only fix didn't accidentally break the existing
        ``-p`` minimal-output contract for the common case (no --only).
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "step_a",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "echo PLAIN_PRINT_CANARY"},
                },
            ],
            "edges": [],
        }
        workflow_path = tmp_path / "print_plain.pflow.md"
        workflow_path.write_text(ir_to_markdown(workflow))

        result = subprocess.run(  # noqa: S603
            [uv_exe, "run", "pflow", "-p", str(workflow_path)],
            capture_output=True,
            text=True,
            shell=False,
            env=subprocess_env,
        )
        _skip_if_uv_sandbox_panics(result)

        assert result.returncode == 0, f"workflow failed unexpectedly\nstderr: {result.stderr!r}"
        assert "PLAIN_PRINT_CANARY" in result.stdout
        # stderr must be empty or near-empty (no progress, no header, no
        # --only line because --only is not active)
        assert "⤷" not in result.stderr, (
            f"-p mode without --only should not emit any --only indicator.\nstderr:\n{result.stderr!r}"
        )
        assert "Executing workflow" not in result.stderr
        assert "Workflow completed" not in result.stderr
        assert "Stopped after" not in result.stderr

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
