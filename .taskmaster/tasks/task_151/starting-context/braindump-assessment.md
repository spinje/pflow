# Braindump: Task 151 — Split core/diagnostic.py

## User's Mental Model

1. **Maximum impact for minimum effort** — "highest leverage" was the framing, not "biggest refactor" or "most needed cleanup"
2. **Informed by history** — they wanted the task reviews read first because they contain hard-won patterns that should inform future structural work
3. **Thorough investigation** — they explicitly said "investigate the codebase thoroughly," suggesting they've been burned by shallow analysis before

## Key Insights

### Why diagnostic.py won over 4 other candidates

The full candidate comparison that shaped the recommendation:

1. **diagnostic.py (870 lines)** — WON. 25+ consumers, clean split boundary, ~18 files get 7x import cost reduction. The data model is stable (barely changed since Task 143). The rendering grew through Tasks 144, 147, 148 and will keep growing.

2. **node_output_formatter.py (944 lines)** — Runner-up. Three clean internal subsystems (core formatting ~300, path extraction ~270, smart display ~300). BUT only 3 external consumers. Low blast radius = low leverage. This is the recommended NEXT refactor.

3. **registry/context_builder.py (869 lines)** — Rejected. Only 2 external consumers. Self-contained. Not worth the coordination cost.

4. **Misplaced CLI files in core/ (output_controller, shell_integration, trace_report, execution_cache — ~1,961 lines)** — Rejected. High effort (many import paths), modest navigability gain. Correct observation but wrong time — this is a "gradual cleanup" not a single refactor.

5. **core/ root-level reorganization (23 files)** — Rejected. Most concern groups have 2-4 files — below the 5-file subdirectory threshold. Forced grouping would create artificial directories.

### The scenario analysis that clinched it

I traced 6 real agent tasks through the codebase and found 4 of 6 benefit from the split. The key insight: template validation work, runtime engine work, batch debugging, and adding new error categories ALL load diagnostic.py but most only need the data model. The only scenarios that need the full file are CLI output fixes and adding new rendering categories — and even those benefit from having a smaller, focused rendering file.

### The `_CATEGORY_TITLES` decision is subtle

`executor_service.py` imports `_CATEGORY_TITLES` — a private symbol — from `diagnostic.py`. I decided it stays in `diagnostic.py` (data model) because it's a data lookup dict, not a rendering function. But this is debatable. ASSUMPTION: The implementing agent should verify this import still exists and decide whether to make it public (rename to `CATEGORY_TITLES`) during the refactor. It's a private symbol being imported cross-module, which is a code smell regardless of which file it lives in.

### The dedup invariant is load-bearing

`format_child_provenance` at line 105 has an extensive docstring explaining the dual-propagation-path dedup architecture. It MUST stay in `diagnostic.py` (not `diagnostic_render.py`) because both `core/workflow/validator.py` and `runtime/workflow_executor.py` import it, and neither needs rendering. If it moves to the renderer, those two files would need a rendering import just for identity formatting. The function itself is trivial (one line: `return f"In step '{step_id}' sub-workflow: {message}"`), but its placement is architecturally significant.

### `core/__init__.py` doesn't export diagnostic symbols

The `core/__init__.py` only exports 5 symbols: `FLOW_IR_SCHEMA`, `SchemaValidationError`, `StdinData`, `normalize_ir`, `validate_ir`. ALL diagnostic imports are direct: `from pflow.core.diagnostic import Diagnostic`. This means there are no `__init__.py` re-exports to worry about — every consumer explicitly names the source module.

### The lazy imports pattern

Two rendering functions have lazy imports of `security_utils.sanitize_parameters`: `_format_api_response_lines` (line 720) and `_format_mcp_error_lines` (line 742). And `exception_to_diagnostics` has a lazy `from dataclasses import replace` (line 794). These lazy imports are for import-time cost avoidance, not circular dependency breaking. They move with their functions — no special handling needed.

## Assumptions & Uncertainties

ASSUMPTION: The ~18 data-model-only consumers I catalogued are complete. I used subagent grep results, but there may be edge cases in test files or scripts/ that import diagnostic symbols I didn't catalog. The implementing agent MUST run a fresh `grep -rn "from pflow.core.diagnostic import" src/ tests/` before starting.

ASSUMPTION: `exception_to_diagnostics` is only used by display-layer code. I verified this through the subagent analysis, but the implementing agent should confirm with grep. If runtime code calls it, the split boundary changes.

UNCLEAR: Whether any test `conftest.py` files import from diagnostic.py. These are easy to miss in grep because they might use wildcard imports or indirect paths.

NEEDS VERIFICATION: The mock.patch sweep. I provided commands in the task file but never ran them. The implementing agent MUST run these before starting implementation — mock.patch targets are the #1 post-refactor surprise (documented in every recent task review).

NEEDS VERIFICATION: Whether `diagnostic_render.py` is the right name. Alternatives: `diagnostic_format.py` (matches `format_diagnostic`), `diagnostic_display.py`. The current name mirrors the internal function naming (`_render_*` helpers). But the public API is `format_diagnostic` — `diagnostic_format.py` might be more discoverable.

ASSUMPTION: No re-exports needed. I decided "clean break, no backward-compat shims." This is consistent with the CLAUDE.md note "We have NO USERS yet." But if any third-party or script imports exist that I missed, they'd break silently.

## Unexplored Territory

UNEXPLORED: **Test file organization.** `test_core/test_diagnostic.py` presumably tests both the data model and the rendering. After the split, should tests split too? Or should one test file import from both modules? The refactor instructions say "Don't add new tests" but existing test imports need updating. If the test file is large, splitting it might improve agent navigability for the same reasons the source split does.

UNEXPLORED: **Dead code in diagnostic.py.** I read every line but didn't grep for callers of each private function. The refactor instructions say "Dead code analysis FIRST." Some rendering helpers might be unused after Tasks 147/148 made changes. Removing dead code before splitting changes the line counts and potentially the split boundary.

CONSIDER: **`_CATEGORY_TITLES` as a public API.** It's imported cross-module by `executor_service.py` (private symbol crossing boundaries). The refactor is an opportunity to either: (a) make it public (`CATEGORY_TITLES`), (b) move it to a more appropriate location, or (c) document why it's OK as-is. Low stakes (importance 1-2) but worth noting.

MIGHT MATTER: **The `from __future__ import annotations` at line 3.** This is a module-level import that affects type annotation behavior. Both new files need it if they use `str | None` style annotations (they do).

UNEXPLORED: **Whether `diagnostic_render.py` should be in `core/` or `execution/`.** The rendering functions are consumed exclusively by display-layer code (CLI, formatters). Architecturally, rendering belongs in `execution/` not `core/`. BUT: moving it there would create a circular dependency — `execution/` imports from `core/`, so `core/exceptions.py` (which has `to_diagnostics()`) can't import from `execution/`. The current placement is correct, but the reasoning isn't documented.

CONSIDER: **Impact on `core/CLAUDE.md`.** The CLAUDE.md has a detailed section on `diagnostic.py` covering template error rendering, WARNING-severity dispatch, multi-output errors, `At:` location format, and block fallbacks. After the split, this documentation needs to split too — data model docs stay with `diagnostic.py`, rendering docs move to a `diagnostic_render.py` section. The CLAUDE.md is 323 lines; this change affects ~40 lines of it.

MIGHT MATTER: **The `exceptions.py` → `diagnostic.py` import direction.** `exceptions.py` imports `Diagnostic` and `Severity` from `diagnostic.py` (for `to_diagnostics()` methods). After the split, this import stays clean — exceptions only need the data model. But if someone later wants exceptions to carry rendering logic, the split boundary would prevent it. This is actually a FEATURE of the split (separation of concerns), not a risk.

## What I'd Tell Myself

1. **Run the mock.patch sweep FIRST.** Before writing any code, before planning the split, before anything. Build the complete consumer table with exact line numbers. The task file has the grep commands. This is the #1 lesson from every recent task review.

2. **Read the full test file before splitting.** If `test_diagnostic.py` is 500+ lines, understand its structure before deciding how imports change. Tests that only test the data model vs. tests that test rendering — the boundary should be visible.

3. **Don't rename anything.** The refactor instructions are explicit: "Don't change any logic, don't add new tests, don't 'improve' code while moving it." The temptation to rename `_CATEGORY_TITLES` or clean up a docstring is strong. Resist.

4. **The `executor_service.py` import of `_CATEGORY_TITLES` is the trickiest consumer.** It imports a private symbol from diagnostic.py. After the split, it stays importing from diagnostic.py, but a future agent might think it "should" come from diagnostic_render.py because "titles" sound like rendering. Add a comment or CLAUDE.md note explaining why it lives where it does.

5. **Two `make check` runs.** After relative import changes, ruff auto-fixes import ordering on the first run (exit code 1), then passes clean on the second. Don't panic at the first failure. This is documented in the refactor skill but easy to forget.

## Open Threads

- **node_output_formatter.py is the next candidate.** I mentioned this to the user as the "secondary candidate (next refactor)." If they ask for the next refactor after this one, the analysis is already done: three subsystems (core formatting, path extraction, smart display), few external consumers, clean internal boundaries.

- **The broader `core/` organization question.** Four CLI-specific files (~1,961 lines) live in core/ but serve display concerns. This wasn't recommended as the current refactor (too much effort for modest gain), but it's the right direction long-term. Each time a file in core/ is touched for another reason, consider whether it should migrate.

- **Whether this refactor should have a scratchpad.** The refactor skill says to write a detailed plan to `scratchpads/<refactor-name>/PLAN.md`. The task file is comprehensive, but a separate PLAN.md with the exhaustive method-to-file mapping table and consumer impact table would be valuable during implementation. The implementing agent should create this before coding.

## Relevant Files & References

**The file being split:**
- `src/pflow/core/diagnostic.py` — 870 lines, read in full during this conversation

**Documentation to update:**
- `src/pflow/core/CLAUDE.md` — ~40 lines about diagnostic.py need splitting between two entries

**Task reviews with relevant patterns:**
- Task 143 review: created the Diagnostic type, dual-propagation-path architecture
- Task 144 review: polymorphic rendering, three-layer model (exception → data → rendering)
- Task 147 review: producer-supplied context, first-write-wins merging
- Task 148 review: failure-category rendering, per-reference classification

**The refactor skill itself:**
- The `/refactor` skill prompt has detailed Phase 2-7 instructions including mock.patch sweeps, consumer audits, bulk replacement strategy, and verification checklists. The implementing agent should re-read it.

## For the Next Agent

**Start by:**
1. Read the task file (`.taskmaster/tasks/task_151/task-151.md`) — it has the full design decisions and requirements
2. Read this braindump — it has the tacit knowledge
3. Run the mock.patch sweep commands from the task file
4. Run `grep -rn "from pflow.core.diagnostic import" src/ tests/` for the complete consumer list
5. Read `src/pflow/core/diagnostic.py` in full (870 lines) — map every function to its target file
6. Create a PLAN.md in `scratchpads/split-diagnostic/` with the method-to-file mapping table

**Don't bother with:**
- Re-analyzing whether this is the right refactor (the assessment was thorough, user approved)
- Investigating other modules (stay focused on diagnostic.py)
- Reading the task reviews again (the patterns are captured here and in the task file)

**The user cares most about:**
- Zero behavior change (tests must pass identically)
- Clean split (no re-exports, no backward compat shims)
- Thoroughness (every consumer updated, every mock.patch fixed, every CLAUDE.md reference caught)

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
