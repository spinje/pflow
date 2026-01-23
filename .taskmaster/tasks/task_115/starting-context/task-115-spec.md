# Feature: stdin_input_routing

## Objective

Route piped stdin to workflow inputs marked with `stdin: true`.

## Requirements

- Must add `stdin` boolean field to workflow input schema in IR
- Must route stdin content to the input marked `stdin: true` before validation
- Must error if stdin is piped but no input has `stdin: true`
- Must error if multiple inputs have `stdin: true`
- Must allow CLI parameter to override stdin for the same input
- Must remove legacy `${stdin}` shared store pattern entirely
- Must update documentation to reflect stdin routing capability

## Scope

- Does not implement type-based auto-detection of stdin target
- Does not route binary stdin data (only text)
- Does not route large stdin via temp file path (only in-memory text)
- Does not auto-enable `-p` flag for stdout piping (separate concern)
- Does not modify output routing behavior

## Inputs

- `stdin_data`: str | StdinData | None - Piped stdin content from CLI
- `workflow_ir`: dict[str, Any] - Parsed workflow IR containing input declarations
- `params`: dict[str, Any] - CLI parameters parsed from command line arguments

## Outputs

Returns: dict[str, Any] - Modified params dict with stdin routed to target input

Side effects:
- Schema validation accepts `stdin: true` on input declarations
- Workflow validation rejects multiple `stdin: true` inputs
- Legacy `populate_shared_store()` calls removed from execution path

## Structured Formats

```json
{
  "input_declaration_schema": {
    "type": "object",
    "properties": {
      "description": {"type": "string"},
      "required": {"type": "boolean", "default": true},
      "type": {"type": "string", "enum": ["string", "number", "boolean", "object", "array"]},
      "default": {},
      "stdin": {"type": "boolean", "default": false}
    },
    "additionalProperties": false
  },
  "routing_result": {
    "target_input": "string | null",
    "stdin_routed": "boolean",
    "cli_override": "boolean"
  }
}
```

## State/Flow Changes

```
CLI invocation (workflow_command)
  ↓
_read_stdin_data() → stdin_data: str | StdinData | None
  ↓
resolve_workflow() → workflow_ir: dict
  ↓
_validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args, stdin_data):
  │
  ├─ parse_workflow_params(remaining_args) → params: dict
  │
  ├─ [NEW] _route_stdin_to_params(stdin_data, workflow_ir, params) → params (mutated)
  │    ├─ _find_stdin_input(workflow_ir) → target: str | None
  │    └─ if target and target not in params: params[target] = stdin_content
  │
  └─ prepare_inputs(workflow_ir, params) → validates required inputs present
  ↓
execute_json_workflow()
```

Note: Stdin routing happens INSIDE `_validate_and_prepare_workflow_params()`, between
parsing (line 3093) and validation (line 3121). This ensures stdin-provided values
are present when `prepare_inputs()` checks for required inputs.

Two execution paths both use this function:
1. `_handle_named_workflow()` → direct file/saved workflows
2. `_execute_successful_workflow()` → planner-generated workflows

## Constraints

- Exactly zero or one input per workflow may have `stdin: true`
- `stdin: true` input must be declared in workflow `inputs` section
- CLI parameter with same name as `stdin: true` input takes precedence over stdin
- Only text stdin (str or StdinData.text_data) is routed; binary and temp file paths are not routed
- Injection point must be after workflow IR load and before parameter validation

## Rules

1. If `stdin_data` is None then return `params` unchanged.
2. If `stdin_data` is StdinData with `text_data` populated then extract text content.
3. If `stdin_data` is StdinData with only `binary_data` or `temp_path` then return `params` unchanged.
4. If `stdin_data` is str then use directly as content.
5. If zero inputs have `stdin: true` and stdin is piped then raise ValueError with agent-friendly message explaining how to add `stdin: true`.
6. If exactly one input has `stdin: true` then use that input as target.
7. If multiple inputs have `stdin: true` then raise ValueError with agent-friendly message listing the conflicting input names and how to fix.
8. If target input already exists in `params` then return `params` unchanged (CLI override).
9. If target input does not exist in `params` then add `params[target] = stdin_content`.
10. Schema must accept `stdin` boolean field on input declarations with default `false`.
11. Validation must reject workflows with multiple `stdin: true` inputs during IR validation.
12. Legacy `populate_shared_store()` must be removed from `executor_service.py`.
13. Legacy `${stdin}` references in shared store must not be supported.

## Edge Cases

- Stdin is empty string → Route empty string to target input (valid content).
- Stdin is valid JSON object → Route as string (no parsing/type coercion).
- Stdin is binary data → Do not route; return params unchanged.
- Stdin is large file (temp_path) → Do not route; return params unchanged.
- Stdin input is optional with default → Stdin overrides default.
- Stdin input is required, no stdin piped, no CLI param → Normal validation error "requires input X".
- Workflow has no `inputs` section → `_find_stdin_input` returns None; if stdin piped, raise error.
- Input name contains special characters → Handled by existing input name validation, not this feature.

## Error Handling

### Error Message Design Principles

Error messages must be **agent-friendly** - designed for AI agents creating and running pflow workflows:

1. **No internals**: Never expose function names, line numbers, stack traces, or implementation details.
2. **Instructional**: Tell the agent exactly what to change in the workflow JSON.
3. **Show syntax**: Include the JSON syntax needed to fix the issue.
4. **Minimal examples**: When helpful, show a brief example of correct usage.
5. **Actionable**: Focus on what the agent should do, not what went wrong internally.

**Implementation approach**:

Since stdin routing happens INSIDE `_validate_and_prepare_workflow_params()` BEFORE `prepare_inputs()` runs:

1. `_route_stdin_to_params()` returns `(params, error)` tuple where error is `str | None`
2. If error is not None, display with `click.echo(..., err=True)` and call `ctx.exit(1)`
3. `ctx` is available in `_validate_and_prepare_workflow_params()` - pass it to routing function
4. Use multi-line `click.echo()` for JSON examples (tuple format too limited)

This matches the existing pattern for invalid parameter names (lines 3096-3100).

### Error Messages

Follow pflow's existing patterns: `❌` prefix, `👉` for suggestions, 3-space indentation.

**No `stdin: true` input when stdin is piped:**
```
❌ Piped input cannot be routed to workflow

   This workflow has no input marked with "stdin": true.
   To accept piped data, add "stdin": true to one input declaration.

   Example:
     "inputs": {
       "data": {"type": "string", "required": true, "stdin": true}
     }

   👉 Add "stdin": true to the input that should receive piped data
```

**Multiple `stdin: true` inputs:**
```
❌ Multiple inputs marked with "stdin": true: {name1}, {name2}

   Only one input can receive piped data.

   👉 Remove "stdin": true from all but one input
```

**Binary stdin with `stdin: true` input:**
Silent no-op - stdin not routed. If the input is required, the standard "Workflow requires input 'X'" error will appear, which is actionable (agent knows to provide the input via CLI or fix the piped data).

## Non-Functional Criteria

- Routing logic executes in O(n) where n = number of declared inputs.
- No additional file I/O beyond existing stdin reading.
- No network calls.
- Memory: stdin content stored once in params dict (no duplication).

## Examples

**Example 1: Basic stdin routing**
```json
{
  "inputs": {
    "data": {"type": "string", "required": true, "stdin": true}
  }
}
```
```bash
echo "hello" | pflow workflow.json
# Result: params = {"data": "hello"}
```

**Example 2: CLI override**
```bash
echo "from_pipe" | pflow workflow.json data="from_cli"
# Result: params = {"data": "from_cli"}
```

**Example 3: Multiple inputs, one stdin**
```json
{
  "inputs": {
    "source": {"type": "string", "required": true, "stdin": true},
    "template": {"type": "string", "required": true}
  }
}
```
```bash
echo "data" | pflow workflow.json template="Hello {name}"
# Result: params = {"source": "data", "template": "Hello {name}"}
```

**Example 4: No stdin: true, piping fails**
```json
{
  "inputs": {
    "path": {"type": "string", "required": true}
  }
}
```
```bash
echo "/tmp/file" | pflow workflow.json
# Error: Workflow has no input marked with stdin: true
```

**Example 5: Multiple stdin: true, validation fails**
```json
{
  "inputs": {
    "a": {"type": "string", "stdin": true},
    "b": {"type": "string", "stdin": true}
  }
}
```
```bash
pflow workflow.json
# Error: Multiple inputs marked with stdin: true: a, b
```

## Test Criteria

1. Given `stdin_data=None` and `params={"x": 1}` then return `{"x": 1}` unchanged.
2. Given `stdin_data="hello"` and workflow with `data: {stdin: true}` and `params={}` then return `{"data": "hello"}`.
3. Given `stdin_data="hello"` and workflow with `data: {stdin: true}` and `params={"data": "override"}` then return `{"data": "override"}`.
4. Given `stdin_data="hello"` and workflow with no `stdin: true` input then raise ValueError containing "Piped input cannot be routed" and "stdin\": true".
5. Given workflow with inputs `a: {stdin: true}` and `b: {stdin: true}` then raise ValueError containing "Multiple inputs marked" and lists both input names.
6. Given `stdin_data=StdinData(text_data="hello")` and workflow with `data: {stdin: true}` then return `{"data": "hello"}`.
7. Given `stdin_data=StdinData(binary_data=b"\x00\x01")` and workflow with `data: {stdin: true}` then return `params` unchanged.
8. Given `stdin_data=StdinData(temp_path="/tmp/x")` and workflow with `data: {stdin: true}` then return `params` unchanged.
9. Given `stdin_data=""` (empty string) and workflow with `data: {stdin: true}` then return `{"data": ""}`.
10. Given workflow IR with `inputs.data.stdin: true` then schema validation passes.
11. Given workflow IR with `inputs.data.stdin: "yes"` (wrong type) then schema validation fails.
12. Given workflow IR with two inputs both having `stdin: true` then workflow validation returns error.
13. Verify `populate_shared_store` is not called in `executor_service.execute_workflow`.
14. Verify `shared["stdin"]` is not set during workflow execution.
15. Given stdin piped and workflow has `stdin: true` input then workflow executes with stdin value in that input.
16. Given no stdin piped and workflow has required `stdin: true` input and no CLI param then validation error "requires input".

## Notes (Why)

- Explicit `stdin: true` chosen over type-based auto-detection for predictability and agent-friendliness.
- Single stdin input constraint simplifies routing logic and avoids ambiguity.
- CLI override enables debugging/testing workflows without modifying piped data.
- Removing `${stdin}` shared store pattern ensures inputs work uniformly via CLI or stdin.
- Binary/large file stdin deferred to avoid scope creep; text covers 95% of piping use cases.

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
|--------|---------------------------|
| 1      | 1                         |
| 2      | 6                         |
| 3      | 7, 8                      |
| 4      | 2                         |
| 5      | 4                         |
| 6      | 2, 6                      |
| 7      | 5, 12                     |
| 8      | 3                         |
| 9      | 2, 15                     |
| 10     | 10, 11                    |
| 11     | 12                        |
| 12     | 13                        |
| 13     | 14                        |

| Edge Case | Covered By Test Criteria # |
|-----------|---------------------------|
| Empty string stdin | 9                    |
| JSON object as string | 2 (implicit)      |
| Binary stdin | 7                          |
| Large file stdin | 8                      |
| Optional input with default | 2 (default overridden) |
| Required input, no stdin, no CLI | 16     |
| No inputs section | 4 (implicit)          |

## Versioning & Evolution

- **Version:** 1.3.0
- **Changelog:**
  - **1.3.0** — Clarified error architecture: use `click.echo()` + `ctx.exit(1)` pattern matching existing validation errors. Function returns `(params, error)` tuple.
  - **1.2.0** — Added Error Message Design Principles for agent-friendly errors. Updated error message formats with JSON examples.
  - **1.1.0** — Corrected injection point after codebase verification. Routing happens INSIDE `_validate_and_prepare_workflow_params()` between parsing and validation. Added `planning/nodes.py` to ripple effects.
  - **1.0.0** — Initial specification for explicit stdin routing via `stdin: true` input flag.

## Epistemic Appendix

### Assumptions & Unknowns

- **A1**: Stdin reading via `_read_stdin_data()` returns text content in `StdinData.text_data` for small text inputs. Verified via research-findings.md.
- **A2**: Injection point is INSIDE `_validate_and_prepare_workflow_params()` between `parse_workflow_params()` (line 3093) and `prepare_inputs()` (line 3121). Function must be modified to accept `stdin_data` parameter. Verified via codebase search - validation happens inside this function, not after it.
- **A3**: No existing workflows use `${stdin}` in production since project has no users yet. Stated in CLAUDE.md.
- **A4**: Binary stdin handling can be deferred without breaking core use cases. Design decision, not verified.

### Conflicts & Resolutions

- **C1**: research-findings.md contains outdated type-detection algorithm code. **Resolution**: Task spec updated to remove type detection; research doc is historical context only. Source of truth: task-115.md.
- **C2**: `populate_shared_store()` exists but only accepts `str`, not `StdinData`. **Resolution**: Function will be removed entirely per design decision to eliminate `${stdin}` pattern.
- **C3**: Original A2 assumed injection at line 3261 (after `_validate_and_prepare_workflow_params()`), but validation happens INSIDE that function. **Resolution**: Spec v1.1.0 corrects this - injection point is inside the function, between `parse_workflow_params()` and `prepare_inputs()`.

### Decision Log / Tradeoffs

- **D1**: Explicit `stdin: true` vs type-based auto-detection.
  - Options: (a) Detect stdin JSON type, match to input types; (b) Require explicit `stdin: true` flag.
  - Tradeoffs: (a) "magic" but fragile, adds edge cases; (b) explicit but requires workflow change.
  - **Decision**: (b) Explicit flag. Rationale: agent-friendly, predictable, single rule.

- **D2**: Binary/large stdin handling.
  - Options: (a) Route file path to input; (b) Base64 encode binary; (c) Defer, text-only.
  - Tradeoffs: (a) changes input semantics; (b) memory overhead; (c) covers 95% use cases.
  - **Decision**: (c) Text-only for now. Binary/large file support can be added later if needed.

- **D3**: Error vs silent no-op for binary stdin.
  - Options: (a) Raise error if binary piped to workflow with `stdin: true`; (b) Silent no-op.
  - Tradeoffs: (a) explicit failure, user knows why; (b) may cause confusing downstream error.
  - **Decision**: (b) Silent no-op. Rationale: downstream "missing required input" error is informative enough; explicit binary error adds complexity for rare case.

### Ripple Effects / Impact Map

- `src/pflow/core/ir_schema.py`: Add `stdin` field to input schema.
- `src/pflow/cli/main.py`: Modify `_validate_and_prepare_workflow_params()` to accept `stdin_data`; add `_find_stdin_input()`, `_route_stdin_to_params()`; integrate between lines 3093-3121.
- `src/pflow/runtime/workflow_validator.py`: Add multi-stdin validation in `prepare_inputs()`.
- `src/pflow/execution/executor_service.py`: Remove `populate_shared_store()` call at line 176.
- `src/pflow/core/shell_integration.py`: Remove `populate_shared_store()` function (lines 200-210).
- `src/pflow/core/__init__.py`: Remove `populate_shared_store` from imports and `__all__`.
- `src/pflow/planning/nodes.py`: Remove stdin checking logic in `ParameterDiscoveryNode.prep()` (lines 840-847).
- `tests/test_shell_integration.py`: Remove tests for `populate_shared_store()`.
- `tests/test_integration/test_user_nodes.py`: Update tests using `shared["stdin"]`.
- `tests/test_planning/`: Update tests that set `shared["stdin"]` or `shared["stdin_data"]`.
- `docs/reference/cli/index.mdx`: Update stdin documentation (line 125 mentions `${stdin}`).
- `architecture/overview.md`, `architecture/architecture.md`: Add Unix-first piping documentation.

### Residual Risks & Confidence

- **Risk**: Binary stdin silently not routed may confuse users. **Mitigation**: Document text-only limitation. **Confidence**: Medium.
- **Risk**: Removing `${stdin}` breaks undocumented usage. **Mitigation**: No users exist per CLAUDE.md. **Confidence**: High.
- **Risk**: `_validate_and_prepare_workflow_params()` signature change affects callers. **Mitigation**: Only two callers, both in same file. **Confidence**: High.

### Epistemic Audit (Checklist Answers)

1. **Assumptions made**: A1-A4 listed above. A4 (binary deferral) is design choice, not verified need.
2. **What breaks if wrong**: If A2 wrong (injection point), stdin won't be available at validation; test 15 will fail. If A4 wrong, users needing binary will be blocked. A2 has been verified via codebase search - injection must be INSIDE `_validate_and_prepare_workflow_params()`.
3. **Elegance vs robustness**: Chose robustness (explicit flag, text-only, clear errors) over elegance (auto-detection, full stdin support).
4. **Rule-Test mapping**: All 13 rules mapped to tests. All 7 edge cases mapped to tests. See Compliance Matrix.
5. **Ripple effects**: 12+ files affected. Listed in Impact Map.
6. **Remaining uncertainty**: Binary/large stdin UX is uncertain. **Confidence**: High for core text routing; Medium for edge case handling.
