"""Task 185 P5 benchmark: build a 30k-file synthetic trace directory in an ISOLATED home, or check it.

    uv run python .taskmaster/tasks/task_185/implementation/bench/build_bench.py build HOME
    uv run python .taskmaster/tasks/task_185/implementation/bench/build_bench.py check HOME

`build` writes HOME/.pflow/debug (refuses the real home and a non-empty debug dir):
- two REAL runs through `uv run pflow` (HOME isolated, PFLOW_TRACE_RETENTION_DAYS=0, provider keys unset):
  a gated workflow that pauses (its trace + `.paused` marker) and a two-step workflow run in full (the
  `--only` Snapshot);
- 1,000 young failed runs (all within 7 days) of one more real workflow (the busy identity) plus five aged
  successes;
- 2,500 workflow hashes in all; 250 of their workflow files exist (the rest are "deleted"), the newest
  runs spread over 0-60 days;
- one `--only` trace; half of the 30,000 files under the pre-185 (legacy) grammar, aged 15-300 days.
Current-grammar names come from `trace_dir.trace_filename`; legacy names are written by hand.
`build` also writes HOME/bench-manifest.json: the ids to time against and the traces Retention must keep.
`check` reports which of those protected traces are missing (run it after a sweep).
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from pflow.core.trace_dir import paused_marker, trace_filename, workflow_hash
from pflow.runtime.workflow_trace import TRACE_FORMAT_VERSION

TOTAL = 30_000
WORKFLOWS = 2_500
PRESENT_FILES = 250
BUSY_YOUNG_FAILURES = 1_000

GATE = """# Gate

Two steps; the second needs approval.

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```

### two

Second, gated.

- type: shell
- approval: required

```shell command
echo two-value
```
"""

SNAP = """# Snap

Two steps.

## Steps

### fetch

First.

- type: shell

```shell command
echo fetched
```

### shape

Second.

- type: shell

```shell command
echo shaped
```
"""


def pflow_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(HOME=str(home), USERPROFILE=str(home), PFLOW_TRACE_RETENTION_DAYS="0")
    return env


def real_run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, the repo's own CLI
        ["uv", "run", "pflow", "--output-format", "json", *args],  # noqa: S607
        env=pflow_env(home),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def lines(path: str | None, execution_id: str, started: datetime, status: str, *, only: bool = False) -> str:
    meta = {
        "kind": "meta",
        "pflow_trace": "jsonl/1",
        "format_version": TRACE_FORMAT_VERSION,
        "execution_id": execution_id,
        "workflow_name": "bench",
        "workflow_path": path,
        "start_time": started.isoformat(),
        "only_node": "a" if only else None,
        "inputs": {},
        "resumed_from": None,
    }
    event = {
        "kind": "event",
        "node_id": "a",
        "node_type": "ShellNode",
        "status": "failed" if status == "failed" else "success",
        "duration_ms": 1.0,
        "node_output": {"stdout": "x", "exit_code": 1 if status == "failed" else 0},
        "id": 0,
        "seq": 0,
        "parent_id": None,
        "ancestor_path": [],
        "port": None,
    }
    out = [meta, event]
    if status != "incomplete":
        out.append({
            "kind": "run.complete",
            "execution_id": execution_id,
            "final_status": status,
            "nodes_executed": 1,
            "nodes_failed": int(status == "failed"),
            "failed_node_ids": ["a"] if status == "failed" else [],
        })
    return "".join(json.dumps(line) + "\n" for line in out)


def write_current(debug: Path, path: str, started: datetime, status: str, *, only: bool = False) -> Path:
    execution_id = str(uuid.uuid4())
    trace = debug / trace_filename(path, "bench", started, execution_id, only=only)
    trace.write_text(lines(path, execution_id, started, status, only=only), encoding="utf-8")
    return trace


def build(home: Path) -> None:
    if home.resolve() == Path(os.path.expanduser("~")).resolve() or (home / ".pflow" / "debug").exists() and any(
        (home / ".pflow" / "debug").iterdir()
    ):
        sys.exit("refusing: HOME must be an isolated, empty home")
    rng = random.Random(185)
    now = datetime.now()
    debug = home / ".pflow" / "debug"
    debug.mkdir(parents=True, exist_ok=True)
    wf_dir = home / "workflows"
    wf_dir.mkdir(exist_ok=True)

    gate = wf_dir / "gate.pflow.md"
    gate.write_text(GATE, encoding="utf-8")
    snap = wf_dir / "snap.pflow.md"
    snap.write_text(SNAP, encoding="utf-8")
    paused = real_run(home, str(gate))
    paused_doc = json.loads(paused.stdout)
    assert paused_doc["status"] == "paused", paused.stdout + paused.stderr
    full = real_run(home, str(snap))
    full_doc = json.loads(full.stdout)
    assert full_doc["status"] == "success", full.stdout + full.stderr

    keep: list[str] = [paused_doc["trace_path"], str(paused_marker(Path(paused_doc["trace_path"]))), full_doc["trace_path"]]

    busy = wf_dir / "busy.pflow.md"
    busy.write_text(SNAP, encoding="utf-8")
    for n in range(5):  # aged successes behind the young failures: the newest of them is the Snapshot
        trace = write_current(debug, str(busy), now - timedelta(days=30 + n), "success")
        if n == 0:
            keep.append(str(trace))
    # Every young failure stays well inside a 14-day window (10 minutes apart: the oldest is ~7 days old), so the
    # second sweep really faces 1,000 young runs it must not read; all of them are kept by age.
    young = [
        write_current(debug, str(busy), now - timedelta(minutes=1 + 10 * n), "failed")
        for n in range(BUSY_YOUNG_FAILURES)
    ]
    keep.extend(str(trace) for trace in young)

    paths: list[str] = []
    for i in range(WORKFLOWS - 3):  # gate, snap and busy are three of the 2,500
        path = wf_dir / f"wf-{i}.pflow.md"
        if i < PRESENT_FILES:
            path.write_text(SNAP, encoding="utf-8")
        paths.append(str(path))
    write_current(debug, paths[0], now - timedelta(days=20), "success", only=True)  # the one --only trace

    current_budget = TOTAL // 2 - len(list(debug.iterdir()))
    per_workflow: dict[str, list[tuple[datetime, str, Path]]] = {}
    for n in range(current_budget):
        path = paths[n % len(paths)]
        started = now - timedelta(days=rng.uniform(0, 60), seconds=n)
        status = rng.choices(["success", "failed", "incomplete"], weights=[85, 10, 5])[0]
        trace = write_current(debug, path, started, status)
        per_workflow.setdefault(path, []).append((started, status, trace))
    for path, runs in per_workflow.items():
        if not Path(path).exists():
            continue
        runs.sort(reverse=True)
        keep.append(str(runs[0][2]))  # rule 3: the newest run
        success = next((trace for _, status, trace in runs if status == "success"), None)
        if success is not None:
            keep.append(str(success))  # rule 2 (the newest success; the sweep may keep an extra aged one)

    for n in range(TOTAL - len(list(debug.iterdir()))):  # legacy names: aged 15-300 days
        path = paths[n % len(paths)]
        started = now - timedelta(days=rng.uniform(15, 300), seconds=n)
        name = f"workflow-trace-{workflow_hash(path)}-bench-{started.strftime('%Y%m%d-%H%M%S')}.json"
        (debug / name).write_text(lines(path, str(uuid.uuid4()), started, "success"), encoding="utf-8")

    manifest = {
        "paused_id": paused_doc["execution_id"],
        "snapshot_workflow": str(snap),
        "snapshot_step": "shape",
        "busy_workflow": str(busy),
        "keep": keep,
        "files": len(list(debug.iterdir())),
    }
    (home / "bench-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "keep"} | {"keep": len(keep)}))


def check(home: Path) -> None:
    manifest = json.loads((home / "bench-manifest.json").read_text(encoding="utf-8"))
    missing = [path for path in manifest["keep"] if not Path(path).exists()]
    print(json.dumps({"files": len(list((home / ".pflow" / "debug").iterdir())), "protected": len(manifest["keep"]),
                      "missing": missing}))
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    command, home_arg = sys.argv[1], Path(sys.argv[2]).resolve()
    build(home_arg) if command == "build" else check(home_arg)
