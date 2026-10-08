# Task 118 — progress log

Append-only. Entry format: ORCHESTRATION.md → "Progress-log entry format".

## [2026-10-06 22:45] task-planner (Fable) — plan written, self-review launching; PARKED-ON-USER after commit (CP-1)
- Did: investigated on `82341e2b`, fast-forwarded the branch to `b2cd92e3` when #715 merged mid-plan (no local
  commits yet, so `--ff-only`); eight `pflow-codebase-searcher` passes (Python param walks, the TypeScript
  scanners, display + redaction, validation layering + parser facts, stale surfaces, Windows + CI, two
  test-classification passes that read every listed site); read `template_surfaces.py`,
  `template_resolution.py`, `shell.py` prep/exec/post/fallback, `data_flow.py` scope + node-param check,
  `file_resolver.py`, `trace_report._format_resolutions`, both shell failure renderers and the carry warning
  directly. Wrote `implementation-plan.md`, `diagnostics-checkpoint.md` (CP-1, BEFORE executed on `b2cd92e3`),
  `inventory.py`; corrected the spec in place (plan §2.7).
- Changed: `implementation/{implementation-plan.md, diagnostics-checkpoint.md, inventory.py, progress-log.md}` (new),
  `task-118.md` (measured size, consumer list, probe sentence, stale-surface list, vehicle-test list, one citation).
- Verified (executed): `inventory.py` → 428 templated bodies / 128 files (plan §2.5 breaks it down);
  `task_159/baseline/verify.sh` → 75 pass / 12 drift / 0 harness errors, drift set named in plan §2.5;
  `task_170/.../capture.py --check` → 29 examples, 1 differing (`error-handling/typo-on-failed-node`) — both
  drifts pre-date this task; fourteen probe workflows (checkpoint BEFORE blocks); `sh` semantics of `${item}`,
  `${fetch-data.stdout}`, `$${HOME}`, `${a.b}` inside `$(…)`.
  | Assumed (named in plan §10): no user node registers as `shell`/`code`; the searcher offload is runnable from
  the build environment. Unverified, settled only by `tests-windows`/Linux CI: plan D8, D3.
- Deviations/surprises (vs the spec): (1) a ninth body consumer the spec did not name — the MCP single-node run
  expands `${VAR}` from the process environment and settings over every param, `command` included
  (`mcp_server/services/execution_service.py:731-736`); a shell loop variable written `${f}` raises there today.
  (2) `cli/commands/_probe_impl.py` resolves nothing — it needs no exemption, only the binding, which is why
  binding is node-owned (D2). (3) Two hand-maintained copies of guide content under
  `src/pflow/mcp_server/resources/instructions/` hold 16 templated shell fences — absent from the spec. (4) The
  inventory cannot see ≈50 sites passed through helper arguments, and a test expecting an error for an
  out-of-scope name in a command passes vacuously after the flip — the gate for PB is the T2 list by name, not
  the script. (5) Today a misspelled step id in a command is an ERROR with did-you-mean; under a scope-only rule
  it would be silent — hence checkpoint ruling 2 (a warning). (6) `tests/test_core/test_types.py` has no shell
  text; `test_union_types.py` is a vehicle file, not retired behaviour. (7) Converting the corpus *before* the
  flip is possible because `env:` already works for strings — it removes the "B without C" window the spec
  describes (D13) and makes the tooling workflows safe under both semantics.
- Not edited, goes up: `task-181.md` cites the unused-input check at `core/workflow/validator.py:555-600`; it is
  at `runtime/template_validation/validator.py:555-612`.
- Self-checks: plan-mode `deep-review` launching now (mandatory — engine contact): review-plan,
  architecture-fit, silent-failures, impact-completeness, validation-consistency, feature-interactions,
  agent-ux, concurrency-safety, test-fidelity. Outcome appended below before the commit.
- Resume point (if this session is lost): the plan and checkpoint are complete drafts on disk, uncommitted. Next
  acts in order — evaluate the nine lens reports, fold confirmed fixes into the plan, append the outcome here,
  commit plan + checkpoint + inventory + spec + log with deliberate staging, hand back with CP-1's path. After
  the user's ruling on CP-1 the planner is resumed ONCE to fold the ruling into the plan (strings and, if rule 1
  or 2 changes, D5) and to record it here; no build starts before that entry exists.
- Next: evaluate the battery.

## [2026-10-06 23:55] task-planner (Fable) — plan self-review folded; committing; PARKED-ON-USER (CP-1)
- Did: nine plan-mode lenses by direct launch (review-plan, architecture-fit, silent-failures,
  impact-completeness, validation-consistency, feature-interactions, agent-ux, concurrency-safety,
  test-fidelity). Criticals verified by the planner against code before folding: (1) FI C1 — a failing child
  shell step's output rides the child-failure bundle into batch error records that CLI text/JSON/MCP emit
  unredacted (`runtime/workflow_executor.py:662-672`, `execution/formatters/batch_errors.py:99-104`,
  `batch_executor.py:484-486`) → D9 now records one display-safe copy at the source; (2) SF C1 — `${limit:-10}`
  on an in-scope name is an Issue the rule ignored and sh would silently default → D5 treats an Issue whose
  leading name is in scope as a leftover; (3) SF C2 — `git-worktree-task-creator` pre-escapes a value for the
  pasting layer (`workflow.pflow.md:308-309`, read) → conversion rule 5.3 + a stubbed `launch-cli` run;
  (4) IC C1 — the drafted Interface comment `NAME: value` registers a fake param (lens executed the extractor)
  → wording changed + an assertion; (5) TF C1 — `document-processor`'s converted step never reaches the
  workflow result (lens executed) → the PC gate dumps per-node outputs from the trace (`baseline/node_outputs.py`).
  Warnings folded: per-step scope for the leftover rule (batch alias/`__index__` only on the batch step; a
  bare `${stepid}` never — VC W1/FI W1); D4's errors shared with the compiler (UI preflight — VC W2); carried
  values are parsed by `inputs:` (#686, accepted — VC W3); no braces in PC and guide fences convert in PC
  (RP W1/W2, VC W4); code bodies read through `ast` string constants so f-strings pass (RP W4/VC W5); file
  references through one node-aware predicate at four callers (RP W3/IC W1); E2BIG translated inside
  `exec()` non-retriable + lone-surrogate check (CS W1/W2); Windows merge keeps the author's spelling
  (CS S3); batch-item report pages (FI W2/IC W2/SF W3); per-row inputs for the consumer table and a
  dynamic instrumented suite run before the flip (TF W1/W3, SF W4); Task-159 compared actual-vs-actual and
  golden hashes bounded (TF W4/W5); the equivalence harness for non-runnable conversions (TF W6); D8
  presence checks (TF W7); dynamic names for the `ignore_errors` test (TF W8); parity-row shapes (TF W9);
  `text` taken off the mode axis into `binds_as_text` + the resolver's `parses_leaves` predicate (AF S1 and
  the coordinator's seam note: one per-leaf predicate Task 120 extends); resume `--force` + skill symlinks in
  the hand-back (AF W1/FI S1); the unread-`inputs:`-key warning (SF W2); every agent-ux rewrite (C1–C3,
  W1–W7) is in the checkpoint. Disputed/declined with reason in the plan: a required `TemplateConfig.node_type`
  (one constructor; 31 test constructions), an AST meta-test, a did-you-mean on plain braced names (Task 182),
  unbound-but-unread env warnings.
- Changed: `implementation-plan.md` (§1, §2.1, §3 rewritten, §4 phases, §5, §6.1, §7, §10),
  `diagnostics-checkpoint.md` (rewritten: per-step scope, hard cases f/g, Issue forms, every rewritten
  message, §4e/§4f new, §5 generalized, §6 display-safe copy), `task-118.md` (the `inputs:`/Carry parse
  clause).
- Verified: the five governing/related issues were read in full at investigation start (body + comments:
  #621, #59, #620, #686, #698) — recorded here because the earlier entry omitted it.
- Deviations/surprises: the spec's "validate-only and the run agree" needed the compiler to share D4's
  errors — the UI launches through a compile-only preflight, so a validator-only error there is invisible
  (`ui/server.py:1019, 1233-1237`); and the spec's byte-for-byte claim holds only for a value bound directly
  (a value through `inputs:` is parsed by #686's mechanism) — the spec now says so.
- Self-checks: all nine lens reports evaluated; two findings handed up unresolved (both other tasks' specs):
  `task-112.md:73` names Pass 7 as coverage; `task-181.md` mis-cites the unused-input check.
- Next: commit plan + checkpoint + inventory + spec + log; hand back with CP-1's path; on resume with the
  ruling, fold strings (and D5 if rule 1/2 change) and record it here before any build.

## [2026-10-07 00:20] task-planner (Fable) — CP-1 RULED; PR shape ruled; plan unparked
- Did: folded the rulings. [RULING] (main orchestrator under the user's grant *"run as far as you can without
  me tonight, end to end, you have the grant"*): CP-1 rulings 1–9 **all as recommended** — scope-based,
  step-local leftover rule with hard cases (a)–(g); ruling 2 = **W** (warning for an unknown-root pflow-only
  shape in a shell command); `$${` an error in both bodies with the drafted fixes; 4a–4f incl. the
  literal-boolean warning, clobber list as a warning, case-duplicates as an error, binding failures raised
  before spawn and never swallowed; ruling 5 incl. the unread-`inputs:`-key warning; ruling 6 = one
  display-safe copy via `redact_sensitive`, 200-char cap wherever it travels, full values in the report;
  7 accepted; 8 acknowledged; 9 wording accepted. **Correction applied:** checkpoint §6 said bound values
  show as "compact JSON" — `to_string` uses default separators (`{"a": 1, "b": [1, 2]}`), as §4a already
  said; §6 now matches. PR shape: **two PRs** — Part 1 non-breaking, may merge once green; **Part 2 goes
  PR-ready and is NOT merged until the user rules on a release** (plan §4.0). Phase E on Opus, not
  design-bearing: ruled. CONTEXT.md nouns (§11): the main orchestrator writes them when Part 2 merges.
- Changed: `diagnostics-checkpoint.md` (header + §6 text rule), `implementation-plan.md` (§4.0, §9 CP-1).
- Verified: n/a (text). | Assumed: nothing new.
- Deviations/surprises: none — every recommendation was taken.
- Self-checks: the build gate the plan names (this entry) now exists; nothing else changes in the plan.
- Next: task orchestrator launches on Part 1 (P0 + PA) from this plan.

## [2026-10-07 00:40] task-planner (Fable) — builder notes (what the plan does not say)

### 1. Dismissed or accepted on documentation alone — and what would show it wrong
- **Searcher/lens facts I never re-read** (trust the citation, check the reasoning): the web scanner chains
  (`scan.ts:129-150`, `sourceDecorate.ts` tiers, `ReadPanel.tsx:74`) and `_param_is_dynamic`'s `True` for
  `echo ${HOME}` — wrong if a grep of `web/src` for `\$\{` finds a fifth scanner; the UI compile-only
  preflight (`ui/server.py:1019, 1233-1237`) — wrong if `/api/run` actually calls `WorkflowValidator`;
  `code_param_type_diagnostics` being shared by step 9 and the compiler — wrong if `compiler.py` imports
  something else; `resume_preflight.py:158-172` content-hash refusal; the four `is_file_reference` callers
  (lens executed `discover_dependencies` raising; I read only `file_resolver.py`); `ir_to_markdown`'s `env`
  round-trip; YAML scalar typing (`yes`→True, `012`→10); the 31 keyword-only `TemplateConfig(` and 36
  `split_params(` test calls; every row of §6 (two searchers read the tests; the test-fidelity lens
  spot-checked 18 rows — the rest is their reading, not mine). Each is wrong if the file:line it cites no
  longer shows it — re-grep before the phase that touches it.
- **Declined findings:** a required `TemplateConfig.node_type` (one constructor; a second constructor
  that forgets it would show me wrong — PA test 2's mutation would then pass against it); an AST meta-test
  for "every walk consults the classification" (wrong if a new walk ships that PB test 1's table does not
  cover); a did-you-mean on a plain `${endpont}` (deferred to Task 182 — wrong if dogfood shows agents
  typo braced names more than bare ones); a "bound but never read" env warning (wrong if conversion
  slips of exactly that kind show up in PC); the empty-secret `<REDACTED>` fix (shared function, #715's).
- **Ledger/spec claims taken as read:** `set -u` fails inside `$(…)` (the spec executed it; I did not);
  the Linux 128 KiB per-string limit and everything Windows (only CI can refute them); "no user node
  registers as `shell`/`code`" (wrong if the registry allows a user override of a builtin name — check
  `registry/scanner.py` when PB touches `param_mode`).
- **One thing I verified myself that looked like a claim:** inline interpolation and `bind_env` share
  `to_string` (`_resolve_string` → `to_string`, `templates.py:611-647`), so byte identity is by
  construction, not by test luck.

### 2. For the task orchestrator and implementers — where I expect a builder to go wrong
- **Measure first, every phase.** P0: the four baselines by name (a difference from plan §2.5 is a
  finding). PA: run checkpoint §4a's probe (`env: {PORT: 8080, N: ${count}}`) before touching the engine —
  it is the bug; after the engine edit, run PA test 2's mutation (restore `:267`) and watch it go red.
  **PC: run the instrumented suite BEFORE converting anything** — that gives the complete site list up
  front (the inventory is a map). PB: flip `iter_node_surfaces` alone first and run `make test` to see
  the tail of sites that survived PC; then the rest. PD: re-run checkpoint §6/§7's probes and diff
  against the BEFORE text.
- **PC traps:** braces (`${NAME}`) in a body are still Templates under the old semantics — split the quotes
  instead; a suggested name that lands on `PATH`/`HOME`/`LANG` (`AMBIENT_NAMES`); single-quoted programs
  (104 sites) — splice, never leave `$NAME` inside `'…'`; a shell step's `inputs:` is deleted only when it
  is not a loop Carry target; the worktree-creator's Layer-0 escaping must go with the conversion.
- **PB traps:** do not reuse data_flow's `node_refs` for the leftover scope (it is workflow-wide); the
  Issue leading-name extraction must handle `${#}`/`${!}`/`${}` without raising; `ast.Constant.lineno` is
  the string's start line — a leftover on a later line of a triple-quoted string needs the newline count
  inside the constant; `validate_data_flow` returns WARNINGs too and the compiler filters ERRORs only —
  keep ruling-2's warning out of `CompilationError`; the unread-`inputs:` warning will fire on the three
  corpus shell steps that have `inputs:` today unless PC removed them — check before PB.
- **PD traps:** `post()` writes the safe copy only on the two `return "error"` paths and pops it on
  success — confirm `NamespacedSharedStore.pop` is routed (the CLAUDE.md says mixins route `pop`);
  `_format_resolutions` must take the parent event for items without breaking the LLM/code pages.
- **PA traps:** `EnvBindingError` needs both class attrs (`retriable = False`, `batch_fatal = False`) or
  the batch burns retries; the E2BIG translation lives in `exec()` before the generic `except Exception`,
  and `exec_fallback` must re-raise `PflowError` without touching the timeout path; the Interface comment
  must not contain `, X: ` (fake-param trap).
- **Least sure:** the equivalence harness (bound it: the 13 single-quoted example sites + worktree-creator;
  if it balloons, hand back rather than skip); the Windows mixed-case rule (D8-2's second row may be the
  first thing CI refutes — that is CP-2); the batch-item report refactor's blast radius on existing
  report tests; whether the unread-`inputs:` warning is noise on real workflows (watch PZ's real runs).
- **Phase E:** the Python side already removes chips/edges; the TS work is three small skips plus parity
  rows — if an implementer starts restyling, stop them.

## [2026-10-06 23:05] implementer I1 (Opus) — P0 baseline (head 0177dd4c = b2cd92e3 + origin/main ebf7cab2 + planner notes)
- Did: ran the four baselines before any edit; hand-captured `examples/nested/document-processor.pflow.md`.
- Changed: `implementation/baseline/` (new): `document-processor.{command.txt, output.json, stderr.txt, trace.jsonl}`.
- Verified (executed, this worktree, macOS):
  - `make test` → **10354 passed, 0 failed** (exit 0, 33 s). Failing set: empty.
  - `inventory.py` → **428 templated bodies in 128 files** (= §2.5). Per-area rows identical to §2.5 (examples 39/20
    + 1 python-dict, workflows 2, guide 8+2, docs 3, `src` MCP resources 16, task_159 6, tests 237/34/35/18, code 1+2+1).
  - `task_159/baseline/verify.sh` → **75 pass / 12 drift / 0 harness errors**; drift set identical to §2.5 by name
    (02/03, 02/05, 03/05..09, 04/03, 04/09d, 04/09e, 10/03, 12/04-guide-auto-detect).
  - `task_170/.../capture.py --check` → **29 examples, 1 differing** (`error-handling/typo-on-failed-node` — the
    `workflow.name` key) (= §2.5).
  - `document-processor` (fresh HOME, fresh cwd, `title=Hello World`, `body=it's a body`): exit 0; workflow
    `result` = `IT'S A BODY` (process_body's — confirms TF C1: the templated step never reaches the result), so
    the trace is stored too; `combine`'s `node_output.stdout` = `Title: HELLO WORLD\nBody: IT'S A BODY`.
- Deviations/surprises: (1) inventory **shape** counts differ from §2.5 while every total matches: plain 220 (§2.5:
  190), dotted 134 (131), dotted-hyphenated 37 (35), single-quoted 105 (104); coalesce/index/`$${`/batch/inputs/env
  identical. Not main moving (the per-area totals are equal) — the shape lines count sites with *at least one* such
  reference across every corpus incl. history, so the §2.5 figures were likely taken from a different run/subset;
  not load-bearing for PA, flagged for PC (which uses the shapes). (2) P0 named only command + output for the hand
  capture; I also stored the trace, because the JSON output cannot show the converted step's result.
- Self-checks: n/a (no code). test-reflect: not applicable to P0.
- Next: PA — §4a probe before the engine edit.

## [2026-10-06 23:25] implementer I1 (Opus) — PA `env:` is a working channel (Part 1)
- Did: D2 binding module, D3 E2BIG translation, D4 static checks (step 9 + compiler), the engine edit
  (`binds_as_text` → `parses_leaves`, `TemplateConfig.node_type`), Interface line, the two tooling workflows
  (exactly the PA edit — diff is 4 lines each), guide section, three CLAUDE.md lines, the coercion-doc sentence,
  PA tests 1–11. [RULING, orchestrator, importance 1] PA's Files line names `ParamMode`/`param_mode`; D1 says
  Part 1 ships `binds_as_text` only → **shipped `binds_as_text` only** (no caller for `param_mode` until Part 2).
- Changed: `nodes/shell/env_binding.py` (new); `nodes/shell/shell.py` (prep binds, exec merges + E2BIG,
  `exec_fallback` re-raises `PflowError`, `_env_key` for the Windows env, Interface line);
  `core/workflow/template_surfaces.py` (`binds_as_text`); `runtime/engine/{types.py, template_resolution.py}`;
  `runtime/compilation/compiler.py`; `core/workflow/validator.py` (`shell_env_diagnostics` + step-9 branch);
  `workflows/{search/run-searcher, review/run-review-lenses}.pflow.md`; `guide/nodes/shell.md`;
  `{nodes, core/workflow, runtime/engine}/CLAUDE.md`; `architecture/core-concepts/data-type-coercion.md`;
  tests: `tests/test_nodes/test_shell/test_env_binding.py` (44), `tests/test_integration/test_shell_env_binding.py`
  (53), 4 `shell_env` rows (8 items) in `test_template_parity.py`.
- Verified (executed, macOS):
  - Gate: `make check` green; `make test` **10459 passed / 0 failed** (P0: 10354 → +105, all new; failing set
    still empty); `make test-e2e` 52 passed / 2 skipped. `verify.sh` drift set identical to P0 by name (75/12/0);
    `12-…/04-guide-auto-detect` (already drifting) now also shows the new guide section + Interface line — explained.
    `capture.py --check` 29 / 1 differing (= P0).
  - Measure first: §4a probe BEFORE the edit reproduced the checkpoint text (`✓ Workflow is valid`, then
    `Command failed with exit code -2: expected str, bytes or os.PathLike object, not int`).
  - **Mutation (PA test 2):** restored `auto_parse=isinstance(template, (dict, list))` at the resolver →
    exactly 3 red: `TestJsonLookingTextStaysText::test_bound_directly_from_upstream`, `…as_a_batch_item`,
    `test_template_parity …[shell_env_compact_json_string]`; restored from a byte copy (`cmp` clean). Extra
    seam mutations, all restored by byte copy: dropping `node_type=` in the compiler → the same 3 red (the
    `""` default cannot hide a forgotten pass); `exec_fallback` swallowing `PflowError` → 3 red (E2BIG rows +
    the fallback unit); `EnvBindingError.retriable` removed → 4 red (continue-batch prep count, E2BIG spawn
    count, the attribute pin).
  - Real surface, checkpoint §4 AFTER (`uv run pflow`, worktree):
    - 4a `env: {PORT: 8080, N: "${count}"}` count=3 → valid; run prints `port=8080 n=3`.
      `env: {DEBUG: true}` → valid + `⚠ [show] Step 'show': env DEBUG is the YAML boolean true and binds as
      the text True.` / `→ Quote it ("true") if the command compares text.`; run prints `debug=True`.
    - 4b `{my-var: hello}` → validate-only and run both: `Error 1: Validation Error` / `Step 'show': env name
      'my-var' cannot be read as a shell variable.` / `At: node 'show', nodes[id=show].params.env.my-var` /
      `→ Use letters, digits and underscores, not starting with a digit — e.g. MY_VAR — and read it as
      "$MY_VAR" in the command.` (= ruled text).
    - 4c `{Path: a, PATH: b}` → `Step 'show': env names 'Path' and 'PATH' differ only by case — on Windows they
      are one variable.` / `At: …params.env` / `→ Keep one of them.` plus ONE clobber warning (see deviations).
    - 4d `{PATH: /opt/bin}` → valid + the ruled warning and fix verbatim; run completes with the warning.
    - 4e literal `[A=1]` → `Step 'show': env must be a map of NAME: value — got a list.`; whole-templated
      `env: "${up.result}"` resolving to `"A=1"` → run: `env must be a map of NAME: value — got a str.`
    - 4f NUL (from an upstream code step) → `Error: Validation Error` / ruled NUL text verbatim / `At: node
      'show'`. 1.2 MB upstream value under `ignore_errors: true` → `The command could not start: … (largest:
      BODY 1.2 MB bound in env:, the command 27 bytes). Pass large values through stdin instead and remove them
      from env: — on macOS the limit is about 1 MB for everything together.` — the run fails (not swallowed).
  - Searcher offload, converted workflow, two real runs (effort=low, trivial prompt), both `success`:
    without `cwd` → trace `resolve-cwd` env `{'CWD_OVERRIDE': ''}`, stdout
    `/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding`, answer names that root;
    `cwd=/Users/andfal/projects/pflow` → env `{'CWD_OVERRIDE': '/Users/andfal/projects/pflow'}`, stdout and
    answer `/Users/andfal/projects/pflow`. `run-review-lenses` validated only (its real run is Part 1's gate).
  | Assumed / unverified: every Windows leg (D8-1..4, the win32 merge in real Git Bash) — CI only; the Linux
  per-value refusal at 200 KB (D8-4 linux leg asserts it; ubuntu CI confirms).
- Deviations/surprises:
  1. `env_problems` returns `list[EnvProblem]` (frozen dataclass: `name`, `message`, `fix`) instead of D2's
     `list[tuple[str | None, str]]` — the ruled text has the fix as a separate `→` line at validation but inside
     the sentence at run time (batch errors carry only `str(exc)`), so the fix had to travel separately.
     `EnvProblem.sentence()` is the run-time form. Importance 1.
  2. Compiler: `_reject_non_string_code` renamed `_reject_static_param_errors` and now dispatches code AND
     shell (ERRORs only) — one site instead of a second sibling; no external references existed.
  3. 4e run-time text is `env must be a map of NAME: value — got a str.`, not the checkpoint's
     `…; ${cfg.env} resolved to a str.` — the node sees only the resolved value, never the template text;
     naming it would need engine plumbing for one message. The `At: node 'show'` line carries the location.
  4. 4d: the checkpoint gave the full text for PATH and only per-name phrases for the rest. Built as
     `Step 'X' sets NAME in env:, replacing the NAME the command inherits — <consequence>.` + `→ To pass data,
     use another name — e.g. TOOL_NAME.`; a lower-case spelling adds `, which on Windows is PATH (names ignore
     case there)` (on POSIX `path` is its own variable — the warning would otherwise be false there). Warned once
     per canonical name (the first real run of 4c showed one warning per spelling — noise; deduped + pinned).
  5. Dropped `node_type` from the diagnostics' context: the renderer printed an extra `Node type: shell` line the
     ruled layout does not have.
  6. `AMBIENT_NAMES` (D2) got its caller now: an invalid name's suggestion that lands on an ambient name gets
     `_VALUE` (`bash-env` → `BASH_ENV_VALUE`), so it does not ship caller-less.
  7. The E2BIG message names a Linux limit ("one value can be at most 128 KB") — checkpoint §4f says only the
     current platform's limit is named; the figure is the kernel's `MAX_ARG_STRLEN` hypothesis, confirmed only
     when ubuntu CI's D8-4 leg passes. Windows names no limit (no branch, per D3).
  8. **Expect `tests-windows` to show D8-4** as either a pass (bound, or a translated refusal) or a red
     assertion whose message carries the observed outcome (a non-E2BIG OSError → today's `-2` path). A pass on
     win32 emits a `D8Observation` warning into the pytest warnings summary, so the outcome is in the CI log
     either way. A D8-1..3 red is CP-2, not to be worked around.
  9. Scratchpad: the session scratchpad dir is shared (a probe file vanished mid-run) — my scratch moved to
     `scratchpad/i1-t118/`; no effect on deliverables.
  10. `docs/reference/nodes/shell.mdx` still reads "Additional environment variables" — PF's surface, untouched.
- Self-checks: fully-happy pass run before handback — doubts raised and fixed: the 4c double warning (deduped,
  test added), the stray `Node type:` line (removed), `AMBIENT_NAMES` without a caller (given one). Remaining
  honest doubt: D8-2's Windows leg greps `env` output for `^path=` case-insensitively — if MSYS exports both a
  `PATH` and the authored `Path`, that leg goes red, which is exactly the CP-2 signal it exists to give.
  test-reflect: **left for the orchestrator to direct** (not run).
- Next: Part 1 close-out (task orchestrator). Hand-back note carried from the plan: converting the two tooling
  workflows changes their content hash — a paused/failed run of either started before the merge resumes only
  with `pflow resume --force`.

## [2026-10-06 23:50] implementer I1 (Opus) — PA self-checks (directed): test-reflect + "fully happy?"
- Did: applied `.claude/commands/test-reflect.md` to PA's tests (`test_env_binding.py`, `test_shell_env_binding.py`,
  the `shell_env` parity rows); answered the fully-happy question below.
- Changed: the three test files only (no `src/` change).
- Verified: `make check` green; `make test` **10458 passed / 0 failed** (10459 − 2 parity items + 1 control test).
  New mutations, each restored from a byte copy (`cmp` clean), counted reds: **M1** binding moved from `prep()` into
  `exec()` → 4 failed (the two unbindable-value rows, the whole-name row, the continue batch); **M3** `bind_env`
  drops `None` values instead of binding them empty → 4 failed. Before the deepening, M3 passed every integration
  row (`""` from an unbound variable equals `""` from an empty one).
- Self-checks: **test-reflect (directed):**
  - DEEPENED `TestBindingFailures._assert_failed_before_spawn`. **Fake-pass found:**
    `"exit_code" not in shared_after.get("s", {})` was vacuous, because a failed step's namespace is gone (the record
    moves to `__failures__`). It now reads `__failures__["s"]` and asserts `category == "exception"` and no
    `exit_code` in its `data`. A new control, `test_a_command_failure_records_its_exit_code_in_the_same_record`
    (`exit 3` → `("shell_failure", 3)`), shows that same record can carry an exit code.
  - DEEPENED the one-attempt count. The fixture went from `prep_calls` to `attempts`, which spies both `prep()` and
    `exec()`. `prep()` is never retried by `Node._exec`, so a prep-only count could not fail on retry; `exec()`
    is the retried, spawning phase. The rows assert `["prep"]` (no exec). The continue batch asserts
    `["prep","exec","prep","prep","exec"]` (item 1 is never spawned even with `max_retries: 3`) plus
    `status is DEGRADED`. The `if item` filter on `results` was removed (results hold successes only).
  - DEEPENED `TestEveryValueBinds` (literal / input / upstream / unset optional). The command now also prints
    `env | grep -c "^V="`, and each row expects `<text>|1`, so a value bound as empty is told apart from one
    never bound (M3).
  - DEEPENED D8-2's first leg with a control spawn. Without a PATH binding, the inherited sentinel must appear in
    the child's PATH line, so the win32 "sentinel absent" assertion is no longer free. Sentinel and marker are
    now real directories, so no layer can drop them as dangling. The win32 leg can fail: one-line count, marker
    presence, sentinel absence, plus the `grep` spawn needs the support paths. D8-1, D8-3 and D8-4 already
    paired absence with presence (`stdout == value` beside "marker not created"; D8-4's `exit_code != -2`
    beside an exact outcome per branch).
  - DEEPENED `test_a_quoted_or_templated_value_does_not_warn`. It now pairs in-test with a literal boolean in the
    same map and asserts the only warning is `env.LITERAL`; before, it relied on a sibling test for the medium.
  - DELETED the `retriable` / `batch_fatal` attribute pins in the node unit test (renamed
    `test_the_error_renders_as_a_validation_error_on_env`, which keeps the title/param pin). Behaviour through the
    engine already kills both (PA mutation B: 3 behavioural reds), so the pins only restated the implementation.
  - DELETED parity row `shell_env_object`. It duplicated the non-string archetype (`shell_env_non_string`) and the
    integration value table; the plan's three rows remain.
  - Kept as is, checked: the validate-only/run pairs. The `_validate(...)[0] == []` halves are agreement checks,
    not shipped-ness evidence (validation passed before this task too). The run halves, the compiler
    `wrapped_diagnostics` equality, and the `${cfg}` run-time sentence are the discriminating parts. Also kept:
    memo-key (presence via the cache-hit count), injection (stdout == value beside marker absence), and the JSON
    rows (PA mutation).
  **Fully happy?** Yes for macOS/Linux behaviour; the honest loose ends are all on Windows, and the plan already
  routes them:
  1. D8-4 on win32 may be red (a non-E2BIG OSError → today's `-2` path) until the branch is written from CI.
  2. D8-2 may show MSYS exporting both spellings. That is CP-2 by design.
  3. Several integration tests (memo `COUNTER`, injection `cwd`) pass a Windows path through `env:`, so they share
     D8-1's fate on `tests-windows`. If D8-1 is red, expect them red too; that is the same root cause, not
     separate bugs.
  4. The Linux 128 KB wording in the E2BIG message is confirmed only by ubuntu CI's D8-4 leg.
- Next: orchestrator commits; completion gate.

## [2026-10-07 00:05] task orchestrator (Opus) — Part 1 phase work committed; completion gate commissioned
- Did: verified I1's handbacks independently (`make check` green, `make test` 10458 passed); accepted PA deviations
  1–10 as logged (the 4e run-time text delta goes in the PR body); committed `ea34cfb5`; `make test-all-local` →
  10510 passed / 2 skipped.
- Gate (code mode, `origin/main...HEAD`), lenses by the deep-review trigger table: sensitive paths (engine,
  `nodes/shell/`) ⇒ `silent-failures`, `impact-completeness`, `feature-interactions`, `test-fidelity`; validator +
  runtime twin ⇒ `validation-consistency`; new messages + guide ⇒ `agent-ux`; subprocess env ⇒
  `concurrency-safety`; **plus `review-simplicity`** — a deliberate addition to the plan's Part 1 list (the plan
  deferred it to Part 2): Part 1 merges alone and Task 120 inherits `env_binding.py` before Part 2 exists, so its
  final-code simplicity is reviewed now (counts are floors). `spec-conformance` stays with Part 2 (never mid-task).
  Dimension lenses scoped per seam; cross-cutting lenses see the whole diff. Gate-runner: I1 (holds the code).
  Dispatch through the CONVERTED `run-review-lenses.pflow.md` with an explicit `cwd` override — that run is the
  spec's required real exercise of the fan-out. `review-falsifier` launched by me directly, LAST, after the
  reading battery's fixes land.
- Next: I1 runs the fan-out, evaluates, fixes, logs every disposition.

## [2026-10-07 00:45] implementer I1 (Opus) — Part 1 completion gate (code mode): fan-out run, evaluated, fixes applied
- Did: dispatched the reading battery through the CONVERTED `run-review-lenses.pflow.md` with an explicit `cwd`
  override. This is the spec's required real exercise of the converted fan-out. Read the merged report in full,
  evaluated every finding, applied the confirmed fixes with tests.
- Command (from the worktree, backgrounded, stdout tee'd, waited in-turn with an until-loop):
  `uv run pflow workflows/review/run-review-lenses.pflow.md "lenses=<8 lenses>" "review_target=<Task 118 Part 1,
  origin/main...HEAD; uv.lock not a target; ADR-0016 + checkpoint §4 settled — silence is a gap, regressions
  disputed by default; Part 2 absence not a finding>" cwd=/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding
  | tee .taskmaster/tasks/task_118/implementation/gate-part1-report.md`.
  - Lens list: impact-completeness, feature-interactions and simplicity on the whole diff. Per-seam targets:
    silent-failures, validation-consistency, agent-ux, concurrency-safety, test-fidelity.
  - Outcome: `✓ Workflow completed in 374.6s`, provider codex, 9 agent calls, `run-codex 8/8`.
  - Trace `~/.pflow/debug/workflow-trace-3a06f035-run-review-lenses-20261006-233103-073360.json`: `resolve-cwd`
    env `{'CWD_OVERRIDE': '/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding'}`, stdout the
    same path. The converted override works for real.
- Coverage: all 8 lenses produced reviews (report §Coverage, "Failed-lens gaps: None"). No re-run needed.
- Findings and dispositions (every one):
  1. **Guide omits "when bound directly"** (impact-completeness W1, agent-ux W2, feature-interactions S;
     convergent). **Confirmed, fixed.** `guide/nodes/shell.md` now says a string bound directly arrives unchanged,
     a value through `inputs:` (or a loop carry) is parsed and re-serialized (`{"a":1}` → `{"a": 1}`), and to bind
     directly when the bytes matter. Plan D2 asked for exactly this sentence and I had dropped it. Docs only.
  2. **(2a) A literal object/array holding an unencodable string passed validation and compile, then failed at
     run time** (validation-consistency, stated Critical). **Confirmed, fixed. Real severity: Warning** — reachable
     only through dict/JSON IR (a `.pflow.md` file cannot hold a lone surrogate), but it is a genuine
     validate-vs-run disagreement.
     - Fix: `env_problems` now checks every value as the text it binds (`to_string(value)`), not only strings.
       That made the second check loop in `bind_env` redundant: `bind_env` now runs `env_problems`, then converts
       (net simpler).
     - Test: `TestNamesAgreeEverywhere::test_a_literal_container_is_checked_as_the_text_it_binds[object|array]`
       asserts a validator ERROR at `params.env.DATA` and a `CompilationError`. Mutation (restore the str-only
       check) → 2 failed.
  3. **(2b) The unencodable-text error advises `stdin:`, and stdin fails too** (agent-ux W1). **Confirmed, NOT
     fixed — handed back.**
     - Reproduced: a `ShellNode` with `stdin: "cut \ud800"` → `UnicodeEncodeError` at `shell.py:885`, then
       `exit_code -2`.
     - Fixing it changes ruled text: checkpoint §4f says the unencodable message has the NUL message's "same
       shape", stdin remedy included.
     - Options: (a) the lens's wording, *"Repair the invalid Unicode in the upstream value before binding DATA —
       passing the same text through stdin fails too."* (recommended: true advice, importance 2, one string plus
       one test assertion); (b) keep the ruled text (a known-wrong remedy on a rare path); (c) (a) plus make
       stdin's own encode failure a pre-spawn error. (c) is out of Part 1 scope and changes the stdin contract.
  4. **(C1) The carried-loop test could not detect a broken carry** (test-fidelity, Critical/false confidence).
     **Confirmed, fixed.**
     - Why it was blind: round 1 already printed `{"a": 1}`, so round 2 looked the same whether the carry was
       used, bypassed, or left unparsed.
     - The test now logs each round's `$STATE` to a file. The step prints a compact `{"b":2}` that differs from
       the seed, and the test asserts the log reads `{"a": 1}|{"b": 2}|`.
     - Mutations, each restored by byte copy: carry bypassed (`loop_control.apply_carry_overrides` ignores
       `carry`) → 1 failed; `inputs:` no longer auto-parsed → 1 failed.
  5. **Suggestion: restore `${cfg.env}` in the 4e run-time message** (agent-ux). **Skipped (disputed).** This is
     deviation 3, already accepted by the orchestrator: the node sees only the resolved value. The PR body names
     it as a checkpoint text delta.
  - Verified clean, per the report: impact-completeness (no missed consumer; `node_type` survives `replace`),
    feature-interactions, simplicity (no simplification found), silent-failures, concurrency-safety (fresh dicts,
    deep-copied workers, `os.environ` untouched), validation-consistency (apart from 2a), and test-fidelity
    (apart from C1).
- Verified: `make check` green; `make test` **10460 passed / 0 failed** (10458 + 2 new 2a items).
- Changed: `src/pflow/nodes/shell/env_binding.py`, `src/pflow/guide/nodes/shell.md`,
  `tests/test_integration/test_shell_env_binding.py`; new `implementation/gate-part1-report.md` (the merged report).
- Deviations/surprises: the fan-out lenses do not execute anything (stated in the report's limits). Windows D8
  and the Linux size outcome remain CI items, as planned.
- [RULING, orchestrator, importance 2] Finding 3 (2b) → **option (a), applied.** This corrects factual advice
  inside checkpoint §4f's ruled shape; the rule is unchanged.
  - The unencodable-value message now reads: "… contains a character the operating system cannot put in an
    environment variable. Repair the invalid Unicode in the upstream value before binding DATA — passing the same
    text through stdin fails too."
  - The full sentence is pinned in `test_text_the_os_cannot_encode_is_refused_naming_the_variable`.
  - The NUL message keeps its stdin advice, verified: `ShellNode` with `stdin: "a\0b"` and `od -c` → exit 0,
    output `a  \0   b`, so a NUL survives stdin.
- Follow-up (option c, not built, pre-existing, out of Part 1): stdin's strict UTF-8 encode (`shell.py:885`) turns
  unencodable text into `UnicodeEncodeError` → the exit -2 path, which `ignore_errors` swallows. The orchestrator
  carries it to the PR body.
- Gate after the ruling: `make check` green; `make test` 10460 passed / 0 failed.
- Next: orchestrator commits; falsifier last.

## [2026-10-07 01:20] implementer I1 (Opus) — gate — falsifier (evaluated on `cba59617`)
- Did: evaluated `implementation/gate-part1-falsifier.md` (direct-launch `review-falsifier`, real CLI, no Critical).
  Checked each finding against the code before acting, following the orchestrator's steer.
- Findings and dispositions:
  - **W1 — a lone surrogate never reaches the user as the ruled message. Not fixed in Part 1 (steer
    confirmed).**
    - Verified: `runtime/workflow_trace.py:999-1016` `_flush_line` catches only `OSError`, although its docstring
      promises never to mask a real node error. `core/trace_io.py:116` does a strict `value.encode("utf-8")`.
    - So `prep()` raises the right `EnvBindingError`, then `record_trace` re-raises a `UnicodeEncodeError` over
      it. This is pre-existing: the same text in any param crashed the writer before Part 1. Part 1 does not
      widen it, and the command is still never spawned.
    - Added a docstring on `test_an_unbindable_value_under_ignore_errors_and_retry`: runner-level evidence with
      trace streaming off, and the CLI path is currently masked by this trace-writer defect.
    - **Follow-up for the orchestrator to file.** Repro: upstream `printf '%s' '{"s":"cut \ud800"}'`; next shell
      step `ignore_errors: true`, `env: {DATA: ${up.stdout.s}}`. Observed: `'utf-8' codec can't encode
      character '\ud800'…`, and the JSON error has no `node_id`. Fix site: `_flush_line` (catch encode errors
      too, or encode with `surrogatepass`/`backslashreplace` in `trace_io`).
  - **W2 — literal YAML numbers are reinterpreted silently (`1.10`→`1.1`, `0755`→`493`). Guide sentence only;
    the warning extension is a follow-up.**
    - Guide (`env:` section) now says: "`VERSION: 1.10` binds `1.1`, `MODE: 0755` binds `493` — quote a value
      whose exact text matters (`VERSION: "1.10"`)."
    - Real run: `env: {VERSION: 1.10, MODE: 0755}` printed `1.1 493`.
    - A numeric-literal warning needs the source text, which the IR does not carry. Follow-up for Task 120 /
      Part 2.
  - **S1 — YAML-word keys give a looping fix; the boolean warning mis-advises. Fixed. [Importance-1 deltas to
    ruled text, per the orchestrator.]**
    - (a) For a key YAML read as null or a boolean (`NULL:`, `YES:`, `OFF:`), the name error's fix is now "YAML
      read this key as a {null|boolean}, not text: quote the key so it stays the name you wrote." It no longer
      suggests `NULL`/`TRUE` back. New helper `_name_fix` in `env_binding.py`; number keys keep the ruled
      `VAR_1` fix. The first sentence is unchanged (ruled §4b; the author's spelling is lost in YAML parsing).
    - (b) The literal-boolean warning's fix `Quote it ("true") …` became "Quote the value if the command compares
      text." (for `YESV: yes` it advised changing `yes` to `true`).
    - Tests: the unit test `test_a_yaml_word_key_is_told_to_quote_not_given_a_yaml_word_back`; the integration
      test `test_a_non_text_yaml_key_is_named_and_fixed` now covers `1`, `YES` and `NULL` from real markdown
      (fixes asserted exactly); `test_a_quoted_yaml_word_key_is_a_valid_name` shows the fix works (`"NULL": v`
      validates clean); the boolean-warning assertion was updated.
  - **O1 — a sub-workflow `inputs:` boundary re-serializes. Guide made true; pre-existing (#686/Task 120).** The
    "first passes through an `inputs:` map" clause now lists the step's own, a loop carry, and a sub-workflow's
    inputs.
  - **O2 — CLI `key=value` inference types values before binding. Guide made true.** Added "a `key=value` given on
    the command line is typed first (`007` → `7`)"; verified `infer_type('007')` → `7`.
    - **Follow-up observation:** a declared `type: string` input still receives the inferred type
      (`v=007` → `7`, `v=true` → `True`) — `cli/param_parsing.py:9-46`. Pre-existing; for Task 120.
- Changed: `src/pflow/nodes/shell/env_binding.py`, `src/pflow/core/workflow/validator.py`,
  `src/pflow/guide/nodes/shell.md`, `tests/test_nodes/test_shell/test_env_binding.py`,
  `tests/test_integration/test_shell_env_binding.py`.
- Verified: `make check` green; `make test` **10461 passed / 0 failed**.
- Deviations/surprises: none beyond the two ruled-text deltas above, which the orchestrator authorized
  (importance 1). The checkpoint file is not edited; it stays the record of what was ruled.
- Next: orchestrator commits.

## [2026-10-07 01:30] task orchestrator (Opus) — Part 1 gate closed; spec Status → in progress; PR next
- Did: verified I1's falsifier dispositions (01:20 entry) and committed them with the falsifier report
  (`implementation/gate-part1-falsifier.md`); spec `## Status` → `in progress` (plan §4.0: Part 1 is not task
  completion; no task-review until Part 2 — a stated exception ruled in the plan and the launch packet).
- Gate record: reading battery 8/8 lenses via the converted fan-out (00:45) + `review-falsifier` direct, last
  (01:20). Every finding dispositioned; none open. Follow-ups carried to the hand-back/PR body: trace writer masks a
  node error on unencodable text (W1); numeric-literal warning in `env:` (W2 → Task 120/Part 2); a declared
  `type: string` CLI input is still type-inferred (O2 → Task 120); stdin's strict UTF-8 encode falls to the
  exit -2 path (00:45 option c).
- Next: merge origin/main, `make check` + `make test-all-local` on the merged result, `create-pr`.

## [2026-10-07 02:10] task orchestrator (Opus) — PR #723 open; tests-windows answered D8; CP-2 FIRES (D8-2 second row) — PARKED-ON-RULING
- Did: `create-pr` → PR #723 (no closing refs — verified `closingIssuesReferences: []`); merged origin/main
  `2a3f73ef` first (the #690 resume-preflight lane; clean merge; `make check` + `make test-all-local` 10536 passed /
  2 skipped on the merged result `cc9c2755`). CI on `cc9c2755`: every job green except `tests-windows
  (core-cli-nodes)` — 1 failed / 6262 passed. Pushed one evidence probe (`54804587`) and re-ran.
- **D8 outcomes (tests-windows, Python 3.13, Git Bash):**
  - D8-1 a native path bound in `env:` is readable as `cat "$FILE"` — PASS (values are data; no translation).
  - D8-2 row 1 `env: {Path: X}` → exactly one PATH-named variable holding X, inherited entry gone — PASS.
  - D8-3 hostile value byte-identical, `$(touch …)` inert — PASS.
  - D8-4 a 200 KB value on win32 — **binds** (`exit_code=0 stdout='200000'`); pinned in `ffed0647` (no Windows
    E2BIG branch, per D3). Linux refuses one value over 128 KiB — confirmed by every ubuntu job; guide states it.
  - **D8-2 row 2 FAILED:** `env: {Temp: bound-temp}` beside an inherited `TEMP` → the child holds
    `TEMP=/d/a/pflow/pflow/bound-temp` and `$Temp` is empty (CI evidence string `'|TEMP=/d/a/pflow/pflow/bound-temp;'`).
    Git Bash's runtime imports `TEMP` upper-cased AND path-converts its value (relative text made an absolute POSIX
    path). Evidence row `PflowD8` beside inherited `PFLOWD8` — PASS: outside Windows' well-known path names the
    authored spelling holds and the value is untouched. Assumed (Cygwin's documented import list, not observed):
    `TMP`, `HOME`, `TMPDIR` behave like `TEMP`; `PATH` is the same mechanism (D8-2 row 1 passes because a PATH
    value is meant to be converted).
- CP-2 (plan §9; builder notes predicted this row): the plan routes a D8-1..3 failure to the user as a design
  fork. Options handed up (main orchestrator → user): (a) accept + document + pin — one guide line ("on Windows,
  Git Bash reads PATH, TEMP, TMP (any spelling) upper-case and converts their values to POSIX paths — use another
  name for data"), the failing row rewritten to pin the observed behaviour, no product code; (b) (a) + add
  TEMP/TMP to the shell-owned warning list (changes ruled 4d's seven-name list); (c) normalize these names on
  win32 ourselves — cannot stop the runtime's path conversion; not recommended. Recommendation: (a).
- State: branch head = this entry's commit (pushed); tree clean; PR #723 CI red ONLY on that row. No implementer
  live (I1 idle, ~392k tokens; holds the PA code). No dev servers.
- **Resume point:** on the ruling, apply it (a: guide line in `guide/nodes/shell.md` env section + rewrite
  `test_d8_2_a_mixed_case_name_colliding_with_an_inherited_one_reads_by_its_spelling` into a pinned
  per-platform assertion — win32: `$TEMP` holds the POSIX-converted value and `$Temp` is empty; POSIX: `$Temp`
  reads its value), `make check` + `make test`, commit, push, wait for CI green on #723, amend the PR body's
  Windows paragraph with the D8 outcomes, hand back at create-pr with head SHA + `gh pr checks` snapshot naming
  `tests-windows (core-cli-nodes)` + `dev servers: none`. Do not merge.

## [2026-10-07 02:40] task orchestrator (Opus) — CP-2 RULED (a); applied
- [RULING] (main orchestrator, under the user's end-to-end grant, importance 2): **(a)** — accept, document, pin.
  Guide states only what was observed. Deltas 1–5 from the checkpoint text accepted as logged; follow-ups 1 and 4
  (unencodable text masked by the trace writer / stdin's -2 path) filed by the main orchestrator at merge; 2 and 3
  go to Task 120's spec.
- Did: `guide/nodes/shell.md` Names bullet: "On Windows, Git Bash imports Windows path variables such as `PATH`
  and `TEMP` upper-cased, with their values converted to POSIX paths — use another name for data." The two D8-2
  second-row tests folded into one — `test_d8_2_a_case_colliding_name_keeps_its_spelling_except_windows_path_variables`:
  presence first (`PflowD8` beside inherited `PFLOWD8` reads by its spelling, value untouched, every platform),
  then the pinned exception (win32: exactly one `TEMP=` entry, value an absolute POSIX path ending `/bound-temp`,
  `$Temp` empty; POSIX: both spellings, `$Temp` = bound value — regression guard).
- Assumed (Cygwin docs, NOT observed, deliberately not in the guide): `TMP`, `HOME`, `TMPDIR` are imported the same
  way as `TEMP`.
- Verified: `make check` green; `make test-all-local` 10536 passed / 2 skipped; CI pending on push.
- Next: push, wait for #723 CI green, amend the PR body's Windows paragraph, hand back at create-pr.

## [2026-10-07 22:40] task orchestrator (Opus) — Part 2 boot (implement-from-plan, PD → PC → PB → PE → PF → PZ)
- Did: verified the worktree `feat-task-118-part-2-bodies-untemplated` at `a296ceca` = `origin/main`, tree clean;
  read spec + starting-context, plan, checkpoint (ruled), this log (CP-1 ruled 00:20; CP-2 ruled (a) 02:40), the
  Task 170 review, Task 179's serialize list (resume seam — Part 2 does not touch it), ADR-0016.
- Verified: `src/`+`web/` delta `b2cd92e3..a296ceca` = Part 1 itself, #690's resume files, #714's gate panel —
  none on a PD/PC/PB/PE surface except the Part 1 files the plan builds on. Plan file:lines are re-verified by
  each implementer before editing (plan header).
- Packet facts recorded here so they survive this context:
  - Parallel lanes: #720 (`ui/run_tailer.py`, `ui/server.py` `/api/gate`, web gate-panel components; maybe a
    READ-side blob resolve in `core/trace_io.py`), #724 (`runtime/workflow_trace.py` `_flush_line`,
    `core/trace_io.py` encode; maybe a `stdin:` encode-error route in `nodes/shell/shell.py`). Editing
    `trace_io.py`/`shell.py` → log it, expect a rebase; editing `workflow_trace.py` → STOP, hand back.
  - v0.16.0 is cut from `main` before Part 2 merges: merge main and re-run the full gate before `create-pr`;
    the merge is the main orchestrator's (plan §4.0).
  - Task 181 requests (plan on `feat/task-181-mcp-code-params-json` @ `924b7d94`, §0 checks 4–5): (1) D5 step 1's
    per-step scope rule as ONE named public helper 181 can call alone; (2) an "add to used" seam in the unused-
    input pass. Both are PB's; evaluated against D1/D5 there and the decision logged — no generality beyond them.
  - Task 120 extends the `env:` no-parse rule as a per-leaf predicate (`binds_as_text`/`parses_leaves`) — never a
    `key == "env"` branch.
  - `tests-windows (core-cli-nodes)` executes this change; `test_stdin_no_hang_integration` flaked once (re-run
    first). A D8 test failure is CP-2 territory (hand back).
  - CONTEXT.md is the main orchestrator's (plan §11) — not edited here.
- Next: launch I2 (Opus · medium) on PD → PC1, bundled per plan §4 (PD's tests get test-reflect, directed now).

## [2026-10-07 23:05] implementer I2 (Opus) — Part 2 baseline (head a296ceca, before any edit)
- Did: the four baselines; saved every Task-159 case's ACTUAL output (P0 recorded only the drift set).
- Changed: `implementation/baseline/task159_actual.sh` (new — runs each case in place exactly as `run-case.sh`
  does, copies the normalized stdout/stderr/exit code out, restores the committed `expected-*` bytes);
  `implementation/baseline/task159-before/<case>/{stdout,stderr,exit-code}.txt` (87 cases).
- Verified (executed, macOS): `make test` **10484 passed / 0 failed** (failing set empty). `inventory.py` **426 sites
  / 126 files** = §2.5's 428/128 minus `workflows/` (2/2, converted by Part 1 — row now absent); every other area
  row equal to §2.5. `verify.sh` **75 / 12 / 0**, drift set = §2.5 by name. `capture.py --check` **29 / 1 differing**
  (`error-handling/typo-on-failed-node`, = §2.5). Harness check: the 87 saved actual outputs equal the committed
  expected files for exactly the 75 passing cases and differ for exactly the 12 drifted ones; `git status` on
  `task_159/` clean after the capture.
- Deviations/surprises: the capture must run each case in its real directory — a copy outside the repo changes the
  repo-relative paths the CLI prints (first attempt: 61 false diffs; `/var` vs `/private/var` was another 35).
- Next: PD.

## [2026-10-07 23:40] implementer I2 (Opus) — PD What ran stays answerable
- Did: D9 display-safe copy (`env_binding.displayable_env`: `redact_sensitive` by name, each value capped at 200
  chars + `… (N chars — full value: pflow report)`, `\n` escaped), written by `ShellNode.post()` only when the
  action is `"error"` and something is bound; enrichment → `context["shell_env"]` (placed after `shell_command`,
  matching the ruled JSON order); `_SHELL_DISPLAY_FIELDS` gains `env`; ONE `_format_shell_env_lines(env, indent=)`
  serves both shell blocks (the redaction note keyed on `is_sensitive_parameter(name)`, the same rule that made the
  copy); report `## Command` (from the step's `node_params`, always, shell steps only — keyed on
  `node_type_tag(...) == "shell"`) + `## Env` (`redact_sensitive({k: to_string(v)})`, full length; a batch item reads
  its own `template_resolutions["env"]`, else the host's params), `env` out of `## Resolved Parameters` and `## Output`.
- Changed: `nodes/shell/{env_binding.py, shell.py}` (**shell.py edited — lane #724 rebase expected**: `post()` is now
  a 4-line wrapper over the old body renamed `_store_and_route`), `execution/executor_service.py`,
  `runtime/engine/template_errors.py`, `core/diagnostic_render.py`, `core/trace_report.py`; tests: new
  `tests/test_integration/test_shell_failure_display.py` (16), `tests/test_core/test_trace_report.py` (899/1571/2457
  rewritten → 3 node-file tests + the batch-item test + the redaction test's `## Env` block),
  `tests/test_nodes/test_shell/test_auto_handling.py:183` (hand-built `prep_res` gains `"env": {}` — `post()` reads it).
- Verified: `make check` green; `make test` **10502 passed / 0 failed** (baseline 10484 → +18, all mine; failing set
  empty). Real surface (`uv run pflow` + `pflow report`, checkpoint §6/§7 probe `echo "calling $ENDPOINT" >&2; exit 3`
  with `ENDPOINT=users`, `API_TOKEN=sk-secret-123456`): the text block, the JSON error (`shell_env` in `context` and
  top level) and the report page reproduce the AFTER text verbatim; a batch probe's `item-1-beta.md` shows the static
  command and `{"ITEM": "beta"}`. Trace format untouched (D12) — the copy is node output the trace already records.
- Deviations/surprises:
  1. **Not built: "popped on success" (D9).** Mutation M2 (removing the pop) left every test green, and the code says
     why: a failing step's whole namespace moves into `__failures__` (`runtime/node_state.py::mark_node_failed`,
     "the original namespace key is removed") and a revisit starts from an empty one — a stale copy cannot survive
     in any engine path, so the pop was dead code. Removed it; PD test 9 stays as the labelled regression guard of
     that archival premise (it is the test that would see a stale copy if archival changed). Importance 1. A trap
     found on the way, for anyone who re-adds it: `NamespacedSharedStore.pop("env", None)` raises `KeyError` when the
     ROOT has an `env` key (a step or input named `env`) — the mixin's `pop` reads through to the root, then
     `__delitem__` refuses to delete there (executed).
  2. `## Command` is gated on the shell node type (plan: "for a shell event") — a non-shell param named `command`
     (an MCP tool's) now lands under `## Resolved Parameters` instead of being rendered as bash; pinned by a test.
  3. A batch item of an OLD-form step (templated command) now shows the host's template text in `## Command`
     (items carry no params; the old code read the item's resolved command). Transitional only — after PB no body
     is templated; PC converts the corpus first. Kept the final-code shape (one source) instead of a fallback PB
     would delete.
  4. Plan PD's Files line says "+ the redaction where the block's data is built" (`template_errors.py`): not needed —
     the copy is display-safe at the source (D9), so the referenced-failure block only had to list `env`.
- Self-checks: **test-reflect (directed):** ran ten mutations, each restored from a byte copy (`cmp` clean), counted
  reds over the PD test files: M1 copy never written → 9 failed; M2 no pop → 0 (→ deviation 1); M3 not redacted → 6;
  M4 not capped → 3; M5 `env` missing from `_SHELL_DISPLAY_FIELDS` → 1 (test 6); M6 item page reads host params →
  3; M7 no `shell_env` enrichment → 7; M8 report shows typed values → 2; M9 no shell type gate → 1; M10 `env` repeated
  under Resolved Parameters → 2. DELETED a redundant tail assertion in the length test (the exact 200-char line
  already fails on an uncapped value). LABELLED as regression guards (they pass on pre-PD code): test 5's success
  half, test 7 (code page), test 8a (a top-level batch's error records carry no node output — M3/M4 left it green,
  as expected), test 9 (see deviation 1). Every absence assertion is paired in the same output with a presence
  (`<REDACTED>` / `PAYLOAD-START` / the `Env:` lines / `## Env`). **Fully happy?** Yes, with one honest note: on
  Windows these tests rely on Git Bash `printf`/`touch`/`>&2` like the rest of the shell suite — not run here.
- Next: PC1 — node-output dumps and the instrumented suite run on the unconverted tree first.

## [2026-10-07 23:55] implementer I2 (Opus) — PD amended per orchestrator ruling (A)
- Did: [RULING, orchestrator, importance 1–2] (A) acknowledged and applied — a batch item's `## Command` and `## Env`
  each read the ITEM's own `template_resolutions[<param>]["resolved"]` when present, else the host's
  `node_params[<param>]` (one helper, `trace_report._resolved_or_static`). **This reverses PD deviation 3** (the
  host-only command): a legacy trace keeps the item's resolved command. `## Env` already had this rule.
- Changed: `core/trace_report.py`; `tests/test_core/test_trace_report.py` +2
  (`test_item_with_literal_env_reads_it_from_the_step`, `test_legacy_item_keeps_its_own_resolved_command`).
- Verified: the two new tests + the PD files 230 passed. Mutations (byte-copy restored): command host-only → 1 failed
  (legacy test); env item-only → 1 failed (literal-env test). (B) noted for PC1 — see its entry.
- Next: PC1.

## [2026-10-08 00:55] implementer I2 (Opus) — PC1 corpus conversion (examples, Task-159 baseline, guide/docs/MCP fences)
- Did: before converting — the node-output tool and before-dumps, then ONE instrumented suite run (temporary hook in
  `split_params` + `iter_node_surfaces`, removed; `git diff` on both files empty). Then converted by §5 (no braced
  `${NAME}` in any body — D13), the `git-worktree-task-creator` hand case (Layer 0 deleted), harness edit (1) only,
  the PC1 tests, react-flow fixture regen, golden hashes; wrote and ran `equivalence.py`.
- [RULING, orchestrator] (B) acknowledged: only harness edit (1) (`drifted_node_ref` → `env: {V: ${ghost-node.result}}`,
  body `echo "$V"`) landed; edit (2) (`_BARE_VAR_RE` → `template_params`) was never made — it is PB's.
- Changed: 20 example files + `examples/workflow_manager_demo.py`; Task-159 `02/03`, `04/03`, `_shared/.../fetch-source`;
  guide `features/{batch,branching,sub-workflows}.md`, `nodes/shell.md` (fences only); `docs/how-it-works/template-variables.mdx`,
  `docs/reference/nodes/shell.mdx`; both `mcp_server/resources/instructions/*.md` (8 fences each); tests
  `test_core/test_graph_build.py:1378` (edge `input_name` `command` → `PREV`), `test_runtime/test_worktree_creator_workflow.py`
  (`:57` → `ROOT: ${get-repo-root.stdout}` in the env block; +1 test: `safe_description` escapes only the two
  do-script layers), `test_docs/test_guide_example_validation.py` (edit 1); `web/src/test/fixtures/contracts/prompt-caching-multi-chunk.json`
  (regen: `env` param added, command static, source lines +2, edge `input_name` → `SESSION_ID`);
  `tests/test_runtime/fixtures/golden_config_hashes.json`. Tools/evidence (new, `implementation/`): `baseline/node_outputs.py`,
  `baseline/node-outputs-{before,after}/`, `baseline/task159-after/`, `equivalence.py`, `baseline/equivalence-run.txt`,
  `pc-instrumented-hits.txt` (77 files / 419 tests, each tagged PC1 / T3 / PC2 — **the PC2 scope**).
- Verified (executed):
  - node-output dumps (7 runnable workflows incl. `document-processor`; dump stable across two pre-runs): **identical** before/after.
  - `capture.py --check`: 29 / 1 differing — output byte-identical to the baseline run (only the pre-existing
    `typo-on-failed-node`). **Not re-captured**: the only hunk is the P0 drift; re-capturing would launder it.
  - `task159_actual.sh` actual-vs-actual: 86/87 identical; the one diff is `12-…/04-guide-auto-detect` (snapshots guide
    text; drifting since P0) and every hunk is a guide fence this phase converted. Not regenerated (drifted at P0; PF
    regenerates after the prose). `02/03` and `04/03` (converted) print the same output.
  - golden hashes: test listed exactly 10 drifted nodes, regenerated, diff = those 10: `batch-test{,-parallel}::greet_users`,
    `template-variables::{api_caller,notifier}`, `git-worktree-task-creator::{create-worktree,copy-folder,output-status,
    launch-cursor,launch-cli,parse-result}`. `parse-result` is the hand case (its code lost Layer 0) — not a body conversion.
  - `--validate-only`: valid — changelog, worktree-creator, vision-scraper, execute-plan, the three agent examples,
    `batch-test*`, `template-variables`, `prompt-caching-multi-chunk`. `release-announcements` / `live-reload` fail ONLY
    on uninstalled MCP servers (unknown `mcp-composio-*` type / `pageId` param); the error set is identical to the
    unconverted file's (diffed), none mentions env/command.
  - `inventory.py`: 0 in `examples/`, `workflows/`, `task_159/`, `src/pflow/guide`, `docs`, `src/pflow/mcp_server/resources`.
    Remaining `src` row = `registry/context_builder.py` — a false positive (the code snippet has no `${`; the scanner
    attributes a neighbouring stdin snippet). Tests: the PC2 set, plus two new rows that are intentional/false
    positives: `test_trace_report.py:1643` (ruling A's legacy-trace fixture — an old-form command in trace data) and
    `test_shell_failure_display.py:584` (f-string with a static fence). Architecture JSON-IR grep: 7 sites, all in
    `architecture/reference/template-variables.md` (PF §7) — not touched.
  - `equivalence.py` (every changed shell step in `examples/`, stub PATH printing argv+stdin, fresh cwd per side):
    benign — identical except (a) the three agent `$${…}` reports: the old form was broken (`bad substitution` —
    `$${x}` reached sh as `${generate.llm_usage.cost_usd}`), now prints `$0.0123`; (b) changelog `get-commits`,
    `get-docs-diff`, `fetch-pr-data`, `get-file-changes`: the old unquoted form word-split a value with spaces; real
    values (tag, PR number, sha) are single tokens, so quoting changes nothing; (c) changelog `output-summary`: argv differs
    by design (`jq --arg`); real-jq run identical for `CHANGELOG.md`, and the old form fails to parse for a hostile path.
    Hostile — every OLD/NEW difference is the old form pasting the value into sh text (quotes broke, `$5` expanded,
    words split); NEW carries every value verbatim except where the value is only compared or its branch is not taken
    (`OVERWRITE`, `OPEN_CLI`, `OPEN_CURSOR`, `DESCRIBE_IMAGES`, `BASE`/`ROOT`/`WORKTREE`/`TARGET_URL` on untaken branches).
  - **Hand case:** `launch-cli` with `osascript` stubbed and a real worktree dir, description `it's "q" $5 \`id\` \ back`:
    the do-script text is **identical** old (Layer 0 + pasting) vs new (no Layer 0 + `env:`). Negative control: keeping
    Layer 0 in the new code → `DIFF hostile … launch-cli` (restored by byte copy).
  - `make check` green; `make test` **10505 passed / 0 failed** (PD 10502 + 2 ruling-A tests + 1 worktree test).
  | Not run: `web/` tests on the regenerated contract fixture (no `node_modules` in this worktree) — `lossless.test.ts`
  sweeps it generically; PE runs `npm test`.
- Deviations/surprises:
  1. Two fences that were not plain conversions (docs, importance 1): `template-variables.mdx`'s escape example is now a
     `write-file` `content: "Price: $${PRICE}"` (PF's stated decision, done here because D13 converts fences in PC; the
     surrounding prose stays true); `nodes/shell.mdx`'s **Wrong** example became `echo "$RESPONSE" | jq` bound in `env:`
     and its one-line label now names the real problem ("structured data bound through `env:` (the OS caps its size; use
     stdin)") — the old label would have been false over the new fence.
  2. `guide/features/sub-workflows.md` take-and-write keeps `inputs: {iteration: ${iteration}}` (it consumes the child's
     declared input; the body never read it) and binds `QUEUE` in `env:`. **PB: the unread-`inputs:`-key warning will
     fire on this guide fence** — decide there (bind it, or drop the input from the example).
  3. Names chosen for content where the old alias was opaque: `raw` → `QUEUE`; worktree-creator `create-worktree` binds
     its existing locals `WT`/`BR`/`BASE` directly (assignments deleted), `copy-folder` binds `FOLDER`/`ROOT`/`WORKTREE`
     directly; agent examples split quotes as `"…$DURATION_MS""ms…"` (a name character follows; no braces — D13).
  4. Inventory `--files` before/after shows `tests/` rows unchanged except the two noted above (PC2 untouched).
  5. The guide/MCP prose around converted fences now contradicts them in places (`shell.md` "Templates in Shell Commands …
     resolve before the shell runs", "`${var}` = pflow template") — PF's, as planned.
- Self-checks: **Fully happy?** Yes for the corpus: every runnable output is identical, every non-runnable step was
  executed under stubs and each difference explained, the hand case is proven with a negative control. Open, for
  others: deviation 2 (PB), `web/` tests (PE), the 7 architecture JSON sites and the prose (PF). test-reflect: not
  needed — the gate tools are the test (the one new unit test, Layer-0, was checked by computing the expected
  string by hand and by the harness's negative control).
- Next: orchestrator commits PD + PC1; PC2 (I3) from `pc-instrumented-hits.txt`.

## [2026-10-07 23:05] task orchestrator (Opus) — cross-model plan read (codex review-plan, relayed by main) — dispositions
- Source: `/Users/andfal/projects/pflow/scratchpads/session-12/fanout-plan-mode/report.md` (claims; 5 W, 0 C). Each read
  against code on `a296ceca`. None changes a phase order or a seam decision → no hand-back.
- (1) PC needs `template_params` before PB creates it — **ADOPTED (relocated).** PF/PC's harness edit (2)
  (`_BARE_VAR_RE` → names from `template_params`) moves to PB; edit (1) (`drifted_node_ref` → `env:`) stays in PC.
  PC writes no braced `${NAME}` in a body (D13), so the harness needs (2) only once bodies may hold `${HOME}`.
  Sent to I2 mid-PC1.
- (2) A fifth `is_file_reference` param site — **ADOPTED for PB.** Verified `core/file_resolver.py:183-200`
  `_resolve_batch_file_references` B2 loop calls `is_file_reference(value)` per batch-item key at :192 with no
  node type. PB routes it through the same `is_param_file_reference(node_type, key, value)` and tests inline and
  file-loaded batch items; PB's brief says: grep EVERY `is_file_reference` caller over a param value, the plan's
  count is not the gate.
- (3) Prediction walk narrowed by `template_params` — **ADOPTED (row dropped).** Verified: `_node_templates_touch`
  (`predict.py:362`) is reached only through `_node_references_any` over `llm_nodes` (`predict.py:229, 251-252`), so
  a shell/code body never reaches it, and `template_params` would drop its `batch`/`inputs` coverage. D7's
  `predict.py` row is not built.
- (4) PD batch-report fallback — **ADOPTED.** Item page: the item's own `template_resolutions[param].resolved`
  first, else the host's `node_params[param]` (literal `env:` is static → absent from item resolutions; legacy
  traces carry the resolved command per item, pinned at `test_trace_report.py:1571`). Sent to I2 mid-PD with two
  tests (literal-only env item page; legacy-shaped item command).
- (5) PE full-tier fallback — **ADOPTED for PE.** Verified `web/src/graph/sourceDecorate.ts:311-325`
  `highlightBlock` falls back to `content.map(refSegments)` for every grammar on null/line-mismatch. PE brief: teal
  refs only where the full tier's successful path would (markdown), in the instant tier AND the fallback; tests for
  null result and line-count mismatch.

## [2026-10-08 01:20] task orchestrator (Opus) — PD + PC1 verified and committed
- Verified: read I2's four entries; `make check` green, `make test` 10505 passed / 0 failed (mine, on the final tree).
  "Fully happy?" asked: yes. Its unlogged residue, for PC2: the hit list predates PC1 (rows tagged PC1 should clear —
  confirm, not assume); it names tests, not lines (map helper-built workflows via §6's helper names); it covers
  `make test` + `make test-e2e` only (marker-excluded tests are not in it); `test_trace_report.py::
  test_legacy_item_keeps_its_own_resolved_command` keeps an old-form command ON PURPOSE (ruling A) — never convert it.
- Accepted deviations: D9's success-path pop not built (dead code — a failed namespace moves to `__failures__`;
  test 9 guards the premise; importance 1); `## Command` gated on the shell node type; the two docs fences rewritten
  rather than converted (PC1 dev. 1). Carry-overs: PB — the sub-workflows guide fence's unread `inputs: {iteration}`;
  PE — `npm test` on the regenerated contract fixture; PF — 7 JSON-IR sites in `architecture/reference/
  template-variables.md`, prose contradicting converted fences.
- Not committed, deliberately: `implementation/baseline/task159-{before,after}/` (522 files, 2.8 MB of normalized CLI
  output). Regenerable: check out `a296ceca` and run `implementation/baseline/task159_actual.sh`. Kept untracked in
  the worktree for PZ's actual-vs-actual comparison; deleted before the PR.
- Next: launch I3 (fresh, Opus · medium) on PC2 from `implementation/pc-instrumented-hits.txt`.

## [2026-10-07 23:54] implementer I3 (Opus) — PC2 test-suite conversion (env: binding, old semantics)
- Did: converted every PC2 site from `pc-instrumented-hits.txt` + §6 (incl. "missed"/helper sites) by §5 — T1 → `env:`
  (no braced `${NAME}` in any body, D13), T2 → the §6 param, T4 → static body + PD surface, T5 → `inputs:`; ran the
  instrumented suite before and after with a fresh temporary hook (I2's was not preserved), then removed it.
- Changed: 76 test files under `tests/` (cli, core, execution, integration, mcp_server, runtime incl.
  `test_template_validation/`); no `src/` change. Mechanical IR-literal sites went through a scratch converter
  (§5.3 quote-state rules, names per §5.2 with `is_sensitive_parameter` + `AMBIENT_NAMES` checks — 0 hits over all 129
  chosen names); markdown/f-string sites by hand.
- Verified (executed):
  - Hook: logs `(PYTEST_CURRENT_TEST, node id, param, site)` when `(shell, command)`/`(code, code)` holds
    `TemplateResolver.has_templates`; `split_params` reads `node_type`/`node_id` from the compiler frame.
    BEFORE (head `eee01b34`): `make test` 10505 passed + `make test-e2e` 52/2 skipped; every PC1-tagged row is ABSENT
    (react-flow fixtures, example/guide validation, multi-chunk, golden hashes, template_parity) — confirmed, not assumed.
    AFTER: 10504 + 52/2; remaining hits = only T3: `test_types.py` (the same 28 tests) and
    `test_loop_validation.py::test_shell_carry_key_referenced_via_nested_path_no_warning`; zero subprocess-child hits.
    Hook removed: `git diff` on `template_surfaces.py` + `template_resolution.py` = 0 lines.
  - `inventory.py --files`, tests rows left: T3 — `test_types.py` 28, `test_command_validation.py` 3,
    `test_loop_validation.py:460`; the two intentional rows — `test_trace_report.py:1643/1650` (ruling A's legacy item,
    one test) and `test_shell_failure_display.py:584`; false positives — `test_trace_report.py:930` (PD's MCPNode
    `command` param, not a shell body), `test_loop_control.py:101` (§6: leave), and the inventory's python-manual
    heuristic (any f-string holding "shell command" and a `$`) on converted or body-free f-strings:
    `test_resume_cli.py:1204`, `test_plan_drift.py:2836`, `test_iteration_pattern.py:45`, `test_loop_config.py:1382`,
    `test_compiler_output_wrapping.py` ×2, `test_only_snapshot.py:1077`, `test_resume_engine.py:775`,
    `test_template_validation/test_validator.py:1056` — every one of them ran under the hook with zero hits.
  - `make check` green; `make test` **10504 passed / 0 failed** (baseline 10505, −1 = deviation 1); `make test-e2e`
    52 passed / 2 skipped (= baseline).
  - T1 outputs: every stdout/file assertion passed unchanged (no expected-output edit anywhere except deviation 3,
    which is a source line number, not command output). Real CLI: `uv run pflow --dry-run` on the converted
    `test_dry_run` shape fails with "Workflow requires input 'name'" (the reason its name states, not a leftover).
  - PD display-copy leak probe (`faninner`, batch items `SENSITIVE-*`): `SENSITIVE` occurrences in the carried
    `__failures__` bundle identical old-form vs env-form (2, both the display-safe `summary` fields).
  | Assumed: marker-excluded tests (paid/LLM) are not in the hook's net — the inventory (static) shows no body site in them.
- Deviations/surprises:
  1. `test_workflow_validator_code_param.py::test_string_code_is_accepted`: dropped the `"${upstream.stdout}"`
     parametrize case (−1 test). Not in §6; it is a templated code body (T5-shaped) whose only claim is "a string is
     accepted" — the validator has no template branch (`validator.py:133`), so the case was redundant with the plain
     string case and becomes meaningless once bodies are static. Importance 1.
  2. `test_core/test_file_resolver_integration.py` (not in §6; I2 tagged it): `test_compile_ir_detects_templates_in_file_content`
     moved to a file-loaded `stdin` (T2; `stdin` is in `FILE_RESOLVABLE_PARAMS`) and DEEPENED — it only asserted
     `workflow is not None`, which passes with or without detection; now asserts
     `node_configs["process"].template_config.template_params["stdin"] == "Processing: ${fetch.stdout}"`.
     `test_nested_workflow_file_refs_resolve_from_child_dir`: T1 (`greet.sh` reads `$NAME`, child binds `NAME`).
  3. `test_cli/test_cli_error_boundary.py`: the added `- env:` line moves the asserted parse-error entity from line 23 to
     24 — four assertions + the header comment updated. Fixture shape, not behaviour.
  4. `test_runtime/test_template_escape.py`: the hit file tags it T3, §6 says retarget the escape tests to `stdin` + `cat`
     IN PC — followed §6: all four escape tests now carry the escape on `stdin`; `…reaches_the_shell` renamed
     `…validates_and_stays_literal` (asserts `${PFLOW_TEST_UNSET_620:-world}` arrives literal — no shell expands it on
     stdin); the batch `results[0]["command"]` assertion dropped; `DOCS_ESCAPE_EXAMPLE` is no longer "verbatim" (PC1
     rewrote the docs fence to `write-file`) — it carries the docs' `"Price: $${PRICE}"` string. No T3 body site is
     left in this file; PB's two body tests (unescaped `${X:-world}`, `$${` in a body is the error) are still PB's.
  5. Names (importance 1): `${rounds.survivors[0]}` → `ROUNDS_SURVIVORS_0` (trailing `_` from `]` dropped; leading/
     trailing `_` stripped generally, as §5.2's `__index__` → `INDEX`); coalesce expressions named from the whole
     expression (`PRIMARY_STDOUT_FALLBACK_STDOUT`); `test_workflow_data_flow.py` helper `_wf` now takes the bare
     reference and binds a fixed `VALUE`; `test_graph_build.py:841` uses §6's `T`.
  6. `test_ir_schema.py:954` (`command: ${task.cmd}` — the item IS the command): `$TASK_CMD` left unquoted with a
     comment (word splitting relied on, §5.3); schema-only test.
  7. Converted beyond the hit list (inventory-visible): `test_cli/test_guide.py:438`, `test_core/test_markdown_parser.py:1650`,
     `test_core/test_ir_schema.py:954`, `test_runtime/test_prepare_inputs_extras.py:253`, `test_resume_engine.py`
     fences 1086/1256/1277/1356, `test_workflow_executor.py` 191/496, `test_trace_integration.py:915`, and
     `test_node_wrapper_template_validation.py:595/610` (`split_params` has no node type → key renamed to `prompt`, §6).
  8. T4 shape actually built: gate previews assert `preview["command"]` = the static body AND `preview["env"]` =
     `{NAME: resolved}` (`test_approval_gate_cli`, `rt/test_approval_gate` ×3, `rt/test_gate_trace` exact dicts,
     `test_cli_mcp_parity` paused text `command:`/`env:` lines); `test_trace_integration` asserts
     `template_resolutions == {"env": {...}}` (and per batch item `["env"]`), which also pins `command` absent.
  9. `test_loop_config.py`: renamed `test_shell_carry_threads_into_command_text_across_rounds` →
     `test_shell_carry_threads_into_env_across_rounds` (keeps `inputs: state` as the Carry target, binds `STATE`), per §6.
- Self-checks: **Fully happy?** Yes, with one stated limit: T2 discrimination was checked by reading each asserted
  message and spot-executing the ones that could go vacuous (loop-validation `__iteration__` messages identical
  old/new except `parameter 'stdin'`; dry-run reason via the real CLI; validate-only/mcp undefined-ref and cycle tests
  assert the ref/cycle text). `test_union_types.py`'s "0 warnings" cases rely on stdin being scanned — proven by its
  sibling that expects exactly 1 warning through the same `stdin` path. test-reflect: not needed — mechanical
  conversion; the instrumented run and byte-identical T1 outputs are the test (one non-discriminating T2 found and
  deepened — deviation 2).
- Next: orchestrator commits PC2; PB.

## [2026-10-08 02:05] task orchestrator (Opus) — PC2 verified and committed
- Verified: `make check` green, `make test` 10504 passed / 0 failed (mine). I3's entry (`[2026-10-07 23:54]` — real
  clock, sorts above I2's 10-08 entries) accepted with its deviations 1–9 (all importance 1).
- "Fully happy?" asked: yes. Residue for PB (I3, not logged by it): `env:` leaf edges ARE labelled by the dict key
  (executed: `env: {T: ${prep.rows}}` → `input_name='T'`); verdict flips expected at PB only in `test_types.py` (28),
  `test_command_validation.py` (3), `test_loop_validation.py:460`; `test_workflow_data_flow.py:493/521` keep
  `${array[@]}` / `${#count}` in shell bodies on purpose — the leftover rule must stay silent on them (an over-fire
  guard); the T2 vehicles (`stdin`/`prompt`/`env`) stay templated after the flip; PB adds (not converts) the two
  escape-in-body tests; golden-hash drift expected at PB = zero (D14); marker-excluded (paid) tests were outside the
  hook — the static inventory shows no body site there.
- Next: launch I4 (fresh, Opus · high) on PB.

## [2026-10-08 00:44] implementer I4 (Opus) — PB The flip
- Did: bodies (`shell.command`, `code.code`) are never surfaces, never resolved, never walked; the body rule (D5 +
  checkpoint §1/§2/§3, ruling 2) runs in `validate_data_flow` (so also at compile); Pass 7 deleted; the loop-carry
  warning generalized to every shell `inputs:` key (§5); file-reference detection, the MCP single-node expansion, the
  graph builder and the canvas `is_dynamic` skip bodies; harness edit (2); the sub-workflows guide fence fixed.
  Measured first: flipping `iter_node_surfaces` alone failed exactly the 15 Pass-7 tests in `test_types.py` (T3) —
  no other site survived PC.
- Changed (src): `core/workflow/template_surfaces.py` (`ParamMode`, `BodyLanguage`, `param_mode`, `template_params`,
  `code_bodies`; `iter_node_surfaces` iterates `template_params`); `core/workflow/data_flow.py` (new section "Code
  bodies": `StepScope`, `step_scope`, `BodyReference`, `body_references`, `body_reference_roots`, `_validate_bodies`
  + message builders; called per node from `validate_data_flow`); `runtime/engine/template_resolution.py`
  (`split_params(..., node_type=None)` — a body is static before `has_templates`); `runtime/compilation/compiler.py`
  (passes `node_type`); `runtime/template_validation/type_validation.py` (Pass 6 iterates `template_params`; Pass 7,
  `_build_quoted_templates`, `_is_shell_safe_type`, `_SHELL_SAFE_TYPES` deleted); `runtime/template_validation/
  validator.py` (Pass 7 call gone; `_validate_unread_step_inputs` replaces `_validate_loop_carry_prompt_usage` +
  `_loop_prompt_sink_text`; unused-input union gains `body_reference_roots(workflow_ir)`); `core/workflow/graph/
  build.py`, `graph/renderers/react_flow.py`; `core/file_resolver.py` (`is_param_file_reference(node_type, key, value)`
  at all FIVE param-value sites: `resolve_file_references` A, `_resolve_batch_file_references` B2, `_collect_param_file_refs`
  (params AND batch items, behind `has_file_references`), `dependency_discovery._collect_param_deps` and
  `_collect_batch_item_deps` — a grep shows the only remaining `is_file_reference(` calls are on a whole `batch:` string);
  `mcp_server/services/execution_service.py` (one `expand_env_vars_nested` call over the non-body params);
  `nodes/shell/env_binding.py` (`_suggest_name` → public `suggest_env_name`, runs collapsed + stripped — PA's tests
  unchanged; NOT `shell.py`, no lane-#724 overlap); `runtime/engine/engine.py` docstring (R, impact S4);
  `guide/features/sub-workflows.md` take-and-write fence. Tests: new `tests/test_integration/test_code_body_consumers.py`
  (12-row consumer table) and `test_code_body_leftovers.py` (62); parity `BODY_ROWS` (6 rows × 2) + `shell_body`/
  `code_body` surfaces; `test_types.py` (Pass-7 block → 1 test), `test_template_extract_pattern.py` (−9),
  `test_nodes/test_shell/test_command_validation.py` deleted, `test_loop_validation.py`, `test_graph_build.py`,
  `test_template_escape.py`, `test_malformed.py`, `test_guide_example_validation.py` (harness edit 2: bare names from
  `iter_template_surfaces`, never a regex over the file), the tightened files below; `inventory.py` (`ALLOWED_FILES`).
- **Task 181 (amendment 4):** scope rule = `pflow.core.workflow.data_flow.step_scope(workflow_ir: dict[str, Any],
  node: dict[str, Any]) -> StepScope`; `StepScope.owner(root: str, *, has_path: bool) -> str | None` (`None` = pflow
  never knew the name; a step id counts only with a path). `body_references(node, scope)` consumes it. Unused-input
  hook = the `| body_reference_roots(workflow_ir)` term of the union passed to `_validate_unused_inputs` in
  `runtime/template_validation/validator.py::validate_workflow_templates` — one function call, no parameter/callback.
- Verified (executed, macOS):
  - `make check` green; `make test` **10558 passed / 0 failed** (baseline 10504 at `c3189b41`, captured by me: +54 =
    consumers 12, leftovers 62, parity 12, loop-validation +8, graph 1, escape 2; retired: Pass-7 −29, extract-pattern
    −9, command_validation −5); `make test-e2e` 52 passed / 2 skipped (= baseline).
  - **Golden hashes: zero drift** (D14) — `golden_config_hashes.json` untouched, `test_golden_baseline_hashes_match` green.
  - Real CLI (`uv run pflow`, probes in scratch): checkpoint §2a/2b/2c/2d (leftover text), §2e (ruling-2 warning; the
    run proceeds and sh prints `bad substitution`), §3 (`$${PRICE}`), §5 (carry + "not visible" warnings) and §8
    (`world 3 /Users/andfal`) reproduce the ruled text; `--validate-only` and the run print the identical message.
    `workflows/search/run-searcher.pflow.md` and `workflows/review/run-review-lenses.pflow.md`: `✓ Workflow is valid`,
    no warning. The fixed guide fence ran twice for real (log `1: a`, `2: b`; queue left `c`).
  - Corpus scan (data-flow body rule + unread-`inputs:` warning over every `.pflow.md` in `examples/`, `workflows/`,
    the Task-159 baseline, and every `## Steps` fence in the guide, docs and both MCP instruction resources — 33
    fences): one hit before the fix (the sub-workflows fence), zero after. No shipped shell step has `inputs:` elsewhere.
  - `inventory.py`: 0 templated bodies outside `ALLOWED_FILES` in tests except §6's leave (`test_loop_control.py:101`)
    and the known `python-manual` heuristic false positives; non-test rows are historical task archives.
  - **Mutation ledger** (22 mutations, each on a byte copy, counted failures, restore asserted byte-equal): M1
    surfaces yield bodies → 27 red (consumer rows data_flow/pass_5/pass_8/issue_pass/source_file_hint/mcp + every false
    positive + parity ambient rows); M2 Pass 6 → `pass_6` row; M3 split_params → 14 (split_params row, runs); M4 graph →
    `graph_build` row + code-body graph test; M5 canvas → `canvas_is_dynamic`; M6 file refs → `file_references`; M7 MCP →
    `mcp_expansion` + MCP run test; M8 unused-input hook → `unused_input` + test 8; M9 rule not run → 53; M10 bare step id
    in scope → 1; M11 batch alias workflow-wide → 2; M12 Issues ignored → 5; M13 code read whole → 2; M14 `$$${` as escape
    → 2; M15 `inputs:` counted as a reader → 1; M16 ruling 2 on an index → 2; M17 whole-body form → 1; M18 script path → 1;
    M19 first operand only → 1; M20 llm carry → 1; M22 colon-less default → 1; M23 SyntaxError guard → 1. (The predict.py
    row is DROPPED per amendment 3 — not in the table.)
  - **T2 check-off (§6), by name** — net: a temporary hook in `_validate_bodies` (removed; `grep TEMP` = 0) logged every
    test whose run emitted a body diagnostic across `make test` + `make test-e2e`: every hit is a new PB test, so no T2
    test passes or fails through a body. Asserted messages read: `test_graph_build.py` (edge `input_name == "T"`, presence);
    `test_loop_validation.py` 132/145 (`__iteration__` messages, stdin); `test_validation_utils.py:170`;
    `test_workflow_data_flow.py` (19 env vehicles; 493/521 keep `${array[@]}`/`${#count}` in bodies and stay `[]` — over-fire
    guard holds, `array`/`count` out of scope; `_wf` helper); `test_workflow_validator.py` 336/366;
    `test_sub_workflow_validation.py` 386/501; `test_node_wrapper_template_validation.py` 595/610 (`prompt`);
    `test_array_notation.py:366`; `test_malformed.py` (15, stdin; + the command now holding `${NAME:-x} ${}` is NOT
    reported); `test_literal_operands.py`; `test_union_types.py` (11); `tv/test_validator.py` 974/1443;
    `test_trace_integration.py` 571/664; `test_enhanced_error_output.py:382`; `test_validate_only.py` 145/629/827;
    `test_runner.py` 30-31 (asserts cycle text); `test_failed_node_invariant.py:1866`; `test_template_resolution_hardening.py`
    (12); `test_mcp_warnings.py`; `test_validation_service.py` 66/95/130/215; `test_guide_example_validation.py` (harness).
    **Tightened** to the original error class: `test_validate_only.py` (missing-required-input → `requires input
    'required_value' but it is not provided`; forward ref → the exact `comes after this node in execution order` text;
    and beyond the plan's list, `wrong_node` → `references non-existent node 'wrong_node' in parameter
    'env.WRONG_NODE_RESULT'`), `test_template_resolution_hardening.py` (89/163/471 → exact `does not output` messages; and
    beyond the list, the three `${missing}` tests that asserted only `not result.success` → the undeclared-reference text),
    `test_workflow_data_flow.py` (`__index__` without batch → the exact "no inputs are declared" text),
    `test_runner.py` (any ERROR → the missing-input text), `test_enhanced_error_output.py:382` (beyond the list:
    `"producer" in stderr or "output" in stderr` → the exact `does not output 'output'` line).
  | Assumed: Windows. Every new test that spawns sh avoids `os.environ["HOME"]` (Git Bash may re-spell HOME; tests compare
  `"${HOME}"` to sh's own `$HOME`) and uses POSIX-form paths; `bash -c 'arr=(…)'` relies on Git Bash's bash on PATH —
  settled only by `tests-windows`.
- Deviations/surprises:
  1. **`body_references` lives in `data_flow.py`, not `template_surfaces.py` (D1).** It takes a `StepScope`, whose
     constructor amendment 4 places in `data_flow.py`; in `template_surfaces.py` it would need a type from the module
     that imports it. One cohesive section in `data_flow.py` holds scope, detector and messages. Importance 1.
  2. **`code_bodies` yields `(param, language, text)`, not `(param, text)`.** The detector must know sh vs Python; a
     `_BODIES: {(type, param): language}` table answers both `param_mode` and that, with no `node_type == "code"`
     branch (Task 182 needs the language too). Importance 1.
  3. **A gap in D5's mechanism vs the ruled §1 verdict, closed:** sh's colon-less default `${limit-10}` parses as ONE
     pflow name (`-` is an identifier character), so the Issue leading-name check never saw it — loud before (undefined
     input), it would have been silent. The ruled table says "a shell expansion form whose leading name is in scope →
     ERROR"; sh names cannot hold `-`, so the expression's first name is split at `-` (`_leftover`). Test + M22.
     Importance 2 — conforms to the ruling, flag if you read it otherwise.
  4. **Texts I drafted where the checkpoint had none** (all follow its voice): an Issue leftover's fix keeps the operator
     (`replace ${limit:-10} with "${LIMIT:-10}"`) and its fix 2 is "Only if the command itself assigns `limit` (a shell
     variable of your own): rename it." (braces cannot be dropped from `${x:-y}`); an ambient-named collision's fix 2 is
     "If you meant the shell's own $HOME: write $HOME without braces." (hard case a); the code-body `$${in-scope}` fix
     (`add `- inputs: {x_cost: ${x.cost}}` … and write f"${x_cost}"`) and code escape message ("…the string keeps both
     dollar signs"); the multi-escape case is one ERROR per escape (D5 step 2 is per-occurrence; leftovers are grouped
     per body as ruled). The §3 in-scope example reads `"value: \$$X_COST"` (name by the naming rule, not `COST`).
  5. **Wording vs ruled drafts:** every `add …` phrase branches on an existing `env:`/`inputs:` (R, C3) instead of
     §5's/§2d's parenthetical "(or N: ${n} under the existing env:)"; the ruling-2 fix says "add `- env: {…}` to the
     step and read" (draft: no "to the step"). `At:` renders `nodes[id=x].params.command:16` because D5 sets
     `context["source_line"]` and the generic renderer appends it to the path (the draft showed no `:line`).
  6. **Ruling-2 did-you-mean cutoff 0.6** (difflib default 0.4 offered `user` → `s` for hard case d — a misleading
     suggestion on text that is most likely another language's). `fecth` → `fetch` still matches.
  7. **`test_command_validation.py` deleted, not replaced** with node-level `bind_env` tests (§6): PA's
     `TestShellNodeBinding` already is that, and its five tests asserted only `action == "default"` (`${dir}` there was
     always plain sh). The verbatim run is PB test 4, end to end.
  8. The sub-workflows fence now binds `ITERATION` and logs `1: a` (the child's declared input stays used); dropping the
     input would have changed the parent pattern the section teaches.
  9. Stale instruction lines my diff makes false, left for PF per §7 (named there): `runtime/template_validation/CLAUDE.md`
     ("Type, shell, and code-annotation passes (6, 7, 9)", "Shell validation rejects dict/list interpolation in
     `command`…"), `core/workflow/CLAUDE.md` data_flow ("Bash expansions such as `${var:-default}` … are Issues, reported
     by the template validator's Issue pass" — not in a body any more). `.taskmaster/tasks/task_148/verification/*.pflow.md`
     (2) still hold old-form bodies — historical artifacts, not corpus.
- Self-checks: **test-reflect (directed):** the ledger above, kill criterion a counted `N failed`. First pass left M2,
  M15, M19 alive → DEEPENED `pass_6` row (a compatible template beside the body so the passes run — the validator's
  no-template early return masked Pass 6), `test_shell_inputs_key_nothing_reads_warns_not_visible` (+ the self-named
  `inputs: {url: ${url}}` shape — the guide's exact pattern), added `test_any_reference_in_an_expression_makes_it_a_leftover`
  (coalesce's later operand, dynamic index). DEEPENED `test_code_with_a_syntax_error…` with a dict-IR twin
  (`test_code_python_cannot_parse_is_left_to_its_parser`, M23 — the markdown-path test passes pre-PB). DELETED
  `test_dict_bound_through_env_arrives_as_json_text_with_apostrophes_intact` (§6's 1385 replacement): duplicates PA's
  `TestEveryValueBinds::test_a_workflow_input[object]` + `TestInjection`. Labelled regression guards (pass pre-PB):
  `test_code_without_references_runs_unchanged`, `test_code_with_a_syntax_error_gets_the_parsers_error_only`. Every
  absence assertion has a same-medium presence partner (consumer rows: env half; false positives: the printed stdout;
  nothing-runs: the proof file appears once fixed; inputs warning: the bound form vs the unbound form).
  **Fully happy?** Yes after closing deviation 3 (found on this pass). Honest residue: (a) the dash split is a rule
  the ruling implies but no draft states; (b) Windows is assumed; (c) a code-body leftover's line can be off by the
  count of escaped `\n` inside a single-quoted Python string before it (`ast` gives the decoded value) — display only.
- Next: mid-task review (`review-validation-consistency`, `review-impact-completeness`, `review-silent-failures`,
  `review-feature-interactions`) on PB's diff; fixes fold in before PE.

## [2026-10-08 02:30] task orchestrator (Opus) — state change from main (received while I4 runs PB)
- v0.16.0 SHIPPED (PyPI). Plan §4.0's merge hold on Part 2 is LIFTED; I still hand back at `create-pr`, main merges
  after CI green on the merged result.
- main `a296ceca` → `a42f55e2` (measured by main): release files; PR #726 (`core/trace_io.py` surrogatepass sizing,
  `runtime/workflow_trace.py` `_flush_line` catches Exception — closes Part 1 follow-up W1;
  `tests/test_integration/test_shell_env_binding.py` lone-surrogate test now with streaming ON — overlaps PC2's
  file); PR #725 + #744 (`ui/server.py` `/api/gate`, `tests/test_cli/test_ui_interaction_server.py` — PC2 touched it,
  web gate components, `web/src/index.css`).
- Action: merge `origin/main` at the PB boundary (after PB is committed, before the mid-task review), re-run
  `make check` + `make test`; PE's brief gets the web delta.
- Issue #727 (shell `stdin:` encode failure after spawn, in `shell.py`): NOT built here; the task-review notes
  whether Part 1's binding check makes it trivial.

## [2026-10-08 03:40] task orchestrator (Opus) — PB verified; rulings on I4's deviations; committed; merging main
- Verified: `make check` green, `make test` 10558 passed / 0 failed (mine). 181 shapes present:
  `template_surfaces.param_mode`/`template_params`/`code_bodies`, `data_flow.step_scope`/`body_references`/
  `body_reference_roots` (§0 checks 1, 3, 4, 5 of 181's plan answerable by name; check 6 is PE's).
- [RULING, orchestrator, importance 2] I4 deviation 3 (sh colon-less default `${limit-10}` split at `-` for the
  leading-name check) — **accepted**: it is the ruled §1 row ("a shell expansion form whose leading name is in scope
  → ERROR") applied to the one form the parser reads as a single name; sh names cannot hold `-`, and the whole root is
  still checked as a pflow name first. Deviations 1, 2, 4–8 accepted (importance 1); 4/5 (texts drafted beyond the
  checkpoint, `At: …params.command:16`) go to the completion gate's agent-ux lens by name. Deviation 9 (two stale
  CLAUDE.md lines) → PF.
- Self-check: I4's entry resolves test-reflect (22-mutation ledger; three survivors deepened) and "fully happy?"
  (residue: dash split, Windows assumed, a code-body line offset by escaped `\n` — display only); re-asked at the
  review resume.
- Next: commit PB; merge `origin/main` (`a42f55e2`); gate; resume I4 for the PB mid-task review.

## [2026-10-08 04:00] task orchestrator (Opus) — PB committed `76a1aed5`; origin/main `a42f55e2` merged `4ab61390`
- Conflict: one hunk in `tests/test_cli/test_ui_interaction_server.py` (main factored the escalation workflow into
  `_escalation_wf`; PC2 had converted the inline copy) → took main's helper and converted its body to `env:`
  (`ESC_RESULT_ESCALATION_DECISION_CHOSEN`); the file's other PC2 conversions kept. `test_shell_env_binding.py`
  (#726) auto-merged.
- Verified on the merged result: `make check` green; `make test` 10566 passed / 0 failed; `make test-e2e` 52 / 2
  skipped. `pflow --version` 0.16.0.
- Next: resume I4 — PB mid-task review (4 lenses) on `c3189b41..76a1aed5`.

## [2026-10-08 01:35] implementer I4 (Opus) — PB mid-task review: fan-out run, every finding dispositioned
- Did: dispatched the battery through `workflows/review/run-review-lenses.pflow.md` (provider codex — opposite the
  Claude builder), backgrounded, stdout → `implementation/review-pb-midtask.md` (256 lines, read whole), waited in-turn.
  Lenses: `review-validation-consistency` (per-lens target: the data-flow body rule + validator ↔ `split_params`/
  compiler/node twins), `review-impact-completeness`, `review-silent-failures`, `review-feature-interactions` (whole
  diff), plus `review-test-fidelity` (added upward: the engine/MCP files are sensitive paths whose skill floor includes
  it; per-lens target = PB's tests). Target `c3189b41..76a1aed5`, with the spec, plan D1/D5/D7/D14 + PB, checkpoint
  §1–§3/§5, ADR-0016 and log entries 23:05 / 00:44 / 03:40 stated as SETTLED. Coverage: 5/5 lenses returned, none
  failed. `review-falsifier` NOT run: it is a direct Agent launch and my role never spawns agents — the completion
  gate owns it.
- Findings (7) — each reproduced by executing against the code before fixing; tests written first and seen to fail:
  1. **Critical (2 lenses) — CONFIRMED, fixed.** A Python bytes literal (`b"${name}".decode()`, `b"$${X}"`) bypassed
     the rule (`_readable_texts` read `str` constants only): was resolved before, silently literal after.
  2. **Critical (2 lenses) — CONFIRMED, fixed.** The accepted dash split covered Expressions only; `${limit-default:value}`
     / `${item-fallback value}` parse as Issues whose leading path is `limit-default`, so an in-scope `limit`/`item`
     ran silently. The split now applies to an Issue's leading name too (full pflow name still checked first).
  3. **Warning (2 lenses) + test-fidelity Critical — CONFIRMED, fixed.** The AST joins adjacent literals, so checkpoint
     §3's own repair `"$$" "{PRICE}"` was re-flagged as an escape whenever the body held another `${…}`. A plain literal is
     now read as its own SOURCE text (adjacent literals stay apart; bytes read like strings — this also fixes 1; line
     counts now hold through `\n` escapes, closing my residue (c)); f-string parts keep their value (their positions are
     unreliable before 3.12). Test: the mixed body validates and runs, printing exactly `$${PRICE}${HOME}`.
  4. **Warning (4 lenses) — CONFIRMED, fixed.** `_leftover` kept only the first in-scope root, so `${primary ?? fallback}`
     or `${values[${index}]}` drew a second "never used" ERROR for the other input, and two `inputs:` keys in one
     leftover drew an unread-`inputs:` warning — against §2's "one mistake, one diagnostic". `BodyReference.roots`
     (every in-scope root, dependency view) now feeds both `body_reference_roots` and `_validate_unread_step_inputs`;
     the body still gets ONE grouped error.
  5. **Critical (silent-failures) — CONFIRMED, fixed.** `${UNSET:-${item}}` is one Issue to the parser (it ends at the
     first `}`), so the nested in-scope `${item}` ran empty (loud before PB). `_segments` re-reads an Issue's interior;
     the leftover names `${item}`. Partner: `${UNSET:-${HOME}}` stays valid.
  6. **Warning (silent-failures) — SKIPPED, pre-existing.** `run_registry_node`'s success branch
     (`mcp_server/services/execution_service.py`) formats node outputs only and has never forwarded a validation
     warning (PA's `env:` warnings included); PB did not touch that output shape and the ruling-2 warning is the only
     new content reaching it. Changing the MCP response shape is outside PB. Follow-up for the merge seam: "MCP
     `registry_run` success drops validation warnings". Importance 1–2.
  7. **test-fidelity Warnings — CONFIRMED, folded into 3 and 4** (the escape-repair test now validates AND runs the
     mixed body; accounting tests cover two known roots through `WorkflowValidator`).
- Changed: `core/workflow/data_flow.py` (`BodyReference.roots`; `_segments`; `_leftover` returns `(reference, owner,
  roots, is_expression)` and dash-splits Expression and Issue alike; `_readable_texts` reads literal source / bytes);
  `runtime/template_validation/validator.py` (unread-`inputs:` reads `ref.roots`); `tests/test_integration/
  test_code_body_leftovers.py` +8 (bytes, two colon-less Issue forms, nested expansion, the §3 repair beside another
  reference, two accounting shapes, two `inputs:` keys in one leftover).
- Verified: `make check` green; `make test` **10574 passed / 0 failed** (10566 at `f061120e` + 8); `make test-e2e` 52 / 2
  skipped. Mutation ledger re-run on the fixed code: all 22 prior mutations still go red (M19/M22 re-anchored to the new
  shape) plus R1 bytes skipped → 1, R2 literal values not source → 2, R3 Issue interior not re-read → 1, R4 first
  in-scope root only → 3, R5 dash split Expressions only → 2, R6 unread-`inputs:` first root only → 1 (counted
  failures; restores asserted byte-equal; R3's first attempt was a syntax-error mutant and was redone). Real CLI: the
  nested shape errors identically at `--validate-only` and at the run; corpus scan (33 fences + every shipped
  `.pflow.md`) still clean; both tooling workflows `✓ Workflow is valid`.
- Deviations/surprises: none against ruled text or a seam decision — every fix applies an existing ruling (§1 rows,
  §2 "one mistake, one diagnostic", §3's repair, the accepted dash split). Detection for code bodies now reads source,
  not decoded values: an obfuscated split like `"${" "name}"` is (correctly) not a reference — it never was one to the
  old resolver either.
- Self-checks: fully happy? Yes — the review found real holes in the detector's edges (all in the "reading" half, none
  in the seam: `split_params`, consumers, compile path were verified clean by all lenses); each is now a named test
  with a killing mutation. Open for you: finding 6's follow-up; `review-falsifier` remains the completion gate's.
- Next: orchestrator commits; PE.

## [2026-10-08 04:45] task orchestrator (Opus) — PB mid-task review closed; committed
- Verified: I4's `[2026-10-08 01:35]` entry — 5 lenses (4 planned + test-fidelity, added by the skill's floor), 7
  findings, 6 fixed with tests (all in the detector's reading half; seam verified clean by every lens), 1 skipped as
  pre-existing (MCP `registry_run` success drops validation warnings — follow-up for the merge seam, carried to the
  task-review/hand-back). `make check` green; `make test` 10574 passed / 0 failed (mine).
- Disposition: accepted as logged. `review-falsifier` stays with the completion gate (direct launch, mine).
- I4 retired for PF: window ~545k, past the plan's ~350k rotation point → PF goes to a fresh Opus · medium launch.
- Next: PE (I5, fresh, Opus · medium, specialist web hand-off).

## [2026-10-08 05:30] implementer I5 (Opus) — PE Web (+ the full-tier-fallback amendment)
- Did: refs stop being read / substituted / tealed inside a code body on the web side; both `sourceDecorate.ts` teal
  sites follow one rule; four test fixtures moved off a ref-bearing shell `command`. Probe driven through `pflow ui`.
- Changed: `web/src/utils/format.ts` (`isCodeBody(kind, name)` beside `paramLanguage`, comment naming
  `template_surfaces._BODIES` as the source of truth); `web/src/graph/scan.ts` (`paramTextReads` skips a body);
  `web/src/components/ReadPanel.tsx` (`ParamBlock`: no batch-item expansion for a body); `web/src/graph/sourceDecorate.ts`
  (`tealsRefs(grammar)` = `null || "markdown"` + `plainLines`, used by the instant tier, the full tier's success path
  and its null/mismatch fallback); `web/src/graph/CLAUDE.md` (one paragraph under Rows and read presentation).
  Tests: `scan.test.ts` (6 parity rows + env-edge landing), `sourceDecorate.test.ts` (old "teals inside fence"
  test inverted; new 4-tier `it.each`), `ParamBlock.test.tsx` (body never expands, `stdin` does),
  `SourcePane.test.tsx`, `useWorkflowGraph.test.tsx:106,397`, `GraphView.test.tsx:115` + its six
  `input_name: "command"` edge/target refs (→ `stdin`).
- **`isCodeBody` call sites (Task 181 checks by name):** `web/src/graph/scan.ts:139` (`paramTextReads`) and
  `web/src/components/ReadPanel.tsx:76` (`ParamBlock` items). Definition `web/src/utils/format.ts:146`.
  `sourceDecorate.ts` does NOT call it (no node type in a fence) — it keys on the fence grammar (`tealsRefs`).
- Verified: web baseline before edits 55 files / 818 tests; after `npm run typecheck` clean, `npm test` 55 / **830**
  passed (no lint script in `web/package.json`). `make check` green; `make test` **10574 passed** / 0 failed (= the
  PB-review head's count; the contract drift check passes, so PC1's `prompt-caching-multi-chunk.json` is current and it
  goes through `lossless.test.ts` "REAL contracts" — green both before and after my edits). Kill check: with
  `scan.ts`/`ReadPanel.tsx`/`sourceDecorate.ts` restored from HEAD, exactly the 8 new skip assertions fail (shell.command,
  code.code, the inverted sync test, instant / null / mismatch tiers, SourcePane line 8, ParamBlock) and every presence
  partner passes; files restored after.
  Driven (`pflow ui --port 8791` from this worktree's `.venv`, PIDs 42525/42532 — stopped; `lsof :8791` empty; no
  chrome-devtools-mcp left). Probe `scratchpad/i5-t118p2/body-probe.pflow.md` (`up` → `use` with
  `echo "${HOME}" "$DATA"` + `env: {DATA: ${up.stdout}}` → literal batch `fan` with `stdin: ${item.name}`,
  `env: {GREETING: ${item.greeting}}`, `cat; echo "${HOME} $GREETING"`); `/api/graph`: every `command` `is_dynamic=false`,
  one data edge `e2 up.stdout → input_name "DATA"`. Screenshots in `/tmp/pflow-shots/t118pe/`:
  (1) `body-probe-advanced-none-LR-n1-2-20261008-011127.png`, `…-n2-2-20261008-011135.png` — command rows plain, no
  chip, no dynamic dot; env/stdin rows dynamic. (2) same + `body-probe-advanced-none-LR-1-20261008-011114.png`;
  `inspect`: e2's path ends at x=136,y=327 = the env row target handle (322–332), the command handle (361–372) unreached.
  (3) `read-use.png` — Command bash-highlighted, no `dynamic` badge, `${HOME}` not teal; Env `dynamic`. (4)
  `fan-command-source.png` + `source-tiers.png` — fence `echo "${HOME}" "$DATA"` plain bash; `DATA: ${up.stdout}` teal.
  Both tiers sampled in-browser by a scratch rAF-polling probe (`scratchpad/i5-t118p2/tier-probe.pflow.md`): instant
  (pre-shiki) and full — fence lines `tealRefs: []` in both, env/stdin lines tealed in both. The instant tier lasts ~6
  frames, so it is a DOM sample, not a screenshot. (5) `read-fan.png`, `read-fan-expanded.png`, `fan-command-source.png`
  (DOM probe: stdin `▸ 2 items` → expands to ada/bob; command no expander; **env no expander — see deviation 1**).
- Deviations/surprises:
  1. **Acceptance (5) "item expansion for `env`" is not met and cannot be by PE's files — needs your ruling.**
     `resolveBatchItems` (`web/src/utils/batchItems.ts:96`) returns null for any non-string value, and `env` ships as
     a dict, so `env: {GREETING: ${item.greeting}}` never had an expander (pre-existing, not a regression of mine).
     Verified with `stdin` (a string Template param) instead. After the flip `env` is THE batch-shell channel, so the
     common batch shell step loses its per-item preview. Options: (a) extend `resolveBatchItems` to dict/list values —
     substitute in string leaves, render the item as JSON (touches `batchItems.ts` + its tests; small, but a
     display choice on how a per-item dict reads); (b) accept, log as a follow-up. Recommend (a) as a follow-up issue,
     not in PE (importance 2; outside the plan's file list).
  2. **Null-grammar fences stay tealed.** The amendment's "(markdown)" vs the full tier's actual behavior: an ungrammared
     fence (`text content` — a write-file Template param) has no highlight attempt; the full tier always tealed it
     through `refSegments`, so "where the full tier would teal" = `markdown || null` (same rule as `CodeBlock.tealRefs`).
     Pinned by the `text content` row in the tier test. Consequence: yaml/json fences (real Template params like
     `headers`) now lose instant-tier teal — they never had full-tier teal, so the tiers just agree now. Importance 1.
  3. **The two `isCodeBody` call sites are defense-in-depth on valid workflows.** A body holding an in-scope root
     (`${item.x}`, `${up.stdout}`) fails validation and `/api/graph` returns 422 (executed on a variant of the probe),
     and an out-of-scope `${HOME}` has no producer, so neither site changes what a valid canvas shows today. They keep
     TS ≡ Python (`param_mode`) as the plan's parity rule requires; the only user-visible PE change on valid workflows is
     the source pane's teal.
  4. `SourcePane.test.tsx`: kept `echo ${repo}` in the shell fence (now the shell's own text) and asserted it is NOT
     tealed while the `- inputs: ${data}` body value is, instead of moving the ref out — the test's subject is the fence
     swap, and the inversion pins PE's rule in the real component.
  5. `GraphView.test.tsx` needed six `input_name: "command"` edits beyond the plan's :115 (the same GRAPH edge's id,
     focus/say targets, an input-port binding into `greet`, the nested-reveal edge) — all now `stdin`.
  6. Python `_BODIES` (`template_surfaces.py:27`) has no back-pointer to `isCodeBody`; the pointer runs TS → Python
     only. A one-line comment there is outside PE's files — PF or the orchestrator, if wanted.
- Self-checks: fully happy? With the code, yes; the loose end is deviation 1 (an acceptance item the plan assumed
  existing code met). `paramLanguage` repeats the same two (kind, name) pairs with a language — left (different
  question, one call each; folding them is a reach). test-reflect (directed scope — skip tests that could pass
  vacuously): resolved — every skip assertion has a presence partner in the same test (env/stdin/inputs/other-kind
  `command` rows read `a.out`; prompt + `text content` fences teal in every tier; `stdin` expands beside the body), and
  the kill check above shows each skip assertion fails without the change. The env-edge landing row passes on HEAD too
  (it pins existing `bindingParam` dict-key landing with a `${HOME}` command beside it — the plan's "labelled by the env
  key" row; kept, not a skip test).
- Tooling postmortem (screenshot skill): worked — `screenshot` / `inspect` / `click` all first-try, `-p` output clean,
  `focus=<node_id>` opens the read panel (undocumented in the URL table: it says "click-focus state"). Friction:
  (S) no way to scroll the read panel — the Command block of a batch node sits below the fold at 760×560; I wrote a
  scratch evaluate-script probe that `scrollIntoView`s a param. (S) the instant source tier cannot be screenshotted
  (≈6 rAF frames); a rAF-polling DOM sample was the only evidence — a `sample-tiers` option or doc note would help.
  (M) a generic `probe.pflow.md` (run a caller-supplied JS selector→facts function after settle, then screenshot)
  would have replaced both scratch workflows. Near-miss: an `evaluate_script` `function:` is a Template param, so a
  literal `${` in the JS (e.g. searching for `"${"`) is parsed as a pflow ref — I wrote `"$" + "{"`; worth a line in
  the skill's Troubleshooting.
- Next: orchestrator rules on deviation 1; commit; PF.
- [2026-10-08 06:05] **Ruling on deviation 1 applied** ((a), in PE). `web/src/utils/batchItems.ts`: `refsBatchAlias`,
  `aliasFields` and `resolveBatchItems` walk string LEAVES (`stringLeaves`; dicts by value, lists by item — keys never
  read or substituted); a dict/list item value is `fullValue(mapLeaves(value, substitute))` — the same formatter
  `ParamBlock` uses for the un-expanded param (indented JSON), no new treatment. `ReadPanel.tsx` `ParamBlock`: an item's
  language now comes from `paramLanguage(kind, name, param.value)` (the item value is text, so asking with it would
  have rendered a dict's items plain; for string params the result is identical — `paramLanguage` keys on type, and
  both are strings). `isCodeBody` skip stays first. Tests: `batchItems.test.ts` (dict `env` per item with substituted
  leaf and non-alias leaf verbatim; ref-looking key untouched; nested list leaf + label drops the read field; dict
  with no alias ref → null), `ParamBlock.test.tsx` (dict `env` expands to the JSON text per item, highlighted as
  `json`; the `stdin` string presence partner unchanged). Kill check: `batchItems.ts` from HEAD → 4 fail; the item
  language reverted to `item.value` → the ParamBlock dict test fails; restored. Driven (same probe, `pflow ui --port
  8791` from this tree, PIDs 90396/90401 stopped, `lsof :8791` empty): `/tmp/pflow-shots/t118pe/read-fan-env-expanded.png`
  — Env `▸ 2 items` → `name: ada {"GREETING": "hi"}`, `name: bob {"GREETING": "hey"}`, JSON-highlighted; Stdin
  still `2 items`; Command no expander. Acceptance (5) now met as written. Gate: `npm run typecheck` clean, `npm test`
  55 / **834** passed, `make check` green, `make test` **10574** passed. `dev servers: none`.

## [2026-10-08 06:00] task orchestrator (Opus) — PE rulings + screenshot-skill postmortem dispositions
- [RULING, orchestrator, importance 2] I5 deviation 1 (no per-item expansion for a dict `env:`) → **built in PE**
  (option a): ORCHESTRATION "a gap your change is about to widen is yours to close" — the dict gap pre-exists, this
  task moves every batch shell step's values into `env:`. Leaves substituted, keys untouched, rendered with the
  un-expanded dict formatter (no new visual); revertible as one function + tests.
- Deviation 2 (null-grammar fences stay tealed; yaml/json lose only instant-tier teal so the tiers agree) — accepted,
  importance 1. Deviation 3 (the two `isCodeBody` sites change nothing visible on a VALID workflow; parity only) —
  accepted. Deviation 6 (Python `_BODIES` has no back-pointer to `isCodeBody`) → PF adds the one-line comment.
- Postmortem (`screenshot-pflow-web-ui`): (S) no read-panel scroll primitive → follow-up issue candidate at the merge
  seam (hand-back); (S) instant source tier not screenshot-able → DROP (one task's need; DOM sample documented in this
  log); (M) generic probe workflow → DROP (no second observed need); near-miss `${` inside an `evaluate_script`
  `function:` parsed as a pflow ref → DROP here, it is exactly Task 181's surface (code handed to MCP tools); named in
  the task-review for 181.

## [2026-10-08 06:40] task orchestrator (Opus) — PE verified and committed
- Verified (mine): `npm run typecheck` clean; vitest 55 files / 834 passed; `make check` green; `make test` 10574 / 0
  failed; nothing listening on 8791 from this tree. I5's sub-bullet "Ruling on deviation 1 applied": dict/list
  expansion via the existing `fullValue` formatter; `ReadPanel` picks the item language from the param's value (an
  item arrives as text) — accepted. Acceptance (5) re-driven: `/tmp/pflow-shots/t118pe/read-fan-env-expanded.png`.
- Fully happy: resolved in I5's entry (code yes; the one loose end was deviation 1, now built). test-reflect resolved
  there (every skip assertion has a presence partner; kill check 8/8).
- Next: PF (fresh, Opus · medium).

## [2026-10-08 07:30] implementer I6 (Opus) — PF Guide, docs, instruction files
- Did: every §7 line re-verified on `a105e744` (PC had already converted all fences; PB had already fixed
  `type_validation.py`/`validator.py` docstrings, `engine.py`, `data-type-coercion.md`) and the remaining prose fixed;
  `nodes/shell.md` rewritten around one pattern; orchestrator additions 2–7 done; Task-159 guide case regenerated.
- Changed: guide `nodes/shell.md` (rewrite: plain-sh bullet; pattern = `env:` + `"$NAME"`; the old "Templates in Shell
  Commands" + `run-pipeline` folded into one `env:` section; body rule one paragraph; names; text rule + YAML note
  (Part 1's, kept); limits as CI showed; `stdin:`; masking; `inputs:` on a shell step; checkpoint §9 sentence verbatim;
  `$VAR`-not-`${VAR}` rule and `$${` paragraph deleted; the Node Creation fence's broken ```` nesting fixed),
  `nodes/code.md` 18/61, `core.md` 580/585/643, `features/loop.md:60`, `features/batch.md:140`; both MCP resources (the
  same 8 sentence edits each: shell bullet, list-recent-files label, code label + rule, "Templates work in any param",
  "In shell commands", common mistake #4 Impact/Fix + closing line); docs `reference/nodes/shell.mdx` (params table incl.
  the "Additional environment variables" line; "Using stdin for data"/Correct-Wrong + the Pass-7 "Validation" accordion
  replaced by "Passing values to the command" (+ breaking-change `<Warning>` per docs/CLAUDE.md), "Using stdin for large
  data", and a validation section quoting the real leftover error; §9 sentence under Security; example `ENV:` →
  `DEPLOY_ENV:` — `ENV` draws the shell-owned warning), `code.mdx:67`, `loops.mdx:47`, `template-variables.mdx` (escape:
  "not in a command or code block"; the false `${node_id.command}` subsection rewritten); `architecture/reference/
  template-variables.md` (all 7 JSON-IR sites; escape + Supported Locations exceptions; "Shell Command Limitations" →
  "Shell Commands and Code Blocks"), `architecture/features/simple-nodes.md` 228/233; source: `shell.py` (bridge comment;
  docstring "Template Variables…/Pattern Detection" → "Passing Values"; §9 sentence under Security features; `command`/
  `env` Interface comments, no comma outside parens — extracted metadata read back), `registry/context_builder.py` (shell
  snippet gains `env:`), `core/templates.py:63-68` comment, `data_flow.py` reference docstring ("in a Template param"),
  `template_surfaces.py` (`_BODIES` back-pointer to `web/src/utils/format.ts::isCodeBody`); CLAUDE.md:
  `runtime/template_validation` (table rows; passes 6/9 only; bodies are data_flow's; dict/list paragraph deleted),
  `core/workflow` (row for `_BODIES`/`param_mode` + body rule home; data_flow paragraph), `core` (escapes: not in a code
  body), `runtime/engine` (body static; callers pass `node_type`), `nodes` (body verbatim; failure `env` record),
  `tests/.../test_template_validation` (test_types row); `.claude/agents/pflow-codebase-searcher.md` (+3 rows) →
  `make sync-claude-assets` (1 file); Task-159 `12-…/04-guide-auto-detect/expected-stdout.txt` regenerated.
- Verified (executed): `inventory.py --sites` → 0 in `src/pflow/guide`, `src/pflow/mcp_server/resources`, `docs` except
  `docs/changelog.mdx:16` (v0.16.0 release notes — history, out of my scope); `src` rows = `data_flow.py:1289` (a
  message f-string) and `context_builder.py` (heuristic false positive I2 named) only. Architecture JSON-IR grep
  (`"command":…${`) → 0 outside `historical/`. `tests/test_docs` + `test_guide.py` + `test_instruction_resources.py`
  115 passed; `make check` green; `make test` **10574 passed** (= PE head). `uv run pflow guide shell` and `guide code`
  read back. Guide fence `list-recent-files` copied verbatim into a scratch workflow, `depth=1` → `./newfile.txt`.
  Every new claim probed: shell `inputs:` unread warning, `DEBUG: true` → `True` + warning, `VERSION: "1.10"` intact,
  `TOKEN_LIMIT` `<REDACTED>` in the failure block, `${NAME:-world} ${#X}` → `world 3`, `$${PRICE}` error; code
  `"${name}".upper()` errors while `f" ${total}"` prints `ABC $5`; `${a.command}` is "does not output" (the docs claim
  was already false). Task-159: the case's actual vs committed expected differs in stdout only (stderr, exit code
  identical); vs `task159-before` every hunk is this task's guide text; vs the committed expected the rest is also
  `pflow guide` output — node Interface text drifted from other merged work (delete-file `deleted: str` #617, llm
  `response: any`, mcp pflow-params section) — so regenerated (`run-case.sh … --write`), then `run-case.sh` rc 0;
  `verify.sh` **76 / 11 / 0**, drift set = P0's §2.5 set minus this case.
- Deviations/surprises:
  1. **Masking wording follows the code, not the plan's draft.** `is_sensitive_parameter` matches whole words: `MY_KEY`
     is NOT masked (only `API_KEY`/`PRIVATE_KEY`/`SSH_KEY`/`SECRET_KEY`), so the plan's "`…_key`" would state a behaviour
     the code lacks; the guide/docs name `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `CREDENTIAL`, `API_KEY` ("one of the
     words"). Also true but not stated: `PASSWD`, `PWD` (!) and `AUTHORIZATION` mask. Importance 1.
  2. The Task-159 regeneration also absorbs ~120 lines of non-118 guide drift (node Interface and mcp guide text from
     merged main work). I judged that "guide text" because it is `pflow guide`'s own output and the case exists to
     snapshot it; overrule → `git checkout` that one file.
  3. MCP resources got the rule-line edits only (as planned) — they still carry no names/limits/masking detail for
     `env:`; their shell bullet now says bind in `env:`, read `"$NAME"`, large values via `stdin:`. A fuller copy is a
     content decision, not made here.
  4. Docs `shell.mdx`: the "Wrong" fence I2 wrote (`env:`-bound JSON piped to jq) was removed rather than kept — binding
     JSON in `env:` is the decided rule and works; the page now teaches `env:` for values and `stdin` for large/streamed
     data. `template-variables.mdx` "Shell command" subsection claimed `${node_id.command}` is readable — it never
     validated; replaced with what is true (failure output + `pflow report` show command and bound `env:`).
  5. Arch type-compat examples moved from `command` (Pass 7, gone) to shell `timeout` (dict → int, probed: Pass 6 fires);
     "Using Whole Dict Where String Expected" retitled "…Where a Scalar Is Expected" — dict → str is legal elsewhere.
  6. `docs/reference/nodes/shell.mdx` gained a breaking-change `<Warning>` (docs/CLAUDE.md update policy).
- Not done / for you: `docs/changelog.mdx:16` (v0.16.0 entry shows `$${batch_name}` in a command — history, yours or
  main's); `.taskmaster/tasks/task_148/verification/*.pflow.md` old-form (I4 noted; history). `/tmp/marker` was touched
  by the fence probe (the guide example's own path).
- Self-checks: **Fully happy?** Yes — every sentence I added was probed against the running code or names a code home;
  the honest residue is deviation 2's judgment call and deviation 3's thinner MCP copy. test-reflect: not needed — docs
  (no test added or changed).
- Next: orchestrator verifies + commits PF; PZ.

## [2026-10-08 07:50] task orchestrator (Opus) — PF verified; rulings; committed
- Verified (mine): `make check` green; `make test` 10574 / 0 failed; the five `.py` files PF touched change comments,
  docstrings and `context_builder`'s example text only (diff read).
- [RULING, importance 1] Task-159 `12-…/04-guide-auto-detect` regeneration — **kept**: the case exists to snapshot
  `pflow guide` output, and every hunk is guide output (this task's text plus guide text other merged work changed);
  `verify.sh` 76 / 11 / 0, the 11 = P0's set minus this case. Named in the task-review (the Task-159 re-record
  follow-up owns the other 11).
- Accepted: masking wording follows the code (whole words — `MY_KEY` is not masked); MCP instruction copies carry the
  planned rule edits only (plan §7 scope; a richer `env:` section there is a content follow-up, named in the
  task-review); the two already-false docs claims corrected; `docs/changelog.mdx` and `task_148/verification/` left
  (history — §5.8).
- Next: PZ — completion gate.

## [2026-10-08 02:10] gate runner G1 (Opus) — PZ steps 1–2: mechanical gate + real surface (head de9e1cc6)
- Did: PZ step 1 (mechanical gate) and step 2 (the spec's Verification list, line by line, through `uv run pflow`; one real
  searcher run). Probes in `scratchpad/g1-t118p2/probes/` (session scratch, not committed).
- Changed: nothing in `src/`/`tests/` for these steps.
- Verified (executed, macOS, before any gate fix):
  - `make check` green; `make test-all-local` **10626 passed / 2 skipped** (= the baseline for the battery fixes).
  - `verify.sh` **76 / 11 / 0**; drift set = P0's §2.5 set minus `12-…/04-guide-auto-detect`, by name. Actual-vs-actual
    (`task159_actual.sh` → scratch): **86/87 identical to `task159-before/`**; the one difference is
    `12-…/04-guide-auto-detect` stdout — 94 changed lines, every hunk this task's guide/fence text — and that actual equals
    the committed (PF-regenerated) expected byte-for-byte.
  - `capture.py --check`: 29 examples, 1 differing — only `error-handling/typo-on-failed-node` (pre-existing `workflow.name`).
  - `inventory.py`: zero outside `ALLOWED_FILES` and history. Remaining rows: `.taskmaster/` archives of done tasks
    (107/118 research/128/147/148/168/38), `releases/v0.7.0-context.md`, `docs/changelog.mdx` (history by ruling);
    `src` = `data_flow.py:1289` (a message f-string) and `context_builder.py` (heuristic, refs=[]); `tests` = the known
    python-manual heuristic rows (refs=[]), `test_loop_control.py:101` (§6 leave), `test_shell_failure_display.py:584`
    (intentional) — no new site.
  - Spec Verification, one line each (`--validate-only` → run):
    1. `${NAME:-world} ${#X} ${HOME} pid=$$` unescaped → valid; run prints `world 3 /Users/andfal pid=67918`.
    2. Hostile value (`-n it's "q"\nline2 $5 \`touch …\` $(touch …) \ back`) from a code step via `env:` → `od -c` shows every
       byte intact, neither marker file created; compact `{"a":1,"b":[1,2]}` bound directly arrives as `[{"a":1,"b":[1,2]}]`.
       Windows leg = Part 1's D8-3 (PASS); Part 2's `tests-windows` run is pending the PR.
    3. 3 / true / null / object / array from a code step + literal `8080` / `[1, 2]` → valid; run prints
       `3|True||{"a": 1, "b": [1, 2]}|[1, 2]|8080|[1, 2]`.
    4. One workflow with every leftover shape (batch `${item}` + `${__index__}`, `${fetch-data.stdout}` + `${a.b}`,
       `'${overwrite}'`, looped `${__iteration__}` + carry/`inputs:` `${state}`, `inputs:` `${url}`) → 5 ERRORs with the
       ruled fixes; the run prints the identical 5 (diff = the header line only), no node executes. Ambient probe
       (`$HOME ${HOME} ${CI:-noci} ${X:-y} ${#HOME}`, `CI=1`) → valid, runs (`5` words).
    5. `"${name}".upper()` → the code-body ERROR naming `inputs:`, identical at validate-only and run; the `inputs:` form
       with `f"…${{x}}"` → valid, prints `ABC ${x}`.
    6. Looped shell step `inputs: {state: a}`, `env: {STATE: ${state}}`, carry `${c.stdout}`, **`cache: true`** → `ab`,
       `abb`, `abbb` (also the memo-key regression guard: a key ignoring `env:` would replay round 1); carry bound nowhere →
       the §5 warning at validate-only and in the run's Warnings.
    7. `- command: ./cmd.sh` holding `${HOME}` and `${NAME:-x}` → `home=/Users/andfal name=x`; one-word
       `./scripts/$NAME.sh` (`env: {NAME: report}`) → valid and runs the script (a command, not a file reference).
    8. Failing step (`ENDPOINT`, `API_TOKEN`, a 4,999-char `LONG`) → text block shows `Command:`, `ENDPOINT=users`,
       `API_TOKEN=<REDACTED>` + the masking note, `LONG` cut at 200 with `(4,999 chars — full value: pflow report)`;
       `--output-format json` `shell_env` the same, no `sk-secret`, no tail marker; `pflow report` page has `## Command`
       and `## Env` with the full 4,999-char value (tail marker present), secret masked.
    9. `my-var` → the ruled ERROR at validate-only and run; 1.2 MB value and a NUL value, both under `ignore_errors: true` →
       the ruled pre-spawn errors naming `BODY` / `DATA`, run fails, neither marker file created.
    10. (memo key) — see 6.
    11. Graph via the `/api/graph` chain (`resolve_validate_build` → `render_react_flow`) on `up` → `echo "${HOME}" "$DATA"`
        + `env: {DATA: ${up.stdout}}`: one data edge `stdout → input_name "DATA"`; `command` `is_dynamic=False`, `env`
        `True`. Web canvas: PE's screenshots (not re-driven — no web change since PE).
    12. Corpus: above. Searcher: `run-searcher.pflow.md agent=pflow-codebase-searcher effort=low cwd=<worktree>` →
        success (11 s, cited `template_surfaces.py:29/34/38` correctly); trace `resolve-cwd` env
        `{'CWD_OVERRIDE': '<worktree>'}`, stdout the worktree path. Fan-out run: the battery below (entry 2).
  | Assumed: Windows for Part 2's diff (the PR's `tests-windows` job); the web canvas beyond the graph contract (PE evidence).
- Deviations/surprises: (1) the orchestrator's packet named head `dc2c6c10`; the branch head is `de9e1cc6` — an amend of
  it whose only delta is one line in `tests/test_runtime/test_template_validation/CLAUDE.md`; gated `de9e1cc6`.
  (2) Verification line 8's terminal block caps a bound value at 200 chars (ruling 6) — the report holds it whole.
- Self-checks: n/a for these steps (no code); the fixes and their checks are in the next entry.
- Next: battery evaluation (entry below).

## [2026-10-08 02:15] gate runner G1 (Opus) — PZ step 3–5: code-mode battery, every finding dispositioned, fixes landed
- Did: dispatched 12 lens runs through `workflows/review/run-review-lenses.pflow.md` (provider codex — opposite the Claude
  builders) with explicit `cwd=<worktree>`, backgrounded, stdout → `implementation/gate-part2-report.md`, waited in-turn:
  `✓ Workflow completed in 506.9s`, `run-codex 12/12`, gaps `[]`. Trace
  `~/.pflow/debug/workflow-trace-7e357182-run-review-lenses-20261008-014828-858277.json`: `resolve-cwd` env
  `{'CWD_OVERRIDE': '/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated'}`, stdout the same path.
  Partition: silent-failures ×3 (engine/validator · shell node + display · web), validation-consistency ×1 (body rule ↔
  split_params/compiler/node + TS `isCodeBody`), agent-ux ×2 (messages — I4 deviations 4–5 named · guide/docs/MCP/examples),
  test-fidelity ×2 (Python · web); impact-completeness, feature-interactions, simplicity, spec-conformance on the whole diff.
  concurrency-safety not triggered (no subprocess/thread change in Part 2 — `shell.py` diff is docstring + `post()`).
  Coverage closure: four lenses declared partial reading of the bulk-converted files → re-ran test-fidelity ×2 over all 76
  PC2-converted test files (`implementation/gate-part2-report-rerun.md`, 2/2, **clean**); docs were read whole by the
  docs agent-ux lens; converted examples rest on execution evidence (PC1 node-output dumps + equivalence harness, my
  capture/verify/real runs), not a reading lens — stated, not re-run.
- Findings → dispositions (14 distinct; each executed or read at file:line before acting; tests written first and seen red):
  1. **Critical (SF core) → real severity Warning — FIXED.** `${UNSET:-${fecth-data.stdout}}` got no ruling-2 warning
     (executed: valid, prints `data.stdout|`). `_foreign_shape_warning` now walks `_segments` (an Issue's interior re-read,
     as the leftover rule does). Test `test_ruling_2_sees_a_misspelled_reference_nested_in_a_shell_expansion` (+ line).
  2. **W (SF web + FI, convergent) — NOT FIXED, handed back.** `batchItems.ts` dict expansion substitutes `${item.x}`
     inside `$${item.x}` (preview shows `$ada`; runtime binds `${item.name}`). Regex predates Part 2 (string params);
     PE's ruled dict expansion widens its reach to `env:`. Display-only.
  3. **W (SF web) — NOT FIXED, handed back.** Same function renders an interpolated bool/null via `fullValue`
     (`flag=true`, `null`) where the child receives `to_string` text (`flag=True`, empty). Pre-existing for string
     params; display-only. 2 and 3 need a `web/` edit verified through the screenshot skill with the shared `pflow ui`
     slot — options for you below.
  4. **W (agent-ux + spec-conformance handoff, convergent) — FIXED.** `"${user.name}"` on an `inputs:` key `user` was told
     "use the variable user" (executed). Now `use user['name']` (`user[0]['name']` for an index; a dynamic index gets "a
     value read from the variable user"); bare names keep the ruled text. Test (field + index rows) also RUNS the advice.
  5. **W (agent-ux) — FIXED.** A step with `env: ${cfg.env}` was told to add a second `- env:` bullet; executed: the parser
     keeps the last bullet, so `AUTH` from the map silently vanished. New branch: `add URL: ${url} to the map that the
     step's env: ${cfg.stdout} produces (a second `- env:` would replace it)` — leftover fixes and the unread-`inputs:`
     warning alike. Test covers both callers.
  6. **Minor (simplicity) — FIXED with 5.** The validator's unread-`inputs:` warning rebuilt `_binding_phrase`'s rule;
     now one public `data_flow.binding_phrase(…, to_the_step=False)` serves it. The kwarg keeps checkpoint §5's ruled text
     ("add `- env: {N: ${n}}` and read…", no "to the step") byte-identical — existing §5 tests green.
  7. **W (test-fidelity) — FIXED.** File-backed batch items (`batch: ./items.yaml`) had no row; added to the consumer table's
     `file_references` row (discovery `["batch", "batch.items[1].command"]`, resolution keeps `./scripts/$NAME.sh`).
     Mutation: file-batch discovery call given `None` node type → that row red; restored (`cmp` clean).
  8. **W (spec-conformance) — FIXED.** PB-1's `pflow workflow save` caller had no test; new `workflow_save` row through
     `save_workflow_with_options` (variable command kept verbatim, `scripts/run.sh` bundled). Mutation: body rule removed
     from `is_param_file_reference` → `file_references` + `workflow_save` red; restored.
  9. **Suggestion (simplicity): consumer-test dispatch table — SKIPPED.** It is the plan's "one parametrized table, a row per
     consumer" (PB test 1); the mutation ledger is keyed by its row ids.
  10. **W (SF display) — NOT FIXED, handed back (lane).** `env: {__VALUE: hello}` binds and shows in the failure block, but
      the trace sanitizer drops `__`-prefixed keys from `node_params.env`, so `pflow report`'s `## Env` omits it (executed).
      Fix site is `runtime/workflow_trace.py` → your lane rule.
  11. **W (validation-consistency) — FIXED.** A comment between adjacent Python literals (`"hello "  # ${name}` / `"world"`)
      was read as string text (executed: ERROR on valid code). `_readable_texts` now reads each literal's own source token
      (`tokenize` over the constant's segment), never the comment; lines unchanged. Test validates AND runs, plus a
      presence half (a `${name}` in the second literal still errors, on its own line).
  12. **W (agent-ux) — FIXED.** `as: LIMIT` + `${LIMIT:-10}` suggested `"${LIMIT:-10}"` — the same leftover (executed). A
      shell binding name that is a name in the step's scope now gets `_VALUE` (`LIMIT_VALUE`, `"${LIMIT_VALUE:-10}"`). Test
      validates the advised form and runs it (`seq` prints 1 2 3).
  13. **W (agent-ux) — FIXED.** The code-body `$${in-scope}` fix omitted the annotation (following it hit "missing a type
      annotation"). Now `…, declare its type in the code (`name: str`), and write f"${name}"` (2d's wording). Test
      validates the advised workflow through `WorkflowValidator` and runs it (`$bob`).
  14. **W (impact-completeness) — DISPUTED.** `pflow probe` drops the failure `env` copy from `outputs`: true (executed), but
      probe excludes every key the caller passed (`command` too, since before this task) and resolves nothing
      (`_probe_impl.py`; spec "skips the compiler and resolves nothing") — the "bound values" are the literals the caller
      typed on that command line. No information is lost.
- Changed: `src/pflow/core/workflow/data_flow.py` (1, 4, 5/6, 11, 12, 13), `src/pflow/runtime/template_validation/validator.py`
  (6), `tests/test_integration/test_code_body_leftovers.py` (+7 tests), `tests/test_integration/test_code_body_consumers.py`
  (+1 row, file-batch block); `implementation/gate-part2-report.md` (+ Appendix A: the spec-conformance lens's raw output,
  verbatim — the merge condenses its inventory), `implementation/gate-part2-report-rerun.md` (new).
- Verified: every new test red before its fix for the reason it names; `make check` green; `make test-all-local`
  **10634 passed / 2 skipped** (10626 + 8, all new; failing set empty). Real CLI after the fixes: the nested typo warns with
  `Did you mean 'fetch-data'?`; `as: LIMIT` prints the `LIMIT_VALUE` fix; `"${user.name}"` prints `use user['name']`.
- Deviations/surprises: texts drafted beyond the checkpoint (none changes ruled text): 4's field-access phrase and its
  dynamic-index fallback, 5's whole-map phrase, 12's `_VALUE` on an in-scope name, 13's annotation clause — flag for the
  falsifier/agent-ux eye. The merged report rated 1 Critical; on evidence it is a Warning (ruling 2 is itself a warning).
- Self-checks: fully happy? With the fixes, yes. Honest residue: the dynamic-index fallback in `_python_read` has no test
  (one phrase, a rare shape); `_literal_tokens` keeps a `TokenError` fallback that a parsed constant cannot reach. Left
  in my HOME by `pflow report` (removal was permission-denied): `~/.pflow/reports/{v8-fail,f10-dunder}`. test-reflect: not
  run separately — every new test pairs absence with presence and was seen red pre-fix; two mutations recorded above.
- For the orchestrator: (A) findings 2+3 (web preview): options (a) fix `substitute()` now — escape-aware match and
  `to_string`-faithful interpolation, keep pure-reference typing; needs the `pflow ui` slot + screenshots (a fresh Opus web
  launch, ~small); (b) follow-up issue (display-only, pre-existing for string params). Recommend (b) unless the slot is free.
  (B) finding 10: options (a) trace keeps author `env:` keys (workflow_trace.py — your lane); (b) a validation warning on
  `__`-prefixed `env:` names (env_binding; changes what such a workflow reports, not what it runs); (c) follow-up issue.
  Recommend (c). (C) The Requirement Inventory for `review-falsifier`: `gate-part2-report.md` → "Appendix A" →
  "### Requirement Inventory" (line 358). Spec-conformance marked Part 2 `tests-windows` as pending gate evidence.
- Next: orchestrator launches `review-falsifier`; I evaluate its report.

## [2026-10-08 08:40] task orchestrator (Opus) — completion gate: G1's dispositions ruled; fixes committed; falsifier next
- Verified (mine): `make check` green; `make test` 10582 / 0 failed (G1: `make test-all-local` 10634 / 2 skipped).
- [RULING, importance 2] Findings 2/3 (web per-item preview: expands `$${item.x}` as a ref; renders an item's `true`/
  `null` where the command receives `True`/empty) → **follow-up issue**, not this PR: display-only, the substitution
  code is pre-existing and wrong identically for string params (`stdin`) — PE's dict extension inherits it, does not
  widen it in kind. Named in the task-review and the hand-back.
- [RULING, importance 2] Finding 10 (a `__`-prefixed `env:` name shows in the failure block but not in the report's
  `## Env` — the trace writer drops `__` keys) → **follow-up issue**: the fix is in `runtime/workflow_trace.py`, a
  live lane's surface (packet: stop, don't edit). Named in the task-review.
- Accepted: the disputed probe finding (probe resolves nothing and omits every caller param) and the skipped
  consumer-table suggestion (the plan's one-row-per-consumer design); new message wording listed in G1's entry.
- Windows: `tests-windows (core-cli-nodes)` runs on the PR — the hand-back carries it.
- Residue outside the tree: G1 left `~/.pflow/reports/v8-fail` and `~/.pflow/reports/f10-dunder` (report outputs);
  deleting under `~` is permission-denied for agents — named in the hand-back for the main orchestrator.
- Next: `review-falsifier` (direct launch, mine) against this commit; G1 evaluates its report.

## [2026-10-08 08:55] gate runner G1 (Opus) — falsifier W1 fixed per ruling; S1/S2 recorded
- Did: evaluated `gate-part2-falsifier.md` W1 (reproduced: `echo "price: \$${COST}USD"` → "sh would run $$ as its process
  id", and following "Write ${COST}" prints `price: ${COST}USD`). Per the [2026-10-08 08:40] ruling `\$${NAME}` stays an
  ERROR; only its diagnosis and fixes changed. An odd number of backslashes before `$${` (sh's `\$`) now gets:
  `Step 's': the command contains \$${COST} (line 16 of the workflow file). It reads two ways: as pflow's escape it was the
  literal text ${COST}; in plain sh it is a dollar sign followed by the value of ${COST}.` with
  `1. For the literal text ${COST} (what it printed before): write \${COST}.` and
  `2. For a dollar sign followed by the value of COST: write \$$COST — or \$""${COST} where a letter, digit or _ follows.`
  (the guide's `\$$COST` repair plus its "braces only where a name character follows" rule). A non-name inner
  (`\$${NOPE:-0}`) gets `\$""${NOPE:-0}` for fix 2; an in-scope pflow reference (`\$${x.stdout}`) gets `\$""{x.stdout}` for
  the literal (`\${x.stdout}` would itself be a leftover) and the existing bound-value fix (now one helper,
  `_bound_dollar_fix`, shared with the plain-escape branch). Code bodies unchanged: there the message ("the string keeps
  both dollar signs") is true for `"\$${X}"` — checked.
- Changed: `src/pflow/core/workflow/data_flow.py` (`_odd_backslashes_before`, `_escape_diagnostic(…, backslashed=)`,
  `_dollar_then_expansion_fixes`, `_bound_dollar_fix`); `tests/test_integration/test_code_body_leftovers.py` +4.
- Verified: every suggested form run under sh, bash and dash before writing it (`\${COST}` → `${COST}`, `\$$COST` → `$4.50`,
  `\$""${COST}USD` → `$4.50USD` quoted and unquoted, `\$""${NOPE:-0}` → `$0`, `\$""{x.cost}` → `${x.cost}` quoted and
  unquoted; `\\$${X}` is backslash + pid — left on today's message). Tests: each fix, applied, validates AND runs printing
  what it promises (out-of-scope, in-scope, expansion-form rows); the plain `$${X}`, the in-scope plain escape and the
  `\\$${X}` (even backslashes) cases keep today's exact text (presence partners; the last passes pre-fix — regression
  guard). Mutations: backslash detection off → 3 red; every escape treated as backslashed → 3 red; restored (`cmp`).
  Real CLI: the probe prints the text above; both fixes applied in the file print `price: ${COST}USD` / `price: $4.50USD`.
  Checkpoint §3 drafts: plain-escape message, its `Write ${PRICE}` fix, the in-scope `\$$COST` fix and the code-body texts
  unchanged (their exact-text tests untouched and green). `make check` green; `make test` **10586 passed** / 0 failed.
- Deviations/surprises: new drafted text (beyond the checkpoint, ruled case): the two-readings message and the three
  fix-2 variants above. Detection is backslash-count only, not quote-aware (no shell lexer — D5): inside single quotes
  `'\$${X}'` is literal to sh yet still gets this message; it was an error before too.
- S1 (approval preview shows typed values / truncated env line — plan D11) and S2 (`${input}` in a shell comment is a
  leftover ERROR — follows the ruled whole-body read): orchestrator-dispositioned (follow-up / accepted); untouched.
- Self-checks: fully happy — yes; the residue is the single-quote case named above. test-reflect: covered by the
  run-the-advice assertions and the two mutations.
- Next: orchestrator commits.

## [2026-10-08 09:10] task orchestrator (Opus) — completion gate CLOSED
- Falsifier (`implementation/gate-part2-falsifier.md`, direct launch on `3d14aba2`): 0 Critical; W1 fixed by G1 per my
  ruling (still an ERROR; the `\`-preceded `$${` message now states both readings, each fix run under sh/bash/dash);
  S1 (approval preview shows typed values — plan D11) → follow-up issue; S2 (`${input}` in a shell comment blocks —
  the ruled whole-body read) → accepted.
- Verified on the final tree (mine): `origin/main` has not moved since `4ab61390`; `make check` green;
  `make test-all-local` **10638 passed / 2 skipped**.
- Every finding of both gates is dispositioned (G1's two entries + this log). The untracked
  `implementation/baseline/task159-{before,after}/` (regenerable from `a296ceca` via `task159_actual.sh`) stay in the
  worktree — deletion is permission-denied for this agent; named in the hand-back (they make the tree non-clean for
  `scripts/worktree rm`).
- Next: spec Status → done; `create-task-review`; `create-pr`.
