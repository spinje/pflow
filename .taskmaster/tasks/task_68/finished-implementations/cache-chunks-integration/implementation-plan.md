# Cache Chunks Integration Implementation Plan

## Executive Summary

Integrate planner cache chunks into the repair system to provide rich context for workflow repairs. This gives the repair system the same contextual knowledge that RuntimeValidationNode had access to.

## Problem Statement

Currently when users run natural language workflows:
1. **Planner** accumulates rich context (requirements, node interfaces, plans) in cache chunks
2. **Execution** gets the workflow but **loses all that context**
3. **Repair** has to guess what nodes are available and how to use them

**Result**: Repairs are less accurate than they could be because they lack the context that made the original workflow generation successful.

## Solution Architecture

### Core Insight: Keep It Simple
Instead of parsing and extracting specific parts of cache chunks, **just pass them directly to the LLM**. Claude is excellent at understanding structured context.

### Cache Chunks Storage Analysis

Cache chunks are stored in planner shared store with different keys based on stage:

```python
# 1. Most Complete (Preferred)
shared["planner_accumulated_blocks"]  # Has full retry history + all context

# 2. Planning Context (Good)
shared["planner_extended_blocks"]     # Has planning result + base context

# 3. Minimal Context (Fallback)
shared["planner_base_blocks"]         # Just system overview + dynamic context
```

**Strategy**: Use priority fallback to get the richest available context.

## Implementation Steps

### Step 1: Extract Cache Chunks from Planner (CLI Layer)

**File**: `src/pflow/cli/main.py`
**Location**: Around line 1899 in `_execute_successful_workflow()`

```python
def _extract_planner_cache_chunks(planner_shared: dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Extract cache chunks from planner shared store in priority order."""
    # Priority 1: Most complete context (has retry history)
    if accumulated := planner_shared.get("planner_accumulated_blocks"):
        return accumulated

    # Priority 2: Planning context (has execution plan)
    if extended := planner_shared.get("planner_extended_blocks"):
        return extended

    # Priority 3: Base context (minimal but better than nothing)
    if base := planner_shared.get("planner_base_blocks"):
        return base

    # No planner context available (file-loaded workflow)
    return None

# Integration point in _execute_successful_workflow()
planner_cache_chunks = _extract_planner_cache_chunks(planner_shared) if planner_shared else None
```

### Step 2: Pass Cache Chunks Through Execution Flow

**File**: `src/pflow/cli/main.py`
**Location**: Around line 993 in `_prepare_execution_environment()`

Following the exact same pattern as `planner_llm_calls`:

```python
def _prepare_execution_environment(
    # ... existing params ...
    planner_cache_chunks: list[dict[str, Any]] | None = None,  # NEW
) -> tuple[...]:

    # ... existing code ...

    # Follow existing pattern for planner_llm_calls
    if planner_cache_chunks:
        enhanced_params["__planner_cache_chunks__"] = planner_cache_chunks

    return cli_output, display, workflow_trace, enhanced_params, effective_verbose

# Update call site in _execute_successful_workflow()
cli_output, display, workflow_trace, enhanced_params, effective_verbose = _prepare_execution_environment(
    ctx, ir_data, output_format, verbose, execution_params, planner_llm_calls, planner_cache_chunks  # NEW
)
```

### Step 3: Integrate Cache Chunks into Repair Service

**File**: `src/pflow/execution/repair_service.py`

#### Option A: Direct Integration (Recommended)

```python
def repair_workflow_with_validation(
    workflow_ir: dict,
    errors: List[Any],
    original_request: Optional[str] = None,
    shared_store: Optional[Dict[str, Any]] = None,
    execution_params: Optional[Dict[str, Any]] = None,  # Already exists
    max_attempts: int = 3
) -> Tuple[bool, Optional[dict], Optional[List[Dict[str, Any]]]]:

    # Extract cache chunks if available
    planner_cache_chunks = None
    if execution_params:
        planner_cache_chunks = execution_params.get("__planner_cache_chunks__")

    # Pass to repair function
    success, repaired_ir = repair_workflow(
        workflow_ir=current_workflow,
        errors=current_errors,
        original_request=original_request,
        shared_store=shared_store,
        planner_cache_chunks=planner_cache_chunks  # NEW
    )
```

#### Update repair_workflow Signature

```python
def repair_workflow(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    original_request: Optional[str] = None,
    shared_store: Optional[Dict[str, Any]] = None,
    planner_cache_chunks: Optional[List[Dict[str, Any]]] = None,  # NEW
) -> Tuple[bool, Optional[dict]]:
```

### Step 4: Simple Cache Chunks Integration in Prompts

**File**: `src/pflow/execution/repair_service.py`
**Function**: `_build_repair_prompt()`

#### The Simple Approach (Recommended)

```python
def _build_repair_prompt(
    workflow_ir: dict,
    errors: List[Dict[str, Any]],
    repair_context: Dict[str, Any],
    original_request: Optional[str],
    planner_cache_chunks: Optional[List[Dict[str, Any]]] = None  # NEW
) -> str:
    """Create prompt for LLM repair with optional planner context."""

    # ... existing error analysis ...

    if has_validation_errors:
        prompt = f"""Fix this workflow that has validation errors.

## Original Request
{original_request or "Not available"}

## Failed Workflow
```json
{json.dumps(workflow_ir, indent=2)}
```

## Validation Errors to Fix
{error_text}"""

        # ADD CACHE CHUNKS CONTEXT (Simple approach)
        if planner_cache_chunks:
            prompt += "\n\n## Planning Context (From Original Generation)\n"
            for i, chunk in enumerate(planner_cache_chunks):
                chunk_text = chunk.get('text', '')
                if chunk_text.strip():  # Only include non-empty chunks
                    prompt += f"\n### Context Block {i+1}\n{chunk_text}\n"

        prompt += """
## Important Requirements
1. Edges must use "from" and "to" keys (NOT "from_node", "to_node")
2. All template variables must reference actual node outputs
3. Node types must exist in the registry
4. JSON must be valid and properly formatted

Return ONLY the corrected workflow JSON.

## Corrected Workflow
```json
"""

    else:
        # Runtime error prompt with cache chunks
        # ... similar pattern for runtime errors ...
```

## Benefits of This Approach

### 1. Rich Context for Repairs
- **Available nodes**: Repair knows which nodes were selected and why
- **Interface details**: Exact input/output specifications for proper template paths
- **User requirements**: Original intent to keep repairs aligned
- **System knowledge**: Workflow patterns and best practices

### 2. Proven Pattern
- **Same as planner_llm_calls**: Uses established context passing mechanism
- **No API changes**: Purely additive functionality
- **Backward compatible**: File-loaded workflows work fine (chunks = None)
- **Minimal risk**: Follows existing patterns exactly

### 3. Simple Implementation
- **No complex parsing**: Let Claude understand the cache chunks directly
- **Robust**: Works even if cache chunk format changes
- **Maintainable**: Less code to debug and maintain
- **Flexible**: Easy to adjust what context is included

## Expected Impact

### Before (Current State)
```
Repair prompt:
- Broken workflow JSON
- Error messages
- Basic repair context
→ LLM has to guess node capabilities
```

### After (With Cache Chunks)
```
Repair prompt:
- Broken workflow JSON
- Error messages
- Basic repair context
- Planning Context:
  - System overview (how workflows work)
  - Available nodes with interfaces
  - User requirements and steps
  - Component selection reasoning
→ LLM has full context for informed repairs
```

### Measurable Improvements
- **Higher repair success rate**: More context = better fixes
- **Fewer repair attempts**: Get it right the first time
- **Better template path accuracy**: Know exact node output formats
- **Aligned with user intent**: Repairs stay true to original requirements

## Implementation Order

1. **Extract function** (`_extract_planner_cache_chunks`) - 5 minutes
2. **CLI integration** (pass chunks through execution flow) - 10 minutes
3. **Repair service signature** (add optional parameter) - 5 minutes
4. **Prompt enhancement** (include cache chunks context) - 15 minutes
5. **Testing** (verify with natural language workflows) - 15 minutes

**Total estimate**: 50 minutes

## Risk Assessment: LOW

- **No breaking changes**: All modifications are additive
- **Proven patterns**: Uses same approach as planner_llm_calls
- **Graceful degradation**: Works without cache chunks (file workflows)
- **Simple rollback**: Can remove cache chunks easily if issues arise

## Success Criteria

1. ✅ Natural language workflows with errors repair more accurately
2. ✅ Repair prompts include relevant planning context
3. ✅ File-loaded workflows continue to work (no cache chunks available)
4. ✅ No performance degradation
5. ✅ All existing tests pass

This implementation gives the repair system the same rich context that made RuntimeValidationNode effective, while maintaining the simplicity and robustness of the current architecture.