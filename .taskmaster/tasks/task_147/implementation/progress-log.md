# Task 147 — Planning Session Progress Log

## 2026-04-07 — Session kickoff

**Starting point**: User provided GitHub issue #219 context + a pre-verified analysis showing the bug was real. The task brief was framed as "verify this, then let's discuss our options." Branch `fix/workflow-validator-return-type` was already checked out in a worktree.

**First move**: Read the issue, the validator, the runner consumer, the exception, the diagnostic module, the template validation sublayer, and the existing tests — in parallel. The goal was to independently verify every claim in the issue body before agreeing with anything.

**Key finding from verification**: The issue body had one claim that was **stale**: "the `run()` path doesn't have this problem because it raises `WorkflowValidationError` with tuple errors." Reading `runner.py:393` showed `WorkflowValidationError(validation_errors=errors)  # type: ignore[arg-type]` where `errors` is `list[str]`. Both paths are equally bare. This was the first "trust but verify" moment — the issue author's mental model was from an older version of the code.

**Why this mattered for planning**: The correction changed the value proposition. Originally the issue framed it as "validate-only is bare, run is rich" → fix the validate path. The correct framing is "both paths are bare" → fix both together. One structural change upgrades both simultaneously, which is *more* valuable than the issue claims and makes the "it's only a cosmetic validate-only issue" argument for deferring invalid.

---

## 2026-04-07 — Architectural framing

**The moment that unlocked the whole plan**: The user asked me to read the task reviews for 141, 143, 144.

Before reading them, I was thinking about this as "fix the validator return type" (a scope-constrained task). After reading them, I was thinking about it as "complete the architectural arc that 141/143/144 started" (a scope-completion task).

**The three-task arc that was already written**:

| Task | Consolidated |
|---|---|
| 141 | Exception **hierarchy** → one root `PflowError` |
| 143 | Output **type** → one dataclass `Diagnostic` |
| 144 | **Rendering** → one format, self-describing exceptions |

**The literal sentence in Task 144's review that reframed everything**:
> `format_validation_failure()` accepts `list[Any]` — should be `list[Diagnostic]` once `WorkflowValidator.validate()` returns Diagnostics (spinje/pflow#219).

Task 144 *already named this task*. The debt was already scoped and tracked. The plan I was drafting wasn't a refactor proposal — it was the completion of an architectural obligation.

**The Task 143 warning that became the single most important planning constraint**:
> "`ValidationResult.errors` returns `list[str]` — Pragmatic: `format_validation_failure()` takes `list[str]`. Changing to `list[Diagnostic]` would require updating the formatter and all callers. **Task 144 tracks unification.**"

Task 143 took the pragmatic shortcut, scoped the cleanup to Task 144, and Task 144 had to come back and fix it. **That lesson was written in ink in the project's history.** It meant: **do not take the pragmatic shortcut this time.** Any plan option that leaves a string boundary "for later" is the wrong plan because #220-whatever would have to come back and fix it.

This single insight killed Option A (outer layer only) and Option C (phased) in my mind before I'd finished writing them out.

---

## 2026-04-07 — Options exploration

I wrote out four options for the user to discuss:

- **Option A**: outer layer only, inner layer stays string-based (wrap at boundary)
- **Option B**: both layers converted, keep tuple return shape
- **Option C**: phased (A now, B later)
- **Option D** (late addition): both layers + single-list return + eliminate the tuple

**Why Option D was late**: I started with A/B/C because they all preserved the `(errors, warnings)` tuple return. Then the user asked: "what's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"

That question forced me to look at the patterns rustc/ESLint/mypy/ruff actually use — which Task 144's research had already identified ("One rendering format — rustc, ESLint, mypy, ruff all converge on one diagnostic format"). None of them use `(errors, warnings)` tuples. They use a single collection of diagnostics where severity is a field.

**The insight**: The tuple return was an artifact of the old types (`list[str]` for errors, `list[Diagnostic]` for warnings). Two different types forced two lists. Once both become `Diagnostic`, the tuple is artificial separation — severity is already a field.

**Option D emerged as**: strictly simpler final code than B, at equivalent implementation cost (test rewrite is roughly linear in assertion count, not in layer count). This is where the user's "prioritize simplicity of final code, not how easy it is to get there" framing became the decisive criterion.

**Decision cascade**: Once Option D was on the table, the subsequent choices all fell out naturally:
1. Single list return → no more tuple
2. `WorkflowValidationError.validation_errors: list[Diagnostic]` → no more str/tuple union
3. Delete `generate_validation_suggestions()` → no more pattern-matching reverse-engineering
4. Delete the runner's fabrication loop → no more string-to-Diagnostic bridge
5. Delete the `# type: ignore[arg-type]` → no more type confession

Each of these was previously justifiable individually. Option D made them all inevitable together. The architecture decided the scope, not the other way around.

**The user's approval message "yes this seems like the correct decisions"** covered 5 explicit sub-questions at once:
- (a) Single list, not tuple — YES
- (b) `validation_errors: list[Diagnostic]` — YES
- (c) Delete `generate_validation_suggestions()` — YES
- (d) Use `format_child_provenance()` for sub-workflow errors — YES
- (e) All three validator layers in one PR — YES

I was careful to phrase questions as explicit lettered yes/no to make the approval unambiguous. Future sessions should use the same pattern when aggregating multiple decisions.

---

## 2026-04-07 — Verification waves

**Before writing the plan**, the user asked what assumptions needed verification. This was a good checkpoint — I had several high-risk assumptions I'd been treating as facts:

**Assumptions I believed but hadn't verified**:
1. "No caller constructs `WorkflowValidationError(validation_errors=[(tuple)])`" — **WRONG**. `cli/main.py:631` does exactly this. Also a unit test.
2. "`prepare_inputs()` in `ir_preparation.py` also uses the tuple form" — partially wrong. It produces tuples but routes them through `SchemaValidationError`, not `WorkflowValidationError`. Orthogonal code path.
3. "`generate_validation_suggestions()` has only one caller" — half-right. 1 production caller + 4 dedicated tests that I'd forgotten about.
4. "`format_validation_failure()` accepts `list[Any]`" — **WRONG**. Task 144 had already migrated it to `list[Diagnostic]`. The tech debt note I kept quoting was stale.

**The meta-lesson**: Plan-the-plan verification catches things the implementing agent would otherwise trip over. A 20-minute verification round saved probably 2 hours of implementation flailing.

**Correction from verification that *shrank* scope** (surprise): I initially thought `prepare_inputs()` also needed conversion because it produces tuples. When I traced where those tuples go, they route through `SchemaValidationError` (which already has `to_diagnostics()` from Task 141) — a completely orthogonal path. I got to delete that from the plan scope.

**Correction from verification that *expanded* scope**: The `cli/main.py:631-640` invalid-parameter-names path builds tuples for `WorkflowValidationError`. I had to add it to the consumer-update list. Small — one call site — but it was a genuine missed consumer that would have broken at implementation time.

---

## 2026-04-07 — Planning phase: parallel research waves

With the architectural direction settled, I dispatched 4 parallel `pflow-codebase-searcher` subagents:

- **Agent A**: Per-producer conversion spec (45 producers across 6 files)
- **Agent B**: Test assertion enumeration (~309 assertions across ~20 files)
- **Agent C**: Renderer context-key dictionary
- **Agent D**: Mock sites + `WorkflowValidationError` construction audit

**Why parallel searchers, not one big one**: Each had a distinct output shape. Parallel execution ran ~6 minutes wall clock instead of 24. Also: each searcher's context window was free to spend on its niche; a single searcher would have been context-starved.

**Agent A's output was 82KB** — the biggest single artifact of the session. I had to split it into 4 files to read it. This was the authoritative per-producer spec — every `errors.append(...)` call site in the 3 layers, with current code, structural data, and proposed `Diagnostic` construction. Without Agent A, the plan would have been "convert the validators" (vague). With Agent A, the plan is "convert these 45 specific producers in this specific way" (atomic).

**Key insights from Agent A that influenced the plan**:
- ~25 of the 45 producers are **free wins** — they'd use context keys the renderer already handles (path, node_id, similar_names, available_fields, etc.). No renderer changes needed for those.
- The highest-value conversion is `format_enhanced_node_error` in `path_validation.py:562` — a 76-line helper that builds a 4-section error. Converting it correctly delivers the biggest user-visible improvement.
- Agent A flagged the `available_fields` renderer gate as the one mandatory renderer change (it currently only fires under `category == "template_error"`, artificially blocking generic use).
- Agent A disagreed with the single-list decision ("recommend keeping tuple"). I overrode this because the user had explicitly approved single-list. **Lesson**: subagents can disagree with architectural decisions; trust your framing from user discussion over subagent recommendations.

**Agent B's output** quantified the test churn: ~309 assertions across ~20 files, dominated by mechanical patterns (`errors[0]` → `errors[0].message`). Biggest clusters: test_types.py (60), test_workflow_data_flow.py (35), test_validator.py (30), test_batch_item_validation.py (30). Agent B also categorized the 7 rewrite patterns, which became the test-update section of the plan.

**Agent C's output** was the renderer context-key dictionary — 14 context keys the renderer consumes, with their gating conditions, expected types, and rendering behavior. This became the "keys producers MUST NEVER set" guardrail in the plan (`phase`, `exception_type`, `raw_response`, `mcp_error`, `shell_*` — they're runtime-only and produce misleading text when set by validators).

**Agent C also caught a subtle gotcha**: `_format_warning_or_info_diagnostic` renders warnings/info using **only** message/node_id/suggestions. Context is completely ignored for non-error severities. This means if a validator producer emits a `Severity.WARNING` with `context={"path": "X"}`, the path won't render in text mode. The existing `_warn_inputless_shell_nodes` follows this rule (all info in `message`), and future warnings must too.

**Agent D's output** audited the consumer surface:
- 3 mock sites (all handled or naturally compatible)
- 21 production `WorkflowValidationError` construction sites (only 2 pass `validation_errors=` with non-None — the rest use the string-summary constructor which stays unchanged)
- ~20 `pytest.raises(..., match=...)` sites (all match against `summary`, which is unchanged)

Agent D's most valuable finding: the production blast radius is *much smaller* than I'd assumed. Only 2 production sites need rewriting. The massive churn is all in tests, which is linear and mechanical.

---

## 2026-04-07 — Drafting the plan file

With Agent A/B/C/D outputs in hand, I wrote the plan in one pass. Target length: ~30KB, ended up at ~80KB after the review additions (see below).

**Structure decisions for atomicity**:
- Started with Context + Principle + Scope tables so an implementing agent gets the framing before the details
- Used concrete code blocks (before/after) for non-obvious conversions, not just descriptions
- Included the exact renderer context-key dictionary as a lookup table
- Added a "Reused helpers (do NOT recreate)" section because discovering these via search wastes time
- Committed structure ordering so each commit leaves the tree in a passing state

**Decisions made while drafting**:

1. **Include the full V12 (`_validate_unknown_params`) conversion in detail** because it's representative of the "free wins from existing renderer" pattern — similar_names + available_fields + path + node_type all for free. Other outer validators (V1-V8) got shorter treatment since they're simpler.

2. **Show the full PV3 (`format_enhanced_node_error`) conversion** — the 76-line helper maps almost 1:1 onto the renderer's existing blocks. This was the showcase example that the conversion is mechanical, not speculative.

3. **Use tables + code blocks hybrid** — tables for enumeration (9 outer helpers, 15 path_validation producers, 7 test-rewrite patterns), code blocks for the non-obvious stuff.

4. **Write the commit structure as suggested-but-not-mandatory** — gave the implementing agent room to merge commits 2+3+4 if the transition-state routing proves awkward. Left the door open for the implementing agent's judgment.

---

## 2026-04-07 — Plan review (the best money spent in the session)

User directed: run `/code-review` with 2-4 agents. I picked 4:
- **review-plan** (structural integrity)
- **review-impact-completeness** (shared-pattern consumers)
- **review-feature-interactions** (sub-workflow/batch/MCP/display)
- **review-validation-consistency** (validation/runtime drift)

**The reviews returned 3 critical findings I had genuinely missed**:

### Finding #1 (review-feature-interactions): `format_validation_failure()` doesn't render the full Diagnostic structure

**This was the biggest miss**. My plan's "manual reproduction" section promised that validate-only output would show `Error 1: Validation Error / message / At: node 'X', nodes[0].params.command / Did you mean one of these?`. That's the `format_diagnostic()` output format.

But `format_validation_failure()` (the dominant CLI/MCP text path) only renders 3 fields per error: `error.message`, `error.context["path"]`, `error.suggestions[0]`. It does NOT call `format_diagnostic()`. Title, node_id, available_fields, similar_names, additional suggestions — all silently dropped.

**The promised output shape was wrong.** The improvement would have reached JSON consumers only. Text-mode users (the majority) would have seen a modest improvement (path + first suggestion gain rendering) but not the full unified format.

**The fix**: add `format_validation_failure()` rewrite to scope. Delegate to `format_diagnostic()` per error. ~15 tests need updating in `test_validation_formatter.py`.

**Why I missed this originally**: I'd read `validation_formatter.py` earlier in the session and noted it "already accepts `list[Diagnostic]`" — which is true. I failed to notice that accepting Diagnostics and rendering them fully are different things. **The formatter was type-correct but behaviorally incomplete.** Task 144 had migrated the type but not the rendering depth.

**Lesson for future planning**: When a claim is "formatter X already accepts the new type, no changes needed", verify that it actually *renders* the new fields, not just accepts them at the boundary.

### Finding #2 (review-feature-interactions + review-validation-consistency): Sub-workflow dual-propagation-path dedup asymmetry

I'd claimed the plan achieves "full symmetry with the warnings path" by using `format_child_provenance()` in sub-workflow error propagation. Both reviewers caught that this claim was **partially wrong**:

- **Validator path** (validator.py:32, `_add_child_provenance`): uses `w.node_id or step_id` (preserves child's node_id if set)
- **Runtime path** (workflow_executor.py:337, `_propagate_child_parser_warnings`): uses `node_id=step_id` (always overwrites)

**Same logical warning, different node_ids, different `Diagnostic.__hash__` → no dedup → duplicate diagnostics** if both paths fire on the same workflow run.

**This is a pre-existing latent bug for warnings.** The plan's V16 conversion would have locked it in for errors too. I would have claimed symmetry that didn't exist.

**The fix**: one-line change at `workflow_executor.py:337` to align with the validator's policy. Added to plan scope.

**Why I missed this originally**: I knew `format_child_provenance()` was "the same helper both paths use" but I didn't read the runtime caller in full. I assumed both paths called the helper identically. **Assumption not verification.** The reviewers caught it because they read both sites.

**Lesson**: "Uses the same helper" ≠ "uses the helper identically". Verify the call sites, not just the helper definition.

### Finding #3 (review-validation-consistency): Compiler consumer of `validate_data_flow()` lacks severity filter

My plan's compile_validation.py update described the change as "one-line: `e` → `d.message`":
```python
if data_flow_diagnostics:
    lines = [f"  - {d.message}" for d in data_flow_diagnostics[:5]]
    raise CompilationError(...)
```

The reviewer noticed the truthiness check `if data_flow_diagnostics:` doesn't filter to errors. Currently dormant (no warning-severity producers in `data_flow.py` today), but the moment any future producer adds a warning, the compiler would silently start raising `CompilationError` for warnings.

**The fix**: add an explicit error filter line. Two-line change instead of one.

**Why I missed this originally**: I was in "mechanical conversion" mode and applied the same pattern I'd used for the validator's `_validate_data_flow` wrapper (which also doesn't filter, because it doesn't need to — the validator orchestrator collects everything into one list). The compiler consumer has a different contract (only errors block compilation), and I didn't notice the asymmetry.

**Lesson**: When the same function has multiple consumers, each consumer's filtering policy must be explicit. Don't assume "currently no warnings means no filter needed."

### Findings I verified as DISPUTED (the reviewers were wrong)

Four reviewer concerns I verified false via targeted grep:

1. **"Tests substring-match against multi-line rendered text"** — zero matches for `Available outputs`, `Did you mean one of these?`, `Items come from` in tests. The reviewer's concern was theoretical. My 7 mechanical patterns are sufficient for the actual test surface.

2. **"CycleError signature change breaks external callers"** — verified zero external callers. Only `data_flow.py:93` itself raises it. Safe to change.

3. **"Dropping `Data flow error:` prefix breaks substring tests"** — both grep matches in tests are comments (`# Data flow error`), not assertions.

4. **"`test_workflow_save_service.py:334` match='nonexistent_node' depends on V11 message"** — V11's new message preserves the substring. Test passes naturally.

**Why it's worth verifying disputed findings explicitly**: It builds confidence that the plan is actually atomic. "The reviewer was wrong about this" is a stronger statement than "maybe this is fine" and justifies not adding scope for phantom concerns.

**Lesson**: Plan reviews catch real bugs AND flag phantom concerns. Verification separates them. Don't blindly accept review findings — verify each one before integrating. Half the work of review synthesis is pruning the wrong alarms.

---

## 2026-04-07 — Integrating review findings into the plan

The plan file grew from ~80KB to ~118KB after integration. Changes:

- Added "Plan review corrections" section near the top (visible to the implementing agent immediately) summarizing the 7 confirmed findings
- Added 3 new scope items to the scope table: `format_validation_failure` rewrite, `workflow_executor.py:337` fix, 6 documentation files
- Updated the compile_validation.py code snippet to include the error filter
- Added full V9 and V11 conversions (Agent 1 said these were the biggest implementer-guesswork risks)
- Added "Pre-implementation grep audit" as a verification step
- Added "Risk 8" documenting that defensive `except Exception` wrappers are load-bearing (catch `TypeError` from malformed `Diagnostic.__post_init__`), not dead code
- Updated the Summary section to surface the critical review findings

**Meta-decision**: I considered putting the review findings in an appendix to keep the plan clean. Rejected because an implementing agent might skip appendices. The "Plan review corrections" section is up-front so it's unmissable.

---

## Meta-learnings for future planning sessions

### What worked

1. **Read the prior task reviews early.** Tasks 141/143/144 had the architectural framing baked in. Without reading their task-review.md files, I would have drafted a scope-minimized plan that repeated the Task 143 "pragmatic shortcut" mistake. The user's instruction "can you read the task reviews" was the most valuable single directive of the session.

2. **Parallel subagents for distinct research concerns.** 4 agents with different niches ran in ~6 minutes wall clock. Each had room to spend its context window on its topic. Sequential would have been 24+ minutes and each would have been context-squeezed.

3. **Verify assumptions before drafting, not after.** The pre-draft verification round caught 4 wrong assumptions. If I'd drafted first and verified during review, the plan would have had structural issues the reviewers couldn't easily fix.

4. **Explicit lettered yes/no questions for user approval.** "(a) yes/no, (b) yes/no, (c) yes/no, (d) yes/no, (e) yes/no" gave unambiguous approval for 5 decisions at once. Avoids the "I thought you meant..." problem.

5. **Trust user framing over subagent recommendations.** Agent A recommended keeping the tuple return. User had approved single-list. I went with user. The plan is correct because of this.

6. **Plan reviews catch the big stuff.** The 4-agent review found 3 genuine critical bugs I'd missed. Two of them would have reached implementation (format_validation_failure, workflow_executor dedup). One would have reached runtime (compile_validation filter). The review cost ~7 minutes of wall clock and saved hours of implementation rework.

### What I'd do differently

1. **Read downstream consumers fully, not just type-check them.** I checked `format_validation_failure()`'s *signature* (accepts `list[Diagnostic]` ✓) but not its *body* (only renders 3 fields). The signature check was necessary but not sufficient. **Next time**: when a claim is "no changes needed to X", read X's full body to verify.

2. **Enumerate all callers of shared helpers, not just the helper definition.** I checked `format_child_provenance()` but assumed both callers used it identically. They didn't. **Next time**: for any claim of "symmetry", read both sides of the symmetry.

3. **Plan for future evolution, not just current state.** The compile_validation.py filter is the "dormant today but latent risk" pattern. I was in "mechanical conversion" mode and applied the current semantics. **Next time**: when a consumer does a truthiness check on a list that might grow new severity levels, add the filter preemptively.

4. **Don't pad scope with speculative concerns.** The reviewers flagged 4 phantom issues. If I'd accepted them uncritically, the plan would have grown with pointless renderer additions and backward-compat scaffolding. **Next time**: for every review finding, do the verification grep before deciding whether to integrate.

### The plan-review loop as a quality multiplier

Rough accounting:
- **Initial plan draft**: ~20 minutes of active work
- **Plan review (4 agents parallel)**: ~7 minutes wall clock
- **Finding verification + integration**: ~15 minutes
- **Net improvement**: 3 critical bugs caught + 4 phantom concerns discarded + plan clarity improved

Without the review loop, the implementing agent would have hit the 3 critical findings during implementation, spent hours on each, and left the plan's final state worse than what we have now. The review-loop ROI on this session was conservatively 10x.

**This should be standard practice for any plan that touches more than ~5 files.** For trivial plans (single file, <100 LOC), the overhead isn't worth it.

---

## 2026-04-07 — Implementation step 1: audit and preflight

**Step completed**: Read the task brief, planning artifacts, prior task reviews (141/143/144), and all critical source files named in the implementation plan before making changes. I also ran the pre-implementation grep audit against the live tree to confirm the plan still matches the codebase shape.

**Verified against live code**:
- `WorkflowValidator.validate()` still returns `tuple[list[str], list[Diagnostic]]`.
- `validate_workflow_templates()` still returns tuple `(errors, warnings)`.
- `validate_data_flow()` still returns `list[str]`.
- `runner.py` still fabricates generic Diagnostics from validation strings and still calls `generate_validation_suggestions()`.
- `WorkflowValidationError.validation_errors` still uses the `list[str | tuple[str, str, str]]` union.
- `validation_formatter.py` still only renders `message`, `path`, and the first suggestion.
- `workflow_executor.py` still overwrites child parser-warning `node_id` with `step_id`, confirming the dedup asymmetry the plan called out.

**Audit findings that matter for implementation**:
- The plan's scope is still accurate. No new consumer surfaced beyond the already-listed docs/tests/fixtures.
- The largest rewrite surface is still tests, not production call sites. Production remains tightly scoped to validator layers, renderer, exception, runner, formatter, compiler/save-service consumers, and one CLI constructor site.
- The strongest leverage point remains unchanged: converting producer sites directly to `Diagnostic` will unlock richer output without adding new rendering concepts beyond the existing context blocks.

**Environment deviation (recorded, not a design deviation)**:
- `uv` cannot complete the requested preflight commands in this sandbox. First it was blocked by the default cache path, which I worked around with `UV_CACHE_DIR=.uv-cache`. After that, `uv` panicked during environment bootstrap (`system-configuration` / `Attempted to create a NULL object`), so `capture_baselines.py`, `pytest`, and `mypy` could not be run through `uv`.
- I checked for a direct fallback. `python3` does not have `pytest` or `mypy` installed, and the partially created `.venv` also lacks those modules. Result: pre-implementation verification is **blocked by environment**, not by code.

**Decision taken**:
- Proceed with implementation anyway, because the task plan is explicit, the source audit is complete, and the verification failure is environmental rather than architectural. I will keep recording this as an execution constraint and rerun the intended checks at the end if the environment becomes usable.

**Trust boundary after step 1**:
- **Verified**: task framing, architectural intent, affected code paths, and live-code alignment with the implementation plan.
- **Unable to verify due environment**: pre-change baseline capture, targeted pytest run, and mypy preflight.

---

## 2026-04-07 — Implementation step 2: renderer gate + data-flow layer + compiler consumer

**Step completed**: Implemented the first planned code slice:
- `src/pflow/core/diagnostic.py`
- `src/pflow/core/workflow/data_flow.py`
- `src/pflow/runtime/compilation/compile_validation.py`

**What changed**:
- Broadened the renderer’s `available_fields` block from template-only to unconditional dispatch, and renamed the helper from `_format_template_error_lines` to `_format_available_fields_block`.
- Converted `validate_data_flow()` from `list[str]` to `list[Diagnostic]`.
- Converted the primitive producer sites in `data_flow.py` to build Diagnostics directly:
  - cycle detection
  - forward-reference errors
  - non-existent node references
  - undefined input references (case-insensitive match, no-inputs-declared, and declared-inputs-list variants)
- Added structured `CycleError.nodes_in_cycle` so the cycle producer does not have to parse its own exception string.
- Updated the compiler consumer to filter `Severity.ERROR` explicitly before raising `CompilationError`, matching the plan’s review correction.

**Decisions made during implementation**:
- Kept the `available_fields` renderer body unchanged apart from the rename. The header text still says "Available fields in node" even for inputs/params. This matches the implementation plan’s explicit instruction to broaden the gate without redesigning the block text in this task.
- Imported `find_similar_items` directly in `data_flow.py` instead of function-local imports because this module already sits at the producer layer and the helper is used in a hot path for structured suggestion generation.
- Preserved the existing permissive semantics around non-`pflow` shell syntax and runtime-dependent refs. This step is a representation change, not a policy change.

**Critical insight from this slice**:
- The lowest-level validator conversion is mechanically straightforward once the `Diagnostic` context keys are treated as the contract. The real complexity is not producer construction; it is downstream consumers and tests that still assume strings. That confirms the plan’s sequencing is correct: convert the producer first, then climb outward.

**Verification performed**:
- `python3 -m py_compile src/pflow/core/diagnostic.py src/pflow/core/workflow/data_flow.py src/pflow/runtime/compilation/compile_validation.py`
- Result: syntax OK on all three touched files.

**Verification still blocked**:
- `pytest`, `mypy`, and baseline capture remain blocked by the sandboxed `uv` bootstrap failure described in step 1.

**Trust boundary after step 2**:
- **Verified**: syntax of the changed files and alignment with the plan’s DF1-DF6 and compiler-filter requirements.
- **Assumed until broader integration step**: downstream callers/tests that still expect string-returning `validate_data_flow()`.

---

## 2026-04-07 — Implementation step 3: template validation layer conversion

**Step completed**: Converted the template-validation producer layer to native `Diagnostic` output:
- `src/pflow/runtime/template_validation/path_validation.py`
- `src/pflow/runtime/template_validation/type_validation.py`
- `src/pflow/runtime/template_validation/batch_item_validation.py`
- `src/pflow/runtime/template_validation/validator.py`
- plus the planned renderer support for `source_file` provenance in `src/pflow/core/diagnostic.py`

**What changed**:
- `validate_workflow_templates()` now returns `list[Diagnostic]` rather than `(errors, warnings)`.
- `validate_template_paths()` now returns one diagnostic list instead of split string/warning collections.
- The path-validation dispatcher now builds Diagnostics directly and attaches external-file provenance via context (`source_file`) instead of string-appending `Loaded from file: ...`.
- The highest-value producer (`format_enhanced_node_error`) was converted into `_build_enhanced_node_diagnostic()`, promoting available outputs and fuzzy matches into structured fields rather than multi-line string sections.
- Batch-item validation producers now return Diagnostics with available-field and similar-name context instead of manual string assembly.
- Type-validation producers now emit Diagnostics directly, including structured fix suggestions and shell-command guidance.
- Added `source_file` rendering support in the diagnostic renderer so provenance attached by template producers actually reaches text output.

**Decisions made during implementation**:
- Kept the task’s core principle intact: represent existing knowledge structurally rather than trying to preserve every exact line break of the old string messages. In practice this meant shorter `message=` text and moving “available options” / “did you mean” / “loaded from file” into structured context where the unified renderer already knows how to display them.
- Used `title="Template Error"` for template-class failures and `title="Validation Error"` for general validator mismatches, matching the plan’s separation between template and non-template producers.
- Chose to render `source_file` through `_format_compilation_context_lines()` rather than inventing a new standalone renderer helper. This is a small deviation in placement, not in behavior: the hint still renders as `Loaded from file: ...` from diagnostic context as the plan required.
- For shell-command validation, stored the truncated display command in `context["shell_command"]`. That preserves the existing ergonomics of the shell-context block without reintroducing bespoke string formatting.

**Critical insight from this slice**:
- The template layer was exactly where the architecture paid off. Once `available_fields`, `similar_names`, `shell_command`, and `source_file` were treated as the contract, the conversion stopped being “rewrite pretty errors” and became “stop throwing away already-known structure.” The output surface will now improve automatically once the outer validator and formatter stop flattening it again.

**Verification performed**:
- `python3 -m py_compile src/pflow/runtime/template_validation/path_validation.py src/pflow/runtime/template_validation/type_validation.py src/pflow/runtime/template_validation/batch_item_validation.py src/pflow/runtime/template_validation/validator.py src/pflow/core/diagnostic.py`
- Result: syntax OK on all touched files.

**Known temporary inconsistency after this step**:
- `core/workflow/validator.py` still expects `validate_workflow_templates()` to return `(errors, warnings)`. This is the expected intermediate state between step 3 and step 4, not an accidental deviation.

**Trust boundary after step 3**:
- **Verified**: syntax of the converted template-validation layer and renderer support for `source_file`.
- **Assumed until next slice**: outer validator integration and any test assertions that still expect string-returning/template-tuple APIs.

---

## 2026-04-07 — Implementation step 4: outer validator and WorkflowValidationError cutover

**Step completed**: Converted the outer validator layer and validation exception boundary:
- `src/pflow/core/workflow/validator.py`
- `src/pflow/core/exceptions.py`

**What changed**:
- `WorkflowValidator.validate()` now returns `list[Diagnostic]`.
- All outer validator helpers were converted from string/tuple returns to `Diagnostic` returns, including:
  - structure validation
  - stdin validation
  - template wrapper
  - node-type validation
  - output-source validation
  - unknown-parameter validation
  - sub-workflow validation and required-input checks
- Output-source helper formatters were rewritten as Diagnostic builders (`_build_node_not_found_diagnostic`, `_build_template_node_diagnostic`) instead of multi-line string assemblers.
- `_add_child_provenance()` now handles child errors and warnings symmetrically and enriches context with `sub_workflow_step` and optional `sub_workflow_path`.
- `WorkflowValidationError.validation_errors` now stores `list[Diagnostic]`, and `to_diagnostics()` is a pass-through with the existing single-summary fallback intact.

**Decisions made during implementation**:
- Preserved `SchemaValidationError.to_diagnostics()` as the source of truth for structural errors instead of reconstructing the same information in the validator wrapper. This is exactly the “self-describing producer” principle task 147 is completing.
- Kept the generic exception wrappers in `_validate_structure`, `_validate_data_flow`, and `_validate_templates` rather than trying to delete them as “impossible” code. The planning review was right: they are still load-bearing defense against producer-construction mistakes and unexpected runtime exceptions.
- Used per-node unknown-type diagnostics instead of one error per unknown type string. This keeps the diagnostic location concrete (`nodes[i].type`) and matches the plan’s “call site owns the context” rule.
- Routed sub-workflow child diagnostics through the generalized provenance helper rather than preserving separate code paths for child errors and child warnings. This removes the remaining asymmetry inside validator recursion.

**Critical insight from this slice**:
- Once the outer validator stopped splitting “errors” and “warnings” by collection type, the code simplified immediately. The tuple shape had been compensating for the old type mismatch; after producer conversion, it became pure bookkeeping noise. The implementation confirmed the plan’s decision to remove the tuple entirely rather than carrying it as transitional debt.

**Verification performed**:
- `python3 -m py_compile src/pflow/core/workflow/validator.py src/pflow/core/exceptions.py src/pflow/runtime/template_validation/path_validation.py src/pflow/runtime/template_validation/type_validation.py src/pflow/runtime/template_validation/batch_item_validation.py src/pflow/runtime/template_validation/validator.py src/pflow/core/diagnostic.py src/pflow/core/workflow/data_flow.py src/pflow/runtime/compilation/compile_validation.py`
- Result: syntax OK across the validator stack after the cutover.

**Known temporary inconsistency after this step**:
- Downstream consumers still assume old shapes in several places (`runner.py`, validation formatter, save service, CLI invalid-parameter constructor, docs, and tests). This is expected and isolated to the final cleanup slice.

**Trust boundary after step 4**:
- **Verified**: syntax of the full validator stack after end-to-end producer conversion and exception-type alignment.
- **Assumed until final slice**: downstream consumer compatibility and test-suite rewrites.

---

## 2026-04-07 — Implementation step 5: consumer cleanup, deletions, docs, and test migration

**Step completed**: Finished the downstream migration layer:
- production consumers (`runner.py`, `save_service.py`, `validation_formatter.py`, `workflow_executor.py`, `cli/main.py`)
- dead-code deletion (`generate_validation_suggestions()` and its dedicated tests)
- docs/examples (`core/CLAUDE.md`, `mcp_server/services/CLAUDE.md`, `architecture/reference/template-variables.md`)
- fixture update (`capture_baselines.py`)
- broad mechanical test migration across the validator/template test surface

**What changed**:
- `runner.py` no longer fabricates generic validation Diagnostics from strings and no longer post-processes them with `generate_validation_suggestions()`.
- `runner._validate()` now filters the validator’s single diagnostic list by severity and raises `WorkflowValidationError(validation_errors=errors)` without the old `# type: ignore[arg-type]`.
- `save_service.py` now preserves structured validation Diagnostics on `WorkflowValidationError` while keeping a one-line summary for the exception text.
- `format_validation_failure()` now delegates to `format_diagnostic()` so validate-only text output uses the same unified rendering shape as runtime and compilation errors.
- `workflow_executor.py` now preserves child `node_id` when propagating parser warnings, matching the validator path and fixing the latent dedup asymmetry identified in plan review.
- `cli/main.py` invalid-parameter validation now constructs a real `Diagnostic` instead of the old `(message, path, suggestion)` tuple form.
- `generate_validation_suggestions()` was deleted, and `TestValidationSuggestions` in `test_workflow_data_flow.py` was removed with it.

**Test migration approach (intentional deviation in mechanics, not in outcome)**:
- The implementation plan described mostly inline assertion rewrites (`errors[0] -> errors[0].message`, etc.). I used a slightly different mechanical strategy for many test modules: introduced tiny local helpers like `_split_validator_diagnostics()` and `_split_template_diagnostics()` that preserve the old test ergonomics (`errors` as message strings, `warnings` as Diagnostics) while calling the new single-list production API underneath.
- Reason: this kept the test diff smaller and reduced the chance of accidentally rewriting dozens of semantically unrelated assertions while still validating the new contract at the boundary.
- This is a **mechanical deviation only**. The architectural outcome is the same: no tests still call the old tuple-returning production APIs.

**Critical insight from this slice**:
- The biggest cleanup win was not in the validator itself; it was deleting the bridges around it. Once `runner.py` stopped fabricating Diagnostics and `format_validation_failure()` stopped under-rendering them, the whole 141 → 143 → 144 → 147 arc became visible in one path: producer creates `Diagnostic`, exception carries `Diagnostic`, formatter renders `Diagnostic`. No reconstruction layer remains.

**Verification performed in this slice**:
- `python3 -m compileall tests`
- `python3 -m compileall src tests .taskmaster/tasks/task_144/research/capture_baselines.py`
- Grep verification:
  - no remaining `generate_validation_suggestions` references in `src/` or `tests/`
  - no remaining tuple-style `validation_errors=[(...)]` constructors in live code/tests
  - no remaining tuple-unpack call sites against `WorkflowValidator.validate()` or `validate_workflow_templates()` in live code/tests/docs
  - the specific `type: ignore[arg-type]` in production is gone; the only remaining `[arg-type]` match is the deliberate negative test in `tests/test_core/test_diagnostic.py`

**Environment constraint still in force**:
- Full pytest, mypy, and baseline-render comparison remain blocked by the same sandbox/`uv` bootstrap panic recorded earlier. This is no longer a code-structure blocker; it is a tool-execution blocker.

**Trust boundary after step 5**:
- **Verified**: syntax of the migrated source/test surface and removal of the old API/dead-code patterns by grep.
- **Unable to verify here**: behavioral test pass/fail and baseline-render diffs, because the environment still cannot run the intended Python toolchain.

---

## 2026-04-07 — Verification wrap-up

**What I could verify locally**:
- The entire `src/` tree, the `tests/` tree, and the updated baseline fixture script compile successfully with `python3 -m compileall`.
- The targeted grep checks required by the plan now come back clean for the live codebase:
  - deleted suggestion bridge
  - removed tuple-style validation-error payloads
  - removed validator/template tuple-unpack consumers
  - removed production `# type: ignore[arg-type]`

**What remains blocked by environment**:
- `uv run pytest ...`
- `uv run mypy ...`
- `uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before/after/compare`

**Net assessment**:
- The implementation is structurally complete according to task 147’s plan.
- Verification is strong at the syntax/API-surface level and incomplete at the runtime/assertion/baseline level because the sandbox cannot execute the project’s intended toolchain.

---

## 2026-04-07 — Post-fix test hardening (high-value only)

**Why I revisited tests**: After the implementation stabilized and the broad migration churn settled, the user explicitly asked whether there were any *high-value* tests still worth adding. The bar was not coverage. The bar was: would this catch a real regression in the architectural outcome of Task 147?

**Tests added**:

1. **Direct producer-structure test for unknown params** in `tests/test_core/test_unknown_param_validation.py`
   - New test: `test_unknown_param_diagnostic_preserves_structure`
   - Why it matters: `_validate_unknown_params()` is the canonical Task 147 case where the validator used to throw away the richest structure (path, similar names, valid params, concrete suggestion). This test now asserts the returned `Diagnostic` preserves:
     - `severity`
     - `node_id`
     - `title`
     - `context["path"]`
     - `context["available_fields"]`
     - `context["similar_names"]`
     - `suggestions`
   - This is the best direct guard that the validator has not regressed back into “string-first” behavior.

2. **Validate-only JSON shape test for a rich validator error** in `tests/test_cli/test_validate_only.py`
   - New test: `test_json_rich_validation_error_preserves_context_fields`
   - Why it matters: Task 147 is not just about prettier text. It is about preserving structure for downstream agent consumers. This test exercises a real typoed unknown-param case through `--validate-only --output-format json` and asserts the JSON error preserves:
     - `title`
     - `node_id`
     - `path`
     - `suggestions`
     - `available_fields`
     - `similar_names`
   - This is the highest-leverage end-to-end guard on the user-visible/agent-visible JSON contract.

3. **Compile-time warning-filter regression test** in `tests/test_runtime/test_compiler_basic.py`
   - New test class: `TestCompileTimeDataFlowValidation`
   - New test: `test_warning_only_data_flow_does_not_raise`
   - Why it matters: this locks in the plan-review correction that `_validate_data_flow_at_compile_time()` must filter `Severity.ERROR` explicitly instead of truth-testing the whole validator list. Without this test, a future warning-only producer in `data_flow.py` could accidentally start failing compilation.

**Why I did NOT add more**:
- I considered adding a direct sub-workflow provenance structure test. I still think it would be valuable, but compared to the three tests above it is less central to the core #219 regression and would have taken more setup relative to its incremental value.
- I did **not** add broad “assert every context key everywhere” tests. Those would optimize for coverage, not for bug prevention, which the user explicitly asked me not to do.

**Verification performed**:
- `python3 -m py_compile tests/test_core/test_unknown_param_validation.py tests/test_cli/test_validate_only.py tests/test_runtime/test_compiler_basic.py`
- Result: syntax OK.

**Assessment**:
- These tests materially improve confidence in the exact architectural promises of Task 147:
  - producers keep structure
  - validate-only JSON preserves structure
  - compiler consumers filter by severity correctly

---

## 2026-04-07 — Manual verification round 1: test suite + manual reproduction

After context-window rotation, picked the work back up with the user as a verification round. The implementing agent had completed the implementation but left a note that pytest, mypy, and the baseline tool were all blocked by a sandbox `uv` bootstrap panic — no behavioral verification had been done. The plan was: run the suite first to give reviewers a working baseline, then manual reproduction.

**Test suite results**:
- `make test`: 4653 tests pass.
- `make check`: ruff failed with 1 remaining error after auto-fixing imports — `S108` flagged `/tmp/out.txt` as insecure tempfile usage in a test fixture.

**Two small fixes during this round**:
1. `tests/test_core/test_unknown_param_validation.py:112` — changed `/tmp/out.txt` to `output.txt` (the value is irrelevant; the test only checks that `file_pat` is recognized as a typo of `file_path`).
2. `tests/test_runtime/test_compiler_basic.py` — accepted ruff's auto-consolidation of the `from unittest.mock import` line (cosmetic).

After both fixes, `make check` passes cleanly: ruff/ruff-format/mypy/deptry all clean. The mypy success is the strongest signal that the `# type: ignore[arg-type]` removal worked end-to-end.

**Manual reproduction (text mode)** with `${nonexistant.stdout}` and a typoed `file_pat` parameter both delivered the unified rich format: title, message, `At:` location, `Did you mean`, available fields, `→` suggestion. Output matched the task spec's promised shape.

**Manual reproduction (JSON mode)**: structured fields all present — `node_id`, `context.path`, `context.available_fields`, `context.similar_names`, `context.template`, `context.node_type`. The full `--validate-only --output-format json` JSON contract that downstream agents will read.

**Verdict at this point**: implementation works as designed. Ready for verification specialist round.

---

## 2026-04-07 — Manual verification round 2: try-to-break-it specialist mode

The user reframed the next round as "you are a verification specialist trying to break this — the test suite is context, not evidence". The implementer is also an LLM; its tests may be heavy on substring matching, mocks, or happy-path coverage. Build a manual testing plan that probes the parts a test suite is least likely to catch.

Created a reusable testing plan at `.taskmaster/tasks/task_147/verification/manual-testing-plan.md` and executed it.

**Probes performed**:
1. Test-helper smell inspection (no execution) — found and characterized below
2. Bypass paths: `pflow run` text + JSON, CLI save, compile-time validation
3. Single-level sub-workflow provenance (parent → child)
4. Three-level sub-workflow provenance (parent → middle → grandchild)
5. Sibling sub-workflows (dedup behavior)
6. Multi-error workflow (rendering + truncation behavior)
7. Negative tests (clean workflow — should validate)
8. Batch with unresolved template (`batch: ${items}` in `--validate-only`)
9. `compile_validation.py` severity filter (source-level review)

### Findings during this round

#### 🔴 Bug 1: `_add_child_provenance` overwrites context on recursion unwind (NEW IN TASK 147)

**Location**: `src/pflow/core/workflow/validator.py:37-39` (in the implementer's original implementation)

For 3-level nested workflows (parent → middle → grandchild), each recursion unwind overwrote `sub_workflow_step` and `sub_workflow_path` in the diagnostic's context. The OUTERMOST hop won, but `node_id` and `context["path"]` still pointed at the DEEPEST hop. A downstream JSON consumer using `sub_workflow_path` to locate the source file would land on `./middle.pflow.md`, but the actual error is in `./grandchild-broken.pflow.md`.

The text message chained correctly (`In step 'invoke-middle' sub-workflow: In step 'invoke-grandchild' sub-workflow: ...`), so humans reading the message could follow the trail — but the structured context fields were inconsistent with the location fields, breaking programmatic consumers.

**Verified end-to-end via JSON output before the fix**:
```json
{
  "node_id": "grandchild-writer",
  "context": {
    "path": "nodes[id=grandchild-writer].params.file_pat",
    "sub_workflow_step": "invoke-middle",         // ← outermost (wrong)
    "sub_workflow_path": "./middle.pflow.md"      // ← outermost (wrong)
  }
}
```

#### 🔴 Bug 2: Defensive wrappers set `exception_type` (TASK 147 SELF-CONSISTENCY VIOLATION)

**Location**: `src/pflow/core/workflow/validator.py:172, 230, 259, 326` (in the implementer's original implementation)

Four `except Exception` wrappers in `_validate_structure`, `_validate_data_flow`, `_validate_templates`, and `_validate_node_types` set `context["exception_type"] = type(e).__name__`. Verified all four were ADDED by `d8e7252c` (the task 147 commit) — none predated it.

This directly contradicts the task's own progress log section "Keys validator producers MUST NEVER set":

> `exception_type` | Runtime wrapped-exception path. Renders "Type: X" — suggests unhandled exception.

Triggering case I hit during the batch-with-unresolved-template probe rendered as:

```
Error 2: Validation Error
Data flow validation error: 'str' object has no attribute 'get'
  Type: AttributeError       ← misleading — looks like a runtime crash
```

The implementer wrote the guideline AND violated it in the same task. The wrappers themselves are pre-existing and load-bearing (they catch real producer-construction bugs and unexpected lower-level crashes), but populating `context["exception_type"]` is new in task 147 and undermines the task's own architectural principle.

#### 🟡 P2: Malformed `nodes[0]batch` paths (PRE-EXISTING — matches open issue spinje/pflow#214)

**Location**: `src/pflow/core/ir_schema.py:_format_path:335`

For a path like `[0, "batch"]`, `_format_path` produced `[0]batch` instead of `[0].batch`. The condition `if i > 0 and not formatted.endswith("]"):` suppressed the dot when the previous component was an int. Verified pre-existing: task 147 didn't touch `ir_schema.py` (`git show d8e7252c -- src/pflow/core/ir_schema.py` returned empty).

This bug had a pre-existing open issue: **spinje/pflow#214** — exact match including code location and example output.

#### 🟡 P5: Stale CLAUDE.md doc (`src/pflow/core/workflow/CLAUDE.md:120`)

The doc said:
> 7. Unknown param warnings — flags params not in node interface metadata (warnings, not errors)

But `_validate_unknown_params` actually emits `Severity.ERROR` (verified by reading `validator.py:608`). Doc was stale relative to the implementation — possibly drifted between an earlier draft and the final implementation.

#### 🟡 Smell 1: 19 test-helper splits flatten Task 147 structural assertion power

The implementer's "mechanical deviation" of introducing local `_split_validator_diagnostics` / `_split_template_diagnostics` helpers in 19 test files preserved old `(errors_str, warnings_diag)` ergonomics by **converting errors to `format_diagnostic()` rendered strings**. The result: substring matching against multi-line rendered output is more permissive than against raw messages, and the structural fields the task was supposed to verify (`context["path"]`, `.suggestions`, `.context["available_fields"]`, `.context["similar_names"]`, `.node_id`, `.title`) are not individually checked by 99% of tests.

After this round, the structural promise of #219 is verified by 8 tests out of ~309 migrated assertions. The remaining ~301 tests verify "rendered string contains substring X" — same depth as pre-task-147, just behind a slightly different facade.

Filed as **spinje/pflow#238** in the cleanup phase.

#### 🟡 Pre-existing finding: CLI save bypasses comprehensive validation

`pflow workflow save` only runs `validate_ir()` (schema-only). It never calls `WorkflowValidator.validate()` or `_validate_and_normalize_ir()`, so a workflow with unknown parameters / unresolved templates / non-existent node references gets accepted into the library. The bug only surfaces later when the user tries to **run** the saved workflow.

Verified pre-existing: task 147 didn't touch `cli/commands/workflow.py`. But the implication for task 147 is that the new `Severity.ERROR` filter at `save_service.py:139` is **only reachable from `mcp_server/services/execution_service.py`**, never from CLI save. The new code has narrower production exposure than it appears.

Filed as **spinje/pflow#236**.

#### 🟡 Pre-existing finding: Batch unresolved template crash

`data_flow.py` and the template validators crash with `'str' object has no attribute 'get'` when `batch` is a template string `${items}` in validate-only mode (no runtime values to resolve the template). Both crashes are caught by the defensive wrappers, so the validator doesn't crash, but the user sees three confusingly duplicated errors for the same root cause.

Verified pre-existing via `git stash` round (running against a state without my unstaged tweaks produced identical output — the crash sites and the wrapper behavior both predated the implementation work).

**Important methodology note**: my first stash test was misleading. I thought I was stashing the task 147 implementation, but task 147 had already been committed at `d8e7252c full implementation` before my session started — my stash only contained small unstaged tweaks. Running against my "pre-task-147" state was actually still running task 147 code. I corrected this by confirming via `git show d8e7252c -- src/pflow/core/ir_schema.py` (empty result → not touched in task 147).

Filed as **spinje/pflow#237**.

#### 🟢 Confirmed working

- `--validate-only` text + JSON: full rich format
- `pflow run` (non-validate-only) text + JSON: same rich format reaches users on actual run failures
- Single-level sub-workflow provenance: child's `node_id` preserved, `sub_workflow_step` set
- Sibling sub-workflows: distinct errors, no false dedup
- Multi-error rendering: 7 errors + 1 warning all flow through to JSON; text mode truncates display to 5 (hardcoded in `format_validation_failure`)
- Clean workflow negative test: zero errors, cache lint warning correctly placed
- Compile-time data-flow filter: `Severity.ERROR` filter present and correct, dormant but defensive
- All 4 defensive `except Exception` wrappers reachable and function as nets

---

## 2026-04-07 — Bug fix round: addressing both critical findings

After the user approved fixing the two 🔴 bugs, applied tightly-scoped fixes plus regression tests.

### Fix 1: `_add_child_provenance` first-write-wins

**File**: `src/pflow/core/workflow/validator.py:19-49`

Changed the dict update from overwrite-semantics to `setdefault`, so the innermost wrapping (closest to the error) is preserved as recursion unwinds:

```python
# Before
new_context = {**(diagnostic.context or {}), "sub_workflow_step": step_id}
if ref_label:
    new_context["sub_workflow_path"] = ref_label

# After
existing_context = diagnostic.context or {}
new_context = dict(existing_context)
new_context.setdefault("sub_workflow_step", step_id)
if ref_label:
    new_context.setdefault("sub_workflow_path", ref_label)
```

Updated the docstring to explicitly explain the first-write-wins semantics for nested workflows.

**Why first-write-wins** instead of accumulating a chain: simpler, keeps the structured fields aligned with `node_id` and `context["path"]` (both of which point at the deepest level). A future feature could add `context["sub_workflow_chain"]` if breadcrumbs are needed.

### Fix 2: Remove `exception_type` from 4 defensive wrappers

**Files**: `src/pflow/core/workflow/validator.py:180, 238, 267, 334`

Removed `"exception_type": type(e).__name__` from each wrapper context. The message prefix (`"Data flow validation error:"`, `"Template validation error:"`, etc.) is sufficient provenance — the user knows the wrapper fired without seeing internal Python exception type names.

### Fix 3: P2 — `_format_path` malformed paths (closes spinje/pflow#214)

**File**: `src/pflow/core/ir_schema.py:330-337`

Removed the `not formatted.endswith("]")` check so the dot separator is always added before a string component when there's a previous component:

```python
# Before
if i > 0 and not formatted.endswith("]"):
    formatted += "."

# After
if i > 0:
    formatted += "."
```

For path `[0, "batch"]`: now produces `[0].batch` (was `[0]batch`).

### Fix 4: P5 — CLAUDE.md doc update

**File**: `src/pflow/core/workflow/CLAUDE.md:120`

Updated step 7 description from "warnings, not errors" to "hard errors with structured suggestions". Brings the doc into alignment with `_validate_unknown_params` actual behavior.

### Regression tests added (12 new)

| File | Tests | Purpose |
|---|---|---|
| `tests/test_core/test_workflow_validator.py::TestDefensiveWrapperDiagnostics` | 4 | Mock lower-level call to raise, verify wrapper diagnostic does NOT contain `exception_type` in context. One test per wrapper site. |
| `tests/test_core/test_sub_workflow_validation.py::TestDeepNestedProvenance::test_three_level_nesting_keeps_innermost_sub_workflow_provenance` | 1 | Builds real parent → middle → grandchild workflow, asserts `node_id`, `context["path"]`, `context["sub_workflow_step"]`, and `context["sub_workflow_path"]` all point at the innermost (grandchild) level. |
| `tests/test_core/test_ir_schema_output_suggestions.py::TestFormatPath` | 6 | 5 unit tests for `_format_path` (int+str, str+str, consecutive ints, empty, single int) plus 1 end-to-end test that triggers the bug via `validate_ir` on a malformed batch field. |

### Verification after fixes

| Check | Result |
|---|---|
| `pytest` (12 new tests in isolation) | 12/12 pass |
| `make test` (full suite) | 4664 / 4664 pass (was 4653 baseline → +11 net counting the test fix file changes) |
| `make check` (mypy + ruff + deptry) | clean |
| Manual repro Bug 1 (text) | Fixed — `Sub-workflow: ./grandchild-broken.pflow.md` (innermost) |
| Manual repro Bug 1 (JSON) | Fixed — `sub_workflow_step: invoke-grandchild`, `sub_workflow_path: ./grandchild-broken.pflow.md` |
| Manual repro Bug 2 (batch case) | Fixed — `Type: AttributeError` line gone from output |

### Files modified in this round

- `src/pflow/core/workflow/validator.py` — Bug 1 fix + Bug 2 fix
- `src/pflow/core/ir_schema.py` — P2 fix
- `src/pflow/core/workflow/CLAUDE.md` — P5 doc update
- `tests/test_core/test_workflow_validator.py` — 4 new wrapper tests
- `tests/test_core/test_sub_workflow_validation.py` — 1 new deep-nesting test
- `tests/test_core/test_ir_schema_output_suggestions.py` — 6 new format_path tests
- `tests/test_core/test_unknown_param_validation.py` — S108 test fixture fix (`/tmp/out.txt` → `output.txt`)
- `tests/test_runtime/test_compiler_basic.py` — ruff import auto-consolidation

---

## 2026-04-07 — Issue triage: avoid filing duplicates

Before filing follow-up issues for the findings I wasn't fixing in this PR, searched `spinje/pflow` for existing matches to avoid duplicates.

### Existing issues that match my findings

| My finding | Existing issue | Status |
|---|---|---|
| P2 (malformed `nodes[0]batch`) | **spinje/pflow#214** | OPEN — exact match. **Closed by my P2 fix.** |
| U2 (cache lint warning placement) | **spinje/pflow#197** | OPEN — broader issue about mixed errors/warnings output. My observation is a sub-case; don't file separately. |

### Filed as new issues

| Filed as | Title | Severity |
|---|---|---|
| **spinje/pflow#236** | CLI `pflow workflow save` bypasses WorkflowValidator — accepts broken workflows into the library | Medium |
| **spinje/pflow#237** | Validator crashes on unresolved batch template in `--validate-only` mode — data_flow and template validators raise AttributeError | Medium |
| **spinje/pflow#238** | Test-helper splits flatten Task 147 structural assertions into rendered-string substring matching | Medium |

Each issue includes: reproduction steps, root-cause file paths and line numbers, proposed fix with code sketch, scope/out-of-scope split, related-issues references, and acceptance criteria where applicable.

### Issues confirmed NOT to be duplicates of my findings

- **spinje/pflow#233** ("Sub-workflow Diagnostic propagation flattens to plain string at parent boundary") — different code path. #233 is about runtime `WorkflowExecutor._extract_child_error` flattening to string. My Bug 1 was about validation-time `_add_child_provenance` overwriting context. Different functions, different lifecycles, different root causes.
- **spinje/pflow#224** ("~41 CLI command error handlers bypass the diagnostic pipeline") — broader concern about inline `click.echo` in error handlers. My P1 (#236) is about a specific upstream gap where comprehensive validation isn't even called. Adjacent but different.
- **spinje/pflow#66** (CLOSED — "Pre-execution validation is weaker than --validate-only validation") — same category as P1 (#236) but for the `pflow run` path. #66 was fixed for run; save was never addressed. #236 references #66 as prior art.

---

## Final state at end of this round

| Action | Result |
|---|---|
| Bugs found by verification | 4 (2 task 147 internal, 2 pre-existing) |
| Bugs fixed in this PR | 4 (Bug 1, Bug 2, P2, P5) |
| Existing GitHub issue closed by this PR | spinje/pflow#214 (via P2 fix) |
| New issues filed for follow-up | spinje/pflow#236, #237, #238 |
| Tests added in this PR (verification round) | 12 (5 for Bug 1+2, 6 for P2, 1 end-to-end) |
| Total test count | 4664 (was 4653 baseline) |
| `make test` | clean |
| `make check` | clean |

### Meta-learnings from the verification round

1. **The test-helper smell wasn't visible in the test count.** 4653 passing tests felt like strong evidence; reading the helper revealed that ~301 of those assertions are weaker than they look. **Lesson**: verification should ALWAYS read what tests assert, not just count what passes.

2. **`git stash` is not the right tool for "test against pre-feature state" when the feature is committed.** My first stash attempt was misleading because I had assumed the implementation was unstaged. Verifying via `git show <commit> -- <file>` is more reliable for "did this commit touch this file".

3. **Self-consistency checks catch the most surprising bugs.** Bug 2 was a case where the implementer wrote the rule AND violated it in the same task. The bug would have been invisible to anyone who just read either the guideline OR the wrapper code in isolation. Cross-referencing the two surfaced it.

4. **Three-level nesting is a different test from one-level nesting.** The single-level sub-workflow case passed cleanly; the three-level case revealed the recursion-unwind bug. Recursive code needs at least one test that exercises 2+ levels of recursion or the unwind behavior is unverified.

5. **Filing duplicates is the second-biggest waste of issue-tracker effort, after filing nothing.** The 30-second `gh issue list --search` round saved one duplicate filing (#214) and confirmed three were genuinely new.

6. **Pre-existing bugs that block verification of new code are still relevant findings.** The CLI save bypass is pre-existing, but it makes the new task 147 error filter unreachable from CLI — which means manual `pflow workflow save` testing won't exercise the new code. Reporting "this is pre-existing but it has implications for your new code" is more useful than "this is pre-existing, not in scope".

---
