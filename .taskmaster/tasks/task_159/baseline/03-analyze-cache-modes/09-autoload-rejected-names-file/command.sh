#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Bug 1 baseline: an auto-loaded trace is structurally rejected because none
# of its root LLM events match the current IR's root LLM node IDs (workflow
# was edited after the trace was recorded). The rejection Notes line must
# name the rejected file + its final_status so the agent knows which trace
# was attempted.
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
data = load_trace_file(Path(src))
data["workflow_path"] = wf_path
data["final_status"] = "success"
data["start_time"] = "2026-05-08T15:32:00"
# Simulate "workflow was renamed since the trace was recorded": none of the
# trace's root LLM events match the current IR's ``answer-a`` / ``answer-b``.
for node in data["nodes"]:
    if node.get("node_id") == "answer-a":
        node["node_id"] = "outdated-answer-a"
    elif node.get("node_id") == "answer-b":
        node["node_id"] = "outdated-answer-b"
data["execution_id"] = "renamed-steps"
name = trace_filename(wf_path, "smoke-with-cache", datetime(2026, 5, 8, 15, 32), "renamed-steps")
write_trace_jsonl(Path(f"{debug}/{name}"), data)
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
