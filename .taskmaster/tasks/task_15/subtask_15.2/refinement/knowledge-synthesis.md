# Knowledge Synthesis for 15.2

## Relevant Patterns from Previous Tasks

- **Registry Pattern for Loading**: [Task 15.1] - Registry's load() implementation provided template for workflow loading. This pattern of graceful error handling and fallback behavior can be applied to the planning context when checking for missing components.

- **Three-Layer Validation**: [Task 15.1] - Separate file operations, JSON parsing, and field validation. This layered approach can be used when validating selected components exist before building planning context.

- **Refactoring for Complexity**: [Task 15.1] - Breaking down large functions into smaller ones. The two-phase context functions should be designed with this in mind from the start.

- **Path Objects for Compatibility**: [Task 15.1] - Always use Path objects. This ensures cross-platform compatibility when working with workflow directories.

## Known Pitfalls to Avoid

- **Function Complexity Limits**: [Task 15.1] - Initial implementation exceeded complexity limits. Start with smaller, focused functions for each phase.

- **Parser Fragility**: [Task 14/Project Context] - The metadata extractor regex patterns are extremely fragile. One wrong change can break 20+ tests. DO NOT modify parser regex patterns.

- **Missing Component Handling**: [Ambiguities Doc] - Never skip missing components silently. This creates broken workflows. Always return error dict to enable retry.

## Established Conventions

- **Exclusive Params Pattern**: [Task 14/16] - Parameters that appear in Reads are filtered out of params display. This is non-negotiable and tests depend on it.

- **Empty Params Arrays**: [Task 14] - All migrated nodes expect empty params arrays when all params are fallbacks. Tests enforce this.

- **No Placeholders**: [Ambiguities Doc] - If a node/workflow lacks a description, omit it entirely rather than showing placeholder text.

- **Error Dict Format**: [Ambiguities Doc] - When components missing, return dict with specific keys: "error", "missing_nodes", "missing_workflows"

## Codebase Evolution Context

- **Workflow Loading Complete**: [Task 15.1 - Just Now] - `_load_saved_workflows()` is implemented and working. Returns list of dicts with workflow metadata. Creates directory if missing, skips invalid files gracefully.

- **All Nodes Migrated**: [Task 14] - All 7 nodes now use enhanced interface format. Structure parsing is fully implemented, not scaffolding.

- **Context Size Increased**: [Task 14.2] - MAX_OUTPUT_SIZE changed from 50KB to 200KB at user request for VERBOSE mode.

- **Build Context No Compatibility Needed**: [Ambiguities Doc] - Can refactor build_context() freely. Only tests use it, no production dependencies.

## Key Technical Details

- **Structure Parser Location**: Lines 543-612 in metadata_extractor.py - fully functional recursive parser
- **Existing Helper Methods**: _process_nodes(), _format_node_section(), _group_nodes_by_category() - all ready to reuse
- **Registry Access Pattern**: `from pflow.registry import get_registry; registry = get_registry()`
- **Workflow Check Pattern**: `any(w['name'] == workflow_name for w in saved_workflows)`
