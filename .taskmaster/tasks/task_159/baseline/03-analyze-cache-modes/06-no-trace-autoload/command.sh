#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Seed a matching trace so auto-load WOULD fire if the flag didn't suppress it.
mkdir -p "$BASELINE_HOME/.pflow/debug"
python3 - <<'PY'
import json, os
src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
dst = os.environ["BASELINE_HOME"] + "/.pflow/debug/workflow-trace-deadbeef-smoke-with-cache-20260101-000000.json"
d = json.load(open(src))
d["workflow_path"] = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
json.dump(d, open(dst, "w"))
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  --no-trace-autoload context="x"
