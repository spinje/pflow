#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

normalize_case_output() {
  sed -E \
    -e 's/[0-9]+ms/<DURATION>/g' \
    -e 's/[0-9]+\.[0-9]+s/<DURATION>/g' \
    -e 's/workflow-trace-[a-f0-9]{8}-/workflow-trace-<HASH>-/g'
}

# Seed a full report first so the later --only run has a stale downstream
# page to remove. Without this setup, the case only proves partial report
# creation, not coherent snapshot replacement.
uv run pflow "$BASELINE_CASE_DIR/workflow.pflow.md" --report >/dev/null 2>/dev/null || exit $?

REPORT="$BASELINE_HOME/.pflow/reports/workflow"
if [[ ! -f "$REPORT/02-second.md" ]]; then
  echo "setup failed: full report did not create 02-second.md" >&2
  exit 2
fi

uv run pflow "$BASELINE_CASE_DIR/workflow.pflow.md" --report --only first \
  2> >(normalize_case_output >&2)

printf '\n--- report files ---\n'
(cd "$REPORT" && find . -maxdepth 1 -type f -name '*.md' | sort)
printf '\n--- summary.md ---\n'
sed -n '1,80p' "$REPORT/summary.md" | normalize_case_output
