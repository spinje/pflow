#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

# Seed a full run so --only has a prior-run snapshot to restore upstream from.
# Since #443, `--only <node>` hard-errors (OnlySnapshotMissingError) without one;
# this case asserts the `-p --only` print-only streaming signal, so it must seed first.
uv run pflow "$BASELINE_CASE_DIR/workflow.pflow.md" >/dev/null 2>/dev/null || exit $?

uv run pflow -p "$BASELINE_CASE_DIR/workflow.pflow.md" --only step-b
