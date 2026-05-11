#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

uv run pflow -p "$BASELINE_CASE_DIR/workflow.pflow.md" --only step-b
