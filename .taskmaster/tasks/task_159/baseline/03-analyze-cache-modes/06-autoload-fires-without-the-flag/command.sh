#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
# The 06 twin: the SAME seeded trace, no flag — auto-load fires (so 06 proves the flag suppresses a real match).
mkdir -p "$BASELINE_HOME/.pflow/debug"
uv run python - <<'PY'
import os
from pathlib import Path

from datetime import datetime

from pflow.core.trace_dir import trace_filename
from pflow.core.trace_io import load_trace_file
from tests.shared.trace_jsonl import write_trace_jsonl

src = os.environ["BASELINE_DIR"] + "/_shared/fixtures/sample-2.1.0-trace.json"
wf_path = os.environ["BASELINE_DIR"] + "/_shared/workflows/smoke-with-cache.pflow.md"
# The producer's filename (core/trace_dir.trace_filename): the workflow hash and the run id make the
# trace one autoload WOULD read — the 06 twin (06-autoload-fires-without-the-flag) proves it does.
name = trace_filename(wf_path, "smoke-with-cache", datetime(2026, 1, 1), "seeded-run")
d = load_trace_file(Path(src))
d["workflow_path"] = wf_path
d["execution_id"] = "seeded-run"
write_trace_jsonl(Path(os.environ["BASELINE_HOME"] + "/.pflow/debug/" + name), d)
PY
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  context="x"
