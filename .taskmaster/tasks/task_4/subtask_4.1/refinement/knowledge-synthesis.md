# Knowledge Synthesis for Subtask 4.1

## Relevant Patterns from Previous Tasks

### Python Package Module Pattern (Task 1)
- **Pattern**: Separate __init__.py for exports and main.py for implementation
- **Where used**: CLI module structure
- **Why relevant**: Same pattern applies to compiler module - clean separation of concerns

### Error Namespace Convention (Task 2)
- **Pattern**: Prefix errors with module namespace (e.g., "cli: error message")
- **Where used**: All CLI errors
- **Why relevant**: CompilationError should follow same pattern with "compiler:" prefix

### Context Manager for Dynamic Imports (Task 5)
- **Pattern**: Use context managers to temporarily modify sys.path
- **Where used**: Scanner dynamic imports
- **Why relevant**: Task 4 will eventually need same pattern for node imports (though not in 4.1)

### Layered Validation Pattern (Task 6)
- **Pattern**: Separate structural validation (schema) from business logic validation
- **Where used**: JSON Schema vs custom validators
- **Why relevant**: Compiler assumes IR is pre-validated but should verify basic structure

### Test-Driven Foundation (All Tasks)
- **Pattern**: Create tests alongside implementation, not after
- **Where used**: Every successful subtask
- **Why relevant**: Must create tests/test_compiler_foundation.py with comprehensive coverage

## Known Pitfalls to Avoid

### Over-Engineering Early (Task 5)
- **Pitfall**: Creating complex fixture systems before needed
- **Where it failed**: Initial test fixture approach was abandoned
- **How to avoid**: Start simple with foundation, add complexity only when required

### Missing Error Context (General)
- **Pitfall**: Generic error messages without context
- **Where it failed**: Early versions lacked helpful debugging info
- **How to avoid**: CompilationError must include node_id, node_type from the start

### Incomplete Type Handling (Task 6)
- **Pitfall**: Only handling one input type
- **Where it failed**: Initial schema only handled dicts
- **How to avoid**: Support both dict and JSON string inputs from the beginning

## Established Conventions

### Module Organization (Project-wide)
- **Convention**: src/pflow/<module>/__init__.py structure
- **Where decided**: Task 1
- **Must follow**: Create src/pflow/runtime/ directory structure

### Error Class Design (Project-wide)
- **Convention**: Custom exceptions with rich context attributes
- **Where decided**: Implied by project standards
- **Must follow**: CompilationError as proper exception class, not just string

### Logging Structure (Implied)
- **Convention**: Structured logging for debugging
- **Where decided**: Architecture docs mention logging
- **Must follow**: Use Python logging module, not print statements

### Test Naming (Project-wide)
- **Convention**: test_<module>_<aspect>.py pattern
- **Where decided**: Established in Tasks 1-6
- **Must follow**: tests/test_compiler_foundation.py

## Codebase Evolution Context

### Registry Format Established (Task 5)
- **What changed**: Registry stores metadata only, not class references
- **When**: Task 5 completion
- **Impact**: Compiler will receive registry instance with clean metadata

### IR Schema Solidified (Task 6)
- **What changed**: Final IR structure with nodes array, edges, metadata
- **When**: Task 6 completion
- **Impact**: Compiler knows exact structure to expect

### Direct Execution Pattern (Task 2)
- **What changed**: No 'run' subcommand, direct workflow execution
- **When**: Task 2 refactoring
- **Impact**: Compiler will be invoked directly from CLI main flow

### Traditional Function Approach Selected (Task 4 Decision)
- **What changed**: Use simple function, not PocketFlow orchestration
- **When**: User decision on Task 4 approach
- **Impact**: Create straightforward compile_ir_to_flow() function
