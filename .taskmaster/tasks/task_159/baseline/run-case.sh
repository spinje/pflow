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

# Pin the workflow default model deterministically (issue #532). The lyrics-generator /
# song-creator family (surfaces 10/12) is the ONLY baseline workflow set whose LLM nodes
# declare no `- model:` — they rely on the workflow default, and their committed trace
# fixtures are gemini. The ANTHROPIC_API_KEY below (needed for the preflight, see env -i)
# would otherwise make auto-detect resolve that default to anthropic (auto-detect is
# anthropic-priority), so those gemini workflows would report a spurious "trace recorded
# gemini, now anthropic — models differ". Every anthropic-intent workflow pins its model
# explicitly on the node, so a gemini default is cosmetic for them — it never overrides an
# explicit model. settings.default_model wins over auto-detect (core/llm_config.py::
# get_default_workflow_model), making default resolution independent of which keys exist.
printf '%s\n' '{"version": "1.0.0", "llm": {"default_model": "gemini/gemini-2.5-flash"}}' \
  > "$BASELINE_HOME/.pflow/settings.json"

if [[ ! -f "$CASE_DIR/command.sh" ]]; then
  echo "ERROR: $CASE_DIR/command.sh not found" >&2
  exit 2
fi

# Each case runs in a clean-room env (`env -i`) for determinism. Three whitelist
# additions are load-bearing (issue #532):
#   * PYTHONPATH=$REPO_ROOT — lets case heredocs import the canonical JSONL trace
#     helpers (`pflow.core.trace_io.load_trace_file` to read, `tests.shared.trace_jsonl.
#     write_trace_jsonl` to write) regardless of CWD or script-file location, so they
#     read/write the Task-172 JSONL trace format — the ONLY on-disk format since #531.
#   * ANTHROPIC_API_KEY / GEMINI_API_KEY — fixed NON-REAL placeholders (the only two
#     providers the fixtures use; ollama is keyless). Since #439 the validator preflights
#     API-key *presence* at validate-time, and `analyze-cache` runs that validator, so a
#     keyless run gains spurious `## Blocking errors → Missing API key` noise that buries
#     the real signal. They gate ONLY the preflight — default-model resolution is pinned by
#     the seeded settings.json above, so it does not depend on which keys are present. These
#     satisfy the presence check WITHOUT enabling any live call:
#     no baseline case reaches the LLM call seam (all are static analyze-cache / --dry-run
#     / parse-validate errors / shell-only execution). If a case ever DID attempt a real
#     call, a placeholder fails loud with an auth error instead of silently making a
#     billed, non-deterministic call — keeping the oracle honest.
env -i \
  HOME="$BASELINE_HOME" \
  PATH="$PATH" \
  PYTHONPATH="$REPO_ROOT" \
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
  ANTHROPIC_API_KEY="not-a-real-key-baseline-preflight-only" \
  GEMINI_API_KEY="not-a-real-key-baseline-preflight-only" \
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
