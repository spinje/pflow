# Task 159 Fix Brief 07 — Final Verification and Task 160 Readiness

Status: research / release-closure handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`

## Purpose

This brief captures what should be true before Task 159 is called complete and
before Task 160 starts.

Task 160 is a pure-structure refactor of `src/pflow/core/cache_analysis/`.
Its own spec says zero behavior change is the bar. The final Stage 2
verification report says Task 159 behavior is not fully verified yet. Therefore
Task 160 should wait until the behavior/UX issues represented by briefs 01-06
are researched, fixed or consciously deferred, and re-verified.

The next agent should use this brief as a closure checklist and sequencing
guide. It is not a substitute for reading the individual issue briefs.

## Inputs to Read First

Read these in order:

1. `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
2. `scratchpads/stage2-verification/README.md`
3. `scratchpads/task159-fix-briefs/01-cost-semantics-negative-savings.md`
4. `scratchpads/task159-fix-briefs/01-cost-semantics-session-research-addendum.md`
5. `scratchpads/task159-fix-briefs/02-trace-evidence-scope-partial-and-dynamic-batch.md`
6. `scratchpads/task159-fix-briefs/03-report-cost-semantics-memo-hits.md`
7. `scratchpads/task159-fix-briefs/04-cli-run-contract-only-output-and-warning-exit.md`
8. `scratchpads/task159-fix-briefs/05-recommendation-actionability-scope-and-syntax.md`
9. `scratchpads/task159-fix-briefs/06-guide-warning-catalog-drift.md`
10. `.taskmaster/tasks/task_160/task-160.md`
11. `src/pflow/core/cache_analysis/CLAUDE.md`

Also read the progress-log sections listed in each issue brief, not just the
section titles. Most pitfalls in Task 159 came from subtle trace/cost semantics
that are explained only in the progress log.

## Current Brief Coverage

The final verification report's 12 findings are covered as follows:

| Final report finding | Covered by |
|---|---|
| F1 guide stale vs warning catalog | Brief 06 |
| F2 impossible negative savings percentages | Brief 01 + addendum |
| F3 memo-hit reports show historical provider costs | Brief 03 |
| F4 partial `--only` trace analysis misleading | Brief 02; cost overlap in Brief 01 |
| F5 below-threshold cache block recommendation | Brief 05; cost/actionability overlap in Brief 01 |
| F6 dynamic batch model accounting wrong | Brief 02 |
| F7 `--only` output routing dumps huge intermediate JSON | Brief 04 |
| F8 warning-only executions exit code 2 | Brief 04 |
| F9 skipped branch analysis/reporting context confusing | Brief 02 for evidence scope; likely also touches report/runtime warning policy |
| F10 `$shared_doc` syntax in recommendation | Brief 05 |
| F11 `<unknown>` workflow identity | Brief 05 |
| F12 negative-signed savings wording | Brief 01 |

If a future agent discovers an item is already fixed in the current worktree,
record that explicitly in the relevant brief or in the closure report. Do not
delete the brief just because the issue no longer reproduces; the evidence and
test expectations are still useful.

## Release-Readiness Position

Current position from the final report:

- Provider prompt-cache mechanism works on real Anthropic Haiku.
- `prompt_cache` rendering, provider cache writes/reads, and rerun cost
  reduction are verified.
- Remaining failures are mainly analyzer correctness, report cost semantics,
  CLI contract, and agent UX.

The important distinction:

- The provider feature is mechanically real.
- The agent-facing surfaces are not yet trustworthy enough to call Task 159
  complete.

Because Task 159 is an agent-facing cost/performance feature, misleading
analysis output is not superficial. If an agent is led to trust wrong
model/cost evidence or apply a non-functional cache edit, that is a Task 159
failure.

## Suggested Fix Sequencing

This is a sequencing recommendation, not a mandate. The fixing agent should
verify dependencies before implementation.

1. **Cost semantics first**
   - Brief 01 and its addendum.
   - Reason: negative savings and possibly wrong Anthropic token accounting can
     contaminate summaries, dry-run nudges, and recommendation ranking.

2. **Trace evidence scope and dynamic batch truth**
   - Brief 02.
   - Reason: partial traces and per-item dynamic model data define which rows
     are valid evidence for cost/model claims.

3. **Recommendation actionability and scope**
   - Brief 05.
   - Reason: below-threshold and wrong-syntax recommendations cause agents to
     apply bad edits. Some fixes may depend on the cost/trace semantics above.

4. **Report and CLI run contract**
   - Briefs 03 and 04.
   - Reason: these are user-visible surfaces, but they likely depend less on
     analyzer internals. Warning-only exit policy may require a user decision.

5. **Guide/catalog drift**
   - Brief 06.
   - Reason: update after behavior and warning IDs settle, unless a warning ID
     drift test is needed earlier to protect in-flight work.

6. **Verification gate cleanup**
   - Fix lint/test-gate issues.
   - Run final verification sweep.

## Decisions That Likely Need User Input

Future agents should not silently choose these if code inspection does not make
the right answer obvious:

- What should warning-only successful runtime executions return as process exit
  code?
- Should first-run provider write premiums render as signed deltas, "write
  premium", null/unavailable, or some separate field?
- Should partial `--only` traces suppress whole-workflow aggregate fields, or
  expose them only under explicit partial/projection labels?
- Should below-threshold suggestions be suppressed entirely, downgraded to
  non-actionable hints, or rendered as "expand this chunk first" guidance?
- Should warning guide text be manually maintained with drift tests or
  generated from the live catalog?

Reminder: there are no external analyzer users yet. Backwards compatibility for
current analyzer JSON field names/semantics is not a constraint. Simplicity and
truthfulness of the final model are more important.

## Verification Gate Status From Final Report

The final report recorded:

- Non-e2e sandbox gate:
  - `6281 passed`.
- E2E as documented failed 5 tests due known sandbox/Homebrew `uv` subprocess
  behavior:
  - `test_litellm_not_imported_by_cli_main`
  - `test_progress_streams_before_downstream_nodes_complete`
  - `test_cli_save_subprocess_with_overlap_exits_nonzero`
  - `test_thinking_temperature_mismatch_pflow_save_subprocess_exits_nonzero`
  - `test_dry_run_json_mode_emits_no_stderr`
- Filtered e2e rerun excluding sandbox-affected subprocess tests:
  - `18 passed, 18 skipped`.
- Focused cache sweep after excluding two sandbox/Homebrew-uv save subprocess
  tests:
  - `883 passed, 2 deselected`.
- Static checks:
  - `ruff check` failed with 38 lint issues in tests, mostly `RUF043` and
    `RUF059`.
  - `ruff format --check` passed.
  - `mypy src` passed.
  - `deptry src` passed.

Release closure needs a clean explanation of any remaining sandbox-specific
failures and a clean static gate on source/tests that are in scope for the
branch.

## Verification Commands

Use the commands in `scratchpads/stage2-verification/README.md` as the
canonical source of truth. In Codex sandbox mode, prefer the sandbox-safe
forms.

Full non-e2e sandbox gate:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m "not e2e"
```

E2E sandbox gate:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 \
  --dist=worksteal \
  --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -m e2e
```

Static checks:

```bash
.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/mypy src
.venv/bin/deptry src
```

Focused cache sweep is listed in the Stage 2 README. Use it before debugging
unrelated failures.

## Required Human/Agent UX Checks

Do not treat command exit code alone as pass/fail for Task 159. Agent UX is a
first-class verification target.

At minimum, manually inspect:

- `pflow guide caching`
  - Warning IDs and cache-layer wording are current.
- `pflow analyze-cache <workflow>` text
  - Blocking errors and recommendations are separated.
  - No negative amount is called "savings".
  - Below-threshold recommendations are not copy-paste actionable unless they
    can provider-cache.
- `pflow analyze-cache <workflow> --format=json`
  - JSON fields tell the same semantic story as text.
  - Partial traces are represented honestly.
  - Dynamic batch model evidence is not collapsed to a wrong default model.
- `pflow <workflow> --report`
  - Cached node pages distinguish paid-this-run from historical source cost.
  - Cache telemetry and `## Cached System` sections remain visible.
- `pflow <workflow> --only <node>`
  - Stdout/stderr messaging matches what is actually emitted.
  - No skipped declared output is claimed as streamed when an intermediate node
    output is emitted instead.
- Warning-only successful runtime executions
  - Exit code and wording match the user-approved policy.

## Paid Provider Re-Run Policy

Do not spend provider budget just to prove the already-verified core mechanism.

Historical evidence from the README/report:

- Anthropic Haiku song-creator traces already prove the spec target:
  - `RUN-HAIKU-FINAL` = 48% fresh input reduction.
  - `RUN-HAIKU-RERUN` = roughly 99% rerun reduction.
- The final report's live Haiku smoke showed provider writes/reads and cheaper
  reruns.

Re-run paid provider workflows only when a fix touches:

- runtime prompt rendering,
- provider telemetry normalization,
- trace cost accounting,
- dynamic batch trace/model accounting that cannot be proven with fixtures,
- or the external lyrics-generator workflow itself.

For clean provider-cache proof, use Anthropic Haiku. Gemini has implicit cache
that can confound explicit `prompt_cache:` measurement.

## Closure Report Expectations

After fixes and verification, write a new closure note rather than editing away
the historical final report.

Suggested path:

```text
scratchpads/stage2-verification/POST-FIX-CLOSURE-REPORT.md
```

The closure report should include:

- Which findings were fixed, deferred, or found no longer reproducible.
- For deferred findings, why deferral is acceptable and what issue/spec tracks
  them.
- Commands run and results.
- Any sandbox-specific test exclusions.
- Manual UX observations, not just exit codes.
- Any paid provider spend and why it was necessary.
- Whether Task 159 is now ready to call complete.
- Whether Task 160 can start.

## Task 160 Readiness Criteria

Task 160 can start only when:

- Task 159 behavior fixes are complete or explicitly deferred with user
  approval.
- Analyzer/report/CLI output is no longer known to mislead agents about
  cost/model/cache actionability.
- Final verification or closure report exists.
- Cache-related focused sweep passes.
- Static checks are clean or remaining failures are documented as unrelated
  and accepted by the user.
- The working tree is in a state where a pure structural refactor can preserve
  behavior.

Do not start Task 160 while behavior fixes are actively changing
`cache_analysis/`. The refactor would make both review and regression diagnosis
harder.

## Non-Goals for This Brief

- Do not solve individual findings here. Use briefs 01-06.
- Do not prescribe exact implementations.
- Do not treat current analyzer JSON compatibility as a constraint.
- Do not re-run expensive provider workflows without a concrete need.
- Do not begin Task 160 before Task 159 closure is real.

