"""Behavioural tests for the gates in scripts/tasks: `--check` (a pre-commit hook), the
six-month fold on the board, and the `--boot` session-log SHA lint. Each runs against a
throwaway `.taskmaster/` tree, since the script resolves everything relative to the cwd.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="scripts/tasks is a bash script")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "tasks"


def spec(root: Path, num: int, status: str, *, roadmap: str | None = None, completed: str | None = None) -> None:
    body = f"# Task {num}: Thing {num}\n\n## Status\n\n{status}\n\n## Description\n\nDo thing {num}.\n"
    if roadmap is not None:
        body += f"\n## Roadmap\n\n{roadmap}\n"
    if completed is not None:
        body += f"\n## Completed\n\n{completed}\n"
    task_dir = root / ".taskmaster" / "tasks" / f"task_{num}"
    task_dir.mkdir(parents=True)
    (task_dir / f"task-{num}.md").write_text(body, encoding="utf-8")


def session_log(root: Path, *lines: str) -> None:
    sessions = root / ".taskmaster" / "orchestration" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "session-01.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], cwd=root, capture_output=True, encoding="utf-8")


# --- --check: every pending spec carries a Roadmap slot ------------------------


def test_check_passes_when_pending_specs_carry_a_slot_and_done_specs_a_date(tmp_path: Path) -> None:
    spec(tmp_path, 1, "not started", roadmap="next")
    spec(tmp_path, 2, "done", completed="2026-01-05")

    result = run(tmp_path, "--check")

    assert result.returncode == 0, result.stdout
    assert "Checked 2 task file(s): 0 error(s), 0 warning(s)." in result.stdout


@pytest.mark.parametrize(
    ("roadmap", "message"),
    [
        (None, "pending but no ## Roadmap slot (next|then|later)"),
        ("soon", 'unrecognized ## Roadmap slot "soon"'),
    ],
)
def test_check_fails_a_pending_spec_without_a_valid_slot(tmp_path: Path, roadmap: str | None, message: str) -> None:
    spec(tmp_path, 7, "not started", roadmap=roadmap)

    result = run(tmp_path, "--check")

    assert result.returncode == 1
    assert f"task_7: {message}" in result.stdout


def test_check_does_not_demand_a_slot_from_non_pending_specs(tmp_path: Path) -> None:
    spec(tmp_path, 3, "deprecated")
    spec(tmp_path, 4, "done")  # no date is a warning, not an error

    result = run(tmp_path, "--check")

    assert result.returncode == 0
    assert "task_4: status is done but no ## Completed date" in result.stdout


# --- the board: roadmap grouping and the six-month fold ------------------------


def test_board_groups_pending_by_slot_and_folds_old_done_tasks(tmp_path: Path) -> None:
    today = datetime.date.today().isoformat()
    spec(tmp_path, 1, "not started", roadmap="next")
    spec(tmp_path, 2, "not started", roadmap="later")
    spec(tmp_path, 3, "not started")
    spec(tmp_path, 4, "done", completed=today)
    spec(tmp_path, 5, "done", completed="2020-01-01")

    board = run(tmp_path)
    assert board.returncode == 0, board.stderr
    out = board.stdout
    assert out.index("## Pending — next") < out.index("Task 1:") < out.index("## Pending — then")
    assert out.index("## Pending — later") < out.index("Task 2:") < out.index("## Pending — unscheduled")
    assert out.index("## Pending — unscheduled") < out.index("Task 3:")
    assert "Task 4:" in out and "Task 5:" not in out
    assert "(1 older done tasks folded" in out

    everything = run(tmp_path, "--done")
    assert "Task 4:" in everything.stdout and "Task 5:" in everything.stdout
    assert "folded" not in everything.stdout


# --- --boot: bare SHAs in the newest session log ------------------------------

SHA = "3f2a9c1e" + "b" * 32


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        (f"- fixed in {SHA}", False),
        ("- fixed in 3f2a9c1e", False),
        (f"- fixed in `{SHA}`", True),
        (f"- see https://github.com/x/y/commit/{SHA}", True),
        (f"- PR #12 merged at {SHA}", True),
        ("- the database row 12345678 was dropped", True),  # digits only: a count, not a SHA
        ("- the database holds deadbeef", False),  # "database" is not the whole word "base"
    ],
)
def test_boot_lints_bare_shas_in_the_newest_session_log(tmp_path: Path, line: str, ok: bool) -> None:
    (tmp_path / ".taskmaster" / "tasks").mkdir(parents=True)
    session_log(tmp_path, "# Session 01", "", line)

    result = run(tmp_path, "--boot")

    assert result.returncode == (0 if ok else 1), result.stdout
    assert ("bare SHA-looking token" in result.stdout) is not ok
    assert "TOTAL" in result.stdout  # the size table prints either way
