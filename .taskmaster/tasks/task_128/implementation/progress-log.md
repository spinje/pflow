# Task 128: Branch Convergence — Implementation Progress Log

## 2026-03-15 — Investigation & Problem Understanding

Read `scratchpads/branch-convergence-no-fallback/BUG-REPORT.md` and reproduction workflows. Launched parallel subagents to trace the full template resolution path, shared store behavior, and branching execution model.

Key findings:
- PocketFlow's `Flow._orch()` is a simple `while curr:` loop following successor edges. Non-taken branches are never reached — no skip tracking, no marking, just absent from the store.
- `NamespacedSharedStore.__init__` always creates `shared[namespace] = {}` on `_run()`, giving a clean three-way distinction: absent (didn't run), empty dict (ran, no output), populated dict (ran with output).
- Template resolution raises `ValueError("Unresolved variables...")` in strict mode when a referenced node's namespace is absent.
- The convergence *wiring* works fine (multiple branches can point to the same `- next:` target). The problem is purely in template resolution.

## 2026-03-15 — Design Discussion & Option Analysis

### Initial Analysis

Explored four approaches from the bug report:

1. **`??` coalesce operator** in templates — `${a.stdout ?? b.stdout}`
2. **`- converge:` parameter** on nodes — new node-level concept
3. **Non-executed nodes resolve to `""`** — breaks fail-fast on typos
4. **Code node as aggregator** with optional inputs — `str | None` annotations

Option 3 rejected immediately: silent failures are worse than the workaround.

### User Concern: No Existing Inline Syntax

User flagged: *"We haven't supported any inline syntax inside variables before this, or?"* — Correct. `${...}` has always been purely path-based (`identifier.field[index]`). No operators, no logic. Adding `??` would be the **first inline operator** — a precedent that opens the door for agents trying `||`, `? :`, etc.

This concern steered us toward exploring non-template-syntax solutions first.

### Exploring `- inputs:` Approaches

I proposed `- inputs:` with list-based fallback on any node type. User pointed out: *"You show inputs on shell here? What about using code node as aggregator?"* — `inputs` is only meaningful on code nodes. Shell/llm nodes don't have typed inputs.

So: code node as the convergence point. But the same problem exists — `inputs: { high: ${branch-high.stdout} }` still fails when branch-high didn't execute. Template resolution errors happen in the wrapper BEFORE the code node's `prep()` ever sees the inputs.

### The `?` Marker Discussion

I proposed marking optional inputs with `?` suffix (e.g., `high?: ${branch-high.stdout}` or `high: ${branch-high.stdout}?`). User asked: *"So skipping the `?` entirely is not an option?"*

Key realization: if the code already declares `high: str | None`, that annotation IS the signal. No `?` needed. The code node already parses annotations via `_extract_annotations()`. We just needed to teach `_get_outer_type()` to decompose `Optional[T]` and check for `None` in the union.

This removed ALL new syntax from Phase 1.

### `typing` Namespace Gap

I noted `Optional[str]` would cause `NameError` in exec because `typing` isn't in the namespace. User's response: *"Can't you just add it?"* — Yes. One line. No security implications (namespace is already unrestricted with full `__builtins__`). This was a non-issue.

### Type Mismatch Concern for `??`

User raised: *"What if the values are not the same type?"* — If `branch-high` returns a dict and `branch-low` returns plain text, `??` silently gives different types depending on which path ran.

Key insight from user: **dot access (which already exists) IS the normalization mechanism**. `${branch-high.stdout.summary ?? branch-low.stdout}` — both sides resolve to strings. You drill into structured outputs to get the value at the type you need. If someone carelessly writes `${a.stdout ?? b.stdout}` where types differ, the downstream node breaks when it gets the unexpected type — which **surfaces the mistake** rather than hiding it.

### Agent Familiarity Argument

User asked: *"What is the most intuitive for an AI agent to understand and write?"*

`??` is probably the most intuitive because every LLM has seen it millions of times in JavaScript, C#, Swift, Kotlin, PHP, SQL (`COALESCE`). An agent would generate it correctly on the first try with minimal instruction. An agent that has never seen pflow docs would likely *guess* this syntax.

### Decision: Both Approaches

User: *"The best of both worlds is implementing both of these approaches, right?"*

Yes — they're complementary, not competing:
- `??` handles simple same-type convergence (one line, zero extra nodes)
- Code node + Optional handles complex convergence (type normalization, logic, transformation)

Phased delivery: Phase 1 (code node, smaller change) first, Phase 2 (`??`, larger change) second. Phase 1 also serves as safety net — even if `??` has edge cases, the code node approach always works.

### Static vs Runtime Validation Gap

Discovered that static validation (pre-execution) **passes** for convergence references because both branch nodes exist in the workflow graph. The failure only happens at **runtime** when the non-executed branch's namespace is absent from the shared store. This means the convergence problem can't be caught at compile time — it's inherently a runtime concern.

## 2026-03-15 — Phase 1 Implementation (Optional Inputs)

### Type System Changes (`python_code.py`)

Added `_is_optional_type()` and `_get_inner_optional_type()` to decompose `Optional[str]` / `str | None` annotations. Fixed `_get_outer_type()` to return `(str, type(None))` instead of `None` (which was skipping all type checks).

- ✅ Existing bug fixed: `list[str] | None` was returning `list` from `_get_outer_type()`, so `isinstance(None, list)` would fail in `_check_input_types()`.
- ✅ Added `typing` module and `Optional` shortcut to exec namespace so users don't need manual imports.
- ✅ Added public `extract_optional_input_keys()` for compiler to call without instantiating node.

### Wrapper Changes (`node_wrapper.py`)

Added `optional_input_keys` constructor param and `_inject_none_for_optional_inputs()` method. Initial version hit ruff C901 complexity (11 > 10). Extracted `_all_variables_from_absent_nodes()` static helper to bring complexity down.

Key semantic: checks `root in context` to distinguish "node didn't execute" (root absent → inject None) from "typo" (root present, path fails → error).

### Compiler Wiring (`compiler.py`)

Added optional key extraction in `_create_single_node()` gated on `node_type == "code"`. Uses lazy import to avoid tight module coupling. Passes through `_apply_template_wrapping()` to the wrapper constructor.

### Results

- All 3986 tests pass
- `make check` clean (ruff, mypy, deptry)
- 6 integration tests + unit tests written covering: Optional injection, non-optional still errors, typo detection preserved, both annotation forms work

## 2026-03-15 — Phase 2 Planning (`??` Coalesce Operator)

### Critical Gap Found

Discovered that `_resolve_simple_template` in `node_wrapper.py` duplicates `TemplateResolver.resolve_template()`'s simple-template path. Both use the same three static methods (`extract_simple_template_var`, `variable_exists`, `resolve_value`) in the same order. The wrapper's version exists solely to return an `is_simple` flag.

This creates a problem for `??`: adding coalesce to `resolve_template()` wouldn't help because the wrapper short-circuits via `_resolve_simple_template` before `resolve_template()` is ever called for simple templates.

Launched 3 parallel subagents to verify the refactor is safe:
- ✅ Single caller — only `_resolve_template_parameter` calls it
- ✅ `is_simple` flag is structural (template string shape, not resolution success)
- ✅ Downstream guards (JSON auto-parse, type validation) are harmless for unresolved templates
- ✅ No direct tests — only tested indirectly through `_run()`

Decision: delete `_resolve_simple_template`, simplify `_resolve_template_parameter` to delegate to `resolve_template()` directly, compute `is_simple` via `TemplateResolver.is_simple_template()`.

### Complete Impact Analysis

Launched thorough subagent to inventory ALL `${...}` pattern locations. Found 14 distinct regex definitions across 8 source files:

**Must change (5 locations)**:
1. `_VAR_NAME_PATTERN` → keep clean, add `_COALESCE_EXPR_PATTERN` on top
2. `TEMPLATE_PATTERN` → use coalesce expression
3. `SIMPLE_TEMPLATE_PATTERN` → use coalesce expression
4. `_PERMISSIVE_PATTERN` (template_validator.py) → independently defined, manual sync
5. Downstream parsing in `workflow_data_flow.py` and `workflow_validator.py`

**No change needed (8+ locations)**: All `[^}]+` patterns already capture coalesce. Downstream is diagnostic-only (error messages, repair context).

### Important Verified Details

- **`_is_bash_syntax()` does NOT flag `??` as bash**: The `bash_operators` list (`%%`, `##`, `:-`, `:=`, `:?`, `:+`, `/`, `^^`, `,,`) does not include `??`. No false positive risk.
- **`context` dict = `shared` + `initial_params`**: If a user provides a param named `branch-high`, it shadows the node namespace. `root in context` returns True, so the template tries to resolve. This is correct — user-provided params should take precedence.
- **`resolve_nested()` calls `resolve_template()`**: For dict params (like `inputs`), `_resolve_template_parameter` calls `resolve_nested()` which internally calls `resolve_template()` for each string value. This means `??` in `resolve_template()` automatically works for dict/list params too — no separate handling needed.
- **Zero backward compatibility risk**: `??` was never valid inside `${...}` under the old regex (`[\w-]` doesn't include `?` or whitespace). No existing template could contain it.
- **`NESTED_INDEX_PATTERN` unchanged**: Coalesce inside nested index brackets (`${results[${a ?? b}].field}`) is unsupported — inner template uses `extract_simple_template_var` which would return `"a ?? b"` then `resolve_value("a ?? b")` would fail. This is an extremely rare pattern (inner templates are always `${__index__}` in practice). Documented as out of scope.

### Plan Written

Full plan at `.claude/plans/sunny-spinning-gem.md`. Covers Steps 1-11 with exact code locations, regex patterns, and test specifications.

## 2026-03-15 — Phase 2 Implementation

### Steps 1-4: Core template_resolver.py changes

Implemented as planned. Key additions to `TemplateResolver`:

- `_COALESCE_EXPR_PATTERN`: builds on `_VAR_NAME_PATTERN` with `(?:\s*\?\?\s*_VAR_NAME_PATTERN)*`
- `TEMPLATE_PATTERN` and `SIMPLE_TEMPLATE_PATTERN` now use `_COALESCE_EXPR_PATTERN` instead of bare `_VAR_NAME_PATTERN`
- `_COALESCE_SPLIT_PATTERN`: compiled regex for splitting on `??` (avoids recompilation)
- `split_coalesce_operands()`: splits `"a ?? b.field"` → `["a", "b.field"]`
- `is_coalesce_expression()`: simple `"??" in expr` check
- `resolve_coalesce()`: the core semantic method — returns `(value, "resolved"|"path_error"|"unresolved")`
- `extract_variables()`: now splits coalesce operands so callers get individual variable names
- `resolve_template()`: coalesce handling added in both simple (type-preserving) and complex (string interpolation) paths

**`is_simple_template("${a ?? b}")` returns True** — the entire string is one `${...}` expression. This means coalesce gets type preservation AND JSON auto-parse treatment in `resolve_nested()`, consistent with regular simple templates.

### Step 5: Refactor node_wrapper.py

Deleted `_resolve_simple_template` method (lines 592-625). Simplified `_resolve_template_parameter` from 15 lines to 7:

```python
# Before: two code paths for simple vs complex
resolved_value, is_simple = self._resolve_simple_template(template, context)
if is_simple:
    return resolved_value, True
resolved_value = TemplateResolver.resolve_template(template, context)
return resolved_value, False

# After: single path
is_simple = TemplateResolver.is_simple_template(template)
resolved_value = TemplateResolver.resolve_template(template, context)
return resolved_value, is_simple
```

This means `resolve_template()` is now the **single resolution entry point** for all template types. Coalesce logic only exists in one place.

### Steps 6-7: template_validator.py

Updated `_PERMISSIVE_PATTERN` with a separate `_PERM_VAR` pattern variable to keep it readable. **Bug caught during implementation**: initially added an extra `)` at the end of `_PERM_VAR`, breaking the regex grouping. Caught immediately by re-reading the generated code.

Updated `_extract_all_templates` to split coalesce operands via inline `re.split(r"\s*\?\?\s*", match)` so downstream path validation sees individual variable names.

### Steps 8-9: Validation consumers

**`workflow_data_flow.py`** — Added module-level `_split_coalesce()` helper with pre-compiled `_COALESCE_SPLIT` pattern. Coalesce operands are split before calling `_validate_template_reference`.

**`workflow_validator.py`** — Split coalesce operands in `_validate_template_in_source` before node ID extraction. Each operand is validated independently.

### C901 Complexity Fixes (deviation from plan)

`make check` flagged two C901 complexity violations not anticipated by the plan:

1. **`resolve_template` in `template_resolver.py` (12 > 10)**: Extracted `_resolve_complex_match()` static method. The complex template loop body (coalesce check + path traversal + simple var check + unresolved logging) moved to this new method. The loop in `resolve_template` is now a clean 3-line for loop.

2. **`validate_data_flow` in `workflow_data_flow.py` (11 > 10)**: Extracted `_validate_node_params()` module-level function. The per-node parameter iteration and template matching moved there. Also moved the coalesce split into a separate `_split_coalesce()` function.

These extractions are purely structural — no behavioral change.

### Step 10: Tests

**New file: `tests/test_runtime/test_template_coalesce.py`** — 67 unit tests across 7 classes:
- `TestCoalesceRegex` (13) — TEMPLATE_PATTERN/SIMPLE_TEMPLATE_PATTERN matching
- `TestSplitCoalesceOperands` (6) — splitting, whitespace handling, chaining
- `TestIsCoalesceExpression` (5) — detection
- `TestExtractVariablesCoalesce` (6) — variable extraction with coalesce
- `TestResolveCoalesce` (18) — core semantics: resolved/path_error/unresolved, chains, type preservation, edge cases
- `TestResolveTemplateCoalesce` (17) — end-to-end: simple/complex, mixed, all-absent
- `TestResolveNestedCoalesce` (3) — resolve_nested integration

**Added to `tests/test_runtime/test_template_resolver.py`**:
- `test_extracts_coalesce_operands` in `TestVariableExtraction`

**Added to `tests/test_integration/test_branch_convergence.py`**:
- `_make_coalesce_ir()` helper + `TestBranchConvergenceCoalesce` (2 tests) — shell node with coalesce, both branch directions

### Step 11: Verification

- `make test`: 4056 passed, 485 skipped, 0 failures
- `make check`: all clean (ruff, ruff-format, mypy, deptry)

## 2026-03-15 — Post-Implementation Analysis: Phase 1 + Phase 2 Interaction

After implementation, analyzed whether Phase 1 (`_inject_none_for_optional_inputs`) and Phase 2 (`??` coalesce) could interfere with each other. This is a scenario where a code node uses BOTH coalesce syntax in its `inputs` dict AND optional type annotations.

### The risk

`_inject_none_for_optional_inputs` runs AFTER template resolution (on the resolved values). If it incorrectly identifies a coalesce result as "unresolved", it would overwrite the successfully resolved value with None.

### Why it works correctly (verified by reading code)

Two independent guards prevent interference:

1. **`_all_variables_from_absent_nodes()` uses `all()`** (line 471): With `${a.stdout ?? b.stdout}`, `extract_variables` returns `{"a.stdout", "b.stdout"}`. The method checks if ALL roots are absent. In the normal convergence case, only ONE root is absent → `all(...)` returns False → no injection. Only when BOTH roots are absent (neither branch ran) does it return True, which is the correct time to inject None.

2. **`input_value != input_template` guard** (line 508): When coalesce successfully resolves, `input_value` is the resolved string (e.g., `"LOW-VALUE\n"`), which differs from the original template `"${a.stdout ?? b.stdout}"`. The guard detects this difference and skips injection.

### Why this is fragile

These guards were designed independently. `_all_variables_from_absent_nodes` was written for Phase 1 without knowing coalesce would exist. The `input_value != input_template` guard is about detecting partial resolution, not about coalesce. The correct behavior emerges from two unrelated checks aligning — not from explicit design coordination.

Future changes to either mechanism could break this. For example:
- If someone changes `all()` to `any()` in `_all_variables_from_absent_nodes`, coalesce in optional inputs would break
- If someone removes the `input_value != input_template` guard (perhaps during a refactor), successfully coalesced values could be overwritten with None

### Tests added

Added `TestCoalesceWithOptionalInputs` class (2 tests) to `test_branch_convergence.py`:

1. **`test_coalesce_in_optional_input_resolves_correctly`**: Code node with `inputs: { branch_value: "${branch-high.stdout ?? branch-low.stdout}" }` and `branch_value: str | None`. One branch runs → coalesce resolves → optional injection does NOT overwrite. Tested both directions.

2. **`test_coalesce_in_optional_input_both_absent_gets_none`**: Router skips both branches → coalesce fails (both roots absent) → template unchanged → optional injection correctly sets None. Code produces `"NONE-INJECTED"`.

### Final count

- `make test`: **4058 passed**, 485 skipped, 0 failures
- `make check`: all clean

## Summary of Deviations from Plan

| Planned | Actual | Why |
|---------|--------|-----|
| No complexity extractions | Extracted `_resolve_complex_match()` and `_validate_node_params()` | C901 violations from added branches. Not anticipated because pre-existing methods were at 9-10 complexity. |
| Plan said "Step 11: No-Change Locations" | Verified by inspection, no code changes needed | As expected |
| No Phase 1+2 interaction test | Added 2 integration tests | Post-implementation analysis revealed fragile alignment between independent guards |
| `_PERM_VAR` as clean extraction | Had to fix extra `)` bug | Regex grouping error caught during implementation |

## 2026-03-15 — Bracket-Only Pre-Processor (Nested Index + Coalesce Fix)

### Problem

Nested index templates (`${results[${__index__}].field}`) didn't compose with coalesce (`${results[${__index__}].field ?? fallback.field}`). The old `NESTED_INDEX_PATTERN` matched the ENTIRE outer `${outer[${inner}]rest}` structure including the closing `}`, so the `?? fallback.field` suffix broke the regex match. The result was a ValueError in strict mode (not silent data loss).

### Fix

Replaced `NESTED_INDEX_PATTERN` (matches full `${outer[${inner}]rest}`) with `_BRACKET_INDEX_PATTERN` (matches only `[${var}]`). The new pattern is context-free — it just finds `[${var}]` anywhere in the string and replaces with `[N]`. It doesn't care what's outside the brackets.

```python
# Old: captures 3 groups, reconstructs full template
NESTED_INDEX_PATTERN = re.compile(
    r"\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\[(\$\{" + _VAR_NAME_PATTERN + r"\})\]((?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)\}"
)

# New: captures 1 group, in-place replacement
_BRACKET_INDEX_PATTERN = re.compile(r"\[(\$\{" + _VAR_NAME_PATTERN + r"\})\]")
```

The `resolve_nested_index_templates` method body simplified accordingly — no group reconstruction needed, just `template[:match.start()] + f"[{resolved_inner}]" + template[match.end():]`.

### Why it's safe

The "stealing" concern (pre-processor now matches `[${count}]` in strings like `echo "[${count}]"`) is invisible because both code paths produce the same output:
- Pre-processor: `[${count}]` → `[5]`
- Normal resolution: `[` + resolve(`${count}`) + `]` = `[5]`

Non-integer inner values and missing variables still cause the pre-processor to skip — normal resolution handles them.

### Bonus

Also fixes `${matrix[${row}][${col}]}` (double nested indices), which the old pattern couldn't handle because `rest_path` expected dots, not more brackets.

### Verification

- `make test`: 4058 passed, 485 skipped, 0 failures (no regressions)
- `make check`: all clean

## 2026-03-15 — Code Review Fixes

Evaluated code review at `scratchpads/code-review-task-128.md`. 5 findings: 3 confirmed, 2 disputed.

### Confirmed and fixed

1. **W1 — `_all_variables_from_absent_nodes` comment** (`node_wrapper.py:466`): Added docstring explaining why `all()` (not `any()`) is critical for coalesce correctness. Without this comment, a future developer could silently break coalesce-in-optional-inputs by changing `all()` to `any()`.

2. **W2 — Coalesce split duplication in `template_validator.py`** (`template_validator.py:1616`): Replaced inline `re.split(r"\s*\?\?\s*", match)` with `TemplateResolver.split_coalesce_operands(match)`. The file already imports `TemplateResolver` (line 14), so this is a one-line change that eliminates a redundant regex pattern.

3. **W2 — "Keep in sync" comment for `workflow_data_flow.py`** (`workflow_data_flow.py:13`): Added `# Mirrors TemplateResolver.split_coalesce_operands — keep in sync` to `_split_coalesce`. Chose not to import `TemplateResolver` because `workflow_data_flow.py` currently has zero pflow imports (pure stdlib), which may be intentional.

4. **S4 — Pre-compile root split pattern** (`template_resolver.py`): Added `_ROOT_SPLIT_PATTERN = re.compile(r"[\.\[]")` as class attribute. Used in both `resolve_coalesce` (line 208) and `_resolve_complex_match` (line 615). Consistency with the file's pattern of pre-compiling all regex.

### Disputed

- **S1 — "Redundant `.strip()`"**: Not redundant. `_COALESCE_SPLIT_PATTERN.split("a ?? b")` can leave residual whitespace at boundaries. The `.strip()` is correct.
- **W3 — `_is_bash_syntax` blocks array validation**: Pre-existing issue, not introduced by this changeset. Review itself recommended no code change.

### Verification

- `make test`: 4058 passed, 485 skipped, 0 failures
- `make check`: all clean

## 2026-03-15 — Code Review Fixes (Round 2)

Evaluated code review at `scratchpads/code-review-task-128-2.md`. 3 findings: 2 confirmed and fixed, 1 partially disputed.

### C1 — `??` + nested index templates (partially disputed)

The reviewer tested against the OLD `NESTED_INDEX_PATTERN` code. The `_BRACKET_INDEX_PATTERN` refactor (done earlier in this session) already fixes the core resolution issue: `resolve_template("${a[${i}] ?? b[${i}]}", {"i": 0, "a": ["x"], "b": ["y"]})` returns `"x"` correctly.

**However**, one sub-issue remained: `_validate_malformed_templates()` had a false positive. The `nested_count` calculation used boolean presence (`if "[${" in ...`) instead of occurrence counting. With two `[${` in one match (`a[${i}] ?? b[${i}]`), it counted 1 instead of 2, triggering `1 + 1 = 2 < 3` → malformed error.

**Fix**: Changed `sum(1 for m in valid_matches if "[${" in f"${{{m}}}")` to `sum(f"${{{m}}}".count("[${") for m in valid_matches)` at `template_validator.py:1565`.

**Test**: Added `test_coalesce_with_nested_indices_not_malformed` to `test_template_validator_malformed.py`.

### W1 — `typing.Optional[T]` annotation form (confirmed)

The `_is_optional_type` and `_get_inner_optional_type` functions checked `startswith("Optional[")` but not `startswith("typing.Optional[")`. Since `typing` is injected into the code node exec namespace, `typing.Optional[str]` is a valid annotation form that `ast.unparse` faithfully preserves. The result: None injection didn't activate, and type checking was silently skipped.

**Fix**: Added `"typing.Optional["` prefix handling in both `_is_optional_type` (line 88) and `_get_inner_optional_type` (line 110) in `python_code.py`. `_get_outer_type` didn't need its own check — it delegates to `_get_inner_optional_type`.

**Tests**: Added 5 tests to `TestOptionalTypeSupport` in `test_python_code.py`: `_is_optional_type`, `_get_inner_optional_type` (str and list[str]), `_get_outer_type`, and `extract_optional_input_keys`.

### W2 — `validate_data_flow()` nested dict gap (disputed as out of scope)

Confirmed the gap is real (top-level `isinstance(param_value, str)` check skips dict-valued params). But verified via `git log` that this is **pre-existing** — the same check existed before Task 128. Task 128 only refactored it into `_validate_node_params` and added coalesce splitting. The template validator's `_extract_all_templates` and `_validate_malformed_templates` DO recurse into dicts, so template validation partially covers this. Recommended as a separate follow-up task, not Task 128 scope.

### Verification

- `make test`: 4064 passed, 485 skipped, 0 failures
- `make check`: all clean

## Known Limitations

1. **Coalesce inside bracket indices is unsupported**: `${results[${a ?? b}].field}` — `extract_simple_template_var` receives `"${a ?? b}"` and returns `"a ?? b"` (now a valid match for `SIMPLE_TEMPLATE_PATTERN`), but `resolve_value("a ?? b")` fails because `resolve_value` expects a single path, not a coalesce expression. Extremely rare pattern — inner templates are always `${__index__}` in practice.

2. **Literal fallbacks out of scope**: `${a ?? "default"}` — would require parsing quoted strings inside templates. Can be Phase 3 if needed.

3. **No static validation for coalesce semantics**: The pre-execution validator validates each operand independently as a valid node reference, but doesn't check whether the operands are in different branches (i.e., it can't warn "these two operands will always both be present"). This would require branch reachability analysis.

4. **Type mismatch between operands is the user's responsibility**: `${branch-returning-dict.stdout ?? branch-returning-text.stdout}` silently gives different types depending on which branch ran. Dot access is the normalization mechanism (drill into structured outputs to get consistent types).

5. **`validate_data_flow()` doesn't traverse nested dict/list params**: Forward references inside `inputs: {"x": "${later.stdout}"}` pass data flow validation. Pre-existing gap (not introduced by Task 128). The template validator's `_extract_all_templates` does recurse. Recommended as a separate follow-up task.

## 2026-03-15 — Coalesce-Aware Error Messages

### Problem

When a coalesce expression failed at runtime, the error message decomposed it into individual variables, losing the `??` context:

```
Unresolved variables in parameter 'command': ${branch-high.stdout}, ${branch-low.stdout}
```

An agent sees two broken references, not one coalesce expression where neither branch executed. The carefully designed typo-detection semantics (root present → path error vs root absent → branch didn't run) were invisible.

### Fix

Added `_diagnose_coalesce` static method to `TemplateAwareNodeWrapper`. It scans the original template for coalesce expressions, diagnoses each operand (root absent vs path not found), and returns formatted lines. `_build_enhanced_template_error` now shows coalesce-specific errors:

```
Unresolved template in parameter 'command':

Coalesce expression ${branch-high.stdout ?? branch-low.stdout} failed — no operand resolved:
  - ${branch-high.stdout}: node 'branch-high' did not execute
  - ${branch-low.stdout}: node 'branch-low' did not execute
```

Or for typos:

```
  - ${branch-high.stddout}: node 'branch-high' executed but path 'branch-high.stddout' not found
```

Extracted `_append_error_context` helper to keep `_build_enhanced_template_error` under C901 complexity limit.

### Tests

Added `TestCoalesceErrorMessages` class (2 tests) to `test_node_wrapper_template_validation.py`:
- `test_coalesce_error_shows_absent_nodes` — both roots absent → "did not execute" per operand
- `test_coalesce_error_shows_path_error` — root present but path wrong → "not found"

### Verification

- `make test`: 4066 passed, 485 skipped, 0 failures
- `make check`: all clean
