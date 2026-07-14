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
    mode: str = "explore",
    phases: str = "",
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
        "mode": mode,
        "phases": phases,
        "issue_number": issue_number,
        "title_resolved": False,
        "agent": agent,
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


BRANCH_RESPONSE = "BRANCH_TYPE=feat\nBRANCH_NAME=portable-agent-assets"


def test_explore_mode_points_agent_at_start_work() -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="explore")

    assert "/start-work" in result["agent_hint"]
    assert "/implement-plan" not in result["agent_hint"]


def test_implement_mode_points_agent_at_implement_plan_with_task_number() -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="177")

    assert "/implement-plan 177" in result["agent_hint"]
    assert "/start-work" not in result["agent_hint"]
    assert "do NOT explore or re-plan" in result["agent_hint"]


def test_implement_mode_without_number_falls_back_to_plan_path() -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="")

    assert "/implement-plan" in result["agent_hint"]
    assert "implementation-plan.md" in result["agent_hint"]


def test_implement_mode_for_issue_does_not_pass_issue_number_as_task_id() -> None:
    # An issue number is NOT a task id and issues have no .taskmaster plan, so it
    # must not become `/implement-plan 443` (which resolves to a nonexistent task).
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", work_type="issue", issue_number="443")

    assert "/implement-plan 443" not in result["agent_hint"]
    assert "existing plan for this issue" in result["agent_hint"]
    assert "do not create taskmaster scaffolding" in result["agent_hint"]


def test_implement_mode_without_phases_tells_agent_to_proceed_on_whole_plan() -> None:
    # /implement-plan asks before implementing a whole plan when no scope is given;
    # implement mode is an explicit "do it directly" request, so proceed.
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="177")

    assert "whole plan" in result["agent_hint"].lower()
    assert "no need to ask" in result["agent_hint"].lower()
    # The proceed directive is mutually exclusive with the phase-scope directive.
    assert "Implement ONLY phase(s)" not in result["agent_hint"]


def test_codex_sandbox_hint_is_skill_neutral_in_implement_mode() -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="177", agent="codex")

    assert "sandbox-testing" in result["agent_hint"]
    assert "start-work" not in result["agent_hint"]


def test_parse_result_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match=r"mode must be"):
        run_parse_result(BRANCH_RESPONSE, mode="wander")


def test_implement_mode_forwards_phase_scope_to_implement_plan() -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="177", phases="1-2")

    assert "/implement-plan 177 phases 1-2" in result["agent_hint"]
    assert "Implement ONLY phase(s) 1-2 and stop" in result["agent_hint"]


def test_implement_mode_forwards_phase_scope_without_task_number() -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="", phases="3")

    assert "implementation-plan.md phases 3" in result["agent_hint"]


@pytest.mark.parametrize("phases", ["1", "1-2", "1,3", "2, 4"])
def test_phases_accepts_digit_ranges_and_lists(phases: str) -> None:
    result = run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="9", phases=phases)

    assert f"phases {phases}" in result["agent_hint"]


@pytest.mark.parametrize("phases", ["one", "1;2", "$(rm)", "1'2", 'phase"1'])
def test_phases_rejects_unsafe_values(phases: str) -> None:
    with pytest.raises(ValueError, match=r"phases must contain only"):
        run_parse_result(BRANCH_RESPONSE, mode="implement", issue_number="9", phases=phases)


def test_phases_requires_implement_mode() -> None:
    with pytest.raises(ValueError, match=r"phases only applies when mode=implement"):
        run_parse_result(BRANCH_RESPONSE, mode="explore", phases="1-2")
