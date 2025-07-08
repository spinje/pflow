# Knowledge Synthesis for 4.4

## Relevant Patterns from Previous Tasks
- **Module pattern**: Clean separation of __init__.py and implementation [Used in 4.1] - Essential for organizing test modules
- **Error namespace convention**: Consistent "compiler:" prefix [Used in 4.1] - Critical for error message clarity in integration tests
- **Structured logging with phases**: Using extra dict to track compilation phases [Used in 4.1] - Will help verify performance and execution flow
- **Dynamic import pattern**: importlib.import_module() + getattr() [Used in 4.2] - Integration tests must verify this works with real nodes
- **CompilationError with rich context**: Provides phase, node_id, suggestions [Used in all subtasks] - Must test error message quality
- **Three helper function pattern**: Clean separation of concerns [Used in 4.3] - Integration tests should verify each phase
- **MockNode with connection tracking**: Override operators to track flow construction [Used in 4.3] - Perfect for integration testing

## Known Pitfalls to Avoid
- **Logging field name conflicts**: "module" is reserved in LogRecord [Failed in 4.2] - Use "module_path" instead
- **Type safety with dynamic imports**: Need explicit casting for mypy [Found in 4.2] - Ensure tests handle type annotations
- **Exception chaining**: Modern Python expects explicit "from e" or "from None" [Found in 4.2] - Apply consistently
- **MockNode inheritance**: Must inherit from BaseNode for operator support [Critical from 4.3] - All test nodes must follow this
- **Empty params handling**: Ruff prefers get() over explicit checks [Found in 4.3] - Use Pythonic patterns
- **Field name mismatch**: IR uses source/target not from/to for edges [Critical from 4.3 handoff] - Integration tests MUST use correct fields

## Established Conventions
- **Traditional function approach**: Compiler uses functions, not PocketFlow orchestration [Decided in Task 4] - Must test as functions
- **Direct PocketFlow usage**: No wrapper abstractions [Architecture decision] - Test with real PocketFlow classes
- **Phase-based error handling**: Each phase has distinct error context [Established in 4.3] - Verify in integration tests
- **Test-as-you-go strategy**: Create tests alongside implementation [Project standard] - Already applied by siblings
- **100% coverage standard**: All siblings achieved full coverage [Proven achievable] - Must maintain

## Codebase Evolution Context
- **Foundation laid (4.1)**: CompilationError, basic structure, parsing, validation - All ready to use
- **Dynamic imports added (4.2)**: import_node_class function with full error handling - Core functionality for integration
- **Flow construction completed (4.3)**: All helper functions implemented, ready for testing - The main logic to integrate
- **Old tests updated**: Tests expecting NotImplementedError now expect CompilationError [Changed in 4.3] - Build on updated foundation

## Integration Test Focus Areas
Based on sibling implementations:
1. **End-to-end compilation**: Test complete IR → Flow transformation
2. **Real registry integration**: Verify with actual node discovery from Task 5
3. **Performance benchmarking**: <100ms target for 5-10 node workflows
4. **Error message quality**: Must include actionable suggestions
5. **Edge cases from all phases**: Missing nodes, import failures, wiring errors
6. **Template variable handling**: Verify $variables pass through unchanged
