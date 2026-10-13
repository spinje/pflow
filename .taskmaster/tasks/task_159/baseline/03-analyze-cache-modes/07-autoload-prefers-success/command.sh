#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Bug 10 baseline: seed an older successful trace + a newer failed trace for
# the same workflow. Auto-load must prefer the older success over the newer
# failed; a Notes line names both files.
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

src_data = load_trace_file(Path(src))
# Older success — earlier timestamp wins sort tiebreaks; final_status=success.
older = dict(src_data)
older["workflow_path"] = wf_path
older["final_status"] = "success"
older["start_time"] = "2026-05-08T15:32:00"
older["execution_id"] = "older-success"
name = trace_filename(wf_path, "smoke-with-cache", datetime(2026, 5, 8, 15, 32), "older-success")
write_trace_jsonl(Path(f"{debug}/{name}"), older)

# Newer failed — later timestamp; final_status=failed.
newer = dict(src_data)
newer["workflow_path"] = wf_path
newer["final_status"] = "failed"
newer["start_time"] = "2026-05-08T16:30:00"
newer["failed_node_ids"] = ["echo"]
newer["execution_id"] = "newer-failed"
name = trace_filename(wf_path, "smoke-with-cache", datetime(2026, 5, 8, 16, 30), "newer-failed")
write_trace_jsonl(Path(f"{debug}/{name}"), newer)
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
