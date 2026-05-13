#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Bug 10 baseline: seed an older successful trace + a newer failed trace for
# the same workflow. Auto-load must prefer the older success over the newer
# failed; a Notes line names both files.
mkdir -p "$BASELINE_HOME/.pflow/debug"
python3 - <<'PY'
import hashlib, json, os
src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
wf_path = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
debug = os.environ["BASELINE_HOME"] + "/.pflow/debug"
# Autoload globs by the md5 hash prefix of the workflow_path; the filename
# must encode it or the trace is invisible to ``_autoload_trace``.
wf_hash = hashlib.md5(wf_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

src_data = json.load(open(src))
# Older success — earlier timestamp wins sort tiebreaks; final_status=success.
older = dict(src_data)
older["workflow_path"] = wf_path
older["final_status"] = "success"
older["start_time"] = "2026-05-08T15:32:00"
json.dump(older, open(f"{debug}/workflow-trace-{wf_hash}-smoke-with-cache-20260508-153200.json", "w"))

# Newer failed — later timestamp; final_status=failed.
newer = dict(src_data)
newer["workflow_path"] = wf_path
newer["final_status"] = "failed"
newer["start_time"] = "2026-05-08T16:30:00"
newer["failed_node_ids"] = ["echo"]
json.dump(newer, open(f"{debug}/workflow-trace-{wf_hash}-smoke-with-cache-20260508-163000.json", "w"))
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
