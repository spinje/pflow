#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
LONG="This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand. This is a stable reference document about the topic at hand."
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --no-trace-autoload --format=json concept_brief="$LONG"
