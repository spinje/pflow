#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# Seed a matching trace so auto-load WOULD fire if the flag didn't suppress it.
mkdir -p "$BASELINE_HOME/.pflow/debug"
uv run python - <<'PY'
import os
from pathlib import Path

from pflow.core.trace_io import load_trace_file
from tests.shared.trace_jsonl import write_trace_jsonl

src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
dst = os.environ["BASELINE_HOME"] + "/.pflow/debug/workflow-trace-deadbeef-smoke-with-cache-20260101-000000.json"
d = load_trace_file(Path(src))
d["workflow_path"] = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
write_trace_jsonl(Path(dst), d)
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  --no-trace-autoload context="x"
