---
description: Plan and execute structural refactors (file splits, subdirectory extraction, module reorganization).
---

# Structural Refactor — Execution Guide

You are executing a structural refactor with zero behavior change. The refactoring target and desired shape should already be identified — if anything is still unclear, any ambiguity remains, or you have unverified assumptions, stop and resolve these before proceeding.

## Execution priorities

Before starting, align with the user on approach:

- **Minimal risk**: Touch as few files as possible, re-export for backward compat?
- **Architectural correctness**: Get the structure right even if it means more changes?

This changes the plan. Risk-minimizing keeps files flat. Architecture-focused creates subdirectories and updates every consumer.

## Phase 1: Deep Read

Once you know WHAT to refactor, understand it thoroughly before planning.

### Dead code analysis FIRST

Before proposing any structure, find and remove dead code. Dead functions change the scope — a file that looks like 821 lines might be 580 after removing 8 unused functions left behind by a formatter migration. Run dead code analysis on every file you're considering splitting.

Use searcher subagents in parallel: "Is function X called anywhere in the codebase?" For each file being refactored, check every private function (`_name`) — these are the most likely candidates.

**Why first**: Dead code inflates your line counts, complicates your call graph, and may create phantom dependencies that influence split boundaries. Removing it simplifies every subsequent step.

### Read the entire file yourself

Do NOT rely on subagent summaries for the file being refactored. Read it line by line. Map:
- Every function, class, constant, and module-level item
- The internal call graph (which functions call which)
- Dead code (defined but never called — verify with grep)

### Build the internal call graph for large files

For files over ~500 lines that you plan to split, map which internal functions call which other internal functions. Use a subagent: "For every function in file X, list which OTHER functions in the same file it calls, with line numbers."

This catches:
- **Cross-group dependencies**: Function A (proposed for file_x.py) calls function B (proposed for file_y.py) — you need an import between the new files
- **Shared utilities**: A serialization helper called by both success and error paths — it must live in one file and be imported by the other
- **Circular import risks**: If group A calls group B AND group B calls group A, you have a cycle. Resolve before planning.

The call graph determines split boundaries. Without it, you're guessing.

### Audit all consumers

```bash
grep -rn "from <module> import" src/ tests/
grep -rn "from \.\.*<module> import" src/    # relative imports — easy to miss!
grep -rn "<ClassName>" src/ tests/            # includes mock.patch string paths
```

Categorize each consumer:
- **Production code**: direct imports, lazy imports inside functions, **relative imports** (e.g., `from ..core.module import X`)
- **Test code**: imports, `mock.patch()` string targets, docstring references
- **Documentation**: CLAUDE.md references, comments

### Mock.patch is a first-class consumer — sweep comprehensively

`mock.patch("module.path.ClassName")` is a string. It won't fail at import time — it fails at **runtime** with confusing `AttributeError`. This makes mock.patch the #1 source of post-refactor surprises.

Run this sweep ONCE at the start, not incrementally:
```bash
# Find ALL mock.patch targets for the module being refactored
grep -rn "mock.patch.*<module_path>" tests/ --include="*.py"
grep -rn "patch(\"<module_path>" tests/ --include="*.py"
grep -rn "patch('<module_path>" tests/ --include="*.py"
```

Build a complete table: file, line, exact patch target string. Include this in the plan. Every string must be updated when the module moves — there is no tooling that catches these automatically.

### Check for existing analysis

Look in `scratchpads/` for prior work. If a spec exists, **verify key claims against the actual code** — specs may be outdated or wrong. Specifically check: symbol names actually exist, import counts match reality, line numbers are current, proposed `__init__.py` re-exports match real function names. Trust code over documentation.

## Phase 2: Identify Split Boundaries

### The core principle: split by concern, not by category

**Right:** Each file owns its detection logic AND its error formatting. They change together, so they live together.

**Wrong:** Extracting "all error formatting" into one file. This creates a dumping ground (a category, not a responsibility) and leaves a large remainder.

### Decision framework for each function

Ask: "When this function changes, what other functions must change too?" Functions that co-change belong in the same file. Functions used by multiple files belong in a shared module.

### Dependency graph must be acyclic

Draw the dependency graph between proposed files. If you find a cycle, the boundaries are wrong. Restructure until the graph is a DAG.

### Framework objects resist extraction

Functions that use a framework's context object (Click's `ctx`, Flask's `request`, Django's `self.request`) or module-level helpers that multiple groups depend on (like a `_log_trace()` utility) resist extraction. Moving them creates circular imports because:
1. The extracted module imports the utility from the orchestrator
2. The orchestrator imports the extracted functions
3. Cycle.

**Solutions in order of preference:**
1. **Keep the function in the orchestrator** — if it calls `ctx.exit()` or uses framework state, it's orchestration, not a separate concern
2. **Pass the dependency as a parameter** — change `_auto_discover(ctx)` to `_auto_discover(show_progress: bool)` to break the framework coupling
3. **Duplicate small helpers** — if a utility is <15 lines and only needed to avoid a cycle, copy it. Document the duplication in CLAUDE.md. This is better than creating a `shared_utils.py` for one function.

**How to detect**: After assigning functions to proposed files, check each cross-file call. If file A calls a function in the orchestrator AND the orchestrator imports from file A, you have a cycle. The function in the orchestrator must stay or the dependency must be broken.

### Naming conventions shift with visibility boundaries

When a method moves from class-private (`ClassName._method()`) to module-level:
- If it's the module's public API (imported by other modules): drop the underscore
- If it's internal to the module: keep the underscore
- The module IS the encapsulation boundary now

### Subdirectory decision

A subdirectory earns its keep when:
- 5+ cohesive files that change together for the same reason
- Enough internal complexity to warrant a dedicated CLAUDE.md
- External consumers would benefit from a clean `__init__.py` re-export API

**Cohesion trap**: Don't measure cohesion by import coupling alone. Files that barely import from each other can still be highly cohesive if they share an architectural concept (e.g., wrapper chain), a protocol (e.g., `_run(shared)` interception), or a single consumer that assembles them. Import coupling is a narrow proxy — conceptual cohesion matters more for agent navigability and CLAUDE.md scoping.

Do NOT create subdirectories for:
- Categories ("utils/", "helpers/") — these become dumping grounds
- Fewer than 5 files — the directory adds friction without discoverability benefit
- Files that don't form a cohesive group (just happen to be nearby)

If creating a subdirectory, do the split AND the move in one pass. Two passes means touching every consumer file twice for no benefit.

### `__init__.py` public API design

When creating a subdirectory with `__init__.py`, only re-export symbols that external consumers actually import. Audit with grep, don't guess.

- **Re-export**: Functions/classes imported by code outside the package
- **Don't re-export**: Private helpers (`_function`) used only by tests — tests import directly from the submodule (e.g., `from package.module import _helper`)
- **Don't re-export**: Internal functions only used between files within the package

The `__init__.py` IS the package's public API. Polluting it with test helpers or internal wiring defeats the purpose of having one.

### `__init__.py` transitive loading cost

Eager imports in `__init__.py` fire whenever the *package* is imported — including via the parent `__init__.py`. If `parent/__init__.py` does `from .subpackage import X`, every eager import in `subpackage/__init__.py` loads transitively for ALL consumers of `parent/`.

Before maintaining backward-compat re-exports in a parent `__init__.py`, **verify they have actual consumers**: `grep -rn "from pflow.<parent> import <symbol>" src/ tests/`. Dead re-exports add import-time cost for zero benefit.

## Phase 3: Write the Plan

Write a detailed plan to a scratchpad (`scratchpads/<refactor-name>/PLAN.md`).

### 3.1 Exhaustive method-to-file mapping

Every single function, constant, class, and module-level item must appear in exactly one target file. Use a table:

```
| Item | Current location (line) | Target file | Reason |
```

This is the most important artifact. If an item is missing from the plan, it will be missing from the implementation.

### 3.2 Dependency graph

```
orchestrator.py
  ├── imports from: path_validation → utils
  ├── imports from: type_validation → type_checker (pre-existing)
  └── imports from: batch_validation → path_validation, utils
```

Verify: no cycles, no file imports from the orchestrator (except the entry point).

### 3.3 Consumer impact table

| File | Current import | After refactor |
|------|---------------|----------------|

Include mock.patch string targets — these are easy to miss.

### 3.4 What to delete

Identify dead code found during the audit. Refactoring is the right time to remove it. List each item with evidence (grep showing zero callers).

### 3.5 What NOT to do

- Don't change any logic
- Don't add new tests (existing tests validate correctness)
- Don't "improve" code while moving it
- Don't add docstrings, comments, or type annotations to code you didn't write

## Phase 4: Implement

### Layer large refactors

When a refactor touches 10+ files or combines multiple types of changes (splits + moves + dead code), split into layers where each layer leaves the codebase in a passing state:

1. **Layer by dependency**: Do extractions before moves. If you split a large file into several files (Layer 1) and then move files to a subdirectory (Layer 2), Layer 2's import paths depend on Layer 1 being complete.
2. **Layer by blast radius**: Internal-only changes first (extractions from one file), then cross-module changes (moves that affect imports everywhere), then cosmetic cleanups (renames, DRY).
3. **Commit between layers**: Each layer gets its own commit. If Layer 2 goes wrong, you can revert to Layer 1's clean state.

**Why this matters**: If you do extractions and moves simultaneously and tests fail, you can't tell whether the failure is from a bad extraction or a broken move. Layering gives you bisectable history.

### Execution order (within each layer)

1. **Baseline**: `make test && make check` — record pass count
2. **Create new files** in dependency order (leaves first): utils → leaf modules → orchestrator
3. **Rewrite the original file** as the orchestrator (if it stays as entry point)
4. **Update production imports** — for deterministic string replacements, use `sed` with `grep -rl` (see below)
5. **Intermediate checkpoint**: `make check` — mypy catches broken imports before you touch tests
6. **Delete old source files** if not already removed by `git mv`
7. **Update test imports and patch strings** — again, `sed` for deterministic replacements
8. **Delete old test files** and **verify**: `make test && make check` — pass count should match baseline (minus any deleted dead-code tests)
9. **Final grep**: confirm zero references to old class/function names in src/ and tests/

### Bulk replacement strategy

**For deterministic string replacements** (import paths, patch strings), use `sed` directly:

```bash
grep -rl "from pflow.old.path import" src/ --include="*.py" | \
  xargs sed -i '' 's/from pflow\.old\.path import/from pflow.new.path import/g'
```

This is faster and more reliable than subagents for simple substitutions. It can't misinterpret context, can't write to wrong files, and can't silently fail.

**For transformations requiring judgment** (deciding lazy vs top-level, restructuring multi-line imports, updating code that references moved symbols in complex ways), use subagents with:
- ONE clear instruction per subagent
- The complete list of files to update
- Explicit file paths at their NEW locations (after `git mv`)
- The instruction to NOT change any logic

**Critical after `git mv`**: If files have been moved, subagents may read/write to old paths, recreating deleted files. Either: (a) give subagents explicit new paths, (b) delete old files before delegating, or (c) verify old files don't reappear after subagent work.

**Subagent quality bar**: Searcher agents find information — give them specific questions. Implementer agents execute changes — give them exact verified content (file paths, line numbers, before/after text), not vague "around line X" guesses. Read the code yourself before dispatching implementers. One focused task per agent.

### Verifying changes applied

After bulk replacements or subagent work, immediately grep for the OLD pattern:

```bash
grep -rn "old_pattern" src/ tests/ --include="*.py"
# Must return zero matches
```

If matches remain, changes didn't apply. Don't proceed to the next phase — diagnose first.

## Phase 5: Verify Completeness

### Automated checks

```bash
make test                    # Must match baseline (minus deleted dead-code tests)
make check                   # ruff + mypy + deptry must pass
```

### Stale reference sweep

Grep for ALL old path patterns across the **entire** codebase — not just `src/` and `tests/`:

```bash
# Code imports (src + tests)
grep -rn "old_module_name" src/ tests/

# CLAUDE.md files project-wide
grep -rn "old_module_name" --include="CLAUDE.md" .

# Architecture docs and code examples
grep -rn "old_module_name" architecture/ docs/

# String-based mock.patch targets (won't fail at import time!)
grep -rn "old_module_name" tests/ --include="*.py"

# Docstrings referencing old class/module names
grep -rn "OldClassName" src/ tests/

# Bare file paths in docs (e.g., "Located: src/pflow/runtime/old_file.py")
grep -rn "old_file_name\.py" architecture/ docs/ src/ tests/
```

### Terminology sweep

The symbol-level grep above catches import paths and class names. But renames leave *vocabulary* behind — comments, docstrings, error messages, variable names. After renaming `planning` → `discovery`, you'll still find "repairable", "triggers repair", "planner" scattered across prose in 70+ files.

Build a list of the old subsystem's domain terms (not just symbol names) and grep for those separately:

```bash
# Domain vocabulary — terms that won't appear in import paths
grep -rn "repairable\|triggers repair\|planner" src/ tests/ --include="*.py" --include="*.md"
```

This is a separate pass from the import sweep. Do it after imports are clean.

### Naming review

After all moves are complete, review every filename in the new structure. Names that were fine in the old context may be wrong in the new one. For example, `node_wrapper.py` was acceptable at the `runtime/` level, but inside a `wrappers/` directory it's generic — every file there wraps nodes. It should be `template_wrapper.py`.

Ask for each file: "If I saw only this filename in `ls` output, would I know what it does?" If the answer is "it could be any of several files," the name is too generic for its new context.

### Migration audit

Use a subagent to verify every item from the Phase 3 mapping exists in exactly one target file:
- Items in ZERO files = missed migration
- Items in MORE THAN ONE file = duplication
- Deleted items should be in ZERO files

### Check for accidental duplicates

Constants are easy to duplicate accidentally (defined in old location AND new location). Grep for each constant name across all new files.

## Phase 6: Documentation

**Content placement principle**: Agents in subdirectories automatically see parent CLAUDE.md files. So:
- **Subdirectory CLAUDE.md**: per-file non-obvious details, internal dependencies, known issues, key lessons — content only relevant when working on those files
- **Parent CLAUDE.md**: cross-cutting concerns (error philosophy, integration map, security issues), brief pointer to subdirectory CLAUDE.md
- Don't duplicate between the two — the hierarchy gives agents both

**Checklist:**
- Update the parent module's CLAUDE.md — remove moved-file details, replace with pointer
- Write a focused subdirectory CLAUDE.md with the moved details
- If test files moved, add source-to-test mapping and any non-obvious test patterns
- Grep ALL other CLAUDE.md files for references to moved/renamed modules — stale references in other directories are easy to miss
- **Document "what stays and why"** for large remainder files. If the original file is still 500+ lines after extraction, future agents will ask "why wasn't X extracted too?" Document the constraint (usually circular imports, framework coupling, or single-caller functions). Without this, agents will attempt further extraction and rediscover the constraint the hard way.

---

## Reference: Test Restructuring

When source files move to a subdirectory, consider whether tests should mirror the structure.

**When to mirror:**
- The test files form a cohesive group (5+) that would benefit from `pytest tests/path/to/subdir/`
- A test-specific CLAUDE.md would help future agents understand test patterns

**What to preserve:**
- Test files organized by *behavior* (malformed detection, type checking) NOT by source file — don't rename test files to match source files 1:1
- Tests that call the public API survive refactors precisely because they don't test internals
- Check for integration tests in `test_integration/` that actually belong with the module tests

**What to change:**
- Move test files to mirrored subdirectory
- Update imports in test files
- Add `conftest.py` if needed for shared fixtures
- Write a short CLAUDE.md with source-to-test mapping table and any non-obvious patterns (e.g., "each file creates its own mock registry — intentional isolation, don't extract to conftest")

## Reference: Scope Management

Refactors expand. "Split one file" becomes "should we use subdirectories?" becomes "should we restructure tests too?" becomes "should we restructure the whole module?"

**Recognize it:** When the conversation moves from the original target to adjacent concerns, pause and name it: "We've moved from splitting file X to restructuring module Y. That's a bigger task."

**Contain or expand deliberately:**
- **Contain**: finish the original refactor, document follow-up work in the scratchpad, let the next agent pick it up
- **Expand**: if the user agrees AND you have enough context window remaining

The wrong move is expanding silently — doing more than asked without acknowledging the scope change.

**Blast radius as a scoping metric:** Count external `src/` consumers for each file group. Files with zero external consumers (only consumed within their own module + tests) have small blast radius — do them first. Files with many external consumers (imported by CLI, execution, MCP server) have large blast radius — separate session. This gives a concrete, defensible answer to "how do we scope this?" rather than relying on gut feel about complexity.

## Reference: Gotchas That Break Refactors

Hard-won knowledge from real refactors. These pass code review but fail in CI, or worse, fail silently.

**Python-specific:**
- `ClassVar[list[str]]` is valid inside a class, fails mypy at module level. When dissolving a class, change to plain type annotation.
- Recursive functions referencing the old class (`ClassName._flatten(...)`) must become `flatten(...)`. Easy to miss inside the function being moved.
- `# noqa: C901` on complex functions must be preserved. Linters re-check after the move.
- Nested closures defined inside methods reference module-level names. When moving, verify these references still resolve.

**File-move traps:**
- **`Path(__file__)` breaks in subdirectories**: Files using `Path(__file__).parent / "resources"` to find sibling directories will break when moved to a subdirectory — `__file__.parent` now points one level deeper. Grep for `Path(__file__)` and `os.path.dirname(__file__)` in every file being moved. Fix: adjust `.parent` chain or use an absolute path anchored to the package root.
- After `git mv`, the Edit tool can recreate deleted files at old paths if a subagent reads/writes to them. Always verify old files stay deleted after subagent work (`ls` the old paths).
- Relative imports (`from ..module import X`) won't match absolute-path greps. Always search for both patterns.
- **`from src.pflow.X` imports**: Some test files use `from src.pflow.module` instead of `from pflow.module`. Your `sed` patterns for `from pflow.X` won't match these. Always grep for BOTH `from pflow\.` AND `from src\.pflow\.` during consumer audits. This has tripped multiple agents.
- **`make check` needs two runs** after relative import changes: ruff auto-fixes import ordering on the first run (exit code 1), then passes clean on the second. Don't panic at the first failure — re-run immediately.
- **Logger name strings**: `logging.getLogger(__name__)` produces module-path strings. When a module moves, tests using `caplog.set_level("WARNING", logger="old.module.path")` silently stop capturing logs — no error, no test failure, just empty caplog. Grep for the old module path in logger arguments: `grep -rn "logger=.*old_module" tests/`. Also check CLAUDE.md files that advise logger names (e.g., testing gotchas sections).

**Duplication traps:**
- Same-name constants in different files (`MAX_DISPLAYED_FIELDS = 20` vs `= 500`) are DIFFERENT constants. Always grep project-wide before deciding where a constant lives.
- Re-exporting AND defining creates two valid import paths. Pick one canonical location.

**Test traps:**
- When you delete dead code, DELETE its tests too. Don't try to fix them.
- Subagents doing mechanical updates may also "fix" things you didn't ask for. Audit their diffs, not just "tests pass."
- `mock.patch("module.path.ClassName")` is a string — breakage is at runtime, not import time. Grep for string-based references.
- After tightening loose assertions, failures may indicate invalid test fixtures, not broken code. If a fixture uses a data shape that doesn't match what production code produces, the fixture is wrong.

**Simplification traps:**
- When you remove branches or collapse complex code paths, enumerate what each removed branch handled. The simplified path must either cover those cases or you've explicitly decided to drop them. Dormant code paths sometimes handle edge cases the "main" path doesn't.
- Comments like "GATED: disabled pending X" mark code for removal, not preservation. Agents consistently misread these as "do not touch."

**Naming traps:**
- Name modules for what they contain, not where they came from. Utilities extracted from `template_validator.py` aren't necessarily "validation utils" — check whether they're all validation-specific.
- Don't use aspirational names. A 2-function module doesn't need a grand name.
- **Cross-project naming collisions**: When moving or creating files, check for name collisions across the ENTIRE project, not just within the target directory. Two files with similar names in different directories may have coexisted harmlessly, but restructuring can make the collision confusing (e.g., `workflow_validator.py` alongside `core/workflow/validator.py`). If you're already moving the file, renaming costs nothing extra — same consumer update operation.

## Reference: Anti-Patterns

1. **Refactoring while restructuring**: "While we're here, let's fix this bug too." No. Pure structural refactor. Logic changes get their own commit.

2. **Category-based splits**: "All formatters in one file, all validators in another." Creates files that change for unrelated reasons.

3. **Premature subdirectories**: Directory for 2-3 files. The `__init__.py`, nesting, and cognitive overhead aren't worth it. Wait until 5+.

4. **Dumping-ground modules**: `utils/`, `helpers/`, `common/` with no qualifier attract every homeless function. Name by contents: `validation_utils`, not `runtime_utils`.

5. **Renaming during restructure**: Changing function names, file names, AND locations simultaneously. Track each transformation explicitly in the plan if you must combine them.

6. **Ignoring mock.patch targets**: String-based patches don't fail at import time. They fail at runtime with confusing errors.

7. **Half-measures on subdirectories**: One organized group alongside several disorganized ones looks accidental. Either restructure the parent holistically or keep everything flat.

8. **Optimizing for the tool instead of the codebase**: Don't choose a two-step approach because it's easier for you as an agent. Choose the approach that produces the best architecture. Manage the complexity — don't avoid it.
