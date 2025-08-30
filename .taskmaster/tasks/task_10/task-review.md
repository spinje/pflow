# Task 10 Review: Create Registry CLI Commands

## Executive Summary

Implemented comprehensive registry CLI commands (`pflow registry list|describe|search|scan`) that replaced a temporary script with proper zero-setup auto-discovery, safe user node management, and hierarchical display. The implementation revealed critical architectural constraints around Registry's destructive saves, CLI routing limitations, and user node execution requirements that shaped the final design.

## Implementation Overview

### What Was Built

Created a complete registry CLI system with four commands that auto-discovers core nodes on first use, eliminating manual setup. Added intelligent search with scoring, security-conscious user node scanning, and enhanced grouped display that organizes nodes hierarchically by package/server.

**Major deviations from spec:**
- Enhanced display with package grouping (not in original spec but user-requested)
- Smart name resolution for simplified MCP names (e.g., `slack-add-reaction` resolves to `mcp-slack-slack_add_reaction`)
- User node Interface format enforcement (discovered requirement during implementation)

### Implementation Approach

Followed MCP CLI pattern exactly for routing, used Registry class enhancement rather than wrapper, implemented auto-discovery as lazy-loading pattern on first `load()` call. Chose in-place Registry modification over separate abstraction layer to minimize complexity.

## Files Modified/Created

### Core Changes
- `src/pflow/registry/registry.py` - Added search(), _auto_discover_core_nodes(), scan_user_nodes(), _save_with_metadata(), caching
- `src/pflow/cli/registry.py` - New file with complete CLI command group implementation
- `src/pflow/cli/main_wrapper.py` - Added registry routing using sys.argv manipulation hack
- `src/pflow/cli/main.py` - Updated help text to mention registry commands
- `src/pflow/runtime/compiler.py` - Fixed user node import using importlib.util.spec_from_file_location()

### Test Files
- `tests/test_cli/test_registry_cli.py` - 47 comprehensive tests covering all commands and edge cases
- Critical tests: auto-discovery trigger, search scoring accuracy, security warning display, routing verification

## Integration Points & Dependencies

### Incoming Dependencies
- CLI main → Registry commands (via main_wrapper.py routing)
- Compiler → Registry (for node type lookup and metadata)
- Planner → Registry (for available nodes discovery)
- Context Builder → Registry (for workflow validation)

### Outgoing Dependencies
- Registry → Scanner (for node discovery)
- Registry → MetadataExtractor (for Interface parsing)
- Registry commands → Registry class (core functionality)
- Registry → File system (~/.pflow/registry.json)

### Shared Store Keys
None directly - registry operates at system level, not workflow level.

## Architectural Decisions & Tradeoffs

### Key Decisions

**Auto-discovery on first load** → Zero setup friction → Alternative: explicit init command (rejected for UX)

**Registry.save() remains destructive** → Simple atomic operations → Alternative: merge/update logic (rejected for complexity)

**sys.argv manipulation for routing** → Works with catch-all args → Alternative: Click subcommands (impossible with current architecture)

**Type detection by convention** → Simple and reliable → Alternative: metadata field (rejected for backward compatibility)

**Single Interface format enforcement** → Consistency across all nodes → Alternative: multiple format support (rejected after user node issues)

### Technical Debt Incurred

- CLI routing hack is fragile if Click changes behavior
- Search is O(n) - acceptable for <1000 nodes but needs vector search later
- No version checking beyond placeholder - post-MVP requirement
- Registry file has no migration path - breaking changes require manual reset

## Testing Implementation

### Test Strategy Applied

Used Click's CliRunner with mocked Registry to avoid file I/O. Focused on user-visible behavior over internal implementation. Created separate tests for each of 19 spec requirements plus edge cases.

### Critical Test Cases
- `test_list_first_time_creates_registry` - Validates auto-discovery trigger
- `test_search_exact_match_scores_100` - Ensures search ranking works
- `test_scan_valid_path_shows_security_warning` - Security enforcement
- `test_main_wrapper_routes_registry_to_registry_group` - Routing verification
- `test_corrupted_registry_returns_empty_dict` - Recovery behavior

## Unexpected Discoveries

### Gotchas Encountered

**Registry.save() is completely destructive** - Overwrites entire file, no merge logic. Must always load→modify→save complete data or lose everything.

**Scanner returns list, Registry expects dict** - Required conversion in update_from_scanner() with last-wins behavior for duplicates.

**Interface must be in CLASS docstring** - MetadataExtractor ignores module docstring entirely. User nodes failed until this was discovered.

**Stdin stored as JSON string** - Not parsed dict, requires `json.loads(shared["stdin"])` in user nodes.

**MCP nodes use virtual paths** - Detection requires checking for "virtual://mcp" or "mcp-" prefix, not real file paths.

### Edge Cases Found

- First-time users have no registry.json - auto-discovery must handle gracefully
- Corrupted registry files - return empty dict and log warning
- User nodes not in Python path - compiler needs special import logic
- Duplicate node names in scan - last-wins with warning
- Empty search queries - return empty results, don't crash

## Patterns Established

### Reusable Patterns

**Lazy initialization pattern:**
```python
def load(self):
    if not self.registry_path.exists():
        self._auto_discover_core_nodes()
    return self._load_from_file()
```

**CLI routing pattern for catch-all args:**
```python
if first_arg == "registry":
    original_argv = sys.argv[:]
    try:
        registry_index = sys.argv.index("registry")
        sys.argv = [sys.argv[0]] + sys.argv[registry_index + 1:]
        registry()
    finally:
        sys.argv = original_argv
```

**Type detection by path/naming:**
```python
if name.startswith("mcp-"):
    return "mcp"
elif "/src/pflow/nodes/" in file_path:
    return "core"
else:
    return "user"
```

### Anti-Patterns to Avoid

- Don't try normal Click subcommands with workflow catch-all args
- Don't call Registry.save() with partial data - it's destructive
- Don't support multiple Interface formats - enforce one standard
- Don't skip security warnings for user nodes - show every time

## Breaking Changes

### API/Interface Changes
None - Registry class enhanced backward-compatibly.

### Behavioral Changes
- Registry auto-discovers on first access (previously required manual population)
- `populate_registry.py` script removed - use `pflow registry list` instead

## Future Considerations

### Extension Points
- Search method ready for vector similarity upgrade
- Version checking stub ready for implementation
- Registry metadata structure supports future fields

### Scalability Concerns
- O(n) search needs optimization for >1000 nodes
- File-based registry needs database for concurrent access
- No pagination in list command for large registries

## AI Agent Guidance

### Quick Start for Related Tasks

**Key files to read first:**
1. `src/pflow/cli/mcp.py` - Exact pattern to copy for new CLI groups
2. `src/pflow/cli/main_wrapper.py` - How routing works
3. `src/pflow/registry/registry.py` - Current Registry capabilities

**Patterns to follow:**
- Use MCP CLI pattern exactly for new command groups
- Always check if Registry file exists before operations
- Load complete registry → modify → save complete (never partial)
- Put Interface in class docstring for metadata extraction

### Common Pitfalls

1. **Trying to use Click normally** - Won't work with catch-all workflow args, must use sys.argv hack
2. **Calling save() without load()** - Will lose entire registry
3. **Assuming Registry merges** - It doesn't, complete replacement only
4. **Module vs class docstring** - Interface MUST be in class docstring
5. **Forgetting user node imports** - Compiler needs special handling for file_path imports
6. **Skipping security warnings** - Always show for user node operations

### Test-First Recommendations

When modifying registry:
1. Run `test_list_first_time_creates_registry` - Ensures auto-discovery works
2. Run `test_registry_marks_*_node_type` - Validates type detection
3. Run `test_main_wrapper_routes_*` - Confirms routing intact

When adding new commands:
1. Copy test structure from existing commands
2. Mock Registry to avoid file I/O
3. Test both human and JSON output modes
4. Include error cases and edge conditions

---

*Generated from implementation context of Task 10*