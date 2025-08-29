# Feature: registry_cli_commands

## Objective

Enable node discovery and management via CLI commands.

## Requirements

- Must have Registry class with load/save functionality
- Must have Scanner module for node discovery
- Must have MetadataExtractor for parsing docstrings
- Must have Click CLI framework installed
- Must have main_wrapper.py routing mechanism

## Scope

- Does not implement versioning beyond placeholder "1.0.0"
- Does not implement vector search
- Does not implement remote node installation
- Does not implement dependency resolution
- Does not implement node removal commands
- Does not implement MCP server discovery (already exists)

## Inputs

- `list` command:
  - json_flag: bool - Output as JSON instead of table
- `describe` command:
  - node_name: str - Name of node to describe
  - json_flag: bool - Output as JSON instead of formatted text
- `search` command:
  - query: str - Search query string
  - json_flag: bool - Output as JSON instead of table
- `scan` command:
  - path: Optional[str] - Directory path to scan (default: ~/.pflow/nodes/)
  - force_flag: bool - Skip confirmation prompt

## Outputs

Returns: Command-specific outputs:
- `list`: Table of nodes or JSON array
- `describe`: Node details or JSON object
- `search`: Ranked results table or JSON array
- `scan`: Confirmation prompt result and count of added nodes

Side effects:
- `list` on first run: Creates ~/.pflow/registry.json with auto-discovered core nodes
- `scan`: Updates ~/.pflow/registry.json with user nodes

## Structured Formats

```json
{
  "list_output": {
    "nodes": [
      {
        "name": "str",
        "type": "core|user|mcp",
        "description": "str"
      }
    ]
  },
  "describe_output": {
    "name": "str",
    "type": "core|user|mcp",
    "module": "str",
    "class_name": "str",
    "description": "str",
    "interface": {
      "inputs": [],
      "outputs": [],
      "params": [],
      "actions": []
    }
  },
  "search_output": {
    "query": "str",
    "results": [
      {
        "name": "str",
        "type": "core|user|mcp",
        "score": "int",
        "description": "str"
      }
    ]
  },
  "registry_format": {
    "version": "str",
    "last_core_scan": "ISO8601",
    "nodes": {}
  }
}
```

## State/Flow Changes

- `registry_missing` → `registry_initialized` when first list command runs
- `user_nodes_discovered` → `user_nodes_added` when scan confirmation accepted
- `core_nodes_outdated` → `core_nodes_refreshed` when pflow version changes

## Constraints

- Search query must be at least 1 character
- Node names must be kebab-case
- Path for scan must be valid directory
- JSON output flag is mutually exclusive with human output

## Rules

1. If registry.json does not exist then auto-discover core nodes on first load
2. If pflow version differs from registry version then refresh core nodes
3. If search query matches node name exactly then assign score 100
4. If search query matches node name prefix then assign score 90
5. If search query matches substring in node name then assign score 70
6. If search query matches substring in description then assign score 50
7. If scan path does not exist then display error message
8. If scan discovers valid nodes then show security warning
9. If scan confirmation denied then abort without changes
10. If scan confirmation accepted then add nodes to registry
11. If describe node not found then suggest similar nodes
12. If list has no nodes then display "No nodes registered"
13. If search has no results then display "No nodes found matching"
14. If --json flag then output valid JSON
15. If MCP node name starts with "mcp-" then mark type as "mcp"
16. If node in src/pflow/nodes/ then mark type as "core"
17. If node from user scan then mark type as "user"

## Edge Cases

- registry.json corrupted → Return empty dict and log warning
- scan path is file not directory → Display error
- node name contains spaces → Reject as invalid
- search query empty string → Display error
- describe non-existent node → Exit code 1 with suggestions
- scan finds no valid nodes → Display "No valid nodes found"
- scan finds invalid node → Display warning with reason
- first argument not "registry" → Route to workflow command

## Error Handling

- Import error during scan → Log warning and skip file
- JSON decode error in registry → Return empty dict
- Permission denied on registry write → Display error and exit 1
- Click command not found → Display help text

## Non-Functional Criteria

- Auto-discovery completes within 2 seconds
- Search returns results within 100ms for 1000 nodes
- JSON output is pretty-printed with indent=2
- Table output truncates descriptions at 40 characters

## Examples

```bash
# List all nodes
$ pflow registry list
Name                 Type    Description
────────────────────────────────────────
read-file           core    Read file contents
write-file          core    Write content to file

# Describe specific node
$ pflow registry describe llm
Node: llm
Type: core
Description: Process text with language models
Interface:
  Inputs:
    - prompt: str - The prompt to send

# Search nodes
$ pflow registry search github
Found 3 nodes matching 'github':
Name                 Type    Match   Description
────────────────────────────────────────────────
github-get-issue     core    prefix  Fetch GitHub issue

# Scan custom nodes
$ pflow registry scan ~/my-nodes/
⚠️  WARNING: Custom nodes execute with your user privileges.
Found 1 valid node:
  ✓ my-node: Custom functionality
Add to registry? [y/N]: y
✓ Added 1 custom node to registry
```

## Test Criteria

1. First list command creates registry.json with core nodes
2. List command with --json outputs valid JSON structure
3. Describe existing node shows full interface
4. Describe missing node exits with code 1
5. Search "file" returns read-file and write-file nodes
6. Search exact match "read-file" scores 100
7. Search prefix "read" scores 90 for read-file
8. Search substring "ead" scores 70 for read-file
9. Search description "content" scores 50 for write-file
10. Scan non-existent path shows error
11. Scan valid path shows security warning
12. Scan confirmation "n" aborts without changes
13. Scan with --force skips confirmation
14. Scan adds nodes with type "user"
15. Registry marks "mcp-github-tool" as type "mcp"
16. Registry marks "read-file" as type "core"
17. Corrupted registry.json returns empty dict
18. main_wrapper routes "registry" to registry group
19. main_wrapper routes "unknown" to workflow command

## Notes (Why)

- Auto-discovery eliminates manual setup friction for new users
- Security warning prevents accidental execution of untrusted code
- Simple substring search sufficient for MVP with <100 nodes
- Type differentiation helps users understand node origin and trust level
- JSON output enables scripting and automation

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 1                          |
| 3      | 6                          |
| 4      | 7                          |
| 5      | 8                          |
| 6      | 9                          |
| 7      | 10                         |
| 8      | 11                         |
| 9      | 12                         |
| 10     | 14                         |
| 11     | 4                          |
| 12     | 1                          |
| 13     | 5                          |
| 14     | 2                          |
| 15     | 15                         |
| 16     | 16                         |
| 17     | 14                         |

## Versioning & Evolution

- v1.0.0 — Initial registry CLI implementation for MVP

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes Click framework properly installed and configured
- Assumes src/pflow/nodes/ directory structure remains stable
- Assumes ~/.pflow/ directory is writable by user
- Unknown: Exact number of core nodes at implementation time
- Unknown: Performance impact of recursive directory scanning

### Conflicts & Resolutions

- Scanner returns list format vs Registry uses dict format → Registry.update_from_scanner() performs conversion
- MCP nodes use virtual paths vs regular nodes use file paths → Check for "virtual://mcp" to differentiate
- populate_registry.py exists as temporary solution → Delete after registry CLI implementation

### Decision Log / Tradeoffs

- Simple substring search chosen over fuzzy matching for predictability and zero dependencies
- Auto-discovery on first use chosen over explicit init command for better UX
- Security warning on every scan chosen over one-time warning for safety
- Type differentiation by naming convention chosen over metadata field for simplicity

### Ripple Effects / Impact Map

- Compiler must handle registry auto-initialization transparently
- Planning system benefits from searchable registry
- Tests must mock Registry to avoid file I/O
- Documentation must update from populate_registry.py to registry commands

### Residual Risks & Confidence

- Risk: User nodes with malicious code executed during scan. Mitigation: Explicit warning and confirmation. Confidence: Medium
- Risk: Registry corruption loses all registrations. Mitigation: Return empty dict and auto-recover core nodes. Confidence: High
- Risk: Search performance degrades with many nodes. Mitigation: Simple algorithm is O(n) which is acceptable for <1000 nodes. Confidence: High

### Epistemic Audit (Checklist Answers)

1. Assumed Click routing works as documented, ~/.pflow is writable
2. Wrong assumptions break CLI routing or prevent registry persistence
3. Chose robustness (auto-recovery) over elegance (clean failure)
4. All rules mapped to tests, all tests trace to rules
5. Touches Registry class, main_wrapper.py, adds new CLI module
6. Uncertain about exact core node count; Confidence: High for implementation success