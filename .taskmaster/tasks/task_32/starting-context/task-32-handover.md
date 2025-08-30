# Task 32 Handoff: What You Really Need to Know

**⚠️ IMPORTANT**: Do not begin implementing immediately. Read this entire handoff, the spec, and the implementation guide, then confirm you're ready to begin.

## The Journey of Discovery

I started with 9 research documents full of assumptions and contradictions. Through extensive verification with the codebase searcher, I discovered that about 40% of the "facts" in those documents were wrong. Here's what matters:

### The Big Revelation

The user and I discovered that metrics and tracing aren't separate features—they're **the same telemetry system at different verbosity levels**. This insight drove the entire unified architecture. When the user asked "think hard" about whether they should be combined, we realized the overlap was massive. This is why there's one `InstrumentedNodeWrapper` serving both needs.

### What Task 27 Really Taught Us

Task 27 (planner debugging) revealed critical bugs that you MUST avoid:

1. **The Lazy Response Bug**: The `llm` library returns lazy Response objects. `prompt()` returns instantly—the actual API call happens when `response.json()` or `response.text()` is called. Task 27 initially timed the wrong thing (always 0ms). You must time the evaluation, not the prompt call.

2. **The `_run()` Bypass Bug**: DebugWrapper initially called `self._wrapped._run()` which bypassed the prep/exec/post methods where LLM interception happens. You must call your own prep/exec/post methods.

3. **The Closure Scope Bug**: When creating interceptor functions, `self` isn't in closure scope. You must capture references first: `trace = self.trace` before defining nested functions.

4. **The `response.usage()` is a Method**: Not a property! Always check `callable(response.usage)` and call it with parentheses.

## What the User Really Wants

Beyond the spec, here's what emerged from our conversation:

1. **Claude Code Comparison**: The user specifically wants to compare pflow's efficiency with Claude Code. That's why top-level metrics match Claude's format (`is_error`, `duration_ms`, `total_cost_usd` at root).

2. **No Deprecation Theater**: When I suggested deprecation warnings for the `--trace` flag change, the user reminded me this is a private MVP with zero users. Just change it. No backward compatibility needed.

3. **Complete Error Traces**: The user emphasized traces should include ALL execution data up to and including errors, not just error information. This helps debug the sequence leading to failure.

4. **Progressive Enhancement**: The user loved the idea of zero overhead → metrics → full traces as a progression. Default must be pristine.

## Critical Discoveries Not Obvious from Docs

### The LLM Usage Overwrite Trap

The LLMNode sets `shared["llm_usage"]` which looks perfect for tracking. But I discovered it OVERWRITES on each call. If you have 3 LLM nodes, you only get the last one's usage. That's why we need `shared["__llm_calls__"]` as an accumulation list. This isn't documented anywhere.

### The time.time() Inconsistency

The docs and comments say to use `time.perf_counter()` but the actual code uses `time.time()` everywhere except in `TimedResponse`. This is a precision issue—`time.time()` is wall clock time affected by NTP adjustments. You must standardize to `time.perf_counter()`.

### The Template Resolution Gap

Templates are currently only logged at DEBUG level (`node_wrapper.py:143`). There's no mechanism to capture them for traces. You'll need to implement this from scratch. The resolution happens in `TemplateAwareNodeWrapper._run()` around lines 112-159.

### The Directory Truth

Every document said traces go to `~/.pflow/traces/`. They don't. It's `~/.pflow/debug/`. Keep the existing directory—don't create a new one.

## Patterns That Actually Work

### Wrapper Delegation (From Existing Code)

Every wrapper in the codebase uses this exact pattern:

```python
def __getattr__(self, name: str) -> Any:
    if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    inner = object.__getattribute__(self, "inner_node")
    return getattr(inner, name)
```

Don't deviate. This prevents pickle/copy infinite recursion while delegating everything else.

### The __metrics__ Pattern

The shared store uses `__` prefix for system keys that don't get namespaced. Follow this pattern:
- `__metrics__` for the collector
- `__llm_calls__` for accumulation
- `__trace__` for trace collector

## Hidden Complexities

### Wrapper Order Is Everything

The wrapper order determines what each wrapper sees:
```
InstrumentedNodeWrapper (sees everything)
    ↓
NamespacedNodeWrapper (creates namespaced store)
    ↓
TemplateAwareNodeWrapper (resolves templates)
    ↓
BaseNode (actual implementation)
```

If you put InstrumentedNodeWrapper in the wrong position, it won't see template resolutions or namespace operations.

### The Planner/Workflow Execution Split

These are TWO SEPARATE FLOWS that share nothing except what you pass through the CLI layer:
1. Planner runs, generates IR, has its own Flow with DebugWrapper
2. Workflow compiles IR, creates new Flow with InstrumentedNodeWrapper

The MetricsCollector must span both, living in the CLI layer and being passed down.

### Model Pricing Units

The existing test tool (`test_prompt_accuracy.py`) uses per-million token pricing. The research docs suggested per-thousand. Go with per-million to match existing code.

## Files You'll Actually Touch

These are the real integration points (verified):

1. **CLI Flags**: `/src/pflow/cli/main.py:1313-1317` - Add `--trace-planner` here
2. **Node Creation**: `/src/pflow/runtime/compiler.py:292` in `_create_single_node()` - Apply wrapper here
3. **Planner Debug**: `/src/pflow/planning/debug.py:100` in `DebugWrapper.__init__` - Add metrics parameter
4. **JSON Output**: `/src/pflow/cli/main.py:333` in `_handle_json_output()` - Wrap with metrics here
5. **Template Resolution**: `/src/pflow/runtime/node_wrapper.py:112-159` - Capture resolutions here

## Questions You'll Hit

**Q: Why not modify LLMNode to accumulate?**
A: Because that changes node behavior. The wrapper pattern keeps nodes pure.

**Q: Why timestamp in filename but UUID in JSON?**
A: Existing pattern. Timestamps are human-readable in filesystem, UUIDs for programmatic correlation.

**Q: Should I fix time.time() everywhere?**
A: Only in new code. Don't touch existing DebugWrapper—that's out of scope.

**Q: What about nested workflows?**
A: WorkflowExecutor nodes will get wrapped too. The instrumentation is recursive.

## The Hardest Parts

### 1. Template Resolution Capture
It's currently only logged, and the information isn't stored anywhere. You'll need to:
1. Detect when you're wrapping a TemplateAwareNodeWrapper
2. Capture the resolution data somehow (maybe a callback?)
3. Store it in the trace

This is the one thing I couldn't fully solve in the spec.

### 2. Zero Test Coverage for Debug System
**CRITICAL DISCOVERY**: The existing debug/tracing system has ZERO test coverage. The test files that Task 27 claims to have created don't exist. This means:
- You're building on untested code (DebugWrapper, TraceCollector)
- You must create comprehensive tests for the new system
- There are no examples of testing trace/debug features to follow

You'll need to create tests from scratch. Use the mocking patterns from `tests/test_planning/integration/test_planner_working.py` for LLM mocking.

## Your Advantage

You have three key documents:
1. **The spec** (`task-32-spec.md`) - The formal requirements, all verified
2. **The implementation guide** (`implementation-guide.md`) - Complete code examples and integration points
3. **This handoff** - The context and gotchas

Together, they give you everything I learned. The spec is clean and verified. The implementation guide has working code. This handoff has the war stories.

## Final Critical Reminder

The user expects this to enable cost transparency. Every pflow user will depend on these metrics to understand their AI spend. Make the costs accurate—verify against Claude Code's output for the same operations.

Also remember: The existing `--trace` flag only traces the planner. You're changing it to trace workflows and adding `--trace-planner` for the planner. This is a breaking change but that's fine—no users yet.

---

**Do not begin implementing yet.** Read the spec and implementation guide, then confirm you understand the task and are ready to begin.