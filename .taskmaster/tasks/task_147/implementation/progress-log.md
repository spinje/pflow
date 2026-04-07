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
