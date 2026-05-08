#!/usr/bin/env bash
# Re-runs every case, captures normalized output, OVERWRITES expected-*.txt.
# Use after intentional behavior changes have been reviewed.
#
# Usage:
#   ./regenerate.sh                    # all cases
#   ./regenerate.sh 01-parser-errors   # one surface
#   ./regenerate.sh 04-warning-catalog/01-cache.order-mismatch  # one case
set -uo pipefail
BASELINE_DIR=$(cd "$(dirname "$0")" && pwd)
GLOB="${1:-}"

if [[ -n "$GLOB" ]]; then
  cases=$(find "$BASELINE_DIR/$GLOB" -name 'command.sh' 2>/dev/null | sort)
else
  cases=$(find "$BASELINE_DIR" -name 'command.sh' -not -path '*/.run-home/*' 2>/dev/null | sort)
fi

if [[ -z "$cases" ]]; then
  echo "no cases matched ${GLOB:-<all>}" >&2
  exit 1
fi

count=0
fail=0
while IFS= read -r cmd; do
  case_dir=$(dirname "$cmd")
  rel=${case_dir#$BASELINE_DIR/}
  printf '>>> %s\n' "$rel"
  if ! "$BASELINE_DIR/run-case.sh" "$case_dir" --write; then
    printf '    FAILED to capture (harness error)\n' >&2
    fail=$((fail + 1))
  fi
  count=$((count + 1))
done <<< "$cases"

echo
echo "regenerated $count cases ($fail harness failures)"
[[ $fail -eq 0 ]] || exit 1
