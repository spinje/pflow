# Task 85 Implementation Plan

**Created**: 2025-10-20
**Status**: Ready for Implementation
**Estimated Effort**: 2-3 days

---

## Executive Summary

This plan details the implementation of Runtime Template Resolution Hardening based on comprehensive research. I've made reasoned decisions on all open questions and structured the work into 6 phases with clear success criteria.

---

## Part 1: Design Decisions (With Reasoning)

### Decision 1: What to Validate ✅

**Question**: Validate all outputs or only parameters?

**DECISION**: **Validate parameters during resolution, not arbitrary outputs**

**Reasoning**:
1. The Issue #95 problem is: **Parameters with unresolved templates being passed to nodes**
2. The bug is in `node_wrapper.py` where simple templates skip error checking
3. MCP nodes legitimately return `${...}` as API response data (false positives if we validate)
4. Shared store contains opaque data from external sources

**Implementation Strategy**:
- **Primary Fix**: Fix the bug in `node_wrapper.py` lines 203-216 (remove `if not is_simple_template` check)
- **Secondary Enhancement**: Add detection in `InstrumentedNodeWrapper` for when nodes produce empty/null output
- **Scope**: Only validate templates that were DECLARED in workflow IR parameters

**What we DON'T validate**:
- MCP node response data (may contain ${...} legitimately)
- Arbitrary strings in shared store
- Documentation/help text

### Decision 2: Escape Syntax ✅

**Question**: Implement `\${var}` escape mechanism now?

**DECISION**: **Defer to post-MVP (v0.2+)**

**Reasoning**:
1. No user requests for this feature yet
2. Adds complexity to MVP scope
3. Can be added later without breaking changes
4. Current workaround: Use different syntax or double-encode

**Future Implementation Notes** (for later):
```python
# Modify TEMPLATE_PATTERN to skip escaped templates
TEMPLATE_PATTERN = re.compile(
    r"(?<!\\)(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"
)

# Add unescape function
def unescape_templates(text: str) -> str:
    return text.replace(r"\${", "${")
```

### Decision 3: Default Mode ✅

**Question**: Should default be `strict` or `permissive`?

**DECISION**: **`strict` as default**

**Reasoning**:
1. **Philosophy shift**: Fail-hard for data integrity (core goal of Task 85)
2. **Better UX**: Explicit failures > silent data corruption
3. **Zero users**: MVP can change behavior without migration pain
4. **Clear opt-in**: Users who need permissive can explicitly configure it
5. **Matches industry**: Most validation tools default to strict

**Opt-out path**: Users can configure `template_resolution_mode: "permissive"` if needed

### Decision 4: "Nonems" Fix Scope ✅

**Question**: Fix "Nonems" as part of Task 85?

**DECISION**: **Yes, include in this task**

**Reasoning**:
1. **Same root cause**: Node failures not being surfaced properly
2. **Simple fix**: 2 lines changed, low risk
3. **Related objective**: Improving error messages (part of Task 85 success criteria)
4. **High value**: Makes debugging much clearer
5. **Natural fit**: We're already touching error formatting

**Scope**: Fix in Phase 2 alongside status enhancement

---

## Part 2: Architecture Overview

### Two-Layer Validation Strategy

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Parameter Resolution (node_wrapper.py)            │
│ - Fix bug: Check BOTH simple and complex templates         │
│ - Detect unresolved templates in parameters                │
│ - Raise ValueError if template failed to resolve           │
│ - Triggers: Repair system (if --auto-repair)               │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Output Validation (instrumented_wrapper.py)       │
│ - Detect when node produces empty/null output              │
│ - Check if downstream nodes will break                     │
│ - Mark as repairable error                                 │
│ - Provide context: what was expected vs what was produced  │
└─────────────────────────────────────────────────────────────┘
```

### Tri-State Status Model

```
Current (Binary):                New (Tri-State):
┌──────────────┐                ┌──────────────┐
│   Success    │                │   SUCCESS    │  All perfect
│ (True/False) │                ├──────────────┤
└──────────────┘                │   DEGRADED   │  Warnings exist
                                ├──────────────┤
                                │    FAILED    │  Error occurred
                                └──────────────┘
```

### Configuration Hierarchy

```
1. Workflow IR (highest priority)
   "template_resolution_mode": "permissive"
         ↓ (overrides)
2. Global Settings (~/.pflow/settings.json)
   runtime.template_resolution_mode: "strict"
         ↓ (overrides)
3. Environment Variable
   PFLOW_TEMPLATE_RESOLUTION_MODE=permissive
         ↓ (fallback)
4. Hard-coded Default
   "strict"
```

---

## Part 3: Implementation Phases

### Phase 1: Fix the Core Bug (Critical) 🔴

**Objective**: Fix simple templates skipping error validation

**File**: `src/pflow/runtime/node_wrapper.py`

**Change Location**: Lines 203-216

**Current Code** (BUGGY):
```python
resolved_value, is_simple_template = self._resolve_template_parameter(
    key, template, context
)
resolved_params[key] = resolved_value

# ⚠️ BUG: Simple templates skip this check!
if not is_simple_template:
    if resolved_value != template:
        logger.debug(f"Resolved param '{key}': '{template}' -> '{resolved_value}'")
    elif "${" in str(template):
        error_msg = f"Template in param '{key}' could not be fully resolved: '{template}'"
        logger.error(error_msg, extra={"node_id": self.node_id, "param": key})
        raise ValueError(error_msg)
```

**Fixed Code**:
```python
resolved_value, is_simple_template = self._resolve_template_parameter(
    key, template, context
)
resolved_params[key] = resolved_value

# Check if template was resolved (for BOTH simple and complex templates)
if resolved_value != template:
    # Successfully resolved
    logger.debug(
        f"Resolved param '{key}': '{template}' -> '{resolved_value}'",
        extra={"node_id": self.node_id, "param": key}
    )
elif "${" in str(resolved_value):
    # Template failed to resolve - still contains ${...}
    error_msg = (
        f"Template in param '{key}' could not be fully resolved: '{template}'\n"
        f"Context: {self.node_id} expected variable but it was not available"
    )
    logger.error(error_msg, extra={"node_id": self.node_id, "param": key})
    raise ValueError(error_msg)  # Triggers repair if enabled
```

**Why This Fix Works**:
1. Removes the `if not is_simple_template` condition
2. Both simple (`${var}`) and complex (`text ${var}`) templates are now checked
3. Detects unresolved templates by checking if `${` is still in resolved value
4. Raises `ValueError` which triggers repair system (compatibility preserved)

**Testing**:
```python
# Test case 1: Simple template, variable exists
context = {"data": "value"}
template = "${data}"
# Should resolve to "value", no error

# Test case 2: Simple template, variable missing (BUG FIX)
context = {}
template = "${missing}"
# Should raise ValueError (previously didn't!)

# Test case 3: Complex template, variable missing
context = {}
template = "text ${missing}"
# Should raise ValueError (already worked)
```

**Success Criteria**:
- ✅ Simple templates with missing variables raise `ValueError`
- ✅ Complex templates still work as before
- ✅ Repair system receives template errors
- ✅ Existing tests still pass

---

### Phase 2: Add Tri-State Status & Fix Nonems (High Priority) 🟡

#### Part A: Tri-State Status System

**Objective**: Distinguish SUCCESS / DEGRADED / FAILED workflow states

**Files to Create/Modify**:

1. **Create**: `src/pflow/core/workflow_status.py`
```python
"""Workflow execution status types."""
from enum import Enum


class WorkflowStatus(str, Enum):
    """Tri-state workflow execution status.

    - SUCCESS: All nodes completed without warnings
    - DEGRADED: Completed but some nodes had warnings
    - FAILED: Workflow failed to complete
    """
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
```

2. **Modify**: `src/pflow/execution/executor_service.py`

**Location**: Line 18 (ExecutionResult dataclass)
```python
@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool  # Keep for backward compatibility
    status: WorkflowStatus  # NEW: Tri-state status
    shared_after: dict[str, Any]
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = field(default_factory=list)  # NEW
    metrics_summary: Optional[dict[str, Any]] = None
    trace_path: Optional[str] = None
    json_output: Optional[dict[str, Any]] = None
    repaired: bool = False
    original_ir: Optional[dict[str, Any]] = None
```

**Location**: Lines 184-193 (enhance success determination)
```python
def _determine_workflow_status(
    self,
    action_result: Optional[str],
    shared_store: dict[str, Any]
) -> tuple[bool, WorkflowStatus]:
    """Determine both boolean success and tri-state status.

    Returns:
        Tuple of (success_boolean, status_enum)
    """
    # Check for hard failure
    if action_result and isinstance(action_result, str) and action_result.startswith("error"):
        return False, WorkflowStatus.FAILED

    # Check for warnings/degradation
    warnings = shared_store.get("__warnings__", {})
    template_errors = shared_store.get("__template_errors__", {})

    if warnings or template_errors:
        # Workflow completed but with issues
        return True, WorkflowStatus.DEGRADED

    # Full success
    return True, WorkflowStatus.SUCCESS
```

**Location**: Line 111 (use new function)
```python
# OLD:
success = self._is_execution_successful(action_result)

# NEW:
success, status = self._determine_workflow_status(action_result, shared_after)
```

**Location**: Line 145 (update ExecutionResult creation)
```python
return ExecutionResult(
    success=success,
    status=status,  # NEW
    shared_after=shared_after,
    errors=errors,
    warnings=self._extract_warnings(shared_after),  # NEW
    metrics_summary=metrics_summary,
    trace_path=trace_path,
    json_output=json_output,
)
```

**Add new method** (after line 193):
```python
def _extract_warnings(self, shared_store: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract warnings from shared store."""
    warnings = []

    # API warnings
    api_warnings = shared_store.get("__warnings__", {})
    for node_id, message in api_warnings.items():
        warnings.append({
            "node_id": node_id,
            "type": "api_warning",
            "message": message
        })

    # Template errors (in permissive mode)
    template_errors = shared_store.get("__template_errors__", {})
    for node_id, error_data in template_errors.items():
        warnings.append({
            "node_id": node_id,
            "type": "template_resolution",
            "message": error_data.get("message", "Template resolution failed"),
            "unresolved_templates": error_data.get("unresolved", [])
        })

    return warnings
```

3. **Modify**: `src/pflow/runtime/workflow_trace.py`

**Location**: Line 37 (update format version)
```python
TRACE_FORMAT_VERSION = "1.2.0"  # Changed from 1.1.0
```

**Location**: Lines 475-476 (tri-state status)
```python
# OLD:
failed_nodes = [e for e in self.events if not e.get("success", True)]
final_status = "failed" if failed_nodes else "success"

# NEW:
def _determine_trace_status(self) -> str:
    """Determine tri-state status from events."""
    failed = [e for e in self.events if not e.get("success", True)]
    if failed:
        return "failed"

    warned = [e for e in self.events if e.get("warning")]
    if warned:
        return "degraded"

    return "success"

final_status = self._determine_trace_status()
```

#### Part B: Fix "Nonems" Bug

**File 1**: `src/pflow/execution/execution_state.py`

**Location**: Line 85
```python
# OLD:
"duration_ms": node_timings.get(node_id),

# NEW:
"duration_ms": node_timings.get(node_id, 0),  # Default to 0 if not found
```

**File 2**: `src/pflow/execution/formatters/success_formatter.py`

**Location**: Line 263
```python
# OLD:
duration = step.get("duration_ms", 0)

# NEW:
duration = step.get("duration_ms") or 0  # Handle explicit None
```

**Success Criteria**:
- ✅ Workflows with warnings show `DEGRADED` status
- ✅ Workflows with errors show `FAILED` status
- ✅ Perfect workflows show `SUCCESS` status
- ✅ "Nonems" never appears in output
- ✅ Trace format version is 1.2.0
- ✅ Backward compatibility: `success` boolean still works

---

### Phase 3: Add Configuration Support (Medium Priority) 🟢

**Objective**: Enable strict/permissive mode configuration

#### Step 1: IR Schema

**File**: `src/pflow/core/ir_schema.py`

**Location**: After line 230 (after `enable_namespacing`)
```python
"template_resolution_mode": {
    "type": "string",
    "enum": ["strict", "permissive"],
    "description": (
        "Template resolution error behavior. "
        "strict: fail on unresolved templates (default). "
        "permissive: warn and continue with unresolved templates."
    ),
    "default": "strict",
},
```

#### Step 2: Settings

**File**: `src/pflow/core/settings.py`

**Location**: After line 31 (create new class)
```python
class RuntimeSettings(BaseModel):
    """Runtime execution configuration.

    These settings control workflow execution behavior.
    """
    template_resolution_mode: str = Field(
        default="strict",
        description="Default template resolution mode: strict or permissive"
    )

    @field_validator("template_resolution_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validate mode is valid."""
        if v not in ["strict", "permissive"]:
            raise ValueError(f"Invalid mode: {v}. Must be 'strict' or 'permissive'")
        return v
```

**Location**: Line 35 (add to PflowSettings)
```python
class PflowSettings(BaseModel):
    """pflow configuration settings."""
    version: str = "1.0.0"
    registry: RegistrySettings
    env: dict[str, str]
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)  # NEW
```

**Location**: After line 100 (environment override)
```python
def _apply_env_overrides(self, settings: PflowSettings) -> None:
    """Apply environment variable overrides."""
    # Existing overrides...

    # Template resolution mode override
    env_mode = os.getenv("PFLOW_TEMPLATE_RESOLUTION_MODE")
    if env_mode is not None:
        if env_mode.lower() in ("strict", "permissive"):
            settings.runtime.template_resolution_mode = env_mode.lower()
        else:
            logger.warning(
                f"Invalid PFLOW_TEMPLATE_RESOLUTION_MODE: {env_mode}. "
                f"Using default: {settings.runtime.template_resolution_mode}"
            )
```

#### Step 3: Compiler Integration

**File**: `src/pflow/runtime/compiler.py`

**Location**: In `_validate_workflow()` around line 873
```python
# Get template resolution mode (workflow override or global default)
template_resolution_mode = ir_dict.get("template_resolution_mode")
if template_resolution_mode is None:
    from pflow.core.settings import SettingsManager
    settings = SettingsManager().load()
    template_resolution_mode = settings.runtime.template_resolution_mode

# Validate mode
if template_resolution_mode not in ["strict", "permissive"]:
    raise ValidationError(
        message=f"Invalid template_resolution_mode: {template_resolution_mode}",
        path="template_resolution_mode",
        suggestion="Use 'strict' or 'permissive'"
    )

# Store in initial_params for access during execution
initial_params["__template_resolution_mode__"] = template_resolution_mode
```

**Location**: In `_create_single_node()` around line 686
```python
# Pass mode to template wrapper
node_instance = _apply_template_wrapping(
    node_instance,
    node_id,
    node_data.get("params", {}),
    initial_params,
    template_resolution_mode=initial_params.get("__template_resolution_mode__", "strict")
)
```

**Location**: In `_apply_template_wrapping()` around line 305
```python
def _apply_template_wrapping(
    node_instance: Union[BaseNode, TemplateAwareNodeWrapper, NamespacedNodeWrapper],
    node_id: str,
    params: dict[str, Any],
    initial_params: dict[str, Any],
    template_resolution_mode: str = "strict",  # NEW parameter
) -> Union[BaseNode, TemplateAwareNodeWrapper, NamespacedNodeWrapper]:
    """Apply template-aware wrapping if needed."""
    has_templates = any(TemplateResolver.has_templates(value) for value in params.values())

    if has_templates:
        return TemplateAwareNodeWrapper(
            node_instance,
            node_id,
            initial_params,
            template_resolution_mode=template_resolution_mode  # NEW
        )

    return node_instance
```

#### Step 4: Wrapper Integration

**File**: `src/pflow/runtime/node_wrapper.py`

**Location**: Line 50 (`__init__` method)
```python
def __init__(
    self,
    node: Any,
    node_id: str,
    initial_params: dict[str, Any],
    template_resolution_mode: str = "strict"  # NEW parameter
):
    """Initialize template-aware node wrapper.

    Args:
        node: The node to wrap
        node_id: Unique identifier for this node
        initial_params: Initial parameters from planner
        template_resolution_mode: 'strict' (fail on unresolved) or 'permissive' (warn)
    """
    self.inner_node = node
    self.node_id = node_id
    self.initial_params = initial_params
    self.template_resolution_mode = template_resolution_mode  # NEW
    self.template_params: dict[str, Any] = {}
    self.static_params: dict[str, Any] = {}
```

**Location**: Lines 203-216 (use mode in error handling)
```python
# Check if template was resolved
if resolved_value != template:
    # Successfully resolved
    logger.debug(...)
elif "${" in str(resolved_value):
    # Template failed to resolve
    error_msg = f"Template in param '{key}' could not be fully resolved: '{template}'"

    if self.template_resolution_mode == "strict":
        # Strict mode: Fail immediately
        logger.error(error_msg, extra={"node_id": self.node_id, "param": key})
        raise ValueError(error_msg)
    else:
        # Permissive mode: Warn and continue
        logger.warning(
            f"{error_msg} (permissive mode: continuing with unresolved template)",
            extra={"node_id": self.node_id, "param": key}
        )
        # Leave template unresolved in resolved_params
        # Downstream node will receive "${...}" literally
```

**Success Criteria**:
- ✅ IR schema validates mode enum
- ✅ Settings support global default
- ✅ Environment override works
- ✅ Workflow-level override works
- ✅ Compiler propagates mode to wrapper
- ✅ Wrapper respects mode in error handling

---

### Phase 4: Enhanced Error Messages (Medium Priority) 🟢

**Objective**: Provide actionable, contextual error messages

**File**: `src/pflow/runtime/node_wrapper.py`

**Location**: Add new helper method (around line 230)
```python
def _build_enhanced_template_error(
    self,
    param_key: str,
    template: str,
    context: dict[str, Any],
) -> str:
    """Build detailed error message for unresolved template.

    Args:
        param_key: Parameter name
        template: Original template string
        context: Resolution context (shared store + initial params)

    Returns:
        Formatted error message with suggestions
    """
    # Extract variable name from template
    variables = TemplateResolver.extract_variables(str(template))

    # Build context section
    available_keys = list(context.keys())
    available_keys.sort()

    # Limit to 20 keys for readability
    if len(available_keys) > 20:
        available_display = available_keys[:20]
        available_display.append(f"... and {len(available_keys) - 20} more")
    else:
        available_display = available_keys

    # Format error message
    error_parts = [
        f"Template in parameter '{param_key}' could not be resolved: '{template}'",
        "",
        f"Node: {self.node_id}",
        f"Unresolved variables: {', '.join(variables)}",
        "",
        "Available context keys:",
    ]

    for key in available_display:
        value = context.get(key)
        value_type = type(value).__name__
        error_parts.append(f"  • {key} ({value_type})")

    # Add suggestions if close matches found
    suggestions = []
    for var in variables:
        # Simple fuzzy matching (Levenshtein distance would be better)
        for key in available_keys[:20]:
            if var.lower() in key.lower() or key.lower() in var.lower():
                suggestions.append(f"Did you mean '${{{key}}}'? (instead of '${{{var}}}')")

    if suggestions:
        error_parts.append("")
        error_parts.append("💡 Suggestions:")
        error_parts.extend(f"  • {s}" for s in suggestions[:3])

    return "\n".join(error_parts)
```

**Location**: Lines 203-216 (use enhanced error)
```python
elif "${" in str(resolved_value):
    # Template failed to resolve - build enhanced error
    error_msg = self._build_enhanced_template_error(key, template, context)

    if self.template_resolution_mode == "strict":
        logger.error(error_msg, extra={"node_id": self.node_id, "param": key})
        raise ValueError(error_msg)
    else:
        logger.warning(
            f"{error_msg}\n(permissive mode: continuing)",
            extra={"node_id": self.node_id, "param": key}
        )
```

**Success Criteria**:
- ✅ Error messages show available context keys
- ✅ Suggestions provided for close matches
- ✅ Messages are actionable and helpful
- ✅ Display limited to 20 items (not overwhelming)

---

### Phase 5: Display Updates (Low Priority) 🔵

**Objective**: Show tri-state status in CLI output

**File**: `src/pflow/execution/display_manager.py`

**Location**: Lines 51-62 (update display method)
```python
def show_execution_result(
    self,
    success: bool,
    status: WorkflowStatus,  # NEW parameter
    data: Optional[str] = None,
) -> None:
    """Display workflow execution result with tri-state status."""
    if status == WorkflowStatus.SUCCESS:
        self.output.show_success("Workflow executed successfully")
    elif status == WorkflowStatus.DEGRADED:
        self.output.show_warning(
            "Workflow completed with warnings - review trace for details"
        )
    elif status == WorkflowStatus.FAILED:
        self.output.show_error("Workflow execution failed")
    else:
        # Fallback to boolean
        if success:
            self.output.show_success("Workflow executed successfully")
        else:
            self.output.show_error("Workflow execution failed")

    if data:
        self.output.write(data)
```

**File**: `src/pflow/execution/formatters/success_formatter.py`

**Location**: Lines 36-86 (update JSON output)
```python
def format_execution_success(
    workflow_name: str,
    result: Any,
    metrics_summary: Optional[dict],
    execution_steps: list[dict[str, Any]],
    status: WorkflowStatus,  # NEW parameter
    warnings: list[dict[str, Any]],  # NEW parameter
    trace_path: Optional[str] = None,
    repaired: bool = False,
) -> dict[str, Any]:
    """Format successful execution result as JSON."""

    # ... existing code ...

    formatted = {
        "success": True,  # Keep for backward compatibility
        "status": status.value,  # NEW: Tri-state
        "result": result,
        "workflow": {
            "name": workflow_name,
        },
        "duration_ms": duration_ms,
        "total_cost_usd": total_cost,
        "nodes_executed": len(execution_steps),
        "metrics": metrics_summary or {},
        "execution": {
            "duration_ms": duration_ms,
            "nodes_executed": nodes_executed,
            "nodes_total": nodes_total,
            "steps": execution_steps,
        },
    }

    # Add warnings if present
    if warnings:
        formatted["warnings"] = warnings

    # ... rest of existing code ...

    return formatted
```

**Success Criteria**:
- ✅ CLI shows ⚠️ for DEGRADED status
- ✅ JSON output includes tri-state status
- ✅ Warnings section added to JSON output
- ✅ Backward compatibility maintained

---

### Phase 6: Comprehensive Testing (Critical) 🔴

**Objective**: Ensure all functionality works correctly with comprehensive test coverage

#### Test File 1: Unit Tests for Bug Fix

**File**: `tests/test_runtime/test_node_wrapper_template_validation.py` (new)

```python
"""Test template validation in TemplateAwareNodeWrapper."""
import pytest
from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper
from pflow.runtime.template_resolver import TemplateResolver


class TestSimpleTemplateValidation:
    """Test that simple templates are validated (bug fix)."""

    def test_simple_template_missing_variable_raises_error_strict(self):
        """Simple template with missing variable should raise ValueError in strict mode."""
        # This is the bug fix test - previously this didn't raise!

        class DummyNode:
            def __init__(self):
                self.params = {}
            def set_params(self, params):
                self.params = params
            def _run(self, shared):
                return "default"

        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict"
        )

        # Set parameter with unresolvable simple template
        wrapper.set_params({"prompt": "${missing_variable}"})

        # Execute should raise ValueError
        with pytest.raises(ValueError, match="could not be fully resolved"):
            wrapper._run(shared={})

    def test_simple_template_existing_variable_resolves(self):
        """Simple template with existing variable should resolve correctly."""
        class DummyNode:
            def __init__(self):
                self.params = {}
            def set_params(self, params):
                self.params = params
            def _run(self, shared):
                return "default"

        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict"
        )

        wrapper.set_params({"prompt": "${data}"})

        # Execute with context containing the variable
        result = wrapper._run(shared={"data": "resolved value"})

        # Should execute successfully
        assert node.params["prompt"] == "resolved value"

    def test_complex_template_missing_variable_raises_error(self):
        """Complex template with missing variable should raise ValueError (already worked)."""
        class DummyNode:
            def __init__(self):
                self.params = {}
            def set_params(self, params):
                self.params = params
            def _run(self, shared):
                return "default"

        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict"
        )

        wrapper.set_params({"prompt": "Hello ${missing_variable}!"})

        with pytest.raises(ValueError, match="could not be fully resolved"):
            wrapper._run(shared={})


class TestPermissiveModeTemplateValidation:
    """Test permissive mode behavior."""

    def test_permissive_mode_continues_with_warning(self):
        """Permissive mode should log warning but continue."""
        class DummyNode:
            def __init__(self):
                self.params = {}
            def set_params(self, params):
                self.params = params
            def _run(self, shared):
                return "default"

        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="permissive"  # Permissive mode
        )

        wrapper.set_params({"prompt": "${missing_variable}"})

        # Should NOT raise error, continue with unresolved template
        result = wrapper._run(shared={})

        # Node should receive literal template
        assert node.params["prompt"] == "${missing_variable}"
        assert result == "default"
```

#### Test File 2: Tri-State Status Tests

**File**: `tests/test_execution/test_workflow_status.py` (new)

```python
"""Test tri-state workflow status system."""
import pytest
from pflow.core.workflow_status import WorkflowStatus
from pflow.execution.executor_service import ExecutionResult


class TestWorkflowStatusEnum:
    """Test WorkflowStatus enum."""

    def test_status_values(self):
        """Test enum has correct values."""
        assert WorkflowStatus.SUCCESS.value == "success"
        assert WorkflowStatus.DEGRADED.value == "degraded"
        assert WorkflowStatus.FAILED.value == "failed"

    def test_status_string_conversion(self):
        """Test enum can be used as string."""
        status = WorkflowStatus.DEGRADED
        assert str(status) == "degraded"


class TestWorkflowStatusDetermination:
    """Test status determination logic."""

    def test_success_status_no_warnings(self):
        """Workflow with no errors or warnings should be SUCCESS."""
        # Test via executor_service._determine_workflow_status
        # (Implementation would use actual executor)
        pass

    def test_degraded_status_with_warnings(self):
        """Workflow with warnings should be DEGRADED."""
        pass

    def test_failed_status_with_error(self):
        """Workflow with error action should be FAILED."""
        pass
```

#### Test File 3: Integration Tests

**File**: `tests/test_integration/test_template_resolution_hardening.py` (new)

```python
"""Integration tests for template resolution hardening."""
import pytest
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry.registry import Registry


class TestStrictModeIntegration:
    """Test strict mode end-to-end."""

    def test_strict_mode_fails_on_unresolved_template(self, test_registry):
        """Workflow with unresolved template should fail in strict mode."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "echo-node",
                    "type": "shell",
                    "params": {
                        "command": "echo",
                        "args": ["${missing_variable}"]  # Will fail to resolve
                    }
                }
            ],
            "edges": []
        }

        flow = compile_ir_to_flow(workflow_ir, test_registry, initial_params={})

        # Execute should raise ValueError due to unresolved template
        with pytest.raises(ValueError, match="could not be fully resolved"):
            flow.run()


class TestPermissiveModeIntegration:
    """Test permissive mode end-to-end."""

    def test_permissive_mode_continues_with_unresolved(self, test_registry):
        """Workflow should continue with unresolved template in permissive mode."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",
            "nodes": [
                {
                    "id": "echo-node",
                    "type": "shell",
                    "params": {
                        "command": "echo",
                        "args": ["${missing_variable}"]
                    }
                }
            ],
            "edges": []
        }

        flow = compile_ir_to_flow(workflow_ir, test_registry, initial_params={})

        shared = {}
        result = flow.run(shared)

        # Should complete (not raise error)
        # Should have warnings in shared store
        assert "__template_errors__" in shared or "__warnings__" in shared
```

#### Test File 4: Real-World Scenario (Issue #95)

**File**: `tests/test_integration/test_issue_95_slack_qa_responder.py` (new)

```python
"""Reproduce and verify fix for Issue #95."""
import pytest


def test_issue_95_unresolved_template_in_slack_message(test_registry):
    """
    Reproduce GitHub Issue #95:
    - Node produces empty output
    - Downstream node tries to use ${node.output}
    - Should fail before sending to external API

    Scenario:
    1. shell node produces empty output
    2. Another node tries to use ${shell.stdout}
    3. Current: Literal "${shell.stdout}" would be sent
    4. Expected: Workflow fails with clear error
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "template_resolution_mode": "strict",  # Default mode
        "nodes": [
            {
                "id": "get-data",
                "type": "shell",
                "params": {
                    "command": "echo",  # Produces empty by default
                    "args": []
                }
            },
            {
                "id": "use-data",
                "type": "shell",
                "params": {
                    "command": "echo",
                    "args": ["${get-data.stdout}"]  # Will fail to resolve if empty
                }
            }
        ],
        "edges": [
            {"from": "get-data", "to": "use-data", "action": "default"}
        ]
    }

    flow = compile_ir_to_flow(workflow_ir, test_registry, initial_params={})

    # Should fail with clear error about unresolved template
    with pytest.raises(ValueError) as exc_info:
        flow.run()

    error_message = str(exc_info.value)
    assert "could not be fully resolved" in error_message
    assert "get-data.stdout" in error_message

    # Verify it tells us what's available
    assert "Available context keys" in error_message
```

#### Test File 5: "Nonems" Fix Verification

**File**: `tests/test_execution/formatters/test_success_formatter.py` (enhance existing)

```python
"""Test success formatter (including Nonems fix)."""


def test_format_step_with_none_duration_no_nonems():
    """Verify None duration doesn't create 'Nonems' (Issue fix)."""
    from pflow.execution.formatters.success_formatter import _format_execution_step

    step = {
        "node_id": "test-node",
        "status": "completed",
        "duration_ms": None,  # Explicit None
        "cached": False,
    }

    result = _format_execution_step(step)

    # Should NOT contain "Nonems"
    assert "Nonems" not in result

    # Should contain "0ms" instead
    assert "0ms" in result


def test_format_step_missing_duration_key():
    """Test when duration_ms key doesn't exist."""
    from pflow.execution.formatters.success_formatter import _format_execution_step

    step = {
        "node_id": "test-node",
        "status": "completed",
        # duration_ms key missing entirely
    }

    result = _format_execution_step(step)

    assert "Nonems" not in result
    assert "0ms" in result
```

**Success Criteria for Phase 6**:
- ✅ 100% test coverage for bug fix
- ✅ Integration tests pass for strict/permissive modes
- ✅ Issue #95 scenario reproduced and fixed
- ✅ "Nonems" never appears in any test
- ✅ All existing tests still pass

---

## Part 4: Implementation Order

### Day 1: Core Fixes
1. ✅ Phase 1: Fix template validation bug (1-2 hours)
2. ✅ Phase 2A: Tri-state status system (2-3 hours)
3. ✅ Phase 2B: Fix "Nonems" bug (30 minutes)
4. ✅ Phase 6: Write unit tests for above (2-3 hours)

### Day 2: Configuration & Enhancement
5. ✅ Phase 3: Configuration support (3-4 hours)
6. ✅ Phase 4: Enhanced error messages (2 hours)
7. ✅ Phase 6: Write integration tests (2-3 hours)

### Day 3: Polish & Testing
8. ✅ Phase 5: Display updates (2 hours)
9. ✅ Phase 6: Real-world tests (Issue #95) (1-2 hours)
10. ✅ Full regression testing (2 hours)
11. ✅ Documentation updates (2 hours)

**Total Estimated Time**: 18-24 hours (2-3 days)

---

## Part 5: Risk Mitigation

### Risk 1: Breaking Repair System
**Likelihood**: Medium
**Impact**: High
**Mitigation**:
- Preserve `ValueError` pattern (repair expects this)
- Test repair flow with template errors
- Verify error message format is parseable

### Risk 2: MCP Node False Positives
**Likelihood**: Low (we're only validating parameters)
**Impact**: Medium
**Mitigation**:
- Only validate workflow IR parameters, not outputs
- Test with MCP workflows
- Document scope of validation

### Risk 3: Performance Degradation
**Likelihood**: Low
**Impact**: Low
**Mitigation**:
- Use fast string checks (`"${" in value`) before regex
- Benchmark with large workflows
- Limit display to 20 items

### Risk 4: Backward Compatibility
**Likelihood**: Very Low (MVP has zero users)
**Impact**: Low
**Mitigation**:
- Keep `success` boolean field
- Add `status` field alongside
- Bump trace format version

---

## Part 6: Success Metrics

### Functional Metrics

✅ **Bug Fixed**: Simple templates with missing variables raise errors
✅ **Status System**: Tri-state SUCCESS/DEGRADED/FAILED works
✅ **Configuration**: Strict/permissive modes configurable
✅ **Error Messages**: Actionable with context
✅ **Nonems Gone**: "Nonems" never appears

### Quality Metrics

✅ **Test Coverage**: >90% for new code
✅ **Regression Tests**: All existing tests pass
✅ **Issue #95**: Exact scenario reproduced and fixed
✅ **Performance**: <100ms overhead per node
✅ **Documentation**: Updated for new features

### User Experience Metrics

**Before** (Current):
```
⚠️ save-message (Nonems)
✓ Workflow successful
Slack: "${save-message.stdout}"
```

**After** (Strict Mode):
```
❌ Workflow failed

Template ${save-message.stdout} could not be resolved

Available context:
  • save-message (dict)

💡 Suggestion:
  Check if save-message produced expected output
```

---

## Part 7: Documentation Updates

### Files to Update

1. **`architecture/features/template-system.md`**
   - Add strict/permissive mode documentation
   - Explain tri-state status
   - Show configuration examples

2. **`architecture/core-concepts/schemas.md`**
   - Document `template_resolution_mode` field
   - Add configuration examples

3. **`src/pflow/runtime/CLAUDE.md`**
   - Update wrapper documentation
   - Explain template validation changes

4. **`CHANGELOG.md`**
   - Add Task 85 entry with breaking changes
   - Document new features

---

## Part 8: Final Checklist

### Before Starting
- [x] Research complete
- [x] Design decisions made
- [x] Implementation plan approved
- [ ] User approval on approach

### Phase 1 (Bug Fix)
- [ ] Fix applied to `node_wrapper.py`
- [ ] Unit tests written
- [ ] Unit tests passing
- [ ] Code reviewed

### Phase 2 (Status & Nonems)
- [ ] Tri-state enum created
- [ ] ExecutionResult updated
- [ ] Trace format updated
- [ ] "Nonems" bug fixed
- [ ] Tests passing

### Phase 3 (Configuration)
- [ ] IR schema updated
- [ ] Settings updated
- [ ] Compiler propagation working
- [ ] Wrapper using mode
- [ ] Tests passing

### Phase 4 (Error Messages)
- [ ] Enhanced error builder added
- [ ] Error messages improved
- [ ] Suggestions working
- [ ] Tests passing

### Phase 5 (Display)
- [ ] CLI display updated
- [ ] JSON format updated
- [ ] Backward compatibility verified
- [ ] Tests passing

### Phase 6 (Testing)
- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] Issue #95 test passing
- [ ] Performance benchmarks acceptable
- [ ] Regression tests passing

### Final Polish
- [ ] Documentation updated
- [ ] CHANGELOG updated
- [ ] Code formatting checked
- [ ] Type checking passed (`mypy`)
- [ ] Linting passed (`ruff`)
- [ ] Full test suite passing (`make test`)
- [ ] Pre-commit hooks passing

---

## Conclusion

This implementation plan provides a clear, phased approach to solving the runtime template resolution issues. By fixing the core bug first, then adding status enhancements and configuration, we build a solid foundation for reliable template validation.

The plan respects existing patterns, maintains backward compatibility where needed, and provides comprehensive testing to ensure quality.

**Ready to begin implementation with user approval.**
