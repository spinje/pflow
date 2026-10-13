#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Bug 10 cousin: only failed traces exist for this workflow. Auto-load picks
# the newest failed trace and discloses the lack of successful evidence so
# the agent knows to re-run or pass --from-trace.
mkdir -p "$BASELINE_HOME/.pflow/debug"
uv run python - <<'PY'
import os
from datetime import datetime
from pathlib import Path

from pflow.core.trace_dir import trace_filename
from pflow.core.trace_io import load_trace_file
from tests.shared.trace_jsonl import write_trace_jsonl

src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
wf_path = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
debug = os.environ["BASELINE_HOME"] + "/.pflow/debug"
# Autoload lists the workflow's traces by the hash and run id the producer's filename carries
# (core/trace_dir.trace_filename); a name without them is invisible to ``_autoload_trace``.
data = dict(load_trace_file(Path(src)))
data["workflow_path"] = wf_path
data["final_status"] = "failed"
data["start_time"] = "2026-05-08T16:30:00"
data["failed_node_ids"] = ["echo"]
data["execution_id"] = "failed-only"
name = trace_filename(wf_path, "smoke-with-cache", datetime(2026, 5, 8, 16, 30), "failed-only")
write_trace_jsonl(Path(f"{debug}/{name}"), data)
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
