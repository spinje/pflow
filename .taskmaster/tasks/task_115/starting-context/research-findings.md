# Task 115: Research Findings - Automatic Stdin Routing

## Executive Summary

This document captures the codebase research for implementing stdin routing in pflow. It documents file locations, current behavior, and technical details discovered during research.

**Key Finding**: Validation runs BEFORE stdin could be injected. The solution is to route stdin to inputs marked with `stdin: true` INSIDE `_validate_and_prepare_workflow_params()`, between parsing and validation.

**NOTE**: This is a research document. For the final design and implementation approach, see `task-115-spec.md` which is the source of truth.

---

## 1. Current Stdin Handling Flow

### 1.1 Reading Stdin

**Entry Point**: `src/pflow/cli/main.py:3719`

```python
stdin_content, enhanced_stdin = _read_stdin_data()
stdin_data = enhanced_stdin if enhanced_stdin else stdin_content
```

**Function**: `_read_stdin_data()` (lines 114-128)
- First tries simple text reading: `read_stdin_content()`
- Falls back to enhanced reading for binary/large data: `read_stdin_enhanced()`
- Returns `(str | None, StdinData | None)` tuple

### 1.2 StdinData Structure

**Location**: `src/pflow/core/shell_integration.py:29-56`

```python
@dataclass
class StdinData:
    text_data: str | None = None      # UTF-8 text under 10MB
    binary_data: bytes | None = None  # Binary content under 10MB
    temp_path: str | None = None      # Path to temp file for data over 10MB
```

### 1.3 Current Injection Path

```
CLI (main.py:3719) reads stdin
  ↓
Passes to execute_json_workflow (line 2183, param stdin_data)
  ↓
Calls workflow_execution.execute_workflow (line 479, param stdin_data)
  ↓
Calls executor_service.execute_workflow (line 57, param stdin_data)
  ↓
Calls _initialize_shared_store (line 147)
  ↓
Calls populate_shared_store (line 176)
  ↓
shared["stdin"] = content  (ONLY if string, bug for StdinData!)
```

### 1.4 Critical Bug Identified

`populate_shared_store()` in `shell_integration.py:200-210` only accepts `str`:

```python
def populate_shared_store(shared: dict, content: str) -> None:
    shared["stdin"] = content
```

But the CLI passes `StdinData` objects for binary/large data - type mismatch!

There's also an unused `_inject_stdin_object()` function at `main.py:259-272` that handles StdinData properly but isn't called in the execution path.

---

## 2. Validation Pipeline

### 2.1 Validation Entry Point

**Location**: `src/pflow/core/workflow_validator.py:24-98`

```python
@staticmethod
def validate(
    workflow_ir: dict[str, Any],
    extracted_params: Optional[dict[str, Any]] = None,
    registry: Optional[Registry] = None,
    skip_node_types: bool = False,
) -> tuple[list[str], list[Any]]:
```

**Validation Layers** (in order):
1. Structural validation - IR schema compliance
2. Data flow validation - Execution order, circular dependency detection
3. Template validation - Variable resolution (uses `extracted_params`)
4. Node type validation - Registry verification
5. Output source validation - Output references point to valid nodes
6. JSON string template validation - Anti-pattern detection

### 2.2 When Validation Happens

**Location**: `src/pflow/cli/main.py:2164`

```python
# Validate before execution (if not using auto-repair)
if not auto_repair:
    _validate_before_execution(ctx, ir_data, enhanced_params, output_format, verbose)
```

**Critical Issue**: At this point, `enhanced_params` does NOT include stdin data. Stdin is passed separately and only injected into shared store AFTER validation.

### 2.3 Parameter Building Flow

1. **CLI args parsed**: `parse_workflow_params()` at line 3093
2. **Enhanced params built**: Lines 1346-1351 add system flags
3. **Validation called**: Line 2164 with `enhanced_params`
4. **Execution called**: Line 2183 with `enhanced_params` AND `stdin_data` separately

### 2.4 Template Validation Errors

**"Template variable ${X} has no valid source"** comes from `template_validator.py`:
- Line 698: Namespaced mode - not a node or input
- Line 703: Non-namespaced mode - path not found
- Line 735: Simple template - not provided

---

## 3. Workflow IR Schema - Input Declarations

### 3.1 Current Schema

**Location**: `src/pflow/core/ir_schema.py:252-270`

```python
"inputs": {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "required": {"type": "boolean", "default": True},
            "type": {
                "type": "string",
                "enum": ["string", "number", "boolean", "object", "array"]
            },
            "default": {"description": "Default value if not provided"}
        },
        "additionalProperties": False  # ← Must add "stdin" here
    }
}
```

### 3.2 How to Add `stdin` Field

Add to the `properties` object:

```python
"stdin": {
    "type": "boolean",
    "default": False,
    "description": "Whether to route piped stdin to this input"
}
```

### 3.3 Type Field is Documentation Only

**Important**: The `type` field on inputs is NOT validated at runtime. No type coercion occurs. This means stdin type detection will need its own logic - can't rely on existing type validation.

---

## 4. Template Resolution

### 4.1 Resolution Pattern

**Location**: `src/pflow/runtime/template_resolver.py:27-31`

```python
TEMPLATE_PATTERN = re.compile(r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[\d+\])?(?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)?)\}")
```

### 4.2 Resolution Sources (Priority Order)

1. **initial_params** - From planner or CLI parameters (highest priority)
2. **Shared store** - Runtime data written by nodes
3. **Workflow inputs** - Declared inputs

### 4.3 Type Preservation

- **Simple templates** (`${var}`): Preserve original type (int, bool, dict, list)
- **Complex templates** (`"Hello ${name}"`): Always return strings

---

## 5. Output Routing (-p Flag)

### 5.1 OutputController

**Location**: `src/pflow/core/output_controller.py:56-71`

```python
def is_interactive(self) -> bool:
    if self.print_flag:      # Rule 1: -p forces non-interactive
        return False
    if self.output_format == "json":  # Rule 2: JSON implies non-interactive
        return False
    return self.stdin_tty and self.stdout_tty  # Rules 3 & 4: Both must be TTY
```

### 5.2 Three Output Modes

**Location**: `src/pflow/cli/main.py:332-378` (`_output_with_header()`)

1. **--print mode** (`print_flag=True`):
   - ONLY raw output to stdout, no header, no summary
   - Perfect for piping: `pflow -p workflow.json | jq`

2. **Interactive terminal** (`is_interactive()=True`):
   - Unix convention: header/summary to stderr, data to stdout

3. **Non-interactive** (`is_interactive()=False`, `print_flag=False`):
   - Everything to stderr for correct ordering
   - **This is why piping breaks without -p!**

### 5.3 Current Piping Behavior

Without `-p` flag:
```
stdout.isatty() == False (pipe detected)
  → Mode 3 triggered
  → ALL output goes to stderr
  → Downstream command receives NOTHING on stdin
```

With `-p` flag:
```
print_flag = True
  → Mode 1 triggered
  → Raw output only to stdout
  → Downstream command receives clean data
```

---

## 6. Complete Execution Flow

### 6.1 Numbered Sequence

1. **CLI Entry**: `main_wrapper.py:cli_main()` → routes to `workflow_command()`
2. **Context Init**: `_initialize_context()`, inject settings, auto-discover MCP
3. **Stdin Reading**: `_read_stdin_data()` at line 3719
4. **Workflow Resolution**: `resolve_workflow()` loads IR from file/saved
5. **Parameter Parsing**: `parse_workflow_params()` at line 3093
6. **Parameter Validation**: `_validate_and_prepare_workflow_params()` with `prepare_inputs()`
7. **Execute JSON Workflow**: `execute_json_workflow()` at line 2121
8. **Pre-Validation**: `_validate_before_execution()` at line 2164 (**stdin NOT available**)
9. **Execute Workflow**: `workflow_execution.execute_workflow()` at line 2183
10. **Executor Service**: `executor_service.execute_workflow()`
11. **Shared Store Init**: `_initialize_shared_store()` - **stdin finally injected here**
12. **Compilation**: `compile_ir_to_flow()`
13. **Flow Execution**: PocketFlow `Flow.run()`
14. **Result Processing**: Extract outputs, determine status
15. **Output Handling**: Route to appropriate display handler

### 6.2 The Gap

```
Step 6: Parameter Validation - enhanced_params has CLI args, NO stdin
Step 8: Pre-Validation - validates templates against enhanced_params
         ↓
         ERROR: ${data} has no valid source (stdin not in params!)
         ↓
Step 11: Stdin finally injected - TOO LATE!
```

---

## 7. Implementation Strategy

**NOTE**: This section contains early research. See `task-115-spec.md` for the final design which uses explicit `stdin: true` only (no type detection).

### 7.1 Correct Injection Point (VERIFIED)

**Location**: INSIDE `_validate_and_prepare_workflow_params()` in `src/pflow/cli/main.py`

```
Line 3093: params = parse_workflow_params(remaining_args)
           ↓
           [INJECT STDIN ROUTING HERE]
           ↓
Line 3121: errors, defaults, env_param_names = prepare_inputs(...)
```

**Why INSIDE the function**:
- `prepare_inputs()` at line 3121 validates required inputs
- If routing happens AFTER this function, required inputs expecting stdin fail validation
- The function must be modified to accept `stdin_data` parameter

### 7.2 Files to Modify

| File | Change |
|------|--------|
| `src/pflow/core/ir_schema.py:265` | Add `stdin` boolean field to input schema |
| `src/pflow/cli/main.py:3076-3140` | Modify `_validate_and_prepare_workflow_params()` to accept and route stdin |
| `src/pflow/runtime/workflow_validator.py:72-195` | Add multi-stdin validation in `prepare_inputs()` |
| `src/pflow/execution/executor_service.py:176` | Remove `populate_shared_store()` call |
| `src/pflow/core/shell_integration.py:200-210` | Remove `populate_shared_store()` function |
| `src/pflow/planning/nodes.py:840-847` | Remove stdin checking in ParameterDiscoveryNode |

### 7.3 Edge Cases (Final Design)

1. **No stdin provided, input marked `stdin: true`**:
   - Normal behavior - input is required, must be provided via CLI

2. **Stdin provided, no `stdin: true` input**:
   - Error with JSON example showing how to add `stdin: true`

3. **Multiple `stdin: true` inputs**:
   - Error listing the conflicting input names

4. **CLI param overrides stdin**:
   - `echo "ignored" | pflow workflow.json data="used"` → uses "used"

5. **Binary stdin**:
   - Silent no-op - not routed, may cause "missing input" error downstream

6. **Large stdin (temp file)**:
   - Silent no-op - not routed

---

## 8. Testing Strategy

**NOTE**: See `task-115-spec.md` for complete test criteria (16 tests defined).

### 8.1 Unit Tests

1. `_find_stdin_input()` - Find input with `stdin: true`, handle zero/one/multiple
2. `_extract_stdin_text()` - Extract text from `str` or `StdinData.text_data`
3. Routing logic - Integration of above

### 8.2 Integration Tests

1. **Basic piping**: `echo '{"x": 1}' | pflow workflow.json` (with `stdin: true` input)
2. **No stdin input error**: Piping to workflow without `stdin: true`
3. **Multiple stdin error**: Workflow with two `stdin: true` inputs
4. **CLI override**: CLI param takes precedence over stdin
5. **Same workflow via CLI**: `pflow workflow.json data='{"x": 1}'`

### 8.3 End-to-End Tests

1. **Pipeline composition**: `pflow -p step1.json | pflow step2.json`
2. **Mixed tools**: `cat data.json | pflow transform.json | jq '.result'`

---

## 9. Documentation Updates Required

After implementation:

1. **Architecture docs** (`architecture/overview.md`, `architecture/architecture.md`):
   - Add Unix-first as explicit design principle
   - Document stdin/stdout contract

2. **CLI instructions** (`src/pflow/cli/resources/`):
   - Add piping examples
   - Document `stdin: true` flag

3. **Verify**: `pflow instructions usage` and `pflow instructions create` show piping examples

---

## 10. Resolved Questions

These questions were resolved during design discussion:

1. **Type-based auto-detection?**
   - **Decision**: No. Explicit `stdin: true` only. User said auto-detection was "hedging".

2. **Keep `${stdin}` in shared store?**
   - **Decision**: No. Remove entirely. `stdin: true` on inputs is more flexible (works via CLI too).

3. **Binary/large stdin handling?**
   - **Decision**: Defer. Silent no-op for now. Text-only covers 95% of use cases.

4. **Error message style?**
   - **Decision**: Agent-friendly with JSON examples. Use `click.echo()` + `ctx.exit(1)`.

See `task-115-spec.md` for complete design decisions and rationale.

---

## Appendix: Key File Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| Stdin reading | `src/pflow/cli/main.py` | 114-128, 3719 |
| StdinData class | `src/pflow/core/shell_integration.py` | 29-56 |
| populate_shared_store | `src/pflow/core/shell_integration.py` | 200-210 |
| Validation entry | `src/pflow/core/workflow_validator.py` | 24-98 |
| Pre-execution validation | `src/pflow/cli/main.py` | 2164 |
| IR schema (inputs) | `src/pflow/core/ir_schema.py` | 252-270 |
| Template validation | `src/pflow/runtime/template_validator.py` | 203-297 |
| Template errors | `src/pflow/runtime/template_validator.py` | 696-737 |
| Output controller | `src/pflow/core/output_controller.py` | 56-71 |
| Output routing | `src/pflow/cli/main.py` | 332-378 |
| Executor service | `src/pflow/execution/executor_service.py` | 57, 147-187 |
| Shared store init | `src/pflow/execution/executor_service.py` | 147-187 |
