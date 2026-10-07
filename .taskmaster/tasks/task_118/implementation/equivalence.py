"""Task 118 PC gate: does a converted shell step hand its commands what the old form did?

For every shell step under ``examples/`` whose body changed between ``git HEAD`` (the
merge base) and the working tree: the OLD body is resolved with pflow's ``resolve()``
over a sample context; the NEW step's ``env:`` is bound over the same context with
``bind_env`` (``to_string`` per value). Both run under ``/bin/sh`` with a stub ``PATH``
in which every external command prints its name, its argv and its stdin, so the
transcript shows exactly what each command received. Two passes:

* benign — values with spaces: the transcripts must be identical;
* hostile — values like ``it's "q" $5 \\ back``: the NEW transcript must carry every
  value intact; an OLD/NEW difference is expected wherever the old form pasted the
  value into sh text (word splitting, quotes, ``$`` expansion) and is reported.

``git-worktree-task-creator`` is the hand case: its ``parse-result`` code changed too
(the heredoc escaping layer is gone), so each side's ``parse-result.result`` comes from
running that side's own code on the same description, and ``launch-cli`` runs with a
real worktree directory so the ``osascript`` branch (stubbed) is exercised.

    uv run python .taskmaster/tasks/task_118/implementation/equivalence.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pflow.core.markdown_parser import parse_markdown
from pflow.core.templates import DynamicIndex, Field, Index, Reference, parse, resolve
from pflow.nodes.shell.env_binding import bind_env

REPO = Path(__file__).resolve().parents[4]
WORKTREE_CREATOR = "examples/real-workflows/git-worktree-task-creator/workflow.pflow.md"
EXTERNALS = (
    "awk basename cat cp curl date dirname git gh grep head jq mkdir mktemp mv open osascript "
    "python3 rm sed sleep sort tail touch tr wc yt-dlp find"
).split()
STDIN_TEXT = "line one\nline two\n"


def changed_examples() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "examples/"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split() if p.endswith(".pflow.md")]


def shell_nodes(text: str) -> dict[str, dict[str, Any]]:
    ir = parse_markdown(text).ir
    return {n["id"]: n for n in ir["nodes"] if n.get("type") == "shell"}


def _set_path(ctx: dict[str, Any], ref: Reference, leaf: Any) -> None:
    """Make ``ref`` resolvable in ``ctx`` with ``leaf`` at its end (lists padded as needed)."""
    if not ref.path:
        ctx.setdefault(ref.root, leaf)
        return
    if not isinstance(ctx.get(ref.root), (dict, list)):
        ctx[ref.root] = [] if isinstance(ref.path[0], (Index, DynamicIndex)) else {}
    cur: Any = ctx[ref.root]
    for pos, seg in enumerate(ref.path):
        last = pos == len(ref.path) - 1
        nxt = ref.path[pos + 1] if not last else None
        empty: Any = leaf if last else ([] if isinstance(nxt, (Index, DynamicIndex)) else {})
        if isinstance(seg, Field):
            if last:
                cur.setdefault(seg.name, leaf)
            elif not isinstance(cur.get(seg.name), (dict, list)):
                cur[seg.name] = empty
            cur = cur[seg.name]
        else:
            index = seg.value if isinstance(seg, Index) else 0
            while len(cur) <= index:
                cur.append(None)
            if cur[index] is None or (not last and not isinstance(cur[index], (dict, list))):
                cur[index] = empty
            cur = cur[index]


def sample_context(texts: list[Any], value_for: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    refs: list[Reference] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            refs.extend(parse(value).references)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    for text in texts:
        collect(text)
    for ref in refs:
        for inner in ref.index_sources:
            ctx[inner.root] = 0
    for ref in refs:
        if ref.root in ("__index__", "__iteration__"):
            ctx[ref.root] = 0
            continue
        _set_path(ctx, ref, value_for(ref.raw))
    return ctx


def stub_dir(root: Path) -> Path:
    stubs = root / "stubs"
    stubs.mkdir()
    for name in EXTERNALS:
        script = stubs / name
        script.write_text(
            "#!/bin/sh\n"
            f"printf '<{name}'; for a in \"$@\"; do printf ' [%s]' \"$a\"; done; printf '>\\n'\n"
            "printf 'stdin{'; /bin/cat; printf '}\\n'\n"
            # stdout of `$(dirname ...)`-style substitutions must be a usable path
            + ('printf "%s\\n" "$1"\n' if name in ("dirname", "basename", "mktemp") else ""),
            encoding="utf-8",
        )
        script.chmod(0o755)
    return stubs


def run(body: str, env: dict[str, str], has_stdin: bool, stubs: Path, cwd: Path) -> str:
    proc = subprocess.run(
        ["/bin/sh", "-c", body],
        env={"PATH": str(stubs), "HOME": str(cwd), **env},
        cwd=cwd,
        input=STDIN_TEXT if has_stdin else "",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return f"exit={proc.returncode}\n--stdout--\n{proc.stdout}--stderr--\n{proc.stderr}"


def parse_result_outputs(text: str, description: str, repo_root: str) -> dict[str, Any]:
    """Run one version's parse-result code (as tests/test_runtime/test_worktree_creator_workflow.py does)."""
    section = text.split("### parse-result", maxsplit=1)[1].split("### create-worktree", maxsplit=1)[0]
    match = re.search(r"```python code\n(?P<code>.*?)\n```", section, re.DOTALL)
    assert match is not None
    namespace: dict[str, Any] = {
        "response": "BRANCH_TYPE=feat\nBRANCH_NAME=equivalence-probe",
        "repo_root": repo_root,
        "current_branch": "main",
        "base_branch": "",
        "description": description,
        "work_type": "task",
        "issue_number": "",
        "title_resolved": False,
        "agent": "claude",
        "model": "",
        "copy_folder": "scratch",
    }
    exec(match.group("code"), namespace)  # noqa: S102 - the example's own code, both versions
    result: dict[str, Any] = namespace["result"]
    return result


def main() -> int:
    findings: list[str] = []
    for rel in changed_examples():
        old_text = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True, text=True, check=True).stdout
        new_text = (REPO / rel).read_text(encoding="utf-8")
        old_nodes, new_nodes = shell_nodes(old_text), shell_nodes(new_text)
        for node_id, new in new_nodes.items():
            old = old_nodes.get(node_id)
            if old is None or old["params"].get("command") == new["params"].get("command"):
                continue
            old_cmd, new_cmd = old["params"]["command"], new["params"]["command"]
            new_env = new["params"].get("env") or {}
            has_stdin = "stdin" in new["params"]
            for mode in ("benign", "hostile"):
                with tempfile.TemporaryDirectory(prefix="t118-eq-") as tmp:
                    root = Path(tmp).resolve()
                    stubs = stub_dir(root)
                    counter = iter(range(1000))

                    def value_for(raw: str, mode: str = mode, counter: Any = counter) -> str:
                        n = next(counter)
                        return f"v{n} with spaces" if mode == "benign" else f"it's \"q\" $5 \\ back {n}"

                    old_ctx = sample_context([old_cmd], value_for)
                    new_ctx = sample_context(list(new_env.values()), lambda raw: None)
                    # Same values on both sides: the NEW env's references read the OLD context's leaves.
                    new_ctx = old_ctx | {k: v for k, v in new_ctx.items() if k not in old_ctx}
                    if rel == WORKTREE_CREATOR:
                        desc = "fix it" if mode == "benign" else "it's \"q\" $5 `id` \\ back"
                        # The worktree path is never escaped for the do-script quoting layers (by
                        # design: parse-result builds it from the repo root), so it stays plain; the
                        # hostile text rides the description, the one value that is escaped.
                        repo_root = str(root / ("repo" if mode == "benign" else "re po"))
                        old_pr = parse_result_outputs(old_text, desc, repo_root)
                        new_pr = parse_result_outputs(new_text, desc, repo_root)
                        Path(new_pr["worktree_path"]).mkdir(parents=True)
                        old_ctx = old_ctx | {"parse-result": {"result": old_pr}, "open_cli": True, "open_cursor": True}
                        new_ctx = new_ctx | {"parse-result": {"result": new_pr}, "open_cli": True, "open_cursor": True}
                        old_ctx["get-repo-root"] = new_ctx["get-repo-root"] = {"stdout": repo_root}
                    old_body = str(resolve(old_cmd, old_ctx).value)
                    bound = bind_env({k: resolve(v, new_ctx).value for k, v in new_env.items()})
                    # A fresh cwd per side: a file one side writes must not change the other's branch.
                    (root / "old").mkdir()
                    (root / "new").mkdir()
                    old_out = run(old_body, {}, has_stdin, stubs, root / "old").replace(str(root / "old"), "<CWD>")
                    new_out = run(new_cmd, bound, has_stdin, stubs, root / "new").replace(str(root / "new"), "<CWD>")
                    old_out, new_out = (t.replace(str(root), "<TMP>") for t in (old_out, new_out))
                    same = old_out == new_out
                    missing = [v for v in bound.values() if mode == "hostile" and v and v.replace(str(root), "<TMP>") not in new_out]
                    status = "same" if same else "DIFF"
                    line = f"{status:4} {mode:7} {rel} :: {node_id}"
                    if missing:
                        line += f"  (values not seen verbatim in NEW: {sorted(bound_name for bound_name, v in bound.items() if v in missing)})"
                    print(line)
                    if not same:
                        findings.append(f"### {mode} {rel} :: {node_id}\n--- OLD\n{old_out}\n--- NEW\n{new_out}")
    if findings:
        print("\n\n".join(["", "==== differences ===="] + findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
