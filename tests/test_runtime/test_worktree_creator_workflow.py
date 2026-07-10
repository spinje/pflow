"""Behavioral tests for the worktree creator's embedded parse-result code."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "examples/real-workflows/git-worktree-task-creator/workflow.pflow.md"
)


def run_parse_result(response: str) -> dict[str, str]:
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
        "work_type": "task",
        "issue_number": "",
        "title_resolved": False,
        "agent": "claude",
        "model": "",
        "copy_folder": "",
    }
    exec(code_match.group("code"), namespace)  # noqa: S102
    return namespace["result"]


def test_parse_result_accepts_kebab_case_branch_values() -> None:
    result = run_parse_result("BRANCH_TYPE=feat\nBRANCH_NAME=portable-agent-assets")

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
