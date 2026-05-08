#!/usr/bin/env bash
# Re-runs every case and DIFFS against committed expected-*.txt.
# Drift = a regression OR an intentional behavior change. Either way: STOP.
#
# Usage:
#   ./verify.sh                    # all cases
#   ./verify.sh 01-parser-errors   # one surface
#
# Exit code: 0 if all pass, 1 if any drift, 2 if any harness error.
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
  exit 2
fi

pass=0
drift=0
errors=0
declare -a drifted=()

while IFS= read -r cmd; do
  case_dir=$(dirname "$cmd")
  rel=${case_dir#$BASELINE_DIR/}
  out=$("$BASELINE_DIR/run-case.sh" "$case_dir" --diff 2>&1)
  rc=$?
  if [[ $rc -eq 0 ]]; then
    printf 'PASS  %s\n' "$rel"
    pass=$((pass + 1))
  elif [[ $rc -eq 1 ]]; then
    printf 'DRIFT %s\n' "$rel"
    printf '%s\n' "$out" | sed 's/^/      /'
    drifted+=("$rel")
    drift=$((drift + 1))
  else
    printf 'ERROR %s\n' "$rel"
    printf '%s\n' "$out" | sed 's/^/      /'
    errors=$((errors + 1))
  fi
done <<< "$cases"

echo
echo "summary: $pass passed, $drift drifted, $errors harness errors"
if [[ $drift -gt 0 ]]; then
  echo "drifted cases:"
  for c in "${drifted[@]}"; do echo "  $c"; done
fi

if [[ $errors -gt 0 ]]; then exit 2; fi
if [[ $drift -gt 0 ]]; then exit 1; fi
exit 0
