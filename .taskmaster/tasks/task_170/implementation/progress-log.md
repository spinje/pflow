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
