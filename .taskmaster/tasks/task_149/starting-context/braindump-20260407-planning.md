# Braindump: Task 149 Planning Session (2026-04-07)

## Where I Am

Plan is **approved, reviewed by 4 specialist agents, and updated to address all critical findings**. Task spec (`task-149.md`) and implementation plan (`implementation/implementation-plan.md`) are both in place. Ready to start implementation but context window is running out.

The plan went through multiple refinements driven by user pushback and multi-agent review. The final version is better than what I originally proposed in every way. Do not second-guess the decisions already recorded.

---

## User's Mental Model — Critical Context

The user's **original motivation** for investigating this was NOT the GH #194 bug per se. It was: **they wanted to see streaming progress output when running pflow interactively in Claude Code**. Their exact words from early in the conversation:

> "the initial issue for all this is that I wanted a streamed response when executing workflows, but for you running in claude code you can never see this kind of output for some reason"

This matters because it changes how to prioritize. The deliverable isn't just "fix #194". It's "make progress visible to agents during workflow execution AS A RESULT of fixing #194". The user cares about the user-visible behavior, not the bug ID.

### User's repeated mantra (mark this, it's important)

The user said this **twice** at critical decision points:

> "we should prioritize simplicity of the final code, not how easy it is to get there. Does this make sense? whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"

First time: I had proposed a narrow "fix #194 only" scope. Second time: I was waffling on whether to keep `-p` or rename it. Both times, this question forced me to reconsider and pick the better answer, not the easier answer.

**Apply this as a filter during implementation**: if you find yourself thinking "this is easier but creates scaffolding/complexity/technical debt", stop and reconsider. The user will notice and push back.

### User's pushback pattern

The user caught me making several wrong turns. Each time, I was over-complicating or losing sight of something. The pattern:

1. **I framed two issues as separate → user: "but isnt these tighly integrated?"** — I was going to fix #194 in a small PR and leave "agents can't see streaming" as a follow-up. The user correctly saw these were one problem with one fix. Don't separate related concerns just to shrink the PR.

2. **I was about to design non-TTY append-only rendering → user: "wait, why isnt line replacing/update inline working anymore?"** — I was about to destroy their interactive experience for no good reason. My reasoning was "append-only is simpler" but I hadn't verified that inline rendering actually fails in non-TTY. It mostly doesn't (only `\r` overwrite does). The user's instinct saved us from a major regression.

3. **I was going to emit a richer non-TTY format → user: "Non-TTY mode is for agents like you? shouldnt we keep that as less noisy / token heavy as possible?"** — I was optimizing for streaming visibility and forgetting that agents pay tokens per byte. The user reframed: non-TTY = agents = token-sensitive = minimize output.

4. **I designed two rendering paths (TTY vs non-TTY) → user: "wouldnt it be more simple to keep the finished output exactly same for both?"** — When I actually tested empirically, the user was right. The `nl=False` + append pattern produces IDENTICAL bytes in TTY and non-TTY. Only `\r` overwrite needs the split. One rendering path, one exception.

5. **I was renaming `--print` to `--quiet` → user: "why do we need to rename print to quiet? for example claude code uses -p when it should just output the result?"** — I was renaming for aesthetic reasons ("`-q` matches pytest/cargo"). The user correctly pointed out that Claude Code's `-p` convention already means what pflow's `-p` does, so the rename was pure churn. Keep the flag name.

**Lesson for next agent**: When in doubt about scope, complexity, or abstraction — ask the user. They will push back on over-engineering and they know the product better than you think.

---

## Key Empirical Findings (verified during planning)

These are the three tests I ran that shaped critical decisions. The results aren't in the plan file as raw data — just the conclusions. If implementation uncovers contradicting behavior, re-verify with these tests.

### Test 1: Python 3 stderr line-buffering in non-TTY

```bash
python3 -c "
import sys, time
for i in range(5):
    print(f'line {i}', file=sys.stderr, flush=False)
    time.sleep(0.4)
" 2>/tmp/out &
# Poll the file at 0.2s intervals
# Result: each line appeared at exactly the expected interval
```

**Conclusion**: Python 3 `sys.stderr` is line-buffered by default, even when redirected. `\n` triggers flush. No explicit flushes needed for streaming. **I set `flush=False` explicitly in the test to rule out auto-flushing.**

### Test 2: `click.echo` with `nl=False` still flushes

```bash
uv run python -c "
import click, time
click.echo('  stage_one...', err=True, nl=False)
time.sleep(0.5)
click.echo(' ✓ 0.1s', err=True)
" 2>/tmp/out &
# Poll: at t+0.1, file had 14 bytes (the partial line)
# At t+0.9, file had 38 bytes (partial + completion)
```

**Conclusion**: Click flushes on every echo call, including with `nl=False`. Partial lines stream to non-TTY consumers in real time. **This is WHY the plan can use `nl=False` + append in non-TTY without switching to append-only.**

### Test 3: `\r` overwrite pattern in non-TTY capture

```bash
python3 -c "
import sys
sys.stderr.write('  process_items...')
for i in range(1, 6):
    sys.stderr.write(f'\r  process_items... {i}/5 ✓')
sys.stderr.write(' 3.1s\n')
" 2>/tmp/out
cat /tmp/out
# Output: "  process_items...  process_items... 1/5 ✓  process_items... 2/5 ✓..."
```

**Conclusion**: `\r` does NOT render correctly when stderr is captured. The bytes concatenate into an ugly single line. **This is WHY `_handle_batch_progress` needs an internal `sys.stderr.isatty()` guard — it's the only rendering path that fails in non-TTY capture.**

All three tests were runnable from within Claude Code's Bash tool. If the next agent wants to reproduce, use the same commands.

---

## What Almost Went Wrong (learn from my near-misses)

These are things I almost got wrong but course-corrected before finalizing. They're recorded here because the next agent might face the same temptations:

1. **Deleting inline cursor rendering for "one rendering path" purity** — I was optimizing for "one code path" and was about to make TTY users lose their nice interactive UX. The user caught it. **The right separation is: routing is unified (one rule), rendering can vary by TTY (cosmetic concern).**

2. **Conflating "TTY detection is bad" with "all TTY checks are bad"** — The original bug was TTY detection affecting ROUTING (stream assignment). That's wrong. But TTY detection for RENDERING (cursor tricks) is fine — it's what `ls --color=auto` does. I was ready to delete all TTY checks; that would have been an overcorrection.

3. **Renaming `--print` → `--quiet`** — aesthetic churn with no user-visible benefit. User correctly kept `-p`.

4. **Framing the refactor as "fix #194 first, then optimize later"** — user correctly insisted on doing it right once. Don't ship incremental fixes that carry technical debt.

5. **Missing that `success_formatter.py` has a PARALLEL copy of the per-node block** — this was caught by the review-plan agent. If I had shipped the original plan, CLI and MCP would have silently diverged. This is the same Task 85 regression pattern documented in `execution/formatters/CLAUDE.md` "Hard-Won: Update BOTH Call Sites".

6. **Missing the failing-node line terminator bug** — caught by review-feature-interactions agent. Without the `✗ Failed` terminator, failing nodes leave hanging `node_id...` partial lines that concatenate with diagnostics. The bug was invisible in today's TTY-gated design because it only manifests when progress is always-on.

7. **Missing `-p` and JSON mode needing to suppress progress** — I removed the TTY gate but didn't think about what happens in `-p` and JSON modes that USED to use the TTY gate indirectly. Caught by review-plan and review-feature-interactions agents.

**Take from these**: design reviews matter. The 4-agent review added ~15-20 critical fixes I would have missed. Don't skip reviews to ship faster.

---

## The 4 Decisions (recorded in plan but worth re-emphasizing)

These are design decisions that came out of review, all approved by the user. They are NOT preferences — they are NECESSARY to avoid bugs or regressions:

1. **MCP per-node block deleted too** (not just CLI). Parity requirement. `success_formatter._append_execution_steps` simplified to match.
2. **JSON mode suppresses progress callback**. Existing invariant says JSON mode = machine-clean stderr. Breaking that invariant would be a regression.
3. **`-p` mode suppresses progress callback**. User explicitly asked for minimal output. Breaking the promise would be visible to users.
4. **Smart-handled tags ported to live callback**. `[no matches]`, `[not found]` tags are agent-diagnostic-critical. Losing them silently would be a UX regression for shell workflow debugging.

**All 4 are "option A" in the plan's decision framing. User agreed to all 4 recommendations in one message: "yes continue".**

---

## Subtle Implementation Gotchas

Things the plan mentions but that are easy to miss or misread:

### Pytest stderr capture breaks the new TTY guard

`pytest` replaces `sys.stderr` with a capture stream. `sys.stderr.isatty()` returns `False` under pytest by default. The new internal guard in `_handle_batch_progress` will cause 5 existing batch-progress tests to fall through silently. **Use `patch.object(sys.stderr, 'isatty', return_value=True)` in those tests.**

I'm 70% confident this approach works. If it doesn't, try `monkeypatch.setattr("sys.stderr.isatty", lambda: True)` or patching at the `output_controller` module level if it does a local import.

### `NamespacedSharedStore` masks the shell.py write location

`shell.py:688-689` does:
```python
shared["smart_handled"] = True
shared["smart_handled_reason"] = reason
```

This looks like a root-level write, but the shell node runs inside a `NamespacedSharedStore` proxy that redirects writes to `parent_store[node_id][key]`. So at the root shared dict level, these values appear at `shared[node_id]["smart_handled"]` — which is where `call_completion_callback` needs to read them (the same pattern as the existing batch detection block).

I verified this by reading the file but did NOT run it. NEEDS VERIFICATION during implementation: one manual test of a grep-no-match workflow should confirm the tag renders.

### MCP server passes NO output kwarg today

`mcp_server/services/execution_service.py` calls `runner.run(resolved, params, config, workflow_manager=..., workflow_name=...)` with NO `output=` kwarg. This means the signature rename from `output=` to `progress_callback=` is safe — MCP path is unaffected. BUT: `execution/CLAUDE.md` documentation and `mcp_server/CLAUDE.md` both falsely claim MCP passes `output=NullOutput()`. That's stale docs, not a real divergence. The plan updates the docs.

### The `output_controller.is_interactive()` method is NOT deleted

After the refactor, `is_interactive()` has exactly one remaining caller: `cli/mcp_sync.py:144`. Keeping the method is out of scope; just narrow its docstring to reflect its reduced role. Don't try to delete it and refactor `mcp_sync.py` as part of this task.

### `should_show_prompts` contradiction

Earlier plan drafts had a contradiction: Step 5 deleted it as "dead code" but Step 17 CLAUDE.md update said it was "still TTY-gated for save prompts". Review caught it. Resolution: **grep confirmed zero production callers of `should_show_prompts`**, only tests. The method really is dead code.

BUT: I did NOT find what actually gates the save-prompt logic. If deleting `should_show_prompts` breaks save-prompt tests, restore it as a minimal 2-line `return self.is_interactive()` method. **NEEDS VERIFICATION during implementation.**

---

## Things I Did NOT Verify (proceed with caution)

### `_format_execution_step` + `_format_batch_node_line` become dead after Step 7b

The plan claims these functions in `success_formatter.py` become unreachable after the per-node loop is deleted. I did NOT grep to confirm they have no other callers. **Before deleting them, run `rg '_format_execution_step|_format_batch_node_line' src/ tests/`** and verify the only remaining references are in `success_formatter.py` itself. If tests import these, either update the tests or keep the functions as dead code (lower-priority cleanup).

### Test count in `test_success_formatter.py`

The plan says "~40 lines of case-by-case updates". I did NOT enumerate exactly which tests break. The implementing agent needs to run the test suite and fix failures one by one. Expect:
- Tests asserting `"Nodes executed (N):"` substring — most common failure
- Tests asserting on per-node `✓ node_id (Nms)` format — second most common
- Tests asserting `⤷ Stopped after` should KEEP PASSING (preserved in the simplified function)

### Thread safety of the new smart_handled callback path

Parallel batch invokes progress callbacks from the main thread only (verified in `batch_executor.py:419-454`), so the callback itself is single-threaded. But the `call_completion_callback` function reads `shared.get(node_id, {}).get("smart_handled")` — and the batch items write to their own `item_shared` dicts, not the parent. For batch nodes, the `smart_handled` tag would not apply anyway (batch aggregates multiple items). **ASSUMPTION**: smart_handled tags are only relevant for non-batch shell nodes. If batch shell nodes need them, that's a future task.

### `_echo_trace` suppression in `-p` mode

The current `_echo_trace` at `main.py:74-92` suppresses the trace file path when `print_flag` is set. This is correct behavior but only applies to the "📊 Workflow trace saved" line. Other things that might leak into stderr in `-p` mode:
- The inline "Executing workflow (5 nodes):" echo (Step 8) — gated on `progress_enabled` in the updated plan, should be silent in `-p`
- The "cli: No outputs declared" auto-detect warning — the plan doesn't explicitly address this, but it's already gated on `not print_flag` in `_handle_text_output`
- The "cli: Warning - output key 'X' not found" message — also already gated

**NEEDS VERIFICATION**: manual test 5d should fail if any of these leak.

---

## Unexplored Territory

Things we didn't discuss but might matter during implementation or review:

**UNEXPLORED: Interactive save prompt logic.** I grepped for `should_show_prompts` but did NOT grep for how save prompts are actually triggered. If the save-prompt uses `click.confirm` directly, it has its own TTY detection and is unaffected. If it uses `sys.stdin.isatty()` directly, same. If it uses something else entirely, we might break it. The next agent should grep for save-prompt logic early and confirm it doesn't depend on `should_show_prompts`.

**UNEXPLORED: What happens to `--only` when combined with `-p` or JSON mode.** The `⤷ Stopped after` line is now emitted by the collapsed summary. In `-p` mode, the whole summary is suppressed. So the `--only` context is lost in `-p` mode. Is this acceptable? The user who uses `-p` has opted into minimal output and probably wants the data on stdout only. But they might also need to know their run was partial. CONSIDER: the `⤷ Stopped after` line could be preserved even in `-p` mode as a special exception.

**MIGHT MATTER: The `--report` flag path.** The plan doesn't touch it. `--report` generates a directory of markdown files. Its code path uses the trace collector directly and shouldn't be affected. But if the review tests exercise `--report`, any assumption about progress callback behavior there would need checking.

**UNEXPLORED: Nested workflow depth display in non-TTY.** Today's TTY display indents nested sub-workflow progress by depth. The plan says this works automatically via the `depth` parameter passed to the callback. I did NOT write a test for 3-level-deep nested workflows in non-TTY. It probably works (propagation is verified) but worth a manual test.

**CONSIDER: Backwards compat for the `output:` parameter.** The signature change from `output=` to `progress_callback=` is a breaking change for any caller. I verified no callers exist in the repo, but pflow IS published to PyPI. Are there external users calling `WorkflowRunner().run(output=...)` directly? The CLAUDE.md says "no users yet" (MVP policy), but if someone happens to be using it, this is a silent breaking change. If concerned, add a compatibility shim:
```python
def run(..., *, output=None, progress_callback=None, ...):
    if output is not None and progress_callback is None:
        progress_callback = output.create_node_callback() if hasattr(output, 'create_node_callback') else None
        warnings.warn("output= is deprecated, use progress_callback=", DeprecationWarning)
```
But per the project's MVP policy (documented in CLAUDE.md: "We have NO USERS yet"), skipping this shim is the right call.

**MIGHT MATTER: `test_execution/formatters/test_output_utils.py` imports `_handle_text_output`** (per Agent 2's report). The plan removes `output_controller` from `_handle_text_output`'s signature. If these tests pass `output_controller` as a kwarg, they'll break. NEEDS VERIFICATION.

**UNEXPLORED: The `_echo_trace` messages for `--report`.** Line 215 in main.py: `_echo_trace(ctx, f"📋 Execution report: {report_dir}")`. This is gated through `_echo_trace` which suppresses in `-p` and JSON mode. Unchanged by the refactor.

---

## What I'd Tell Myself (if starting over)

1. **Start with the user's real goal**, not the GH issue title. #194 was the blocker for "agents can't see streaming". The spec should lead with the user goal, not the bug.

2. **Verify empirically before designing**. I wasted time arguing about whether `nl=False` works in non-TTY before just testing it. 30 seconds of `cat > /tmp/test.py; python3 /tmp/test.py 2>/tmp/out` would have saved 20 minutes of speculation.

3. **Multi-agent review is cheap insurance**. The 4 review agents caught 7 critical issues I missed. Always run reviews before approving significant refactors. The skill defaults to 7-8 agents for plan reviews; don't shortcut.

4. **Trust the user's instincts on UX**. Every time the user pushed back on my design, they were right. They know their product. Default to asking when they seem to disagree.

5. **Read the plan after each major edit**. I made inconsistent edits twice during the review-response phase (Step 5 vs Step 17 on `should_show_prompts`). Re-reading the full plan after each section edit would have caught this.

---

## Open Threads

Things that are planned but not resolved:

1. **`should_show_prompts` actual usage** — verify during implementation. If save-prompt tests break on deletion, restore as minimal passthrough.

2. **`test_success_formatter.py` failing tests** — count and fix case-by-case during implementation.

3. **`_format_execution_step`/`_format_batch_node_line` deadness** — grep to confirm before deleting.

4. **Manual test 5d might show leaks** — if stderr isn't fully silent in `-p` mode, find the leak and fix it (possibly a `click.echo` that the plan missed).

5. **The "Executing workflow (N nodes):" inline echo placement in main.py** — the plan shows it inside `execute_json_workflow` replacing lines 310-311. The exact placement matters because it needs to fire AFTER `_get_output_controller` and BEFORE `runner.run()`. Don't move it to the top of the function.

---

## Relevant Files & References

**Task files:**
- `.taskmaster/tasks/task_149/task-149.md` — specification
- `.taskmaster/tasks/task_149/implementation/implementation-plan.md` — atomic step-by-step plan with line numbers, exact code, test inventory
- `.taskmaster/tasks/task_149/starting-context/braindump-20260407-planning.md` — this file

**Scratchpad (DO NOT DELETE):**
- `scratchpads/streaming-baseline/streaming-test.pflow.md` — the test workflow used throughout manual verification; referenced by Step 15d and manual tests

**Critical code files (read these first on implementation):**
- `src/pflow/cli/workflow_output.py:40-86` — the `_output_with_header` bug site
- `src/pflow/cli/workflow_output.py:520-609` — the `_display_execution_summary` that gets collapsed
- `src/pflow/core/output_controller.py:73-155` — the `_handle_*` methods (node_start nl=False, batch_progress \r, node_complete)
- `src/pflow/core/output_controller.py:180-245` — `create_progress_callback` (TTY gate at line 186 gets deleted)
- `src/pflow/execution/runner.py:50-66, 399-425` — `run()` signature + `_initialize_shared_store`
- `src/pflow/execution/formatters/success_formatter.py:283-319` — MCP's `_append_execution_steps` (the parity twin)
- `src/pflow/runtime/engine/instrumentation.py:354-449` — callback call sites
- `src/pflow/runtime/engine/batch_executor.py:381-401` — `_report_batch_progress`
- `src/pflow/nodes/shell/shell.py:198-201, 688-689` — where smart_handled is written + the stale comment
- `src/pflow/cli/main.py:295-325` — the execute_json_workflow section where DisplayManager/CliOutput are instantiated and Runner is called

**Test files to update (from biggest to smallest impact):**
- `tests/test_core/test_output_controller.py` — ~12 tests to delete/update
- `tests/test_execution/formatters/test_success_formatter.py` — case-by-case
- `tests/test_cli/test_shell_stderr_warnings.py` — delete `_format_node_status_line` tests
- `tests/test_cli/test_workflow_output_handling.py` — add 2 regression tests
- `tests/test_integration/test_cli_mcp_parity.py` — DELETE entire file

**External references:**
- GH #194 (the issue being fixed)
- `src/pflow/execution/formatters/CLAUDE.md` "Hard-Won: Update BOTH Call Sites" — Task 85 regression pattern that informed the MCP parity decision
- `scratchpads/architectural-debt/compounding-issues.md` Issue 7 — where #194 was originally flagged as agent UX critical

---

## For the Next Agent

**Start by reading in this order:**
1. `.taskmaster/tasks/task_149/task-149.md` (specification — WHAT and WHY)
2. This braindump (tacit context you'd otherwise miss)
3. `.taskmaster/tasks/task_149/implementation/implementation-plan.md` (HOW — step by step)

**Do these verifications before writing any code:**
1. `rg '_format_execution_step|_format_batch_node_line' src/ tests/` — confirm dead after Step 7b
2. Read `tests/test_execution/formatters/test_output_utils.py` — check if it passes `output_controller=` to `_handle_text_output` (if so, update)
3. Grep for how save-prompt interaction is actually triggered in CLI — confirm it doesn't depend on `should_show_prompts`
4. Read `src/pflow/core/output_controller.py` in full once — get the mental model of the event dispatch before editing

**Don't:**
- Don't try to unify everything into one rendering path — the `\r` batch counter legitimately needs a TTY guard
- Don't rename `--print` to `--quiet` — user explicitly kept the flag
- Don't add backwards-compat shims for the `output:` parameter — MVP policy, no users
- Don't skip the manual tests in Step 17 — they're the only way to verify the empirical claims about Python stderr behavior and click.echo flushing
- Don't delete `is_interactive()` from OutputController — one remaining caller in `mcp_sync.py`
- Don't batch all changes into one commit — the plan suggests commit-by-commit order for reviewability (though the user didn't explicitly request this, it's good practice for a large refactor)
- Don't skip the failure-path manual test (5a) — the `_handle_node_complete` terminator fix is easy to forget to verify

**The user cares most about:**
1. The final code being simple (not the journey)
2. Agent UX (token efficiency + streaming visibility)
3. Not breaking the TTY interactive experience
4. Matching Claude Code conventions (keeping `-p`)

**Implementation tip**: Start with Step 1 (the core `_output_with_header` fix) because it's the smallest, most focused change. Verify it works end-to-end with the scratchpad workflow before touching anything else. Then work outward.

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
