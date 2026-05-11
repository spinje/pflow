#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
ESCAPED=$(
  python3 -c "import json,sys; print(json.dumps({'core_idea': 'tiny idea', 'title': 'tiny title', 'body': open(sys.argv[1]).read()}))" \
    "$BASELINE_DIR/_shared/long-stable-text.txt"
)
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --no-trace-autoload concept="$ESCAPED"
