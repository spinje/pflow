"""Behavioral tests for the worktree creator's embedded parse-result code."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "examples/real-workflows/git-worktree-task-creator/workflow.pflow.md"
)


def run_parse_result(
    response: str,
    *,
    work_type: str = "task",
    issue_number: str = "",
    agent: str = "claude",
) -> dict[str, str]:
    """Execute the workflow's parse-result node with deterministic inputs."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    section = workflow.split("### parse-result", maxsplit=1)[1].split("### create-worktree", maxsplit=1)[0]
    code_match = re.search(r"```python code\n(?P<code>.*?)\n```", section, re.DOTALL)
    assert code_match is not None
    namespace = {
        "response": response,
        "repo_root": "/project/pflow",
        "current_branch": "main",
        "base_branch": "",
        "description": "Add portable agent assets",
        "work_type": work_type,
        "issue_number": issue_number,
        "title_resolved": False,
        "agent": agent,
        "model": "",
        "copy_folder": "",
    }
    exec(code_match.group("code"), namespace)  # noqa: S102
    return namespace["result"]


BRANCH_RESPONSE = "BRANCH_TYPE=feat\nBRANCH_NAME=portable-agent-assets"


def test_parse_result_accepts_kebab_case_branch_values() -> None:
    result = run_parse_result(BRANCH_RESPONSE)

    assert result["full_branch"] == "feat/portable-agent-assets"


def test_copy_folder_resolves_from_the_repository_root() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    section = workflow.split("### copy-folder", maxsplit=1)[1].split("### output-status", maxsplit=1)[0]

    assert "ROOT='${get-repo-root.stdout}'" in section
    assert '[ -d "$ROOT/$FOLDER" ]' in section
    assert 'cp -r "$ROOT/$FOLDER"' in section


@pytest.mark.parametrize(
    "response",
    [
        "BRANCH_TYPE=evil\nBRANCH_NAME=portable-agent-assets",
        "BRANCH_TYPE=feat\nBRANCH_NAME=bad'branch",
        'BRANCH_TYPE=feat\nBRANCH_NAME=bad"branch',
    ],
)
def test_parse_result_rejects_unsafe_llm_branch_values(response: str) -> None:
    with pytest.raises(ValueError, match=r"branch_(type|name)"):
        run_parse_result(response)


def test_task_hint_points_the_agent_at_claude_md_and_the_task_spec() -> None:
    result = run_parse_result(BRANCH_RESPONSE)

    assert "CLAUDE.md" in result["agent_hint"]
    assert ".taskmaster/tasks/" in result["agent_hint"]
    assert result["work_label"] == "Task"


def test_issue_hint_forbids_task_scaffolding_and_fetches_via_gh() -> None:
    result = run_parse_result(BRANCH_RESPONSE, work_type="issue", issue_number="443")

    assert "do not create taskmaster task scaffolding" in result["agent_hint"]
    assert "via gh" in result["agent_hint"]
    assert result["work_label"] == "GitHub issue"
    assert result["full_branch"] == "feat/issue-443"  # unresolved title → anchored on the number alone


def test_parse_result_rejects_unknown_work_type() -> None:
    with pytest.raises(ValueError, match=r"work_type must be"):
        run_parse_result(BRANCH_RESPONSE, work_type="ticket")


def test_codex_gets_the_sandbox_testing_hint() -> None:
    result = run_parse_result(BRANCH_RESPONSE, agent="codex")

    assert "sandbox-testing" in result["agent_hint"]
    assert result["agent_label"] == "Codex"
