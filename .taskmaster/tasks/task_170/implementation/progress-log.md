# Task 170 — Progress Log

Append-only. Entry format: `.taskmaster/orchestration/ORCHESTRATION.md` → "Progress-log entry format".
Spec: `../task-170.md` · Plan: `implementation-plan.md` · Base: `7dc5ad5d` (== origin/main at planner launch, 2026-09-28).

## [2026-09-28 23:40] task-planner — planning complete (plan + self-review folded)
- Did: investigated (9 searchers, ~20 executed probes), wrote `implementation-plan.md`, ran a seven-lens plan battery, verified every Critical by execution/reading, folded (Appendix A of the plan), merged `origin/main` (`7d7ffd44`: #628/#624/#639) into the branch as `c07acb4d`.
- Changed: `implementation/implementation-plan.md` (new), `task-170.md` (seven in-authority line corrections: lru-cache no-cache list, deferral sites incl. `:1155`/`sub_workflow_resolver`, loop-validator location, the int-inner `??` freeze case, `_diagnose_carry_ref` cite, #262 flips-as-consequence, Parity-forced validator corrections sentence), this log.
- Verified: base `7dc5ad5d` == origin/main at launch; merged head baselines — `make test` 9276 passed, `make check` green, `make test-e2e` 46 passed/2 skipped, freeze harness 812 passed; the §1 truth tables executed on `7dc5ad5d` (dynamic index, escapes, walk pair, converse-silent class, output sources, the loud-today Issue shapes, `is_type_compatible("int","str") is True`, `TEMPLATE_PATTERN` sees only `${i}`, balanced-escape regex on five ledger cases). | Assumed: the carry-with-Issue loud case (inferred from the same mechanism — phase-1 row verifies); `web/` vitest works once `npm ci` runs (node_modules absent in this worktree).
- Deviations/surprises: the battery overturned four load-bearing design points of the draft (resolve() auto-parse contract; Issues needed as a second channel; per-key `inputs` for inject_none; inner refs must not be "variables") and the corpus harness (the nested `[N]` over-rejection sat under the planned producer; strict xfail without `raises=` would have green-lit a harness bug). Old 4a/4b merged into one engine-contact phase because the facade's semantics reach runtime consumers immediately. Two rulings reversed from the draft: R4 (narrow `$node.x`), R5 (reject `??` chunks). One ledger-wording conflict escalated (declared outputs "skip" vs error). Not a spec contradiction otherwise.
- Self-checks: fully happy with the plan's shape; residual doubts are the four handback questions; test-reflect: n/a (no tests written).
- Next: main orchestrator rules on the handback questions and the size call, then launches phase 1 (Agent A, Opus/high) on `c07acb4d`.

## [2026-09-28 23:55] task-planner — rulings written into the spec ledger
- Did: recorded the main orchestrator's four rulings (all at importance 2, each matching the plan's recommendation) in `task-170.md`: ledger wording for declared outputs (error unless all-absent `??`), `$node.x` output-source form removed, `??` chunk vars rejected at parse, inline-list `batch.items` stays unflagged (Out of scope, lane-B pointer); added the phase-4d `npm ci` note to Implementation Notes.
- Changed: `task-170.md`, this log. No code; no implementation (user ruled no new starts this session).
- Verified: each ruling matches the plan's §0.6 (R4/R5/R12) and Appendix A row; nothing in the code disagrees (executed evidence in the previous entry). | Assumed: none.
- Deviations/surprises: none.
- Self-checks: clean.
- Next: the next main orchestrator launches the Opus task orchestrator on the committed plan; phase 1 starts on the merged head.

## [2026-09-29 09:00] task-orchestrator (Opus) — bootstrap, baseline
- Did: verified base (branch tip `25e14b1f`; `origin/main` `848cc7c8` differs from the merged base `7d7ffd44` only in `.taskmaster/orchestration/*` + start-orchestration assets — no producer-facing change, no merge needed before phase 1); `make install`; read ORCHESTRATION, spec, plan, log, ADR-0006/0015, CONTEXT, braindump (the June braindump predates this plan — its "resolvable: bool" rule and agent names are superseded).
- Verified: Python 3.14.0 venv; `make test` 9276 passed; freeze harness 812 passed; `make check` green; `make test-e2e` 46 passed / 2 skipped — identical to the planner's numbers. Logs under `scratchpads/task-170/` (gitignored).
- Deviations/surprises: `make install` reports `core.hooksPath` set → pflow pre-commit hooks not installed in this worktree; commits will not run the hooks, so `make check` before every commit is the gate.
- Next: launch Agent A (Opus/high) on phase 1; stop after phase 1 per plan §3.

## [2026-09-29 13:40] Agent A (Opus) — phase 1: parity corpus + characterization (tests only)
- Did: built the corpus harness and ALL row groups 1a–1g, every `today` cell measured by running the code (probe scripts under `scratchpads/task-170/phase1/`); executed the mutation ledger; captured the examples baseline; directed test-reflect.
- Changed (all NEW unless noted; zero `src/` edits):
  - `tests/test_integration/test_template_parity.py` — harness (Row/Expect/outcomes; a `SURFACES` table: one `build`/`drive`/`observe` entry per surface; `HarnessError` for harness preconditions so an `xfail(raises=AssertionError)` item can never swallow a harness bug); 1b `TestSurfaceParity` (121 rows: param 47, batch 18, loop 16, output 15, sub-workflow 6, prewarm 3, cache 16); 1d `TestDynamicIndexConsumers` (21 rows); `TestRunnerOnlyRows` (R10), `TestDeferralSitesEscapeOnly` (R6), 1c `TestHistoricalFixtures` (4516cd72, #266, 6b7faf8f, #630 ×2 today+after), `test_example_nested_index_runs_unchanged`, 1e `TestRawPaths`.
  - `tests/test_core/test_template_grammar.py` — 1a (76 rows, 17 tagged `flips_in="4a"`), literal-grammar invariants (counted), strict⇒discoverable (counted; 4a replaces it), 1f walk pair (12 rows × both readers) + raw-reader/dynamic-index pin + array-`??`-None.
  - `tests/fixtures/template_corpus/nodes/producer.py` — `TemplateCorpusProducer` (payload via FILE) + `TemplateCorpusSink` (typed `sink`/`sink_list`/`sink_str`/`sink_any` + `sink_union: str|dict`, added for the plan's "union" shape).
  - `tests/CLAUDE.md` — one "Find the test owner" row.
  - `.taskmaster/tasks/task_170/implementation/examples-baseline/` — `capture.py`, `manifest.json`, 29 normalized `*.json`.
- Verified: `make check` green; `make test` **9695 passed, 81 xfailed** (baseline 9276 → +419 passed, +81 xfailed — exactly the two new files: `pytest <both files>` = 419 passed / 81 xfailed); freeze harness **812 passed** (unchanged); `git diff --stat -- src/` empty after every mutation and at the end; every xfail item fails with `AssertionError` for the intended reason (checked with `--runxfail`: 81/81 AssertionError, each message shows today's measured value); corpus runs order-independent (random order + `-n 8`). e2e not re-run (no e2e-marked test added). | Assumed: Windows — no shell consumer in the corpus (code/sink only); the one shell run is the committed `examples/test-nested-index.pflow.md` (bash via `PFLOW_BASH` on the Windows job; stdout `.strip()`ed); markdown paths are `json.dumps`-quoted (YAML double-quoted escapes) — not executed on Windows here.
- Mutation ledger (each applied to `src/`, corpus run, file restored from a byte copy; red = counted failures):
  - drop `(?<!\$)` in `TEMPLATE_PATTERN` → 9 red (escape_only, sub_inputs/sub_workflow/prewarm escape rows, grammar `$${var}`/`$$${x}`/`${x} $${x}`, #266, strict⇒discoverable).
  - drop it in `_PERMISSIVE_PATTERN` (the #620 class) → 13 red (validator+runtime escape rows, R6 model, #266, grammar escape rows).
  - drop it in `_INTERPOLATION_PATTERN`'s expr branch → **0 red: an equivalent mutant**, proved by exhaustive enumeration (all 87,380 strings ≤ 8 chars over `$ { } x`: identical `.sub` output) — the escape alternative always wins at the earlier index. No row can catch it; the lookbehind there is redundant.
  - narrow `_PERM_VAR` to `\w` → 4 red (grammar `${my-node.out}`, `${a-}`, strict⇒discoverable, the nested-index example).
  - derive `found` from `value is not None` → 10 red (found-None coalesce, complex stringify, 6 walk-pair items, array-`??`-None).
  - `has_templates == bool(TEMPLATE_PATTERN.search)` → 9 red (escape-only routing rows, R6 model, grammar escape rows).
  - drop `batch.items` from `_node_template_value_sources` → 3 red; drop the loop fields → 4 red.
  - Pass 5 field-checks `??` operands → 15 red (#441 rows, 4516cd72, `??` loop/batch rows).
  - skip the `[${` nested count → 36 red (every dynamic-index validator row, the example).
- Examples baseline re-run (phase 5): `uv run python .taskmaster/tasks/task_170/implementation/examples-baseline/capture.py --check` — exits 1 and prints a unified diff per differing example. Normalization: every `duration_ms`/`node_timings` value → 0, UUIDs → `<UUID>`, repo root/cwd/HOME → placeholders; fresh HOME + cwd per run (no memo cache, no settings). Two consecutive runs diffed clean. JSON is written `ensure_ascii=True` because the `pretty-format-json` pre-commit hook rewrites non-ASCII (a `False` setting made the hook edit 7 files). 29 examples = every example needing no API key/network/MCP (inventory of node types incl. sub-workflows); required inputs get fixed params in `EXAMPLES`; 11 exit 1 by design (error-handling/invalid fixtures).
- Deviations/surprises:
  1. **§1 cache-var coalesce is only half right** — `a.x ?? b.y` renders ABSENT only when root `a` never ran; with `a` present and `.x` missing the chain RESOLVES today (`${p.nope ?? p.out_str}` → `"Base: S"`, row `cache_var_coalesce_present_root_r5`). So R5 ("reject every `??` chunk var at parse") also turns a working shape into an error. Encoded per the decided ruling; flagged for the orchestrator (not a stop: no stated `today` value was contradicted, the ledger rationale is incomplete).
  2. §1's inferred loud carry case `${tick.result.0}` → `LoopCarryError` is unreachable: the validator rejects it ("carry values must reference this loop node's own latest output") and compile-time data-flow raises `CompilationError` first (row `loop_carry_issue_shape`). Still loud.
  3. Converse-silent `${data..result.x}` depends on structure: `${p..out}` is silent (OK + static), `${p..out.x}` errors for the wrong reason ("does not output 'out'") — both rows kept.
  4. Pass 8 fires only when items come from an upstream batch's `results` (`_infer_batch_item_structure`); the Pass-8 `??` rows use `items: ${b.results}` via an `upstream_batch` node.
  5. Measured gaps not in the plan, pinned: (a) an input used only in an output `source:` is flagged "never used" though the runtime resolves it (`output_only_input_use_flagged_unused`, no phase flips it — the §0.3 operand iterator leaves outputs out); (b) `${p.out_arr[${nope}].x}` with undeclared `nope` validates clean (inner refs never root-checked; after 4b per delta 6); (c) the chunker cuts a dynamic-index cache var at the inner `}` (`p.out_arr[${i}` — row flips in 4c); (d) `runtime/workflow_executor.py:771` decides unresolved-ness from the RESOLVED `workflow` text (`"${" in workflow`), so a literal `${x}` child path can never run — a #630-pattern site absent from the spec's list (R6 does not change it); (e) the #630 strict message names NO reference ("Unresolved template in parameter 'sink_any'") — rows assert that text.
  6. Plan 1d labels the declared-output dynamic-index flip "4a"; derived from §0.2 the int-inner/outer-missing case flips in **phase 2** (rewritten ref joins the unresolved set) and only the non-int case in 4a — two rows. Also: phase 2's interim `issues` rule ("unescaped `${` not matched after the pre-pass") may catch the non-int rewrite `${a[abc].x}` already in phase 2 → a possible early XPASS for `dyn_non_int_inner_names_outer`/`dyn_declared_output_non_int` that phase 2 re-derives.
  7. `after` messages the plan does not fix verbatim are taken from its text: `Malformed template` (§0.3 keeps the shape), `cache prose may not contain template references` (§0.3 — note §0.3 says markdown-built prose never has one, while R2 makes Issues prose; the 4c implementer settles which message), `output source has no template expression` (R3), `coalesce is not supported` (R5), plus root-name substrings (`lsit`, `typo`, `nope`, `${x}`). A flipping phase whose wording differs sees its `after` item still failing — re-derive there.
  8. Harness shape vs plan: 1d is Row tables (same parametrized tests, `mutation` field) rather than "plain tests"; the plan's typed sink gained `sink_union`; the `workflow: ${child}` path rides in a declared input; loops' end-to-end observation is the iteration count (trace node events); prewarm's silent drop is `Absent` (the helper returns `None`, no report exists) rather than a fabricated `Unresolved`; the R6 model finding is a WARNING, so those rows read warnings; #630 fixtures use a `code` node (Windows) instead of the issue's shell repro.
  9. Pitfall 17 hit: scanning `src/pflow/nodes` at collection imported the agent backend before `test_agent`'s SDK stub → 21 red agent tests. Fixed by adding only the fixture-dir scan to the conftest-served core registry (`registry.save({**load(), **corpus})`).
  10. `rm -rf` denied: an accidental `tmp_out/` dir at the worktree root was removed with `rmdir` (empty); nothing else created outside scratch.
- Self-checks: fully happy? Mostly — raised and fixed: harness asserts could hide inside xfail items (→ `HarnessError`); `Unresolved` for batch items/prewarm checked a message the harness itself fabricated (→ batch items now drive the executor's own `_resolve_and_validate_items`, prewarm is `Absent`); cache `Absent` could pass for a `prompt_cache` name that is not a chunk (→ required); build/drive/observe were three if-chains per surface (→ one `SURFACES` table, per the simplicity lens). Residual doubt: items 1, 5(d), 6, 7 above are judgment the orchestrator should see. test-reflect (directed): deepened `batch_items_*` (real executor report), `prewarm_system_*` (Absent, not a fabricated report), cache Absent rows (chunk-name precondition), `cache_prose_unclosed_r2` (added its 4c validator `after`, was an unflagged message change); added `permissive_missing_field_recorded` + `dyn_permissive_outer_field_missing` (the `mode` field had no row), `output_only_input_use_flagged_unused`; deleted the redundant third cache render and the unused `batch_extra`/`child_inputs` Row fields; kept `test_strict_matches_are_discoverable` (tautological by design, but it went red under two mutations; 4a replaces it). Every "must not appear" has a same-medium presence partner (R6 model, `forbid`, CLI `-o`).
- Next: orchestrator commits phase 1 and rules on deviations 1, 5(d), 6, 7; phase 2 (Agent B) starts on this corpus.

## [2026-09-29 10:00] task-orchestrator — standing obligations (main-orchestrator notes) + phase-1 rulings
- Obligations (main orchestrator, 2026-09-29):
  - **Completion gate includes `review-falsifier`** (spec makes testable user-facing promises: Sanctioned deltas, behavior freeze, converse parity). The orchestrator launches it directly, LAST, after the reading battery's confirmed fixes land, packeted with the spec path + `review-spec-conformance`'s Requirement Inventory; its report goes to the gate-runner with the fan-out's. Tier ≥ Full (diff touches `runtime/engine/`). Log which lenses ran / were skipped, with a reason each.
  - **User's governing lens — pass VERBATIM to every phase implementer and gate-runner:** "We should prioritize simplicity of the FINAL code, not how easy it is to get there. When in doubt we should ask ourselves whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet? What this doesnt mean is overfitting to "top 10% of codebases" and overengineering, this is about more simple code that is optimized for AI agents to understand and add features to."
  - **Collision:** the #615 lane edits `runtime/engine/engine.py::_gate_pausable` (`:98-121` + a minimal iteration read at its call site) by user ruling — disjoint from this plan's `engine.py` sites (`:130-167`, `:242-258`, `:393-402`); expect a small textual merge at the pre-PR main merge. `main` also moved by #617 (PR #651, `nodes/file/delete_file.py` + docs) — not this surface.
- Rulings on Agent A's phase-1 deviations (orchestrator, importance ≤ 2 unless stated):
  - **Dev 1 (R5 turns a working shape into an error) → ESCALATED (3/5)** to the main orchestrator: new evidence contradicts the ledger's R5 rationale ("the runtime silently drops such chunks") — `${p.nope ?? p.out_str}` renders today when root `p` ran. Not needed before 4c; phases 2–4b proceed. Resume point for 4c: the ruling.
  - **Dev 5(a) (input used only in an output `source:` → "never used" ERROR while the runtime resolves it)** → a one-way-soundness over-rejection; sanctioned class ("over-rejections the runtime resolves flip to accepted"). **Lands in 4b**: unused-input accounting counts output-source references; row `output_only_input_use_flagged_unused` gains an `after` (Ok) flipping in 4b + a negative partner (a genuinely unused input still errors).
  - **Dev 5(d) (`runtime/workflow_executor.py:771` decides unresolved-ness from the resolved `workflow` text)** → NOT migrated. The engine already judges unresolved-ness of the `workflow` param through the channels (strict raises; permissive records); the `:771` check is the executor's last-line loud message for a permissive-mode literal path, and the only false positive is a child path that literally contains `${` (only reachable via `$${`) — not an observed use. Named in the task-review's unmigrated list beside §6.
  - **Dev 6 (declared-output dynamic-index flip split 2 / 4a)** → accepted; phase 2's gate re-derives any early XPASS of `dyn_non_int_inner_names_outer` / `dyn_declared_output_non_int` per §0.5.1.
  - **Dev 7 (unfixed `after` wording)** → accepted as provisional; a flipping phase whose wording differs edits the `after` substring and logs it (a re-derivation, not a row trim). Cache-prose message: an **Issue** in prose (markdown or dict IR) gets the standard malformed-template message from the one Issue pass; an **Expression** in prose (dict IR only — the chunker makes every markdown Expression a chunk) gets "cache prose may not contain template references".
- Verified: `make test` 9695 passed / 81 xfailed; `make check` green; `git diff --stat -- src/` empty (orchestrator re-run).
- Next: self-check resume of Agent A, commit phase 1, launch Agent B on phase 2.

## [2026-09-29 14:10] Agent A (Opus) — phase 1 self-check (directed)
- Did: re-audited for inferred `today` cells, harness shortcuts, order dependence and baseline noise.
- Changed: `examples-baseline/capture.py` only — the child env now drops inherited `PFLOW_*` switches except `PFLOW_BASH`. Before this, a caller's `PFLOW_TEMPLATE_RESOLUTION_MODE` or `PFLOW_MAX_NODE_VISITS` would have changed the phase-5 outputs.
- Verified: `PFLOW_TEMPLATE_RESOLUTION_MODE=permissive capture.py --check` → 29 examples, 0 differing. No absolute path, timestamp or version string is left in the 29 stored JSONs (grepped). `make check` green; `make test` 9695 passed / 81 xfailed; `git diff --stat -- src/` empty.
- Loose ends kept on purpose:
  - Every `today` cell was executed. Rows written without a separate probe still passed on their first run against the code; the `after` cells are derived (as already logged).
  - Harness shortcuts, both cross-checked end to end on validator-clean rows:
    - `seed_shared` sets declared-input values itself (param else default) instead of running `prepare_inputs` coercion. Every corpus input has a typed default, so the values are identical.
    - `_drive_batch_param` rebuilds the item context as `{**shared, item, __index__}`. The real executor also resets the node namespace per item.
  - The fixture module's top-level import name is the generic `producer` (the plan's filename). A future `producer` module on `sys.path` would shadow it. That would be loud, not silent: the import-time guard raises if the scan does not find exactly the two corpus nodes.
  - Order: `make test` runs in random order under xdist; green on 3 full runs plus 2 targeted random runs.
  - Phase-5 diff: expected differences also come from anything merged from `origin/main` between now and phase 5. If main is merged before phase 5, re-capture on the merge commit first, so the diff shows only Task 170's changes.
- Self-checks: clean after the env fix.
- Next: orchestrator commits phase 1.

## [2026-09-30 00:30] Agent B (Opus) — phase 2: one internal walk + the unresolved/issues channels (#630)
- Did: merged the two traversal loops into `_walk` and added `Resolution` + module-level `resolve(value, ctx, *, auto_parse=False)`. Switched every phase-2 consumer to the channels: the strict check, per-key `inputs` + `inject_none`, the loop-carry helper, `_resolve_template_string`, `output_resolver`, `resolve_batch_items` (string form), `_resolve_chunk_value`, the diagnostic and `classify_unresolved_references`. Deleted `contains_unresolved_template`/`_check_string_unresolved`/`all_variables_from_absent_nodes`/`_traverse_path_part`/`_check_array_indices`/`_resolve_inline_expr`. Delta 1 flips.
- **Differential gate (orchestrator ruling, replacing "commit before any src/ edit"):** wrote `tests/test_runtime/test_template_walk_differential.py` with legacy `variable_exists`/`resolve_value` + all four private helpers vendored from `git show 7dc5ad5d:…`. 21 paths × 28 values × {dict, MappingProxy} context = **1177 combos, green on UNMODIFIED `src/`** (it includes a chained index into JSON-string elements; legacy never re-parses those between chain links, and the walk keeps that). Green again after the change, then deleted. A pre-change copy is at `scratchpads/task-170/phase2/differential-snapshot.py`.
- Changed:
  - `src/`: `runtime/template_resolver.py` (walk, `_lookup_expression`, `_resolve_string`, `Resolution`, `resolve`; an `issue` alternative in `_INTERPOLATION_PATTERN`; `_DYNAMIC_INDEX_OPEN`; context params widened to `Mapping`); `engine/template_resolution.py`; `engine/template_errors.py`; `engine/engine.py` (only `:48`, `:70`, the carry site `:245` + new `_plan_left_unresolved`, and `_resolve_template_string`; `_gate_pausable` untouched); `output_resolver.py`; `engine/batch_executor.py`; `core/prompt_cache.py`.
  - Tests, sanctioned: deleted `TestContainsUnresolvedTemplate`; moved the 7 `inject_none` calls to the new signature.
  - Tests, new: `TestResolutionChannels` (10) in `test_template_resolver.py`; `TestInputsResolvedPerKey` (6) in `test_node_wrapper_template_validation.py`; `TestDiagnosticClassifiesTheResolutionSet` (2) in `test_template_error_messages.py`.
  - Corpus: 9 rows flipped to `now(after)`; the two `test_630_*_today` items deleted and the `_after` markers removed.
- Verified:
  - `make check` green. `make test` **9709 passed / 70 xfailed**. Against the baseline 9695/81, which I re-captured myself: −4 deleted, +10 channels, +6 per-key, +2 diagnostic = +14 passed; −11 xfailed = the 11 flipped items (their `after` items now pass as plain tests).
  - Freeze harness 818 (812 − 4 + 10). Corpus 419 passed / 70 xfailed, every remaining xfail strict. `make test-e2e` 46 passed / 2 skipped. Four-name grep over `src/ tests/` is empty. The `template_resolutions` trace tests are unmodified and green. No trace field added; the channels never ride `last_resolutions`.
  - **Verdict differential** (scratch, `scratchpads/task-170/phase2/verdict_diff.py`): the 7dc5ad5d resolver + old echo check vs the new `resolve()`, over 5130 template×context combos (escapes, Issues, coalesce, dynamic index int/OOB/non-int/absent, upstream text).
    - Resolved values are identical in every combo.
    - The verdict differs in exactly two classes. 348 cases go silent→loud; all are a rewritten int dynamic index. 52 go loud→silent; all involve `$${` or an upstream value containing `${…}` text. Both classes are delta 1.
  - Real surface:
    - `uv run pflow repro630.pflow.md` prints `hello | ${greeting} | src says ${greeting}`, exit 0. Before the change it failed with "Unresolved template in parameter 'command'" (checked by stashing `src/`).
    - `dynidx.pflow.md` (`${src.result[${idx}].nope}`) now fails naming `${src.result[0].nope}` as a path_error on `src`. Before, it silently output the literal.
  - Mutations, each killed by a counted failure: dict-wide subtract of injected expressions; roots taken from `unresolved` only; no literal guard; no outer-root neutralization; no dynamic-open guard; Issues into `unresolved`; interim Issue rule off; `auto_parse` ignored; alphabetical diagnostic order; carry helper off (`test_loop_config.py` permissive ×2).
  - Assumed: Windows is not exercised (no new shell-dependent test).
- Deviations/surprises:
  1. **The plan's phase-2 `issues` rule contradicts itself.** Plan §2 defines it as every unescaped `${` not matched after the pre-pass, then calls that "exactly the class today's echo check catches". Executed, that rule flipped 5 non-phase-2 corpus rows to loud, and none of them XPASSed their `after`: `output_prose_wrap_recorded_drift`, `output_escape_only_r3`, `silent_coalesce_inner_index`, `dyn_coalesce_non_int_inner`, `dyn_declared_output_non_int`. The fence won, so I implemented the stated intent: an Issue counts only in a string resolution left untouched (no expression resolved, no escape, no index rewritten). That is the old echo class; the verdict differential above confirms it.
     - A second interim clause came out of the self-check: the opening of a dynamic index the pre-pass could not rewrite (`${a[${` …) is not an Issue. Without it, `${g.items[${g.i}].x}` as an Optional input with both roots absent stopped getting `None` and raised — a regression against today, now pinned by `test_dynamic_index_from_an_absent_branch_is_injected`.
     - Both clauses die in 4a with `parse().issues`. **Heads-up for 4a (my inference, not executed):** the plan's Issue span ("to the first `}`") swallows the inner `${p.out_str}` of the normalized output source `${prefix ${p.out_str}}`. So `output_prose_wrap_recorded_drift` (`now(Resolves("${prefix S}"))`) and `output_escape_only_r3` will likely break under 4a's grammar.
  2. **`build_template_error_diagnostic`** takes `resolution: Resolution | None = None` as the 4th positional-or-keyword parameter. It has 23 direct test callers outside §5 (`test_template_error_messages.py`, `test_runner.py`, `test_failed_node_invariant.py`). With the default, they stay unmodified and the plan's call shape works. The default resolves the template itself; every production caller passes its own resolution.
  3. **Carry helper:** implements `var in entry["unresolved_expressions"]` and drops the plan's `or entry["issues"]`. A carry is a validator-enforced simple self-reference, so it cannot hold an Issue. Any Issue elsewhere in `inputs` would have raised a `LoopCarryError` blaming the carry.
  4. **`inject_none` interim:** the outer-root/all-expressions test neutralizes `[${…}]` with `TemplateResolver._BRACKET_INDEX_PATTERN` from the engine. That is a private reach and a phase-2 stand-in for `parse(t).expressions`; 4a deletes it. A key is injected only if every operand is a non-literal reference with an absent outer root and there is no Issue. So `${b.x ?? "d"} ${c.y}` is not injected, same as today.
  5. **Diagnostic order:** `unresolved` is a frozenset, so `_in_source_order` sorts by the position of `${expr}` in the author text. Rewritten dynamic-index texts sort last. This keeps today's message order; the new diagnostic test pins it.
  6. **Early XPASS, re-derived per §0.5.1** (both explained by this diff; markers removed):
     - `dyn_optional_input_absent_root`: the outer-root injection rule is §0.2's phase-2 rule.
     - `dyn_batch_item_inner_renderer`: item.i=5 is out of range, so the rewritten ref joins the set — the class §1 flips in phase 2.
     - `dyn_non_int_inner_names_outer` and `dyn_declared_output_non_int` do NOT XPASS under the final rule. They stay 4a.
  7. **Row re-derivations beyond "delete today + marker"**, under the Dev-7 wording ruling:
     - `dyn_batch_item_inner_renderer` gained `end_to_end=Unresolved(("p.out_arr[5].x",))`. The run's error line names the rewritten ref; the direct report names the author text through the template echo. 4a drops the override.
     - `dyn_permissive_outer_field_missing` gained `end_to_end=Resolves("${p.out_arr[0].nope}")`. A permissive run completes with the literal.
  8. **Test edits beyond §5:**
     - `TestDepthLimit`'s comment named `contains_unresolved_template`; I reworded it because the gate grep must be empty.
     - Three of the 7 `inject_none` tests had inconsistent fixtures under the new signature (the resolution is now the judge). `test_resolved_value_not_modified` got a context in which its template resolves. `test_no_injection_when_key_not_inputs` now goes through `resolve_templates`, because the function no longer takes `key`.
  9. **Not fixed, outside my phase's files:** `src/pflow/runtime/CLAUDE.md` "Template resolution" should say that `resolve()` returns the channels the engine consumes. Phase 3 edits that section. Also out of scope: #503 untouched; the `ValueError` contract is unchanged.
- Self-checks:
  - Fully happy? Raised and fixed the Optional-input dynamic-index regression (dev 1, second clause). Doubts I would not otherwise volunteer:
    - Dev 1 is a judgment call on a self-contradictory plan line; a reviewer may prefer I had stopped.
    - The two interim clauses and the private reach (dev 4) add phase-2-only complexity that 4a must remember to delete. The comments say so.
  - test-reflect (directed): deleted `test_facade_is_the_value_view` (tautological: the facade delegates by construction). Deepened `test_issue_is_its_own_channel` (`not result.ok`). Added `TestDiagnosticClassifiesTheResolutionSet` after a mutation (alphabetical order) survived the whole suite; both of its tests fail on the old code. Added `test_dynamic_index_from_an_absent_branch_is_injected` (the regression). Every other new test was mutation-checked above. Kept the equality-based channel tests (exact `Resolution` equality covers value + both channels).
- Next: mid-task review (`review-silent-failures`, `review-impact-completeness`) on this diff; the orchestrator commits and dispositions deviations 1–4; then phase 3 (Agent B resumed).

## [2026-09-30 01:00] task-orchestrator — phase 2 verified + rulings; main-merge plan
- Verified (orchestrator re-run): `make test` 9709 passed / 70 xfailed; `make check` green; four-name grep over `src/ tests/` empty; `engine.py` hunks only at imports `:45/:67`, carry `:242-273`, `_resolve_template_string` `:409` — `_gate_pausable` untouched.
- Correction to my bootstrap entry: pre-commit hooks DO run on commits in this worktree (they ran on `006bd80b`); the `core.hooksPath` notice is about pflow's own installer, not about hooks being absent.
- Rulings on Agent B's deviations (importance ≤ 2):
  - Dev 1 (interim `issues` rule = today's echo class, not "every unmatched `${`") → **accepted**: the fence outranks plan prose (plan authorities; the verdict differential confirms the echo class exactly). Both interim clauses die in 4a. **4a obligation:** the plan's Issue span "to the first `}`" must not break the recorded prose-wrap drift rows (`output_prose_wrap_recorded_drift` → `'${prefix S}'`, `output_escape_only_r3`) — 4a re-derives against those rows and hands back if the grammar forces a row change.
  - Dev 2 (`build_template_error_diagnostic(..., resolution=None)` self-resolving default for 23 unsanctioned test callers) → accepted for now; a test-convenience default in production code is named for the completion-gate simplicity lens (candidate: make it required and re-point the callers in phase 5).
  - Dev 3 (carry helper drops `or entry["issues"]`) → accepted (a carry is a validator-enforced simple self-ref; the clause would mis-blame the carry).
  - Dev 4 (`inject_none` reaches `TemplateResolver._BRACKET_INDEX_PATTERN`) → accepted as interim; **4a deletes it** with the pre-pass (on the 4a handoff grep).
  - Self-check: answered in-context in B's entry (regression found + fixed, residual doubts stated); test-reflect directed + resolved. Not re-asked.
- Main-merge plan: `origin/main` is `8bb82c30` (#617 PR #651, #618 PR #653 `nodes/python/output_capture.py`, #615 PR #655 incl. `runtime/engine/engine.py::_gate_pausable`, `runtime/engine/CLAUDE.md`, `cli/commands/run.py|resume.py`). Merge AFTER the phase-2 mid-task review's fixes land and BEFORE phase 3 (phase 3 re-points `cli/` + `execution/` imports on the current files); `make check` + `make test` on the merged result; then `capture.py --check` — any examples diff there is main's (#618 touches code-node capture), logged, and the baseline re-captured on the merge commit so phase 5 diffs only Task 170. Phase 5's `runtime/engine/CLAUDE.md` edit re-reads #615's version.
- Next: commit phase 2; commission the mid-task review (`review-silent-failures` + `review-impact-completeness`) with Agent B as gate-runner.

## [2026-09-30 01:40] Agent B (Opus) — phase-2 mid-task review (gate-runner)
- Did: ran deep-review in code mode on `006bd80b..a32052f6` through the pflow fan-out. Provider codex (cross-model; I am the Claude builder), lenses exactly `review-silent-failures` + `review-impact-completeness`. The review target told both lenses about the accepted deviations 1–4 and the deferred sites (four cost-analysis sites → 4a, `workflow_executor.py:771` ruling, `_resolve_static_prefix_for_cache` → 4c, R12). Waited in-turn and read the merged report in full (`scratchpads/task-170/phase2/review/report.md`). Coverage: both lenses reported on the exact scope, with no coverage gaps.
- Findings, each dispositioned:
  1. **Critical, `review-silent-failures`: a partially resolved optional input silently becomes `None` → CONFIRMED by execution, FIXED.**
     - Repro: an optional input `"item [${idx}] ${branch.stdout}"` with `idx` present and `branch` absent. At `a32052f6` it gets `{'opt': None}` with no error; at `006bd80b` it raised "Unresolved variables … ${branch.stdout}" (probe: `scratchpads/task-170/phase2/review/probe_critical.py`).
     - Cause: `_left_to_absent_nodes` neutralized EVERY `[${…}]` with `_BRACKET_INDEX_PATTERN`, including a bracketed expression in prose. The resolved `${idx}` vanished from the operand set.
     - Fix: new `TemplateResolver._DYNAMIC_INDEX` (`(\${VAR)\[\${VAR}\]`) replaced with `\1[0]`, looped until stable (one index per reference per pass). Only indices inside an outer reference are neutralized.
     - Test: new `TestInputsResolvedPerKey::test_bracketed_reference_outside_a_dynamic_index_counts_as_resolved` fails before the fix (1 failed) and passes after.
     - Re-verified: the dynamic-index injection probes (`${g.out_arr[${g.i}].x}`, `${…[${__index__}]…}`, `${…[${h.i}]…}`) plus a chained `${g.a[${i}].b[${j}].c}` all still get `None`.
     - This is interim code; 4a deletes it together with the accepted private reach.
     - Why my phase-2 verdict differential missed it: that differential judged `resolve()` verdicts only, never the injection predicate. The lens found a gap the differential could not reach.
  2. Warnings / Suggestions: none from either lens.
  3. Verified clean (per lenses):
     - Channel adoption at every phase-2 consumer (strict/permissive check, per-key inject, carry, prewarm, output source + declared outputs, batch string form, cache chunk).
     - Found-`None` / falsy values stay distinct from a miss.
     - A required sibling keeps its channel.
     - Every changed-signature caller is updated.
     - `unresolved_expressions` / `issues` never reach `last_resolutions` or the trace.
     - Raw-path consumers are untouched.
     - The deferred sites match their rulings.
- Changed: `src/pflow/runtime/template_resolver.py` (+`_DYNAMIC_INDEX`), `src/pflow/runtime/engine/template_resolution.py` (`_left_to_absent_nodes` neutralization), `tests/test_runtime/test_node_wrapper_template_validation.py` (+1 test).
- Verified:
  - `make check` green. `make test` 9710 passed / 70 xfailed (+1 over the phase-2 commit = the new test).
  - Freeze harness 818 passed. Corpus 419 passed / 70 xfailed.
  - Verdict differential unchanged: 5130 combos, values identical, only the two delta-1 classes differ.
  - Assumed: none.
- Deviations/surprises: the only Critical sat in the accepted interim helper's logic, not in its private-API access. The fix stays inside that interim code and adds one more private pattern, which 4a deletes. No decision at importance ≥3; nothing touches the ledger or an ADR.
- Self-checks: fully happy with the fix. The interim stand-in is now three private patterns deep (`_BRACKET_INDEX_PATTERN` pre-pass, `_DYNAMIC_INDEX_OPEN`, `_DYNAMIC_INDEX`), which is more reason for 4a to delete all of them at once. test-reflect: the new test is a mutation-proven regression test (red before the fix); nothing shallow was added.
- Next: the orchestrator commits the review fix; phase 3 (Agent B resumed) on instruction.

## [2026-09-30 02:00] task-orchestrator — phase-2 review closed; origin/main merged
- Did: verified Agent B's review dispositions (report `scratchpads/task-170/phase2/review/report.md`: both lenses on codex, full scope, 1 Critical fixed with a failing-first test, no W/S); committed the fix `fa551740`; merged `origin/main` `08e1eb68` (#617, #618, #615, root-CLAUDE.md lens edit) as `8113641b` — clean, no conflicts.
- Verified (merged result): `make test` 9738 passed / 70 xfailed (+28 from main's tests); `make check` green; `capture.py --check` → 29 examples, 0 differing (phase 2 + main change no example output; baseline NOT re-captured — still valid).
- Next: resume Agent B on phase 3 (relocation to `core/templates.py`), which re-reads the merged `cli/commands/run.py|resume.py`.

## [2026-09-30 03:00] Agent B (Opus) — phase 3: relocate to `core/templates.py` (mechanical)
- Did: moved the template module with `git mv src/pflow/runtime/template_resolver.py src/pflow/core/templates.py`. Put a shim at the old path (re-exports `Resolution`, `TemplateResolver`, `resolve`; docstring says phase 5 deletes it). Re-pointed every `src/` importer, deleted the `template_resolver()` accessor, landed rule 4, the identity assertion and the subprocess pin, and updated the instruction files. My phase-2 interim private patterns moved with the module, untouched.
- Importer inventory, re-grepped on `a144bbb1` (not the plan's counts): 28 `src/` files. Every hit was a module-level or lazy `from pflow.runtime.template_resolver import …`, plus one relative `from ..template_resolver` (`engine/error_context.py`). Main's #615/#618 files (`cli/commands/run.py`, `resume.py`, `nodes/python/output_capture.py`) import nothing from it, so they are untouched. Tests import only `TemplateResolver` / `resolve` / `Resolution` (23 sites), all covered by the shim. No string-path patch targets, importlib paths or logger-name assertions on the old module exist.
- Changed:
  - `core/` (15 files): every lazy import hoisted to one module-level `from pflow.core.templates import …`. That covers `prompt_cache.py`, `trace_report.py`, `trace_loading.py`, `token_estimation.py` ×6, `context.py` ×4, `sub_workflow_walker.py` ×3, `graph/scope.py`, plus the three module-level importers.
  - `prompt_cache_analysis/context.py`: accessor and its `__all__` entry deleted. Its "do not hoist — drags the runtime stack" layer-policy note is rewritten (no longer true). The four stage consumers (`row_builder`, `discrepancy/predict`, `cross_workflow`, `warnings`) plus context's own four uses now call `TemplateResolver` directly.
  - `runtime/` (11 files), `execution/` (3), `cli/` (2), `mcp_server/services/field_service.py`: import re-pointed.
  - `nodes/llm/llm.py`: its lazy import hoisted to module level. The laziness existed only because the old module was heavy.
  - Comments: `data_flow.py:1429`, `type_checker.py:32`.
  - New tests: `tests/test_import_hygiene.py` rule 4 (`test_core_does_not_import_the_template_shim`: any scope, matches `import pflow.runtime.template_resolver` and `from pflow.runtime import template_resolver`; docstring item 4). New `tests/test_core/test_templates_module.py` with the identity assertion (`TemplateResolver`/`Resolution`/`resolve` are the same objects through the shim) and the e2e subprocess pin (importing `pflow.core.templates` loads no `pflow.runtime*` and no `litellm*`).
  - Instruction/doc files:
    - `.claude/agents/{pflow-codebase-searcher,review-architecture-fit,review-silent-failures,review-plan,review-feature-interactions,review-validation-consistency}.md`, then `make sync-claude-assets` (6 `.codex` twins).
    - `src/pflow/core/CLAUDE.md`: :156, plus a new navigation row for `templates.py` and its leaf rule.
    - `src/pflow/runtime/CLAUDE.md`: owner row, plus the "Template resolution" section now says the language lives in core and that `resolve()` → `Resolution` channels are the only judge of unresolved-ness (phase-2 dev 9).
    - `template_validation/CLAUDE.md`: the regex table gains `_TEMPLATE_OPEN`, `SIMPLE_TEMPLATE_PATTERN`, `_INTERPOLATION_PATTERN`, `_BRACKET_INDEX_PATTERN`; the "three views" rewrite waits for 4b.
    - `architecture/architecture.md:526`; `architecture/reference/template-variables.md:158` (:922 names the still-existing test file, so kept).
    - `architecture/core-concepts/data-type-coercion.md:73/:90`: stale line numbers dropped; :90 now points at the `auto_parse` rule.
    - Module docstring of `core/templates.py`.
- Verified:
  - `make check` green, including asset sync.
  - `make test` 9740 passed / 70 xfailed: +2 over the merged 9738, the two new non-e2e tests.
  - `make test-e2e` 47 passed / 2 skipped: +1, the pin.
  - Zero edits to existing tests (the diff under `tests/` is additions only).
  - Freeze harness 818; corpus 419 / 70 xfailed.
  - Clean-interpreter cycle check `import pflow.core.workflow.validator, pflow.core.workflow.graph.scope, pflow.core.prompt_cache_analysis` → OK. Each hoisted module also imports alone.
  - `grep template_resolver src/` hits only the shim.
  - Examples baseline `capture.py --check`: 29 examples, 0 differing.
  - Planted violations, each seen red and then removed:
    - lazy `from pflow.runtime.template_resolver import …` in `core/prompt_refs.py` → rule 4 red;
    - `from pflow.runtime import template_resolver` → rule 4 red;
    - `import litellm` in `core/templates.py` → pin red (litellm leaked);
    - an import-time `import pflow.runtime.node_state` at the end of `core/templates.py` → pin red (`pflow.runtime` leaked);
    - a subclass copy of `TemplateResolver` in the shim → identity test red.
  - Every file was restored from a byte copy, and all 6 pins passed again.
  - Assumed: none.
- Deviations/surprises:
  1. `nodes/llm/llm.py`'s lazy import is hoisted rather than just re-pointed. The plan listed it only as "(lazy)", and the reason for the laziness is gone.
  2. The subprocess pin lives in a new `tests/test_core/test_templates_module.py`, beside the identity test, not literally beside `test_litellm_runtime.py:882`. That file is litellm's; one home for the two template-module pins is simpler. Same mechanics (`uv_exe`, `prepared_subprocess_env`, e2e marker).
  3. A planted `import pflow.runtime.X` at the TOP of `core/templates.py` fails as a circular ImportError at collection, before the pin can speak. So the direct regression is already loud, and the pin covers the late or indirect leak.
  4. Nothing else — the shim re-exports exactly the three names; no caller needed any other name.
- Self-checks: fully happy? Yes. Loose ends named on purpose:
  - Tests keep the old import path until phase 5, per plan.
  - `template_validation/CLAUDE.md`'s "never `str.split('.')`" line is still false for three validator files (spec: 4b/5).
  - Hoisting ~15 lazy imports makes `core/` import `core.templates` eagerly. The pin proves it is a `pflow.core`-only leaf, and the CLI lazy-import tests (`test_cli/test_lazy_imports.py`, part of `make test`) stay green.
  - test-reflect: n/a beyond the planted-violation checks above (mechanical relocation).
- Next: the orchestrator commits phase 3; phase 4a (Agent C).

## [2026-09-30 10:30] Agent C (Opus) — phase 4a: STOPPED before any src/ edit (Issue span vs output prose-wrap rows)
- Did: read the plan (§0, §1, 4a, §5, §6), the spec, the full log, the guidance CLAUDE.md files, `core/templates.py`, both corpus files and `output_resolver.py`. Captured the baseline. Before writing any code I prototyped the §0.1 tokenizer (`scratchpads/task-170/phase4a/span_probe.py`) to test Agent B's heads-up, following the launch instruction "if the grammar can't keep both rows without a row change, STOP and hand back with the options".
- Changed: nothing under `src/` or `tests/`; this log entry only.
- Verified (executed):
  - Baseline: `make test` 9740 passed / 70 xfailed (matches the phase-3 numbers).
  - **The corpus pins two Issue-span rules that exclude each other.** Structural twins: `${a[${i ?? 0}]}` and `${prefix ${p.out_str}}` (the normalized output source). Both are an OPEN, junk, a nested valid `${…}`, then `}`.
    - Plan span ("to the first `}`"):
      - `${a[${i ?? 0}]}` → one Issue `${a[${i ?? 0}`;
      - `${arr[${idx ?? 0}]}` → Issue;
      - `${a[${b[${c}]}]}` → Issue `${a[${b[${c}`.
      - These are the three grammar `after` rows (`has False`, no variables, verbatim) and `silent_coalesce_inner_index` → StaticLiteral. All four need this rule.
      - But under this rule `${prefix ${p.out_str}}` → Issue `${prefix ${p.out_str}` (it swallows the inner reference), and `${${p.out_str}}` → Issue `${${p.out_str}`. The value is verbatim and the `issues` channel is non-empty, so `populate_declared_outputs` raises.
      - That breaks `output_prose_wrap_recorded_drift` (`now(Resolves("${prefix S}"))`) and `output_escape_only_r3` (`now(Resolves("${S}"))`).
    - "Stop before the next OPEN" span:
      - It keeps the inner `${p.out_str}` as an Expression (value `${prefix S}` / `${S}`).
      - It makes `${i ?? 0}` / `${idx ?? 0}` / `${b[${c}]}` live Expressions, so the three grammar rows and the StaticLiteral row break.
      - It would still need an output-resolver-only rule that tolerates an Issue next to a resolved Expression, because `issues = parse().issues` makes the output loud.
  - **The plan contradicts itself on the same seam.** The 4a table (`implementation-plan.md:723`) sets `_normalize_source` = `source if has_templates(source) else "${"+source+"}"`. Executed on today's resolver:
    - `prefix ${p.out_str}` → `'prefix S'`, ok. That FIXES the drift, while §6 (`:1008`), §0.3 (`:245`) and the spec (behavior freeze + Out of scope) say "recorded, not fixed".
    - `$${p.out_str}` → `'${p.out_str}'`, ok. So `output_escape_only_r3`'s runtime `now(Resolves("${S}"))` cannot survive R4 under any grammar. It exists only through the `$`-prefix branch that R4 deletes. Phase 1 mis-derived it as `now`.
    - `$p.out_str` → `${$p.out_str}`, which is unresolved and loud (R4 as intended). The corpus row `output_dollar_prefix_r4` says 4b while the plan table puts R4 in 4a. That would be an explained early XPASS, so it is not a blocker by itself.
- Deviations/surprises: this is a planning bug, surfaced rather than absorbed. The fence (two `now` rows), the plan's grammar (§0.1 Issue span) and the plan's 4a normalizer cannot all hold. **Options (the orchestrator decides; importance ≥3 because the spec freezes the drift value):**
  - **(1) Recommended, simplest final code.** Keep the plan grammar ("to the first `}`") and apply the plan's 4a normalizer as written (the `$` branch deleted; a source that already contains template syntax is used as-is; otherwise it is wrapped). The normalizer then never creates Issues the author didn't write.
    - Row re-derivations: `output_prose_wrap_recorded_drift` runtime → `Resolves("prefix S")` (the drift is fixed, needs a spec edit to the freeze and Out-of-scope lines); `output_escape_only_r3` runtime → `Resolves("${p.out_str}")`; `output_dollar_prefix_r4` runtime flips early in 4a (explained XPASS).
    - Validator: 4b's §0.3 already keeps `prefix ${n.stdout}` OK on the raw text, so validator and runtime agree on a sensible value.
  - **(2) Spec-conservative.** Keep the plan grammar and today's normalizer (R4 stays in 4b per the row).
    - Row re-derivations: prose-wrap runtime → `Raises(OutputResolutionError)` (the drift goes from a garbage value to loud); `output_escape_only_r3` → Raises.
    - Cost: a validator-OK source now fails at run time. 4b keeps the validator OK for prose sources, so that under-check becomes permanent unless 4b adds an ERROR. It also deviates from the plan's 4a normalizer line.
  - **(3) Keep both row values.** Use the "stop before next OPEN" span plus an output-resolver rule that an Issue beside a resolved Expression rides silently.
    - Cost: it breaks four 4a rows (three grammar rows + `silent_coalesce_inner_index`). It revives the phase-2 interim echo class in a new home, and `${arr[${idx ?? 0}]}` stops being an Issue-only static value. Not recommended: more rules, and the ledger's grammar class blurs.
  - (4) Rejected: a normalizer special case that recomputes `${` + resolve(source) + `}` to reproduce the garbage value.
- Self-checks: fully happy with stopping here. The probe covers exactly the five contested shapes, and nothing else in 4a depends on this ruling except `_normalize_source`, the Issue span, and the three output rows. The rest of 4a (AST, `parse`/`parse_path`/`lookup`, facade, engine/loop/diagnostic/cost-analysis consumers) is unblocked once the span rule is fixed. test-reflect: n/a (no tests written).
- Next: the orchestrator rules on (1)/(2)/(3), plus the R4 timing: 4a per the plan table, or 4b per the row. Then resume Agent C on 4a with the ruling.

## [2026-09-30 10:45] task-orchestrator — 4a output-source span conflict: ESCALATED (3/5); 4a proceeds on the rest
- Agent C's stop verified by reading its probe results against the rows and `implementation-plan.md:723` (the plan's 4a normalizer fixes the prose-wrap drift, contradicting spec Behavior-freeze + Out-of-scope and plan §0.3/§6). Spec contradiction ⇒ escalation, not an orchestrator call.
- **ESCALATED (3/5)** to the main orchestrator, options (1)/(2)/(3) as in Agent C's entry; **recommendation (1)**: plan grammar (Issue span to the first `}`) + the plan's 4a normalizer (`source if has_templates(source) else "${"+source+"}"`, `$` branch deleted). Why: the normalizer stops manufacturing Issues the author never wrote; validator (4b parses the raw source → OK) and runtime then agree on `prefix S` with zero extra rules; option (2) leaves a permanent validator-OK/runtime-raises gap, (3) adds a tolerance rule and blurs the ledger's grammar class. Cost of (1): one user-visible change outside the Sanctioned deltas (a prose-wrapped `source:` interpolates instead of yielding `'${prefix S}'`) ⇒ spec edits (freeze line, Out-of-scope line, sanctioned list). Supporting evidence: docs/guide show only simple sources (`guide/core.md:636` `source: ${source_name}`), so no documented behavior changes.
- Orchestrator ruling (1/5): **R4 lands in 4a** with the normalizer edit (plan table); `output_dollar_prefix_r4`'s runtime row flips as an explained early XPASS.
- `output_escape_only_r3` runtime `now(Resolves("${S}"))` is a phase-1 mis-derivation under R4 in every option (the value exists only via the deleted `$` branch) — re-derived with the ruling.
- Resume point: Agent C resumed on ALL decision-independent 4a work now; `_normalize_source`, the three output rows, and the Issue-span choice for them wait for the ruling (the plan span is used everywhere else — both options (1) and (2) keep it). If the ruling has not arrived when the rest is done, C hands back with only those rows open.

## [2026-09-30 14:10] Agent C (Opus) — phase 4a: AST, parse/parse_path/lookup, facade, runtime consumers (resumed per the 10:45 orchestrator ruling; the prose-wrap seam is still open)
- Did: rewrote `core/templates.py` over a typed parse:
  - Frozen, slotted AST: `Text`, `Field`, `Index`, `DynamicIndex`, `Reference`, `Literal`, `Expression`, `Issue`, `Template`.
  - `parse` (`lru_cache(4096)`), `parse_path`, `lookup`, and one `_walk` shared by templates and raw paths.
  - Every `TemplateResolver` method now sits over them, and the public patterns are rebuilt from the tokenizer's grammar.
  - The literal grammar is tightened to JSON escapes. `has_references` is new, and `CONTAINER_TYPES` / `LIST_TYPES` are added.
  - The core no longer reaches into the facade: the walk, stringify and raw-lexer helpers are module-level, and the facade delegates.
  - Migrated every runtime consumer in the plan's 4a table, plus two whose meaning the facade shifted (below).
  - Issue span per the ruling: "to the first `}`", everywhere. R4 is in 4a per the ruling.
- Changed (src):
  - `core/templates.py`.
  - `engine/template_resolution.py`: `is_simple` via `parse`; injection over `parse(t).expressions`; type sets from `core.templates`.
  - `engine/template_errors.py`: operands classified from the parse, inner references first; `lookup` for found-ness; "absent" from node status; field correction over segments; the type-error var is the first Expression.
  - `engine/engine.py`: `_diagnose_carry_ref` over the parse only; `_gate_pausable` untouched, and the hunks are at `:35` and `:159-171` only.
  - `engine/loop_control.py`: `evaluate_loop_condition` goes through `resolve`.
  - `engine/batch_executor.py`: R10.
  - `output_resolver.py`: R4 (`$` branch deleted); `_is_all_absent_coalesce` over the parse. The rest of `_normalize_source` waits for the ruling.
  - `execution/plan.py`: R11.
  - Cost analysis (`row_builder`, `token_estimation` ×2, `sub_workflow_walker`): `resolve()` channels. The lower bound strips unresolved expressions by raw text.
  - `core/diagnostic_render.py::_extract_field_path` over `Reference.first_field()`.
  - `core/user_errors.py`: an Issue-only output failure names its source.
  - `core/workflow/validator.py::_params_reference_alias` → `parse().references`.
  - `template_validation/type_checker.py::infer_template_type`: a dynamic index types like a static one.
  - `template_validation/batch_item_validation.py`: Pass 8 collects `parse().references`.
  - `core/CLAUDE.md`, `runtime/CLAUDE.md`, `template_validation/CLAUDE.md`: regex table rows for the deleted patterns replaced; the `extract_variables` value-view note rewritten.
- Changed (tests):
  - NEW `tests/test_core/test_templates.py` (295 items): AST shapes and spans; views; frozen AST, tuples and cache identity; fresh `Literal.value`; bounded cache; never-raises over 236 strings with uncached-scan agreement; the eight `TestSplitTemplatePath` expectations re-homed as `parse_path` rows plus 6 out-of-grammar rows; the dynamic-index walk (int / range / bool / None / str / float); non-int warning plus `??`; `first_field`; facade helpers.
  - Grammar corpus (sanctioned): the discovery column now reads `parse()`; the 17 `flips_in="4a"` rows are flipped; `test_strict_matches_are_discoverable` is REPLACED by `test_parse_covers_every_open_and_reassembles_losslessly` (82 openings counted by escape-blanking, independent of the tokenizer); the literal "bad escapes today/after" pair is folded into the rejects test.
  - Parity corpus: 14 row sides flipped (`today` item and marker deleted); R10's today test deleted and its after unmarked; the new row `batch_item_field_inside_dynamic_index_pass8`.
  - Sanctioned: `test_nested_templates.py:54-59` pin flipped.
  - Re-derivations: see Deviations 5–8.
  - New consumer tests:
    - loop dynamic-index condition (until/while);
    - `TestDynamicIndexDiagnostics` ×5;
    - R11 per-item warning;
    - alias inside a dynamic index;
    - carry diagnosis over segments;
    - `infer_template_type` dynamic index;
    - `TestEscapedTemplateInPromptIsMeasured` ×4.
- Verified:
  - `make check` green.
  - `make test`: **10048 passed, 2 failed, 37 xfailed**, against the baseline 9740 passed / 70 xfailed.
    - Items 9810 → 10087 (+277) = `test_templates` +295, grammar −19, parity −13, token_estimation +4, error_messages +5, and +1 each in loop_control, plan_batch_sub_workflow, sub_workflow_validation, loop_config, type_checker.
    - xfailed −33 = 17 grammar + 1 literal + 14 parity + 1 R10.
    - The 2 failures are exactly the ruling rows (below).
  - `make test-e2e` 47 passed / 2 skipped (unchanged). Freeze harness 819: 818 plus the one new `test_type_checker` test; edits are sanctioned or listed below. `test_trace_integration.py` 21 passed and unmodified; no trace field.
  - Corpus: 418 passed / 2 failed (the ruling rows) / 37 xfailed. Every remaining xfail is strict, and no XPASS is left.
  - Examples `capture.py --check`: 29 examples, 0 differing.
  - Handoff greps:
    - `resolve_nested_index_templates|_BRACKET_INDEX_PATTERN|_INTERPOLATION_PATTERN|_DYNAMIC_INDEX_OPEN|_DYNAMIC_INDEX|_COALESCE_EXPR_PATTERN|_OPERAND_PATTERN` over `src/` and `tests/` → empty.
    - The plan grep in `runtime/engine/`, `output_resolver.py`, `prompt_cache_analysis/` → only `trace_loading.py:559`, `token_estimation.py:462`, `discrepancy/predict.py:374` (all IR/author text, §6 long tail) and a docstring `split(".")` in `prompt_cache_analysis/__init__.py:148`. None scans resolved text.
  - Differentials (executed against a byte copy of the phase-3 module):
    - Raw-path walk: 210 combos, 2 differ, both deviation 3.
    - Templates: 864 combos. Differences are delta 3 (104), delta 4 (16), the literal grammar (32), the Issue-span class `${prefix ${a}}` / `${${a}}` (32, the ruling seam) and Issue-beside-expression now in `issues` (5; `${a.b.0} ${b}`, which the validator already rejects). Nothing else.
  - Mutation ledger, each a counted failure on top of the 2 ruling reds:
    - bool inner index;
    - shared `Literal.value`;
    - Issue span stops before the next OPEN (4 grammar rows);
    - unclosed escape consumes to the next `}`;
    - inner accepts `??`;
    - multi-index accepted;
    - negative index;
    - `issues` channel dropped (9 more);
    - `first_field` ignores the root index;
    - classify outer first;
    - R11 arm dropped;
    - alias via the value view;
    - token site rescans the resolved text;
    - row_builder rescans the resolved text;
    - type_checker lexical split;
    - loop via the raw reader (4 more);
    - injection ignores literals;
    - R10 off;
    - simple gate on the old grammar;
    - Pass 8 value view.
    - Equivalent mutant: dropping `(?<!\$)` in `_SCAN` turns nothing red. The escape alternative always wins at the earlier index and no token ends in `$`, the same class as phase 1's `_INTERPOLATION_PATTERN` finding. Kept as documentation.
  - Real surface (`uv run pflow …`, files in `scratchpads/task-170/phase4a/surface/`):
    - `dyn-dict.pflow.md`: batch `${first.results[${__index__}].stdout}` (a JSON string) into `row: dict` → exit 0, output `dict:alice` / `dict:bob`. Delta 3: before, the rewritten text was not simple, so a str was delivered (corpus row `dyn_shape_json_string_element`). `--validate-only` → "Workflow is valid".
    - `dyn-oob.pflow.md`: `${make.result[${idx}].x}` with idx=5 → exit 1, "Unresolved variables in parameter 'inputs': ${make.result[${idx}].x}", naming the author's reference.
    - `escapes.pflow.md`: `$${a[${i}]} | $${FOO:-${bar}} | ${bar}` → exit 0, output `${a[${i}]} | ${FOO:-${bar}} | B` (delta 4). It needed a declared `i`, because the validator's escape blindness flips in 4b.
  - Python 3.10: checked `match` over slotted frozen dataclasses, `X | Y` aliases and `lru_cache.cache_info()` under `uv run --python 3.10`.
  - Assumed: Windows is not exercised; no shell-dependent test was added, except that `dyn-dict` is a manual surface run only.
- **Open, waiting for the ruling (per the 10:45 instruction):** `output_prose_wrap_recorded_drift` and `output_escape_only_r3` runtime `today` items fail, and only because of the ruling-dependent span. Today they observe `OutputResolutionError: "Unresolved template in output 'o': prefix ${p.out_str}"` and `…: $${p.out_str}`. What each option changes:
  - (1) `_normalize_source` = `source if source.startswith("${") or TemplateResolver.has_templates(source) else "${" + source + "}"`, one line (executed):
    - prose-wrap runtime → `now(Resolves("prefix S"))`: the drift is fixed, so the spec's freeze and Out-of-scope lines need an edit;
    - escape_only_r3 runtime → `now(Resolves("${p.out_str}"))`;
    - `$p.out_str` / `p.out_str.0` stay loud (R4 and the Issue rows hold).
    - Design note: use `has_templates`, not `has_references`. With `has_references`, an escape-only source would be wrapped into an Issue.
  - (2) No code change (the current code IS option 2). Row edits: prose-wrap → `now(Raises("OutputResolutionError", "prefix ${p.out_str}"))`; escape_only_r3 → `now(Raises("OutputResolutionError", "$${p.out_str}"))`. Validator OK plus a runtime error stays until 4b adds a check.
  - (3) Unchanged from my 10:30 entry. It would reopen the four grammar/static rows this phase just flipped.
- Deviations/surprises (the signal):
  1. **The facade's `extract_variables` change reaches the validator in 4a, not 4b.** Three consequences:
     - (a) The delta-6 rows `dyn_shape_json_string_element` (validator) and `dyn_type_pass_code_annotation_delta6` XPASSed early. They are flipped, explained by the diff.
     - (b) `dyn_type_pass_mismatch_partner` went red. Its "expects int" was produced by typing the INNER `${idx}` (the wrong reason delta 6 removes). With the outer reference, `infer_template_type` returned None, because it split on every `.` and stripped only `[N]`. Fix: `split_template_path` plus `_strip_index` in `type_checker.py`, a file outside the 4a list. 4b/4d replace it with `parse_path` segments. Phase 5 must re-point it when `split_template_path` dies.
     - (c) **A real validator regression the corpus did not catch.** Pass 8 lost `${item.nope}` inside `${p.out_arr[${item.nope}]}`, which the phase-3 tree flags (executed on both trees). Fixed in `batch_item_validation._collect_templates_from_value` (dependency view) and pinned by the new row. Outside the 4a list as well. 4b's operand iterator subsumes it.
  2. **Two more facade meaning-shift consumers migrated beyond the table:**
     - `core/workflow/validator.py::_params_reference_alias`: under the value view, an alias read only inside a dynamic index is missed.
     - `diagnostic_render._extract_field_path`: the plan's formula `var[len(root):].lstrip(".")` would regress a static root index to `peer.[0].stdout`. Implemented over `Reference.first_field()`, a new AST method shared with `template_errors`' field correction, so the segment-to-text grammar has one home.
  3. **One walk changes one raw-path shape:** `x[0][1]` / `x.k[0][1]` over a JSON-array-string element now resolves (a strict widening; before, the parse happened only before a chain). The plan asked for "the same `_walk`"; keeping the legacy rule would need a second index rule. Pinned in `test_raw_path_reader_chains_indices_through_json_strings`.
  4. The plan's §0.1 traversability sets (`TRAVERSABLE_TYPES`, `TRUSTED_TRAVERSABLE_TYPES`) are NOT added yet: they have no 4a consumer and land with 4b/4d. `to_string` stays `_convert_to_string` (4d per §0.4). `TemplateResolver._get_dict_value` is deleted: nothing calls it, only a test docstring mentions it (`test_template_resolver.py:319`, and `test_template_feature_combinations.py:57` for `_try_parse_json_for_traversal`); both are stale docstrings in tests, left as-is.
  5. Test edits beyond §5, each re-derived:
     - `test_template_resolver.py::test_rewritten_dynamic_index_is_unresolved` → `test_dynamic_index_miss_is_the_authors_reference` (phase 2's interim; delta 3).
     - `test_template_error_messages.py::test_rewritten_…_path_error` → the author's reference.
     - `test_output_resolver.py::test_resolves_dollar_format` → `test_dollar_format_is_not_a_source` (R4, freeze-harness file; §5 lists no R4 test edit).
     - `test_cache_analysis_token_estimation.py::test_tokenize_prompt_region_returns_none_when_resolved_value_contains_literal_template_bytes` → `…measures_resolved_values_containing_template_text`. It pinned exactly the resolve-then-rescan the plan retires at these sites.
  6. **Monkeypatch sites:**
     - The two `token_estimation` tests are re-targeted from `TemplateResolver.resolve_template` to `token_estimation.resolve`. That is the new call path; both still guard the except-clause breadth, and without the re-target they fail loudly, not silently.
     - `test_cache_analysis_analyze.py:5930` still intercepts through `sub_workflow_walker.py:580` (the batch-items `resolve_template`, not migrated), so its assertion is unchanged and meaningful.
  7. Corpus re-derivations beyond "delete today + marker":
     - `dyn_permissive_outer_field_missing` `end_to_end` → `Resolves("${p.out_arr[${idx}].nope}")`.
     - `dyn_batch_item_inner_renderer`: the override is dropped, as the phase-2 note said.
     - `dyn_loop_while_r1` gains `end_to_end=Resolves(2)`: validator-clean now, so it runs end to end, where the observation is the iteration count.
     - `output_dollar_prefix_r4` runtime flipped early (R4 is in 4a by ruling).
     - `output_dollar_prefix_typo_partner` stays `now` because the divergence was fixed, not the row: the Issue-only summary names the source.
  8. R11 wording: "Batch item N: 'inputs:' left ${…} unresolved (strict mode). Runtime will reject this item." The planner has no mode in scope, hence the qualifier.
  9. Observations, not acted on (long tail per §6):
     - `discrepancy/predict._node_templates_touch` and `trace_loading` now see a dynamic index's outer root instead of its inner one via the rebuilt `TEMPLATE_PATTERN` (both partial views before and after).
     - `prompt_cache._resolve_static_prefix_for_cache` now resolves `${a[${i}].x}` whole, where before it spliced `${i}` into `${a[0].x}` garbage. 4c owns the site.
     - `sub_workflow_walker:533`'s escape behavior has no direct test (only the two sibling sites do); it follows the same `resolution.unresolved` rule.
  10. A single-string param with an Issue next to a resolved Expression (`${a.b.0} ${b}`) now fails strict at runtime, where the phase-2 interim was silent. The validator already rejects it (malformed count), so it is reachable only through programmatic IR. The same applies to a prewarm `system` of that shape (now dropped, Absent).
- Self-checks:
  - Fully happy? Almost:
    - The Pass 8 regression (deviation 1c) was found only by this self-check's "which validator consumers read `extract_variables` as a dependency view?" audit, executed on both trees. It is fixed and pinned now, and it is the kind of thing the mid-task `review-impact-completeness` lens should re-sweep: any other consumer of `extract_variables` or the rebuilt `TEMPLATE_PATTERN` that means "dependencies".
    - The type_checker fix is a stop-gap (lexical `split("[",1)`), honest but not the 4b/4d shape.
    - The two open rows are not mine to close.
  - test-reflect (directed):
    - DELETED `test_spans_slice_the_source`: it duplicates `test_parse_shape`'s exact spans and the grammar-file coverage invariant.
    - DEEPENED the diagnostic absence checks with presence partners: `did_you_mean` exact beside the `'i}]'` absence; the exact coalesce fix line beside the torn-text absence.
    - DEEPENED `test_field_correction_after_a_root_index…`: its first draft had a nonsense fixture, replaced with a dict root plus a `[${i}]` miss.
    - KEPT the rest: each was killed by a counted mutation above, and `test_parse_and_resolve_never_raise` also asserts the uncached scans agree with the cached parse.
    - Found a MISSING row (Pass 8 inner ref) and added it with a mutation check.
- Next: the orchestrator relays the (1)/(2) ruling. On (1) I apply the one-line normalizer and the two row flips; on (2), the two row edits only. Then the mid-task review (`review-silent-failures`, `review-impact-completeness`, `review-test-fidelity`) on this diff. Not committed.

## [2026-09-30 11:30] task-orchestrator — 4a verified (pending ruling); WIP checkpoint commit
- Verified (orchestrator re-run): `make test` 10048 passed / 2 failed / 37 xfailed — the 2 failures are exactly `output_prose_wrap_recorded_drift-today` and `output_escape_only_r3-today` (the escalated seam; code currently implements option 2); `make check` green.
- Deviations 1–10 read; all within the phase's intent and explained. Accepted: 1b/1c edits outside the 4a file list (`type_checker.py` stop-gap — phase 5 re-points it when `split_template_path` dies; `batch_item_validation.py` Pass-8 dependency view — 4b's iterator subsumes it); 2 (two more meaning-shift consumers); 3 (raw-path `x[0][1]` over JSON-string element widens — one walk, pinned); 4 (traversability sets deferred to 4b/4d — no 4a consumer); 5–8 (re-derivations); 10 (Issue beside a resolved expression now strict-loud; validator already rejects it).
- Committed as a WIP checkpoint (disaster recovery for a ~465k-token phase) with the two ruling rows red; the ruling commit follows. Not a phase-complete commit.
- Next: on the ruling, resume Agent C for the seam; then the 4a mid-task review with Agent C as gate-runner (its window is ~465k — healthy enough for one review round on its own diff; **4b rotates to a fresh C2** per plan §2 4b).

## [2026-09-30 15:20] Agent C (Opus) — phase-4a mid-task review (gate-runner)
- Did: ran deep-review in code mode on `89ab9bb2..bbaca071` through the pflow fan-out (provider codex, cross-model against me as the Claude builder), with exactly `review-silent-failures`, `review-impact-completeness` and `review-test-fidelity`.
  - Each lens got the orchestrator's focus plus the deferred list: the two ruling rows, 4b, 4c, the §6 tail and `workflow_executor.py:771`.
  - Target text: `scratchpads/task-170/phase4a/review/target.txt`. Report: `…/review/report.md`, read in full.
  - Coverage: all 3 lenses reported on the exact range; no failed lens. All three are static reads (no tests run by the lenses).
  - I verified every Critical and Warning by execution before changing code (probe outputs are in this session; the repros are the new tests).
- Findings, each dispositioned:
  1. **Critical (silent + impact, convergent): an all-absent `??` output skip hid a node that ran or FAILED.** CONFIRMED by execution: `${p.items[${pick.i}] ?? q.value}` with `p` run, and `${primary.stdout[${pick.result}] ?? fallback.stdout}` with `primary` FAILED, both skipped silently.
     - Cause: `_is_all_absent_coalesce` judged on the diagnostic's classification, which reports an unresolved inner ref in place of its outer operand.
     - FIXED, simpler than before: `output_resolver._is_all_absent_coalesce` now requires every operand to be a Reference whose OUTER root has `NodeStatus.ABSENT`. It no longer calls `classify_unresolved_references`, and its unused `resolution` parameter is dropped. For non-dynamic operands this is identical, since classify's "absent" ⟺ node status ABSENT.
     - Tests: `TestAllAbsentCoalesceWithDynamicIndex` ×3 in `test_output_resolver.py`: ran → raises; failed → raises; partner all-outer-absent → skipped.
  2. **Warning (impact, silent cross-handoff): `error_context.extract_node_ids_from_template` read the value view**, so a failed dynamic-index selector's stderr was dropped from enrichment. CONFIRMED (`{'rows'}`). FIXED: `{ref.root for ref in parse(template).references}`, the dependency view. The plan table's "operands" label was wrong for this consumer. Test: `test_dynamic_index_inner_node_is_upstream`.
  3. **Warning (silent + impact, convergent): a RESOLVED reserved inner (`__index__`, `__iteration__`) was reported as an absent node**, because node status excludes `__*__` keys. CONFIRMED (`[('__index__', 'absent')]`). FIXED: `classify_unresolved_references` classifies an inner ref only when `lookup` misses it, so FAILED precedence holds (a failed root is gone from the live namespace). Test: `test_resolved_reserved_inner_is_not_a_cause[__index__|__iteration__]`.
  4. **Critical (silent): `${x}\n` stopped being simple.** CONFIRMED against the phase-3 module: old `[1, 2]` / simple; new `'[1, 2]\n'` / complex. The old `^…$` anchor matched before one final newline, which matters for a YAML block scalar `v: |`. That is behavior-freeze territory and outside the deltas. FIXED: `Template.is_simple` tolerates one trailing `Text("\n")`, dropped by resolution exactly as before. `\n\n` stays complex, as before (executed). Test: `test_one_trailing_newline_keeps_a_template_simple`.
  5. **"Critical" (test-fidelity; really a production bug the test missed): the lower-bound tokenizer `str.replace`d unresolved `${…}` from the RESOLVED value**, cutting equal bytes that came from an escape. CONFIRMED by the reviewer's arithmetic plus a mutation run.
     - FIXED: `token_estimation._tokenize_prompt_region_lower_bound_with_resolver` cuts the unresolved Expressions out of the AUTHOR text by span, then resolves the rest (no text search at all).
     - Test deepened: the collision `Use $${missing} for ${text} and ${missing}`, with an explicit check that the collision changes the count.
  6. **"Critical" (test-fidelity): the root-index correction test enshrined an impossible suggestion (`cfg[${i}].name` on a dict root).** CONFIRMED, and the bug is in production, not just the test: after a root index, the root's keys are the wrong container.
     - FIXED: `_suggest_field_correction` suggests only for a field directly on the root. That also drops its use of `first_field()`, which stays in `diagnostic_render._extract_field_path`.
     - Test replaced: `test_no_field_correction_after_a_root_index` (plus a direct-typo partner that is still corrected).
  - Suggestions: none standalone. Verified clean per lenses: tokenizer escape / Text-Issue boundary; strict/permissive channels; injection vs required siblings; loop / carry / batch / cache / prewarm / dry-run failure checks; the full `extract_variables` / `TEMPLATE_PATTERN` / `SIMPLE_TEMPLATE_PATTERN` consumer sweep (Pass 8 and alias fixes confirmed dependency-view; type consumers correctly value-view); the span invariant is non-tautological; the grammar and parity flips match the sanctioned semantics; both monkeypatch re-targets hit the called binding.
  - Nothing at importance ≥3. Nothing contradicts the ledger or an ADR. Finding 4 RESTORES frozen behavior.
- Changed:
  - src: `runtime/output_resolver.py`, `runtime/engine/error_context.py`, `runtime/engine/template_errors.py`, `core/templates.py` (`is_simple`), `core/prompt_cache_analysis/token_estimation.py`.
  - tests: `test_output_resolver.py` (+3), `test_batch_node_stderr_context.py` (+1), `test_template_error_messages.py` (+2, 1 replaced), `test_cache_analysis_token_estimation.py` (1 deepened), `test_templates.py` (+1).
- Verified:
  - `make check` green.
  - `make test` 10055 passed / 2 failed / 37 xfailed: +7 new tests over the 4a entry; the 2 failures are still exactly the ruling rows.
  - `make test-e2e` 47 passed / 2 skipped. Freeze harness 822 (+3, `test_output_resolver.py`). Corpus plus `test_templates`: 714 passed / 2 ruling rows / 37 strict xfail, no XPASS.
  - `capture.py --check`: 29 examples, 0 differing.
  - Revert-mutation per fix, each a counted failure in its new test: R-F1 2, R-F2 1, R-F3 2, R-F4 1, R-F5 1, R-F6 1. For R-F5 the stand-in was an author-text replace, which fails the same collision test.
- Deviations/surprises:
  - Two lens "Criticals" filed under test-fidelity (5, 6) were production defects, not only weak tests. Both were fixed at the source, and each test was rewritten to discriminate.
  - Finding 4 is a freeze behavior that no corpus row pinned. It is now pinned in `test_templates.py`. A corpus row may be worth adding in 4b, when validator-side simple-ness also reads the parse.
  - Not committed.
- Self-checks: fully happy with the six fixes. Each simplified or kept the code shape (1 and 6 removed code paths), and each is mutation-proven. test-reflect on the review tests: every one fails on its revert; none is shallow.
- Next: the orchestrator reviews and commits. The prose-wrap ruling (1)/(2) is still pending; apply it on arrival (one line plus two row flips, or two row edits).

## [2026-09-30 15:40] task-orchestrator — 4a review closed; main-orchestrator notes; next steps
- Verified: Agent C's review dispositions (6 findings, all fixed with failing-first tests; report `scratchpads/task-170/phase4a/review/report.md`, three lenses on codex, full scope); `make test` 10055 passed / 2 failed (the escalated rows only) / 37 xfailed; `make check` green. Committed the fixes.
- Main-orchestrator notes (2026-09-30):
  - The prose-wrap escalation changes the Sanctioned-delta set → with the user. Pending; code implements option (2) meanwhile.
  - `origin/main` → `abcaa50f`: #606 (`core/llm_providers.py`), #654 (`core/litellm_runtime.py`), #652 (`core/stdout_reservation.py`, `run.py`, `_probe_impl.py`, `mcp_server/server.py`), **#643 (PR #664)**: `core/validation_utils.validate_with_placeholder_inputs(workflow_ir, *, workflow_file)` is now the single validation-params construction (`runner.validate`, `save_service`, `analyze-cache`). Consequences for 4b: the corpus docstring's #643 asymmetry note is stale (fix it); `core/workflow/validator.py:1606-1614` child recursion builds both channels by hand — switch to the helper only if 4b already edits that region, else leave and say so; PR #664 "Sibling gaps" executed `source: ${sub.reslt}` (typo'd child output) → `--validate-only` OK, run fails `Unresolved variables in output 'out'` — loud, so an under-check, not a converse violation. 4b: if the validator already checks child output names for `${sub.x}` in params, the output-source gap is a surface-parity miss → fix; else a named corpus row (validator Ok / runtime Unresolved) per spec Parity "under-checks are visible".
- Rotation: Agent C at ~507k → **4b goes to a fresh C2** (plan §2 4b). The prose-wrap seam (one-line `_normalize_source` for (1), or two row edits for (2)) is handed to C2 when the ruling lands; C2 also owns 4b's output-source validation, which the ruling may shape (under (2) a validator ERROR for prose sources is a candidate; under (1) the raw-source check stays OK).
- Next: merge `origin/main`, gate the merge, launch C2 on 4b.

## [2026-09-30 17:30] Agent C2 (Opus) — phase 4b: validator consumers on the AST (enumerator, one Issue pass, operand classifier; deltas 2 and 6, #262, R3/R6/R9, Pass-8 policy)
- Did: built §0.3.
  - NEW `core/workflow/template_surfaces.py`: `iter_template_surfaces` / `iter_node_surfaces`, one `TemplateSurface(kind, node_id, key, value)` per location: params, `batch.items`, loop fields, carry, output `source:`, cache var, cache prose. `TemplateSurface.templates()` yields `(location, parse)` per string. `path(location)` gives the diagnostic path.
  - One Issue pass (`_validate_malformed_templates`) runs over it on every surface.
  - NEW `template_validation/operands.py`: `OperandPolicy`, `classify_operand`, `iter_template_operands` (dynamic-index inner refs included). It feeds Pass 5 (`FIELD_CHECK`), unused inputs (all) and Pass 8 (`FIELD_CHECK`, own node).
  - `data_flow` checks `parse().references` on the node's param/batch/loop surfaces, so `batch.items` is now walked. `_PFLOW_VAR_RE` is deleted.
  - Pass 5 and `infer_template_type` walk `parse_path` segments through one index rule, `utils.descend_index` (R9).
  - Output sources are parsed raw: R3, root checks inner refs included, and they count toward unused inputs.
  - R6 at all 7 deferral sites.
  - The 4a stop-gaps are replaced: `type_checker._strip_index`/`split_template_path` → segments; Pass 8's `_collect_templates_from_value` → the iterator.
- Changed:
  - src: `core/workflow/{template_surfaces.py (new), data_flow.py, validator.py, sub_workflow_resolver.py, graph/build.py (docstring pointer), CLAUDE.md}`, `core/templates.py` (+`TRAVERSABLE_TYPES`/`TRUSTED_TRAVERSABLE_TYPES`, facade comment), `runtime/template_validation/{operands.py (new), validator.py, path_validation.py, batch_item_validation.py, type_checker.py, type_validation.py, utils.py, CLAUDE.md}`.
  - Deleted now, not in phase 5 (no callers remained): `_PERM_VAR`, `_PERM_OPERAND`, `_PERMISSIVE_PATTERN`, `_TEMPLATE_OPEN`, `_malformed_literal_operand_hint`, `_node_template_value_sources`, `_operands_in_string`, `_field_checkable_templates`, `_QUOTED_TEMPLATE_PATTERN`, `_check_param_value`, `_PFLOW_VAR_RE` (data_flow), `_strip_index`, `_validate_array_access`.
  - src LOC: tracked files +613/−1003, plus 161 new-file lines ≈ −229 net.
  - tests:
    - The sanctioned `test_validator.py:298-311`: asserts the malformed message and path, plus a positive-control test.
    - Additions only elsewhere: `test_malformed.py::TestIssuePassCoversEverySurface` ×4, `test_batch_item_validation.py` ×1 (alias shared by two nodes), `test_array_notation.py` ×1 (continue-mode gate on `[${__index__}]`), `test_file_resolver_integration.py` ×1 (batch-item source file), `test_workflow_validator_llm_output_schema.py` ×1 (R6 escape-only schema), `test_workflow_data_flow.py::TestCacheVarRoots` ×3.
    - Corpus:
      - 22 rows flipped (`today` item and marker deleted);
      - `TestDeferralSitesEscapeOnly` today test deleted and its after unmarked;
      - `output_only_input_use_flagged_unused` → `now(Ok())`, plus partner `output_only_input_use_partner`;
      - `cache_prose_empty_braces_r2` validator flipped early (see Deviations 3);
      - `test_643_child_output_typo_in_output_source_is_an_under_check` added;
      - the stale #643 docstring note rewritten;
      - the now-unused `_xfail` helper deleted.
- Verified:
  - Baseline (my capture) was 10069 passed / 2 failed / 37 xfailed. `make test` is now **10084 passed / 2 failed / 13 xfailed**; the 2 failures are exactly `output_prose_wrap_recorded_drift-today` / `output_escape_only_r3-today`, untouched.
    - Delta: 24 `today` items deleted (22 rows + cache prose + R6); their 24 `after` items now pass unmarked; +15 new tests.
  - `make check` green. `make test-e2e` 51 passed / 2 skipped (unchanged). Freeze harness 829 = 822 + 7 additions; the only edit to an existing test is the sanctioned one.
  - Corpus: the 13 remaining xfails are all `4c` and strict; no XPASS. Every 4b XPASS was explained by this diff and flipped.
  - Handoff grep → only `cache_overlap.py:_PFLOW_VAR_RE` and `utils.split_template_path` + its `__init__` export (both phase 5).
  - `capture.py --check`: 29 examples, 0 differing.
  - Real surface (`scratchpads/task-170/phase4b/surface/`; base = `git archive HEAD` copy run via `PYTHONPATH`):
    - `silent.pflow.md` (`echo "got ${c.stdout.0}"`): base "✓ Workflow is valid", and the run hands the literal to sh ("bad substitution"). 4b: "Malformed template syntax: found 1 '${' but only 0 valid template(s)", `nodes[id=use].params.command`.
    - `root-typo-dyn.pflow.md` (`${lsit[${__index__}].x ?? "default"}`): base valid, and the run returns `"default"` for every item. 4b: "Node 'each' references non-existent node 'lsit' in parameter 'inputs.v'".
    - `list-input-262.pflow.md` (`${items[0]}`): base "Template variable ${items[0]} has no valid source". 4b valid; the run outputs `first`.
    - `delta6-type.pflow.md` (`row: ${make.result[${__index__}]}` into `row: dict`): valid on both trees (it flipped early in 4a); the 4b run gives results 1, 2.
    - `out-escape.pflow.md` (`source: $${n.stdout}`): "Output 'o' is invalid: output source has no template expression ('$${n.stdout}' resolves to literal text)."
    - `out-prose.pflow.md` (`prefix ${n.stdout}`): still "✓ Workflow is valid".
    - #643(c) probe: a `${sub.reslt}` param → "Node 'sub' (type: workflow) does not output 'reslt'". As an output source → "✓ Workflow is valid".
  - Mutation ledger (`scratchpads/task-170/phase4b/mutate.py`; each applied, the targeted tests run, the file restored from a byte copy; kill = a counted failure). 20 mutations, all killed:
    - drop `batch.items` surface (53);
    - drop inner refs from operands (3);
    - Pass 8 without the node filter (2);
    - classifier always FIELD_CHECK (8);
    - `list` not indexable (6);
    - list structure ignored (2);
    - `initial_params` keyed by raw text (4);
    - outputs out of unused accounting (3);
    - continue gate static index only (2);
    - provenance skips batch items (1);
    - R6 schema not unescaped (1);
    - data_flow skips `batch.items` (1);
    - no cache-prose Expression check (1);
    - opens = segment count (1);
    - element type always `any` (1);
    - no loop-operator guidance (1);
    - R3 dropped (1);
    - cache var roots outer-only (2);
    - prose check fires on escapes (1);
    - Issues counted on escape-only text (18).
    - The first ledger run had a baseline-red filter that also swallowed the `output_escape_only_r3` VALIDATOR item, which made R3 look unkilled. Fixed to exact ids and re-run.
  - Assumed: Windows is not exercised (no new shell-dependent test).
- Deviations/surprises (the signal):
  1. **#643(c): not fixed; pinned as a named under-check, and needs a ruling.** Executed: the validator DOES check child output names for `${sub.x}` in params (Pass 5), while output sources are root-checked only, for EVERY node. The `now(Ok())` row `output_missing_field` (`${p.nope}`) and plan §0.3 ("output-source … validation root-check References only") pin that. Field-checking output sources would flip a `now` row and widen 4b beyond the plan, so I added `TestHistoricalFixtures::test_643_child_output_typo_in_output_source_is_an_under_check`: validator Ok, run fails naming `${s.gto}`, and a partner asserts the param form errors. **Options:**
     - (a) Keep the pin; the fix is a lane issue "field-check output sources through Pass 5".
     - (b) Do it now: Pass 5 over `output_source` surfaces (`FIELD_CHECK`), flipping `output_missing_field` and the pin.
     - I recommend (a) for this task (scope and a spec-level change of the output-source contract); importance 3, reversible.
  2. **The shared index rule now types a trailing index, so a new ERROR appears (importance 2–3, needs your call).** `descend_index` gives the element type (`list[X]` → X; batch `results` → its `items` type), where the old inference returned `None` for `${b.results[0]}`.
     - Executed `trailing-index.pflow.md`, `echo ${b.results[0]}` in shell. Base: "✓ Workflow is valid", and the run prints the JSON with its quotes eaten (`{stdout: x, stdout_is_binary: false, …}`). 4b: Pass 7's "cannot use ${b.results[0]} (type: dict) in command parameter".
     - This is the existing dict-in-shell policy, correctly applied now that the element is known. The corpus partner `dyn_type_pass_mismatch_partner` needs element typing (`list[dict]` → dict). No other test or example changed.
     - Reversal: one line (element type `any` unless `list[X]`).
  3. **Early flip, wording re-derived:** `cache_prose_empty_braces_r2` validator side (row said 4c). §0.3 puts cache prose in the 4b Issue pass, so its `today` Ok went red. Per the Dev-7 ruling (an Issue in prose gets the standard malformed message) its `after` became `Error(MALFORMED)`; it XPASSed, explained, and flipped. **For 4c:** `cache_prose_unclosed_r2`'s `after` still says `CACHE_PROSE_ISSUE`, which is wrong under the same ruling. Editing it to MALFORMED will XPASS at once through the cache-var Issue path. I left it, because my diff does not force it.
  4. **R5 not landed (per launch: 4c).** The plan's 4b table assumes a single-operand var ("after R5"). To keep the 4c rows' `today` green, `data_flow._cache_var_roots` checks every Reference root (inner included) only for a single-operand var. A `??` chain or an Issue keeps the whole-var lexical root, which is what `_resolve_chunk_value` gates on. 4c deletes that branch.
  5. **Issue message count:** "found N '${'" uses N = unescaped `${` openings, not the plan's "expressions+issues": `${first ${second` is one Issue with two openings, and `test_malformed.py:329` asserts 2. With that, all five count phrases stay green with zero edits, as the plan intends.
  6. **Loop condition Issue:** `while: ${c.exit_code > 0}` is an Issue, so the Issue pass would return early before the loop pass's targeted operator message (`test_loop_validation.py::test_operator_while_rejected` went red). The Issue pass, the one home of Issue policy, now emits `_make_loop_operator_diagnostic` for a `loop.while`/`loop.until` Issue containing an operator character.
  7. **Shape vs plan §0.3:**
     - `TemplateSurface` carries `key` + `templates()` + `path(location)` instead of a `path` field, because data_flow needs the short name ("in parameter 'inputs.v'") and the Issue pass needs the full path.
     - `iter_node_surfaces` is public, because data_flow walks per node.
     - The classifier and iterator live in a new `operands.py` (Pass 8 in `batch_item_validation.py` cannot import `validator.py`: circular). They yield a `TemplateOperand(node_id, ref, policy)` dataclass with no `path` (no consumer).
     - `validate_batch_item_fields` gains an `operands` argument; the orchestrator computes them once.
  8. **R6 in `sub_workflow_resolver`:** the plan puts the unescape inside the shared resolver, which the executor and dry-run also call with RESOLVED values. `has_references` is safe there, but `resolve(v, {})` parses a resolved value when it contains `$${`, which bends "parse() runs on author text only" and would double-unescape a runtime path containing a literal `$${`. Unreachable in practice; the alternative (unescape at the validator call sites) cannot work, because the resolver would re-read the unescaped `${x}` as a reference.
  9. **Smaller behavior notes:**
     - `_find_template_source_file` matches parsed references instead of a `${template}` substring (coalesce operands now found too).
     - data_flow names batch items "in parameter 'batch.items'", with path `nodes[id=X].params.batch.items`, which mirrors the existing `loop.while` quirk.
     - Pass 8 nested diagnostics check deeper fields only when the ref has more than one Field (today's `len(parts) > 1`).
     - `_carry_value_unknown_output` and the carry self-ref check read parsed operands (same outcomes).
     - The carry-prompt usage check now counts a carry key read inside a dynamic index (`${x[${state}]}`) as referenced (delta 6 spirit; before it warned).
  10. **#643(b):** `core/workflow/validator.py`'s child-recursion region (`_validate_one_child_call` dummy params) is untouched by 4b, so it is left on its hand-built params, as instructed.
  11. **Stale text left for phase 5:**
      - `.claude/agents/review-validation-consistency.md:158/:219` still describe data_flow's `_PFLOW_VAR_RE` positive match. **The 4b review lens reads this file**, so the review target should say data_flow now checks `parse().references` over `iter_node_surfaces`, and bash `${VAR:-x}` is an Issue reported by the Issue pass.
      - Test docstrings in freeze-harness files name deleted helpers (`test_workflow_data_flow.py:328/:839` `_check_param_value`, `test_type_checker.py:361` `_validate_array_access`), as does the corpus mutation string on `batch_items_coalesce_root_typo`. Left under the zero-edit rule.
- Self-checks:
  - Fully happy? Not fully: deviations 1 and 2 need your ruling, and 8 is a known wrinkle. Raised and fixed during the phase:
    - the loop-operator regression (6);
    - a missing test for cache-var inner roots, found by the ledger (M18 survived) and added;
    - my own ledger filter bug (R3 looked unkilled).
    - Type passes 6/7/9 still walk params themselves (plan §6, simplicity-lens follow-up).
  - test-reflect (directed):
    - Every added test has a counted kill.
    - The absence test `test_well_formed_surfaces_are_clean` was kept only after M19 proved it the sole catcher. It is paired with the presence test `test_every_surface_reports_at_its_path` through the same helper.
    - Added `TestCacheVarRoots` after M18 survived.
    - Nothing deleted: no added test was shallow, and each asserts exact messages or paths, not truthiness.
- Next: the mid-task review (`review-validation-consistency`, `review-impact-completeness`) on this diff; rulings on 1 and 2 (and the pending prose-wrap ruling, still one line or two row edits). Not committed.

## [2026-09-30 19:30] task-orchestrator — 4b verified; rulings on C2's deviations; WIP commit
- Verified (orchestrator re-run): `make test` 10084 passed / 2 failed (the escalated prose-wrap rows only) / 13 xfailed (all 4c); `make check` green.
- Rulings:
  - Dev 1 (#643(c) output sources root-checked only, all nodes) → **(a), importance 2**: keep the named under-check pin (`test_643_child_output_typo_in_output_source_is_an_under_check`) — spec Parity requires deliberate under-checks be visible, and a named row satisfies it; field-checking output sources changes the output-source validation contract beyond the plan (§0.3) → a lane-B follow-up issue in the completion handback.
  - Dev 2 (trailing static index now typed → `echo ${b.results[0]}` in shell hits the existing dict-in-shell policy) → **accepted provisionally, importance 2**: consistent application of an existing policy once R9's shared index rule knows the element type; the run it blocks prints quote-mangled JSON. User-visible (a workflow that validates today stops validating) → surfaced to the main orchestrator for overrule; reversal is one line (element type `any` unless `list[X]`).
  - Dev 3 → 4c edits `cache_prose_unclosed_r2`'s `after` to the standard malformed message (Dev-7 ruling); expect an explained XPASS.
  - Dev 4 → 4c deletes the `??`/Issue whole-var-root branch in `data_flow._cache_var_roots` with R5 (pending ruling).
  - Dev 8 (`sub_workflow_resolver` `resolve(v, {})` may see resolved values containing `$${`) → accepted as a known wrinkle; named for the review lenses.
  - Dev 11 → `.claude/agents/review-validation-consistency.md:158/:219` is corrected BEFORE the 4b review dispatch (the lens reads it); the test-docstring staleness waits for phase 5.
- Committed 4b as WIP (the two ruling rows red).
- Next: C2 runs the 4b mid-task review (`review-validation-consistency` + `review-impact-completeness`).

## [2026-09-30 20:10] Agent C2 (Opus) — phase-4b mid-task review (gate-runner)
- Did:
  - Fixed the lens instruction file first. `.claude/agents/review-validation-consistency.md` §4 data_flow bullet and known-gap 3 now say that data_flow checks `parse().references` over `iter_node_surfaces`, and that bash `${VAR:-x}` is an Issue reported by the one Issue pass (template validation only, not the compile path). Then ran `make sync-claude-assets` (1 file).
  - Ran deep-review in code mode on `d8443162..b3732f62` through the pflow fan-out: provider codex (cross-model against me, the Claude builder), lenses exactly `review-validation-consistency` + `review-impact-completeness`.
  - The target (`scratchpads/task-170/phase4b/review/target.txt`) carried: the scope, the per-lens focus, Dev 2 and Dev 8 as named items to check, and the deferred list (the prose-wrap rows, R5/4c, 4d, the phase-5 deletions, Passes 6/7/9 walks, #643(c) ruled (a), `workflow_executor.py:771`).
  - Waited in-turn and read the report in full (`…/review/report.md`).
  - Coverage: both lenses reported on the exact scope, no gaps. Both were read-only; neither ran probes.
- Findings, each dispositioned (verified by execution against a byte copy of `d8443162`; probe `…/review/probe.py`):
  1. **Critical (validation-consistency): a literal cache var `${42}` bypasses the root check → CONFIRMED, FIXED.**
     - Base: "Cache chunk '42' references '${42}' but '42' is not a declared input…". 4b: no error. The runtime gates on root `"42"` → ABSENT, so the chunk and its prose are silently dropped.
     - Cause: `_cache_var_roots` took the Reference path for any single-operand var, and a Literal has no references.
     - Fix: only a one-**Reference** var reads its references; anything else keeps the lexical whole-var root.
     - Test: `TestCacheVarRoots::test_literal_var_is_rejected`, red before the fix.
  2. **Warning (validation-consistency): the greedy `list[X]` match tears union types → CONFIRMED, FIXED.**
     - `descend_index({"type": "list[str]|list[int]"})` gave element type `str]|list[int`, which yields false Pass-6 errors.
     - Fix: the element type comes only from a single (non-union) `list[X]`; otherwise `dict` if a structure is declared, else `any`.
     - Test: `test_type_checker.py::test_index_into_a_union_of_lists_is_an_unknown_element` (plus the `list[str]` → `str` partner), red before the fix.
  3. **Warning (impact-completeness): type passes check every `??` operand, including ones after a literal, so `${0 ?? b.results[0]}` / `${b.results[0] ?? 0}` into `x: int` newly error → NOT CHANGED; disputed as a new defect class.**
     - Executed on base: `${0 ?? p.result}` into `x: int` already errors ("expects int but receives dict from ${p.result}"). Type passes 6/7/9 have always typed each operand.
     - 4b only makes an indexed operand typed like a non-indexed one. That is Dev 2 (accepted provisionally, surfaced upward), not a new rule.
     - `${b.results[0] ?? 0}` is a real mismatch whenever the element exists. "An operand after a literal is unreachable" is a pre-existing type-pass policy question.
     - Named as a follow-up with Passes 6/7/9 (§6); not fixed here.
  4. **Suggestion (impact-completeness): CLAUDE.md said carry values join unused-input accounting → CONFIRMED, FIXED (doc).** Carry values do not join, because a carry may reference only the loop node itself (`data_flow._validate_loop_carry_value_self_ref`). `template_validation/CLAUDE.md` is corrected.
  5. Dev 8 (named item): both lenses found no concrete failure beyond the known double-unescape. Dev 2: covered by finding 3; no other new over-rejection was reported.
  - Verified clean (both lenses):
    - Issue coverage on every enumerated surface (nested params, batch items, loop, carry, outputs, cache).
    - Dynamic-index inner references reach data_flow and unused-input accounting.
    - Passes 5/8 keep the `??` field fallback; Pass 8 is scoped to its node.
    - Plain and templated output sources count toward input use.
    - All changed signatures' callers are migrated.
    - Remaining path splitting in validation is diagnostic display or deferred.
- Changed:
  - src: `core/workflow/data_flow.py` (`_cache_var_roots`), `runtime/template_validation/utils.py` (`descend_index`), `runtime/template_validation/CLAUDE.md`, `.claude/agents/review-validation-consistency.md` (+ `.codex` twin).
  - tests: `test_workflow_data_flow.py` +1, `test_type_checker.py` +1 (additions only).
- Verified:
  - `make check` green (incl. asset sync).
  - `make test` 10086 passed / 2 failed / 13 xfailed: +2 tests; the 2 failures are still exactly the prose-wrap ruling rows.
  - Corpus 421 passed / 2 ruling rows / 13 strict 4c xfails, no XPASS.
  - `capture.py --check`: 29 examples, 0 differing.
  - Both new tests were red before the fix.
- Deviations/surprises:
  - Finding 3 widens Dev 2's footprint beyond shell (Pass 9 / code annotations over `??` operands). It adds evidence to the Dev-2 ruling already surfaced, not a new decision.
  - `rm -rf` is denied, so I reused my earlier byte copy `phase4b/base` (extracted at `d8443162`) for the before-tree.
  - Nothing at importance ≥3 was fixed; nothing contradicts the ledger or an ADR.
- Self-checks: fully happy with the two fixes. Both keep the code shape: one condition each, and one removes a false branch. test-reflect: both new tests are revert-red and assert exact values; nothing shallow was added.
- Next: the orchestrator commits the review fixes; the Dev-2 ruling (now including finding 3) and the prose-wrap ruling stay open. Not committed; 4c not started.

## [2026-09-30 20:30] task-orchestrator — 4b closed; 4d runs before 4c (ruling wait)
- Verified + committed C2's 4b review fixes `24fdd2a8` (`make test` 10086 passed / 2 failed (ruling rows) / 13 xfailed (4c); `make check` green). The indexed-`??` type Warning folds into the Dev-2 surfacing (same cause).
- Ruling (importance 1, reversible): **4d before 4c.** 4c needs the pending R5 ruling; 4d (graph scope + `scan.ts`, type-rule homes, display strippers) shares no code path with the cache chunker/renderer — the plan's 4c→4d order is not load-bearing between those two. 4c follows once R5 lands.
- Rotation: C2 at ~500k → **fresh Agent D (Opus/medium) for 4d**; 4c then goes to D resumed if healthy.
- Next: launch D on 4d.

## [2026-09-30 21:30] Agent D (Opus) — phase 4d: graph scope + `scan.ts` mirror, type-rule homes, display strippers
- Did:
  - `graph/scope.py::refs_with_path_in` reads `parse(value).references`: `(root, first Field, remaining Fields)`, with Index/DynamicIndex skipped. A dynamic index yields the outer ref, then its index source. `_BRACE_BLOCK_RE`, `_REF_IN_BLOCK_RE` and the `_VAR_NAME_PATTERN` reach are deleted.
  - `web/src/graph/scan.ts` is now a grammar mirror in the same step:
    - regex strings copied from `core/templates.py`;
    - one left-to-right scan: a balanced escape is literal, an OPEN is an Expression or an Issue through its first `}`, and literal operands are skipped;
    - `pathRefs` walks segments, dynamic-index sources included.
    - The old block regex, root-prefix regex, `VAR_NAME_RE`, `splitCoalesceOperands` and `isLiteralOperand` are deleted.
  - §0.4 type-rule homes:
    - `TYPE_COMPATIBILITY_MATRIX` and `is_type_compatible` moved verbatim into `core/templates.py`, which now imports `core.types.outer_base_type`. The header states template-flow vs `TypeSpec.accepts`, and the stale "Task 120 could add element checking here" sentence is dropped.
    - `_to_string` → public `to_string`; `_convert_to_string` alias kept.
    - `type_validation.py` imports the matrix from `core.templates`. Its `SHELL_BLOCKED_TYPES` local and the `["dict","list","object"]` list → `CONTAINER_TYPES`.
    - `type_checker.py` keeps inference only.
  - Display strippers:
    - `mermaid._first_sentence` renders `parse(text)` through a new `_debraced`: Expression → raw, Issue → de-braced raw, Text → text.
    - `_strip_template` → `extract_simple_template_var` with the loose fallback.
    - `warnings.py` ×2 `[2:-1]` → `extract_simple_template_var`.
  - Pointers:
    - Task 112 (`:11/:71/:136-137/:164/:174/:194`) and `research/output-field-validation.md:44/:114`. `:44` now points at `nodes/python/python_code.py`, where annotations are actually checked (`:42/:58`).
    - Task 120 (`:11/:13/:66`): → `TypeSpec.accepts`; the matrix is template-flow only.
    - Task 167 (`:134-135/:182`) → `Template.segments` spans.
    - `architecture/reference/template-variables.md:599/:608`: the matrix moved, the fictional `NoneType` row is gone, and a template-flow note is added.
    - `core/CLAUDE.md` types section; `template_validation/CLAUDE.md:17/:116`; `template_resolution.py:38` docstring; `web/src/graph/CLAUDE.md`, whose backend-owner line now says a grammar change in `core/templates.py` must edit `scan.ts` in the same step.
- Changed:
  - src: `core/templates.py`, `core/workflow/graph/scope.py`, `graph/renderers/mermaid.py`, `prompt_cache_analysis/stages/warnings.py`, `template_validation/{type_checker,type_validation}.py`, `engine/template_resolution.py` (docstring), CLAUDE.md ×3.
  - web: `src/graph/scan.ts`, `scan.test.ts`.
  - Lens: `.claude/agents/review-validation-consistency.md:181`, synced to `.codex`.
  - tests:
    - `test_graph_build.py` +2: the characterization pin `${data[0].field}` → `("data","field",())`, plus the dynamic-index / escape / Issue rows; the example's DATA_FLOW edge `process-batch.results` → `correlate-batch.command`, `output_path ("stdout",)`.
    - `test_type_checker.py:9`: the sanctioned import re-point.
    - `scan.test.ts` +9 rows under "consumedReadPaths — runtime parity (mirrors scope.py)".
  - Evidence: `implementation/4d-screenshots/{before-no-edge-into-correlate-batch,after-process-batch-stdout-edge}.png`.
  - `src/` + `web/src`: +273/−228 (≈+45). Most of it is the moved matrix block (+105 in templates.py, −105 in type_checker).
- Verified:
  - `make check` green.
  - `make test`: 10088 passed / 2 failed / 13 xfailed, against the 10086 / 2 / 13 baseline (+2 = the new graph_build tests). The 2 failures are exactly the ruling rows `output_prose_wrap_recorded_drift-today` and `output_escape_only_r3-today`, untouched.
  - `make test-e2e`: 51 passed / 2 skipped (unchanged).
  - Web: `npx vitest run` 810 passed (55 files; the 9 new rows are included), and `tsc --noEmit` is clean.
  - `capture.py --check`: 29 examples, 0 differing.
  - Red-first: both Python tests and 7 of the 8 first scan rows failed before the fix. The multi-index row is a partner that passed on both trees.
  - Python↔TS differential: every `${`-bearing string constant in the three template corpora (288 templates; 210 with refs, 33 with dynamic-index inner refs, 26 escapes) was run through Python `refs_with_path_in` and the TS `templateRefs` (extracted from `scan.ts` via esbuild). Result: **0 differing**. A planted TS mutation gave 46 differing, so the probe discriminates. Scripts: `scratchpads/task-170/phase4d/{corpus.json,diff.mjs}`.
  - UI, real surface:
    - Graph API on this tree: edge `e3 process-batch → correlate-batch results ['stdout'] command`. On a `git archive HEAD` copy (its own bundle build, served via `PYTHONPATH`): no such edge.
    - The screenshots show the dotted DATA_FLOW line from process-batch's `stdout` row into correlate-batch's `command` (after) and its absence (before).
    - `visual-invariants` (after, advanced / collapse=none): passed. Contract 4 = DOM 4, 0 missing, 0 overlaps.
  - Assumed: Windows is not exercised (no shell-dependent test added).
- Deviations/surprises (the signal):
  1. **`type_validation.py`'s `_generate_type_fix_suggestions` branch (`:138`) is unreachable, and was before 4d.** It runs only when `not is_type_compatible(inferred, expected)` AND inferred ∈ containers AND expected ∈ {str, string}. The matrix makes every container→str pair compatible (executed: all 8 True). I re-pointed it to `CONTAINER_TYPES` per plan, but it stays dead (~50 lines incl. the helper). Candidate deletion for the phase-5 simplicity lens; not deleted here (outside the plan's list).
  2. **`mermaid._strip_template` gains a branch with no behavior change.** For every grammar-valid simple template, `extract_simple_template_var` equals `[2:-1].strip()`, and the plan-mandated loose fallback keeps today's text otherwise. It fails the deletion test; kept per the plan, named for the simplicity lens.
  3. **`_debraced` (mermaid descriptions), two display differences vs today:**
     - An escape `$${x}` now shows `${x}` (today `$x`). That is the author's literal text, stated in the docstring.
     - An unclosed `${foo` now shows `foo` (today `${foo`).
     - A dynamic-index Expression's raw `a[${i}].x` still contains `${`. Today's regex also leaked it (`a[${i].x}`). Not a new leak.
  4. **Scope characterization beyond the plan's named pin:** the field tuple now keeps fields after an index everywhere: `${a.b[0].c.d}` → `("a","b",("c","d"))`, today `("a","b",())`. So `output_path` on such edges gains the deeper fields. Same rule as the pin; `build.py`'s consumers only compare `ref_field` and pass `ref_path` through. Pinned.
  5. **`build.py:849` batch-alias detection now sees an alias used only as a dynamic-index source** (`${x[${item.i}]}`). That is the dependency view, the correct direction. No test was affected.
  6. **TS/Python regex-flavor gap (pre-existing class, not widened):** Python `\w`/`\d`/`\b` are Unicode on `str`, JS without `u` is ASCII. So `${café.x}` is a Reference in Python and no read in the scan. The old `VAR_NAME_RE` had the same `\w`. Noted, not fixed.
  7. Plan §4's "manual end to end after 4d" list was not run. 4d changes no runtime path (graph/display/validator type homes only), and with 4c pending, "after phase 4" = after 4c. That list belongs to 4c's close.
  8. Pre-existing tooling bug (see the postmortem): `visual-invariants.pflow.md`'s `out_path` default is not applied. It reproduces on main's checkout and on the base copy.
- Self-checks:
  - Fully happy? Yes with the code. Loose ends are named above (1, 2, 6 for the lenses; 8 for tooling); none is mine to fix inside 4d.
  - Raised and fixed during the phase:
    - a stray `web/tsconfig.tsbuildinfo` (my `tsc -b`), removed;
    - a missing Issue-span row, added to both tables (`${a[${i ?? 0}]}` / `${gen.result[${idx.result ?? 0}]}`), after the ledger showed that no row pinned "an Issue runs through its first `}`";
    - the lens file's matrix row (`review-validation-consistency.md:181`), fixed and synced.
  - test-reflect (directed, the new scope/scan rows). Mutation ledger `scratchpads/task-170/phase4d/mutate.py` (apply, run, restore from bytes):
    - scope value view without inner refs → killed (1);
    - scope indices as fields → killed (2);
    - scan drops dynamic-index sources → killed (2);
    - scan unbalanced escape → killed (3);
    - scan Issue stops before the next OPEN → killed (1, by the added row);
    - scan indices as fields → killed (4);
    - **scan keeps literal operands → SURVIVED, an equivalent mutant at the interface.** No literal can produce a read: string, number, `[]` and `{}` literals fail `IDENT` in `pathRefs`, and `true`/`false`/`null` would be bare roots with no field, which never count. The skip stays so `templateRefs` equals `Expression.references`; the differential above covers it.
    - Nothing was deleted: each new row asserts exact read paths or exact tuples, with a presence partner in the same table ("a real ref after an escape still reads").
- Screenshot tooling postmortem (for disposition):
  - Worked well:
    - `screenshot.pflow.md -p` returns one path and settles reliably; both runs took under 20 s.
    - A `git archive` base copy plus a symlinked `node_modules` gave an honest before-state (its own bundle) with no stash.
    - The `/api/graph` JSON is the fastest edge oracle, faster than any screenshot.
  - Friction/near-miss:
    - (S) **`visual-invariants.pflow.md` fails with "Workflow requires input 'out_path'" despite `required: false` + a default** (the error comes at execution, after "Executing workflow (3 nodes)"; `--validate-only` passes). It also reproduces from the main checkout. The SKILL.md example command omits `out_path`, so the documented invocation fails. Workaround: pass `out_path=`. Needs an issue: either an input-default bug in the runner or in a sub-workflow call.
    - (S) SKILL.md's "Before running" starts the server on the default port 8765 and `make ui-build`, which re-runs `npm ci`. With parallel worktrees (another lane held 8791), a per-worktree port convention would avoid cross-lane collisions. I used 8793/8794.
  - Ideas:
    - (M) An `edges` filter mode on `inspect.pflow.md` (edge id → source/target/labels), so edge-correctness phases need no screenshot eyeballing.
- dev servers: none. I started `pflow ui` on 8793 (this tree) and 8794 (the base copy); both were stopped and verified down. The 8791 server belongs to another worktree (`fix-issue-650-…`) and was left alone.
- Next: the orchestrator reviews and commits 4d. 4c (cache chunker, `render_cache_chunks`, `_resolve_static_prefix_for_cache`) is untouched and waits on the R5 ruling; D can resume it. Not committed.

## [2026-09-30 22:00] task-orchestrator — 4d verified + committed; dispositions
- Verified (orchestrator re-run): `make test` 10088 passed / 2 failed (ruling rows) / 13 xfailed (4c); `make check` green; screenshot `4d-screenshots/after-process-batch-stdout-edge.png` read — the dotted DATA_FLOW edge from `process-batch`'s `stdout` row into `correlate-batch` is present (absent in the `before-` shot). No process rooted in this worktree (`pgrep -fl feat-task-170` empty).
- Dispositions of Agent D's items:
  - 1 (dead `_generate_type_fix_suggestions` branch at `type_validation.py:~138`) → phase 5: delete it if still unreachable (simplicity; ~50 lines).
  - 2 (`mermaid._strip_template` branch that changes nothing) → phase 5: drop it (fails the deletion test; the user lens outranks the plan's line).
  - 3 (graph edges keep fields after an index everywhere) → accepted: same rule as the planned `${data[0].field}` characterization delta, pinned.
  - 4 (surviving `scan.ts` literal-skip mutant, unobservable through the public output) → accepted; covered by the Python-vs-scan differential (288 templates, 0 diffs).
  - 5 (plan §4 manual end-to-end list) → runs at 4c's close + at completion, as D says.
  - 6 tooling postmortem (`visual-invariants.pflow.md` ignores its `out_path` default → "Workflow requires input 'out_path'"; the skill's documented command fails as written) → **issue** (pre-existing on main, shared tooling — not fixed in this PR while other producers are live); named in the completion handback.
- Next: 4c waits on the R5 ruling (and the prose-wrap ruling) — Agent D resumed on 4c when R5 lands.

## [2026-09-30 22:40] Agent D (Opus) — phase 5 part A: shim + dead-helper deletions, cache_overlap on the parse, 4d items 1–2 (no cache-block work)
- Did:
  - Deleted `src/pflow/runtime/template_resolver.py` (the shim). Re-pointed every `pflow.runtime.template_resolver` import in `tests/` to `pflow.core.templates`: 22 import sites in 20 files, lazy imports included. Grep-driven; the plan said 17.
  - Deleted `test_templates_module.py::test_shim_re_exports_the_same_objects`: it tested the deleted shim.
  - No `.claude`/CLAUDE.md/docs file named the old path. `test_agent_references` stays green; no asset sync was needed for this item.
  - Deleted `template_validation/utils.py::split_template_path`, its `__init__` export, and `test_nested_templates.py::TestSplitTemplatePath` (8 tests, sanctioned). There were zero src callers: the 4a `type_checker` stop-gap was already gone (verified by grep).
  - `cache_overlap.py`:
    - `_PFLOW_VAR_RE` deleted, along with its reach into `TemplateResolver._VAR_NAME_PATTERN`, `_is_batch_scoped_ref` and the `TEMPLATE_PATTERN` + split + literal-skip loop.
    - `_extract_body_refs` now reads value-position `Reference` operands of `parse(prompt).expressions`, skipping `op.root in batch_aliases`.
    - `_canonicalize_path` stays (§6).
  - Deleted the class-level `TemplateResolver._VAR_NAME_PATTERN` / `_LITERAL_PATTERN` aliases. Their last user, `test_template_grammar.py::_is_literal`, now asks the parse through the interface: `${text}` is simple and its operand is a `Literal`.
  - 4d item 1: deleted the unreachable Pass-6 suggestion branch, `_generate_type_fix_suggestions`, and `_traverse_to_structure`, which became dead with it. The mismatch diagnostic loses three context keys that were always `None` (`available_fields`, `_total`, `_label`) and `suggestions=None`. Also deleted the `Field`/`Segment`/`Sequence`/`parse_path` imports.
  - 4d item 2: `mermaid._strip_template` is back to its pre-4d body (the no-op grammar branch is dropped). `TemplateResolver` is no longer imported there.
  - `test_yaml_utils.py::TestBraceAwareTemplates` +2 pins: `$${y}` survives the flow form verbatim beside `${w}`; `${a[${i}].x}` is captured whole.
  - Stale test text re-worded: `test_workflow_data_flow.py:333/:844` (`_check_param_value`), `test_type_checker.py:366` (`_validate_array_access` → `utils.descend_index`), `test_validator.py:994` (`_split_template_path`), and the parity mutation string at `:1170` (`_node_template_value_sources` → `template_surfaces.iter_node_surfaces`).
- Changed:
  - src: `runtime/template_resolver.py` (deleted), `core/cache_overlap.py`, `core/templates.py`, `core/workflow/graph/renderers/mermaid.py`, `runtime/template_validation/{__init__,utils,type_validation}.py`. src diff: +12/−186.
  - tests: the 20 re-pointed files, plus `test_cache_overlap.py` (+4 parametrized rows), `test_yaml_utils.py` (+2), `test_templates_module.py` (−1), `test_nested_templates.py` (−8).
- Verified:
  - `make check` green.
  - `make test`: 10085 passed / 2 failed / 13 xfailed. Baseline was 10088 / 2 / 13; the delta −3 = −8 TestSplitTemplatePath −1 shim test +4 overlap rows +2 yaml pins. The 2 failures are exactly the prose-wrap ruling rows.
  - `make test-e2e`: 51 passed / 2 skipped (unchanged).
  - `capture.py --check`: 29 examples, 0 differing.
  - Gate grep `runtime.template_resolver|split_template_path|_PFLOW_VAR_RE` over `src/ tests/` → only `tests/test_import_hygiene.py:32/:172/:177`; see Deviation 1.
  - The plan's full phase-5 grep list over `src/ tests/ .claude/` → only `markdown_parser.py:_CACHE_TEMPLATE_RE` (4c) and the hygiene pin. `test_template_grammar.py:5` also mentions `_PERMISSIVE_PATTERN`, as a history note ("before —").
  - Overlap rows red-first: against the HEAD `cache_overlap.py`, 2 of the 4 rows fail. The dynamic-index overlap was missed before, and `$${a[${items}]}` was a false duplicate, because `TEMPLATE_PATTERN` cannot see escape consumption. The other 2 rows are partners.
- Deviations/surprises (the signal):
  1. **The gate grep cannot be empty while spec meta-test 3 lives.** `test_import_hygiene.py::test_core_does_not_import_the_template_shim` names `pflow.runtime.template_resolver` by design (spec Structure: "No module under core/ imports pflow.runtime.template_resolver or its shim (meta-test 3)"). I kept it; the spec outranks the grep.
     - With the shim gone, a top-level core import of it now fails loudly anyway. The pin still catches a lazy import, or a re-created module.
     - Options: (a) keep, which is what I did; (b) delete it and amend the spec's meta-test 3. Importance 2, reversible.
  2. **`cache_overlap` behavior deltas.** Both are consistent with delta 3 and 4 and are pinned by the new rows:
     - A dynamic-index body ref (`${items[${i}].x}`) now overlaps a chunk `items` as `cache_contains_body`. Before, it was excluded by the static-only `_PFLOW_VAR_RE`.
     - An escaped span no longer yields refs (`$${a[${items}]}` was a false `duplicate`).
     - The plan's `parse_path(operand) is not None` gate is not written: an operand the parse yields as a `Reference` already passed that grammar, so the gate would be dead.
     - A dotted inner index (`a[${i.j}].x`) still canonicalizes unevenly through the §6 `_canonicalize_path`. The outcome is still right for a chunk `a`.
  3. **Pass-6 type-mismatch JSON shape.** The diagnostic `context` no longer carries `available_fields: null`, `available_fields_total: null` or `available_fields_label: null`. These were always null, since the branch that set them could not run. No test or renderer depended on them (`diagnostic_render` reads `available_fields` with `.get`).
  4. **Near-miss (process):** while producing the red-first run I used `git stash -- <file>`, and it also stashed the staged shim deletion. My new `cache_overlap.py` briefly existed only in that stash. I restored it from the stash, diffed it, confirmed the tests green, and dropped only my own stash entry. The other `stash@{0}` (a different branch's WIP) was untouched. Nothing was lost; noted so the next agent uses byte copies, as the mutation script does.
- Self-checks:
  - Fully happy? Yes, with Deviation 1 left for the orchestrator's call.
  - Residual: `_is_shell_safe_type` still takes a `blocked_types` parameter that now has one caller, always passing `CONTAINER_TYPES`. It could fold, but that is outside the listed items.
  - test-reflect (directed as "not needed unless you add logic"): logic was added in `cache_overlap`, so I applied it to the 4 new rows. Each asserts the exact `(chunk, body_ref, kind)` list. The two behavior rows were red on the old code; the two partners (index source is not a ref; a real ref after an escape still counts) guard against over-correcting. The yaml pins assert exact dicts. Nothing shallow; nothing deleted beyond the sanctioned tests.
- dev servers: none (none started).
- Next: the orchestrator commits part A and rules on Deviation 1. Part B (meta-test 2, the instruction/docs pass, the final grep, LOC, completion examples `--check`) and 4c wait on R5. Not committed.

## [2026-09-30 23:00] task-orchestrator — phase 5 part A verified + committed
- Verified (orchestrator re-run): `make test` 10085 passed / 2 failed (ruling rows) / 13 xfailed (4c); `make check` green.
- Rulings (importance 1): meta-test 3 (`tests/test_import_hygiene.py` rule 4 naming `pflow.runtime.template_resolver`) **stays** — it is the spec's meta-test 3 and still catches a lazy import or a re-created module; the phase-5 grep list's `runtime\.template_resolver` entry is scoped to `src/` + every test except that meta-test. `cache_overlap` now reading the parse (dynamic-index refs overlap a cached root; escaped refs no longer false-duplicate) → accepted, pinned. The three always-null Pass-6 JSON keys removed with the dead branch → accepted (no reader).
- Next: 4c on the R5 ruling; then phase 5 part B.

## [2026-09-30 23:50] Agent D (Opus) — phase 4c (all but R5): chunker on parse spans, one `render_cache_chunks`, static prefix over segments (delta 5, R2)
- Did:
  - **Chunker on spans** (`markdown_parser._parse_cache_code_block`):
    - Every `parse(content).expressions` entry is a chunk. `name = var_expr = content[span[0]+2:span[1]-1]`, with `assert == expr.raw`.
    - `prose_before` is the escaped source slice, verbatim.
    - Escapes and Issues are prose (R2); duplicate / no-chunk / trailing-discard are unchanged.
    - `_CACHE_TEMPLATE_RE` is deleted.
    - A no-chunk block whose only `${` is an Issue now raises "Malformed template syntax in '## Cache': '<issue>' is not a valid '${var}' reference." Before, it said "must contain at least one '${var}'", which is false for such a block.
  - **One renderer:** `prompt_cache.render_cache_chunks(cache_ctx, shared) -> (list[RenderedChunk], skipped)`, where `RenderedChunk(name, prose, value)` is frozen.
    - Prose is unescaped by `_render_segments`; the value (`_resolve_chunk_value` → `deterministic_serialize`) stays verbatim.
    - `plan_node._render_cache_for_hash` is now 3 lines over it, with the hash dict shape unchanged. `build_cache_system_blocks` (the LLM node + prewarm) builds `prose + value` from it.
    - The undeclared-subset warning moved into the helper.
  - **`_resolve_static_prefix_for_cache` = `_render_segments(text, shared)`:** Text unescaped; each Expression resolved → `deterministic_serialize`, else raw; an Issue verbatim. Its stale "Python repr" docstring is rewritten.
  - **R5 left pending, named sites** (today's observable behavior kept; the 3 `cache_var_coalesce_*` rows keep `today`, and their R5 `after` items stay strict xfail):
    - (1) the comment-marked spot in the chunker loop (`markdown_parser.py`, "R5 (ruling pending)"): ruling (a) adds `if len(expr.operands) > 1: raise MarkdownParseError("coalesce is not supported in a ## Cache chunk")` there;
    - (2) `prompt_cache._resolve_chunk_value` (whole-var root gate: ruling (b) resolves per operand here);
    - (3) C2's `data_flow._cache_var_roots` whole-var-root branch for `??`/Issue, untouched.
  - **Tests (sanctioned):**
    - `test_prompt_cache_rendering.py:~427` identity pin retargeted: `plan_node.render_cache_chunks is prompt_cache.render_cache_chunks`.
    - Third byte-symmetry test `test_hash_render_and_prep_render_byte_equivalent_with_escapes`: prose `$${HOME}`, `$${a[${i}]}`, bare `$$`; values `"value keeps $${x}"` and a dict holding `$${y}`. hash texts == prep texts == the exact expected bytes.
    - `test_cache_block_parser.py` +10: 7 chunk rows, 2 Issue-only-block rows, 1 escape-only block.
    - `test_prompt_cache.py`: the Round-5 `TEMPLATE_PATTERN` parity test is replaced by 4 static-prefix parse rows.
  - **Docs:**
    - `docs/how-it-works/prompt-caching.mdx:46` now says prose is verbatim except `$${…}` → literal `${…}` (and is prose, not a chunk). `guide/features/prompt-caching.md` does not repeat the claim, so it is untouched.
    - `core/workflow/graph/CLAUDE.md`: `cached_prefix` keeps `prose_before` escaped.
- Changed:
  - src: `core/markdown_parser.py`, `core/prompt_cache.py`, `runtime/engine/plan_node.py` (the logger is dropped, now unused), `nodes/llm/llm.py` (two `noqa: F401` "meta-test identity" imports deleted, docstring).
  - tests: the four files above plus `test_template_parity.py` (rows below; the now-unused `CACHE_PROSE_ISSUE` constant is deleted).
  - src diff: +110/−119.
- Verified:
  - `make check` green.
  - `make test`: 10098 passed / 2 failed / 6 xfailed, against 10085 / 2 / 13. Deltas:
    - passed +13 = parser +10, prompt_cache +4−1, rendering +1−1 (escape test added, sentinel test deleted);
    - xfailed −7 = 7 flipped `after` items now plain passes.
    - The 2 failures are exactly the prose-wrap ruling rows.
  - `make test-e2e`: 51 passed / 2 skipped.
  - `capture.py --check`: 29 examples, 0 differing.
  - Corpus: 315 passed, 6 xfailed = the 3 R5 rows × 2 sides, all strict. No XPASS left; every 4c XPASS was flipped or re-derived (below).
  - Red-first against HEAD source (byte copies swapped in, then restored): every new parser row, the Issue-block rows, the escape-only row and the static-prefix escape rows fail on HEAD.
  - **Task-159 baseline** (`verify.sh`): 80 passed, 7 drifted, 0 harness errors. **All 7 drift identically with HEAD's source swapped in**, so they pre-date 4c. They are:
    - the analyze-cache "## Blocking errors — 'source' is a required property" block, from #628's sourceless-output rule (5 × `03-analyze-cache-modes`, `10-live-recordings/03`);
    - guide wording (`12-…/04-guide-auto-detect`: `agent` vs `claude-code`, code-node thread-output line).
    - None touches cache rendering, and there is no trace-format change. The oracle needs a re-record by its owner, not by this task.
  - **Real surface** (`scratchpads/task-170/phase4c/surface/`, isolated `HOME`, placeholder `ANTHROPIC_API_KEY`):
    - `home-escape.pflow.md` has cache prose `Shell note: expand $${HOME} yourself…` + `${topic}`.
    - `uv run pflow --validate-only` → "✓ Workflow is valid". `--dry-run --output-format json` → `execute`, `cache_key eb3d829d…`.
    - The real run went through the real CLI `main()` with ONLY the LLM adapter swapped for the repo's `tests/shared/llm_mock.MockLLMClient` (`run_mocked.py`): exit 0, output `ok`. The system block sent was `"Shell note: expand ${HOME} yourself; …\n\ncaching"`.
    - The trace `llm_system` holds `${HOME}` (no `$${HOME}`).
    - A second `--dry-run` → `cached`, `hash_match`, **same key `eb3d829d…`**: dry-run's hash render and the run's prepare/hash agree.
- Deviations/surprises (the signal):
  1. **Issue-only cache block → parse error (user-visible).** Under R2 an Issue is prose, so `Base: ${p.out.items.0}` (row `cache_var_issue_shape`) has no chunk. It used to be validator ERROR + runtime chunk silently ABSENT; now both sides raise the parse error with the standard "Malformed template" wording. Row runtime re-derived `Absent` → `Raises(MarkdownParseError, MALFORMED)`. Loud beats silent; I chose to name the Issue in the message.
  2. **`cache_prose_unclosed_r2`: phase 1's `after` contradicts the 4a Issue-span ruling.**
     - The `after` expected `Resolves("Unclosed ${a then S")` with a note that "an unclosed `${a` no longer swallows text". Under the ruled span (to the first `}`), the Issue `${a then ${p.out_str}` swallows the only chunk, so the block fails to parse.
     - Re-derived: validator `Error(MALFORMED)` (per your Dev-7 instruction; it arrives via the parse error), runtime `Raises(MarkdownParseError, MALFORMED)`. Pinned in the parser rows too.
  3. **`cache_prose_escape_declared_delta5` validator re-derived to `Error("never used as template variable: topic")`.** Before, `$${topic}` "used" `topic` through a bogus chunk; now the escape is literal and the input is genuinely unused. This is a correct delta-5 consequence, not a new rule.
  4. **`cache_var_dynamic_index` runtime `after` said `Base: A0`; the correct value is `Base: A1`**, because `i` takes its declared default 1 (`I_INPUT`). A phase-1 mis-derivation.
  5. **API shape vs plan:** `render_cache_chunks` returns `(rendered, skipped)`, not a bare list, because the prepare site needs `chunks_skipped` for `llm_usage`. The undeclared-chunk warning now lives in the helper, so it fires at the prepare site too, and it no longer names the node: `CacheRenderContext` has no node id, and threading one through for a bypass-only warning did not pass the deletion test.
  6. **R5 "one small, clearly named branch":** there is no code branch, only a comment at the exact spot. A `??` Expression needs no special handling to keep today's behavior, so a branch that does nothing would fail the deletion test (the user lens). Applying ruling (a) is a 3-line insertion there.
  7. **Tests beyond §5:**
     - `test_chunk_absent_sentinel_class_is_shared` is deleted. It asserted that `plan_node` and `llm` both re-export `_ChunkAbsentSentinel`; the ABSENT filter now exists once, inside `render_cache_chunks`, so the invariant is structural. That also let the two `noqa` identity imports in `llm.py` go.
     - `test_static_prefix_uses_resolver_pattern_object_directly` is replaced: it pinned `TEMPLATE_PATTERN`, which the helper no longer uses.
  8. `_render_segments(text, shared | None)`: one helper serves prose (no context → Expressions verbatim) and the static prefix (context → resolved). I considered two functions; one keeps the Text/Issue rule in one place.
- Self-checks:
  - Fully happy? Yes, with 1, 2 and 5 surfaced for your call.
  - Residual: `_resolve_chunk_value` still gates on the lexical `extract_root_node_id(var_expr)`. That is intentional until R5; for a single-Reference var it equals `parse` root. The `assert` in the chunker guards an invariant, not user input.
  - test-reflect (directed, byte-symmetry test + chunker rows). Mutation ledger `scratchpads/task-170/phase4c/mutate.py` (byte-copy restore), 7 of 7 killed:
    - prose not unescaped (both sites) → the escape symmetry test;
    - hash site re-escapes its prose → the escape symmetry test;
    - prepare unescapes `prose + value` together → the escape symmetry test (value `$${x}` must stay);
    - IR `prose_before` unescaped → parser row;
    - Issues become chunks → parser row;
    - static prefix not unescaped → static-prefix row;
    - no-chunk error loses the Issue → Issue-block row.
    - The symmetry test asserts EXACT expected bytes at both sites, not just hash == prep, so a symmetric-but-wrong render cannot fake-pass.
    - Nothing shallow found; nothing deleted beyond item 7.
- dev servers: none.
- Next: the orchestrator commits 4c-minus-R5. On the R5 ruling, D applies it: (a) the 3-line reject at the chunker comment + delete the `_cache_var_roots` whole-var-root branch + flip the 3 rows; or (b) per-operand resolution in `_resolve_chunk_value` + re-derive the rows. Then part B. Not committed.

## [2026-10-01 00:10] task-orchestrator — 4c (minus R5) verified + committed
- Verified (orchestrator re-run): `make test` 10098 passed / 2 failed (prose-wrap ruling rows) / 6 xfailed (the 3 R5 rows); `make check` green.
- Dispositions (importance ≤ 2): item 1 (a cache block whose only `${` is an Issue now fails the existing no-chunk parse rule, naming the malformed template) → accepted: it is ADR-0015's stated consequence ("a block left with no `${var}` fails to parse"), not a second Issue-policy home — Issues still never raise by themselves (R2); loud replaces validator-error-plus-silent-drop. Items 2–3 (row re-derivations: `cache_prose_unclosed_r2` per the 4a span + Dev-7; `cache_prose_escape_declared_delta5` "never used" = delta-4 validator half; `cache_var_dynamic_index` `A0`→`A1` phase-1 mis-derivation) → accepted. Item 4 (`render_cache_chunks` → `(rendered, skipped)`; the undeclared-chunk warning moved into the helper and now also fires at the prepare site without a node id) → accepted; **named for the completion gate** (agent-ux: a warning that lost its node id; silent-failures/feature-interactions: possible duplicate warning per run). Item 5 (R5 = one comment site + `_resolve_chunk_value` + `data_flow._cache_var_roots`) → noted; the ruling applies there.
- Task-159 baseline `verify.sh`: 80 pass / 7 drift — the same 7 with the pre-4c source swapped back in (Agent D executed), traced to #628's required-`source:` rule and guide wording on main → pre-existing, not this task; oracle re-recording by its owner = a follow-up for the completion handback.
- Next: phase 5 part B (grammar-uniqueness meta-test, final docs/instruction pass, grep list, LOC) — decision-independent except the R5 and prose-wrap seams.

## [2026-10-01 00:50] Agent D (Opus) — phase 5 part B: grammar-uniqueness meta-test, final grep, instruction/docs pass, LOC
- Did:
  - **Meta-test 2:** new `tests/test_core/test_template_grammar_seam.py` (§0.5.2).
    - Rule A: `ast.Constant` strings containing `\$\{` or `\${`.
    - Rule B: an `re.<fn>(…)` whose pattern argument names a `pflow.core.templates` import. Covered alias forms: `import … as`, `from pflow.core import templates as`, `from … import X as`, `TemplateResolver`, `import re as`, `from re import compile as`, and the `pattern=` keyword.
    - Prefilter `"$" | "TemplateResolver" | "templates"`.
    - Allowlist of 4 files, each with its reason verbatim: the seam, MCP env expansion, the YAML mask, the jsonschema patterns.
    - A stale-entry check: each allowlisted file must still yield ≥1 Rule-A hit.
    - 11 planted spellings, each must be flagged, plus a clean public-interface file that must yield zero hits.
    - **Green on first run:** no site outside the allowlist writes or composes the grammar.
  - **Final grep list** (§2 Phase 5) over `src/` is empty. Outside `src/`, the only hits are live symbols (`_render_cache_for_hash`, `_convert_to_string`), ADR history, the grammar-table docstring's "before" note, and meta-test 3 (scoped by your ruling).
  - **Instruction files:**
    - `core/CLAUDE.md`: the `templates.py` row now points to a new **Template language** section. It covers the module surface and leaf rule, grammar uniqueness plus the `scan.ts` same-step rule, and six rules: pick the view, dynamic index = one Reference, the two channels, author text only, raw-path mode, escapes, type rules. It ends with the ADR-0006 pointer. The types section's compatibility sentence became a pointer.
    - `runtime/CLAUDE.md`: the template section is cut to engine-specific facts plus a pointer. The stale "shim deleted by phase 5" sentence and the incident ref are gone.
    - `runtime/engine/CLAUDE.md` (re-read after #615): one paragraph in "Parameters, reuse, and templates". It covers channels, not text comparison; `inputs` per key; a sibling sharing the text keeps its own channel.
    - `template_validation/CLAUDE.md`, final:
      - the views paragraph → a pointer (its home is now core);
      - the matrix paragraph condensed and pointed at core;
      - the `#621` / `#441` incident refs restated as constraints.
    - `tests/CLAUDE.md`: +1 row (grammar seam + leaf pin).
    - `.claude/agents/pflow-codebase-searcher.md`: core CLAUDE.md scope line; the "Template usage" search row now names `core/templates.py` + `parse(|TemplateResolver|resolve(` (was `grep "\$\{"`); the trace-resolution step 1. `make sync-claude-assets` run (1 file).
    - `core/workflow/CLAUDE.md`: already current since 4b (references over `iter_node_surfaces`); left.
  - **Docs:**
    - `docs/how-it-works/template-variables.mdx`: the Array notation section gains the dynamic index as one reference (type kept, out-of-range/non-int → unresolved, `??` applies). The Escaping section now says an escape runs through its matching `}` with one nested level, gives the `$${NAME:-${default}}` example, and notes that text after the `}` is templated.
    - `src/pflow/guide/features/batch.md:~173`: **the claim was false.** `${my_input[${__index__}]}` DOES resolve now. The bold "Indexing works on a node's `.results`, not on declared inputs" is replaced by "A declared `array` input indexes the same way".
    - `architecture/reference/template-variables.md`: the one-regex "Pattern Recognition" block is replaced by the `parse()` description. It gains the balanced-escape sentence. The runtime-validation section's nonexistent `runtime/wrappers/template_wrapper.py` path and "set intersection" detection are replaced by the channels. The "false positive" note is restated.
- Changed:
  - tests: `tests/test_core/test_template_grammar_seam.py` (new).
  - docs/instructions: `src/pflow/core/CLAUDE.md`, `src/pflow/runtime/CLAUDE.md`, `src/pflow/runtime/engine/CLAUDE.md`, `src/pflow/runtime/template_validation/CLAUDE.md`, `tests/CLAUDE.md`, `.claude/agents/pflow-codebase-searcher.md` (+ `.codex` twin), `docs/how-it-works/template-variables.mdx`, `src/pflow/guide/features/batch.md`, `architecture/reference/template-variables.md`.
  - No production code change.
- Verified:
  - `make check` green.
  - `make test`: 10115 passed / 2 failed / 6 xfailed, against 10098 / 2 / 6. +17 = the new meta-test file. The 2 failures are the prose-wrap ruling rows.
  - `make test-all-local`: 10166 passed / 2 failed (same rows) / 2 skipped / 6 xfailed.
  - All three meta-tests green: parity corpus (apart from the 2 ruling rows), `test_template_grammar_seam.py`, and `test_import_hygiene.py` rule 4 + `test_templates_module.py`.
  - `tests/test_docs/` incl. `test_agent_references.py`: 24 passed.
  - Real-tree non-vacuity: a planted `src/pflow/core/_seam_probe.py` (`re.compile(TemplateResolver.TEMPLATE_PATTERN.pattern)`) made the real scan fail, naming it as Rule B. The file was removed.
  - Guide claim executed (`scratchpads/task-170/phase5b/input-index.pflow.md`): `--validate-only` valid, and the run gives `label=alpha` / `label=beta`.
  - Doc claims executed via `resolve()`:
    - `$${FOO:-${bar}}` → `${FOO:-${bar}}`;
    - `$${a} ${bar}` → `${a} B`;
    - `${results[${i}].t}` → `{'k': 1}` (dict kept);
    - an out-of-range index → unresolved, and with `??` → the fallback;
    - bare `$$` untouched.
  - **LOC** (merge-base `abcaa50f` with `origin/main`):
    - committed branch `src/`: 52 files, +2104/−2678;
    - including this uncommitted part: `src/**/*.py` +2029/−2631, **net −602 Python lines**; all of `src/` +2149/−2693.
    - The target was ≤ baseline; it is met (measured, not chased).
- Deviations/surprises (the signal):
  1. **`guide/features/batch.md` stated the opposite of today's behavior**, a user-facing agent instruction. Indexing a declared array input by `${__index__}` works: the #262-class over-rejection flipped in 4b. The plan said "verify"; I verified, found it false, and rewrote the sentence.
  2. **`architecture/reference/template-variables.md` had more false text than the pointer lines 4d fixed:** the old single regex, a deleted module path (`runtime/wrappers/template_wrapper.py`), and "set intersection" detection. All three are corrected. It is a long doc (1700+ lines) and I corrected only statements Task 170 made false; I did not re-audit the whole file.
  3. **Language-level rules moved to one home.** The dependency/value-view rule and the matrix semantics lived in `template_validation/CLAUDE.md`, and the dynamic-index/channel rules in `runtime/CLAUDE.md`. All four now live in `core/CLAUDE.md` → **Template language**, and the other two files point there. The per-package files keep only their package's facts.
  4. Meta-test 2's helper was split into `_bound_names` + `_by_symbol_patterns`, because ruff C901 flagged the single-function draft (14 > 10). The mutation ledger was re-run after the split.
  5. **`context/CONTEXT.md` proposals** (not edited):
     - **Issue**: "an unescaped `${` in a Template that opens no valid expression; always a validation ERROR, carried verbatim at runtime. _Avoid_: malformed template (as a noun), parse error."
     - **Dynamic index**: "an index that is itself a Reference, `a[${i}].x`; the whole thing is one Reference, unresolved unless the inner resolves to an in-range integer. _Avoid_: nested template, nested index."
     - Both are now used in code, CLAUDE.md files and diagnostics.
- Self-checks:
  - Fully happy? Yes.
  - Residual: `core/templates.py`'s own docstrings still carry `(#630)` / `(#621)` incident refs (`Resolution`, the module docstring). They are code comments outside this part's write list; they are a one-line cleanup candidate for the completion gate.
  - The ADRs keep the deleted symbol names by design (history).
  - test-reflect (directed, meta-test 2 only). Ledger of 9 mutations, 8 killed:
    - prefilter `$`-only → 6 planted Rule-B spellings red;
    - Rule B off → 6 red;
    - Rule A off → 9 red (plants + allowlist-stale checks);
    - Rule A missing the `\${` spelling → the escaped-literal plant red;
    - module aliases unbound → import-as-alias plant red;
    - `from re import` unbound → the re-function plant red;
    - `pattern=` keyword ignored → the re-module-alias plant red;
    - Rule B over-broad (grammar name anywhere in the call) → the clean-interface test red.
    - The 9th ("stale check disabled") survives by construction: in-tree, every allowlisted file does write a grammar. Its firing condition was shown directly: every entry yields ≥1 hit today, and the probe proves the scan reads real files.
    - Nothing shallow; nothing deleted.
- dev servers: none.
- Next: the orchestrator commits part B. Still pending: R5 and prose-wrap rulings → the 3 R5 rows + the 2 prose-wrap rows; examples `--check` at the end; the completion gate. Not committed.

## [2026-10-01 01:10] task-orchestrator — phase 5 part B verified + committed; completion gate commissioned
- Verified (orchestrator re-run): `make test` 10115 passed / 2 failed (prose-wrap ruling rows) / 6 xfailed (R5 rows); `make check` green. D's items: 1 (`guide/features/batch.md` said the dynamic-index-over-input shape does not resolve; executed: it does → corrected) accepted; 2 (architecture doc: fixed only statements this task made false) accepted; 3 (language rules homed in `core/CLAUDE.md` "Template language") accepted; 4 CONTEXT.md terms **Issue** / **Dynamic index** → proposed in the completion handback; 5 (issue numbers in `core/templates.py` docstrings) → the gate-runner's to settle (#621 as a forward pointer to the deferred ruling may stay; incident-style references go).
- Net `src/` Python vs merge base: +2029 / −2631 (−602).
- **Completion gate commissioned now, with the two user rulings still pending** (prose-wrap seam: `output_resolver._normalize_source` + 2 rows; R5: the chunker comment site + `_resolve_chunk_value` + `data_flow._cache_var_roots` + 3 rows). Reason: every other line is final; both rulings land as pre-specified edits at named sites; `review-falsifier` runs LAST, after the reading battery's fixes AND the rulings, so the shipped state is attacked by execution.
- Lens selection (Major tier: >500 lines, >50 files; engine diff ⇒ ≥ Full): **ran** `review-spec-conformance`, `review-simplicity`, `review-validation-consistency`, `review-silent-failures`, `review-impact-completeness`, `review-feature-interactions`, `review-agent-ux` (diagnostic wording changed across engine/validator/cache), `review-test-fidelity` (the corpus is the task's core deliverable) — 8 = the cap; + `review-falsifier` direct, last. **Skipped** `review-concurrency-safety` (no new threads/executors; the one shared-state hazard — cached AST across batch threads — is pinned by the frozen/tuple/fresh-`Literal.value` tests, and R10 only adds an `except`); `review-plan` / `review-architecture-fit` (plan mode only).
- Gate-runner: a **fresh** Opus review-evaluator (Agent E), packeted with spec + plan + this log — no single builder holds the whole diff (A–D each built a slice; D, the latest, is at ~440k).

## [2026-09-30 03:45] Agent E (Opus) — completion gate — reading battery
- Coverage:
  - Deep-review code mode via the pflow fan-out (`workflows/review/run-review-lenses.pflow.md`), provider **codex** (cross-model against the Claude builders A–D).
  - Scope: `git diff abcaa50f..0d5ce06c` (merge base with origin/main), minus `uv.lock` and the examples-baseline JSON. 130 files.
  - Lenses (8, the cap): spec-conformance, simplicity, validation-consistency, silent-failures, impact-completeness, feature-interactions, agent-ux, test-fidelity. **All 8 reported; none failed.** Each noted partial file reading, as expected on 130 files.
  - Target text: `scratchpads/task-170/gate/review_target.txt` (rulings, pending rows and named asks briefed). Report: `scratchpads/task-170/gate/report.md`, read in full.
  - No lens executed anything. I verified every Critical and Warning by execution: probes in `scratchpads/task-170/gate/{probe1.py,probe_cache_warn.py,surface/}`, with the merge-base tree at `scratchpads/task-170/gate/base` via `PYTHONPATH`.
- Findings and dispositions (lens, severity, finding, then disposition):
  1. **validation-consistency Critical, spec-conformance W1, feature-interactions W2 (convergent) — numeric literals with non-ASCII digits (`${1٢ ?? 7}`) crash `resolve` with `JSONDecodeError`.** CONFIRMED (the base guarded this through `try_parse_json`). FIXED:
     - the grammar's digits are ASCII `[0-9]`, never `\d` (JSON's digits, and what `scan.ts`'s JS `\d` means; `scan.ts` strings mirrored);
     - `_expression_at` admits a `Literal` only if `try_parse_json` decodes it, which makes "every literal-grammar match round-trips `try_parse_json`" true by construction.
     - Tests: `test_templates.py::test_numbers_json_cannot_decode_are_issues` (8 ids) + partner `test_a_large_number_within_the_limit_is_a_literal`.
  2. **test-fidelity Critical 1 — the literal and totality corpora miss those numbers.** FIXED by the same tests.
  3. **spec-conformance W2, validation-consistency W3 — a 5000-digit `[N]` makes `parse` / `has_templates` raise `ValueError`** (int-string limit). CONFIRMED. FIXED: `parse_path` returns `None` on the failed conversion, so the template is an Issue. The oversized literal is covered by item 1's decode gate. Test: the `big-index` / `big-literal` / `big-fallback` ids.
  4. **silent-failures W1, impact-completeness W, feature-interactions W1 (convergent) — an Issue after the last `## Cache` chunk vanished** (trailing prose is discarded), so validation passed. CONFIRMED as a regression: the base rejected `${typo..field}` via the cache root check; the branch said "✓ Workflow is valid".
     - FIXED with one rule in `_parse_cache_code_block`: an Issue in the discarded tail raises the malformed parse error at its own line. The old no-chunk Issue branch is the no-chunk case of the same rule, so the code got shorter.
     - Tests: `test_cache_block_parser.py::test_issue_after_the_last_chunk_is_named` (3 rows, line asserted) + partner `test_escape_after_the_last_chunk_is_still_discarded_prose`.
  5. **validation-consistency Critical — `while: ${"false"}` validates, then fails with `LoopConditionError` after the node ran.** CONFIRMED (base: treated as absent, silently ran once). Real severity is Warning: loud, not silent.
     - FIXED: the loop-condition gate types a string `Literal` operand as `str`, the same rule as a `str`-typed reference (the runtime belt raises on both).
     - Test: `test_loop_validation.py::test_string_literal_condition_is_a_known_string`, 4 conditions × while/until, exact message, with bool/number partners.
     - Consequence: `${c.exit_code ?? "done"}` is now rejected too. It is correct, since the runtime raises whenever that fallback fires.
  6. **impact-completeness Critical — carry values skip their dynamic-index sources.** CONFIRMED:
     - `${s.result.lst[${typo}] ?? s.result.lst[0]}` validated clean, so every round silently took the fallback;
     - an input used only in `${s.result.lst[${i}]}` was flagged "never used" (the corpus row masked it with `extra_params`).
     - FIXED: new `Reference.index_sources` (`references` = self + index_sources). `data_flow._checked_references` checks a carry's index sources, and `operands.iter_template_operands` yields them for accounting. The outer self-reference keeps its own carry check. Executed: an invalid carry `${ghost.result}` still gets exactly ONE diagnostic, as on the base; dropping the skip wholesale would have given two.
     - Tests: parity rows `dyn_loop_carry_index_source_counts_as_input_use` and `dyn_loop_carry_index_source_root_typo`.
     - `template_validation/CLAUDE.md` carry bullet updated.
  7. **test-fidelity Critical 2 — no test proves the diagnostic classifies the channel the check judged** (all callers used the self-resolving default). CONFIRMED. FIXED: `test_node_wrapper_template_validation.py::TestInputsResolvedPerKey::test_diagnostic_names_only_the_kept_misses` (optional `${skipped.stdout}` injected, required `${broken.stdout}` named alone).
  8. **simplicity Suggestion (named ask) — `build_template_error_diagnostic(..., resolution=None)` self-resolving default.** FIXED: `resolution` is required; the fallback branch and the `resolve` import are gone. 29 calls in `test_template_error_messages.py` go through one local `_diagnose` helper (resolve, then diagnose); `test_runner.py` and `test_failed_node_invariant.py` pass `resolve(...)` explicitly.
  9. **agent-ux W1 — an out-of-range / non-int dynamic index reads as "does not produce field 'result[${idx}].name'"** beside "Available fields: result". CONFIRMED by a real run.
     - FIXED: a path_error on a reference whose index sources resolved carries `index_values` (`{"idx": 5}`). The renderer prints `Index ${idx} is 5` under the field line (value truncated at 80 via `_truncate_error_text`).
     - Executed: the trace carries no diagnostic context (0 hits for `unresolved_references` / `index_values`), so **no trace field**. The CLI JSON error gains the key only for dynamic-index path errors.
     - Tests: `TestDynamicIndexDiagnostics::test_out_of_range_index_shows_the_index_value` + partner `test_static_path_error_has_no_index_values`.
     - SKIPPED part: the lens's "suggest index 0 or add `??`" repair line. The value line makes the cause visible, and a canned repair would guess.
  10. **simplicity handoff (no severity) — `Reference.first_field` offset wrong for `a[01].x`** (re-rendered `[1]`), so `_extract_field_path` sliced `].x`. CONFIRMED. FIXED: the offset is the first `.` outside brackets in `raw`, which is simpler than the re-render loop. Test: row `a[01].x → (5, "x")`.
  11. **agent-ux W2 plus five lenses' handoffs (named ask) — `render_cache_chunks`' undeclared-chunk warning repeats per render without a node id.** Verified by execution: `compile_workflow` raises `CompilationError` on an undeclared `prompt_cache` name (data-flow B2.3), so the branch is unreachable for any compiled workflow. Only a hand-built `CacheRenderContext` reaches it, and there is **no duplicate warning in any real run**. The comment's "direct compile_workflow" claim was false: CORRECTED. SKIPPED the node-scoped redesign: it would add a parameter for an unreachable path, which fails the deletion test.
  12. **test-fidelity W1 — grammar-seam Rule B misses an unaliased `pflow.core.templates.X` chain.** CONFIRMED. FIXED: a pattern whose unparsed source names the module is flagged. Planted case `qualified-module` added.
  13. **simplicity Suggestion — `resolve_template_parameter`** had one caller, an unused `key` and a redundant tuple. FIXED: inlined, 3 lines at the caller.
  14. **agent-ux Suggestion — the Issue pass's hint ("Check for missing '}'…") is irrelevant to `${producer.items.0}`.** FIXED: the suggestion names the Issue (truncated at 60) and the fixes: bracket index, close `${`, `$${` escape. The count message is unchanged. Test: `test_malformed.py::test_malformed_template_suggestion_names_the_issue_and_the_fixes`.
  15. **spec-conformance S1, impact S, agent-ux S — `data-type-coercion.md:73/:90` name deleted `TemplateResolver` methods.** FIXED: they point at `_json_container` / `_walk` / `_resolve_string`. Left: `:104`'s `runtime/wrappers/template_wrapper.py` path, which is dead from before this task.
  16. **All 8 lenses, Suggestion (named ask) — incident refs in `core/templates.py` docstrings.** FIXED: `#630` ×2, `#460`, `#441` replaced by the constraint text. `#621` is kept only as the forward pointer "the deferred #621 tolerance ruling".
  17. **Named ask to simplicity — Passes 6/7/9's own param walks.** The lens verified KEEP: shell checks need quote spans, code checks need bindings/annotations, and dependency refs must not be typed as values, so folding them adds filtering without removing logic. No change.
  18. **spec-conformance coverage note — plan §4's final manual checklist (P:962) and the blocking `tests-windows` gate (P:971) are not established.** HANDED BACK: `review-falsifier` / the orchestrator's final pass and CI own them. Windows is not exercised locally.
- Changed:
  - src: `core/templates.py`, `core/markdown_parser.py`, `core/prompt_cache.py` (comment), `core/diagnostic_render.py`, `core/workflow/data_flow.py`, `runtime/engine/template_errors.py`, `runtime/engine/template_resolution.py`, `runtime/template_validation/{validator,operands}.py`, `runtime/template_validation/CLAUDE.md`.
  - web: `src/graph/scan.ts` (4 regex strings, `\d` → `[0-9]`; equivalent in JS).
  - docs: `architecture/core-concepts/data-type-coercion.md`.
  - tests: `test_templates.py`, `test_cache_block_parser.py`, `test_loop_validation.py`, `test_template_grammar_seam.py`, `test_template_parity.py` (+2 rows), `test_node_wrapper_template_validation.py`, `test_template_error_messages.py`, `test_malformed.py`, `test_runner.py`, `test_failed_node_invariant.py`.
- Verified:
  - `make check` green.
  - `make test` **10146 passed / 2 failed / 6 xfailed** against my captured baseline 10115 / 2 / 6. +31 = my new test items. The 2 failures are exactly `output_prose_wrap_recorded_drift-today` / `output_escape_only_r3-today`.
  - `make test-all-local` **10197 / 2 (same rows) / 2 skipped / 6 xfailed** (baseline 10166).
  - `capture.py --check`: 29 examples, 0 differing.
  - `web`: `npx vitest run src/graph/scan.test.ts` 17 passed, `tsc --noEmit` clean.
  - No benchmark flake occurred.
  - Mutation ledger `scratchpads/task-170/gate/mutate.py` (byte-copy restore): 11/11 fixes, each revert KILLED by its new test (M1–M11). M1 (back to `\d`) kills only the index row: the decode gate alone already turns non-ASCII literal digits into Issues, so ASCII digits are load-bearing for indices (Python `int('١')` resolves where `scan.ts` cannot match).
  - Real surface: the `scratchpads/task-170/gate/surface/*.pflow.md` probes were each run before and after.
- Deviations/surprises:
  - (a) Grammar tightening outside the Sanctioned deltas, importance 1: `${a[١]}` (a non-ASCII digit index) is now an Issue, so a validator ERROR. It resolved at runtime before and never matched the TS mirror.
  - (b) A no-chunk cache block whose Issue sits on a later line now reports that Issue's line instead of the block's first line.
  - (c) The CLI JSON error gains `index_values` on dynamic-index path errors. It is additive, not in the trace.
  - (d) `test_template_error_messages.py` now routes through `_diagnose`. It is the honest "diagnose what resolve left" helper; the channel-filtering contract is pinned at the `resolve_templates` level (item 7).
  - Nothing at importance ≥3 was applied. Nothing contradicts the ledger, ADR-0006/0015 or a logged ruling: #503's `ValueError`, `_gate_pausable` and the other lanes' files are untouched.
- Self-checks:
  - Fully happy? Yes with the fixes. Residual doubts:
    - Item 5's widening to `??` string fallbacks is a real (correct) new rejection that an existing workflow could hit. No example or test did.
    - Item 11 keeps an unreachable warning rather than deleting it: a judgment call, and cheap to reverse.
  - test-reflect: every new test asserts exact values/messages/lines and was revert-red. The `_diagnose` helper is kept deliberately (without item 7's test it would hide the contract; with it, it doesn't). Nothing deleted.
- Next: the orchestrator reviews + commits. Pending user rulings (prose-wrap seam, R5) are unchanged. Then `review-falsifier` directly, LAST. Hand it the spec path + spec-conformance's inventory (report §"Verified clean → review-spec-conformance"). I stay available to evaluate its report.

## [2026-10-01 04:10] task-orchestrator — reading battery closed; falsifier launched
- Verified: `make test` 10146 passed / 2 failed (prose-wrap ruling rows) / 6 xfailed (R5); `make check` green. Read Agent E's 18 dispositions (report `scratchpads/task-170/gate/report.md`).
- Orchestrator dispositions on E's residuals: item 5's widening (`while: ${c.exit_code ?? "done"}` now rejected) → accepted, importance 2: it types a string-literal operand exactly as the existing rule types a `str`-typed reference operand (policy consistency), and the fallback fails at runtime every time it fires — **surfaced in the completion handback** as a user-visible validator tightening alongside the shell-typing one; item 11 (unreachable warning kept, comment corrected) → accepted; deviations (a)–(d) accepted ((c) `index_values` is CLI-JSON only — trace untouched, E executed the check).
- Committed the gate fixes. **`review-falsifier` launched directly now** (reading-battery fixes landed): scope = everything EXCEPT the two user-pending seams (prose-wrap `_normalize_source` + its 2 rows; R5's three sites + 3 rows) — a targeted falsifier re-check covers those after the rulings land. Packet: spec path + the spec-conformance section of the gate report (`## Verified clean → review-spec-conformance` + its findings) as the Requirement Inventory + plan §4's manual end-to-end list.

## [2026-10-01 04:40] Agent E (Opus) — completion gate — falsifier
- Did: evaluated the `review-falsifier` report at `68848924` (probes in `scratchpads/task-170/falsifier/`), re-ran its W1/S1 repros on this tree, and applied the two directed fixes, each with tests that fail without the fix.
- Findings and dispositions:
  1. **W1 — `--dry-run` predicts node failure for a `continue` batch sub-workflow whose item[0] fails to resolve, while the run succeeds.** CONFIRMED on `r10.pflow.md` (parallel) and `r10seq.pflow.md` (sequential): exit 1 with "Template Resolution Failed". FIXED in `execution/plan.py::_prepare_batch_sub_workflow_params`: under `error_handling: continue`, item[0]'s probe resolves with `replace(template_config, resolution_mode="permissive")`. It still supplies the merged params/child shape; the per-item loop (`_resolve_per_item_sub_workflow_inputs`, which already covers index 0) emits the R11 WARNING "Batch item 0: 'inputs:' left ${…} unresolved (strict mode). Runtime will reject this item."
     - This mirrors R10's runtime pre-warm skip. The planner cannot skip the probe, because it needs item[0]'s params to locate and compile the child.
     - `fail_fast`/default keeps the node-level ERROR (`r10ff`: exit 1). A redundant local `from dataclasses import replace` in `_attach_entry_flags` folded into the module import.
     - Tests: `test_plan_batch_sub_workflow.py::test_first_item_template_miss_under_continue_is_a_per_item_warning[True|False]` (plan status `sub_workflow`, exact single warning, AND the real run succeeds) + partner `test_first_item_template_miss_under_fail_fast_still_fails_the_plan` (plan ERROR naming `${item.v}`, real run fails). With HEAD's `plan.py` swapped in, both parametrizations fail and the partner passes.
     - Residual (named, not fixed): under `continue`, a strict item[0] *type-validation* error is now also not a node-level plan error, and the per-item loop checks only the unresolved/Issue channels, so the plan is silent on it. At runtime that is a per-item failure too. Not observed; one-line revert.
  2. **S1 — out-of-range index on a declared INPUT reads "Node 'labels' executed but does not produce field 'labels[5]'".** CONFIRMED (`inoob.pflow.md`). FIXED:
     - a path_error carries `root_is_node` (the root is in `__execution__.completed_nodes`; true when the context has no execution record, keeping today's wording);
     - the renderer says `'labels' has no '[5]'` for a non-node root;
     - when no field follows the root, the path shown is what follows it, never the root again.
     - Also correct now for a batch item alias: `${item.nope}` read "Node 'item' executed…" and now reads `'item' has no 'nope'` (executed).
     - A node root keeps its wording on a real run (`dyn-oob`). Dry-run shows the same text (`r10ff`: `'labels' has no '[${item.idx}]'` + `Index ${item.idx} is 5`).
     - Tests: `TestDynamicIndexDiagnostics::test_input_root_is_not_called_a_node_and_the_root_is_not_repeated[static|dynamic]` + presence partner `test_node_root_keeps_the_node_wording`. The two new ones fail with HEAD's renderer; the partner passes on both.
  3. **Observation — batch memo cache serves stale results when a non-item value changes (`instrumentation.py::_compute_memo_cache_key`).** NOT THIS DIFF: `instrumentation.py` has no diff vs the merge base; the falsifier executed it identically on base → lane issue.
  4. **Observation — prewarm warm-up drops the user `system` when there is no `## Cache`.** NOT THIS DIFF: the `batch_executor.py` diff has no `system` line. `engine._resolve_template_string` changed only its unresolved detection (channels vs re-scan; `prewarm_system_*` rows pin that), and the base run is identical → lane issue.
  5. **Observation — `read-fields` reports a found `null` as "(not found)".** NOT THIS DIFF: `cli/commands/read_fields.py` changed only its import. `resolve_value` → `None` conflates found-null with a miss (the walk pair's `variable_exists` exists for that), and the formatter predates this task → lane issue.
  6. **Windows question** (`tests-windows` runs the WHOLE suite in two shards, `.github/workflows/main.yml:211-224`, with Git Bash via `PFLOW_BASH`):
     - `$${…}` through the shell node: COVERED. `tests/test_runtime/test_template_escape.py` runs real shell workflows with `$${PRICE}`, `$${VAR:-world}`, `$${name}`.
     - Escape-built sub-workflow path: COVERED by `sub_workflow_escape_only_r6` (validator + runtime + end-to-end).
     - Path with spaces: was NOT covered; cheap fix applied. The corpus child now lives in `tmp_path/"child dir"/`, so every `${child}` row, incl. `test_runtime[sub_workflow_templated_path-today]`'s real end-to-end run, carries a spaced (on Windows, backslashed) path through resolution. It is deterministic and adds no new test.
     - CRLF `.pflow.md`: NO test warranted. Every workflow read is `Path.read_text` (universal newlines: `manager.py:269/420`, `sub_workflow_resolver.py:163/194`, `dependency_discovery.py`), so CRLF never reaches `parse()`. CRLF stdin normalization is already pinned (`test_run_stdin.py::test_win32_text_stdin_normalizes_crlf_from_real_buffer`), and the falsifier's LF/CRLF engine run was identical.
- Changed: `src/pflow/execution/plan.py`, `src/pflow/runtime/engine/template_errors.py`, `src/pflow/core/diagnostic_render.py`; tests `test_plan_batch_sub_workflow.py` (+3), `test_template_error_messages.py` (+3), `test_template_parity.py` (spaced child dir).
- Verified:
  - `make check` green.
  - `make test` **10152 passed / 2 failed / 6 xfailed** (+6 over 10146 = the new tests). The 2 failures are exactly the prose-wrap ruling rows.
  - `make test-all-local` **10203 / 2 (same) / 2 skipped / 6 xfailed**.
  - `capture.py --check`: 29 examples, 0 differing.
  - Falsifier repros re-run: `r10`, `r10seq` exit 0 with the item-0 warning; `r10ff` exit 1; `inoob` and `inoob-dyn` wording as above.
- Deviations/surprises:
  - `root_is_node` is a second additive key on CLI-JSON path errors (the trace carries no diagnostic context, as executed in the reading-battery entry).
  - S1's wording fix also corrects batch-item-alias misses, which the falsifier did not name.
  - Nothing at importance ≥3; no ledger/ADR/ruling contradiction; #503, `_gate_pausable` and the other lanes' files untouched.
- Self-checks: fully happy with both fixes. The residual in item 1 is named above. test-reflect: every new test asserts exact messages/statuses and is revert-red, and each has a presence partner; nothing shallow.
- Next: the orchestrator commits. The two user rulings (prose-wrap seam, R5) and the targeted falsifier re-check on those seams remain. Items 3–5 go to lane issues in the handback.

## [2026-10-01 06:00] task-orchestrator — falsifier findings closed
- Verified: `make test` 10152 passed / 2 failed (prose-wrap ruling rows) / 6 xfailed (R5); `make check` green. E's dispositions accepted: W1 fixed (planner's item[0] probe under `continue` runs non-strict so R11's per-item warning reports it; `fail_fast`/default still fail — the residual "a strict TYPE error on item[0] under `continue` no longer fails the plan" matches runtime per-item semantics, accepted, one-line revert); S1 fixed (input/alias roots read `'<root>' has no '<path>'`; node roots unchanged; CLI JSON gains `root_is_node`, trace untouched); observations 1–3 confirmed not this diff → lane issues in the handback; Windows: spaced child path added to the corpus row, CRLF normalized by `read_text`.
- Remaining before close: the two user rulings (prose-wrap seam; R5) → apply → targeted falsifier re-check on those seams → merge main → final gates → create-task-review → create-pr.
