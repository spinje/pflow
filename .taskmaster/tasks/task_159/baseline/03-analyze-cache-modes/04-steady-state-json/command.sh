#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow analyze-cache "$BASELINE_REPO_ROOT/examples/core/prompt-caching.pflow.md" --no-trace-autoload --format=json article=hello
