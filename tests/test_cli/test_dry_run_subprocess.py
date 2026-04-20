"""Real-subprocess tests for `--dry-run`.

Covers agent-facing contracts that the in-process `invoke_cli` harness
cannot reliably test: exit codes at the OS level, JSON-mode stderr silence,
and stream-separation under real file descriptors. See
`test_progress_streaming_subprocess.py` for the rationale behind using real
subprocesses instead of CliRunner (logger.* writes to the original stderr
FD, not Click's captured stream).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix subprocess test")


def _skip_if_uv_sandbox_panics(result: subprocess.CompletedProcess) -> None:
    if result.returncode == 101 and "Attempted to create a NULL object" in (result.stderr or ""):
        pytest.skip("uv subprocess panics in this sandbox before pflow starts")


@pytest.fixture(scope="module")
def subprocess_env(tmp_path_factory, uv_exe):
    """Isolated HOME for subprocess pflow runs; scrubs PYTEST_CURRENT_TEST.

    Matches the pattern in `test_progress_streaming_subprocess.py`: without
    scrubbing PYTEST_CURRENT_TEST the subprocess short-circuits
    `configure_logging`, hiding the real stream-routing behavior.
    """
    home = tmp_path_factory.mktemp("home_dry_run_subprocess")
    (home / ".pflow").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def test_dry_run_json_mode_emits_no_stderr(tmp_path, uv_exe, subprocess_env):
    """`--dry-run --output-format json` must keep stderr empty.

    pflow's JSON convention: stdout gets the JSON document, stderr stays
    silent so `pflow ... -f json 2>/dev/null | jq` works. The in-process
    CLI harness can't reliably test this because `logger.*` writes route
    to the ORIGINAL stderr FD, not the harness's captured stream —
    corruption only shows up under a real subprocess.
    """
    wf = tmp_path / "silent.pflow.md"
    wf.write_text(
        """# Silent

Minimal workflow for stderr-silence test.

## Steps

### echo

Echoes.

- type: shell
- command: printf hi
""",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603
        [uv_exe, "run", "pflow", "--dry-run", "--output-format", "json", str(wf)],
        capture_output=True,
        text=True,
        shell=False,
        env=subprocess_env,
        cwd=str(tmp_path),
        timeout=60,
    )
    _skip_if_uv_sandbox_panics(result)

    assert result.returncode == 0, f"dry-run exited {result.returncode}; stderr={result.stderr!r}"
    assert result.stderr == "", f"JSON mode must keep stderr empty; got {result.stderr!r}"
    # Stdout must be a single, parseable JSON document.
    payload = json.loads(result.stdout)
    assert set(payload) == {"workflow", "plan", "summary", "diagnostics"}
