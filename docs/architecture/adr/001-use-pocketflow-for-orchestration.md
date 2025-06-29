# ADR-001: Use PocketFlow for Internal Orchestration

Date: 2025-06-29

## Status

Accepted

## Context

pflow is a workflow compiler that transforms natural language and CLI syntax into executable workflows using the PocketFlow framework. During development, we faced an architectural decision: should we use PocketFlow internally to build pflow itself, or use traditional imperative Python code?

Initial reaction was to avoid using PocketFlow internally, based on the principle "don't use your output format to build your compiler." However, deeper analysis revealed that PocketFlow is not just an output format - it's a lightweight pattern for reliable orchestration.

### Key Observations

1. **PocketFlow is minimal**: The entire framework is ~100 lines of Python code
2. **Many pflow operations are multi-step orchestrations**: compilation, planning, execution, tracing
3. **These operations have common needs**: retry logic, error handling, state accumulation
4. **Traditional code leads to complexity**: Nested try/catch blocks, manual retry loops, hidden control flow

## Decision

Use PocketFlow for complex orchestration tasks within pflow, while keeping simple utilities and data structures as traditional code.

### Components Using PocketFlow

The following 6 core orchestration tasks will use PocketFlow:

1. **IR-to-PocketFlow Compiler** (Task 4)
   - Load JSON → Validate → Import Nodes → Build Flow
   - Multiple I/O operations with failure modes
   - Dynamic imports need retry logic

2. **Shell Integration** (Task 8)
   - Detect stdin → Read/Stream → Handle signals → Exit codes
   - Complex I/O with timeouts and branching

3. **LLM Workflow Generation** (Task 17)
   - Parse input → Call LLM → Validate → Retry on errors
   - Self-correcting loops with multiple retry strategies

4. **Approval and Storage** (Task 20)
   - Present → User decision → Validate → Store → Index
   - Interactive flow with multiple paths

5. **Named Workflow Execution** (Task 22)
   - Load → Validate lockfile → Apply params → Execute
   - Multi-step with various failure modes

6. **Execution Tracing** (Task 23)
   - Monitor → Capture → Format → Output to multiple destinations
   - Parallel output streams without interfering with execution

### Components Using Traditional Code

All other components use traditional Python patterns:
- Pure utilities (validators, formatters)
- Data structures (schemas, registries)
- Simple CLI commands
- Platform nodes (already inherit from BaseNode)

## Consequences

### Positive

1. **Built-in Reliability**: Automatic retry/fallback for I/O operations
2. **Clear Control Flow**: Visual representation with `>>` operator
3. **Better Testing**: Isolated nodes are independently testable
4. **Consistent Error Handling**: Explicit error paths with action-based routing
5. **Easy Extension**: New steps can be added without modifying existing code
6. **Dogfooding**: We prove PocketFlow works by using it ourselves

### Negative

1. **Learning Curve**: Developers need to understand PocketFlow patterns
2. **Debugging**: Stack traces go through PocketFlow orchestration
3. **Potential Over-engineering**: Some simple operations might feel heavyweight as nodes

### Neutral

1. **Different Programming Style**: Flow-based vs imperative
2. **More Files**: Each flow has multiple node files
3. **Explicit State**: Shared store makes all state visible

## Implementation Guidelines

### Directory Structure

```
src/pflow/
├── flows/              # PocketFlow-based orchestration
│   ├── planner/        # Natural language workflow generation
│   ├── compiler/       # IR to PocketFlow compilation
│   ├── shell/          # Shell integration
│   ├── approval/       # User approval and storage
│   ├── execution/      # Named workflow execution
│   └── tracing/        # Execution monitoring
├── core/               # Traditional code
├── nodes/              # Platform nodes
└── cli/                # Entry points
```

### Decision Criteria

Use PocketFlow when the component has:
- Multiple discrete steps with data flow
- External dependencies that might fail
- Multiple execution paths
- State that accumulates
- Retry/fallback requirements
- Benefits from visual flow representation

Use traditional code when:
- Pure computation with no external dependencies
- Single-purpose utilities
- Performance-critical inner loops
- Simple data structures

## References

_Note: The detailed analysis documents referenced here were part of the decision-making process but have been consolidated into this ADR._

## Notes

This decision was made after extensive analysis comparing PocketFlow and traditional implementations for each task. The key insight was recognizing that PocketFlow is not a heavy framework but a lightweight pattern that makes unreliable operations reliable - exactly what pflow's internal operations need.

## Comments

Honest Assessment: Is PocketFlow for Internal Use Actually Good?

  The Real Benefits (Not Hype)

  1. Retry logic is genuinely useful
    - Writing manual retry loops is tedious and error-prone
    - PocketFlow's 8-line retry implementation is simple and works
    - For operations like dynamic imports or API calls, this is a real win
  2. The overhead is truly minimal
    - It's literally 100 lines of code
    - Just method calls and a while loop
    - No serialization, no framework magic
  3. Testing isolated nodes is easier
    - Each node can be tested independently
    - Mocking is straightforward with the shared dict

  The Real Drawbacks

  1. It's different from what most Python developers expect
    - New developers need to learn the pattern
    - Debugging through the flow orchestration adds a layer
    - Stack traces are less direct
  2. Simple operations do feel over-engineered
  # This feels silly for a simple operation
  class LoadFileNode(Node):
      def exec(self, shared):
          with open(shared["path"]) as f:
              shared["content"] = f.read()
          return "next"
  3. The visual flow benefit is overstated
    - load >> validate >> compile looks nice
    - But modern IDEs can show call graphs anyway
    - The benefit is marginal for understanding
  4. We might be drinking our own Kool-Aid
    - Using PocketFlow because we're building for PocketFlow
    - Risk of hammer-nail syndrome

  The Realistic Middle Ground

  Where it actually makes sense:
  - Task 17 (LLM Planner): Multiple retry strategies, complex branching
  - Task 8 (Shell Integration): Genuinely complex I/O with timeouts
  - Maybe Task 4 (Compiler): The retry on imports is useful

  Where it's questionable:
  - Task 20 (Approval): User interaction doesn't really need this
  - Task 22 (Execution): Could be a simple function with try/catch
  - Task 23 (Tracing): Observability could be middleware/decorators

  The Uncomfortable Truth

  1. We could build pflow without PocketFlow internally
    - Good error handling libraries exist (tenacity, retrying)
    - Middleware patterns work well for cross-cutting concerns
    - Traditional code would be more familiar to contributors
  2. The main argument is philosophical
    - "Eating our own dog food"
    - Proving the pattern works
    - But this isn't necessarily a technical win
  3. The 6 tasks might be too many
    - Starting with 2-3 would be more prudent
    - See how it goes before committing to all 6

  My Honest Recommendation

  Scale it back:
  1. Use PocketFlow for Task 17 (LLM Planner) - This genuinely benefits from the retry/branching
  2. Maybe Task 8 (Shell Integration) - Complex I/O handling
  3. Keep everything else traditional for now
  4. Revisit after implementing these two

  Why:
  - Less cognitive overhead for developers
  - Prove the value incrementally
  - Easier to change direction if needed
  - Focus PocketFlow where it truly shines

  The Bottom Line

  PocketFlow for internal orchestration isn't bad, but I oversold it. It's a decent pattern that
  helps with specific problems (retry logic, complex branching), but it's not revolutionary. The
  honest take is:

  - Good for: Complex orchestrations with lots of I/O and branching
  - Unnecessary for: Most of pflow's internals
  - Real benefit: Mainly the retry mechanism and testing isolation
  - Real cost: Different pattern that developers need to learn
