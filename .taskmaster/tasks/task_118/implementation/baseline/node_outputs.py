"""Task 118 PC gate: dump every node's stdout / stderr / exit_code from a real run's trace.

The workflow result alone does not see every converted step (``document-processor``'s
``combine`` never reaches it), so each workflow of the named runnable set runs as
``pflow --output-format json <file> k=v`` in a fresh HOME and a fresh cwd, and the run's
trace is walked — batch items, loop iterations and sub-workflow steps included, the
``command`` excluded (it is what the conversion changes).

    uv run python .taskmaster/tasks/task_118/implementation/baseline/node_outputs.py <out-dir>

Writes ``<out-dir>/<slug>.json`` per workflow; compare two dumps with ``diff -r``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pflow.core.trace_io import load_trace_file

REPO = Path(__file__).resolve().parents[5]

# The plan's P0 runnable set: the six templated-shell examples in Task 170's capture.py
# (same params) plus document-processor (P0's hand capture params).
RUNS: tuple[tuple[str, dict[str, str]], ...] = (
    ("examples/bundling/sub-echo.pflow.md", {"text": "hello"}),
    ("examples/core/stdin-echo.pflow.md", {"data": "hello"}),
    ("examples/core/stdout-result.pflow.md", {}),
    ("examples/core/stateful-loop-tournament.pflow.md", {}),
    ("examples/nested/to-uppercase.pflow.md", {"text": "hello"}),
    ("examples/test-nested-index.pflow.md", {}),
    ("examples/nested/document-processor.pflow.md", {"title": "Hello World", "body": "it's a body"}),
)
FIELDS = ("stdout", "stderr", "exit_code")


def _records(event: dict[str, Any], path: str, out: list[dict[str, Any]]) -> None:
    output = event.get("node_output") or {}
    record: dict[str, Any] = {"path": path, "status": event.get("status")}
    if (iteration := event.get("iteration")) is not None:
        record["iteration"] = iteration
    record.update({key: output[key] for key in FIELDS if key in output})
    out.append(record)
    for position, item in enumerate(event.get("batch_items") or []):
        _records(item, f"{path}[{item.get('index', position)}]", out)
    for child in event.get("sub_workflow_events") or []:
        _records(child, f"{path}/{child.get('node_id')}", out)


def dump(example: str, params: dict[str, str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="t118-home-") as home, tempfile.TemporaryDirectory(prefix="t118-cwd-") as cwd:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PFLOW_") or k == "PFLOW_BASH"}
        env.update({"HOME": home, "USERPROFILE": home})
        env.pop("PYTEST_CURRENT_TEST", None)
        args = ["uv", "run", "--project", str(REPO), "pflow", "--output-format", "json", str(REPO / example)]
        args += [f"{k}={v}" for k, v in params.items()]
        proc = subprocess.run(  # noqa: S603 - fixed argv
            args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300, check=False
        )
        traces = sorted((Path(home) / ".pflow" / "debug").glob("workflow-trace-*.json"))
        records: list[dict[str, Any]] = []
        if traces:
            for event in load_trace_file(traces[-1])["nodes"]:
                _records(event, str(event.get("node_id")), records)
        text = json.dumps({"exit_code": proc.returncode, "nodes": records}, indent=2, sort_keys=True)
        for old, new in ((str(Path(cwd).resolve()), "<CWD>"), (cwd, "<CWD>"), (str(Path(home).resolve()), "<HOME>"), (home, "<HOME>"), (str(REPO), "<REPO>")):
            text = text.replace(old, new)
        result: dict[str, Any] = json.loads(text)
        return result


def main() -> int:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for example, params in RUNS:
        result = dump(example, params)
        slug = example.removeprefix("examples/").removesuffix(".pflow.md").replace("/", "__")
        (out_dir / f"{slug}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{example}: exit {result['exit_code']}, {len(result['nodes'])} node records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
