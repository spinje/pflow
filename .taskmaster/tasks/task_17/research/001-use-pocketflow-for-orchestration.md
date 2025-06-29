# ADR-001: Use PocketFlow for Natural Language Planning Only

Date: 2025-06-29 (Revised: 2025-06-29)

## Status

Accepted (Revised)

## Context

pflow is a workflow compiler that transforms natural language and CLI syntax into executable workflows using the PocketFlow framework. During development, we faced an architectural decision: should we use PocketFlow internally to build pflow itself, or use traditional imperative Python code?

Initial analysis suggested using PocketFlow for 6 internal tasks. However, further reflection revealed that only the natural language planner (Task 17) has the complex orchestration patterns that genuinely benefit from PocketFlow.

### Key Observations

1. **PocketFlow is minimal**: The entire framework is ~100 lines of Python code
2. **Only the planner has complex orchestration**: Multiple LLM retries, self-correcting loops, branching logic
3. **Other tasks are straightforward**: Simple I/O, linear execution, basic error handling
4. **Risk of over-engineering**: Using PocketFlow everywhere violates "simplicity first" principle

## Decision

Use PocketFlow ONLY for the Natural Language Planner (Task 17), which has genuine complex orchestration needs. All other components use traditional Python patterns.

### Component Using PocketFlow

**LLM Workflow Generation** (Task 17)
- Parse input → Call LLM → Validate → Retry on errors
- Self-correcting loops with multiple retry strategies
- Complex branching based on LLM responses
- Progressive enhancement of generated workflows
- Multiple fallback paths for different error types

This is the ONLY component that truly benefits from PocketFlow's orchestration capabilities.

### Components Using Traditional Code

ALL other components use traditional Python patterns:
- **IR Compiler (Task 4)**: Simple JSON loading and module imports
- **Shell Integration (Task 8)**: Linear stdin processing
- **Approval System (Task 20)**: Basic user interaction
- **Workflow Execution (Task 22)**: Straightforward flow running
- **Execution Tracing (Task 23)**: Output formatting and capture
- Pure utilities (validators, formatters)
- Data structures (schemas, registries)
- Simple CLI commands
- Platform nodes (already inherit from BaseNode)

## Consequences

### Positive

1. **Focused Complexity**: PocketFlow used only where it adds real value
2. **Lower Learning Curve**: Most developers work with familiar patterns
3. **Simplified Architecture**: Fewer abstraction layers
4. **Planner Reliability**: The one complex component gets retry/fallback benefits
5. **Easier Debugging**: Most code has direct stack traces
6. **Selective Dogfooding**: We validate PocketFlow for its best use case

### Negative

1. **Manual Retry Logic**: Other components need explicit error handling
2. **Less Consistency**: Two different patterns in the codebase
3. **Potential Duplication**: Some retry patterns might be reimplemented

### Neutral

1. **Hybrid Approach**: Mix of traditional and flow-based code
2. **Clear Boundaries**: Only the planner uses PocketFlow
3. **Documentation Needs**: Must explain why planner is different

## Implementation Guidelines

### Directory Structure

```
src/pflow/
├── flows/              # PocketFlow-based orchestration
│   └── planner/        # Natural language workflow generation (ONLY)
├── core/               # Traditional code (most components)
├── runtime/            # Traditional runtime components
│   ├── compiler.py     # IR compilation
│   ├── shell.py        # Shell integration
│   └── tracing.py      # Execution monitoring
├── planning/           # Traditional planning components
│   └── approval.py     # User approval
├── nodes/              # Platform nodes
└── cli/                # Entry points
```

### Decision Criteria

Use PocketFlow when the component has:
- Complex retry strategies with multiple approaches
- Self-correcting loops (e.g., LLM validation)
- Genuinely complex branching logic
- Multiple interdependent external API calls
- Benefits from visual flow representation

Use traditional code for:
- Everything else
- Simple I/O operations
- Linear execution flows
- Basic error handling
- User interactions
- Pure computations

## References

_Note: The detailed analysis documents referenced here were part of the decision-making process but have been consolidated into this ADR._

## Notes

This decision was revised after recognizing that only the natural language planner has the complex orchestration patterns that genuinely benefit from PocketFlow. Using it for simpler tasks would violate our "simplicity first" principle and add unnecessary cognitive overhead.

The planner's complexity justifies PocketFlow:
- Multiple LLM API calls with different prompts
- Self-correcting validation loops
- Retry with progressive prompt enhancement
- Fallback strategies for different failure modes
- Complex state accumulation across attempts

Other tasks are straightforward enough that traditional Python code with good error handling is clearer and simpler.
