# Task 10: Create registry CLI commands

## ID
10

## Title
Create registry CLI commands

## Description
Implement CLI commands for registry operations (`pflow registry list|describe|search|scan`) to replace the temporary `scripts/populate_registry.py` script. Core nodes will auto-discover on first use, while user nodes require explicit scanning with security warnings.

## Status
not started

## Dependencies
- Task 2: Basic CLI run command with stdio/stdin support - Registry commands need the CLI infrastructure to be in place
- Task 5: Node discovery and registry implementation - Registry class and scanner are required for the CLI commands to function
- Task 7: Extract node metadata from docstrings - MetadataExtractor is needed to parse node interfaces for display

## Priority
medium

## Details
The registry CLI will provide users with commands to explore and manage available nodes in pflow. Currently, users must run a temporary script (`scripts/populate_registry.py`) to populate the registry, which is not user-friendly. This task will:

### Core Implementation
- Create a new `src/pflow/cli/registry.py` Click command group with subcommands
- Enhance the Registry class to support auto-discovery of core nodes on first load
- Add search functionality to the Registry class using simple substring matching
- Update `main_wrapper.py` to route "registry" commands to the new command group
- Delete the temporary `populate_registry.py` script

### Commands to Implement
1. **`pflow registry list`** - Display all registered nodes in a formatted table
   - Auto-discovers core nodes from `src/pflow/nodes/` on first use
   - Shows node name, type (core/user/mcp), and description
   - Supports `--json` flag for programmatic output

2. **`pflow registry describe <node>`** - Show detailed information about a specific node
   - Displays full interface (inputs, outputs, parameters)
   - Shows example usage
   - Supports `--json` flag

3. **`pflow registry search <query>`** - Search nodes by name or description
   - Simple substring matching with scoring (exact=100, prefix=90, name contains=70, description contains=50)
   - Returns ranked results
   - Supports `--json` flag

4. **`pflow registry scan [PATH]`** - Scan for custom user nodes
   - Default path: `~/.pflow/nodes/`
   - Shows security warning about executing arbitrary Python code
   - Requires explicit confirmation (unless `--force` flag)
   - Validates nodes and shows warnings for invalid ones

### Key Design Decisions
- **Auto-discovery**: Core nodes are automatically discovered on first registry access - no manual setup required
- **Security model**: User nodes require explicit scanning with clear warnings about code execution risks
- **Search simplicity**: Basic substring matching for MVP, with plan to add vector search in future task
- **Type differentiation**: Clear labeling of nodes as core (built-in), user (custom), or mcp (from MCP servers)
- **No versioning in MVP**: Display "1.0.0" as placeholder, real versioning is post-MVP

### Technical Considerations
- Registry will cache nodes in memory after first load for performance
- Registry saves with metadata including pflow version for future upgrade detection
- MCP nodes follow `mcp-{server}-{tool}` naming pattern and are already integrated
- All commands support both human-readable and JSON output formats
- Use Click's built-in formatting rather than adding external dependencies

### User Experience Flow
```bash
# First time user - zero setup required
$ pflow registry list
[Auto-discovering core nodes...]
✓ Registered 12 core nodes

Name                 Type    Description
────────────────────────────────────────
read-file           core    Read file contents
write-file          core    Write content to file
llm                 core    Process text with LLM
...

# Adding custom nodes
$ pflow registry scan ~/.pflow/nodes/
⚠️  WARNING: Custom nodes execute with your user privileges.
   Only add nodes from trusted sources.

Found 1 valid node:
  ✓ my-analyzer: Analyze code complexity

Add to registry? [y/N]: y
✓ Added 1 custom node to registry
```

## Test Strategy
Comprehensive testing will ensure the registry CLI works correctly and safely:

### Unit Tests (`tests/test_cli/test_registry_cli.py`)
- Test auto-discovery triggers on first `list` command
- Test JSON output format for all commands
- Test search ranking algorithm (exact > prefix > contains)
- Test describe command with valid and invalid nodes
- Test scan command shows security warning
- Test scan requires confirmation (and --force flag skips it)
- Mock Registry class to avoid file I/O in tests

### Integration Tests
- Test with real registry file creation and loading
- Test scan → list → describe workflow
- Test that core nodes are found without any setup
- Test error handling for corrupted registry files

### Edge Cases to Test
- Empty registry (first time use)
- Node not found in describe command (with suggestions)
- No search results
- Invalid node files during scan
- Non-existent scan paths