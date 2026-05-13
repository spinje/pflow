#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --no-trace-autoload --format=json article=hello
