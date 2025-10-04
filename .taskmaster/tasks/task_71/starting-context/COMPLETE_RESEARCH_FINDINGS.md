# Task 71: Complete Research Findings

## Executive Summary

This document consolidates all research findings for Task 71: Extend CLI Commands for agentic workflow building. The key discovery is that we can directly reuse planner nodes without extraction, and that rich error context already exists but isn't displayed.

## Table of Contents

1. [Planner Node Architecture](#planner-node-architecture)
2. [Context Builder Functions](#context-builder-functions)
3. [Error Flow Analysis](#error-flow-analysis)
4. [CLI Architecture](#cli-architecture)
5. [Key Discoveries](#key-discoveries)

---

## Planner Node Architecture

### Direct Node Reuse Pattern

**Finding**: Planner nodes can run standalone without a Flow.

```python
# Simple pattern that works for ALL planner nodes:
node = WorkflowDiscoveryNode()
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
action = node.run(shared)
# Results available in shared dict
```

**Evidence**: 350+ tests in the codebase use this pattern. The `run()` method handles the full prep→exec→post lifecycle.

### WorkflowDiscoveryNode

**Location**: `src/pflow/planning/nodes.py:67-319`

**Requirements**:
- `shared["user_input"]` - The query string
- `shared["workflow_manager"]` - Optional, defaults to WorkflowManager()

**Outputs**:
- `shared["discovery_result"]` - Contains `found`, `workflow_name`, `confidence`, `reasoning`
- `shared["found_workflow"]` - Full workflow IR if match found
- Returns action: `"found_existing"` or `"not_found"`

### ComponentBrowsingNode

**Location**: `src/pflow/planning/nodes.py:322-619`

**Requirements**:
- `shared["user_input"]` - The query string
- `shared["requirements_result"]` - Optional, uses empty dict if missing

**Outputs**:
- `shared["browsed_components"]` - Contains `node_ids`, `workflow_names`
- `shared["planning_context"]` - Full markdown context with interface details
- `shared["registry_metadata"]` - Registry data
- Returns action: `"generate"` (always)

### ValidatorNode

**Location**: `src/pflow/planning/nodes.py:2126-2423`

**Requirements**:
- `shared["generated_workflow"]` - Workflow IR to validate
- `shared["workflow_inputs"]` - Optional parameters for template validation

**Outputs**:
- `shared["validation_result"]` - Contains `valid` boolean and `errors` list
- `shared["validation_errors"]` - List of error strings
- Returns action: `"valid"` or `"invalid"`

### MetadataGenerationNode

**Location**: `src/pflow/planning/nodes.py:2426-2608`

**Requirements**:
- `shared["validated_workflow"]` - Validated workflow IR

**Outputs**:
- `shared["workflow_metadata"]` - Rich metadata with capabilities, keywords, etc.
- Returns action: `"complete"` (always)

---

## Context Builder Functions

**Location**: `src/pflow/planning/context_builder.py`

### build_nodes_context()
- **Lines**: 588-637
- **Returns**: Lightweight numbered list for browsing
- **Format**: `"1. node-id - Description"`
- **Use Case**: LLM selection in ComponentBrowsingNode

### build_workflows_context()
- **Lines**: 726-796
- **Returns**: Rich workflow list with metadata
- **Format**: Includes flow visualization, capabilities, use cases
- **Use Case**: Discovery in both nodes

### build_planning_context()
- **Lines**: 892-949
- **Returns**: FULL interface documentation
- **Format**: Complete inputs, outputs, parameters with types and descriptions
- **Use Case**: Detailed node specifications

### build_discovery_context()
- **Lines**: 520-585
- **Returns**: Combined nodes + workflows
- **Format**: Lightweight browsing format
- **Use Case**: Initial discovery phase

---

## Error Flow Analysis

### Current Error Display Problem

**Location**: `src/pflow/cli/main.py:1034-1060`

**Current output** (generic):
```
cli: Workflow execution failed - Node returned error action
```

**Available but hidden**: `ExecutionResult.errors` contains rich error data:
```python
{
    "source": "runtime",
    "category": "template_error|api_validation|execution_failure",
    "message": "Detailed error with context",
    "node_id": "failed-node",
    "fixable": True
}
```

### Error Information Capture

**HTTP Nodes** (`src/pflow/nodes/http/http.py`):
- Store full response in `shared["response"]` including validation details
- But only set `shared["error"] = "HTTP 422"` (status code only)

**MCP Nodes** (`src/pflow/nodes/mcp/node.py`):
- Store full result in `shared["result"]` with nested error data
- But only set `shared["error"] = "invalid_blocks"` (error code only)

### The Gap

**What's captured** (in shared store):
```json
{
  "response": {
    "message": "Validation Failed",
    "errors": [
      {"field": "assignees", "code": "invalid", "message": "should be a list"}
    ]
  }
}
```

**What's shown**: "Workflow execution failed"

**What repair LLM sees**: "HTTP 422"

---

## CLI Architecture

### Command Structure

**Location**: `src/pflow/cli/main.py:2768-2793`

- No subcommands for execution - direct invocation
- Flags MUST come before arguments: `allow_interspersed_args=False`
- Parameters use `key=value` format with automatic type inference

### Existing Flags

```bash
--no-repair         # Disable automatic repair
--validate-only     # To be added - validate without execution
--output-format     # json or text
--trace            # Save execution trace
--verbose          # Detailed output
```

### Parameter Type Inference

**Location**: `src/pflow/cli/main.py:1491-1528`

- `"true"/"false"` → Boolean
- `"42"` → Integer
- `"3.14"` → Float
- `'[1,2,3]'` → List
- `'{"key":"val"}'` → Dict
- Everything else → String

---

## Key Discoveries

### 1. Direct Node Reuse is Optimal

- ✅ Nodes designed for standalone execution
- ✅ No extraction needed - just `node.run(shared)`
- ✅ Test suite proves this works
- ❌ Don't create wrapper functions
- ❌ Don't bypass the lifecycle

### 2. Context Builders Are Complete

- ✅ `build_planning_context()` provides full interface details
- ✅ `build_workflows_context()` includes rich metadata
- ✅ All formatting already done for CLI display
- No enhancements needed

### 3. Error Context Exists but Hidden

- ✅ Nodes capture complete error responses
- ✅ ExecutionResult has structured error data
- ❌ CLI doesn't display it
- ❌ Repair LLM doesn't receive it
- Simple fix: Pass and display ExecutionResult.errors

### 4. Workflow Manager Is Production Ready

- ✅ `save()` method has validation, atomicity, metadata
- ✅ Name validation built in
- ✅ Proper exceptions for conflicts
- Just needs CLI wrapper

### 5. Validation Can Run Standalone

- ✅ ValidatorNode provides 4-layer validation
- ✅ No side effects - pure validation
- ✅ Can validate with partial parameters
- Perfect for --validate-only flag

### 6. LLM Integration Already Solved

- ✅ Nodes handle all LLM calls internally
- ✅ Error handling built in
- ✅ Structured output with Pydantic
- ✅ Prompt caching configured
- No additional LLM logic needed

---

## Implementation Time Estimates

Based on research findings:

| Component | Complexity | Time | Why Fast |
|-----------|-----------|------|----------|
| workflow discover | Low | 30 min | Direct WorkflowDiscoveryNode reuse |
| registry discover | Low | 30 min | Direct ComponentBrowsingNode reuse |
| registry describe | Low | 30 min | Direct build_planning_context() call |
| --validate-only | Low | 45 min | ValidatorNode reuse, flag addition |
| workflow save | Low | 30 min | WorkflowManager.save() exists |
| Enhanced errors | Medium | 30 min | Data exists, just needs display |
| Documentation | Low | 45 min | Clear patterns from research |
| **Total** | | **4 hours** | All heavy lifting already done |

---

## Critical Implementation Notes

### What TO Do

1. **Use nodes directly**: `node.run(shared)`
2. **Display existing error data**: Pass ExecutionResult to error handler
3. **Reuse context builders**: They return markdown ready for display
4. **Trust the patterns**: 350+ tests prove they work

### What NOT to Do

1. **Don't extract logic** from nodes - use them as-is
2. **Don't create wrappers** - direct execution works
3. **Don't skip validation** - critical for agents
4. **Don't hide errors** - display the rich context

---

## References

- Planner flow: `src/pflow/planning/flow.py`
- Node implementations: `src/pflow/planning/nodes.py`
- Context builders: `src/pflow/planning/context_builder.py`
- Error extraction: `src/pflow/execution/executor_service.py`
- CLI main: `src/pflow/cli/main.py`
- Test patterns: `tests/test_nodes/`