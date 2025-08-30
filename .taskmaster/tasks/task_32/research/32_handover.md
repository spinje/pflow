# Task 32 Handoff: Critical Knowledge for Unified Metrics Implementation

**⚠️ IMPORTANT**: Do not begin implementing immediately. Read this entire handoff first, understand the context, and confirm you're ready to begin.

## The Foundation You're Building On (Task 27)

I just completed Task 27 (planner debugging), and you'll be extending that infrastructure. Here's what you MUST know:

### The Four Critical Bugs That Almost Killed Me

1. **The `_run()` bypass bug** (`src/pflow/planning/debug.py:91-113`)
   - Initially, DebugWrapper's `_run()` called `self._wrapped._run()` directly
   - This COMPLETELY BYPASSED our prep/exec/post methods where LLM interception happens
   - **Fix**: Call our own `self.prep()`, `self.exec()`, `self.post()` instead
   - Without this, you'll capture NOTHING from LLM nodes

2. **The closure scope bug** (`src/pflow/planning/debug.py:135`)
   - LLM interceptor functions tried to reference `self.trace` but `self` wasn't in closure scope
   - **Fix**: Capture `trace = self.trace` BEFORE defining nested functions
   - This is subtle but will cause "NoneType has no attribute" errors if wrong

3. **The `response.usage()` is a method, not property** (`src/pflow/planning/debug.py:262`)
   - Different LLM providers return usage differently
   - Some have `response.usage` as property, others as `response.usage()` method
   - **Fix**: Check `callable(response.usage)` and handle both cases
   - This caused AttributeError: 'function' object has no attribute 'get'

4. **The lazy Response evaluation bug** (DISCOVERED POST-IMPLEMENTATION)
   - The `llm` library returns LAZY Response objects - `prompt()` returns instantly
   - Actual API call happens when `response.json()` or `response.text()` is called
   - **Initial bug**: Duration was always 0ms because we timed the wrong operation
   - **Fix**: Wrap Response object to time when `.json()`/`.text()` triggers actual API call
   - **Critical for Task 32**: Your metrics MUST capture timing at evaluation, not at prompt() call

### How LLM Interception Actually Works

The interception happens at the `llm.get_model()` level, not at the node level:

```python
# We monkey-patch llm.get_model globally
original_get_model = llm.get_model
llm.get_model = our_interceptor

# Our interceptor wraps the model's prompt() method
def intercept_get_model(*args, **kwargs):
    model = original_get_model(*args, **kwargs)
    original_prompt = model.prompt
    model.prompt = our_prompt_interceptor
    return model
```

**Critical insight**: We only install the interceptor ONCE (first LLM-using node), but we update `trace.current_node` for each node to track which node is making the call.

**⚠️ LAZY EVALUATION WARNING**: The `prompt()` method returns a Response object immediately. The actual API call happens when the code calls `response.json()` or `response.text()`. Our interceptor returns a wrapped `TimedResponse` object that captures timing at evaluation time, not at prompt() time.

### ⚠️ CRITICAL: The LLM Cleanup Requirement

**This wasn't obvious and almost broke workflow execution:**

After the planner completes but BEFORE executing the generated workflow, we MUST call `trace_collector.cleanup_llm_interception()`. Here's why:

1. **The problem**: We monkey-patch the global `llm.get_model` during planner execution
2. **The consequence**: Without cleanup, the generated workflow's LLM nodes would use our interceptor!
3. **The symptoms if you forget**:
   - Workflow LLM calls might fail with "NoneType" errors
   - Trace collector might try to record to already-finalized traces
   - Confusing mixing of planner vs workflow LLM calls

**Where this happens** (`src/pflow/cli/main.py:961-963`):
```python
# Clean up LLM interception BEFORE workflow execution
if trace_collector:
    trace_collector.cleanup_llm_interception()
```

**Why this matters for Task 32**: If you're adding metrics for workflow execution, you MUST ensure this cleanup happens, or your workflow metrics will be polluted with debugging interceptors.

## Workflow Execution Is COMPLETELY Different

I researched this extensively with pflow-codebase-searcher. Here's what you need to know:

### The Execution Pipeline

1. **CLI** (`src/pflow/cli/main.py:480`) → `execute_json_workflow()`
2. **Compilation** (`src/pflow/runtime/compiler.py:589`) → `compile_ir_to_flow()`
3. **Node Instantiation** (`src/pflow/runtime/compiler.py:213`) → `_instantiate_nodes()`
4. **Wrapping Layers** (ORDER MATTERS!):
   ```
   BaseNode → TemplateAwareNodeWrapper → NamespacedNodeWrapper → [YOUR TracingWrapper]
   ```

### Critical Difference: Dynamic Node Loading

**Planner**: 9 hardcoded nodes in `create_planner_flow()`
**Workflows**: Arbitrary nodes loaded from registry at runtime

This means:
- You CAN'T wrap nodes during flow creation
- You MUST hook into `_instantiate_nodes()` in the compiler
- Nodes are loaded dynamically: module import → class extraction → instantiation

### The Registry Lookup Chain

```python
# src/pflow/runtime/compiler.py:101
node_type → registry.json → module_path → import → class → instance
```

Special case: `"workflow"` type returns `WorkflowExecutor` (nested workflows!)

## Token Extraction Is A Nightmare

Every LLM provider does it differently:

- **OpenAI**: `response.usage.total_tokens`
- **Anthropic via llm**: `response.usage()` returns dict with `input_tokens`/`output_tokens`
- **Local models**: Often NO token counts at all

I started building this in `src/pflow/planning/debug.py:259-267`:

```python
if hasattr(response, "usage"):
    usage_data = response.usage() if callable(response.usage) else response.usage
    if isinstance(usage_data, dict):
        tokens = {
            "input": usage_data.get("input_tokens", 0),
            "output": usage_data.get("output_tokens", 0)
        }
```

But you'll need more robust extraction for all providers.

## The Shared Store Is Your Communication Channel

Both planner and workflows pass a `shared` dictionary through execution. Use reserved keys:

```python
shared = {
    "__metrics__": metrics_collector,  # Your metrics
    "__trace__": trace_collector,      # Debug traces
    "_trace_collector": trace,         # Already used by Task 27
    # ... user data ...
}
```

**Warning**: The automatic namespacing feature (enabled by default!) will namespace user writes but NOT reserved keys starting with `_` or `__`.

## Files You'll Be Modifying

### For Planner Metrics
- `src/pflow/planning/debug.py` - Add metrics collection to existing DebugWrapper
- `src/pflow/planning/flow.py` - Pass metrics through DebugContext
- `src/pflow/cli/main.py:882-983` - The `_execute_planner_and_workflow()` function

### For Workflow Metrics (NEW)
- `src/pflow/runtime/compiler.py:213` - Hook into `_instantiate_nodes()` to add TracingWrapper
- `src/pflow/runtime/compiler.py:589` - Modify `compile_ir_to_flow()` to accept metrics
- Create new `src/pflow/runtime/tracing_wrapper.py` - Your TracingNodeWrapper

### For Output
- `src/pflow/cli/main.py:480` - Modify `execute_json_workflow()` to handle metrics
- `src/pflow/cli/main.py:561` - The JSON output formatting happens here

## Architectural Patterns That Work

1. **Wrapper Pattern**: Already proven with DebugWrapper, TemplateAwareNodeWrapper, NamespacedNodeWrapper
2. **Dependency Injection**: Pass collectors through context objects, not global state
3. **Reserved Keys in Shared Store**: Use `__` prefix for system data
4. **Closure Capture**: Always capture references before defining nested functions

## Anti-Patterns to Avoid

1. **Don't modify existing nodes** - Always wrap
2. **Don't use global state** - Pass through shared store
3. **Don't deep copy large objects** - Metrics should be lightweight
4. **Don't block execution** - Metrics collection must be fast

## The Cost Calculation Challenge

Model pricing changes frequently. I suggested `~/.pflow/pricing.json` config file with defaults. Key models to support:

- `anthropic/claude-sonnet-4-0` (default for planner nodes - see `src/pflow/planning/nodes.py:91`)
- `anthropic/claude-3-haiku-20240307` (metadata generation uses faster model - see line 1376)
- `anthropic/claude-3-5-sonnet-20240620`
- `gpt-4`, `gpt-4o`, `gpt-4o-mini`
- `gpt-3.5-turbo`

## Testing Considerations

The test infrastructure was refactored (see `.taskmaster/tasks/task_27/handoffs/test-infrastructure-refactoring-insights.md`). Tests now mock at the LLM level, not module level. This means you can import normally without module state issues.

To test metrics:
1. Use the `mock_llm_responses` fixture
2. Configure it to return token counts in the response
3. Verify metrics are accumulated correctly

## Performance Warning

The planner takes 10-30 seconds typically (6 LLM calls at 2-8 seconds each). Workflow execution varies wildly. Your metrics collection CANNOT add significant overhead. Consider:
- Lazy evaluation (remember: LLM Response objects are lazy!)
- Incremental aggregation
- Avoiding shared store snapshots for large data
- Using `time.perf_counter()` not `time.time()` for sub-second precision

## The Output Format Challenge

Currently, when `--output-format json` is used, the code expects to output just the result. You'll need to wrap it:

```json
{
  "result": <existing output>,
  "metrics": <your metrics>
}
```

This might break existing consumers expecting just the result at root level. Consider a flag like `--include-metrics` to opt-in.

## Don't Forget About Nested Workflows

`WorkflowExecutor` nodes run other workflows. Your metrics need to handle hierarchical execution. The registry is passed as `__registry__` parameter to these nodes.

## Final Critical Insight

The planner and workflow execution are TWO SEPARATE FLOWS:
1. Planner runs first, generates IR
2. Workflow compiles IR and runs

They share NOTHING except what you explicitly pass through the CLI orchestration layer. Your MetricsCollector needs to span both phases, living in the CLI layer and being passed down to both.

## Links to Critical Code

- Planner execution: `src/pflow/cli/main.py:882-983`
- Workflow execution: `src/pflow/cli/main.py:480-560`
- Node wrapping: `src/pflow/runtime/compiler.py:213-311`
- Existing debug infrastructure: `src/pflow/planning/debug.py`
- Node detection logic: All nodes return `model_name` in prep if they use LLM

## Remember

- The `--trace` flag already exists for debugging
- Progress indicators already show during planner execution
- The infrastructure for wrapping and intercepting is proven
- The shared store is your friend for passing data

Good luck. The foundation is solid, but the details are treacherous.

**Again: Read everything first, understand the architecture, THEN begin implementation.**