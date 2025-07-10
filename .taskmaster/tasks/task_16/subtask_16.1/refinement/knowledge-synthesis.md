# Knowledge Synthesis for Subtask 16.1

## Relevant Patterns from Previous Tasks

- **Phased Implementation**: Task 7 (metadata extraction) - Break complex processing into clear phases for easier debugging
- **Defensive Metadata Handling**: Task 7 - Graceful degradation when metadata is incomplete or malformed
- **Dynamic Import Pattern**: Task 5 (registry) - Use `import_node_class()` from runtime.compiler for safe imports
- **Component-Specific Logging**: Task 7 - Use prefixes like "context:" for clear error tracking
- **Truthiness-Safe Parameter Handling**: Task 11 (file nodes) - Handle empty strings and None values correctly

## Known Pitfalls to Avoid

- **Registry Field Names**: Registry has "docstring" not "description" - Don't confuse with metadata extractor output
- **Import Failures**: Many nodes may fail to import during development - Log and skip, don't crash
- **Test Node Pollution**: Test nodes exist in registry - Filter them out based on file paths
- **Parameter Redundancy**: ALL inputs can also be params - Must filter to show only exclusive params

## Established Conventions

- **Shared Store Pattern**: ALL nodes use `shared.get(key) or self.params.get(key)` - Critical for parameter filtering
- **Function Signature**: `build_context(registry_metadata: dict[str, dict[str, Any]]) -> str` - Parameter name is registry_metadata
- **Markdown Output**: Simple, clean markdown for LLM consumption - Not JSON or complex formats
- **Error Handling**: Log warnings but continue processing - Never fail entire context build for one bad node

## Codebase Evolution Context

- **Registry System**: Task 5 established registry format with module, class_name, name, docstring fields
- **Metadata Extraction**: Task 7 created structured extraction of inputs, outputs, params, actions
- **Shared Store Pattern**: Core pflow design - Data flows through shared store, params are fallbacks
- **Planning System**: Task 16 creates context, Task 17 will consume it for 95% success rate target

## Critical Implementation Details

- **The Exclusive Parameters Pattern**: This is THE key insight - filter params that are also inputs
- **Import Pattern**: Must use `import_node_class()` from runtime.compiler, not direct imports
- **Directory Creation**: `src/pflow/planning/` doesn't exist yet - need to create with `__init__.py`
- **Impact on Success Rate**: Format directly impacts whether Task 17's planner achieves 95% success rate

## Integration Points

- **Input**: Registry dict from `Registry.load()`
- **Processing**: Use `PflowMetadataExtractor` to get structured metadata
- **Output**: Markdown text for LLM consumption by Task 17's planner
