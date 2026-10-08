#!/usr/bin/env bash
# Task 118 PC gate helper: capture every Task-159 baseline case's ACTUAL normalized output
# (stdout, stderr, exit code) into <outdir>/<case>/ — the same clean-room run and
# normalization as task_159/baseline/run-case.sh, but written outside the case dirs, so
# two captures (before / after the conversion) diff actual-vs-actual (`diff -r`) instead
# of against expected files that already drift.
#
# Usage: task159_actual.sh <outdir>
set -uo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
BASELINE_DIR=$(cd "$HERE/../../../task_159/baseline" && pwd)
RUN_CASE="$BASELINE_DIR/run-case.sh"

# Same loop shape as verify.sh (a here-string on stdin, not a pipe): a case's pflow must see
# the same non-pipe stdin it sees under verify.sh, and must not consume the case list.
cases=$(find "$BASELINE_DIR" -name 'command.sh' -not -path '*/.run-home/*' | sort)
while IFS= read -r cmd; do
  case_dir=$(dirname "$cmd")
  rel=${case_dir#$BASELINE_DIR/}
  dest="$OUT/$rel"
  mkdir -p "$dest"
  # run-case.sh --write writes the actual output over expected-*.txt in the case dir (the case
  # must run in place: the CLI prints repo-relative paths). Back the committed files up first,
  # copy the fresh output out, restore the committed bytes.
  bak=$(mktemp -d)
  cp "$case_dir"/expected-stdout.txt "$case_dir"/expected-stderr.txt "$case_dir"/expected-exit-code.txt "$bak/"
  "$RUN_CASE" "$case_dir" --write >/dev/null 2>&1
  for f in stdout.txt stderr.txt exit-code.txt; do
    cp "$case_dir/expected-$f" "$dest/$f"
    cp "$bak/expected-$f" "$case_dir/expected-$f"
  done
  rm -rf "$bak"
  printf '%s\n' "$rel"
done <<< "$cases"
