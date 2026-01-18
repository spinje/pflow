# Node Filtering System

## Overview

The node filtering system allows users to control which nodes are available in pflow through a settings file and environment variables. This provides security (hiding dangerous operations), customization (per-user preferences), and testing support (enabling test nodes in CI).

## Architecture

### Core Design Principle

**Filter at load time, not storage time**. The registry file (`~/.pflow/registry.json`) contains ALL discovered nodes. Filtering is applied when nodes are loaded based on settings, not when they're saved.

```
Registry File → load() → Settings Filter → Filtered Nodes → Consumers
   (all nodes)            (apply rules)      (subset)       (CLI, LLM, etc)
```

### Components

1. **SettingsManager** (`src/pflow/core/settings.py`)
   - Loads settings from `~/.pflow/settings.json`
   - Applies allow/deny patterns using fnmatch
   - Handles environment variable overrides

2. **Registry.load()** (`src/pflow/registry/registry.py`)
   - Modified to filter by default: `load(include_filtered=False)`
   - Single point of filtering for entire system
   - Lazy-loads SettingsManager to avoid circular imports

3. **Settings File** (`~/.pflow/settings.json`)
   ```json
   {
     "registry": {
       "nodes": {
         "allow": ["*"],
         "deny": ["pflow.nodes.git.*", "pflow.nodes.github.*"]
       }
     }
   }
   ```

   > **Note**: Git and GitHub nodes are denied by default as they are deprecated in favor of MCP integrations.

4. **Environment Override**
   - `PFLOW_INCLUDE_TEST_NODES=true` includes internal test nodes regardless of patterns
   - Critical for CI/CD where tests need access to test nodes

## User Experience

### Default Behavior

```bash
# Test nodes are hidden by default
$ pflow registry list
file.read
file.write
git.status
# (no echo or test nodes)

# LLM/planner doesn't see denied nodes
$ pflow "create a workflow"
# LLM context excludes denied nodes
```

### Managing Settings

```bash
# Add deny pattern
$ pflow settings deny "github.delete-*"

# Add allow pattern
$ pflow settings allow "mcp-slack-*"

# Check if node would be included
$ pflow settings check echo
✗ Node 'echo' would be EXCLUDED

# View current settings
$ pflow settings show
```

### Test Environment

```bash
# Tests automatically enable test nodes via conftest.py
$ make test  # PFLOW_INCLUDE_TEST_NODES=true is set

# Manual override for debugging
$ PFLOW_INCLUDE_TEST_NODES=true pflow registry list
# Now shows echo and other test nodes
```

## Implementation Details

### Filtering Logic

1. **Priority Order**:
   - Environment variables (highest)
   - Settings file deny patterns
   - Settings file allow patterns
   - Default behavior (lowest)

2. **Pattern Matching**:
   - Uses Python's `fnmatch` for glob-style patterns
   - Patterns checked against both node name and module path
   - Examples: `test.*`, `mcp-github-*`, `*/test/*`

3. **Lazy Loading**:
   - SettingsManager loaded on first access to avoid circular imports
   - Settings cached after first load for performance

### Security Considerations

- **Denied nodes are completely hidden** from LLM context
- **No bypass mechanism** in production (only test env var)
- **Settings file is user-specific** (in home directory)

## Testing

### Critical Test Coverage

1. **test_denied_nodes_not_in_llm_context**
   - Verifies denied nodes don't leak to LLM prompts
   - Security critical

2. **test_env_var_overrides_settings**
   - Ensures test environment can access test nodes
   - CI/CD critical

3. **test_registry_load_respects_settings**
   - Core filtering mechanism works correctly
   - Foundation for all other filtering

## Migration and Compatibility

### Backward Compatibility

- Existing code continues to work (Registry.load() just returns filtered nodes)
- Old registry files work (filtering applied at runtime)
- No changes needed to existing nodes or workflows

### Future Enhancements

- Per-workflow node permissions
- Organization-level settings
- Audit logging of denied node access attempts
- Dynamic reloading of settings without restart

## Files Modified

```
src/
├── pflow/
│   ├── core/
│   │   └── settings.py (NEW)
│   ├── registry/
│   │   └── registry.py (modified load(), list_nodes())
│   ├── cli/
│   │   ├── main_wrapper.py (added settings routing)
│   │   └── commands/
│   │       └── settings.py (NEW)
│   └── mcp/
│       └── registrar.py (added filtering support)
tests/
├── conftest.py (added enable_test_nodes fixture)
├── test_integration/
│   └── test_settings_filtering.py (NEW)
└── test_registry/
    └── test_registry_filtering.py (NEW)
```

## Design Decisions

### Why filter at load time?

1. **Reversibility**: Can re-enable nodes by changing settings
2. **Performance**: No registry rewrite on settings change
3. **Simplicity**: One filtering point for entire system
4. **Safety**: Can't accidentally delete node information

### Why include test nodes in registry?

1. **Completeness**: Registry represents all available nodes
2. **Testing**: Can enable for debugging without re-scanning
3. **Documentation**: Can see what's available even if denied

### Why environment variable override?

1. **CI/CD**: Tests need test nodes regardless of settings
2. **Debugging**: Quick way to enable without editing files
3. **Isolation**: Doesn't affect persistent settings