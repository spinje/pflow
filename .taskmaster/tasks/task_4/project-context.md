# Project Context for Task 4: Implement IR-to-PocketFlow Object Converter

**File Location**: `.taskmaster/tasks/task_4/project-context.md`

*Created by sub-agents on: 2025-06-29*
*Purpose: Provide focused project understanding for ALL subtasks of this task*

## Task Domain Overview

Task 4 implements the core compiler that transforms JSON Intermediate Representation (IR) into executable pocketflow.Flow objects. This is the critical bridge between the planning/validation layer and the execution layer. The compiler takes validated JSON IR (from Task 6) and uses the node registry (from Task 5) to dynamically import and instantiate nodes, connecting them into a flow that pocketflow can execute.

This component is essential because it separates the declarative workflow description (JSON IR) from the imperative execution model (pocketflow objects), enabling workflows to be stored, validated, and reasoned about before execution.

## Relevant Components

### JSON IR Schema (Task 6)
- **Purpose**: Defines the structure and validation rules for workflow representation
- **Responsibilities**:
  - Schema validation via jsonschema
  - Business logic validation (node references, duplicate IDs)
  - Template variable support ($variable syntax)
- **Key Files**: `src/pflow/core/ir_schema.py`
- **How it works**: Provides `validate_ir()` function that ensures IR is well-formed before compilation

### Node Registry (Task 5)
- **Purpose**: Discovers and indexes available nodes with their metadata
- **Responsibilities**:
  - Filesystem scanning for BaseNode subclasses
  - Metadata extraction (module path, class name, docstring)
  - Persistent storage in `~/.pflow/registry.json`
- **Key Files**: `src/pflow/registry/scanner.py`, `src/pflow/registry/__init__.py`
- **How it works**: Registry provides metadata ONLY - module paths and class names, NOT class references. Components must use dynamic imports.

### PocketFlow Framework
- **Purpose**: The underlying execution engine that pflow extends
- **Responsibilities**:
  - Node lifecycle management (prep→exec→post)
  - Flow orchestration via `>>` operator
  - Action-based routing via `-` operator
  - Built-in retry mechanism
- **Key Files**: `pocketflow/__init__.py`
- **How it works**: Provides BaseNode/Node classes and Flow class that handles all execution orchestration

## Core Concepts

### Dynamic Import Pattern
- **Definition**: Using `importlib.import_module()` to load node classes at runtime based on registry metadata
- **Why it matters for this task**: The compiler cannot have static imports of all nodes - it must load them dynamically based on what's in the IR
- **Key terminology**: module path, class name, dynamic loading, import errors

### IR-to-Object Mapping
- **Definition**: The process of converting declarative JSON structures into imperative Python objects
- **Why it matters for this task**: This is the core responsibility of the compiler
- **Relationships**:
  - IR nodes → pocketflow Node instances
  - IR edges → pocketflow `>>` connections
  - IR params → node.set_params() calls
  - IR actions → pocketflow `-` operator routing

### Shared Store Pattern
- **Definition**: Flow-scoped dictionary for inter-node communication
- **Why it matters for this task**: While the compiler doesn't directly manipulate the shared store, it must understand that nodes communicate through it
- **Key terminology**: natural interfaces (shared["key"]), proxy mappings (for incompatible interfaces)

## Architectural Context

### Where This Fits
The IR compiler sits at the boundary between the planning/validation layer and the execution layer:

```
User Input → CLI Parser → Planner → JSON IR → [IR Compiler] → pocketflow.Flow → Execution
                                         ↑
                                    Registry Metadata
```

The compiler is invoked after:
1. IR has been generated (either from CLI syntax or natural language planning)
2. IR has been validated by the schema validator
3. All node references have been verified to exist in the registry

### Data Flow
1. **Input**: Validated JSON IR + Registry instance
2. **Processing**:
   - Parse IR structure
   - For each node: lookup metadata, import module, get class, instantiate
   - For each edge: connect nodes using appropriate operators
   - Handle proxy mappings if specified
3. **Output**: Executable pocketflow.Flow object ready for runtime

### Dependencies
- **Upstream**:
  - IR Schema (provides validated input)
  - Registry (provides node metadata for dynamic imports)
- **Downstream**:
  - Runtime/Execution Engine (executes the compiled Flow)
  - CLI (invokes compiler as part of execution pipeline)

## Architectural Decision: Traditional Function Implementation

**Critical Decision (Made 2025-06-29)**: The IR compiler will be implemented using traditional Python functions, NOT as a PocketFlow orchestration. This was a deliberate architectural choice based on the analysis that the compiler is a straightforward transformation function that doesn't need the complexity of PocketFlow nodes and flows.

**Rationale**:
- The compiler is a simple IR → Flow transformation
- No retry logic needed (compilation either works or fails immediately)
- No async operations or external I/O
- Traditional functions are easier to test and debug
- Avoids meta-complexity of using PocketFlow to compile PocketFlow

**Implementation Approach**:
- Main function: `compile_ir_to_flow(ir_json, registry)`
- Helper functions for specific concerns (parsing, validation, import, wiring)
- Standard exception handling with CompilationError
- No Node/Flow abstractions for the compiler itself

## Constraints and Conventions

### Technical Constraints
- **No static node imports**: All nodes must be loaded dynamically via importlib
- **Registry provides metadata only**: Must use module path + class name, not class references
- **BaseNode inheritance required**: All nodes must inherit from pocketflow.BaseNode (or Node)
- **Error handling is critical**: Import failures, missing classes, and invalid nodes must have clear error messages
- **Traditional function approach**: The compiler itself uses traditional functions, not PocketFlow orchestration

### Project Conventions
- **Naming**: Node types use kebab-case (e.g., "read-file", "github-get-issue")
- **Patterns**: Direct use of pocketflow classes, no wrapper abstractions
- **Style**: Clear error messages with suggestions for fixing issues

### Design Decisions
- **Dynamic imports over static**: Enables extensibility and avoids circular dependencies
- **Metadata-driven compilation**: Separates discovery from execution
- **Direct pocketflow usage**: "Extend, don't wrap" principle from integration guide

## Applied Knowledge from Previous Tasks

### Relevant Patterns
- **Pattern: PocketFlow for Internal Orchestration** (from knowledge base)
  - Why relevant: While the compiler itself might be simple enough to not need PocketFlow internally, understanding this pattern helps appreciate why we're compiling TO PocketFlow objects
  - How to apply: Recognize that the output Flow objects will benefit from PocketFlow's retry logic and error handling
  - Example usage: The compiled flows get automatic retry capabilities from pocketflow.Node

- **Pattern: Layered Validation with Custom Business Logic** (from Task 6)
  - Why relevant: The compiler assumes IR has already been validated, but may need to add runtime validation
  - How to apply: Trust the IR validation but verify dynamic imports and class inheritance
  - Example usage: After importing a class, verify it actually inherits from BaseNode

### Known Pitfalls to Avoid
- **Pitfall: Over-engineering with wrapper classes**
  - Risk for this task: Temptation to create PflowNode or PflowFlow wrappers
  - Mitigation strategy: Use pocketflow classes directly as shown in integration guide
  - Warning signs: Any class that just inherits without adding functionality

- **Pitfall: Assuming registry contains class references**
  - Risk for this task: Trying to use registry data as classes directly
  - Mitigation strategy: Always use importlib with registry's module path and class name
  - Warning signs: AttributeError when trying to instantiate from registry data

### Architectural Constraints
- **Decision: Registry stores metadata only** (from Task 5)
  - Impact on this task: Must implement dynamic import logic
  - Required compliance: Use importlib.import_module() with error handling

## Decomposition Guidance
Based on accumulated knowledge:
- Consider structuring the compiler as a single main function with helper functions
- Separate concerns: IR parsing, node importing, flow building, error handling
- Ensure all subtasks handle ImportError and AttributeError with clear messages
- Follow the direct pocketflow usage pattern - no abstractions needed

## Key Documentation References

### Essential pflow Documentation
- `docs/architecture/pflow-pocketflow-integration-guide.md` - **Critical**: Shows exactly how to compile IR to Flow objects (see Critical Insight #7)
- `docs/core-concepts/schemas.md` - Defines the IR structure the compiler must understand
- `docs/core-concepts/registry.md` - Explains registry metadata format
- `docs/reference/execution-reference.md` - Shows how compiled flows will be executed

### PocketFlow Documentation (if applicable)
- `pocketflow/__init__.py` - The source of truth for BaseNode, Node, and Flow classes
- `pocketflow/docs/core_abstraction/flow.md` - How Flow orchestration works
- `pocketflow/docs/core_abstraction/node.md` - Node lifecycle and methods

*These references should be included in the decomposition plan to guide subtask generation.*

## Key Questions This Context Answers

1. **What am I building/modifying?** A compiler that converts JSON IR to executable pocketflow.Flow objects using dynamic imports from registry metadata

2. **How does it fit in the system?** It's the bridge between the declarative IR representation and the imperative pocketflow execution model

3. **What rules must I follow?**
   - Use dynamic imports with registry metadata
   - No wrapper classes - use pocketflow directly
   - Verify BaseNode inheritance
   - Handle all import errors gracefully

4. **What existing code should I study?**
   - The registry implementation to understand metadata format
   - The IR schema to understand input structure
   - The integration guide's compile_ir_to_flow example

## What This Document Does NOT Cover

- How to implement specific nodes (that's Task 11+)
- How to generate IR from user input (that's the planner's job)
- How to execute the compiled Flow (that's the runtime's job)
- Template variable resolution (happens at runtime, not compilation)

---

*This briefing was synthesized from project documentation to provide exactly the context needed for this task, without overwhelming detail.*

**Note**: This document is created ONCE at the task level and shared by ALL subtasks. It is created by the first subtask and read by all subsequent subtasks.
