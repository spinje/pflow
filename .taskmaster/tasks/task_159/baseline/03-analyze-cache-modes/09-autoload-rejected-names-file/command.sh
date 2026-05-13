#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Bug 1 baseline: an auto-loaded trace is structurally rejected because none
# of its root LLM events match the current IR's root LLM node IDs (workflow
# was edited after the trace was recorded). The rejection Notes line must
# name the rejected file + its final_status so the agent knows which trace
# was attempted.
mkdir -p "$BASELINE_HOME/.pflow/debug"
python3 - <<'PY'
import hashlib, json, os
src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
wf_path = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
debug = os.environ["BASELINE_HOME"] + "/.pflow/debug"
# Autoload globs by the md5 hash prefix of the workflow_path; the filename
# must encode it or the trace is invisible to ``_autoload_trace``.
wf_hash = hashlib.md5(wf_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
data = json.load(open(src))
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
json.dump(data, open(f"{debug}/workflow-trace-{wf_hash}-smoke-with-cache-20260508-153200.json", "w"))
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
