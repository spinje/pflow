# Feature: structure_only_token_efficiency

## Objective

Return node execution structure without data for token efficiency.

## Requirements

- Must have existing registry run command infrastructure
- Must have MCP server exposing registry tools
- Must have filesystem for cache storage
- Must have LLM client for smart filtering
- Must have shared formatters between CLI and MCP

## Scope

- Does not modify workflow execution behavior
- Does not change existing workflow IR format
- Does not affect saved workflows
- Does not require backwards compatibility
- Does not modify planner behavior
- Does not change template resolution

## Inputs

**registry_run:**
- node_type: str - Node identifier to execute
- parameters: dict[str, Any] - Parameters for node execution

**read_fields:**
- execution_id: str - Identifier from previous registry_run
- field_paths: list[str] - Paths to retrieve (e.g., ["result[0].title"])

## Outputs

**registry_run:**
Returns: dict containing:
- execution_id: str - Unique identifier for this execution
- structure: dict - Flattened template paths with types
- field_count: int - Number of fields before filtering
- filtered: bool - Whether smart filtering was applied

**read_fields:**
Returns: dict[str, Any] - Mapping of requested paths to values
Side effects: None

## Structured Formats

### Execution Cache Format
```json
{
  "execution_id": "exec-12345-abc",
  "node_type": "mcp-github-list-issues",
  "timestamp": "2025-01-14T10:30:45Z",
  "ttl_hours": 24,
  "params": {...},
  "outputs": {...}
}
```

### Structure Output Format
```json
{
  "execution_id": "exec-12345-abc",
  "structure": {
    "result": {"type": "list", "length": 847},
    "result[0].id": {"type": "int"},
    "result[0].title": {"type": "str", "avg_length": 50},
    "result[0].body": {"type": "str", "avg_length": 2000}
  },
  "filtered": true,
  "original_field_count": 200
}
```

## State/Flow Changes

- None

## Constraints

- Cache TTL = 24 hours
- Smart filter threshold = 50 fields
- Cache directory = ~/.pflow/cache/node-executions/
- Smart filter LLM = haiku-3-5-latest-20241022
- Max execution_id length = 32 characters

## Rules

1. Registry run executes node with provided parameters
2. Registry run stores outputs in cache with unique execution_id
3. Registry run returns structure without data values
4. Registry run applies smart filtering when field count > 50
5. Smart filtering uses Haiku 3.5 to reduce fields
6. Smart filtering removes metadata fields (URLs, IDs, timestamps)
7. Smart filtering preserves business-relevant fields
8. Read-fields validates execution_id exists in cache
9. Read-fields checks cache entry is not expired (24hr TTL)
10. Read-fields parses each field path independently
11. Read-fields returns requested values as dict
12. Read-fields returns None for invalid paths
13. Cache files use JSON format with UTF-8 encoding
14. Cache files have 600 permissions
15. Execution IDs use format "exec-{timestamp}-{random}"
16. CLI displays structure as formatted text
17. MCP returns structure as dict

## Edge Cases

- execution_id not found → read-fields returns error "Execution not found"
- execution_id expired → read-fields returns error "Execution expired"
- invalid field path → read-fields returns None for that path
- field path out of bounds → read-fields returns None
- empty field_paths list → read-fields returns empty dict
- node execution fails → registry_run returns error, no cache entry created
- cache directory not writable → registry_run continues but warns
- smart filter LLM unavailable → use unfiltered structure
- binary data in output → encode as base64 string
- circular references in structure → limit depth to 10 levels

## Error Handling

- Cache write failure → Log warning but continue execution
- Smart filter timeout → Use unfiltered structure with warning
- Malformed cache file → Treat as cache miss
- Permission denied on cache → Fall back to temp directory

## Non-Functional Criteria

- Cache lookup completes < 100ms for 1000 entries
- Smart filtering completes < 2 seconds
- Token reduction ≥ 600x vs traditional tool calling
- Cache storage < 1GB total

## Examples

### CLI Usage
```bash
# Execute node - returns structure only
$ pflow registry run mcp-github-list-issues repo=org/repo
✓ Node executed successfully
Execution ID: exec-20250114-abc123

Available template paths:
  ✓ ${result} (list, 847 items)
  ✓ ${result[0].title} (str)
  ✓ ${result[0].id} (int)

# Read specific fields
$ pflow read-fields exec-20250114-abc123 result[0].title result[0].id
result[0].title: "Fix authentication bug"
result[0].id: 12345
```

### MCP Usage
```python
# Agent executes node
response = await registry_run(
    node_type="mcp-github-list-issues",
    parameters={"repo": "org/repo"}
)
# Returns: {"execution_id": "exec-20250114-abc123", "structure": {...}}

# Agent reads fields
data = await read_fields(
    execution_id="exec-20250114-abc123",
    field_paths=["result[0].title", "result[0].id"]
)
# Returns: {"result[0].title": "Fix auth bug", "result[0].id": 12345}
```

## Test Criteria

1. Registry run with valid node creates cache entry
2. Registry run returns execution_id and structure
3. Registry run with 100+ fields triggers smart filtering
4. Registry run with <50 fields does not filter
5. Smart filter reduces 200 fields to <20
6. Smart filter preserves title, body, status fields
7. Smart filter removes URL and ID fields
8. Read-fields with valid execution_id returns data
9. Read-fields with expired execution_id returns error
10. Read-fields with invalid execution_id returns error
11. Read-fields with valid path returns correct value
12. Read-fields with invalid path returns None
13. Read-fields with multiple paths returns all values
14. Read-fields with empty paths returns empty dict
15. Cache files expire after 24 hours
16. Cache files have 600 permissions
17. CLI and MCP return identical structure format
18. Binary data encoded as base64 in cache
19. Circular references limited to 10 levels
20. Cache lookup under 100ms with 1000 files

## Notes (Why)

- Structure-only reduces tokens from 200,000 to 300 (600x improvement)
- Selective field retrieval enables data privacy by default
- Smart filtering prevents information overload from complex APIs
- Cache enables stateless tool design while maintaining context
- 24-hour TTL balances storage with typical agent session length

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 1                          |
| 3      | 2                          |
| 4      | 3, 4                       |
| 5      | 5                          |
| 6      | 7                          |
| 7      | 6                          |
| 8      | 8, 10                      |
| 9      | 9, 15                      |
| 10     | 11, 12                     |
| 11     | 13                         |
| 12     | 12                         |
| 13     | 1, 18                      |
| 14     | 16                         |
| 15     | 2                          |
| 16     | 17                         |
| 17     | 17                         |

## Versioning & Evolution

- v1.0.0 — Initial implementation of structure-only mode and read-fields

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes Haiku 3.5 API remains available and affordable
- Assumes 24-hour TTL sufficient for agent workflows
- Unknown: Optimal smart filter threshold (50 fields is initial guess)
- Unknown: Actual token reduction in production (600x is estimate)

### Conflicts & Resolutions

- Conflict: Return execution_id in text output vs separate line
- Resolution: Separate line for clear parsing

### Decision Log / Tradeoffs

- Chose filesystem cache over in-memory: Persistence across sessions
- Chose 24hr TTL over configurable: Simplicity for MVP
- Chose Haiku 3.5 over GPT-4-mini: Better structured data understanding
- Chose 50 field threshold over dynamic: Predictable behavior

### Ripple Effects / Impact Map

- Registry run output format changes affect existing documentation
- MCP agents need update to handle new response format
- Monitoring systems may need adjustment for cache directory growth

### Residual Risks & Confidence

- Risk: Cache growth if cleanup fails; Mitigation: Monitor disk usage
- Risk: Smart filter removes needed field; Mitigation: All fields still accessible
- Confidence: High (85%) - Pattern proven in similar systems

### Epistemic Audit (Checklist Answers)

1. Assumed fixed TTL and threshold values are optimal
2. Wrong assumptions cause suboptimal performance, not failure
3. Prioritized robustness (all data accessible) over elegance
4. All rules mapped to tests, all edge cases covered
5. Ripple effects limited to output format changes
6. Uncertainty on optimal thresholds; Confidence: High for core functionality