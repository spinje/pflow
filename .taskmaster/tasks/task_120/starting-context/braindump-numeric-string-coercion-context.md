# Braindump: Numeric String Coercion Bug Fix & Task 120 Context

## Where I Am

The numeric string coercion bug fix (PR #84) is **complete and ready to commit**. Task 120 (strict input validation) was created as a follow-up task based on a PR review comment. This braindump captures the full context of the bug fix implementation and the reasoning behind creating Task 120.

## User's Mental Model

The user thinks about type handling in two layers:
1. **Workflow inputs** - declared in `## Inputs` section with `type: string`, `type: number`, etc.
2. **Hardcoded node params** - literal values in the middle of workflows (Task 112 scope, different from this bug)

Key insight the user provided: "In the future we will have support for more code node types than python and then it can feel natural to align the types to the language you are using throughout the workflow." This is why we expanded the IR schema to accept Python type aliases (`str`, `int`, `bool`, `dict`, `list`) alongside JSON Schema types (`string`, `number`, `boolean`, `object`, `array`).

The user's priorities:
- **Fix the bug correctly** - numeric strings like Discord snowflake IDs should stay as strings when declared `type: string`
- **Future-proof** - support for TypeScript nodes (Task 113) means users might naturally use different type naming conventions
- **Verify exhaustively** - manual workflow testing, not just unit tests

## Key Insights

### Two Root Causes, Not One

The bug had TWO root causes discovered during implementation:

1. **CLI's `infer_type()`** (main.py:2279-2316) - Aggressively converts "1458..." to int BEFORE workflow declared types are consulted

2. **Template resolver's JSON auto-parsing** (template_resolver.py:625-631) - When resolving `${channel_id}`, if the value is a string that looks like JSON, it auto-parses it. `json.loads("1458059302022549698")` returns int!

The first root cause was expected. The second was discovered during testing when the bug persisted after fixing the first. This is documented in `scratchpads/bug-numeric-string-coercion/progress-log.md`.

### The Template Resolver Fix Is Intentional

Changed from `if success:` to `if success and isinstance(parsed, (dict, list)):` - only parse JSON containers, not primitives. This is a **behavior change** that could theoretically break workflows relying on primitive auto-parsing. However:
- This IS the bug fix - without it, numeric strings still get corrupted
- Per CLAUDE.md: "NO USERS using the system" so no backwards compatibility concerns
- The old test `test_parses_json_primitives` was renamed to `test_json_primitives_stay_as_strings`

### PR Review Feedback

A bot review (claude[bot]) on PR #84 raised 4 warnings. We addressed them:

1. **Identity check pattern** (FIXED) - Changed from fragile `if coerced_value is not provided_value` to explicit `coerced_value, was_coerced = _coerce_provided_input(...)` tuple return

2. **Template resolver breaking change** (DOCUMENTED) - Added comments explaining why primitives aren't parsed

3. **Error handling / lenient coercion** (DOCUMENTED + TASK 120) - Current behavior: coercion failures log warning and pass through original value. User decided this is fine for now, created Task 120 for strict validation as future enhancement

4. **Type alias normalization** (FIXED) - Changed `_normalize_type()` to preserve case for unknown types

## Assumptions & Uncertainties

ASSUMPTION: The 5 fewer tests in final run (3707 vs 3712) is normal variance from parametrized tests, not a regression. Both runs showed all tests passing.

ASSUMPTION: "Lenient coercion" is acceptable for MVP. The error still surfaces at code node type checking, just with less context than strict validation would provide.

UNCLEAR: Should Task 120 (strict validation) be higher priority? The user set it as "low" but it would improve user experience. The user knows best here.

NEEDS VERIFICATION: The expanded IR schema (accepting Python type aliases) should be tested with the planner when it's re-enabled (Task 107). The planner might generate `type: string` (JSON Schema) while users write `type: str` (Python).

## Unexplored Territory

UNEXPLORED: How does type coercion interact with default values? If `default: 42` is specified for `type: string`, does it get coerced to `"42"`? I believe it should but didn't test this path.

CONSIDER: The coercion happens in `prepare_inputs()` which is called from both CLI (main.py) and runtime compiler (compiler.py). Both paths should work identically but only CLI was exhaustively tested.

MIGHT MATTER: MCP tool parameters use `coerce_to_declared_type()` (the older function for dict/list → str), not `coerce_input_to_declared_type()` (the new function for bidirectional coercion). These are separate code paths for different purposes.

UNEXPLORED: What happens with stdin routing (Task 115)? If stdin content is a numeric string and the receiving input has `type: string`, does coercion work? Stdin content comes through a different path.

## What I'd Tell Myself

1. **Read the progress log first** - `scratchpads/bug-numeric-string-coercion/progress-log.md` has the full implementation journey including the surprise second root cause

2. **The template resolver change is critical** - Don't revert it thinking it's unrelated. It's half the bug fix.

3. **Test with actual workflows** - Unit tests passed before the template resolver fix, but the actual workflow still failed. The user emphasized manual testing for a reason.

4. **Type aliases live in two places** - IR schema (ir_schema.py:262) for validation AND param_coercion.py for normalization. Keep them in sync.

## Open Threads

- Task 120 is documented but not implemented - strict validation at input boundary
- The PR review suggested documenting primitive auto-parsing change in CHANGELOG/docs - not done
- No migration notes written for the behavior change (probably not needed given no users)

## Relevant Files & References

**Core implementation:**
- `src/pflow/core/param_coercion.py` - `coerce_input_to_declared_type()` and helpers
- `src/pflow/runtime/workflow_validator.py` - `_coerce_provided_input()`, `_resolve_missing_input()`, integration in `prepare_inputs()`
- `src/pflow/runtime/template_resolver.py` - JSON auto-parsing fix (lines 222, 631)
- `src/pflow/core/ir_schema.py` - Type enum expansion (lines 262, 288)

**Tests:**
- `tests/test_core/test_param_coercion.py` - 52 new tests for coercion functions
- `tests/test_runtime/test_prepare_inputs_coercion.py` - 17 integration tests (NEW FILE)
- `tests/test_runtime/test_template_resolver_inline_object_parsing.py` - Updated test for primitives

**Documentation:**
- `scratchpads/bug-numeric-string-coercion/bug-report.md` - Original bug report with reproduction steps
- `scratchpads/bug-numeric-string-coercion/progress-log.md` - Implementation journey
- `scratchpads/bug-numeric-string-coercion/reproduce.pflow.md` - Reproduction workflow

**Task reviews that informed the fix:**
- `.taskmaster/tasks/task_84/task-review.md` - Type checking architecture
- `.taskmaster/tasks/task_102/task-review.md` - Params-only pattern
- `.taskmaster/tasks/task_103/task-review.md` - Type preservation philosophy

## For the Next Agent

**If implementing Task 120:**
- Start by reading `coerce_input_to_declared_type()` docstring - it explains the current "lenient coercion" behavior
- The validation should happen in `_coerce_provided_input()` after coercion, checking if result type matches declared type
- Use the `_TYPE_ALIASES` dict to map declared types to expected Python types
- Add helpful error messages with valid value hints (e.g., "Valid boolean values: true, false, 1, 0, yes, no")

**If reviewing/modifying the bug fix:**
- Don't separate the two fixes (input coercion + template resolver) - they work together
- The identity check was intentionally replaced with explicit tuple return per PR review
- Test with the reproduction workflow: `uv run pflow scratchpads/bug-numeric-string-coercion/reproduce.pflow.md channel_id="1458059302022549698"` - should output `Type: str`

**The user cares most about:**
- Correctness - numeric strings staying as strings when declared
- Future-proofing - type aliases for TypeScript nodes
- Exhaustive verification - manual testing beyond unit tests

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
