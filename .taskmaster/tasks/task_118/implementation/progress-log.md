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
