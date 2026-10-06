# Task 118: Shell and Code Bodies Are Plain Code — `env:` Binding for Shell Steps

## Description

A shell step's `command` becomes plain POSIX sh and a code step's `code` plain Python: neither is
ever a Template. A shell body reads values only as environment variables bound through the shell
node's existing `env:` param (the code node already binds through `inputs:`). This removes the
`${…}` collision between pflow and shell (#621) and shell injection through quoted values (#59),
and converts every in-tree workflow, example, guide page and test to the new form.

## Status
not started

## Priority

medium

## Roadmap

next

> **Refreshed 2026-10-06 against main `a2d094b7`** — rewritten from an eight-lens spec review
> (every "today" claim below was read at the cited line or executed on that commit). Scope narrowed
> by user ruling the same day: code handed to MCP tools plus the `${x|json}` filter is Task 181,
> code-block linting is Task 182. Line numbers drift — re-verify before editing.

## Problem

`${…}` is pflow's Template syntax and also the native syntax of sh. Every node param is scanned
and resolved the same way, the shell `command` and the code node's `code` included — there is no
per-param exemption anywhere (`runtime/engine/template_resolution.py:111-114`,
`core/workflow/template_surfaces.py:77-82`); the guide's "templates go in `inputs`, never in the
code block" is an authoring rule nothing enforces (`result: str = "${name}".upper()` runs today).

- **#621:** in a shell body `${NAME:-world}` and `${#X}` are Issues ("malformed template") and
  `${HOME}` "references an undeclared input". The way through is the `$${…}` escape on every
  brace; the guide tells authors to write `$VAR` instead (`src/pflow/guide/nodes/shell.md:9`).
- **#59:** a value pasted into a quoted shell context breaks on quotes — injection by construction.
- A body that contains Templates is not valid sh on its own, so it cannot be linted (Task 182).

## Solution

**Shell.** `command` is never scanned or resolved. Values are bound in `env:` — Templates resolve
there like in any param — and the body reads them as shell variables:

````markdown
<!-- today: the value is pasted into the command text -->
- type: shell

```shell command
curl -s "https://api.example.com/${endpoint}?limit=${limit}" | jq '.name'
```

<!-- after: the body is plain sh; values arrive as environment variables -->
- type: shell
- env:
    ENDPOINT: ${endpoint}
    LIMIT: ${limit}

```shell command
curl -s "https://api.example.com/$ENDPOINT?limit=$LIMIT" | jq '.name'
```
````

`$HOME`, `${HOME}`, `${X:-default}`, `${#X}` in a body are shell, with no escape. `env:` exists
today (`nodes/shell/shell.py:438`, read at `:803`, merged into the child environment at `:865`)
but the guide never mentions it and it only works for string values (see Requirements).

**Code.** `code.code` gets the same exemption; `inputs:` stays its binding.

**`inputs:` on a shell step keeps its meaning** — the template namespace other params draw from
(`env:`, `stdin`, `cwd`), and where loop Carry lands (`runtime/engine/loop_control.py:65-86`). It
does not reach the body. A looped shell step therefore declares the carried key in `inputs:` and
binds it in `env:` (`env: {STATE: ${state}}`).

**Breaking by design (no external users).** Every inline-templated shell command converts in this
task. Measured size (`implementation/inventory.py`, re-run it for current counts): `examples/` 39
bodies in 20 files; `workflows/` 2 of 2; `src/pflow/guide/` 8 blocks + 2 inline; `docs/` 3; the two
MCP instruction resources 16; `shell.py` 5 docstring examples; the Task-159 baseline workflows 6;
tests ≈325 visible sites in ≈75 files plus ≈50 passed through helper arguments. Templated code
bodies: one, a test (`tests/test_core/test_graph_build.py:1399`).

## Design Decisions

**Ledger (user rulings).** Task 170 deferred one language ruling on non-pflow `${…}` (#621, #550,
#59). Options weighed: (1) strict everywhere + the `$${` escape (status quo), (2) tolerate
non-grammar `${…}` inside code-bearing params, (3) tolerate everywhere as a warning, (4)
code-bearing bodies are never Templates; values bind as variables. The orchestrator first
recommended (2) now + (4) later; the user: *"isnt the real fix to do 4. task 118 or?"* — (2) would
be built for shell/code bodies and then deleted by (4).

- **DECIDED 2026-10-05 (*"yes to all"*) — code-bearing bodies are never Templates.**
  `shell.command` and `code.code` are exempt from scanning and resolution. Contract: ADR-0016.
- **DECIDED 2026-10-05 (*"yes go ahead witht this"*) — the shell binding param is the existing
  `env:`.** Rejected: `inputs:` with shell-specific semantics — it would redefine a key that means
  "template variables" on every node, and a second binding mechanism beside `env:` fails the
  deletion test.
- **DECIDED 2026-10-06 (*"go ahead with all your recommendations"*) — what a non-string value
  becomes in `env:`:** exactly the text `${x}` produces inside any string today — that is
  `core/templates.to_string(value)` (`src/pflow/core/templates.py:621-647`), the one function,
  not a second table. Converted workflows receive byte-for-byte what they received when the value
  was pasted into the command (executed: `True`, empty for null, `3`,
  `{"a": 1, "b": [1, 2]}`), and a string is itself, never re-parsed and re-serialized. Rejected: JSON-style scalars (`true`, `null`) — friendlier
  to sh, but it changes what existing workflows receive and makes `env:` render differently from
  every other string. Task 120 inherits this rule.
- **DECIDED 2026-10-06 — the dangerous-command block stays on the body text.** Today
  `rm -rf ${dir}/*` with an empty `dir` resolves to `rm -rf /*` and is blocked
  (`shell.py:776-780`); once the value arrives as `$DIR` the check cannot see it. Value-driven
  cases are documented as no longer caught. Rejected: expanding shell variables ourselves to
  re-check (fragile), and retiring the check (it still catches literal text).
- **DECIDED 2026-10-06 — scope.** Code handed to MCP tools and the `${x|json}` filter are Task 181;
  linting is Task 182. MCP code params are unchanged by this task (strict, `$${` as today).
- **Settled by evidence (orchestrator, stated to the user):**
  - *The guard against leftover and misspelled references is a static check at validation, not
    shell strictness.* Executed in sh, bash 3.2 and dash: under `set -u` an unset variable inside
    `$(…)` or a non-final pipeline stage prints "unbound variable" but the step still exits 0; `set -u` also breaks `${#X}` on an unset
    name; and ADR-0013 says the meaning of an unadorned shell step never changes.
  - *One classification of code-bearing bodies* that every param walk consults — not an exemption
    patched into two sites.
- **File-loaded bodies** (`- command: ./cmd.sh`) are in scope automatically: they are inlined into
  `command`/`code` before validation (`core/file_resolver.py:38-46`), so a rule keyed on the param
  covers them.

## Requirements

**The exemption**

- `shell.command` and `code.code` are never scanned, validated or resolved as Templates — by
  every consumer, keyed on (node type, param), decided in one place. Consumers on `a2d094b7`:
  the surface walk `template_surfaces.iter_node_surfaces` (`iter_template_surfaces` wraps it and
  feeds `data_flow.py:789`, `path_validation.py:384`, `operands.py:50/60`,
  `template_validation/validator.py:624/735`); the
  runtime split `template_resolution.split_params` (`:112-114`; it has no node type — its caller
  `compiler.py:331` does); and four walks that bypass both: Pass 6
  (`runtime/template_validation/type_validation.py:70-84`), the graph builder
  (`core/workflow/graph/build.py:586`, `_params_strings`),
  `core/workflow/graph/renderers/react_flow.py:473` (`_param_is_dynamic`), and the TypeScript mirror (`web/src/graph/scan.ts:129-137`). A walk that
  misses the rule draws phantom data-flow edges and ref chips from `${HOME}`, or keeps
  type-checking a body. One more consumer reads a body with a different `${…}` language: the MCP
  single-node run expands environment variables over every param, `command` included
  (`mcp_server/services/execution_service.py:731-736`) — a body is exempt there too.
- The exemption keys on the param **before** any "has templates?" test: `$${` counts as a Template
  today, so an exemption gated on that test would still collapse `$${X}` to `${X}`.
- Every consumer listed above is covered by a behavioural test — a body containing `${HOME}`
  produces no surface, edge, chip or type diagnostic — with a parity row for the TypeScript
  mirror. The single-node probe (`cli/commands/_probe_impl.py`) skips the compiler and resolves
  nothing, so a body already reaches the node verbatim; it must get the same `env:` binding.
- The classification's shape must serve Task 181 without being reshaped: that task adds
  code-bearing MCP params, identified by tool (the type string `mcp-{server}-{tool}` is in the IR;
  the server name is user-chosen; registry metadata is not visible to the walks —
  `iter_node_surfaces` takes only the IR, `split_params` has no node type).

**No silent leftovers (validate-only and the run agree on all of these)**

- A `${…}` left in a shell or code body that pflow would have resolved before this task is a
  validation error naming the fix — bind it in `env:` (shell) or `inputs:` (code). It must catch
  the shapes sh itself misses — executed: `${item}` → empty, exit 0; `${fetch-data.stdout}` → the
  text `data.stdout` (sh reads `${name-default}`); `${a.b}` is "bad substitution" only outside
  `$(…)` and pipelines; `'${overwrite}'` in single quotes stays literal; `${__index__}` /
  `${__iteration__}` → empty — and a body Reference to an `inputs:` key or a Carry key, without
  firing on ambient names (`$HOME`, `$CI`, `$GITHUB_TOKEN`) or on shell's own `${X:-y}` forms.
- The plan states the classification rule and resolves each hard case explicitly (part of the
  diagnostics checkpoint): (a) a pflow name that is also an ambient or shell name — `batch.as`
  allows upper case (`ir_schema.py:100`) and `inputs:`/Carry keys are unconstrained, so `as: PATH`
  or `inputs: {HOME: …}` is possible (workflow input and step ids cannot collide: they must match
  `^[a-z][a-z0-9_-]*$`); (b) a shell loop variable with the batch alias's name
  (`for item in …; do echo "${item}"`); (c) a `${name}` declared nowhere — ambient variable or
  typo; (d) another language's own syntax inside the body (`node -e '…`${user.name}`…'`), which
  needs a way to be written, given that `$${` is an error too; (e) bash's `${arr[0]}`, which
  parses as a pflow Reference.
- `$${` in an exempt body is a validation error pointing at the new rule — otherwise sh reads
  `$${HOME}` as its PID followed by `{HOME}` (executed). Three examples already misuse it
  (`examples/nodes/agent/claude-basic.pflow.md:32`, `claude-git-workflow.pflow.md:123`,
  `claude-debug.pflow.md:82` write `$${x.cost}` meaning "a dollar sign, then the value") and are
  rewritten by hand.
- The same check covers `code.code`: a body that relies on a Template today
  (`"${name}".upper()`) must fail validation, not start returning the literal text.

**`env:` becomes a working channel**

- Non-string values bind per the decided rule. Today any non-string crashes at spawn after
  `--validate-only` said "valid": `env: {PORT: 8080}`, a number or boolean input, `${__index__}`,
  `None` from an unset optional input → `TypeError: expected str…`, reported as a false
  "exit code -2".
- A string that looks like JSON reaches the child unchanged when it is bound directly. Today dict
  params resolve with auto-parse (`template_resolution.py:255-267`, `core/templates.py:591-597`),
  so `env: {DATA: ${fetch.stdout}}` with JSON stdout becomes a dict — and re-serializing it would
  change the bytes (`{"a":1}` → `{"a": 1}`). This is #686's mechanism met from the shell side. A
  value that first passes through the step's `inputs:` (and every loop Carry) is parsed there
  (`:262`) — that half is #686 itself and stays Task 120's; it reproduces what the inline form
  produced, so converted loops are unchanged.
- A value that cannot be bound (NUL byte, oversized) and a name that cannot be read as `$NAME`
  (`my-var`, `1x`, `a.b`) fail **before spawn** with a diagnostic naming the variable, at
  validation when it is knowable. A binding failure never surfaces as a command exit code, so
  `ignore_errors: true` cannot swallow it (`shell.py:1006-1016, 1072-1090`). Oversized values point
  at `stdin:`; the limit is the total of arguments plus the whole environment (~1 MiB on macOS;
  ~128 KiB per value on Linux; Windows unverified).
- Names that clobber the shell (`PATH`, `HOME`, `IFS`, `ENV`, `BASH_ENV`, `PS4`, `LD_PRELOAD`) get a
  stated rule, compared case-insensitively (Windows; `BASH_ENV` is sourced by `bash -c`, the
  Windows invocation at `shell.py:169`). `env:` legitimately sets real variables, so this is more
  likely a warning than a refusal — the plan decides and says why.

**Checks that lose their object are re-homed, never silently dropped**

- The dict/list block on `command` and its quote-escape tier (`type_validation.py:158-295`,
  reads `params["command"]` at `:209`) retire with the templated body: they exist because JSON
  pasted into command text breaks quoting, and the decided rule binds objects and arrays through
  `env:` as text. Not moved onto `env:` — that would forbid what the decision allows.
- The loop-carry warning (`runtime/template_validation/validator.py:447-499`) → looks for the
  carried key in `env:`/`stdin` values; its suggestion text ("Reference `${key}` in the node's
  command text") flips.
- The dangerous-command block → per the decision above; `WARNING_PATTERNS` and the
  `PFLOW_SHELL_STRICT` block (`shell.py:783-794`), the `[AUDIT]` log line and the docstring's
  "Pattern Detection" claim (`shell.py:425-427`) are checked for the same loss.
- File-reference detection treats "contains `${`" as "a template, not a path"
  (`core/file_resolver.py:66-67`): a converted one-word body `./scripts/$NAME.sh` is taken for a
  file reference and fails to compile. A body containing `$` is a command, never a path (any one-word `./…` body without one is already a
  file reference today, `:83-84`).

**What ran stays answerable**

- The failure block ("Shell details: Command:" — `core/diagnostic_render.py:612-620, 813-825`,
  fed by the node's `command` output at `shell.py:988` via `executor_service.py:359-364`) and the
  JSON error show the body **and the bound values**, masked by key name. The body keeps today's
  display cap (`[:200]` at `diagnostic_render.py:614, 818`); a bound value is not cut to 20
  characters by the generic sanitizer (`sanitize_parameters` does that to anything over 100 —
  the gate and the web UI avoid it for that reason), and any length cap on values is a stated
  display rule drafted in the diagnostics checkpoint.
- `pflow report` shows a shell step's command. It renders `## Command` only when `command` is in
  `template_resolutions` (`core/trace_report.py:1321-1323`), so after this task every shell step
  would lose it; code steps already read `node_params`.
- The trace format does not change: `node_params` and `template_resolutions` already carry the
  body and the resolved `env:`. If the plan finds it must, that is a version bump plus the
  Task-159 baseline.
- Approval previews and the web UI mask by key name at any depth (`core/gate.py:125-146`,
  `ui/run_node.py:322-336`): `TOKEN_LIMIT: "5"` shows as `<REDACTED>`. Ordinary data now travels
  this channel — the guide's naming rule must keep an approver able to see what they approve.

**The corpus, and the tooling that is part of it**

- Converted workflows produce the same results as before, shown on a named runnable set the plan
  lists by file: the offline examples and the Task-159 baseline
  (`.taskmaster/tasks/task_159/baseline/verify.sh` — 87 cases, about three with templated shell
  bodies; validator-case expectations carry source lines, so the bar is "identical, or each drift
  explained"), outputs captured before and diffed after.
- Old-form workflows outside the repo fail validation loudly with the fix, never run wrong: the
  user's saved library (`~/.pflow/workflows/`, where several workflows use shell) and any live
  worktree's copy of `workflows/` run by the main checkout's `pflow`. Converting the saved library
  is the user's call, not this task's.
- Tests that assert on example text (`tests/test_runtime/test_worktree_creator_workflow.py`
  asserts `ROOT='${get-repo-root.stdout}'`) convert with their examples.
- `workflows/search/run-searcher.pflow.md` and `workflows/review/run-review-lenses.pflow.md` are in
  the corpus and are **shared tooling every live lane runs** — both use `inputs:` + a body
  Reference (`cwd_override`) that would silently take the wrong branch. They convert in this task
  and are exercised for real (a searcher run, a review fan-out run with a `cwd` override) before
  the PR.
- Tests that use `shell.command` only as a convenient templated string
  (`tests/test_core/test_workflow_data_flow.py:493/521/547`,
  `tests/test_runtime/test_template_validation/test_union_types.py`, `test_malformed.py`,
  `test_literal_operands.py`) move to another templated param; converting or deleting them leaves
  success-expecting tests passing while testing nothing. A test that expects an error for an
  unknown name in a command is the mirror case: left alone it stops failing for its own reason.

**Surfaces that go stale**

- `pflow guide`: `nodes/shell.md` (lines 9, 12, 19, 24, 29-41 — the `$VAR`-not-`${VAR}` rule and
  the `$${` escape die; `env:` gets its section: one pattern, UPPER_SNAKE names chosen for the
  content, always double-quoted in the body, the limits, the naming/masking rule), `core.md` (580,
  585, 643), `nodes/code.md` (18, 61 — the authoring rule becomes the mechanism),
  `features/loop.md:60`, `batch.md:26,30,138`, `branching.md`, `sub-workflows.md` (52, 82, 194-201).
- The MCP server's agent instructions — hand-maintained copies of guide content:
  `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` and
  `mcp-sandbox-agent-instructions.md` (16 templated shell fences and the same rule lines).
- `docs/` (`reference/nodes/shell.mdx`, `reference/nodes/code.mdx:67`,
  `how-it-works/template-variables.mdx`, `how-it-works/loops.mdx:47`), `architecture/`
  (`reference/template-variables.md`, `features/simple-nodes.md`), the shell node docstring and
  Interface line (`shell.py:367-438`), `registry/context_builder.py:560-571`.
- Instruction files: `src/pflow/nodes/CLAUDE.md`, `runtime/template_validation/CLAUDE.md`
  (15, 26-27, 56-58, 113-115), `runtime/engine/CLAUDE.md`, `core/CLAUDE.md:101`,
  `core/workflow/CLAUDE.md:60-64`, `.claude/agents/pflow-codebase-searcher.md`
  (+ `make sync-claude-assets`).
- `context/CONTEXT.md`: **Template** is defined as "a string in a Step's params" — bodies no longer
  are; the planner proposes the amended entry and any new noun (a name for a code-bearing body).

## Constraints for the plan

- **Phasing is the planner's, with one observation from review:** the work falls into (A) `env:`
  as a working channel — fixes a live validate-passes-run-crashes bug on its own, and Task 120
  needs it; (B) the exemption, the leftover check, the re-homed checks and the two tooling
  workflows; (C) the mechanical conversion of the corpus. B without C breaks the corpus; A stands
  alone. Whether A ships as its own PR first is the planner's proposal at hand-back.
- **The two tooling workflows land in a quiet moment** — they are read live by every running lane
  and by the review fan-out; the task orchestrator coordinates the merge with the main
  orchestrator.
- **Engine contact** (`runtime/engine/template_resolution.py`): plan-mode deep-review is mandatory;
  the build serializes with every other engine change (#503 edits the same file).
- **Diagnostics are a user checkpoint (show-before-code).** The planner drafts BEFORE/AFTER for
  every new or changed message — the leftover-Reference error for the three likeliest mistakes
  (batch `${item}`, a hyphenated step id, an `inputs:` key), the `$${` error, the `env:` binding
  errors, the reworded loop-carry warning, the failure block — and hands them back before the
  build starts.
- **Windows.** `tests-windows` is a blocking gate (ADR-0013 unchanged). The path-translation
  bridge (`shell.py:78-97`) stays on the body; whether a Windows path bound through `env:` works
  in Git Bash is settled by a test, not by inference, as is `{Path: …}` beside the inherited `PATH`.
- **A misspelled bare variable** (`$ENDPONT` beside a declared `ENDPOINT`) is silent today and
  stays outside the error above; a did-you-mean warning is welcome if it needs no shell parser.
- **Batch memo cache** keys on the raw template plus the resolved items, never other resolved
  params (#675, pre-existing) — moving values into `env:` neither fixes nor worsens it; do not
  fold it in.

## Dependencies

None blocking. Task 170 (one template language, PR #673) and #678 are merged — read
`.taskmaster/tasks/task_170/task-review.md` first (the surface-listed-once invariant, the
TypeScript parity mirror). Coordinate-with: Task 120 (inherits the non-string rule and shares the
auto-parse mechanism via #686; builds after this task), Task 181 (MCP code params; builds after),
Task 101 (file inputs for shell — partly overtaken; see its note).

## Verification

- A shell body containing `${NAME:-world}`, `${#X}`, `${HOME}` and `$$` validates and runs unescaped.
- A value containing quotes, newlines, `$`, backticks and a leading `-` bound through `env:`
  reaches the command intact (#59), on POSIX and on Windows; so does compact JSON text, unchanged.
- Number, boolean, null, object and array values bound through `env:` arrive as the decided text;
  `--validate-only` and the run agree on each.
- Each leftover shape above is a validation error with a one-step fix; ambient `$HOME`/`$CI` and
  `${X:-y}` are not flagged; `--validate-only` and the run agree.
- A code body containing `${x}` fails validation; one without runs unchanged.
- A looped shell step reads its carried value through `env:`; the carry warning fires when the
  key is bound nowhere and stays quiet when it is.
- A file-loaded `./cmd.sh` containing `${HOME}` runs; a one-word body `./scripts/$NAME.sh` is a
  command, not a file reference.
- A failing shell step's error block and `pflow report` show the body and the bound values, with
  a secret-named value masked and a long value untruncated.
- An invalid name, an oversized value and a NUL byte each fail before spawn naming the variable,
  including under `ignore_errors: true`.
- Regression guard (already true — non-batch nodes key on resolved params,
  `instrumentation.py:233-235`): changing an `env:` value changes the memo-cache key.
- The graph and the web UI draw no edge or ref chip from a body's `${…}`; `env:` References still
  draw theirs (Python and the TypeScript mirror agree).
- The named corpus set produces identical outputs before and after; the review fan-out and the
  searcher offload run for real after conversion.

## References

- `context/adr/0016-118-code-bodies-untemplated-env-binding.md` (the contract) · ADR-0013.
- Issues: #621 (shell half closes here; JS half is Task 181), #59 (closes), #620 (the `$${` escape
  stays everywhere outside code bodies), #686 (same auto-parse mechanism), #698 (failure output).
- `starting-context/` and `research/` predate the rulings and recommend `inputs:` for shell —
  superseded by the ledger above; read them for the observed pain, not the design.
