#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
ESCAPED=$(python3 -c "
import json, sys, os
text = open(os.environ['BASELINE_DIR'] + '/_shared/long-stable-text.txt').read()
print(json.dumps({
    'core_idea': text,
    'title': 'Test concept',
    'details': {
        'body': text,
        'subtitle': 'Test subtitle'
    }
}))
")
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --no-trace-autoload --format=json concept="$ESCAPED"
