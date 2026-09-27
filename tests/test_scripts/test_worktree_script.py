"""Behavioural tests for scripts/worktree against a throwaway git repository.

`make` and `gh` are stubbed on PATH: `make` records that `install` ran, `gh` answers the
merged-PR query with whatever `GH_STUB_MERGED_HEAD` holds. Cursor/agent launches are
suppressed with `WORKTREE_NO_LAUNCH=1`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "worktree"


@pytest.fixture
def repo(tmp_path: Path) -> dict[str, Path]:
    main = tmp_path / "pflow"
    main.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=main, check=True)
    (main / "README.md").write_text("hello\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "README.md"], cwd=main, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=main, check=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "make").write_text('#!/bin/sh\necho "$@" >> .make-calls\n')
    (stubs / "gh").write_text('#!/bin/sh\nprintf "%s\\n" "${GH_STUB_MERGED_HEAD:-}"\n')
    for stub in ("make", "gh"):
        (stubs / stub).chmod(0o755)
    return {"main": main, "stubs": stubs, "worktrees": tmp_path / "worktrees"}


def run(
    repo: dict[str, Path], *args: str, cwd: Path | None = None, merged_head: str = ""
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{repo['stubs']}:{os.environ['PATH']}",
        "PFLOW_WORKTREES_DIR": str(repo["worktrees"]),
        "WORKTREE_NO_LAUNCH": "1",
        "GH_STUB_MERGED_HEAD": merged_head,
    }
    return subprocess.run([str(SCRIPT), *args], cwd=cwd or repo["main"], env=env, capture_output=True, text=True)


def tip(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_new_creates_worktree_branch_and_runs_install(repo: dict[str, Path]) -> None:
    result = run(repo, "new", "feat/task-94-model-list", "--no-open")

    assert result.returncode == 0, result.stderr
    wt = repo["worktrees"] / "feat-task-94-model-list"
    assert wt.is_dir()
    assert (
        subprocess.run(["git", "branch", "--show-current"], cwd=wt, capture_output=True, text=True).stdout.strip()
        == "feat/task-94-model-list"
    )
    assert (wt / ".make-calls").read_text().strip() == "install"
    assert "worktree ready" in result.stdout


def test_new_refuses_an_existing_worktree_dir(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "fix/dup", "--no-open").returncode == 0
    result = run(repo, "new", "fix/dup", "--no-open")

    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_new_off_a_feature_branch_requires_an_explicit_base(repo: dict[str, Path]) -> None:
    subprocess.run(["git", "checkout", "-qb", "feat/elsewhere"], cwd=repo["main"], check=True)

    refused = run(repo, "new", "fix/thing", "--no-open")
    assert refused.returncode == 1
    assert "not main" in refused.stderr

    explicit = run(repo, "new", "fix/thing", "main", "--no-open")
    assert explicit.returncode == 0, explicit.stderr


def test_copy_preserves_the_repo_relative_location(repo: dict[str, Path]) -> None:
    notes = repo["main"] / "scratchpads" / "notes"
    notes.mkdir(parents=True)
    (notes / "brief.md").write_text("read me\n")

    result = run(repo, "new", "feat/with-notes", "--copy", "scratchpads/notes", "--no-open")

    assert result.returncode == 0, result.stderr
    assert (repo["worktrees"] / "feat-with-notes" / "scratchpads" / "notes" / "brief.md").read_text() == "read me\n"


def test_sonnet_model_is_refused(repo: dict[str, Path]) -> None:
    result = run(repo, "new", "feat/x", "--no-open", "--claude", "do it", "--model", "sonnet")

    assert result.returncode == 1
    assert "Sonnet tier is retired" in result.stderr
    assert not (repo["worktrees"] / "feat-x").exists()


def test_agent_launch_frames_plain_context_and_passes_slash_commands_verbatim(repo: dict[str, Path]) -> None:
    plain = run(repo, "new", "feat/a", "--no-open", "--claude", "Fix the thing")
    assert "Task: Fix the thing." in plain.stdout
    assert "claude --dangerously-skip-permissions" in plain.stdout

    slash = run(repo, "new", "feat/b", "--no-open", "--codex", "/start-orchestration 94", "--model", "opus")
    assert "/start-orchestration 94" in slash.stdout
    assert "Task: /start" not in slash.stdout
    assert "--model gpt-5.6-sol" in slash.stdout
    assert "sandbox-testing" in slash.stdout


def test_rm_refuses_dirty_and_unmerged_and_removes_when_merged_clean(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/done", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-done"
    (wt / ".make-calls").unlink()  # the stub's marker would read as dirt
    (wt / "dirty.txt").write_text("x")

    dirty = run(repo, "rm", "feat/done")
    assert dirty.returncode == 1 and "dirty" in dirty.stderr

    (wt / "dirty.txt").unlink()
    unmerged = run(repo, "rm", "feat/done", merged_head="")
    assert unmerged.returncode == 1 and "no MERGED PR" in unmerged.stderr

    moved = run(repo, "rm", "feat/done", merged_head="0" * 40)
    assert moved.returncode == 1 and "branch moved" in moved.stderr

    ok = run(repo, "rm", "feat/done", merged_head=tip(wt))
    assert ok.returncode == 0, ok.stderr
    assert not wt.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", "feat/done"], cwd=repo["main"], capture_output=True, text=True
    ).stdout
    assert branches.strip() == ""


def test_rm_force_skips_checks_and_keeps_the_branch(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/keep", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-keep"
    (wt / "dirty.txt").write_text("x")

    result = run(repo, "rm", "feat/keep", "-f")

    assert result.returncode == 0, result.stderr
    assert not wt.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", "feat/keep"], cwd=repo["main"], capture_output=True, text=True
    ).stdout
    assert "feat/keep" in branches


def test_rm_refuses_the_main_checkout(repo: dict[str, Path]) -> None:
    result = run(repo, "rm", str(repo["main"]))

    assert result.returncode == 1
    assert "main checkout" in result.stderr


def test_list_shows_worktrees_with_merge_state(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/listed", "--no-open").returncode == 0

    result = run(repo, "list", merged_head="")

    assert result.returncode == 0, result.stderr
    assert "(main checkout)" in result.stdout
    assert "feat/listed" in result.stdout and "unmerged" in result.stdout
