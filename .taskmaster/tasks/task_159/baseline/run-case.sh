#!/usr/bin/env bash
# Per-case runner. Used by regenerate.sh (write mode) and verify.sh (diff mode).
#
# Usage: run-case.sh <case-dir> [--write|--diff]
#   --write  (default): captures normalized output to expected-*.txt
#   --diff           : re-runs and diffs against committed expected-*.txt
#
# Always exits with the case's actual exit code on success/failure detection.
# In --diff mode, exits 0 if zero drift, 1 if drift, 2 if the case crashed
# unexpectedly (i.e. case command itself errored before producing output).
set -uo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <case-dir> [--write|--diff]" >&2
  exit 2
fi

CASE_DIR=$(cd "$1" && pwd)
MODE="${2:---write}"
BASELINE_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$BASELINE_DIR/../../../.." && pwd)

export BASELINE_DIR
export BASELINE_CASE_DIR="$CASE_DIR"
export BASELINE_HOME="$CASE_DIR/.run-home"
export BASELINE_REPO_ROOT="$REPO_ROOT"

rm -rf "$BASELINE_HOME"
mkdir -p "$BASELINE_HOME/.pflow/debug" "$BASELINE_HOME/.pflow/cache" "$BASELINE_HOME/.pflow/workflows"

if [[ ! -f "$CASE_DIR/command.sh" ]]; then
  echo "ERROR: $CASE_DIR/command.sh not found" >&2
  exit 2
fi

env -i \
  HOME="$BASELINE_HOME" \
  PATH="$PATH" \
  BASELINE_DIR="$BASELINE_DIR" \
  BASELINE_CASE_DIR="$CASE_DIR" \
  BASELINE_HOME="$BASELINE_HOME" \
  BASELINE_REPO_ROOT="$REPO_ROOT" \
  PFLOW_NO_COLOR=1 \
  NO_COLOR=1 \
  PYTHONHASHSEED=0 \
  TZ=UTC \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  TERM=dumb \
  bash "$CASE_DIR/command.sh" \
  > "$CASE_DIR/.raw-stdout" 2> "$CASE_DIR/.raw-stderr"
RC=$?

NORM_STDOUT=$(BASELINE_HOME="$BASELINE_HOME" BASELINE_CASE_DIR="$CASE_DIR" BASELINE_REPO_ROOT="$REPO_ROOT" \
  python3 "$BASELINE_DIR/normalize.py" < "$CASE_DIR/.raw-stdout")
NORM_STDERR=$(BASELINE_HOME="$BASELINE_HOME" BASELINE_CASE_DIR="$CASE_DIR" BASELINE_REPO_ROOT="$REPO_ROOT" \
  python3 "$BASELINE_DIR/normalize.py" < "$CASE_DIR/.raw-stderr")

rm -f "$CASE_DIR/.raw-stdout" "$CASE_DIR/.raw-stderr"
rm -rf "$BASELINE_HOME"

if [[ "$MODE" == "--write" ]]; then
  # Empty content → empty file (matches what pre-commit's trailing-whitespace
  # hook produces). Non-empty content → exactly one trailing newline (keeps
  # end-of-file-fixer happy). Bash command substitution stripped any pre-
  # existing trailing newlines from NORM_*, so this is the canonical writer.
  _write_with_newline() {
    local content="$1" path="$2"
    if [[ -z "$content" ]]; then
      : > "$path"
    else
      printf '%s\n' "$content" > "$path"
    fi
  }
  _write_with_newline "$NORM_STDOUT" "$CASE_DIR/expected-stdout.txt"
  _write_with_newline "$NORM_STDERR" "$CASE_DIR/expected-stderr.txt"
  echo "$RC" > "$CASE_DIR/expected-exit-code.txt"
  exit 0
fi

if [[ "$MODE" == "--diff" ]]; then
  drift=0
  if [[ ! -f "$CASE_DIR/expected-stdout.txt" ]]; then
    echo "MISSING: expected-stdout.txt"
    exit 1
  fi
  # Mirror the writer above: empty → empty stream; non-empty → trailing nl.
  _emit() { [[ -z "$1" ]] || printf '%s\n' "$1"; }
  diff -u <(_emit "$NORM_STDOUT") "$CASE_DIR/expected-stdout.txt" || drift=1
  diff -u <(_emit "$NORM_STDERR") "$CASE_DIR/expected-stderr.txt" || drift=1
  expected_rc=$(cat "$CASE_DIR/expected-exit-code.txt" 2>/dev/null || echo "MISSING")
  if [[ "$RC" != "$expected_rc" ]]; then
    echo "EXIT-CODE-DRIFT: expected=$expected_rc actual=$RC"
    drift=1
  fi
  exit "$drift"
fi

echo "ERROR: unknown mode $MODE" >&2
exit 2
