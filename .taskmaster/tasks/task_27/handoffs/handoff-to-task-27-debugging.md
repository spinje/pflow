# Critical Context for Planner Debugging (Task 27)

## The Planner is a Meta-Workflow

**This is not a traditional function** - the planner is itself a PocketFlow workflow that creates other PocketFlow workflows. It's workflows all the way down. This means:
- Debugging requires understanding PocketFlow's Flow/Node execution model
- Each node has `prep()` → `exec()` → `post()` lifecycle
- Nodes communicate only through `shared` dictionary
- The planner's output is another workflow's IR (intermediate representation)

Entry point: `src/pflow/planning/flow.py::create_planner_flow()`

## Two Execution Paths That Converge

The planner has two fundamentally different paths that converge at a single point:

**Path A (Reuse)**: User input → Discovery finds existing workflow → Extract params → Execute
**Path B (Generation)**: User input → Discovery fails → Browse components → Generate new → Validate → Extract params → Execute

**Critical convergence point**: `ParameterMappingNode` (lines 796-835 in `src/pflow/planning/nodes.py`)
- This node detects which path it's on by checking `shared.get("generated_workflow")`
- Returns different action strings: `"params_complete_validate"` (Path B) vs `"params_complete"` (Path A)
- **This routing logic is fragile** - any change to shared keys breaks path detection

## The Validation Redesign That Fixed Everything

**Original fatal flaw**: Template validation happened BEFORE parameter extraction
- Result: `$input_file` validated against empty `{}` → always failed
- Impact: ALL workflows with required inputs were broken

**The fix** (December 2024):
- Reordered flow: Generate → ParameterMapping → Validate → Metadata
- ValidatorNode now receives `extracted_params` for template validation
- Files: See scratchpad `/Users/andfal/projects/pflow/scratchpads/task-17-validation-fix/`

**Why this matters for debugging**: If you see template validation errors, check the execution order and ensure parameters are extracted first.

## LLM Communication Pitfalls

**Discovery #1**: The context builder was lying to the LLM
- Showed "Parameters: none" for nodes that accept template variables
- LLM followed instructions and hardcoded values instead of using `$variables`
- Fix: `src/pflow/planning/context_builder.py` lines 627-664

**Discovery #2**: LLMs take 10-30 seconds for complex requests
- No progress indication → users think it's frozen
- Added verbose messages warning about delays
- Consider adding progress callbacks for debugging

**Discovery #3**: Missing parameters behave differently
- Path A (reuse): Common - user says "run analyzer" but workflow needs `$input_file`
- Path B (generation): Rare - same input used for generation AND extraction

## CLI Decision Tree (How Requests Reach the Planner)

```
User Input → Is it JSON?
├─ YES → Execute directly (bypass planner)
└─ NO → Looks like workflow name?
    ├─ YES & Exists → Direct execution (100ms)
    ├─ YES & Not Found → Fall to planner
    └─ NO → Send to planner (2-5s)
```

**Key files**:
- Detection logic: `src/pflow/cli/main.py::is_likely_workflow_name()` (line 652)
- Direct execution: `src/pflow/cli/main.py::_try_direct_workflow_execution()` (line 593)
- Planner invocation: `src/pflow/cli/main.py::_execute_with_planner()` (line 520)

## Testing Without Real LLMs

**The mock**: `tests/test_cli/conftest.py`
- Replaces entire planning module to raise ImportError
- Triggers fallback to echo behavior
- Applied automatically to all CLI tests

**For planner-specific tests**: Mock individual nodes
```python
with patch.object(WorkflowGeneratorNode, 'exec') as mock_exec:
    mock_exec.return_value = {"found": False, "workflow": {...}}
```

**Real LLM tests**: Set `RUN_LLM_TESTS=1` environment variable
- Tests marked with `@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"))`
- Costs money, takes 30+ seconds per test

## Performance Bottlenecks

1. **Discovery phase**: Should be <1s but includes context building
   - Context builder loads ALL workflows and nodes into memory
   - See `src/pflow/planning/context_builder.py::build_discovery_context()`

2. **LLM calls**: Each takes 2-5s, sometimes 10-30s
   - Discovery, Browsing, Generation, Parameter extraction = 4+ LLM calls minimum
   - No caching between calls

3. **Validation retries**: Up to 3 attempts if generation fails
   - Each retry is another full LLM generation call

## Critical Shared Store Keys

The planner's nodes communicate through these keys:
- `user_input` - Original natural language request
- `workflow_manager` - For loading/saving workflows
- `found_workflow` - Path A: loaded workflow
- `generated_workflow` - Path B: newly created workflow
- `extracted_params` - Parameters extracted from user input
- `planner_output` - Final result with `success`, `workflow_ir`, `execution_params`

**Warning**: Many nodes check existence of keys to determine state. Adding/removing keys can break path detection.

## Edge Cases That Will Bite You

1. **Empty workflow names**: `pflow ""` was incorrectly detected as workflow name
   - Fixed in `is_likely_workflow_name()` but watch for similar heuristic failures

2. **CLI syntax confusion**: `pflow node1 => node2` was treated as workflow "node1"
   - Detection now checks for `=>` operator in remaining args

3. **Template variables in params**: Nodes use fallback pattern
   ```python
   value = shared.get("key") or self.params.get("key")
   ```
   - ANY parameter can be a template variable, not just exclusive ones

4. **Missing WorkflowManager**: Some nodes create singleton if not in shared
   - Leads to inconsistent state in tests
   - Always pass WorkflowManager explicitly

## Architecture Patterns (Use These)

1. **Two-phase context loading**: Discovery gets minimal context, planning gets full context
   - Prevents LLM context overflow
   - See `build_discovery_context()` vs `build_planning_context()`

2. **Structured LLM output**: All nodes use Pydantic models
   - `WorkflowDiscoveryOutput`, `ComponentBrowsingOutput`, etc.
   - Enforces response structure, aids debugging

3. **Action-based routing**: Nodes return action strings, Flow handles routing
   - Don't put routing logic in nodes
   - Use `post()` method to return action string

## Anti-Patterns (Avoid These)

1. **Don't test individual nodes** - Test complete paths
   - Nodes depend on shared state from previous nodes
   - Isolated tests miss integration issues

2. **Don't hardcode shared keys** - Use constants or configuration
   - Key typos are silent failures

3. **Don't skip parameter extraction** - Even for "simple" workflows
   - Users expect `pflow "analyze data.csv"` to set `input_file=data.csv`

## Files You'll Need Constantly

**Core orchestration**:
- `src/pflow/planning/flow.py` - The planner's PocketFlow structure
- `src/pflow/planning/nodes.py` - All 9 nodes (1400+ lines, intentionally monolithic)

**Context building**:
- `src/pflow/planning/context_builder.py` - How LLMs see available components

**Integration points**:
- `src/pflow/cli/main.py` lines 520-590 - Planner invocation
- `src/pflow/runtime/compiler.py` - How workflow IR becomes executable

**Test infrastructure**:
- `tests/test_planning/integration/` - Complete path tests
- `tests/test_cli/conftest.py` - CLI test mocking

## Debugging Starting Points

1. **"Planning failed" errors**: Check `shared["planner_output"]["error"]`
   - Add logging to `ResultPreparationNode` to see what's in shared

2. **Wrong path taken**: Add logging to `ParameterMappingNode.post()`
   - Check if `generated_workflow` key exists in shared

3. **Template validation failures**: Log in `ValidatorNode._validate_templates()`
   - Verify `extracted_params` contains expected values

4. **Slow performance**: Time each node execution
   - Add timestamps in `prep()` and `post()` methods

5. **LLM producing bad output**: Capture raw LLM responses
   - Log before Pydantic parsing in each node's `exec()`

## The Most Important Thing

**The planner is fragile because it's a complex state machine**. Each node depends on previous nodes setting up shared state correctly. When debugging:

1. **Always trace the full path** - Don't assume the problem is where the error appears
2. **Check shared state at each step** - One missing key cascades into failures
3. **Verify Path A vs Path B detection** - Most bugs come from taking the wrong path
4. **Remember it's async with LLMs** - Add timeouts and progress indication

The planner works, but it's held together by careful coordination of shared state. Treat it like a distributed system where nodes can't talk directly - because that's what it is.