#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Bug 10 cousin: only failed traces exist for this workflow. Auto-load picks
# the newest failed trace and discloses the lack of successful evidence so
# the agent knows to re-run or pass --from-trace.
mkdir -p "$BASELINE_HOME/.pflow/debug"
uv run python - <<'PY'
import hashlib, os
from pathlib import Path

from pflow.core.trace_io import load_trace_file
from tests.shared.trace_jsonl import write_trace_jsonl

src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
wf_path = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
debug = os.environ["BASELINE_HOME"] + "/.pflow/debug"
# Autoload globs by the md5 hash prefix of the workflow_path; the filename
# must encode it or the trace is invisible to ``_autoload_trace``.
wf_hash = hashlib.md5(wf_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
data = dict(load_trace_file(Path(src)))
data["workflow_path"] = wf_path
data["final_status"] = "failed"
data["start_time"] = "2026-05-08T16:30:00"
data["failed_node_ids"] = ["echo"]
write_trace_jsonl(Path(f"{debug}/workflow-trace-{wf_hash}-smoke-with-cache-20260508-163000.json"), data)
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
