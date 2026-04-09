# Braindump for Task 148 Implementing Agent

I'm the agent who designed this task end-to-end with the user. The task spec and the implementation plan capture WHAT and HOW. This braindump captures everything else — the user's mental model, the journey, the things I almost missed, and the subtleties I'm only 70% sure about.

**Read this fully before touching code.** If you skip it and dive into the plan, you'll miss why decisions were made and you'll fight the user's intent without realizing it.

---

## Where I Am

Plan is approved (`ExitPlanMode` succeeded). The user has explicitly approved the full Tier 1 + Tier 2 scope after pushing back twice on my initial "just patch it" instinct. Plan file: `.taskmaster/tasks/task_148/implementation/implementation-plan.md` (~145KB, 3200+ lines). Spec: `.taskmaster/tasks/task_148/task-148.md` (just rewrote it as pure spec — no implementation details).

The bug is reproduced and the fix design is fully fleshed out. Nothing has been implemented yet. Phase 1 is the next concrete action.

## User's Mental Model — Read This Carefully

The user thinks about software in terms of **invariant correctness, code simplicity at the END state, and AI-agent actionability**. They care more about how the final code reads than how easy it is to write. They reframe problems aggressively when they smell shortcut-thinking.

**Their exact words and the moments they mattered:**

1. After my first proposal (3 options, recommend "patch resolve_coalesce"): *"so there are no tradeoffs or alternatives to consider? lets take a step back. we should prioritize simplicity of the final code, not how easy it is to get there. Does this make sense? whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"*

   This reframe changed the entire task. I had been thinking "smallest change to fix the bug." They were thinking "what's the right invariant?" I'd been treating Task 128's "node ran ↔ present" as a load-bearing constraint. They asked me to question whether that invariant was actually right. **It wasn't.** That's the whole task.

2. After I proposed the invariant fix: *"this seems to be in the right direction, how should we think about this in terms of validation and what shows up in trace file and --report?"*

   They want to think holistically about downstream consumers BEFORE committing. They will ask "what about X" for things you haven't considered. Be ready to defend or update.

3. *"we shouldnt take any shortcuts here, if you can see any paths for simplification or consolidation of existing code, call it out. All error messages should be improved for actionability and clarity for ai agents making/editing workflows"*

   This is THE directive. Two things matter equally: (1) consolidation/simplification of existing duplicated code, (2) error messages that an AI agent can actually act on. Don't optimize for one and ignore the other.

4. After I gave the consolidation analysis: *"how do you suggest we handle warnings 6-12?"*

   They wanted my opinion BEFORE I made changes. They use questions to invite analysis, not to delegate decisions. When asked for a recommendation, give one (with rationale) — don't punt back.

5. After my recommendations on warnings 6-12: *"yes go ahead with this"*

   This was tacit approval of EVERY recommendation, including #8 (typo detection on failed nodes as a secondary hint). I had explicitly framed #8 as a decision point for them — they didn't carve it out, so I incorporated all 7 warning fixes.

6. They use `/code-review` aggressively. Expect them to review your implementation the same way they reviewed the plan. Errors of omission (missing consumers, untested combinations, ambiguous instructions) get caught.

**Stated priorities, ranked**:
1. Final code simplicity and correctness (the invariant must be right)
2. AI-agent actionability of every error message
3. No shortcuts in the work itself — fix all the duplications you find
4. Tier 1+2 in one task (not two), to avoid re-touching files

**Unstated priorities I picked up**:
- They review messages by reading them as if they were the AI agent receiving them. If it sounds like bureaucratic noise, they'll reject it.
- They want the final state to be coherent — not a Frankenstein of patches.
- They will challenge "but X is already there" with "should X be there?"

## The Journey — How Understanding Evolved

This took 4 distinct reframing rounds:

**Round 1**: I saw the bug and proposed Option 1 (error-aware coalesce check that consults `__execution__["completed_nodes"]`), Option 2 (new `?!` operator), Option 3 (clean up failed namespace). I recommended Option 1 because it was the smallest change.

**Round 2**: User pushback ("simplicity of final code, not ease of getting there"). I realized Option 1 leaves the bad invariant in place. The right answer is Option 3 — but with a TWIST: don't delete the failed data, MOVE it to `__failures__` so diagnostics still work. This is what I should have proposed first.

**Round 3**: User asked about validation, trace, --report. I researched and confirmed all three are safe (validation reads IR not shared store; trace snapshots BEFORE the move; --report reads only trace file). But the research surfaced a critical missed consumer: `executor_service.build_error_list()` reads `shared[failed_node]` AFTER the engine returns. This led to the "move via helper, fall back via helper" pattern.

**Round 4**: User asked for consolidation + AI-actionable messages. I dispatched a research agent to map all duplications (15 read sites, 5 write sites, 5 root extractions, 4 message variants, 2 broken category paths, 12 dead context fields). This expanded the task from ~50 lines of code to ~390 lines / ~1100 lines of plan.

**Round 5**: 4-agent code review pass on the plan caught:
- Phase ordering bug (Phase 3 used a method only added in Phase 4)
- `clear_node_failure` defined but never wired up (loop re-entry bug)
- `execution_state.py:143` not in migration list (failed batch/shell display regression)
- Integration tests using `ir_to_markdown` which drops `on-error` routing
- Integration tests passing `config=None` which crashes
- 7 UX warnings (Case 2 missing fix, placeholder peer names, hardcoded shell fields, etc.)

ALL of these are now in the plan. Don't re-discover them.

## Things Not In The Spec or Plan That You Need to Know

### About the plan's structure

The plan is 3200+ lines because the user wanted "no ambiguity." Each code edit has verbatim old/new strings. **Read the "Architectural Decisions (DO NOT REVISIT)" section first** — those are settled. Then read "Implementation Order" to understand phase dependencies. THEN go phase-by-phase.

The "Critical Files To Read Before Modifying" list at the top of the plan is real — read those files in full before starting. The plan references line numbers from those files; if your reading has the file open, you can verify the old_string matches.

### Subtle landmines I almost stepped on

1. **`cache_result` is UNCHANGED**. The plan says this explicitly in Phase 2 Action 2. But an earlier draft had it modified. If you skim Phase 2, you might modify it anyway. Don't. The data move happens at step 17.5 of `_execute_node`, NOT inside `cache_result`. `cache_result` only sets `failed_node` (its current behavior).

2. **`record_trace` is UNCHANGED**. Same trap. With the new ordering, `mark_node_failed` runs AFTER `record_trace`, so the trace reads `shared[node_id]` directly (data still there). An earlier plan version had `record_trace` migrated to use `get_node_output` — that's no longer needed.

3. **`enrich_llm_cost` is UNCHANGED**. Same reason. The data is still in `shared[node_id]` when `enrich_llm_cost` runs (it's called BEFORE `mark_node_failed` in both happy path step 15 and exception path).

4. **`call_completion_callback` is UNCHANGED**. Same reason.

5. **`_execute_node` happy path adds NEW code at step 17.5** — not modifying existing code. The existing return statement stays; the new `mark_node_failed` call goes between `call_completion_callback` and `return action`, gated on `if str(action).startswith("error")`.

6. **`_handle_no_successor` is called AFTER `_execute_node` returned successfully**. By then `cache_result` has added the node to `completed_nodes`. You must call `invalidate_cache(node_id, shared)` BEFORE `mark_node_failed` to roll back. The plan does this correctly but it's easy to miss the ordering.

7. **The two `Action 1`s in Phase 1**. Phase 1 has Action 1 (create `node_state.py`) AND Action 2 (add `extract_root_node_id` to `template_resolver.py`). BOTH must be done in Phase 1 because Phase 3's read-site migrations call `TemplateResolver.extract_root_node_id`. If you only do Action 1, Phase 3 won't compile.

### The Phase 6 yaml line tracking is the trickiest single change

The plan tells you to set `yaml_current_item_start_line = line_num` at `markdown_parser.py:374`, which is an ASSIGNMENT (not an `.append()`). If you grep for `yaml_current_item_lines.append`, you'll find continuation appends, not the new-item creation site. Trust the line number in the plan — verify the assignment exists at line 374 before adding.

The line number variable is `line_num` (not `line_idx`). It's computed earlier in the loop body around line 259.

### Things I'm only 70% sure about

**ASSUMPTION**: The `Diagnostic.__eq__/__hash__` constraint won't cause dedup issues with the new template error messages. The message format includes `param_key` + first 3 variable names, which should be specific enough. But I haven't extensively tested edge cases with multiple template errors in the same workflow.

**NEEDS VERIFICATION**: After Phase 5, run the new error messages through `format_diagnostic` and check that the layout reads naturally. The exact wording flexibility is OK, but if the structure is wrong (e.g., missing line breaks, indentation off), iterate. The user will read these and judge them.

**NEEDS VERIFICATION**: The `_pflow_template_diagnostic` attribute attachment to `ValueError` survives the runner's exception path. I added this via Phase 5 Action 3, and Phase 5 Action 5 reads it back in `_builtin_exception_diagnostic`. But if there's any intermediate `except Exception as e: raise` that uses `from e` or wraps the exception, the attribute might get lost. Test: trigger a strict-mode template error end-to-end and verify the resulting Diagnostic has the structured context, not the generic `category="execution_failure"`.

**ASSUMPTION**: `available_context_keys` in the Diagnostic context is filtered correctly. I filter `__*__` keys but don't filter `_pflow_*` keys. Verify those don't show up in user-facing error messages.

**UNCLEAR**: How `mark_node_failed` interacts with parallel batch items. The plan says batch items use `_execute_single_node` which doesn't go through `mark_node_failed`, so per-item failures don't archive. But I haven't traced this end-to-end. If a parallel batch item fails AND the batch node itself returns "default", the per-item failure data lives in `shared[batch_node_id]["errors"]` which stays put. Verify nothing weird happens.

**ASSUMPTION**: `output_resolver._diagnose_unresolved_output` calling `classify_unresolved_references` from `template_errors.py` doesn't create a circular import. Both are in `runtime/`, so the dependency is `output_resolver → template_errors → template_resolver` (which is fine). But verify on first import.

### Things the user did NOT discuss that might matter

**UNEXPLORED**: Sub-workflow Diagnostic propagation. When a child workflow's template error happens, the structured Diagnostic flattens to a string at `_extract_child_error` in `workflow_executor.py`. The plan acknowledges this as out-of-scope but doesn't fix it. If a user references `${child_wf.field}` and `child_wf` is a sub-workflow that failed because of a template error inside it, they get a wrapped string, not structured context. This is acceptable for this task but worth noting in the progress log.

**MIGHT MATTER**: Performance of `_find_peer_nodes_with_field`. It's O(n*m) where n=context size and m=number of failed references. For typical workflows (5-20 nodes), this is fine. For workflows with hundreds of nodes referencing many template variables that fail, it could become noticeable. Probably not a concern for this task.

**CONSIDER**: The MCP server JSON output. The plan claims `to_display_dict()` will surface `unresolved_references` to MCP consumers. I verified the path conceptually but didn't write an explicit MCP test. If you have time, add one to Test File 4 — assert that an MCP-formatted error includes the structured context.

**UNEXPLORED**: The `__failures__` dict could grow unbounded in long-running workflows with many transient failures (e.g., batch with retries). The plan doesn't add a cleanup mechanism. For most workflows this is fine; for edge cases it could matter. Worth a note in the progress log if you notice it.

## Hard-Won Knowledge

1. **Task 128's invariant comment is wrong**. It says "node ran → present in shared". The right invariant is "node succeeded → present in shared". This task corrects it. When you update `runtime/CLAUDE.md` in Phase 7, replace the old invariant text — don't append.

2. **`shell.post()` writes outputs BEFORE returning the action**. This is at `shell.py:613-639`. It's the proximate cause of the bug. The fix doesn't touch shell.py — it lets shell write its data to the namespace, then the engine moves the namespace to `__failures__` after execution.

3. **`NamespacedSharedStore.__init__` eagerly creates `parent[namespace] = {}`**. This is at `namespaced_store.py:39-41`. It's the second cause of the bug — failed nodes that wrote nothing still have an empty dict in shared. The fix doesn't touch namespaced_store.py either; the move post-execution catches both cases.

4. **`_PROPAGATED_KEYS` in `workflow_executor.py` excludes `__execution__`**. So sub-workflows have their own execution state. `__failures__` will inherit the same exclusion (it should NOT be in `_PROPAGATED_KEYS`). Verify this in Phase 2 Action 1's helper definitions — `mark_node_failed` writes to `shared["__failures__"]` which is the per-workflow shared store.

5. **The `tests/CLAUDE.md` "Gotchas with `ir_to_markdown`" section is real**. `ir_to_markdown` does NOT emit `edges`, `start_node`, or `ir_version`. Tests for on-error scenarios MUST pass IR dicts directly to `WorkflowRunner.run(ir_dict, ...)`. The plan's Phase 8 Test File 3 already does this; if you write more tests, follow the same pattern.

6. **`WorkflowRunner.run` requires `config: RunnerConfig`**, not `None`. Passing `None` crashes on `config.cache_enabled`. Use `config=RunnerConfig()` for default behavior.

7. **The reproducer is at `scratchpads/issue-208/repro.pflow.md`**. I created it. Run it after Phase 3 — should produce `fallback-content`. Run it after every subsequent phase as a smoke test. If it stops working, you broke something.

## What I'd Tell Myself If Starting Over

1. Read `execution_state.py` BEFORE writing the first plan. It was the most critical missed consumer and only the second-pass review caught it. Anytime you're touching shared-store access patterns, search the entire codebase for `shared.get(node_id` and `shared[node_id` patterns.

2. The user will reframe at least once. Don't get attached to the first design. When they say "lets take a step back," they're inviting you to reconsider the foundation, not just tweak the surface.

3. When they ask about a specific dimension (validation, tests, --report), it's because they suspect you haven't considered it. Research it first, THEN answer with confidence.

4. The 4-agent code review pass is gold. Run it before exit-plan-mode. The cost is small; the value is enormous. Phase ordering bugs and missing consumers WILL be caught.

5. The failed-node typo detection (warning #8) — I framed it as a decision point but the user said "yes go ahead with this" to all 7 fixes including #8. Don't punt decisions back when the user is in "go" mode.

6. The plan's "Architectural Decisions" section is critical. Future agents (including you, after compaction) will need to know what's settled vs. open. Make it clear which decisions are immutable.

## Open Threads (None Critical)

- The MCP server JSON output assertion is in Test File 4 conceptually but not as an explicit end-to-end test. Could add one.
- Sub-workflow Diagnostic propagation is acknowledged out-of-scope but might come up if users complain.
- Performance characterization of `_find_peer_nodes_with_field` could be added if needed.
- The `__failures__` dict has no cleanup mechanism — fine for now, might matter later.

## Implementation Order & What to Watch For

Strict order (also in the plan):

1. **Phase 1** — Both Action 1 (node_state.py) AND Action 2 (extract_root_node_id). Self-contained. Run the verification snippet to confirm imports work.

2. **Phase 2** — The biggest cross-cutting change. Tests will fail. **Run the repro after Phase 2** — it might still produce wrong output (Phase 3 finishes it). Check that `make check` passes (lint/types) before moving on.

3. **Phase 3** — Read-site migrations. After this phase, the **#208 repro MUST produce `fallback-content`**. If it doesn't, stop and debug. Don't proceed to Phase 4 with a broken repro.

4. **Phase 4** — Trivial sweep. `data_flow.py` only.

5. **Phase 5** — Biggest body of work. Template error rewrite + structured rendering. After this, manually run the three Cases from the spec and verify the format. Iterate the rendering if the layout reads poorly.

6. **Phase 6** — Source line tracking. Easy in concept, finicky in the parser. Test with the repro after.

7. **Phase 7** — Documentation. Just update the CLAUDE.md files.

8. **Phase 8** — Tests. The 12-test list of existing breakages is in the plan. Work through them. Run `make test` repeatedly.

9. **Phase 9** — File the 3 GH issues for Tier 3 follow-ups.

**Recommended checkpoint**: After Phase 2, run `/code-review` before starting Phase 3. The review-impact-completeness and review-feature-interactions agents are most useful here.

## Verification — What "Done" Looks Like

The 7 final verification steps in the plan's "Verification — Final End-to-End" section. The most important:

1. `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` → outputs `fallback-content`
2. `make check` and `make test` both pass
3. The three Case examples from the spec produce the agreed format (or close enough — wording flexibility OK as long as the structure matches)
4. JSON output mode shows structured `unresolved_references` (not opaque message)
5. `--report` works for the repro

If 1-5 work, the task is done.

## Relevant Files & References

**Bug**: GH #208 (https://github.com/spinje/pflow/issues/208)
**Reproducer**: `scratchpads/issue-208/repro.pflow.md`
**Spec**: `.taskmaster/tasks/task_148/task-148.md`
**Plan**: `.taskmaster/tasks/task_148/implementation/implementation-plan.md`
**Original plan file**: `/Users/andfal/.claude/plans/quirky-sniffing-wave.md` (same content as the implementation/ copy)

**Source files most touched**:
- `src/pflow/runtime/node_state.py` (NEW)
- `src/pflow/runtime/template_resolver.py` (small addition)
- `src/pflow/runtime/engine/engine.py` (3 sites)
- `src/pflow/runtime/engine/instrumentation.py` (3 sites)
- `src/pflow/runtime/engine/template_errors.py` (FULL REWRITE — keep build_type_error_message and build_json_parse_error_message)
- `src/pflow/runtime/engine/template_resolution.py` (small)
- `src/pflow/runtime/engine/error_context.py` (small)
- `src/pflow/runtime/output_resolver.py` (medium — also cleans up duplicate regex)
- `src/pflow/runtime/workflow_executor.py` (small — `_extract_child_error`)
- `src/pflow/core/diagnostic.py` (medium — new renderer functions)
- `src/pflow/core/user_errors.py` (rewrite `OutputResolutionError.to_diagnostics`)
- `src/pflow/execution/executor_service.py` (medium)
- `src/pflow/execution/execution_state.py` (small — line 143 only)
- `src/pflow/execution/runner.py` (small — improve canned suggestions)
- `src/pflow/core/markdown_parser.py` (medium — yaml line tracking)
- `src/pflow/core/workflow/data_flow.py` (small — replace `_ROOT_SPLIT_PATTERN` reach)

**CLAUDE.md files to update**:
- `src/pflow/runtime/CLAUDE.md` — Reserved Shared Store Keys + new invariant section
- `src/pflow/runtime/engine/CLAUDE.md` — `mark_node_failed` documentation

## For the Next Agent

**Start by**:
1. Reading this braindump fully (you're doing it now)
2. Reading the spec at `.taskmaster/tasks/task_148/task-148.md` for WHAT and WHY
3. Reading the "Architectural Decisions" and "Implementation Order" sections of the plan
4. Reading `scratchpads/issue-208/repro.pflow.md` and running it ONCE before any code changes — verify the bug exists for you
5. Reading the "Critical Files To Read Before Modifying" list at the top of the plan and reading those files in full

**Don't**:
- Modify `cache_result`, `record_trace`, `enrich_llm_cost`, or `call_completion_callback`. The plan says they're unchanged. They are.
- Skip Phase 1 Action 2 (`extract_root_node_id`). Phase 3 needs it.
- Use `ir_to_markdown` for tests with on-error routing. It drops the routing.
- Pass `config=None` to `WorkflowRunner.run()`. Use `RunnerConfig()`.
- Re-discover the warnings 6-12 fixes. They're in the plan.
- Try to fix sub-workflow Diagnostic propagation. It's out of scope.

**The user cares most about**:
1. The repro producing `fallback-content`
2. Error messages being agent-actionable (paste-able fixes, real peer node names, specific failure context)
3. Code simplicity at the END state (consolidation, no scattered duplications)
4. Passing `make check` and `make test` cleanly with no `# noqa` shortcuts

**The hard parts** (where you'll spend most of your time):
1. Phase 5 — the template error rewrite is the largest single body of work
2. Phase 8 — fixing 12 existing tests that encode the old invariant
3. Phase 6 — yaml line tracking in the parser is finicky

**The easy parts**:
1. Phase 1 — copy/paste the helper module
2. Phase 4 — one line change in data_flow.py
3. Phase 7 — documentation updates

**Keep a progress log** at `.taskmaster/tasks/task_148/implementation/progress-log.md` as you go. Record decisions, deviations from the plan, and any surprises. The user will read it.

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
