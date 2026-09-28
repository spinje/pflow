"""No live file may name a retired Codex runner model.

The runner model name has no single home: it is hard-coded in the asset generator, the worktree
script and both orchestration workflows, and named in prose in ORCHESTRATION.md, AGENTS.md and the
worktree command — ten-plus files once the generated `.codex/` mirrors are counted. A hand-run
`grep` at swap time reliably misses some of them, so the sweep is pinned here instead of being
re-derived by hand at the next model swap.

Three failure modes:

- A retired name survives (or comes back) in a live file. `test_no_live_file_names_a_retired_model`
  scans for it; because a healthy repo makes that assertion pass vacuously,
  `test_detector_reports_a_planted_retired_name` feeds the SAME detector a known-bad file so the
  red case is demonstrated rather than asserted.
- The scan reads nothing and reports clean anyway — a scanner that visits zero files is
  indistinguishable from a clean repo. `test_scan_reaches_the_files_that_name_a_runner_model` is
  the positive control, and it is also the alarm at the NEXT swap: when the current model is
  retired it fails and names this file as the checklist that has to move.
- The searcher's routing VALUE drifts while every name stays right. The effort -> (model,
  reasoning) table lives in a workflow `code` node no other test executes, so a tier quietly
  re-pointed at another model or reasoning level would leave the suite green.
  `test_searcher_effort_routes_to_the_current_model_at_matching_reasoning` runs that node through
  the real `PythonCodeNode`.

Dated records are excluded — task artifacts, session logs and release notes record what a run
actually used, and rewriting them would falsify history. So are scratchpads, which are working
notes rather than references.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pflow.core.markdown_parser import parse_markdown
from pflow.nodes.python.python_code import PythonCodeNode

REPO_ROOT = Path(__file__).resolve().parents[2]

# The model every contract tier currently launches on Codex (ORCHESTRATION.md "Model routing").
CURRENT_MODEL = "gpt-6-astra"

# Assembled from parts so the literals never appear in this file: a scanner that has to skip
# itself has a hole in it, and this is the one file guaranteed to mention every retired name.
RETIRED_MODELS = tuple(f"gpt-5.6-{suffix}" for suffix in ("sol", "terra"))

# Dated records and working notes — never rewritten, so never scanned.
EXCLUDED_PREFIXES = (
    ".taskmaster/tasks/",
    ".taskmaster/orchestration/sessions/",
    "releases/",
    "scratchpads/",
)

# Every live file that names the runner model. The positive control asserts the scan reaches all of
# them AND that each still names the current model.
MODEL_HOMES = (
    "scripts/sync_claude_assets.py",
    "scripts/worktree",
    "workflows/review/run-review-lenses.pflow.md",
    "workflows/search/run-searcher.pflow.md",
    "AGENTS.md",
    ".claude/commands/worktree.md",
    ".taskmaster/orchestration/ORCHESTRATION.md",
)

SEARCHER_WORKFLOW = REPO_ROOT / "workflows/search/run-searcher.pflow.md"


def _is_excluded(name: str) -> bool:
    return name.startswith(EXCLUDED_PREFIXES) or "node_modules/" in name


def live_text_files() -> dict[str, str]:
    """Every tracked or untracked-but-not-ignored file that decodes as text, by repo-relative path.

    Untracked files count: a model name in a file not yet committed is exactly the case a
    pre-commit sweep must catch. Ignored files (`.venv/`, build output) are not the repo's text.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.split("\0")

    files: dict[str, str] = {}
    for name in listed:
        if not name or _is_excluded(name):
            continue
        try:
            files[name] = (REPO_ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary asset, a stale index entry, or a submodule; none carries a model name
    return files


def retired_names_in(files: Mapping[str, str]) -> list[str]:
    """Every `path: model` pair where a scanned file names a retired model.

    Separate from the corpus walk so the detector can be fed a KNOWN-BAD file. Against the live
    repo this returns nothing by design, and a detector that returned nothing for any input would
    look exactly as healthy.
    """
    return sorted(f"{name}: {model}" for name, text in files.items() for model in RETIRED_MODELS if model in text)


def test_scan_reaches_the_files_that_name_a_runner_model() -> None:
    files = live_text_files()

    missing = [home for home in MODEL_HOMES if home not in files]
    assert missing == [], f"scan never reached: {missing}"

    stale = [home for home in MODEL_HOMES if CURRENT_MODEL not in files[home]]
    assert stale == [], (
        f"{stale} no longer name {CURRENT_MODEL!r}. If the runner model changed, add the old name "
        f"to RETIRED_MODELS and update CURRENT_MODEL — this file is the sweep's checklist."
    )


def test_detector_reports_a_planted_retired_name() -> None:
    for model in RETIRED_MODELS:
        planted = {"scripts/worktree": f'      opus|fable) model="{model}" ;;'}

        assert retired_names_in(planted) == [f"scripts/worktree: {model}"]


def test_no_live_file_names_a_retired_model() -> None:
    offenders = retired_names_in(live_text_files())

    assert offenders == [], "retired Codex model names must not survive in live files:\n" + "\n".join(offenders)


def searcher_routing_code() -> str:
    """The searcher workflow's effort-routing `code` node, found by the inputs it declares.

    By its declared inputs, never by its node id: the point is to get hold of the executable code
    and run it, so a renamed node or a stale id cannot pass for it.
    """
    ir = parse_markdown(SEARCHER_WORKFLOW.read_text(encoding="utf-8")).ir
    for node in ir["nodes"]:
        params = node.get("params", {})
        if node["type"] == "code" and {"agent", "cwd", "effort"} <= set(params.get("inputs", {})):
            return str(params["code"])
    raise AssertionError(f"{SEARCHER_WORKFLOW.name} has no code node declaring agent/cwd/effort")


def run_searcher_routing(effort: str) -> dict[str, Any]:
    """Run the routing node through the real code node and return the shared store it wrote."""
    node = PythonCodeNode()
    node.set_params({
        "code": searcher_routing_code(),
        "inputs": {"agent": "pflow-codebase-searcher", "cwd": str(REPO_ROOT), "effort": effort},
    })
    shared: dict[str, Any] = {}
    node.run(shared)
    return shared


@pytest.mark.parametrize("effort", ("low", "medium", "high"))
def test_searcher_effort_routes_to_the_current_model_at_matching_reasoning(effort: str) -> None:
    shared = run_searcher_routing(effort)

    assert "error" not in shared, shared.get("error")
    result = shared["result"]
    assert (result["model"], result["effort"]) == (CURRENT_MODEL, effort)
    assert result["persona"], "the node returned an empty persona — it resolved the wrong file"


def test_searcher_rejects_an_unknown_effort() -> None:
    """Also proves the node above really executed: a no-op body would not raise this."""
    shared = run_searcher_routing("xhigh")

    assert "Unknown effort" in shared["error"]
