#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

TRACE="$BASELINE_DIR/_shared/fixtures/live-gemini-translation.trace.json"
REPORT="$BASELINE_HOME/report"

uv run pflow report "$TRACE" -o "$REPORT"
printf '\n--- summary.md ---\n'
sed -n '1,80p' "$REPORT/summary.md"
printf '\n'
REPORT_PAGE="$REPORT/01-answer-a.md" python3 - <<'PY'
import os
import sys
from pathlib import Path

page = Path(os.environ["REPORT_PAGE"])
text = page.read_text()
required_sections = [
    "## Cached System",
    "## Cache telemetry",
    "## Prompt",
    "## Response",
]
missing = [section for section in required_sections if section not in text]
if missing:
    print(f"missing report sections: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)

print("--- 01-answer-a.md ---")
for line in text.splitlines():
    if line.strip().startswith('"text": '):
        indent = line[: len(line) - len(line.lstrip())]
        print(f'{indent}"text": "<cached system text elided: live trace contains long stable reference>",')
    else:
        print(line)
PY
