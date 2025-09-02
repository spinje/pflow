# Task 50 Review: Node Filtering System with Settings Management

## Executive Summary
Implemented a comprehensive node filtering system that hides test/dangerous nodes from users and the LLM planner by default, while allowing test environments to override via environment variable. The system filters nodes at load-time (not storage-time) through a settings file with allow/deny patterns.

## Implementation Overview

### What Was Built
Built a complete node filtering system with:
- `SettingsManager` class for managing allow/deny patterns via `~/.pflow/settings.json`
- Load-time filtering in `Registry.load()` (default behavior filters, `include_filtered=True` bypasses)
- Environment variable override `PFLOW_INCLUDE_TEST_NODES=true` for CI/testing
- CLI commands for settings management (`pflow settings allow/deny/check/show`)
- Protection against test nodes leaking to LLM context

**Major deviation from original plan**: Initially attempted filtering at discovery/save time, but shifted to load-time filtering after realizing this violated the "registry as complete catalog" principle.

### Implementation Approach
- **Filter at load, not storage**: Registry file maintains ALL nodes; filtering applied when loaded
- **Ephemeral overrides**: Environment variable never persists to settings file, and is re-applied on every load (starting from the file's base value) to prevent sticky state
- **Lazy loading**: Settings manager loaded on-demand to avoid circular imports
- **Pattern-based filtering**: Uses `fnmatch` for glob-style patterns
  - Matches are checked against node name, module path, file path, plus convenience aliases for MCP nodes (tool-only and `server.tool` forms)

## Files Modified/Created

### Core Changes
- `src/pflow/core/settings.py` - NEW: Complete settings management system with Pydantic models
- `src/pflow/registry/registry.py` - Modified `load()` to filter by default, added `include_filtered` parameter
- `src/pflow/cli/commands/settings.py` - NEW: CLI commands for settings management
- `src/pflow/cli/main_wrapper.py` - Added settings command routing
- `src/pflow/mcp/registrar.py` - Fixed to load unfiltered registry before saving
- `src/pflow/planning/context_builder.py` - Now receives filtered nodes automatically
- `src/pflow/planning/nodes.py` - Now receives filtered nodes automatically
- `tests/conftest.py` - Added `enable_test_nodes` fixture for test environment

### Test Files
- `tests/test_integration/test_settings_filtering.py` - NEW: Critical security tests
- `tests/test_registry/test_registry_filtering.py` - NEW: Core filtering mechanism tests
- `tests/test_cli/test_registry_cli.py` - Updated mock to support new filtering

## Integration Points & Dependencies

### Incoming Dependencies
- CLI commands -> SettingsManager (for user configuration)
- Registry -> SettingsManager (for filtering decisions)
- Planning/LLM -> Registry (receives filtered nodes)
- Tests -> Environment variable (via conftest.py fixture)

### Outgoing Dependencies
- SettingsManager -> filesystem (`~/.pflow/settings.json`)
- Registry -> SettingsManager (lazy loaded to avoid circular import)

### Shared Store Keys
None - this is a registry/configuration feature, not a node feature.

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **Load-time filtering** -> Preserves complete catalog, allows reversibility -> Rejected: storage-time filtering
2. **Lazy load SettingsManager** -> Avoids circular imports -> Alternative: dependency injection (too complex)
3. **Ephemeral env override** -> Never persists, purely runtime -> Rejected: mutating deny list
4. **Property for settings_manager** -> Clean lazy loading pattern -> Alternative: init-time loading (circular import)

### Technical Debt Incurred
- `_cached_nodes` in Registry is populated but never read (left for future optimization)
- Two save methods in Registry (`save()` vs `_save_with_metadata()`) cause format inconsistency
- Pattern matching checks multiple fields (`module_path`, `file_path`, `module`) due to inconsistent metadata

## Testing Implementation

### Test Strategy Applied
Focused on critical security paths rather than coverage:
- Denied nodes not leaking to LLM context
- Environment override working for CI
- Settings persistence safety

### Critical Test Cases
- `test_denied_nodes_not_in_llm_context` - Validates security boundary
- `test_env_var_overrides_settings` - Ensures CI can run tests
- `test_registry_load_respects_settings` - Core filtering mechanism

## Unexpected Discoveries

### Gotchas Encountered
1. **Circular import trap**: Registry imports from core, core.workflow_validator imports Registry
2. **Env override mutation bug**: Initial implementation modified deny list in memory, could persist
3. **MCP registrar bug**: Was saving filtered registry, permanently losing denied nodes
4. **Test node detection**: Name-based patterns needed for nodes without module paths

### Edge Cases Found
- `pflow settings check echo` showed wrong result with env override (fixed by name-pattern detection)
- Registry tests were inadvertently testing filtering instead of storage (fixed with `include_filtered=True`)

## Patterns Established

### Reusable Patterns
```python
# Lazy loading to avoid circular imports
@property
def settings_manager(self) -> Any:
    if self._settings_manager is None:
        from pflow.core.settings import SettingsManager
        self._settings_manager = SettingsManager()
    return self._settings_manager
```

```python
# Ephemeral override pattern
if settings.registry.include_test_nodes:
    # Check conditions but never mutate persisted state
    if is_test_node:
        return True
```

### Anti-Patterns to Avoid
- Don't filter at save/storage time - violates catalog completeness
- Don't mutate settings during override checks - causes persistence bugs
- Don't load filtered registry before mutations - causes data loss

## Breaking Changes

### API/Interface Changes
- `Registry.load()` now filters by default (breaking for code expecting all nodes)
- New parameter: `Registry.load(include_filtered=True)` to get unfiltered

### Behavioral Changes
- Test nodes now hidden from users by default
- LLM planner no longer sees test/denied nodes
- `pflow registry list` shows filtered view

## Future Considerations

### Extension Points
- Could add `pflow registry list --all` to show unfiltered
- Settings could support regex patterns (currently fnmatch only)
- Could add per-workflow node permissions

### Scalability Concerns
- Pattern matching is O(n*m) for n nodes and m patterns
- No caching of pattern match results (recomputed each load)

## User Guide: Node Filtering (Settings + Examples)

### Defaults
- Test nodes are hidden by default.
- The planner and `pflow registry list` use the filtered view.

### Managing settings
- Show current settings:
  - `pflow settings show`
- Add deny pattern:
  - `pflow settings deny "github-list-prs"`
  - `pflow settings deny "github-*"` (all GitHub core nodes)
  - `pflow settings deny "pflow.nodes.github.*"` (by module path)
  - `pflow settings deny "*/nodes/github/*"` (by file path)
- Remove a pattern:
  - `pflow settings remove "github-*" --deny`
- Reset to defaults:
  - `pflow settings reset`

### Testing patterns before applying
- Check if a node would be included (reports which patterns match considering name/module/file path and aliases):
  - Core node example: `pflow settings check github-list-prs`
  - MCP tool example: `pflow settings check mcp-slack-reply_to_thread`

### MCP-specific patterns (convenience aliases)
For MCP nodes named `mcp-{server}-{tool}` we also match:
- Tool-only (hyphens): e.g., `reply-to-thread`
- Server.tool alias: e.g., `slack.reply-to-thread`

Examples:
- Deny one Slack tool by tool-only name:
  - `pflow settings deny "reply-to-thread"`
- Deny one Slack tool by server.tool alias:
  - `pflow settings deny "slack.reply-to-thread"`
- Deny all Slack MCP tools:
  - `pflow settings deny "mcp-slack-*"`

### Test node override (CI/dev only)
- Hide test nodes explicitly:
  - `export PFLOW_INCLUDE_TEST_NODES=false`
- Include test nodes (CI/debugging):
  - `export PFLOW_INCLUDE_TEST_NODES=true`
- The override is ephemeral and never saved to `~/.pflow/settings.json`. It is re-applied on every load to avoid sticky state.

### Expected UX
- `pflow registry list` shows only allowed nodes/tools after your rules.
- `pflow settings check <name>` explains why a node/tool is included or excluded.

## AI Agent Guidance

### Quick Start for Related Tasks
1. Read `src/pflow/core/settings.py` first - it's the control center
2. Check `Registry.load()` in `src/pflow/registry/registry.py` - that's where filtering happens
3. Use `include_filtered=True` when you need ALL nodes (for mutations)
4. Always test with both `PFLOW_INCLUDE_TEST_NODES` set and unset

### Common Pitfalls
- **Circular import**: Never import Registry in core modules at module level
- **Filter before save**: Always load unfiltered (`include_filtered=True`) before saving
- **Env var persistence**: Never save `include_test_nodes` to settings file
- **Test contamination**: Always use the `enable_test_nodes` fixture in tests

### Test-First Recommendations
When modifying:
1. Run `tests/test_integration/test_settings_filtering.py` - catches security issues
2. Check `tests/test_registry/test_registry_filtering.py` - validates core mechanism
3. Verify with: `unset PFLOW_INCLUDE_TEST_NODES && pflow registry list | grep echo` (should be empty)

### Troubleshooting: Seeing test nodes in `pflow registry list`?

- PFLOW_INCLUDE_TEST_NODES is set in your shell
  - Check/unset:
    - `echo $PFLOW_INCLUDE_TEST_NODES`
    - `unset PFLOW_INCLUDE_TEST_NODES`
- Your settings file enables test nodes
  - Inspect/reset:
    - `uv run pflow settings show` (look for `registry.include_test_nodes: true`)
    - `uv run pflow settings reset`
- Deny patterns missing/incomplete
  - Ensure these exists (defaults now include them):
    - `uv run pflow settings deny "test.*"`
    - `uv run pflow settings deny "test-*"`
    - `uv run pflow settings deny "test_*"`
    - `uv run pflow settings deny "*/test/*"`
    - `uv run pflow settings deny "echo"`

---

*Generated from implementation context of Task 50*
*Session ID: f147252f-38da-4c69-8000-ca50e7f7f231*
*PR URL: https://github.com/spinje/pflow/pull/11*