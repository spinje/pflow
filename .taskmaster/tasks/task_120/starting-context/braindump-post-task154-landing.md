# Braindump: post-Task-154 landing, what Task 120 inherits

**Timestamp**: 2026-04-17

**Context**: I just shipped Task 154 (type vocabulary coherence) on branch `fix/type-vocab-incoherence`, currently at commit `5b5a8cbd`. Two consolidation passes: initial review fixes, then architecture-level simplification (round-2). This braindump captures what's in my head that Task 120 will need but isn't written in the task files.

---

## Where Task 120 stands right now

Task 154 was designed as Task 120's prerequisite. The vocabulary is now canonical; `TypeSpec` is the single source of truth. The plumbing point for strict runtime enforcement is documented as `TypeSpec.accepts(value)`. But the way Task 154 ended — specifically the round-2 deletion of `_TYPE_ALIASES` and the template-ref bypass close — changed the design constraints for Task 120 in ways the task_120.md file likely doesn't reflect yet.

**Read first**: `.taskmaster/tasks/task_154/task-review.md` — I added a "Round-2 Addendum" at the top that contradicts several load-bearing claims in the rest of the doc. The addendum is the canonical post-task-154 design state. Don't skip it.

---

## The round-2 story (why `_TYPE_ALIASES` is GONE, not just relocated)

The original Task 154 plan kept `_TYPE_ALIASES` and `_normalize_type` in `param_coercion.py` as "defense-in-depth for template-referenced sub-workflows that bypass `validate_ir`." This was a real bypass — the resolver returns None for `${...}` refs, so the parent validator skips them.

In round-2, we closed the bypass directly: added `normalize_ir` + `validate_ir` at `workflow_executor.py:_validate_and_compile_child` so every IR path through `compile_workflow` is validated. This made `_TYPE_ALIASES` structurally dead, and it was deleted along with `_normalize_type`, the drift-guard test, and the defense-in-depth pin.

**Why this matters for Task 120**: a natural instinct when implementing strict coercion is to think "let me handle both canonical and Python alias names, just in case." **Don't.** The invariant is now: by the time a value reaches `coerce_workflow_input`, the `declared_type` is guaranteed canonical. If Task 120 finds an untested entry point, the fix is to ADD `validate_ir` to that path, not to restore alias tolerance in coercion.

**Most dangerous place to read**: `task-review.md` line ~249 before I added the addendum said *"Do NOT remove `_TYPE_ALIASES` in `param_coercion.py`"*. The addendum explicitly overrides this. If a future agent reads that line out of context and restores the map, they reintroduce ~40 lines of dead code and undo the round-2 simplification.

---

## The composable-`CompilationError` pattern just established (NEW)

In this session I also fixed a latent bug in `CompilationError.to_diagnostics()` that will affect Task 120 if it wraps exceptions. Before this fix, `wrapped_diagnostics` and `details["sub_workflow_path"]` short-circuited each other — you got one OR the other. After:

```python
# exceptions.py:305-320
def to_diagnostics(self) -> list[Diagnostic]:
    if self.wrapped_diagnostics:
        sub_workflow_path = self.details.get("sub_workflow_path")
        if sub_workflow_path is None:
            return list(self.wrapped_diagnostics)
        return [
            replace(d, context={"sub_workflow_path": sub_workflow_path, **(d.context or {})})
            for d in self.wrapped_diagnostics
        ]
    ...
```

This means Task 120 can raise `CompilationError(wrapped_diagnostics=e.to_diagnostics(), details={"sub_workflow_path": ...})` and BOTH the inner structure (similar_names/available_fields) AND the outer container context (sub_workflow_path) reach the renderer. The `setdefault` semantics (wrapped-diag wins on conflict) are important — don't accidentally reverse the merge order.

---

## The user's mental model (verbatim where possible)

Key things the user said during this session, in their words:

> **"prioritize simplicity of the final code, not how easy it is to get there"**

This came up twice. First when reviewing the 3.14 failures (I was about to just skip the tests). Second when evaluating the W1 reviewer finding (I had proposed the reviewer's patch verbatim). Both times, when I stepped back to think about end-state complexity instead of minimum-diff, I found a better answer. For Task 120: when you're tempted to add a config flag or a compatibility shim, stop and ask what the final shape should be.

> **"what's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"**

The user routinely pushes for this framing. "Similar" here means CLI-first Python tools with heavy emphasis on agent UX — Typer, Click, Ruff, FastAPI, Pydantic patterns. Not enterprise frameworks.

> **"are you sure we should fix any of 5-7 issues? (F1-F3?)"**

The user caught me being over-credulous of review-agent findings. They pushed back hard — I'd flagged three "warnings" as potential follow-ups without scrutinizing whether they were real. On re-examination, all three were non-issues. **Lesson for Task 120**: review agents produce findings by design; your job is to challenge each one before filing. Review findings aren't bugs until you've verified them.

> **"make sure to not overfit to your context window, only add the most relevant information"**

Came up when I over-wrote a CLAUDE.md entry with 15 lines when surrounding entries were 2-3. The user values terseness. Task 120's documentation additions should match the density of surrounding prose, not add more.

> **"carefully implement B"**

Trust earned through Options A/B/C analysis. When I present tradeoffs clearly with a recommendation, the user gives fast approval. When I just start coding without presenting options, they push back.

---

## The cross-layer testing lesson (W1 case study)

The single most instructive moment in this session was the W1 bug. The `test_template_ref_bypass_close_end_to_end_through_runner` test was passing, but it was only asserting:

```python
assert "Use 'string' instead of 'str'" in diagnostic_messages  # joined .message fields
```

This substring matched because the OLD broken code flattened `suggestion` into the exception's string representation. When I fixed W1 to preserve structured context (moving the fix into `Diagnostic.suggestions` where it belongs), the test FAILED because the message no longer contained the fix text — it was in `.suggestions` now, which was the correct place all along.

**The assertion itself was WRONG — pinning a symptom of the bug.** A structure-preserving fix broke the test because the test was designed around the broken behavior.

**For Task 120 tests**: when you add strict-validation tests, assert on structured fields:
- `d.context["similar_names"]` — for fuzzy/typo diagnostics
- `d.context["available_fields"]` — for enumerated-option errors
- `d.suggestions` — for opinionated canonical fixes
- `d.context["path"]` — for the error location

Never assert `"Use 'X' instead" in d.message` unless you're specifically testing message rendering. The same pattern is now pinned in `test_template_ref_bypass_close_end_to_end_through_runner:498-519` as a template.

---

## What Task 120 actually has to do (my read)

From the existing task_120.md (read it fresh — I haven't in this session), plus what I know:

1. **Strict `coerce_workflow_input`** — currently lenient, warns on failure, returns original value. Needs to raise `WorkflowValidationError` or similar on coercion failure.

2. **`type: object` dict-only enforcement at runtime** — `_coerce_to_object` in `param_coercion.py` currently JSON-parses strings silently if they look like JSON. Strict mode should reject non-dict values (unless... UNCLEAR: should it still accept a JSON string that PARSES to a dict? That's a UX question — task 120 should decide).

3. **Use `TypeSpec.accepts(value)` as the check primitive.** The asymmetric semantics are baked in:
   - `integer` rejects `bool` (`isinstance(True, int)` returns True in Python, but JSON Schema says integer≠bool — the `accepts` method MUST enforce JSON Schema semantics, not Python's)
   - `object` is dict-only (not wildcard, despite the historical overload)
   - `any` returns True for everything
   - `number` accepts both `int` and `float`

   `TypeSpec.accepts`'s existing docstring comments this asymmetry. Don't "simplify" it by using `isinstance(value, TypeSpec.python_type())`. `TypeSpec.python_type()` was DELETED in round-2 precisely because its loose isinstance semantics were wrong for strict enforcement.

4. **Extend `_validate_child_params`** — Task 153 added this at `workflow_executor.py:~485`. It currently checks only PRESENCE of keys (missing-required / extras). Task 120's natural extension is to also check value types against declared types using `TypeSpec.accepts(value)`. Preserves the defense-in-depth pattern task 153 established.

---

## ASSUMPTIONS / UNCLEAR / NEEDS VERIFICATION

**ASSUMPTION**: Task 120's scope is strict runtime enforcement at CLI/workflow-input boundaries (where external values enter). Not internal type checks between nodes (that's template validation, different subsystem).

**UNCLEAR**: Where exactly should the strict check fire?
- Option A: `coerce_workflow_input` itself — closest to "where types enter the system"
- Option B: `_validate_child_params` for sub-workflows only — mirrors task 153's pattern
- Option C: Earlier in the pipeline at `prepare_inputs` stage — catches at compile time

The natural answer is probably A for the top-level + B for sub-workflows. But I didn't verify this — check whether there are other entry points that currently call `coerce_workflow_input` and would need to change.

**UNCLEAR**: `_coerce_to_object`'s JSON-parsing lenience. Current behavior: string `'{"a": 1}'` → `json.loads` → dict `{"a": 1}`. Is this:
- (a) convenience that should stay (CLI users pass JSON strings)
- (b) silent coercion that masks bugs and should be removed
- The user's instinct on similar questions this session was "top 10% does the hard thing" — so probably (b), with CLI taking responsibility for parsing.

**NEEDS VERIFICATION**: Does strict mode break any existing tests? Task 154 migrated 16 test files to canonical vocab, but did it also flush out tests that depended on LENIENT coercion? I didn't grep for this. Task 120 should start with a "what tests rely on lenient behavior" audit.

**NEEDS VERIFICATION**: Does strict coercion at `coerce_workflow_input` interact with the compile-once cache? When batch item 1 passes strict check and item 2 has a type error, does the cache short-circuit the check for item 2? `workflow_executor.py:265-270` has a KNOWN LIMITATION comment about per-item coercion bypass. Task 120 needs to verify strict checks aren't bypassed here.

---

## UNEXPLORED / CONSIDER / MIGHT MATTER

**UNEXPLORED**: `error_action: continue` + strict-validation errors. GH #284 documents that error_action doesn't catch prep-time errors. Task 120 would add MORE prep-time errors. Consider: should Task 120 fix #284 as part of its scope, or leave it for a separate task? The user generally prefers NOT bundling scope, but this specific interaction might create a noticeable UX regression (users set error_action: continue expecting bad values to fail gracefully, now they abort the whole workflow).

**CONSIDER**: How does Task 120 interact with Claude Code `output_schema`? That's S3 (deliberately Python-named), and values are produced by LLM generation. If Task 120 adds strict `type: object` enforcement, do LLM-generated outputs that accidentally return a string instead of a dict fail loudly? Probably the right behavior, but worth checking the output_schema validation path separately.

**MIGHT MATTER**: `type: any` passthrough. Current `_coerce_to_any` is pure identity. Strict mode preserves this (any = wildcard). But if the child has a code node annotating `x: int` for an input typed `any`, the code node raises `TypeError` at exec time with a confusing blame (user sees "int expected, got str" and wonders why the `any` declaration didn't help). Task 120 isn't responsible for fixing this, but it might surface the complaint more often once strict mode catches the easier cases. Flag for the task-120 task doc.

**UNEXPLORED**: MCP server entry points. `pflow_execute` via MCP submits a workflow IR + parameters. Does it go through the same `coerce_workflow_input` path? If MCP has its own coercion that bypasses strictness, Task 120 ships an inconsistency between CLI and MCP. Search `src/pflow/mcp_server/` for coercion paths.

**UNEXPLORED**: Test for strict + `null` input. Task 154 dropped `null` from vocabulary (deferred until union syntax lands). In strict mode, `type: string` with a None value — does it raise, or is None handled specially? Probably should raise, but verify the behavior is tested.

---

## Hard-won knowledge from this session

**The AST walker in `_check_annotation_vocabulary` taught me that import detection matters.** Originally I tried to reject all typing-module names in annotations (`Union`, `List`, etc.) — but that broke `from typing import Literal` users. The fix was `_extract_imported_names` — only reject when NOT imported. Task 120 might need similar import-awareness if it validates Python code paths. Pattern: collect imports first, then check usage against the import set.

**PEP 649 (Python 3.14+) changes annotation evaluation semantics.** This hit us in CI — the existing `NameError`-based opinionated hints stopped firing on 3.14 because annotations are deferred. Task 120 isn't directly exposed to this (runtime coercion happens before code annotations run). But any Task 120 design that relies on Python's runtime to enforce type checks must test across Python versions.

**The review agents produce findings by design — challenge each one before acting.** The user called me on this explicitly. I'd reflexively listed every agent finding as potential follow-up work. Most were theoretical concerns that didn't apply. For Task 120: when review agents flag "strict mode could miss X edge case," verify the edge case is reachable before scoping work around it.

**`make check` cyclomatic complexity (C901) limit is 10.** Adding a third `except` branch to `_compile_sub_workflow` pushed it to 11, blocking the commit. Had to extract `_validate_and_compile_child` static method. Task 120 will likely add dispatch logic that bumps against C901 — plan for extraction rather than `# noqa`. User memory explicitly says don't suppress linter warnings.

**Subprocess vs in-process tests for rendering pipeline.** I've defaulted to in-process tests (format_diagnostic in the same process). ~3ms vs 500ms subprocess. Same coverage for everything except CLI entry wiring (which is a stable contract, separately tested). Task 120 renderer tests should be in-process unless specifically testing stderr/stdout separation.

---

## Open threads I didn't pursue

The user mentioned the `error_action: continue` / `validate_ir` interaction as a follow-up candidate but didn't want it filed as a GH issue. If Task 120 goes there, it'll hit this. Consider whether Task 120's scope naturally extends to cover prep-time errors uniformly.

The review mentioned `docs/reference/nodes/claude-code.mdx:134-142` teaches `str/int/bool/list/dict` for output_schema without a "this is S3, intentionally different from S1" clarifying sentence. I flagged it as low-stakes and moved on. Task 120 might run into agent confusion about this and want to add the clarifying sentence.

I ran the review-feature-interactions agent earlier and it produced findings F1-F3 which the user correctly dismissed. But one finding I didn't fully explore was the scenario where the compile-once cache serves a stale strict-check result to a later batch item. If Task 120 doesn't explicitly address this, add an explicit invariant test: "batch item 2 with invalid type still raises even if item 1 passed."

---

## Relevant files (in priority order)

- `.taskmaster/tasks/task_154/task-review.md` — **READ THE ROUND-2 ADDENDUM FIRST**. Many sections below it are stale.
- `.taskmaster/tasks/task_154/implementation/progress-log.md` — the "post-merge-review round 2" entry has the Option B → Option D pivot that's load-bearing for Task 120's "don't reintroduce `_TYPE_ALIASES`" invariant.
- `src/pflow/core/types.py` — `TypeSpec`, `CANONICAL_TYPES`, `PYTHON_ALIASES_AT_S1`. `TypeSpec.accepts()` is Task 120's extension point.
- `src/pflow/core/param_coercion.py` — the lenient coercer. Look at `_COERCION_DISPATCH` and `_coerce_to_object` specifically.
- `src/pflow/runtime/workflow_executor.py:_validate_and_compile_child` — the new static helper where W1 landed. Study the exception chain if Task 120 needs to add its own wrapping.
- `src/pflow/core/exceptions.py:CompilationError.to_diagnostics` — the just-fixed compose behavior. Reuse the pattern if Task 120 wraps exceptions.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py:TestTemplateRefSubWorkflowValidation` — template for cross-layer rendering tests. Specifically `test_template_ref_bypass_close_end_to_end_through_runner` shows the structured-assertion pattern.
- `tests/test_runtime/test_prepare_inputs_coercion.py` — pre-existing tests for `coerce_workflow_input`. Task 120 will extend/replace these.

---

## What I'd tell myself starting over

1. **Don't bundle scope**. Task 120 is "strict enforcement of the vocabulary Task 154 established." It is NOT the place to fix `error_action`, rename the `<inline>` sentinel, or consolidate the three vocabularies (S1/S2/S3). If the user asks whether you should bundle, the answer is probably no — reviewers consistently preferred scoped PRs.

2. **Design the test contract before writing code**. What does `result.diagnostics` look like for a strict-validation error? Which fields matter? Write the assertion pattern FIRST, then make the code match. The W1 lesson is that tests encoding the wrong contract hide real bugs.

3. **Dispatch table, not if/elif**. `_COERCION_DISPATCH` in `param_coercion.py` is the existing pattern. Task 120's strict check should follow the same shape — `_STRICT_CHECK_DISPATCH: dict[str, Callable]` keyed by canonical S1 names.

4. **The user will push back on over-engineered strict modes**. If Task 120 has feature-flag config for strict/lenient, the user will likely reject it (like task 154 rejected deprecation warnings). Just make it strict, breaking-change atomic ship, migrate tests in the same PR. MVP state = no external users = no compat debt.

---

## For the next agent

- **Start by reading `task_154/task-review.md` top-to-bottom, especially the Round-2 Addendum.** Then re-read this braindump. Then the Task 120 task doc.
- **Don't bother reinstating `_TYPE_ALIASES` or `_normalize_type`.** They're structurally unnecessary after the round-2 bypass close.
- **The user cares most about**: (a) final-code simplicity over minimal-diff, (b) structured diagnostics over flattened messages, (c) top-10% patterns from CLI-first tools. Their review style is challenging — present options with tradeoffs, and they'll approve fast.
- **Test cross-layer rendering, not just unit structure.** `test_template_ref_bypass_close_end_to_end_through_runner` is the template to copy.
- **The branch `fix/type-vocab-incoherence` is still open and waiting for merge**. Task 120 work should happen on a fresh branch off `main` AFTER this PR merges. Don't continue on this branch.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
