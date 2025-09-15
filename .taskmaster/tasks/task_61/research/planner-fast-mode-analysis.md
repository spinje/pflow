# Planner Fast Mode Analysis: Aggressive Parallelization

## Concept: --fast Mode

A special mode that trades quality for speed by aggressively parallelizing the planner pipeline.

## Proposed Architecture

### Standard Mode (Current - Quality First)
```
Discovery (500ms) → ParameterDiscovery (400ms) → RequirementsAnalysis (400ms) →
ComponentBrowsing (400ms) → Planning (600ms) → WorkflowGenerator (1200ms)
Total Path B: ~3600ms (excluding validation/metadata)
```

### Fast Mode (Speed First)
```
Stage 1: Discovery + ParameterDiscovery (parallel)
         500ms max

Stage 2: RequirementsAnalysis + ComponentBrowsing (parallel)
         400ms max

Stage 3: Planning → WorkflowGenerator (sequential - required)
         1800ms

Total Path B: ~2700ms (25% faster!)
```

## Implementation Design

### Stage 1: Parallel Start (Already Analyzed)
```python
# Both run in parallel
Discovery (500ms) ────────┐
                          ├→ Route Decision + Results
ParameterDiscovery (400ms)┘
```
**Output**: `discovery_result`, `templatized_input`, `discovered_params`

### Stage 2: Parallel Analysis (NEW)
```python
# Both run in parallel with Stage 1 outputs
RequirementsAnalysis (400ms) ──┐
                                ├→ Both results to Planning
ComponentBrowsing* (400ms) ─────┘
```

**Key Change**: ComponentBrowsing modified to work WITHOUT requirements:
- In standard mode: Uses requirements to improve selection
- In fast mode: Uses only user_input + templatized_input

## Quality Trade-offs

### What We Lose in Fast Mode

1. **Component Selection Quality**
   - Standard: ComponentBrowsing knows WHAT needs to be done (requirements)
   - Fast: ComponentBrowsing guesses based on raw input
   - **Impact**: May select unnecessary nodes (10-20% over-selection)

2. **Error Detection Timing**
   - Standard: RequirementsAnalysis can fail fast on vague input
   - Fast: Vague input detected but ComponentBrowsing runs anyway
   - **Impact**: Wasted component browsing on doomed requests

3. **Conceptual Clarity**
   - Standard: Clean WHAT→HOW flow
   - Fast: WHAT and HOW determined simultaneously
   - **Impact**: Harder to debug, less predictable

### What We Keep

✅ Requirements abstraction still happens
✅ Planning still gets both requirements AND components
✅ Context accumulation still works
✅ Retry learning preserved
✅ All Task 52 benefits maintained

## Implementation Strategy

### 1. Add CLI Flag
```python
@click.option('--fast', is_flag=True, help='Trade quality for speed (25% faster)')
def plan(user_input, fast=False):
    if fast:
        flow = create_fast_planner_flow()
    else:
        flow = create_planner_flow()
```

### 2. Create Fast Flow Variant
```python
def create_fast_planner_flow():
    # Stage 1: Parallel start
    parallel_start = ParallelStartNode()  # Discovery + ParameterDiscovery

    # Stage 2: Parallel analysis
    parallel_analysis = ParallelAnalysisNode()  # Requirements + ComponentBrowsing

    # Stage 3: Sequential generation (unchanged)
    planning = PlanningNode()
    generator = WorkflowGeneratorNode()

    # Wire the flow
    flow = Flow(start=parallel_start)
    parallel_start >> parallel_analysis
    parallel_analysis >> planning
    planning >> generator
    # ... rest unchanged

    return flow
```

### 3. Modify ComponentBrowsingNode
```python
class ComponentBrowsingNode(Node):
    def prep(self, shared):
        # Check if we're in fast mode (no requirements yet)
        fast_mode = "requirements_result" not in shared

        if fast_mode:
            # Use templatized input for better hints
            context = shared.get("templatized_input", shared["user_input"])
            # Build context without requirements
            prompt = self._build_fast_prompt(context)
        else:
            # Standard mode with requirements
            requirements = shared["requirements_result"]
            prompt = self._build_standard_prompt(requirements)
```

### 4. Create ParallelAnalysisNode
```python
class ParallelAnalysisNode(AsyncParallelBatchNode):
    def prep(self, shared):
        # Prepare inputs for both nodes
        return [
            {"type": "requirements", "input": shared["templatized_input"]},
            {"type": "components", "input": shared["user_input"]}
        ]

    async def exec_async(self, items):
        results = await asyncio.gather(
            requirements_node.exec_async(items[0]),
            component_browsing_node.exec_async(items[1])
        )
        return results

    def post(self, shared, prep_res, exec_res):
        # Store both results
        shared["requirements_result"] = exec_res[0]
        shared["browsed_components"] = exec_res[1]

        # Check for vague input
        if not exec_res[0]["is_clear"]:
            return "clarification_needed"
        return "continue"
```

## Performance Analysis

### Time Savings Breakdown

| Stage | Standard Mode | Fast Mode | Savings |
|-------|--------------|-----------|---------|
| Stage 1 | 900ms (sequential) | 500ms (parallel) | 400ms |
| Stage 2 | 800ms (sequential) | 400ms (parallel) | 400ms |
| Stage 3 | 1800ms | 1800ms | 0ms |
| **Total** | **3500ms** | **2700ms** | **800ms (23%)** |

### Cost Analysis

**Additional LLM costs in Fast Mode:**
- None! Same number of LLM calls, just reordered
- No wasted work if properly coordinated

**Quality cost:**
- 10-20% over-selection of components
- Slightly less optimal workflows
- May need more retries (5-10% increase)

## User Experience Comparison

### Standard Mode
```bash
$ pflow "analyze github issues and create report"
[1/6] Discovering existing workflows... (500ms)
[2/6] Extracting parameters... (400ms)
[3/6] Analyzing requirements... (400ms)
[4/6] Selecting components... (400ms)
[5/6] Planning execution... (600ms)
[6/6] Generating workflow... (1200ms)
✓ Workflow generated in 3.5s
```

### Fast Mode
```bash
$ pflow --fast "analyze github issues and create report"
[1/4] Discovering + Extracting... (500ms)
[2/4] Analyzing + Selecting... (400ms)
[3/4] Planning execution... (600ms)
[4/4] Generating workflow... (1200ms)
✓ Workflow generated in 2.7s (fast mode)
```

## Risk Assessment

### Low Risk ✅
- No architectural changes to core nodes
- Conversation/context pattern preserved
- Easy to maintain both modes
- User explicitly opts in with --fast

### Medium Risk ⚠️
- Component over-selection may cause inefficient workflows
- Parallel coordination complexity
- Testing burden (need to test both modes)
- Debugging harder with parallel execution

### High Risk ❌
- None identified - worst case is slightly degraded quality

## Recommendation

### YES, Implement Fast Mode Because:

1. **User Choice**: Let users decide the trade-off
   - Default: Quality first (standard mode)
   - Opt-in: Speed first (--fast flag)

2. **Significant Speedup**: 23% faster is noticeable
   - 3.5s → 2.7s crosses a psychological threshold
   - Under 3 seconds feels "instant"

3. **Acceptable Quality Loss**:
   - Component over-selection is minor
   - Planning still optimizes the workflow
   - Most workflows will be identical

4. **Learning Opportunity**:
   - Gather data on quality impact
   - A/B test user preferences
   - Inform future optimizations

### Implementation Priority

1. **Phase 1**: Discovery + ParameterDiscovery parallel (both modes)
   - 400ms improvement
   - Low risk
   - Benefits everyone

2. **Phase 2**: Add --fast flag with Requirements + ComponentBrowsing parallel
   - Additional 400ms improvement
   - Opt-in only
   - Gather metrics on usage and quality

3. **Phase 3**: Consider making fast mode default if:
   - Quality impact < 5%
   - User satisfaction increases
   - Retry rate doesn't spike

## Alternative: Smart Mode Selection

Instead of a flag, automatically choose based on input complexity:

```python
def choose_mode(user_input):
    # Simple requests use fast mode
    if len(user_input.split()) < 10:
        return "fast"

    # Complex requests use standard mode
    if "and then" in user_input or "after that" in user_input:
        return "standard"

    # Default to fast for common patterns
    if user_input.startswith(("create", "generate", "fetch")):
        return "fast"

    return "standard"
```

## Code Example: Fast Mode Implementation

```python
# src/pflow/planning/fast_flow.py

from pocketflow import AsyncParallelBatchNode, Flow
import asyncio

class FastPlannerStage1(AsyncParallelBatchNode):
    """Parallel Discovery + ParameterDiscovery"""

    async def exec_async(self, shared):
        discovery_task = discovery_node.run_async(shared.copy())
        param_task = parameter_discovery_node.run_async(shared.copy())

        discovery_result, param_result = await asyncio.gather(
            discovery_task, param_task
        )

        # Merge results
        shared.update(discovery_result)
        shared.update(param_result)

        # Route based on discovery
        if shared["discovery_result"]["found"]:
            return "path_a"
        return "path_b"

class FastPlannerStage2(AsyncParallelBatchNode):
    """Parallel Requirements + ComponentBrowsing"""

    async def exec_async(self, shared):
        # Prepare modified component browsing without requirements
        component_shared = shared.copy()
        component_shared["fast_mode"] = True

        requirements_task = requirements_node.run_async(shared.copy())
        component_task = component_browsing_node.run_async(component_shared)

        req_result, comp_result = await asyncio.gather(
            requirements_task, component_task
        )

        # Check for vague input
        if not req_result["requirements_result"]["is_clear"]:
            return "clarification_needed"

        # Merge and continue
        shared.update(req_result)
        shared.update(comp_result)
        return "continue"

def create_fast_planner_flow():
    """Create the fast mode planner flow"""

    stage1 = FastPlannerStage1()
    stage2 = FastPlannerStage2()
    planning = PlanningNode()
    generator = WorkflowGeneratorNode()
    # ... other nodes

    flow = Flow(start=stage1)

    # Path A (reuse)
    stage1 - "path_a" >> parameter_mapping

    # Path B (generation)
    stage1 - "path_b" >> stage2
    stage2 - "continue" >> planning
    stage2 - "clarification_needed" >> result_preparation

    planning >> generator
    # ... rest of flow

    return flow
```

## Conclusion

**Fast mode is worth implementing** as an opt-in feature. It provides meaningful speed improvements (23%) with acceptable quality trade-offs. The implementation is straightforward using PocketFlow's async patterns, and it gives users control over the speed/quality balance.

Start with Phase 1 (Discovery + ParameterDiscovery) for everyone, then add the --fast flag for users who prioritize speed. Monitor metrics to determine if fast mode should become the default in the future.