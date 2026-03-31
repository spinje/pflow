# Braindump: Exception Hierarchy Consolidation (Task 141)

## Where I Am

Research phase complete. Task spec written. No implementation started. Six parallel research agents verified every assumption. The user approved scope including the ValueError miscategorization fix (Finding 2).

## User's Mental Model

The user came into this conversation to evaluate next steps after completing Tasks 138 (shared execution pipeline) and 135 (execution core redesign / orchestration engine). These were the two biggest structural fixes in the architectural debt sweep. They wanted to assess "what's left."

After reading the four documents (compounding-issues, handoff, two task reviews), I presented the full status of the 10 compounding issues and recommended options. The user chose to look at #185 specifically.

The pivotal moment: after I presented Option A (minimal move), Option B (move + UserFriendlyError family), and Option C (move + rebase), the user asked: **"what would be the most correct fix, that a top 10% codebase would do?"** This is the design directive. They don't want the safe minimal fix — they want the architecturally correct one. This reframing led to the rename + rebase approach.

Then they pushed further: **"If our endgoal would be a coherent exception hierarchy like a top 1-10% codebase. What would be the next steps? How bad is the issue right now and what would solving it mean? lets take a step back"** — they wanted the holistic view, not just the tactical fix. This led me to frame the problem as "four independent trees → one tree" and articulate what the end state actually buys.

The user's unstated priority: they want pflow's codebase to be exemplary. They're building for quality, not speed. Every decision should be the one you'd make if designing from scratch with zero users (which is the actual situation per CLAUDE.md).

## Key Insights

### The ValueError miscategorization is a real find

When researching what ValueErrors reach `_exception_to_result`, agent #5 discovered that node execution errors (HTTP timeouts, GitHub API failures, git push rejections) are categorized as `category: "validation"` when they should be `category: "execution_failure"`. This is a pre-existing bug unrelated to our rebase. The user explicitly said "yes Finding 2 in scope" — they value compound fixes that clean up adjacent issues found during research.

The discriminator is clean: `_pflow_node_id` is set by the engine (engine.py:307) and the runner's `_compile_and_execute` (runner.py:200) — only for exceptions from node execution. Pre-execution ValueErrors (from resolution, IR parsing) never have it. Three lines to fix.

### The MarkdownParseError(ValueError) hack has exactly one consumer

The docstring says "so existing `except ValueError` catches still work." The exhaustive search found exactly one site that actually relies on this: `test_workflow_executor_comprehensive.py:226` with `pytest.raises(ValueError)`. Zero production code relies on it. The hack was probably needed during initial development but every catch site evolved to catch `MarkdownParseError` explicitly.

### CompilationError cleanup is bigger than #185 suggests

The issue says "4 sibling modules." The actual count is: 5 lazy imports in compilation/ siblings, 2 in engine.py, 3 in runner.py, 1 redundant in batch_executor.py. Plus `compile_validation.py` has a weird pattern where it PASSES `CompilationError` as a function parameter (line 102/160) to avoid a second lazy import. After converting to module-level, that parameter should be removed.

### The runner.py validate() method needs a small touchup

Line 282 catches `(WorkflowNotFoundError, ValueError, PermissionError, FileNotFoundError)`. After MarkdownParseError rebase, parse errors fall through to line 294's `except Exception` which handles them correctly (same result). But it would be cleaner to add `MarkdownParseError` to the first tuple — makes the intent explicit. The task spec says "could optionally" — I'd recommend doing it.

### core/__init__.py re-export decision

Currently: `from .ir_schema import FLOW_IR_SCHEMA, ValidationError, normalize_ir, validate_ir`. After rename, this becomes `from .ir_schema import FLOW_IR_SCHEMA, SchemaValidationError, normalize_ir, validate_ir` — BUT the re-export in ir_schema.py maps the old name. Tests use both `from pflow.core import ValidationError` and `from pflow.core.ir_schema import ValidationError`. The implementing agent needs to update BOTH the re-export in `__init__.py` and all test imports. Don't forget the `__all__` list.

## Assumptions & Uncertainties

ASSUMPTION: All lazy imports of these exceptions exist because of circular import risk from the heavy modules, not for other reasons (like startup performance). After moving to `core/exceptions.py` (a leaf), all can be module-level. This was verified — `core/exceptions.py` imports only from `typing`.

ASSUMPTION: The `runner.py` lazy imports (lines 299, 328, 492) currently import from `pflow.runtime` (which re-exports from compilation). Switching to `from pflow.core.exceptions import CompilationError` should be safe at module-level because there's no `runner.py → core.exceptions → runner.py` cycle. Verified: `core.exceptions` imports nothing from pflow.

ASSUMPTION: The re-export in `ir_schema.py` (for backward compat) won't be needed by external tools. Per CLAUDE.md: "We have NO USERS yet." But the re-export is one line and costs nothing, so I recommended keeping it as a safety net.

NEEDS VERIFICATION: After converting all compilation/ lazy imports to module-level, verify that the circular import that originally caused the lazy pattern is truly broken. The chain was: `compiler.py` → (something) → `compile_validation.py` → `compiler.py`. With `CompilationError` no longer imported from `compiler.py` by siblings, the cycle should be broken. But run `python -c "from pflow.runtime.compilation import compiler"` to confirm.

UNCLEAR: Whether the `error_output.py:_is_markdown_parse_error()` helper function (line 272-276) should be eliminated after the move. It exists solely to avoid the heavy import. After the move, a module-level import from `core.exceptions` is trivial. The helper becomes dead abstraction. I'd remove it, but it's not in the task spec.

## Unexplored Territory

UNEXPLORED: **`compile_validation.py`'s CompilationError-as-parameter pattern.** Line 102: `_validate_data_flow_at_compile_time(ir, compilation_error_cls)` receives the exception class as a parameter. Line 160 passes it: `_validate_data_flow_at_compile_time(ir, CompilationError)`. This is clever but obscure. After converting to module-level import, the function can import directly and the parameter is dead. But changing a function signature might affect tests that call it directly. Check if any test calls `_validate_data_flow_at_compile_time` directly.

CONSIDER: **Should `runner.py:validate()` add MarkdownParseError to its first except tuple?** Currently catches `(WorkflowNotFoundError, ValueError, PermissionError, FileNotFoundError)`. After rebase, MarkdownParseError no longer caught here. The fallback `except Exception` handles it fine (same result). But explicit is better than implicit — adding it documents the intent. Low effort, high clarity.

MIGHT MATTER: **The `error_output.py` dispatch chain order.** Currently: WorkflowValidationError → WorkflowNotFoundError → MCPError → OutputResolutionError → UserFriendlyError → MaxNodeVisitsError → MarkdownParseError → IrSchemaValidationError → FileNotFoundError → PermissionError → fallthrough. After our changes, SchemaValidationError replaces IrSchemaValidationError and MarkdownParseError stays in the same position. No reordering needed. But the implementing agent should understand that MCPError/OutputResolutionError MUST be checked before UserFriendlyError (subclass before parent).

MIGHT MATTER: **`_exception_to_result` in runner.py will have a MarkdownParseError branch that extracts `.line` and `.suggestion`.** These fields don't exist on the current error dict shape for this exception type. The CLI error output pipeline (`workflow_errors.py`, `error_output.py`) would need to handle these new fields in the error dict. Check if the error display code renders `line` and `suggestion` from the error dict — it might just show `message` and ignore extra fields. If so, the new fields are invisible until someone adds display support.

UNEXPLORED: **Whether to add `MarkdownParseError` to `core/__init__.py` exports.** Currently not exported from `core/__init__.py` (only `ValidationError`, `FLOW_IR_SCHEMA`, etc.). The task spec doesn't address this. Probably not worth it — `from pflow.core.exceptions import MarkdownParseError` is the canonical path.

CONSIDER: **The `_is_markdown_parse_error()` helper in `error_output.py:272-276`.** This exists to avoid importing from the heavy `markdown_parser.py`. After the move, `from pflow.core.exceptions import MarkdownParseError` is cheap. The helper becomes unnecessary abstraction. Inline the isinstance check and delete the helper. Not in task spec — flag for implementing agent.

## What I'd Tell Myself

1. **The task spec is comprehensive.** Read it, don't re-research. The six parallel agents already verified every assumption.

2. **Phase order matters.** Move the classes first (Phase 1), then rebase UserFriendlyError (Phase 2), then fix imports (Phase 3), then fix ValueError categorization (Phase 4). Phase 3 depends on Phase 1 because the import targets change. Phase 4 depends on Phase 1 because MarkdownParseError needs its own branch.

3. **The one breaking test is at `test_workflow_executor_comprehensive.py:226`.** This is `pytest.raises(ValueError)` catching a MarkdownParseError. Change to `pytest.raises(MarkdownParseError)`. Don't forget the import.

4. **Don't forget `__all__` lists.** `core/__init__.py`, `core/exceptions.py` (if it has one), `ir_schema.py` — all need updating when the name changes.

5. **The compile_validation.py parameter pattern** at line 102/160 is the trickiest part. The function receives CompilationError as a parameter. After making the import module-level, remove the parameter from the function signature and import directly inside the function body. Check if any test calls this function directly.

6. **Run `make test && make check` after every phase.** The rename touches ~40 import sites. Typos will happen. Catch them early.

7. **The user approved the full scope including Finding 2** (ValueError miscategorization). Don't skip it. It's ~3 lines but addresses a real categorization bug.

## Open Threads

1. **`_is_markdown_parse_error()` helper elimination** — not in task spec, but it becomes dead abstraction after the move. The implementing agent should inline it.

2. **`runner.py:validate()` first except tuple** — should MarkdownParseError be added explicitly? Functionally identical either way, but explicit is better.

3. **New error dict fields for MarkdownParseError** (`.line`, `.suggestion`) — the task spec adds them to `_exception_to_result`, but does the error display pipeline render them? If not, they're invisible. Could be a follow-up.

4. **Whether to update the compounding-issues.md** — Issue 7 status should be updated to reflect this task. But the document is already long and mostly marked done. The user might prefer to just note completion in the handoff doc instead.

## Relevant Files & References

### Must-read before implementing
- Task spec: `.taskmaster/tasks/task_141/task-141.md` — THE document, covers everything
- Current exceptions: `src/pflow/core/exceptions.py` — target file, read to understand current hierarchy
- Current user errors: `src/pflow/core/user_errors.py` — one-line change here
- ValidationError class: `src/pflow/core/ir_schema.py:75-114` — moving + renaming this
- MarkdownParseError class: `src/pflow/core/markdown_parser.py:31-53` — moving + rebasing this
- The duck-type hack: `src/pflow/execution/runner.py:545` — must fix
- ValueError miscategorization: `src/pflow/execution/runner.py:541-544` — must fix

### Good to skim
- Error dispatch chain: `src/pflow/cli/error_output.py:142-189` — understand the dispatch order
- CompilationError move precedent: `.taskmaster/tasks/task_135/task-review.md` — how Task 135 did the same thing for CompilationError
- GitHub issue: #185 — original issue description

### Don't bother re-reading
- `scratchpads/architectural-debt/compounding-issues.md` — massive file, mostly historical. The task spec captures everything relevant.
- `scratchpads/handoffs/architectural-debt-fixes.md` — same, historical context already distilled.
- Individual agent research outputs — findings are captured in this braindump and the task spec.

## For the Next Agent

**Start by**: Reading `.taskmaster/tasks/task_141/task-141.md` (the task spec). It has the full import site inventory, the target hierarchy, and the implementation notes.

**Don't bother with**: Re-researching the codebase. Six parallel agents already did exhaustive searches. The task spec's import site inventory is complete and verified.

**The user cares most about**: Architectural correctness. They asked "what would a top 1-10% codebase do?" — that's the quality bar. Don't cut corners.

**Watch out for**:
- The `compile_validation.py` CompilationError-as-parameter pattern (line 102/160) — it's the most non-obvious change
- The `_is_markdown_parse_error()` helper in `error_output.py:272-276` — eliminate it after the move (dead abstraction)
- `core/__init__.py` `__all__` list — must update the re-export name
- Test imports use inconsistent paths (`pflow.core` vs `pflow.core.ir_schema`) — update ALL of them to `pflow.core.exceptions`

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
