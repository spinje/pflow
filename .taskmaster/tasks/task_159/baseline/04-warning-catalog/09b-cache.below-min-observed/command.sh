#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
python3 "$BASELINE_DIR/_shared/write_cache_warning_trace.py" observed "$BASELINE_CASE_DIR/workflow.pflow.md" "$BASELINE_CASE_DIR/trace.json"
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --from-trace "$BASELINE_CASE_DIR/trace.json" --format=json
