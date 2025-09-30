# Research Findings: LLM Trace Analysis Issue

## Executive Summary

The `scripts/analyze-trace/latest.sh` script is broken for workflow LLM calls because the workflow trace collector fails to capture LLM prompts. While the analysis script is correctly designed to handle both planner and workflow trace formats, the workflow traces are missing the `llm_prompt` field that the script expects.

## The Problem

### What Works
- ✅ Planner traces correctly show LLM calls with prompts and responses
- ✅ Workflow traces capture LLM metadata (model, tokens, costs)
- ✅ Workflow traces sometimes capture LLM responses
- ✅ The analysis script can handle both formats when data is present

### What's Broken
- ❌ Workflow traces don't capture LLM prompts
- ❌ Repair LLM calls aren't tracked at all
- ❌ LLM interception mechanism fails for workflow execution

## Root Cause Analysis

### 1. LLM Node Detection Failure

**Location**: `src/pflow/runtime/instrumented_wrapper.py:676`

```python
def _setup_llm_interception(self) -> None:
    node_params = self._get_node_params()
    if node_params and "prompt" in node_params:  # ❌ WRONG!
        self.trace.setup_llm_interception(self.node_id)
```

**Issue**: The code only sets up LLM interception if the node has `"prompt"` in its params. However, LLM nodes typically get their prompt from the shared store via `shared.get("prompt")`, not from params.

**Impact**: LLM interception is never set up for actual LLM nodes, so prompts are never captured.

### 2. Missing Prompt in __llm_calls__ Data

**Location**: `src/pflow/runtime/instrumented_wrapper.py:100-162`

```python
def _capture_llm_usage(self, shared, shared_before, duration_ms, is_planner):
    # ... captures usage data ...
    llm_call_data = llm_usage.copy()
    llm_call_data["node_id"] = self.node_id
    # ❌ MISSING: No prompt capture here!
    shared["__llm_calls__"].append(llm_call_data)
```

**Issue**: When capturing LLM usage data, the prompt is never added to the `__llm_calls__` entry.

**Impact**: Even if we had the prompt available, it wouldn't be stored where the trace collector looks for it.

### 3. Thread-Based Interception Complexity

**Location**: `src/pflow/runtime/workflow_trace.py:480-533`

```python
def intercept_prompt(prompt_text: str, **prompt_kwargs: Any) -> Any:
    thread_id = threading.current_thread().ident
    if thread_id and thread_id in WorkflowTraceCollector._active_collectors:
        collector = WorkflowTraceCollector._active_collectors[thread_id]
        if collector._current_node:
            collector.llm_prompts[collector._current_node] = prompt_text
```

**Issue**: The thread-based interception relies on complex thread management that often fails. The collector might not be registered for the thread, or `_current_node` might not be set.

**Impact**: Even when interception is set up, prompts still might not be captured.

### 4. No Fallback Prompt Detection

**Location**: `src/pflow/runtime/workflow_trace.py:195-268`

```python
def _find_llm_prompt(self, node_id: str, event: dict[str, Any], shared_after: dict[str, Any]) -> Optional[str]:
    # Tries multiple sources but misses the obvious one:
    # LLM nodes store prompt in shared["prompt"] before execution!
```

**Issue**: The trace collector doesn't check `shared_before["prompt"]` which is where LLM nodes read their prompts from.

**Impact**: Even without interception, we could capture prompts but we don't look in the right place.

## Comparison with Planner Traces

The planner trace system (`src/pflow/planning/debug.py`) works differently and successfully:

### Planner Approach (Working)
1. Uses direct method interception of `llm.get_model()` and `model.prompt()`
2. Captures prompts immediately when LLM calls are made
3. Stores everything in a centralized `llm_calls` list at the root level

### Workflow Approach (Broken)
1. Uses thread-based interception that's fragile
2. Relies on detecting LLM nodes incorrectly
3. Stores data in multiple locations without proper coordination

## The Fix Strategy

### Immediate Fixes Needed

1. **Fix LLM Node Detection**
   - Check if node type contains "llm" OR if node reads from `shared["prompt"]`
   - Look at actual node execution patterns, not just params

2. **Add Prompt to __llm_calls__**
   - When capturing LLM usage, also capture the prompt from `shared_before["prompt"]`
   - Store it in the `__llm_calls__` entry

3. **Add Fallback Prompt Detection**
   - In `_find_llm_prompt()`, check `shared_before.get("prompt")`
   - This would work even without interception

4. **Track Repair LLM Calls**
   - The repair service uses LLM but isn't tracked at all
   - Need to ensure repair LLM calls are captured in traces

### Why This Will Work

- The analysis script (`analyze.py`) already handles the data correctly when it's present
- The workflow traces already capture some LLM data (responses, tokens)
- We just need to capture and store the prompts in the expected locations

## Impact on Task 68

This issue is separate from but related to the repair system work:
- The repair tracking we added will be visible in traces
- But repair LLM calls won't show up until we fix the prompt capture
- This affects debugging capabilities for the repair system

## Files That Need Changes

1. **`src/pflow/runtime/instrumented_wrapper.py`**
   - Fix `_setup_llm_interception()` detection logic
   - Add prompt capture to `_capture_llm_usage()`

2. **`src/pflow/runtime/workflow_trace.py`**
   - Add fallback prompt detection from `shared_before["prompt"]`
   - Potentially simplify the interception mechanism

3. **No changes needed to `scripts/analyze-trace/analyze.py`**
   - It already handles the data correctly when present