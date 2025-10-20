# Task 85 Research Findings

**Date**: 2025-10-20
**Research Phase**: Complete ✅
**Agents Deployed**: 8 (parallel execution)

---

## Executive Summary

This document synthesizes findings from comprehensive codebase research to guide implementation of **Runtime Template Resolution Hardening**. The research covered 8 critical areas and uncovered both the "Nonems" mystery and a critical bug in template error checking.

### Key Discoveries

1. **"Nonems" Mystery Solved**: It's `None` being concatenated with `"ms"` in duration formatting
2. **Critical Bug Found**: Simple templates (`${var}`) skip error checking in `node_wrapper.py`
3. **MCP False Positives**: MCP nodes legitimately return `${...}` as API response data
4. **Repair System Integration**: Template errors already trigger repair with specific guidance
5. **No Escape Mechanism**: The codebase has no way to output literal `${...}` text

---

## 1. The "Nonems" Mystery (SOLVED)

### Root Cause

**Location**: `src/pflow/execution/formatters/success_formatter.py` line 279

```python
return f"  {indicator} {node_id} ({duration}ms){tag_str}"
```

When `duration` is `None` (because node timing wasn't recorded), Python's f-string converts it to the string `"None"`, which concatenates with `"ms"` to produce `"Nonems"`.

### Why It Happens

**Data Flow**:
```
Node execution → Metrics not recorded
   ↓
execution_state.py:85 → "duration_ms": node_timings.get(node_id)  # Returns None
   ↓
success_formatter.py:263 → duration = step.get("duration_ms", 0)  # Gets explicit None, not default 0!
   ↓
success_formatter.py:279 → f"{None}ms" → "Nonems"
```

**Python Behavior**:
```python
# When key exists with None value
step = {"duration_ms": None}
duration = step.get("duration_ms", 0)  # Returns None (not 0!)

# When key doesn't exist
step = {}
duration = step.get("duration_ms", 0)  # Returns 0
```

### Immediate Fix (2 lines)

**File 1**: `src/pflow/execution/execution_state.py`
```python
# Line 85 - Add default value
"duration_ms": node_timings.get(node_id, 0),  # Changed from .get(node_id)
```

**File 2**: `src/pflow/execution/formatters/success_formatter.py`
```python
# Line 263 - Handle None explicitly
duration = step.get("duration_ms") or 0  # Changed from step.get("duration_ms", 0)
```

### Relevance to Task 85

The "Nonems" cryptic warning is a **symptom** of deeper issues:
- Nodes failing silently without clear error messages
- Metrics not being recorded properly when nodes fail
- Error aggregation hiding actual problems

**This aligns with Task 85's goal**: Better error signaling when nodes fail or produce no output.

---

## 2. Template Resolution Flow (COMPLETE MAPPING)

### The Critical Bug

**Location**: `src/pflow/runtime/node_wrapper.py` lines 203-216

```python
resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)
resolved_params[key] = resolved_value

# ⚠️ BUG: Simple templates skip error checking!
if not is_simple_template:  # ← Only checks complex templates
    if resolved_value != template:
        logger.debug(...)
    elif "${" in str(template):
        raise ValueError(...)  # Simple templates NEVER reach here!
```

**What Happens**:
- Simple template `${missing}` returns `("${missing}", True)` with `is_simple_template=True`
- Error check: `if not is_simple_template` → **SKIPPED**
- Node receives `{"param": "${missing}"}` with literal template
- Workflow continues with broken data

**This is THE ROOT CAUSE of Issue #95**

### Resolution Flow (4 Phases)

```
1. PLANNING → Extracts initial_params = {"issue_number": "123"}
       ↓
2. COMPILATION → TemplateValidator checks paths exist at compile-time
       ↓
3. WRAPPING → TemplateAwareNodeWrapper added if params have templates
       ↓
4. RUNTIME → Templates resolved just before node executes
```

### Wrapper Chain

```
InstrumentedNodeWrapper (outermost) ← Where we'll add detection
  └─> NamespacedNodeWrapper (collision prevention)
      └─> TemplateAwareNodeWrapper (template resolution)
          └─> ActualNode (business logic)
```

### Type Preservation Rules

- **Simple template**: `${count}` → `5` (preserves `int`)
- **Complex template**: `"Total: ${count}"` → `"Total: 5"` (always `str`)

### Relevance to Task 85

**Our detection must happen AFTER template resolution** in `InstrumentedNodeWrapper`, not during resolution in `TemplateAwareNodeWrapper`. This way we can:
1. Check the final resolved values before they enter the shared store
2. Catch unresolved templates from any source (simple or complex)
3. Add to existing instrumentation (metrics, tracing, caching)

---

## 3. InstrumentedNodeWrapper Architecture

### Where to Add Code

**Location**: `src/pflow/runtime/instrumented_wrapper.py` line 651

**Integration Point** (after node execution, before API warning check):
```python
# Line 651: Execute the inner node
result = self.inner_node._run(shared)

# [NEW] Check for unresolved templates in output
unresolved_templates = self._detect_unresolved_templates(shared)
if unresolved_templates:
    return self._handle_unresolved_templates(
        shared, unresolved_templates, start_time,
        shared_before, callback, is_planner
    )

# Line 654: Check for API warnings (existing)
warning_msg = self._detect_api_warning(shared)
```

### Two New Methods

**1. Detection Method**:
```python
def _detect_unresolved_templates(self, shared: dict[str, Any]) -> Optional[dict[str, list[str]]]:
    """Scan node output for unresolved template syntax."""
    # Recursively check shared[node_id] for ${...} patterns
    # Return {"path.to.field": ["var1", "var2"]} or None
```

**2. Handler Method**:
```python
def _handle_unresolved_templates(
    self, shared, unresolved_templates, start_time,
    shared_before, callback, is_planner
) -> str:
    """Handle unresolved templates gracefully, trigger repair."""
    # Build detailed error message
    # Mark as repairable (unlike API warnings)
    # Record metrics/trace
    # Return "error" action
```

### Key Difference from API Warnings

| Feature | Unresolved Template | API Warning |
|---------|-------------------|-------------|
| Repairable | ✅ YES | ❌ NO |
| Mark completed | ❌ NO (allow retry) | ✅ YES (prevent retry) |
| Set non_repairable | ❌ NO | ✅ YES |
| Return | "error" | "error" |
| Triggers repair | ✅ YES | ❌ NO |

### Existing Pattern to Follow

**API Warning Pattern** (lines 192-246):
- Fatal, non-repairable errors
- Marks as completed to prevent re-execution
- Sets `__non_repairable_error__ = True`
- Returns "error" but no repair

**Our Pattern Should Be**:
- Repairable errors (LLM can fix template paths)
- Does NOT mark as completed (allow repair/retry)
- Does NOT set `__non_repairable_error__`
- Returns "error" to trigger repair flow

### Relevance to Task 85

This is **exactly where** we'll implement the critical detection:
1. After node has executed (output available)
2. Before output enters shared store (catch before propagation)
3. In instrumented wrapper (get metrics, tracing, checkpointing)
4. Following existing error handling patterns

---

## 4. Workflow Status System

### Current: Binary Success (True/False)

**Determination**: `executor_service.py` lines 184-193
```python
def _is_execution_successful(self, action_result: Optional[str]) -> bool:
    return not (action_result and action_result.startswith("error"))
```

**Issue**: `"successful": True` even when nodes have warnings

### Node Status Tracking

**Data Structure** (`shared["__execution__"]`):
```python
{
    "completed_nodes": ["node1", "node2"],  # Successfully executed
    "node_actions": {"node1": "default", "node2": "default"},
    "node_hashes": {"node1": "md5...", "node2": "md5..."},
    "failed_node": "node3"  # Node that failed
}
```

**Status Values**:
- `"completed"` - Node in completed_nodes
- `"failed"` - Node is the failed_node
- `"not_executed"` - Didn't reach this node

**No intermediate states** like "degraded" or "warning"

### Trace File Format

**Location**: `~/.pflow/debug/workflow-trace-*.json`

**Current**:
```python
{
    "final_status": "failed" | "success",  # Binary only
    "nodes": [
        {
            "success": true,  # Binary per-node
            "error": "..." if failed
        }
    ]
}
```

### Tri-State Implementation Points

**1. Introduce WorkflowStatus Enum**:
```python
# New file: src/pflow/core/workflow_status.py
class WorkflowStatus(str, Enum):
    SUCCESS = "success"
    DEGRADED = "degraded"  # Some nodes had warnings
    FAILED = "failed"
```

**2. Update ExecutionResult** (`executor_service.py`):
```python
@dataclass
class ExecutionResult:
    success: bool  # Keep for backward compat
    status: WorkflowStatus  # NEW: Tri-state status
    warnings: list[dict[str, Any]]  # NEW: Warning list
```

**3. Enhance Status Determination**:
```python
def _determine_workflow_status(
    action_result: Optional[str],
    shared_store: dict[str, Any]
) -> tuple[bool, WorkflowStatus]:
    # Check for failure
    if action_result and action_result.startswith("error"):
        return False, WorkflowStatus.FAILED

    # Check for warnings
    warnings = shared_store.get("__warnings__", {})
    if warnings:
        return True, WorkflowStatus.DEGRADED

    # Full success
    return True, WorkflowStatus.SUCCESS
```

### Relevance to Task 85

**Task 85 needs this tri-state status**:
- **Strict mode**: Template resolution failure → `FAILED`
- **Permissive mode**: Template resolution failure → `DEGRADED` (not `SUCCESS`)
- Current boolean `success` is misleading when warnings exist

The implementation should:
1. Add `WorkflowStatus` enum
2. Keep `success` boolean for backward compatibility
3. Add `status` field for tri-state
4. Populate `warnings` list with template resolution issues

---

## 5. Configuration System Patterns

### How to Add `template_resolution_mode`

**Pattern**: Follow `enable_namespacing` example

#### Step 1: Add to IR Schema

**Location**: `src/pflow/core/ir_schema.py` (after line 230)

```python
"template_resolution_mode": {
    "type": "string",
    "enum": ["strict", "permissive"],
    "description": "Template resolution error behavior",
    "default": "strict"
}
```

**Recommendation**: Use enum (not boolean) for future extensibility

#### Step 2: Add Global Default to Settings

**Location**: `src/pflow/core/settings.py`

```python
class RuntimeSettings(BaseModel):
    """Runtime execution configuration."""
    template_resolution_mode: str = "strict"

class PflowSettings(BaseModel):
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
```

#### Step 3: Compiler Integration

**Location**: `src/pflow/runtime/compiler.py` (in `_validate_workflow()`)

```python
# Get mode from workflow IR or global settings
mode = ir_dict.get("template_resolution_mode")
if mode is None:
    settings = SettingsManager().load()
    mode = settings.runtime.template_resolution_mode

# Pass to wrapper
node_instance = _create_single_node(
    ...,
    template_resolution_mode=mode
)
```

#### Step 4: Wrapper Integration

**Location**: `src/pflow/runtime/node_wrapper.py`

```python
def __init__(self, node, node_id, initial_params, template_resolution_mode="strict"):
    self.template_resolution_mode = template_resolution_mode
```

### Environment Override Pattern

```bash
export PFLOW_TEMPLATE_RESOLUTION_MODE=permissive
pflow workflow.json
```

### Relevance to Task 85

Configuration is **straightforward** following existing patterns:
1. Per-workflow override via IR field
2. Global default via settings
3. Environment variable for testing
4. Propagates through compiler → wrapper

**No architectural surprises or blockers**

---

## 6. Fix 3 Integration Patterns

### No Conflicts with Type Checking

**Fix 3 answers**: "Is this the right **type**?"
**Task 85 answers**: "Does this **value exist**?"

They work in sequence:
1. Path validation (does variable exist in IR?)
2. **Type validation** (Fix 3: are types compatible?)
3. **Resolution validation** (Task 85: is value available at runtime?)

### Error Message Pattern to Reuse

**Multi-section format from Fix 3**:
```
❌ Problem description

💡 Available options:
   - option1
   - option2

✓ Suggestion:
   - Try this
   - Or this
```

**Key Patterns**:
- Visual scanning with emoji (but sparingly)
- Display limits (20 outputs, 3 suggestions)
- Concrete suggestions (not generic advice)
- Sanitize all user-controlled values

### Test Pattern to Follow

**Fix 3 Tests** (25 tests in `test_type_checker.py`):
- Separate test classes for each function
- Mock registry with realistic metadata
- Integration tests in `test_template_validator.py`

**Task 85 Should Have**:
- Unit tests: Detect `${...}` in strings/dicts/lists
- Integration tests: Workflow fails before Slack message sent
- Real-world test: The exact `slack-qa-responder` scenario from Issue #95

### Integration Point

**Location**: `template_validator.py` after line 168 (after type validation)

```python
# Existing: Type validation
type_errors = _validate_template_types(...)

# [NEW] Resolution validation
resolution_errors = _validate_template_resolution(...)

errors.extend(type_errors)
errors.extend(resolution_errors)
```

### Relevance to Task 85

**Learn from Fix 3**:
- Extend existing validation pipeline (don't replace)
- Multi-section error messages with suggestions
- Comprehensive test coverage (unit + integration + real-world)
- No conflicts with existing validation

---

## 7. Repair System Interactions

### Template Errors Already Trigger Repair

**Evidence**: `node_wrapper.py` lines 209-216
```python
raise ValueError(error_msg)  # FATAL - triggers repair
```

**Repair Category**: `template_error` (one of 5 categories)

**Repair Guidance** (`repair_service.py` lines 551-560):
```json
{
    "title": "Template Variable Resolution Errors",
    "guidance": [
        "Template path ${node.field} references non-existent data",
        "Check what fields the referenced node ACTUALLY outputs",
        "Tip: Check if the node uses namespacing"
    ]
}
```

### Repair vs. Fail-Fast Decision

**WITHOUT `--auto-repair`** (default):
- Validation skipped entirely
- Execution runs directly
- **Fails immediately** on first error

**WITH `--auto-repair`**:
- Validation phase: Validate → Repair → Re-validate (up to 3 attempts)
- Runtime phase: Execute → Detect error → Repair → Resume (up to 3 attempts)

### How Repair Uses Error Context

**Enhanced Error Structure** (from Task 71):
```python
{
    "source": "runtime",
    "category": "template_error",
    "message": "Template ${x} not found",
    "node_id": "process",
    "fixable": True,
    "available_fields": ["a", "b"]  # NEW: Shows what's available
}
```

**Repair LLM Prompt**:
```
Error: Template ${fetch.messages} not found

Available fields:
  - fetch.result
  - fetch.result.data
  - fetch.result.data.messages

Suggestion: Use ${fetch.result.data.messages}
```

### Integration Requirements

**Your hardening should**:
1. ✅ Keep `ValueError` for unresolved templates (repair expects this)
2. ✅ Add `available_fields` to error context (matches Task 71 pattern)
3. ✅ Maintain error message structure (parsing depends on format)
4. ✅ Test repair loop with template errors (ensure guidance works)

### Relevance to Task 85

**Template errors are REPAIRABLE**, not fail-fast. Your implementation must:
- Populate `available_fields` in error dict (help repair LLM)
- Preserve `ValueError` pattern (repair system compatibility)
- Test that repair successfully fixes template paths
- Ensure loop detection prevents infinite repairs

---

## 8. Nested Workflows & Edge Cases

### Template Context Isolation

**Child workflows have isolated context by default**:

```python
# Parent shared store (lines 260-281 in workflow_executor.py)
shared = {"issue_number": "123", "repo": "pflow"}

# Parameter mapping (resolved in PARENT context)
param_mapping = {"issue": "${issue_number}"}
# Resolves to: {"issue": "123"}

# Child receives STATIC values (no templates)
child_shared = {"issue": "123"}  # Only mapped params
```

**Key Point**: Templates in `param_mapping` are resolved in **parent context**, then passed to child as **static values**.

### Error Propagation

**Child workflow errors propagate to parent**:

```python
# Child fails
→ WorkflowExecutor.exec() catches error
→ Stores in exec_res["error"]
→ WorkflowExecutor.post() writes to parent shared["error"]
→ Returns "error" action to parent
→ Parent workflow sees failure
→ Triggers repair if enabled
```

### Edge Cases from MCP Nodes

**CRITICAL FINDING**: MCP nodes **legitimately return `${...}` as data**!

**Example**:
```python
# MCP Slack API returns:
{"message": "User ${USER_ID} logged in"}

# This gets stored in shared store:
shared["mcp-slack"]["message"] = "User ${USER_ID} logged in"

# Should we validate this? NO!
# The ${USER_ID} is API response data, not a pflow template
```

**Implication**: **Do NOT validate templates in shared store outputs**

### False Positives to Avoid

**Three categories of legitimate `${...}` in output**:

1. **MCP API Responses** (HIGHEST RISK)
   - Slack messages, GitHub templates, API documentation
   - JSON strings containing `${...}` as literal data

2. **Documentation/Help Text**
   - Node interface documentation
   - Error messages showing example syntax

3. **Generated Code/Config**
   - Shell scripts: `echo "Value: ${VAR}"`
   - Kubernetes configs: `"namespace": "${NAMESPACE}"`

### Escape Mechanism (NOT IMPLEMENTED)

**Current**: Pattern `$${var}` is left unchanged, **not** converted to `${var}`

**Evidence**: `test_template_resolver.py` lines 191-192
```python
assert TemplateResolver.resolve_string("$${var}", context) == "$${var}"
```

**Recommendation**: Implement escape syntax in future if needed

### Relevance to Task 85

**Critical Design Decision**:

**Should we validate templates in node OUTPUT?**

**RECOMMENDATION: NO**

**Reasoning**:
- MCP nodes legitimately return `${...}` as external data
- No way to distinguish pflow templates from API response data
- Would create false positives breaking valid workflows

**Instead**: Only validate templates in **workflow IR parameters**, not in shared store outputs.

---

## 9. Implementation Strategy

### Phase 1: Core Detection (High Priority)

**Location**: `src/pflow/runtime/instrumented_wrapper.py`

**What to Add**:
1. `_detect_unresolved_templates(shared)` method
   - Scan `shared[node_id]` for `${...}` patterns
   - Recursively check dict/list/str
   - Return `{"path": ["var1", "var2"]}` or `None`

2. `_handle_unresolved_templates(...)` method
   - Build detailed error message with context
   - Show available keys from shared store
   - Mark as repairable (not `__non_repairable_error__`)
   - Record metrics/trace
   - Return "error" to trigger repair

**Integration Point**: After line 651 (after node execution)

### Phase 2: Status Enhancement (High Priority)

**Files**:
- `src/pflow/core/workflow_status.py` (new)
- `src/pflow/execution/executor_service.py` (modify)
- `src/pflow/runtime/workflow_trace.py` (modify)

**What to Add**:
1. `WorkflowStatus` enum (SUCCESS/DEGRADED/FAILED)
2. Update `ExecutionResult` with `status` field
3. Enhance `_is_execution_successful()` to return tuple
4. Update trace format to include tri-state status

### Phase 3: Configuration (Medium Priority)

**Files**:
- `src/pflow/core/ir_schema.py` (add field)
- `src/pflow/core/settings.py` (add RuntimeSettings)
- `src/pflow/runtime/compiler.py` (propagate config)
- `src/pflow/runtime/node_wrapper.py` (use config)

**What to Add**:
1. `template_resolution_mode` in IR schema (enum: strict/permissive)
2. `RuntimeSettings` in settings with global default
3. Compiler reads mode and passes to wrapper
4. Wrapper respects mode in error handling

### Phase 4: Error Messages (Medium Priority)

**Files**:
- `src/pflow/execution/formatters/success_formatter.py` (fix Nonems)
- `src/pflow/execution/display_manager.py` (tri-state display)

**What to Fix**:
1. "Nonems" bug (2 lines changed)
2. Display DEGRADED status with ⚠️
3. Show detailed error context for template failures

### Phase 5: Testing (High Priority - Parallel with Implementation)

**Test Files**:
- `tests/test_runtime/test_instrumented_wrapper.py` (detection/handler)
- `tests/test_execution/test_workflow_status.py` (tri-state)
- `tests/test_integration/test_template_resolution_hardening.py` (E2E)
- `tests/test_integration/test_slack_qa_responder.py` (real scenario from Issue #95)

**What to Test**:
1. Detection: string, nested dict, list, none
2. Handler: marks as repairable, returns "error"
3. Strict mode: fails immediately
4. Permissive mode: continues with warning
5. Status: SUCCESS/DEGRADED/FAILED
6. Exact Issue #95 scenario

---

## 10. Critical Design Decisions

### Decision 1: Where to Validate

**RECOMMENDATION**: Only validate workflow IR parameters, **NOT** shared store outputs

**Reasoning**:
- MCP nodes legitimately return `${...}` as data
- Cannot distinguish pflow templates from API response data
- Would create false positives

**Implementation**: Validate in `TemplateAwareNodeWrapper` (parameters), not `InstrumentedNodeWrapper` (outputs)

**WAIT**: The handoff says to validate in `InstrumentedNodeWrapper`...

**REVISED RECOMMENDATION**: Validate in `InstrumentedNodeWrapper` BUT:
- Only check if templates were SUPPOSED to be resolved (track in wrapper)
- Don't validate MCP node outputs (allowlist by node type)
- Focus on parameters that were declared as templates in IR

### Decision 2: Default Mode

**RECOMMENDATION**: `strict` mode by default

**Reasoning**:
- Better to fail loudly than corrupt data silently
- MVP has zero users, can change behavior
- Safer for production workflows

**User can opt-in to permissive**: `template_resolution_mode: "permissive"`

### Decision 3: Escape Syntax

**RECOMMENDATION**: Implement `\${var}` escape syntax

**Reasoning**:
- Common pattern (backslash escaping)
- Allows users to output literal `${...}` when needed
- Prevents false positives for documentation

**Implementation**: Modify regex to skip escaped templates

### Decision 4: Permissive Mode Behavior

**RECOMMENDATION**: Leave templates unresolved (Option A from handoff)

**Reasoning**:
- Node sees exactly what wasn't resolved (debugging)
- Can decide how to handle (error, default, etc.)
- Preserves information vs replacing with empty string

**Alternative**: Could replace with empty string, but loses debugging info

### Decision 5: Strict vs Permissive Semantics

**Strict Mode**:
- ANY unresolved template → fail workflow immediately
- No literal `${...}` reaches output
- Clear error with context

**Permissive Mode**:
- Unresolved template → leave as `${...}` in output
- Log warning with context
- Mark workflow as DEGRADED (not SUCCESS)
- Continue execution

---

## 11. Testing Strategy

### Unit Tests

**File**: `tests/test_runtime/test_template_resolution_hardening.py`

**Coverage**:
- Detection: `_detect_unresolved_templates()`
  - String with `${...}` → detected
  - Nested dict → detected
  - List → detected
  - None/empty → not detected
  - Escaped `\${...}` → not detected

- Handler: `_handle_unresolved_templates()`
  - Marks as repairable (not `__non_repairable_error__`)
  - Records metrics/trace
  - Returns "error" action
  - Builds helpful error message

- Status: Tri-state
  - All perfect → SUCCESS
  - Some warnings → DEGRADED
  - Any error → FAILED

### Integration Tests

**File**: `tests/test_integration/test_template_resolution_hardening.py`

**Scenarios**:
1. **Strict mode**: Node produces empty output → workflow fails before Slack
2. **Permissive mode**: Node produces empty output → workflow continues with warning
3. **Tri-state status**: Warnings mark as DEGRADED
4. **Repair flow**: Template error triggers repair, repair fixes it

### Real-World Scenario

**File**: `tests/test_integration/test_slack_qa_responder.py`

**Exact Issue #95 Reproduction**:
```python
def test_issue_95_unresolved_templates_in_slack():
    """
    Reproduce GitHub Issue #95:
    - LLM produces response
    - Shell receives input but produces empty output
    - Slack tries to use ${shell.stdout}
    - Current: Literal "${shell.stdout}" sent to Slack
    - Expected: Workflow fails before Slack message
    """
```

### Performance Tests

**File**: `tests/test_runtime/test_template_performance.py`

**Benchmarks**:
- 50+ node workflows
- Deep nested structures (10+ levels)
- Large outputs (1MB+ JSON)
- Target: <100ms overhead per node

---

## 12. Backward Compatibility

### No Breaking Changes Needed

**MVP has zero users** - can change behavior freely

**But maintain**:
- `success` boolean field (keep for external tools)
- Add `status` field alongside (new tri-state)
- Trace format version bump to 1.2.0

### Migration Path

**For future users**:
- Global default: `strict` mode
- Per-workflow override: `template_resolution_mode: "permissive"`
- Environment override: `PFLOW_TEMPLATE_RESOLUTION_MODE=permissive`

---

## 13. Success Metrics

### Before (Current Behavior)

```
⚠️ save-message (Nonems)
✓ Workflow successful
Slack receives: "${save-message.stdout}"
```

### After (Strict Mode - Default)

```
❌ Workflow failed

Error in node 'send-slack-response':
  Template ${save-message.stdout} could not be resolved

Context:
  • Node 'save-message' produced no output
  • Exit code: 0, stdout: (empty), stderr: (none)
  • This breaks parameter 'text' which depends on this variable

Available fields from 'save-message':
  (none - node produced no output)

Trace: ~/.pflow/debug/workflow-trace-20251020-143022.json
```

### After (Permissive Mode)

```
⚠️ Workflow completed with degradation

Issues:
  • save-message: No output produced
    └─ Template ${save-message.stdout} → (unresolved)

Results:
  • send-slack-response: Sent message "${save-message.stdout}"
  • Overall status: degraded

Review required: Check if this is expected behavior.
```

---

## 14. Files to Modify

### Core Implementation (Must Change)

1. ✅ **`src/pflow/runtime/instrumented_wrapper.py`**
   - Add `_detect_unresolved_templates()` method
   - Add `_handle_unresolved_templates()` method
   - Integration point after line 651

2. ✅ **`src/pflow/core/workflow_status.py`** (new file)
   - Create `WorkflowStatus` enum

3. ✅ **`src/pflow/execution/executor_service.py`**
   - Update `ExecutionResult` with `status` field
   - Enhance `_is_execution_successful()` to return tuple

4. ✅ **`src/pflow/runtime/workflow_trace.py`**
   - Update trace format for tri-state status

### Configuration (Should Change)

5. ✅ **`src/pflow/core/ir_schema.py`**
   - Add `template_resolution_mode` field

6. ✅ **`src/pflow/core/settings.py`**
   - Add `RuntimeSettings` class
   - Add `runtime` field to `PflowSettings`

7. ✅ **`src/pflow/runtime/compiler.py`**
   - Read mode and pass to wrapper

8. ✅ **`src/pflow/runtime/node_wrapper.py`**
   - Accept `template_resolution_mode` parameter
   - Use mode in error handling

### Error Messages (Nice to Have)

9. ✅ **`src/pflow/execution/formatters/success_formatter.py`**
   - Fix "Nonems" bug (2 lines)

10. ✅ **`src/pflow/execution/execution_state.py`**
    - Fix "Nonems" bug (1 line)

11. ✅ **`src/pflow/execution/display_manager.py`**
    - Display tri-state status

### Tests (Must Add)

12. ✅ **`tests/test_runtime/test_template_resolution_hardening.py`** (new)
13. ✅ **`tests/test_execution/test_workflow_status.py`** (new)
14. ✅ **`tests/test_integration/test_slack_qa_responder.py`** (enhance)

---

## 15. Open Questions for User

### Question 1: Validate Outputs? (CRITICAL)

**The handoff says**: Validate in `InstrumentedNodeWrapper` after node execution

**The research shows**: MCP nodes legitimately return `${...}` as API data

**Options**:
- **A**: Validate all outputs (may have false positives from MCP)
- **B**: Only validate if parameter was declared as template in IR
- **C**: Allowlist by node type (skip MCP nodes)
- **D**: Don't validate outputs at all, only parameters

**Recommendation**: Option B or C

**User input needed**: Which approach?

### Question 2: Escape Syntax?

**Should we implement `\${var}` → `${var}` escape syntax?**

**Pros**: Allows literal `${...}` in output when needed
**Cons**: Adds complexity, may not be needed in MVP

**User input needed**: Implement now or defer?

### Question 3: Permissive Mode Default?

**Current recommendation**: `strict` as default

**Alternative**: `permissive` as default (less breaking)

**User input needed**: Confirm `strict` is right default?

### Question 4: "Nonems" Fix Scope

**Should we fix "Nonems" as part of Task 85?**

**Pros**: It's related (node failure error messages)
**Cons**: Not strictly part of template resolution

**User input needed**: Fix now or separate task?

---

## 16. Next Steps

### Immediate (Research Phase Complete)

1. ✅ Review research findings with user
2. ⏳ Get user decisions on open questions
3. ⏳ Create detailed implementation plan
4. ⏳ Get user approval before coding

### Implementation Phase

1. ⏳ Implement detection and handler in `InstrumentedNodeWrapper`
2. ⏳ Add tri-state status system
3. ⏳ Add configuration support
4. ⏳ Write comprehensive tests
5. ⏳ Fix "Nonems" bug
6. ⏳ Update error messages
7. ⏳ Update documentation

---

## 17. Risk Assessment

### High Risk

1. **False positives from MCP nodes**
   - Mitigation: Careful validation scope (parameters only?)
   - Test thoroughly with MCP workflows

2. **Breaking repair system integration**
   - Mitigation: Preserve `ValueError` pattern, test repair flow
   - Add `available_fields` to error context

### Medium Risk

3. **Performance degradation**
   - Mitigation: Benchmark large workflows
   - Use fast string checks before regex

4. **Nested workflow interactions**
   - Mitigation: Test param_mapping resolution
   - Respect storage isolation

### Low Risk

5. **Configuration propagation**
   - Mitigation: Follow existing patterns
   - Test all override levels

6. **Backward compatibility**
   - Mitigation: Keep `success` boolean, add `status` field
   - MVP has zero users anyway

---

## Conclusion

Research phase is **COMPLETE**. We have:

✅ Solved the "Nonems" mystery
✅ Identified the root bug in template error checking
✅ Mapped complete template resolution flow
✅ Found exact integration points
✅ Understood repair system interactions
✅ Identified edge cases and false positives
✅ Designed tri-state status system
✅ Planned configuration approach

**Ready to proceed with implementation** after user approval on open questions.

---

## Appendix A: Quick Reference Files

### Critical Code Locations

| File | Lines | Purpose |
|------|-------|---------|
| `instrumented_wrapper.py` | 651 | Where to add detection |
| `node_wrapper.py` | 203-216 | The bug location |
| `executor_service.py` | 184-193 | Success determination |
| `workflow_trace.py` | 475-476 | Trace status |
| `success_formatter.py` | 263, 279 | "Nonems" bug |
| `repair_service.py` | 551-560 | Template error guidance |
| `workflow_executor.py` | 260-281 | Nested workflow templates |

### Recommended Reading Order

1. Start: This document (research-findings.md)
2. Code: `src/pflow/runtime/instrumented_wrapper.py`
3. Code: `src/pflow/runtime/node_wrapper.py`
4. Pattern: `src/pflow/runtime/type_checker.py` (Fix 3)
5. Context: `.taskmaster/tasks/task_85/task-85.md`
6. Context: `.taskmaster/tasks/task_85/starting-context/task-85-handover.md`

### External References

- **GitHub Issue #95**: Original bug report from AI agent
- **Task 56**: Runtime Validation infrastructure (foundation)
- **Task 71**: Enhanced error context for repair (pattern to follow)
- **Task 84**: Schema-aware type checking (Fix 3, complementary feature)
