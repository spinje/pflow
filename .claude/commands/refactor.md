---
description: Analyze, plan, and execute structural refactors (file splits, subdirectory extraction, module reorganization)
---

# Structural Refactor

You are guiding a structural refactor. Your job is to find what's wrong, discuss it with the user, plan the fix, and execute it with zero behavior change.

This is a discussion-first command. The user may point you at a specific module or file, or they may ask you to find the most high value refactor point in the codebase, expecting you to find what needs work. Either way: assess first, discuss findings, scrope and outcome, then plan.

## Phase 0: Assess

### If the user pointed at a specific target

Focus your analysis there. But don't ignore adjacent issues — if you're auditing `runtime/`, note problems in `runtime/` even if they're not in the specific file the user mentioned.

### If no specific target

Survey the whole codebase. Use parallel subagents to audit multiple modules simultaneously. For each top-level module under `src/pflow/`:

```bash
# File sizes — god files are the most obvious symptom
wc -l src/pflow/<module>/*.py | sort -rn

# File count — overcrowded directories
ls -1 src/pflow/<module>/*.py | wc -l

# Import graph — who depends on whom
grep -rn "from pflow.<module>" src/pflow/ --include="*.py"

# Cross-module coupling — reaching into other modules' internals
grep -rn "from pflow.<module>.*import _" src/pflow/ --include="*.py"

# CLAUDE.md size — oversized docs signal oversized modules
wc -l src/pflow/<module>/CLAUDE.md
```

### What to look for

File size is just one symptom. Look deeper:

**Structural smells:**

- **Misplaced responsibilities**: Function lives in module A but serves module B's concern. Sign: module B imports it, it uses module B's types. It migrated to where it was first needed, not where it belongs.
- **Boundary violations**: Importing private functions across module boundaries (`from pflow.module._internal import ...`). The module never defined a proper public API.
- **Shotgun surgery**: One feature change touches 5+ files across multiple directories. The feature's code is scattered instead of co-located.
- **Hidden coupling**: Two modules share implicit contracts — same magic strings, same dict shapes, assumptions about execution order — with no import relationship to explain why.
- **Abstraction mismatch**: A class that's really a namespace (all static methods, no state). A "manager" that does everything. A module you can't describe in one sentence without "and."
- **Missing APIs**: No `__init__.py` exports, no clear public surface. Consumers guess what to import by reading source.

**AI-agent readability** — this codebase is built by agents, optimize for how agents work:

- **Context window cost**: How many files must an agent load to understand one concern? If it's 5+, the concern is too scattered or the files are too entangled. Each concern should be a "context island" loadable independently.
- **Greppability**: Can an agent find code by searching for what it does? Good: `validate_template_paths`. Bad: `process`, `handle`, `run`.
- **Traceable data flow**: Can an agent follow data input-to-output by reading code? Or are there indirection layers (registries, dynamic dispatch, string-based routing) that require config knowledge to trace?
- **CLAUDE.md health**: Does each directory have one? Is it the right size? A 400-line CLAUDE.md covering 19 files signals the directory needs splitting. No CLAUDE.md at all means agents fly blind.
- **Self-describing structure**: Does `ls` on a directory communicate the architecture? File names should cluster by concern (shared prefixes like `template_*validation*.py`).
- **Isolation of concerns**: Can an agent modify one concern without understanding others? If adding a new validation pass requires understanding the wrapper chain, the module boundaries are wrong. Each concern should be a "context island" an agent can load independently.

### Investigate cross-module issues with subagents

When the initial survey reveals smells that cross module boundaries — imports reaching into other modules' internals, functions that seem misplaced, coupling patterns — launch `pflow-codebase-searcher` subagents **in parallel** to investigate. Don't burn your own context window tracing import chains across the whole codebase.

Examples of targeted investigations:
- "Who imports from `runtime/validation_utils.py` outside of `runtime/`? What do they use and why?"
- "Trace all uses of `flatten_output_structure` — is it a validation concern or a general output utility?"
- "Find all `mock.patch` targets referencing `template_validator` in the test suite"
- "What does `execution/formatters/` import from `runtime/`? Map the dependency surface."

Each subagent gets ONE question, returns a focused answer. You synthesize the results into a coherent picture of what's wrong and where the real boundaries should be.

### Present findings to the user

This is a discussion. Present what you found with concrete numbers — file sizes, import counts, specific examples of the smells you identified. Your findings might lead to:

- **File splitting** (single large file → multiple focused files)
- **Subdirectory extraction** (cohesive file group → own directory with CLAUDE.md)
- **Responsibility migration** (function moves from module A to module B)
- **Interface clarification** (add `__init__.py` exports, stop importing internals)
- **Nothing** (the architecture is fine — valid outcome, say so honestly)

Don't invent problems to justify a refactor. Don't inflate small issues into big projects.

## Phase 1: Align

Once you and the user agree on what to refactor, align on HOW before writing any code.

### Understand their priorities

- **Minimal risk**: Touch as few files as possible, re-export for backward compat?
- **Architectural correctness**: Get the structure right even if it means more changes?
- **Future extensibility**: Design for the next refactor too?

This changes the plan. Risk-minimizing keeps files flat. Architecture-focused creates subdirectories and updates every consumer.

### Show concrete before/after

Present your proposed split boundaries visually. Show the target file structure, which functions go where, and what the import graph looks like. Let the user react before you write code. Refactors are expensive to undo — 30 seconds of alignment saves hours of rework.

### Surface decisions explicitly

You'll encounter decision points. Flag them:

- **Naming**: "This utils module contains both validation helpers and output structure traversal. Name it by what it actually contains?"
- **Scope**: "This file is 1,200 lines but may be one cohesive concern. Split it or just move it?"
- **Backward compat**: "4 files import from here. Re-export from the original path or update all consumers?"
- **Dead code**: "This function is never called. Remove it during the refactor?"
- **Subdirectories**: "These 5 files form a cohesive group. Extract to a subdirectory with its own CLAUDE.md?"

Gauge importance (1-5). For low-stakes (1-2), state your recommendation and proceed. For anything higher, stop and wait.

### Check your own consistency

Before presenting a recommendation, review it against everything else you've said. If you recommended "do it holistically" earlier, don't recommend "defer half of it" later without acknowledging the change and explaining why. Inconsistency erodes trust.

## Phase 2: Deep Read

Once you know WHAT to refactor, understand it thoroughly before planning.

### Read the entire file yourself

Do NOT rely on subagent summaries for the file being refactored. Read it line by line. Map:
- Every function, class, constant, and module-level item
- The internal call graph (which functions call which)
- Dead code (defined but never called — verify with grep)

### Audit all consumers

```bash
grep -rn "from <module> import" src/ tests/
grep -rn "<ClassName>" src/ tests/  # includes mock.patch string paths
```

Categorize each consumer:
- **Production code**: direct imports, lazy imports inside functions
- **Test code**: imports, `mock.patch()` string targets, docstring references
- **Documentation**: CLAUDE.md references, comments

### Check for existing analysis

Look in `scratchpads/` for prior work. If a spec exists, verify it against the actual code — specs may be incomplete or wrong. Trust code over documentation.

## Phase 3: Identify Split Boundaries

### The core principle: split by concern, not by category

**Right:** Each file owns its detection logic AND its error formatting. They change together, so they live together.

**Wrong:** Extracting "all error formatting" into one file. This creates a dumping ground (a category, not a responsibility) and leaves a large remainder.

### Decision framework for each function

Ask: "When this function changes, what other functions must change too?" Functions that co-change belong in the same file. Functions used by multiple files belong in a shared module.

### Dependency graph must be acyclic

Draw the dependency graph between proposed files. If you find a cycle, the boundaries are wrong. Restructure until the graph is a DAG.

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

## Phase 4: Write the Plan

Write a detailed plan to a scratchpad (`scratchpads/<refactor-name>/PLAN.md`).

### 4.1 Exhaustive method-to-file mapping

Every single function, constant, class, and module-level item must appear in exactly one target file. Use a table:

```
| Item | Current location (line) | Target file | Reason |
```

This is the most important artifact. If an item is missing from the plan, it will be missing from the implementation.

### 4.2 Dependency graph

```
orchestrator.py
  ├── imports from: path_validation → utils
  ├── imports from: type_validation → type_checker (pre-existing)
  └── imports from: batch_validation → path_validation, utils
```

Verify: no cycles, no file imports from the orchestrator (except the entry point).

### 4.3 Consumer impact table

| File | Current import | After refactor |
|------|---------------|----------------|

Include mock.patch string targets — these are easy to miss.

### 4.4 What to delete

Identify dead code found during the audit. Refactoring is the right time to remove it. List each item with evidence (grep showing zero callers).

### 4.5 What NOT to do

- Don't change any logic
- Don't add new tests (existing tests validate correctness)
- Don't "improve" code while moving it
- Don't add docstrings, comments, or type annotations to code you didn't write

## Phase 5: Implement

### Execution order

1. **Baseline**: `make test && make check` — record pass count
2. **Create new files** in dependency order (leaves first): utils → leaf modules → orchestrator
3. **Rewrite the original file** as the orchestrator (if it stays as entry point)
4. **Update production imports** (use dedicated subagents for mechanical changes)
5. **Delete old source files** and **verify**: `make test` — isolates source migration from test migration. All production-path tests should pass; only test files with old imports should fail.
6. **Update test imports** (use dedicated subagents — one for straightforward changes, one for mock.patch sites)
7. **Delete old test files** and **verify**: `make test && make check` — pass count should match baseline (minus any deleted dead-code tests)
8. **Final grep**: confirm zero references to old class/function names in src/ and tests/

### Subagent delegation strategy

Use subagents for mechanical import updates. Give each subagent:
- ONE clear instruction (e.g., "change `ClassName.method(` to `method(`")
- The complete list of files to update
- The instruction to NOT change any test logic

Do NOT give subagents two simultaneous transformations (rename + change import path). That doubles the error surface per file.

### Handling unforeseen issues

After subagents complete, audit their work:
- Check for stale references they may have missed
- Check for references they changed incorrectly (e.g., importing private functions from wrong modules)
- Run tests immediately — don't batch multiple changes before verifying

If tests fail, diagnose before fixing. The failure tells you what was missed.

## Phase 6: Verify Completeness

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


### Migration audit

Use a subagent to verify every item from the Phase 4 mapping exists in exactly one target file:
- Items in ZERO files = missed migration
- Items in MORE THAN ONE file = duplication
- Deleted items should be in ZERO files

### Check for accidental duplicates

Constants are easy to duplicate accidentally (defined in old location AND new location). Grep for each constant name across all new files.

## Phase 7: Documentation

- Update the parent module's CLAUDE.md to reflect new file structure
- If a subdirectory was created, write a focused CLAUDE.md for it
- If test files moved to a subdirectory, write a short CLAUDE.md with source-to-test mapping and any non-obvious patterns (e.g., "each file has its own mock registry — intentional, don't extract")
- Grep ALL other CLAUDE.md files for references to moved/renamed modules — stale references in other directories are easy to miss
- Don't over-document — the code should be self-explanatory; the CLAUDE.md covers non-obvious relationships

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

## Reference: Gotchas That Break Refactors

Hard-won knowledge from real refactors. These pass code review but fail in CI, or worse, fail silently.

**Python-specific:**
- `ClassVar[list[str]]` is valid inside a class, fails mypy at module level. When dissolving a class, change to plain type annotation.
- Recursive functions referencing the old class (`ClassName._flatten(...)`) must become `flatten(...)`. Easy to miss inside the function being moved.
- `# noqa: C901` on complex functions must be preserved. Linters re-check after the move.
- Nested closures defined inside methods reference module-level names. When moving, verify these references still resolve.

**Duplication traps:**
- Same-name constants in different files (`MAX_DISPLAYED_FIELDS = 20` vs `= 500`) are DIFFERENT constants. Always grep project-wide before deciding where a constant lives.
- Re-exporting AND defining creates two valid import paths. Pick one canonical location.

**Test traps:**
- When you delete dead code, DELETE its tests too. Don't try to fix them.
- Subagents doing mechanical updates may also "fix" things you didn't ask for. Audit their diffs, not just "tests pass."
- `mock.patch("module.path.ClassName")` is a string — breakage is at runtime, not import time. Grep for string-based references.

**Naming traps:**
- Name modules for what they contain, not where they came from. Utilities extracted from `template_validator.py` aren't necessarily "validation utils" — check whether they're all validation-specific.
- Don't use aspirational names. A 2-function module doesn't need a grand name.

## Reference: Anti-Patterns

1. **Refactoring while restructuring**: "While we're here, let's fix this bug too." No. Pure structural refactor. Logic changes get their own commit.

2. **Category-based splits**: "All formatters in one file, all validators in another." Creates files that change for unrelated reasons.

3. **Premature subdirectories**: Directory for 2-3 files. The `__init__.py`, nesting, and cognitive overhead aren't worth it. Wait until 5+.

4. **Dumping-ground modules**: `utils/`, `helpers/`, `common/` with no qualifier attract every homeless function. Name by contents: `validation_utils`, not `runtime_utils`.

5. **Renaming during restructure**: Changing function names, file names, AND locations simultaneously. Track each transformation explicitly in the plan if you must combine them.

6. **Ignoring mock.patch targets**: String-based patches don't fail at import time. They fail at runtime with confusing errors.

7. **Half-measures on subdirectories**: One organized group alongside several disorganized ones looks accidental. Either restructure the parent holistically or keep everything flat.

8. **Optimizing for the tool instead of the codebase**: Don't choose a two-step approach because it's easier for you as an agent. Choose the approach that produces the best architecture. Manage the complexity — don't avoid it.
