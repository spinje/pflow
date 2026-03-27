# Braindump: Type Validation Gap Discovered During Sub-Workflow Validation Bug Fix

## Where I Am

This braindump comes from a deep investigation of the sub-workflow validation bug (branch `fix/sub-workflow-validation-errors`). We weren't working on Task 120 — we were figuring out why sub-workflow validation errors aren't caught at parse time. But the investigation uncovered significant new context about pflow's type validation gap that directly affects Task 120's scope and design.

## User's Mental Model

The user asked a sharp question during our analysis: "What would we need to also be able to detect if all required inputs are being sent to the subworkflow?" This led to systematically categorizing every validation check in the system into three categories:

- **Category A (structural)**: ~90% of checks. No runtime values needed.
- **Category B (needs input key names)**: ~5%. Template path existence — needs to know which params exist, not their values.
- **Category C (needs runtime values)**: ~5%. Required input presence, empty string, **type coercion**.

The user then asked: "wouldn't mocking also solve C problems?" — meaning, if we generate dummy/placeholder values for sub-workflow inputs, could we catch type mismatches at validation time? After thorough analysis, the answer was **no**, specifically because of lenient coercion.

The user's reaction to learning that declared types are effectively documentation-only: they asked "do you agree with this?" — questioning whether the lenient design is actually good. The consensus was that the "better context" rationale in `coerce_input_to_declared_type()`'s docstring is weak, but fixing it is Task 120's job, not the sub-workflow bug's.

The user sees Task 120 as broader than just CLI inputs. Their mental model is: **types should be enforced, period** — whether the input comes from CLI, a parent workflow, env vars, or defaults.

## Key Insights

### 1. Declared types are enforced NOWHERE in the pipeline

This was the most surprising finding. We traced every node type:

- **Shell nodes**: interpolate into command strings — never type-check
- **LLM nodes**: interpolate into prompts — never type-check
- **HTTP nodes**: interpolate into URLs/bodies — never type-check
- **File nodes**: interpolate into paths/content — never type-check
- **Code nodes**: the ONLY type that might do type checking, but it's the user's Python code that fails, not pflow

The docstring in `coerce_input_to_declared_type()` says lenient coercion "allows downstream validation (e.g., code node type checking) to catch the error with full context." But "code node type checking" means the user's own `int(text)` call failing — not a pflow-provided check. For every other node type, the type mismatch is silently ignored.

### 2. `prepare_inputs()` is called for sub-workflows too

The task description focuses on CLI inputs, but `prepare_inputs()` is called from `compile_ir_to_flow()` (`compile_validation.py:208`), which is called for EVERY sub-workflow compilation in `WorkflowExecutor._compile_sub_workflow()`. This means Task 120's strict validation would automatically apply to sub-workflow inputs too — a much larger blast radius than just CLI.

NEEDS VERIFICATION: Does this create issues for sub-workflow inputs where values come from template resolution (always strings) rather than CLI (where `infer_type()` attempts type detection)?

### 3. Two conflicting "required" heuristics exist

| Component | Location | Heuristic |
|---|---|---|
| `WorkflowExecutor._validate_child_params()` | `workflow_executor.py:379` | `"default" not in input_spec` |
| `ir_preparation.prepare_inputs()` | `ir_preparation.py:59` | `input_spec.get("required", True)` |

An input declared `{required: false}` without a default is treated as **required** by the WorkflowExecutor but **optional** by prepare_inputs. Task 120 should harmonize these.

### 4. Mock/dummy values can't catch type errors

We analyzed this exhaustively. `generate_dummy_parameters()` produces `"__validation_placeholder__"` for all inputs regardless of type. If you pass this through `prepare_inputs()`:

- `string` input: placeholder is a string, passes trivially
- `integer` input: `int("__validation_placeholder__")` raises ValueError, caught silently, original string returned, no error
- `boolean`, `array`, `object`: same — lenient coercion swallows the failure

Even with smarter mocks (e.g., `0` for integer), the checks would just pass trivially. The lenient coercion design means `prepare_inputs()` fundamentally cannot produce type errors — making Task 120 necessary.

### 5. Template resolution always produces strings

When `${upstream.count}` resolves, even if `upstream.count` was stored as `int(5)`, the template system may return `"5"` (string). This means sub-workflow inputs arriving via template resolution are often strings regardless of their upstream type. Task 120 needs to handle this — strict type checking can't just reject all strings for integer inputs, because that's how the template system works.

ASSUMPTION: The auto-JSON-parsing in template resolution (`json.loads()` for containers only, after the numeric string bug fix in PR #84) means integer values might still arrive as strings through templates. Task 120 should coerce THEN validate, not validate the raw input.

## Assumptions & Uncertainties

ASSUMPTION: Task 120's strict validation should happen AFTER coercion (check if coercion succeeded), not BEFORE (reject wrong input types). The coercion step is still valuable — `"5"` should coerce to `5` for integer inputs. Only if coercion FAILS should it error.

ASSUMPTION: The `was_coerced` tuple return pattern (added in PR #84) is the right hook point. After `_coerce_provided_input()` returns `(value, was_coerced)`, check if the result type matches the declared type.

UNCLEAR: Should strict validation apply to ALL input sources equally? The 5-tier precedence in `prepare_inputs()` is: CLI → os.environ → settings.env → default → error. Env vars are always strings. Settings values might be typed. Defaults are whatever the workflow author wrote. Each source has different type characteristics.

UNCLEAR: Should strict validation apply to sub-workflow `prepare_inputs()` calls identically to top-level? Template-resolved values from parent workflows behave differently from CLI inputs.

NEEDS VERIFICATION: The existing braindump mentions `_coerce_provided_input()` as the right place. But since PR #84, has the code structure changed? The braindump references `runtime/workflow_validator.py` which may have been refactored into `runtime/compilation/ir_preparation.py`.

## Unexplored Territory

UNEXPLORED: What about batch item types? When `batch.items` is an array of objects, each object's fields become available as `${item.field}`. These fields have no declared types. Should Task 120 consider batch item typing?

CONSIDER: The existing `--validate-only` flow explicitly SKIPS `prepare_inputs()`. If Task 120 adds strict type validation to `prepare_inputs()`, the `--validate-only` path won't benefit. Should validation-only also run prepare_inputs with real CLI values? Currently it uses dummy params to avoid this.

MIGHT MATTER: MCP tool parameters use a DIFFERENT coercion path (`coerce_to_declared_type()`) than workflow inputs (`coerce_input_to_declared_type()`). These are separate functions in `param_coercion.py`. Task 120 might need to address both.

CONSIDER: If strict validation is added, what's the escape hatch? A user might legitimately want to pass a string where an integer is declared (e.g., `"auto"` as a special sentinel). Should there be a `strict_types: false` workflow-level setting? Or is this over-engineering? The user said: "We have NO USERS yet" — maybe just be strict and adjust if needed.

UNEXPLORED: How does this interact with the `inputs-as-template-context` feature (PR #161, just merged)? That feature allows `inputs:` as a node-level param for mapping inputs. If those mapped values need type validation, the scope expands.

## What I'd Tell Myself

1. **The task description undersells the scope.** It says "CLI-provided values" but the real scope is all inputs entering `prepare_inputs()` — CLI, env vars, defaults, AND sub-workflow params.

2. **Don't just add validation — fix the conflicting "required" heuristics first.** Two different functions disagree on what "required" means. Harmonize before adding strict checking on top.

3. **The coerce-then-validate pattern is correct.** Don't reject `"5"` for an integer input — coerce it to `5` first, THEN check if coercion succeeded. The `was_coerced` return pattern from PR #84 is exactly the right hook.

4. **Template-resolved values need special consideration.** They arrive as strings. A naive "reject strings for integer inputs" would break every sub-workflow that passes `- count: ${upstream.count}`.

## Relevant Files & References

**Core type coercion:**
- `src/pflow/core/param_coercion.py` — `coerce_input_to_declared_type()`, lenient coercion, `_TYPE_ALIASES`
- `src/pflow/runtime/compilation/ir_preparation.py` — `prepare_inputs()`, `_coerce_provided_input()`, the 5-tier precedence

**Sub-workflow input validation (runtime, current):**
- `src/pflow/runtime/workflow_executor.py:369-400` — `_validate_child_params()`, the conflicting "required" heuristic
- `src/pflow/runtime/workflow_executor.py:265-271` — `_extract_child_inputs()`, RESERVED_PARAMS filtering

**Dummy/mock parameter generation:**
- `src/pflow/core/validation_utils.py:6-29` — `generate_dummy_parameters()`, produces `"__validation_placeholder__"` for all types

**Previous braindumps (READ THESE FIRST):**
- `.taskmaster/tasks/task_120/starting-context/braindump-numeric-string-coercion-context.md` — original PR #84 context
- `.taskmaster/tasks/task_120/starting-context/broader-validation-gap.md` — empty value detection gap

**The investigation that produced this braindump:**
- `scratchpads/sub-workflow-validation-bug/README.md` — the bug report that led here

## For the Next Agent

**Start by reading** the two existing braindumps in this directory — they cover the original coercion fix (PR #84) and the empty value gap. This braindump adds the sub-workflow dimension.

**The user cares about:** types being enforced, not just documented. They questioned whether the lenient design was correct and concluded it should be changed. They see this as a system-wide concern, not just CLI inputs.

**The hardest part** will be handling template-resolved values (always strings) vs CLI values (type-inferred) vs env vars (always strings) vs defaults (author-typed). Each source has different type characteristics, and a single strict check needs to work for all of them. The coerce-then-validate pattern is the right approach.

**Don't bother with** mock/dummy-based type validation — we proved exhaustively that it can't work due to lenient coercion. Fix the coercion to be strict instead.

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
