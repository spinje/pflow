# 05 — print mode with --only

**Surface**: 15-run-flag-interactions

**Triggers**: `pflow -p <workflow> --only step-b`.

**Expected behavior**: stdout contains only the target node's output. stderr
still contains the `--only` mode confirmation, with no full progress summary.

**Mutation contract**: if `-p` suppresses the mode signal, or if `--only`
streams full-run declared output instead of the target node output, this case
fails.

