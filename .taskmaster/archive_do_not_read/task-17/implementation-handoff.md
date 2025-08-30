# Task 17 Implementation Handoff Memo

## Context and Current State

This memo documents the complete research phase findings for Task 17 (Natural Language to IR Planner) implementation. The pflow project has established key foundations that Task 17 will build upon:

### Completed Components

1. **JSON IR Schema** (Task 6): Fully implemented in `src/pflow/core/ir_schema.py`
   - Pydantic-style validation with `validate_ir()`
   - Custom `ValidationError` with helpful messages
   - Business logic validation (node references, duplicate IDs)

2. **IR to PocketFlow Compiler** (Task 4): Complete in `src/pflow/runtime/compiler.py`
   - `compile_ir_to_flow(ir_json, registry) -> Flow`
   - Dynamic node import from registry
   - Rich error handling with compilation phases

3. **Node Discovery System** (Task 5): Operational in `src/pflow/registry/`
   - Scanner finds BaseNode subclasses via filesystem
   - Registry persists to `~/.pflow/registry.json`
   - Automatic node naming (explicit or kebab-case)

4. **Simple Platform Nodes**: File manipulation nodes implemented
   - ReadFileNode, WriteFileNode, CopyFileNode, etc.
   - Clear shared store interface pattern
   - Comprehensive error handling

5. **CLI Foundation**: Basic structure in `src/pflow/cli/main.py`
   - Collects raw input from args/stdin/file
   - Stores in context for planner consumption
   - Ready for planner integration

### Key Integration Points

1. **Registry Access**:
   ```python
   from pflow.registry import Registry
   registry = Registry()
   available_nodes = registry.load()  # Dict[str, metadata]
   ```

2. **IR Validation**:
   ```python
   from pflow.core import validate_ir
   validate_ir(ir_dict)  # Raises ValidationError with details
   ```

3. **Compilation**:
   ```python
   from pflow.runtime import compile_ir_to_flow
   flow = compile_ir_to_flow(ir_dict, registry)
   ```

4. **CLI Context**:
   - Raw input available in `ctx.obj["raw_input"]`
   - Input source in `ctx.obj["input_source"]`

## Task 3 Requirements Summary

### Core Functionality
1. Parse natural language or CLI syntax input
2. Identify required nodes and parameters
3. Generate valid JSON IR
4. Support both natural language and explicit CLI syntax

### Key Decisions Needed
1. LLM integration approach (llm library vs direct API)
2. Prompt engineering strategy
3. Error recovery mechanisms
4. Syntax detection heuristics

### Technical Constraints
- Must use shared store pattern for node communication
- Node types must exist in registry
- Generated IR must pass validation
- Should provide helpful error messages

## Recommended Implementation Approach

### 1. Module Structure
```
src/pflow/planner/
├── __init__.py          # Export plan_workflow
├── planner.py           # Main planner logic
├── syntax_detector.py   # Detect input type
├── cli_parser.py        # Parse CLI syntax
├── nl_planner.py        # Natural language planning
└── prompts.py           # LLM prompts
```

### 2. Core Flow
```python
def plan_workflow(raw_input: str, registry: Registry) -> dict[str, Any]:
    """Convert raw input to validated IR."""
    # 1. Detect syntax type
    if is_cli_syntax(raw_input):
        ir = parse_cli_syntax(raw_input, registry)
    else:
        ir = plan_with_llm(raw_input, registry)

    # 2. Validate
    validate_ir(ir)

    return ir
```

### 3. CLI Syntax Parser
- Split on `=>` operator
- Parse node commands with click-style parsing
- Extract parameters from flags
- Build IR structure

### 4. Natural Language Planner
- Use available nodes from registry
- Structured prompt with examples
- JSON extraction from LLM response
- Fallback/retry on failures

### 5. Integration with CLI
```python
# In cli/main.py after collecting input:
from pflow.planner import plan_workflow
from pflow.runtime import compile_ir_to_flow

ir = plan_workflow(ctx.obj["raw_input"], registry)
flow = compile_ir_to_flow(ir, registry)
flow.run()
```

## Critical Patterns to Follow

### 1. Shared Store Usage
Nodes communicate via shared store, not parameters:
```json
{
  "nodes": [
    {"id": "read", "type": "read-file", "params": {"file_path": "data.txt"}},
    {"id": "proc", "type": "llm", "params": {"prompt": "Summarize"}}
  ],
  "edges": [{"from": "read", "to": "proc"}]
}
```
The read-file node writes to `shared["content"]`, which llm reads.

### 2. Error Handling Pattern
```python
try:
    # Operation
except SpecificError as e:
    logger.error("Context", extra={"phase": "planning", ...})
    raise PlanningError("User message", suggestion="...") from e
```

### 3. Registry-Driven Design
Always check registry for valid node types and suggest alternatives on errors.

## Testing Strategy

1. **Unit Tests**:
   - Syntax detection accuracy
   - CLI parser edge cases
   - Prompt generation
   - IR building logic

2. **Integration Tests**:
   - End-to-end planning scenarios
   - Registry integration
   - Validation pass/fail cases

3. **Example Workflows**:
   - Simple: "read file.txt"
   - Chain: "read data.csv and summarize it"
   - CLI: "read-file --path=data.txt => llm --prompt='Extract names'"

## Next Steps

1. Review and finalize LLM integration approach
2. Implement syntax detector
3. Build CLI parser
4. Create natural language planner
5. Integrate with main CLI
6. Add comprehensive tests

## References

- Task 3 specification: `architecture/features/planner.md`
- IR Schema: `src/pflow/core/ir_schema.py`
- Compiler: `src/pflow/runtime/compiler.py`
- Registry: `src/pflow/registry/`
- Node examples: `src/pflow/nodes/file/`
