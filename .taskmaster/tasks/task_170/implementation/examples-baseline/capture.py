"""Task 170 examples baseline: run every no-API-key example, normalize, store or diff.

    uv run python .taskmaster/tasks/task_170/implementation/examples-baseline/capture.py          # capture
    uv run python .taskmaster/tasks/task_170/implementation/examples-baseline/capture.py --check  # diff vs stored

Each example runs as `pflow --output-format json <file> [k=v ...]` in a fresh HOME
(no memo cache, no settings, no traces leaking between runs) and a fresh cwd
(file-writing examples write there). Normalized fields: every `duration_ms` and
`node_timings` value → 0; every UUID (execution ids) → `<UUID>`; the repo root → `<REPO>`; the run's cwd → `<CWD>`; the
run's HOME → `<HOME>`. `manifest.json` records example → params → exit code →
output file. `--check` exits 1 and prints a unified diff on any difference.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]

# (example path relative to the repo, CLI params). Chosen: every example whose
# node types (sub-workflows included) need no API key, no network, and no MCP
# server; required inputs get fixed values.
EXAMPLES: tuple[tuple[str, dict[str, str]], ...] = (
    ("examples/bundling/command-ref.pflow.md", {}),
    ("examples/bundling/parent-with-sub.pflow.md", {"input": "hello"}),
    ("examples/bundling/simple.pflow.md", {}),
    ("examples/bundling/sub-echo.pflow.md", {"text": "hello"}),
    ("examples/core/conditional-branching.pflow.md", {}),
    ("examples/core/error-handling.pflow.md", {}),
    ("examples/core/minimal.pflow.md", {}),
    ("examples/core/proxy-mappings.pflow.md", {}),
    ("examples/core/simple-pipeline.pflow.md", {}),
    ("examples/core/stateful-loop-judge-round.pflow.md", {"contenders": '["a", "b", "c", "d"]'}),
    ("examples/core/stateful-loop-tournament.pflow.md", {}),
    ("examples/core/stdin-echo.pflow.md", {"data": "hello"}),
    ("examples/core/stdout-result.pflow.md", {}),
    ("examples/error-handling/coalesce-mixed-absent-failed.pflow.md", {}),
    ("examples/error-handling/failed-node-direct-reference.pflow.md", {}),
    ("examples/error-handling/loop-recovery.pflow.md", {}),
    ("examples/error-handling/non-retriable-file-error.pflow.md", {}),
    ("examples/error-handling/retry-with-backoff.pflow.md", {}),
    ("examples/error-handling/source-line-heavy-offsets.pflow.md", {}),
    ("examples/error-handling/source-line-multi-output.pflow.md", {}),
    ("examples/error-handling/typo-on-failed-node.pflow.md", {}),
    ("examples/file-references/code-file-ref.pflow.md", {"input": "hello"}),
    ("examples/file-references/command-file-ref.pflow.md", {}),
    ("examples/file-references/no-file-refs.pflow.md", {}),
    ("examples/invalid/code-annotation-type-mismatch.pflow.md", {}),
    ("examples/invalid/code-missing-result-annotation.pflow.md", {}),
    ("examples/nested/to-uppercase.pflow.md", {"text": "hello"}),
    ("examples/simple-workflow.pflow.md", {}),
    ("examples/test-nested-index.pflow.md", {}),
)


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _normalize(value: Any, key: str | None, subs: tuple[tuple[str, str], ...]) -> Any:
    if isinstance(value, dict):
        if key == "node_timings":
            return {k: 0 for k in value}
        return {k: _normalize(v, k, subs) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v, key, subs) for v in value]
    if key is not None and key.endswith("duration_ms") and isinstance(value, (int, float)):
        return 0
    if isinstance(value, str):
        for old, new in subs:
            value = value.replace(old, new)
        value = _UUID.sub("<UUID>", value)
    return value


def run_one(example: str, params: dict[str, str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="t170-home-") as home, tempfile.TemporaryDirectory(
        prefix="t170-cwd-"
    ) as cwd:
        # Drop inherited PFLOW_* behavior switches (e.g. PFLOW_TEMPLATE_RESOLUTION_MODE,
        # PFLOW_MAX_NODE_VISITS) so a caller's shell cannot change the outputs; keep
        # PFLOW_BASH, which only locates bash on Windows.
        env = {k: v for k, v in os.environ.items() if not k.startswith("PFLOW_") or k == "PFLOW_BASH"}
        env.update({"HOME": home, "USERPROFILE": home})
        env.pop("PYTEST_CURRENT_TEST", None)
        args = ["uv", "run", "--project", str(REPO), "pflow", "--output-format", "json", str(REPO / example)]
        args += [f"{k}={v}" for k, v in params.items()]
        proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        subs = ((str(Path(cwd).resolve()), "<CWD>"), (cwd, "<CWD>"), (str(Path(home).resolve()), "<HOME>"),
                (home, "<HOME>"), (str(REPO), "<REPO>"))
        try:
            payload: Any = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"__unparsed_stdout__": proc.stdout}
        text = json.dumps(_normalize(payload, None, subs), indent=2, sort_keys=True) + "\n"
        return proc.returncode, text


def _slug(example: str) -> str:
    return example.removeprefix("examples/").removesuffix(".pflow.md").replace("/", "__") + ".json"


def main() -> int:
    check = "--check" in sys.argv
    manifest: list[dict[str, Any]] = []
    stored = json.loads((HERE / "manifest.json").read_text(encoding="utf-8")) if check else []
    stored_codes = {entry["example"]: entry["exit_code"] for entry in stored}
    failures = 0
    for example, params in EXAMPLES:
        code, text = run_one(example, params)
        out = HERE / _slug(example)
        manifest.append({"example": example, "params": params, "exit_code": code, "output": out.name})
        if check:
            old = out.read_text(encoding="utf-8")
            if old != text or stored_codes.get(example) != code:
                failures += 1
                print(f"DIFF {example} (exit {stored_codes.get(example)} -> {code})")
                sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), text.splitlines(True), "before", "after"))
            else:
                print(f"same {example}")
        else:
            out.write_text(text, encoding="utf-8")
            print(f"captured {example} (exit {code})")
    if not check:
        (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(EXAMPLES)} examples, {failures} differing")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
