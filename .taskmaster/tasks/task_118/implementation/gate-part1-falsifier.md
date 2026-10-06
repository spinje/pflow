# Task 118 Part 1 — review-falsifier report (direct launch, last lens, on `cba59617`)

Probes ran through the real CLI with a redirected HOME and a fake `codex` binary (no paid calls).

## Claim ledger (verdicts)
1 typed values bind as decided text, validate-only = run — HOLDS (19 vars: literals, inputs, CLI inputs, upstream, unset optional, `${__index__}`)
2 hostile values + compact JSON intact (#59) — HOLDS (no marker files created)
3 invalid name / oversized / NUL fail before spawn naming the variable, incl. `ignore_errors` and `retry` — HOLDS (spawned: 0, no retry)
3b literal cases caught at validation; validate and run messages identical — HOLDS
3c unencodable text (lone surrogate) fails with the ruled message — FALSIFIED (W1)
4 batch per-item env (parallel, continue, NUL/E2BIG items) — HOLDS
5 changed env value changes the memo key — HOLDS
6 tooling workflows identical old vs converted across 9 cwd cases — HOLDS (a `$`/`"` path: old fails, new succeeds — the #59 fix)
7 nested sub-workflow binding + static checks — HOLDS
8 whole-templated `env: ${x}` — HOLDS
9 single-node probe + MCP single-node run — HOLDS
10 env beside stdin/cwd; POSIX case variant of inherited name — HOLDS
11 resume keeps bound values — HOLDS
12 References and `$${` escapes inside env still Templates — HOLDS
13 literal YAML values — partly FALSIFIED (W2, S1)

## W1 — a lone surrogate never reaches the user as the ruled message
Repro: upstream `printf '%s' '{"s":"cut \ud800"}'`; next shell step `ignore_errors: true`, `env: {DATA: ${up.stdout.s}}`.
Observed: exit 1, `Error: Validation Error` / `'utf-8' codec can't encode character '\ud800' in position 4: surrogates not allowed`; JSON error has no `node_id`.
Root cause (sys.settrace): `ShellNode.prep` raises the correct `EnvBindingError` (`nodes/shell/env_binding.py:177-186`); then `record_trace` (`runtime/engine/engine.py:1706`) → `workflow_trace.py:1012 _flush_line` → `core/trace_io.py:116 value.encode("utf-8")` raises `UnicodeEncodeError`; `_flush_line` catches only `OSError` (`workflow_trace.py:1016`) though its docstring says it must never mask a real node error. Pre-existing trace-writer defect; the command is still not spawned. The integration test `test_an_unbindable_value_under_ignore_errors_and_retry[lone-surrogate]` passes only because `tests/conftest.py:283 disable_trace_file_writes_by_default` turns trace streaming off.

## W2 — literal YAML numbers silently reinterpreted; only booleans warn
`env: {MODE: 0755, ZIP: 02134, VERSION: 1.10}` → `--validate-only` clean; run prints `MODE=493 ZIP=1116 VERSION=1.1`; also `0x1F`→`31`, `1_000`→`1000`. Follows the decided `to_string` rule; before Part 1 these crashed at spawn, now they are silently different from what the author typed.

## S1 — YAML-keyword keys: misquoted key and a looping fix
`env: {NULL: x}` → `env name 'null' … e.g. NULL` (the same key — following the fix loops); `YES:` → `'true'`, suggests `TRUE`; `OFF:` → `'false'`, suggests `FALSE`. Mechanism: `_as_written` (`env_binding.py:195`) rebuilds the key from the parsed value; `_suggest_name` (`:204`) upper-cases it back into a YAML keyword. Related: the boolean warning says `Quote it ("true")` for `YESV: yes`, which changes `yes` into `true`.

## Observations (pre-existing)
- O1: a value crossing a sub-workflow `inputs:` boundary is JSON-parsed and re-serialized (`{"a":1}` → `{"a": 1}`) even for a declared `type: string` child input — #686 / Task 120. The guide's "bind directly when the bytes matter" names the step's `inputs:` and loop carry, not this boundary.
- O2: CLI `key=value` inference (`cli/param_parsing.py:9-46`) turns a declared `type: string` input `v=007` into `7`, `v=true` into `True`, `v={"a":1}` into `{"a": 1}` before binding — byte-identical to the old inline form, but the guide's "a string bound directly arrives unchanged" is not true for CLI-supplied text that looks typed.

Not attacked: Windows legs and the Linux 128 KB limit (CI), the web-UI preflight (no server), approval-gate masking, loop carry, Part 2 surfaces.
