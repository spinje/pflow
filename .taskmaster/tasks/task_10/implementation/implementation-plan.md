# Task 10 Implementation Plan

## Overview
Implement CLI commands for registry operations (`pflow registry list|describe|search|scan`) to replace the temporary `scripts/populate_registry.py` script.

## Phase 1: Context Gathering (Parallel Tasks) - 30 min

### Parallel Subagent Tasks:
1. **Registry Architecture Analysis**
   - Task: "Analyze src/pflow/registry/registry.py to understand current methods and structure, focusing on load(), save(), update_from_scanner() and the registry storage format"
   - Task: "Find all usages of Registry class throughout the codebase to understand integration points"

2. **CLI Pattern Analysis**
   - Task: "Study src/pflow/cli/mcp.py to understand the Click command group pattern and how it's structured"
   - Task: "Analyze main_wrapper.py routing mechanism for MCP commands, focusing on sys.argv manipulation"

3. **Scanner and Metadata Understanding**
   - Task: "Examine Scanner.scan_for_nodes() return format and how Registry.update_from_scanner() converts it"
   - Task: "Understand MetadataExtractor output format and how Interface is structured"

4. **Testing Pattern Discovery**
   - Task: "Find existing CLI test patterns in tests/test_cli/ especially mocking patterns"
   - Task: "Identify test utilities for mocking Registry and avoiding file I/O"

## Phase 2: Registry Class Enhancement - 1 hour

### Tasks (Sequential):
1. Add `_auto_discover_core_nodes()` method
   - Scan src/pflow/nodes/ subdirectories
   - Convert scanner results to registry format
   - Mark nodes as type="core"
   - Save with metadata

2. Implement `search()` method
   - Simple substring matching
   - Scoring: exact=100, prefix=90, contains=70, desc=50
   - Return sorted results

3. Add `scan_user_nodes()` method
   - Validate path exists
   - Call scanner
   - Mark as type="user"

4. Implement `_save_with_metadata()`
   - Include version and timestamp
   - Preserve existing structure

5. Update `load()` for auto-discovery
   - Check if registry exists
   - Trigger auto-discovery if missing
   - Add caching

## Phase 3: CLI Command Group - 1.5 hours

### Tasks (Can be parallelized):
1. Create src/pflow/cli/registry.py
   - Copy MCP pattern exactly
   - Create Click group

2. Implement `list` command
   - Auto-discover on first use
   - Support --json flag
   - Display grouped by type

3. Implement `describe` command
   - Show full interface
   - Support --json flag
   - Suggest similar on not found

4. Implement `search` command
   - Use Registry.search()
   - Display with scores
   - Support --json flag

5. Implement `scan` command
   - Show security warning
   - Require confirmation
   - Support --force flag

## Phase 4: System Integration - 30 min

### Tasks (Sequential):
1. Update main_wrapper.py
   - Add registry routing
   - Follow MCP pattern exactly

2. Update main CLI help text
   - Add registry command description
   - Update examples

## Phase 5: Testing - 1 hour

### Parallel Test Creation:
1. **Unit Tests** (tests/test_cli/test_registry_cli.py)
   - Auto-discovery tests
   - JSON output tests
   - Search ranking tests
   - Security warning tests

2. **Integration Tests**
   - End-to-end workflow tests
   - Registry file creation tests
   - Error handling tests

3. **Edge Case Tests**
   - Empty registry
   - Corrupted registry
   - Missing nodes
   - Invalid paths

## Phase 6: Cleanup - 15 min

### Tasks:
1. Delete scripts/populate_registry.py
2. Run full test suite
3. Run make check for linting
4. Document any issues found

## File Assignments to Avoid Conflicts

### Files to CREATE:
- `/Users/andfal/projects/pflow/src/pflow/cli/registry.py` - New CLI command group
- `/Users/andfal/projects/pflow/tests/test_cli/test_registry_cli.py` - New test file

### Files to MODIFY:
- `/Users/andfal/projects/pflow/src/pflow/registry/registry.py` - Add search, auto-discovery, etc.
- `/Users/andfal/projects/pflow/src/pflow/cli/main_wrapper.py` - Add registry routing
- `/Users/andfal/projects/pflow/src/pflow/cli/main.py` - Update help text

### Files to DELETE:
- `/Users/andfal/projects/pflow/scripts/populate_registry.py` - After verification

## Critical Implementation Notes

1. **Registry.save() is DESTRUCTIVE** - Always load before saving
2. **Scanner returns LIST, Registry uses DICT** - Must convert properly
3. **MCP nodes are VIRTUAL** - Detect by "mcp-" prefix
4. **CLI routing is HACKY** - Follow MCP pattern exactly
5. **Security warning is MANDATORY** - Show on every scan

## Success Metrics

- [ ] All 19 test criteria from spec pass
- [ ] `make test` passes with no regressions
- [ ] `make check` passes (linting, type checking)
- [ ] Core nodes auto-discover on first use
- [ ] Security warning shows for user nodes
- [ ] All commands support --json flag
- [ ] populate_registry.py deleted

## Risk Mitigation

1. **Registry corruption**: Return empty dict, auto-recover core nodes
2. **Import errors during scan**: Log and skip, don't fail
3. **Concurrent access**: Registry operations are atomic (full replace)
4. **Performance**: Simple O(n) search acceptable for <1000 nodes