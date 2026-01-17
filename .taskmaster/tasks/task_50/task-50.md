# Task 50: Implement Comprehensive Node Filtering System with Settings Management

## Description
Implement a flexible node filtering system that allows users to control which nodes are available through a settings.json configuration file with allow/deny patterns. The system hides test nodes from regular users by default while providing an environment variable override for testing. It supports filtering of all node types including MCP nodes, provides CLI commands for managing settings, and ensures denied nodes are completely hidden from the LLM/planner context. The filtering is applied at load-time to maintain reversibility while preserving all nodes in the registry.

## Status
done

## Completed
2025-08-31

## Dependencies
- Task 7: Extract node metadata from docstrings - The filtering system needs to identify nodes by their metadata
- Task 5: Node discovery and registry implementation - The filtering integrates with the registry's node discovery mechanism

## Priority
high

## Details
The implementation provides a two-tier filtering system that prevents test nodes from appearing in user-facing contexts while maintaining full test suite functionality:

### Core Implementation Components

1. **SettingsManager Class** (`src/pflow/core/settings.py`)
   - Manages `~/.pflow/settings.json` configuration file
   - Provides allow/deny pattern matching using fnmatch
   - Supports environment variable overrides (`PFLOW_INCLUDE_TEST_NODES`)
   - Default configuration denies: `test.*`, `test-*`, `test_*`, `*/test/*`, `echo`

2. **Registry Filtering** (`src/pflow/registry/registry.py`)
   - Modified `Registry.load()` to filter nodes by default
   - Added `include_filtered` parameter for bypassing filters when needed
   - Filtering happens at load time, not save time (preserves all nodes in registry.json)
   - Single point of filtering ensures consistency across all consumers

3. **MCP Node Support** (`src/pflow/mcp/registrar.py`)
   - MCP nodes respect the same filtering rules
   - Lazy-loaded SettingsManager to avoid circular imports
   - Filtered nodes are not registered when syncing MCP servers

4. **CLI Commands** (`src/pflow/cli/commands/settings.py`)
   - `pflow settings init` - Initialize settings file
   - `pflow settings show` - Display current settings
   - `pflow settings allow <pattern>` - Add allow pattern
   - `pflow settings deny <pattern>` - Add deny pattern
   - `pflow settings check <node>` - Test if a node would be included
   - `pflow settings remove <pattern>` - Remove patterns

5. **Test Environment Configuration** (`tests/conftest.py`)
   - Auto-applied fixture sets `PFLOW_INCLUDE_TEST_NODES=true` for all tests
   - Session-scoped to ensure test nodes are available throughout test runs
   - Restores original environment after tests complete

### Key Design Decisions

- **Filtering at Load Time**: Instead of removing nodes from the registry, we filter at `Registry.load()` time. This preserves reversibility and simplifies the architecture.
- **Environment Variable Priority**: `PFLOW_INCLUDE_TEST_NODES` overrides settings.json for CI/test scenarios
- **Lazy Loading**: SettingsManager is lazy-loaded to avoid circular import issues
- **Pattern Matching**: Uses fnmatch for flexible glob-style patterns
- **Single Source of Truth**: All filtering logic centralized in `Registry.load()`

### Critical Implementation Details

Based on code review and testing, several important safeguards were added:

1. **Ephemeral Environment Override**: The `include_test_nodes` field is stripped when saving settings to prevent the temporary test override from becoming permanent
2. **MCP Registry Integrity**: MCP registrar operations (`sync_server`, `remove_server_tools`) always load the unfiltered registry to avoid data loss
3. **Comprehensive Pattern Matching**: Filtering checks `file_path` in addition to `module_path` to support path-based patterns like `*/test/*`
4. **Error Handling**: Settings loading logs warnings when corrupted instead of failing silently
5. **Test Node Detection**: Enhanced to recognize nodes by name patterns (`test*`, `test-*`, `test_*`, `echo`) even without module information

### Integration Points

- Planning system automatically gets filtered nodes (LLM doesn't see denied nodes)
- CLI registry commands show only allowed nodes
- Workflow execution uses filtered node list
- Test suite bypasses filtering via environment variable

## Test Strategy
The implementation has been thoroughly tested with:

- **Unit Tests**: Modified registry CLI tests to handle new filtering behavior
- **Integration Tests**: All 1678 existing tests pass with test nodes enabled via environment variable
- **Focused Test Coverage**: Added specific tests for critical functionality:
  - `test_denied_nodes_not_in_llm_context`: Ensures security by verifying denied nodes don't leak to LLM
  - `test_env_var_overrides_settings`: Confirms test environment can access test nodes via env override
  - `test_registry_load_respects_settings`: Validates core filtering mechanism
  - `test_registry_list_nodes_uses_load_filtering`: Ensures consistent filtering delegation
- **Manual Testing**: Verified that:
  - Test nodes are hidden from `pflow registry list` by default
  - Test nodes appear when `PFLOW_INCLUDE_TEST_NODES=true`
  - Settings commands work correctly for managing patterns
  - Denied nodes don't appear in LLM/planner context
  - MCP nodes respect filtering rules
  - Environment override doesn't persist to settings file
- **CI Compatibility**: Environment variable approach ensures CI tests have access to test nodes
