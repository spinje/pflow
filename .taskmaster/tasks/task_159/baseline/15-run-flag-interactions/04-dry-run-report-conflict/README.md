# 04 — dry-run report conflict

**Surface**: 15-run-flag-interactions

**Triggers**: `pflow <workflow> --dry-run --report`.

**Expected behavior**: The command exits non-zero with a clear error explaining
that reports are generated from execution traces and dry-run performs no
execution.

**Mutation contract**: if `--dry-run --report` silently accepts, generates an
empty report, or emits the error on the wrong surface, this case drifts.

