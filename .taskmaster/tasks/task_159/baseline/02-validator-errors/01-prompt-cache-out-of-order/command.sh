#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow run "$BASELINE_CASE_DIR/workflow.pflow.md" article=hi topic=test
