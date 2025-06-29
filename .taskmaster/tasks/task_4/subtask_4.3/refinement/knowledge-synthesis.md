# Knowledge Synthesis for 4.3

## Relevant Patterns from Previous Tasks

- **Module pattern from Task 1**: Clean separation of __init__.py and implementation - [Used in Task 4.1] - Keep main logic in compiler.py, expose only public interface
- **Structured logging pattern**: Using extra dict for context - [Used in Task 4.1, 4.2] - Track compilation phases with extra={"phase": "..."}
- **Dynamic import pattern**: importlib.import_module() + getattr() - [Used in Task 4.2] - Standard approach for loading node classes
- **CompilationError with rich context**: Provides phase, node_id, details, suggestions - [Used in Task 4.1, 4.2] - Continue this pattern for flow construction errors
- **Type annotations for dynamic imports**: Use cast() after runtime validation - [From Task 4.2] - Will need for node class references

## Known Pitfalls to Avoid

- **Logging field name conflicts**: Reserved fields like "module", "filename", "funcName" - [From Task 4.2] - Never use these in extra dict
- **Exception chaining**: Always use `from e` or `from None` when re-raising - [From Task 4.2] - Important for CompilationError raising
- **Mock imports in tests**: Avoid real dependencies - [From Task 4.2] - Test with mock nodes, not real node implementations

## Established Conventions

- **Error namespace**: "compiler:" prefix for all errors - [From Task 4.1] - Must follow
- **Phase tracking in logs**: Use extra={"phase": "..."} for all debug logs - [From Task 4.1, 4.2] - Continue for flow construction phases
- **Traditional function approach**: No PocketFlow nodes for compiler - [From project context] - Keep using helper functions, not nodes
- **Test-as-you-go**: Create tests alongside implementation - [From CLAUDE.md] - Must create test_flow_construction.py

## Codebase Evolution Context

- **Foundation laid**: Task 4.1 created error handling and basic structure - [Completed] - Build on established CompilationError
- **Import capability added**: Task 4.2 added import_node_class() function - [Completed] - Use this to get node classes from registry
- **Current state**: Have parsing, validation, and import - ready for flow construction - [Now] - This subtask adds the final piece
- **Next step**: Task 4.4 will add execution preparation - [Future] - Keep interfaces clean for this
