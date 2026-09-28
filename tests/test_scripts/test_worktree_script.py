"""Behavioural tests for scripts/worktree against a throwaway git repository.

`make` and `gh` are stubbed on PATH: `make` records its arguments in `MAKE_CALLS` (outside the
worktree, so the tree stays clean) and exits with `MAKE_EXIT`; `gh` answers the merged-PR query
with `GH_STUB_MERGED_HEAD`, or fails when `GH_STUB_FAIL` is set. Cursor/agent launches are
suppressed with `WORKTREE_NO_LAUNCH=1`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="scripts/worktree is a bash script")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "worktree"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *GIT_ID, *args], cwd=cwd, capture_output=True, encoding="utf-8", check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> dict[str, Path]:
    main = tmp_path / "pflow"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "README.md").write_text("hello\n", encoding="utf-8")
    git(main, "add", "README.md")
    git(main, "commit", "-qm", "init")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "make").write_text('#!/bin/sh\necho "$@" >> "$MAKE_CALLS"\nexit "${MAKE_EXIT:-0}"\n', encoding="utf-8")
    (stubs / "gh").write_text(
        '#!/bin/sh\n[ -z "${GH_STUB_FAIL:-}" ] || exit 1\nprintf "%s\\n" "${GH_STUB_MERGED_HEAD:-}"\n',
        encoding="utf-8",
    )
    for stub in ("make", "gh"):
        (stubs / stub).chmod(0o755)
    return {"main": main, "stubs": stubs, "worktrees": tmp_path / "worktrees", "make_calls": tmp_path / "make-calls"}


def run(
    repo: dict[str, Path],
    *args: str,
    cwd: Path | None = None,
    merged_head: str = "",
    gh_fail: bool = False,
    make_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{repo['stubs']}:{os.environ['PATH']}",
        "PFLOW_WORKTREES_DIR": str(repo["worktrees"]),
        "WORKTREE_NO_LAUNCH": "1",
        "GH_STUB_MERGED_HEAD": merged_head,
        "GH_STUB_FAIL": "1" if gh_fail else "",
        "MAKE_CALLS": str(repo["make_calls"]),
        "MAKE_EXIT": str(make_exit),
    }
    return subprocess.run([str(SCRIPT), *args], cwd=cwd or repo["main"], env=env, capture_output=True, encoding="utf-8")


def branches(repo: dict[str, Path], pattern: str) -> str:
    return git(repo["main"], "branch", "--list", pattern)


# --- new ---------------------------------------------------------------------


def test_new_creates_worktree_branch_and_runs_install(repo: dict[str, Path]) -> None:
    result = run(repo, "new", "feat/task-94-model-list", "--no-open")

    assert result.returncode == 0, result.stderr
    wt = repo["worktrees"] / "feat-task-94-model-list"
    assert wt.is_dir()
    assert git(wt, "branch", "--show-current") == "feat/task-94-model-list"
    assert repo["make_calls"].read_text(encoding="utf-8").strip() == "install"
    assert "worktree ready" in result.stdout
    assert "warning" not in result.stderr


def test_new_refuses_an_existing_worktree_dir(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "fix/dup", "--no-open").returncode == 0
    result = run(repo, "new", "fix/dup", "--no-open")

    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_new_off_a_feature_branch_requires_an_explicit_base(repo: dict[str, Path]) -> None:
    git(repo["main"], "checkout", "-qb", "feat/elsewhere")

    refused = run(repo, "new", "fix/thing", "--no-open")
    assert refused.returncode == 1
    assert "not main" in refused.stderr

    explicit = run(repo, "new", "fix/thing", "main", "--no-open")
    assert explicit.returncode == 0, explicit.stderr


def test_new_warns_when_local_main_is_behind_origin(repo: dict[str, Path]) -> None:
    (repo["main"] / "later.txt").write_text("x\n", encoding="utf-8")
    git(repo["main"], "add", "later.txt")
    git(repo["main"], "commit", "-qm", "landed on GitHub")
    ahead = git(repo["main"], "rev-parse", "HEAD")
    git(repo["main"], "reset", "-q", "--hard", "HEAD~1")  # local main never pulled it
    git(repo["main"], "update-ref", "refs/remotes/origin/main", ahead)

    result = run(repo, "new", "feat/stale", "--no-open")

    assert result.returncode == 0, result.stderr
    assert "behind origin/main" in result.stderr


def test_new_removes_the_half_provisioned_worktree_when_install_fails(repo: dict[str, Path]) -> None:
    result = run(repo, "new", "feat/broken", "--no-open", make_exit=2)

    assert result.returncode == 1
    assert "nothing was left behind" in result.stderr
    assert not (repo["worktrees"] / "feat-broken").exists()
    assert branches(repo, "feat/broken") == ""  # a branch this run created is deleted again
    assert "feat-broken" not in git(repo["main"], "worktree", "list")


def test_failed_install_keeps_a_pre_existing_branch(repo: dict[str, Path]) -> None:
    git(repo["main"], "branch", "feat/existing")

    result = run(repo, "new", "feat/existing", "--no-open", make_exit=2)

    assert result.returncode == 1
    assert not (repo["worktrees"] / "feat-existing").exists()
    assert "feat/existing" in branches(repo, "feat/existing")


def test_copy_preserves_the_repo_relative_location(repo: dict[str, Path]) -> None:
    notes = repo["main"] / "scratchpads" / "notes"
    notes.mkdir(parents=True)
    (notes / "brief.md").write_text("read me\n", encoding="utf-8")

    result = run(repo, "new", "feat/with-notes", "--copy", "scratchpads/notes", "--no-open")

    assert result.returncode == 0, result.stderr
    copied = repo["worktrees"] / "feat-with-notes" / "scratchpads" / "notes" / "brief.md"
    assert copied.read_text(encoding="utf-8") == "read me\n"


def test_model_flags_are_validated_before_anything_is_created(repo: dict[str, Path]) -> None:
    sonnet = run(repo, "new", "feat/x", "--no-open", "--claude", "do it", "--model", "sonnet")
    assert sonnet.returncode == 1
    assert "Sonnet tier is retired" in sonnet.stderr

    orphan = run(repo, "new", "feat/x", "--no-open", "--model", "opus")
    assert orphan.returncode == 1
    assert "--model only applies alongside" in orphan.stderr

    assert not (repo["worktrees"] / "feat-x").exists()
    assert branches(repo, "feat/x") == ""


def test_agent_launch_frames_plain_context_and_passes_slash_commands_verbatim(repo: dict[str, Path]) -> None:
    plain = run(repo, "new", "feat/a", "--no-open", "--claude", "Fix the thing")
    assert "Task: Fix the thing." in plain.stdout
    assert "claude --dangerously-skip-permissions" in plain.stdout

    slash = run(repo, "new", "feat/b", "--no-open", "--codex", "/start-orchestration 94", "--model", "opus")
    assert "/start-orchestration 94" in slash.stdout
    assert "Task: /start" not in slash.stdout
    assert "--model gpt-6-astra" in slash.stdout
    assert "sandbox-testing" in slash.stdout


# --- rm ----------------------------------------------------------------------


def test_rm_refuses_dirty_and_unmerged_and_removes_when_merged_clean(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/done", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-done"
    (wt / "dirty.txt").write_text("x", encoding="utf-8")

    dirty = run(repo, "rm", "feat/done")
    assert dirty.returncode == 1 and "dirty" in dirty.stderr

    (wt / "dirty.txt").unlink()
    unmerged = run(repo, "rm", "feat/done", merged_head="")
    assert unmerged.returncode == 1 and "no MERGED PR" in unmerged.stderr

    moved = run(repo, "rm", "feat/done", merged_head="0" * 40)
    assert moved.returncode == 1 and "branch moved" in moved.stderr

    ok = run(repo, "rm", "feat/done", merged_head=git(wt, "rev-parse", "HEAD"))
    assert ok.returncode == 0, ok.stderr
    assert not wt.exists()
    assert branches(repo, "feat/done") == ""


def test_rm_reports_a_gh_failure_instead_of_calling_the_branch_unmerged(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/offline", "--no-open").returncode == 0

    result = run(repo, "rm", "feat/offline", gh_fail=True)

    assert result.returncode == 1
    assert "could not query gh" in result.stderr
    assert "no MERGED PR" not in result.stderr
    assert (repo["worktrees"] / "feat-offline").exists()


def test_rm_refuses_a_detached_head_unless_forced(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/detached", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-detached"
    git(wt, "checkout", "-q", "--detach")

    refused = run(repo, "rm", "feat/detached", merged_head="0" * 40)
    assert refused.returncode == 1 and "detached HEAD" in refused.stderr

    forced = run(repo, "rm", "feat/detached", "-f")
    assert forced.returncode == 0, forced.stderr
    assert not wt.exists()
    assert "no branch to delete" in forced.stdout
    assert "feat/detached" in branches(repo, "feat/detached")  # the branch it left is untouched


def test_rm_dirty_refusal_lists_the_dirty_paths(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/scratchy", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-scratchy"
    (wt / ".lane-scratch").mkdir()
    (wt / ".lane-scratch" / "notes.md").write_text("x", encoding="utf-8")
    (wt / "README.md").write_text("edited\n", encoding="utf-8")

    result = run(repo, "rm", "feat/scratchy", merged_head=git(wt, "rev-parse", "HEAD"))

    assert result.returncode == 1
    assert "    ?? .lane-scratch/" in result.stderr  # untracked scratch vs...
    assert "     M README.md" in result.stderr  # ...an uncommitted edit — the reader can tell them apart
    assert wt.exists()


def test_rm_force_on_a_dirty_tree_still_deletes_a_merged_branch(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/merged-dirty", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-merged-dirty"
    (wt / "dirty.txt").write_text("x", encoding="utf-8")

    result = run(repo, "rm", "feat/merged-dirty", "-f", merged_head=git(wt, "rev-parse", "HEAD"))

    assert result.returncode == 0, result.stderr
    assert "?? dirty.txt" in result.stdout  # what was discarded is on the record
    assert not wt.exists()
    assert branches(repo, "feat/merged-dirty") == ""


@pytest.mark.parametrize(
    ("gh", "reason"),
    [
        ({"gh_fail": True}, "could not query gh"),
        ({"merged_head": ""}, "no MERGED PR"),
        ({"merged_head": "0" * 40}, "branch moved"),
    ],
    ids=["gh-unavailable", "no-merged-pr", "tip-moved"],
)
def test_rm_force_keeps_an_unverified_branch_and_says_why(
    repo: dict[str, Path], gh: dict[str, Any], reason: str
) -> None:
    assert run(repo, "new", "feat/keep", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-keep"
    (wt / "dirty.txt").write_text("x", encoding="utf-8")

    result = run(repo, "rm", "feat/keep", "-f", **gh)

    assert result.returncode == 0, result.stderr
    assert not wt.exists()
    assert "feat/keep" in branches(repo, "feat/keep")
    assert "branch 'feat/keep' kept" in result.stderr and reason in result.stderr


@pytest.mark.skipif(shutil.which("lsof") is None, reason="the live-process guard needs lsof")
def test_rm_force_never_overrides_a_live_process_inside_the_tree(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/busy", "--no-open").returncode == 0
    wt = repo["worktrees"] / "feat-busy"
    (wt / "dirty.txt").write_text("x", encoding="utf-8")  # everything -f overrides, set up to proceed
    sleeper = subprocess.Popen(["sleep", "30"], cwd=wt)
    try:
        result = run(repo, "rm", "feat/busy", "-f", merged_head=git(wt, "rev-parse", "HEAD"))
    finally:
        sleeper.kill()
        sleeper.wait()

    assert result.returncode == 1
    assert f"pid={sleeper.pid}" in result.stderr
    assert "discarding" not in result.stdout
    assert (wt / "dirty.txt").exists()
    assert "feat/busy" in branches(repo, "feat/busy")


def test_rm_refuses_the_main_checkout(repo: dict[str, Path]) -> None:
    result = run(repo, "rm", str(repo["main"]))

    assert result.returncode == 1
    assert "main checkout" in result.stderr


def test_rm_resolves_a_branch_name_before_a_same_named_repo_directory(repo: dict[str, Path]) -> None:
    (repo["main"] / "docs" / "reference").mkdir(parents=True)  # the branch type AND a real directory
    assert run(repo, "new", "docs/reference", "--no-open").returncode == 0
    wt = repo["worktrees"] / "docs-reference"

    result = run(repo, "rm", "docs/reference", merged_head=git(wt, "rev-parse", "HEAD"))

    assert result.returncode == 0, result.stderr
    assert not wt.exists()
    assert (repo["main"] / "docs" / "reference").is_dir()


# --- list --------------------------------------------------------------------


def test_list_shows_worktrees_with_merge_state(repo: dict[str, Path]) -> None:
    assert run(repo, "new", "feat/listed", "--no-open").returncode == 0

    unmerged = run(repo, "list", merged_head="")
    assert unmerged.returncode == 0, unmerged.stderr
    assert "(main checkout)" in unmerged.stdout
    assert "feat/listed" in unmerged.stdout and "unmerged" in unmerged.stdout

    offline = run(repo, "list", gh_fail=True)
    assert offline.returncode == 0, offline.stderr
    assert "gh unavailable" in offline.stdout and "unmerged" not in offline.stdout
