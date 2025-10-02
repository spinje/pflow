# Feature: cli_agent_enablement

## Objective

Add CLI commands enabling AI agents to discover pflow capabilities through intelligent LLM-powered discovery and validate workflows before execution.

## Requirements

- LLM integration must be available for discovery selection
- Planner nodes (WorkflowDiscoveryNode, ComponentBrowsingNode, ValidatorNode) must be available
- Registry module must expose node metadata via Registry.load()
- WorkflowManager must support list_all() and save() operations
- Context builder must provide build_nodes_context() with full details
- Context builder must provide build_workflows_context() with rich metadata
- Context builder must provide build_planning_context() for detailed specs
- Click command framework must be available
- File system must support ~/.pflow/workflows/ for global library
- File system must support ./.pflow/workflows/ for local drafts

## Scope

- Does not implement MCP server integration
- Does not modify existing execute command (already supports file paths)
- Does not implement nested workflow execution
- Does not implement workflow generation (only discovery and validation)
- Does not add --json option to workflow describe (agents can parse text)

## Inputs

- `command`: str - CLI command name (workflow discover, registry discover, workflow save, registry describe)
- `query`: str - Rich natural language description for discover commands
- `file_path`: str - Path to workflow JSON file for save commands
- `workflow_name`: str - Name for saved workflow (lowercase with hyphens)
- `description`: str - Human-readable workflow description
- `node_ids`: list[str] - Node IDs for registry describe command
- `validate_only`: bool - Flag to validate workflow without execution
- `no_repair`: bool - Flag to disable automatic repair on failure
- `delete_draft`: bool - Flag to delete source file after save
- `force`: bool - Flag to overwrite existing workflow
- `generate_metadata`: bool - Flag to generate rich discovery metadata

## Outputs

Returns: Command-specific outputs via stdout

For `pflow workflow discover`:
- Markdown-formatted matching workflow details
- Includes description, node flow, inputs, outputs, capabilities
- Shows confidence score from LLM matching

For `pflow registry discover`:
- Markdown-formatted relevant node specifications
- Full interface details via planning context
- Grouped by category

For `pflow --validate-only`:
- Validation status for 4 layers (schema, templates, compilation, runtime)
- Specific error messages for failures
- Success confirmation when all layers pass
- Exits without execution

For `pflow workflow save`:
- Success: Confirmation message with saved location in ~/.pflow/workflows/
- Failure: Error message with reason

For `pflow registry describe`:
- Complete node specifications for requested node IDs
- Full interface details including examples

For enhanced error output (with --no-repair):
- Node ID where failure occurred
- Error category and message
- Template resolution attempts and available fields
- Whether error is fixable with repair

Side effects:
- `workflow save` creates file in ~/.pflow/workflows/ (global library)
- `workflow save --delete-draft` removes source file
- `workflow save --generate-metadata` enriches with discovery metadata

## Structured Formats

```json
{
  "workflow_discover_output": {
    "format": "markdown",
    "workflows": [
      {
        "name": "string",
        "description": "string",
        "node_flow": "string",
        "inputs": {},
        "outputs": {},
        "capabilities": ["string"],
        "confidence": "float"
      }
    ]
  },
  "registry_discover_output": {
    "format": "markdown",
    "planning_context": "string with full node interface details"
  },
  "workflow_validate_output": {
    "layers": [
      {"name": "schema", "passed": "boolean", "errors": ["string"]},
      {"name": "templates", "passed": "boolean", "errors": ["string"]},
      {"name": "compilation", "passed": "boolean", "errors": ["string"]},
      {"name": "runtime", "passed": "boolean", "errors": ["string"]}
    ]
  },
  "file_path_resolution": {
    "rules": [
      {"pattern": "contains /", "resolution": "file_path"},
      {"pattern": "ends with .json", "resolution": "file_path"},
      {"pattern": "otherwise", "resolution": "workflow_name"}
    ]
  },
  "file_locations": {
    "local_drafts": "./.pflow/workflows/",
    "global_library": "~/.pflow/workflows/"
  }
}
```

## State/Flow Changes

- `query` → `node.run(shared)` → `filtered_components` when discover commands process
- `workflow_ir` → `validation` → `errors|success` when validate command runs
- `draft_workflow` → `saved_workflow` when save command succeeds
- `local_file (./.pflow/workflows/)` → `global_file (~/.pflow/workflows/)` on save
- `local_file` → `deleted` when --delete-draft flag is used

## Constraints

- Discover commands require LLM for intelligent selection
- Query must be descriptive enough for LLM to understand intent
- Workflow names must match regex: ^[a-z0-9-]+$
- Workflow names must be ≤ 30 characters
- File path must exist and be readable for save/validate commands
- Validation runs 4 layers in sequence
- Local drafts must be in ./.pflow/workflows/ directory
- Global library must be in ~/.pflow/workflows/ directory
- Nodes must be run directly via node.run(shared) pattern

## Rules

1. workflow discover must use WorkflowDiscoveryNode directly
2. registry discover must use ComponentBrowsingNode directly
3. --validate-only flag must use ValidatorNode's 4-layer validation
4. workflow save must use WorkflowManager.save() directly
5. registry describe must use build_planning_context() directly
6. All discovery commands must accept rich natural language queries
7. All nodes must be run via node.run(shared) pattern
8. Validation must check schema, templates, compilation, and runtime
9. Validation must not have side effects (pure validation)
10. workflow save must validate name format as lowercase with hyphens
11. workflow save must reject names over 30 characters
12. workflow save must validate workflow IR before saving
13. workflow save --generate-metadata must use MetadataGenerationNode
14. workflow save --force must overwrite existing workflows
15. workflow save --delete-draft must remove source file after success
16. registry describe must accept multiple node IDs
17. File path detection must check for "/" or ".json" extension
18. Commands must be added to existing command groups (workflow.py, registry.py)
19. --validate-only flag must be added to main CLI command
20. Enhanced error output must show ExecutionResult.errors details
21. AGENT_INSTRUCTIONS.md must document complete workflow with validation
22. Direct node reuse without extraction or wrapper functions

## Edge Cases

- Query too vague → LLM returns best guess with all potentially relevant items
- Query mentions non-existent capability → return empty results with helpful message
- No workflows match query → return empty list with suggestion to create new
- No nodes match query → return error with suggestion to check available nodes
- Invalid workflow name format → reject with error message
- Duplicate workflow name without --force → reject with error message
- Invalid JSON in source file → reject with parse error
- LLM service unavailable → nodes handle gracefully with fallback
- Validation finds errors → return specific actionable messages
- Unknown node IDs in describe → error with list of valid nodes

## Error Handling

- LLM failure → Nodes handle internally, may return empty results
- File not found → Exit with error message to stderr
- Invalid JSON → Exit with parse error details
- Permission denied → Exit with file access error
- Workflow validation failure → Return specific errors from each layer
- Name already exists → Exit with conflict error unless --force
- Missing ~/.pflow/workflows/ directory → Create directory automatically
- Node execution failure → Access error info from shared dict

## Non-Functional Criteria

- Discovery commands should complete within 2 seconds (including LLM call)
- Validation should be near-instant (no LLM required)
- Full details must be complete enough for agent to build workflows
- Output must be formatted for readability (markdown sections)
- Commands must preserve backward compatibility
- Must reuse planner nodes directly without extraction
- Error messages must be specific and actionable

## Examples

### Example 1: Discover workflows
```bash
$ pflow workflow discover "I need to analyze pull requests"

## pr-analyzer
**Description**: Comprehensive PR analysis workflow
**Node Flow**: github-get-pr >> llm >> write-file
**Inputs**:
  - repo: str (required) - GitHub repository
  - pr_number: int (required) - Pull request number
**Outputs**:
  - report_path: str - Path to generated report
**Capabilities**:
  - Analyzes code changes
  - Identifies potential issues
**Confidence**: 95%
```

### Example 2: Discover nodes
```bash
$ pflow registry discover "I need to fetch GitHub issues and analyze them"

## GitHub Operations

### github-get-issue
**Description**: Fetch a specific GitHub issue
**Inputs**:
  - repo: str (required) - Repository in owner/repo format
  - issue_number: int (required) - Issue number
**Outputs**:
  - issue_title: str - Title of the issue
  - issue_body: str - Full issue description
[...]
```

### Example 3: Validate workflow
```bash
$ pflow --validate-only .pflow/workflows/draft.json repo=owner/repo pr_number=123

✓ Schema validation passed
✓ Template resolution passed
✓ Compilation check passed
✓ Runtime validation passed

Workflow is ready for execution!
```

### Example 4: Complete agent workflow
```bash
# Discover what's needed
$ pflow workflow discover "analyze GitHub PRs"
$ pflow registry discover "GitHub and LLM operations"

# Get specific details
$ pflow registry describe github-get-pr llm

# Create workflow locally
$ mkdir -p .pflow/workflows
# [Agent creates .pflow/workflows/draft.json]

# Validate before execution
$ pflow --validate-only .pflow/workflows/draft.json repo=owner/repo pr_number=123

# Test it
$ pflow --no-repair .pflow/workflows/draft.json repo=owner/repo pr_number=123

# Save when working
$ pflow workflow save .pflow/workflows/draft.json my-pr-analyzer "Analyzes PRs" --generate-metadata --delete-draft
```

## Test Criteria

1. workflow discover with rich query returns relevant workflows only
2. workflow discover shows confidence score from LLM
3. registry discover with rich query returns relevant nodes only
4. registry discover returns full interface details via planning context
5. workflow validate performs 4-layer validation without side effects
6. workflow validate returns specific errors for each layer
7. workflow validate requires all required parameters (fails if missing required inputs)
8. workflow save creates file in ~/.pflow/workflows/
9. workflow save with invalid name "My Workflow" returns error
10. workflow save with name over 30 characters returns error
11. workflow save --generate-metadata enriches with discovery metadata
12. workflow save --force overwrites existing workflow
13. workflow save --delete-draft removes source file
14. registry describe accepts multiple node IDs
15. registry describe returns complete specifications
16. Unknown node IDs in describe return helpful error
17. Direct node execution via node.run(shared) works
18. File path "draft.json" is detected as path not workflow name
19. Workflow name "my-workflow" resolves from ~/.pflow/workflows/
20. AGENT_INSTRUCTIONS.md includes validation in workflow

## Notes (Why)

- Direct node reuse eliminates code duplication and complexity
- Pre-flight validation critical for agent iteration speed
- LLM-based discovery mimics planner's proven approach
- Rich queries enable single-shot discovery
- Full details eliminate need for follow-up commands
- Validation without execution prevents partial state
- Grouping and formatting aid comprehension
- Local vs global separation enables testing before saving

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2                       |
| 2      | 3, 4                       |
| 3      | 5, 6, 7                    |
| 4      | 8                          |
| 5      | 14, 15                     |
| 6      | 1, 3                       |
| 7      | 17                         |
| 8      | 5, 6                       |
| 9      | 5                          |
| 10     | 9                          |
| 11     | 10                         |
| 12     | 8                          |
| 13     | 11                         |
| 14     | 12                         |
| 15     | 13                         |
| 16     | 14                         |
| 17     | 18                         |
| 18     | Implementation tests       |
| 19     | 20                         |
| 20     | 17                         |

## Versioning & Evolution

- v1.0.0 - Initial CLI commands with LLM-based discovery and validation
- v1.1.0 - (Future) Add caching for repeated queries
- v1.2.0 - (Future) Add workflow generation from natural language
- v2.0.0 - (Future) MCP server integration from Task 72

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes planner nodes can run standalone (proven by tests)
- Assumes agents can process detailed markdown output effectively
- Assumes build_planning_context() provides sufficient detail
- Unknown optimal LLM model for discovery selection
- Unknown whether 2-second target achievable with LLM latency
- Unknown how well agents will use validation feedback

### Conflicts & Resolutions

- Original design had separate discover commands vs under existing groups - Resolution: Under existing groups for consistency
- JSON output for describe vs markdown only - Resolution: Markdown only, agents can parse
- Extract logic vs direct node reuse - Resolution: Direct reuse proven simpler

### Decision Log / Tradeoffs

- Chose direct node reuse: Simpler implementation vs potential coupling
- Chose pre-flight validation: Better UX vs additional command
- Chose markdown output: Human-readable vs structured JSON
- Chose under existing command groups: Consistency vs new namespace

### Ripple Effects / Impact Map

- Requires LLM configuration for CLI commands
- Planner nodes become part of CLI interface contract
- Agent workflow patterns change to include validation
- Performance testing needed with LLM integration
- Documentation must explain node reuse pattern

### Residual Risks & Confidence

- Risk: Direct node coupling - Mitigation: Nodes designed for reuse
- Risk: LLM latency - Mitigation: Cache common queries
- Risk: Validation complexity - Mitigation: Reuse ValidatorNode directly
- Confidence: High for functionality, High for implementation simplicity

### Epistemic Audit (Checklist Answers)

1. Assumed node reuse feasible, agent markdown processing, sufficient context detail
2. Node API changes would affect CLI; LLM unavailability needs fallback
3. Chose simplicity (direct reuse) over abstraction (extraction)
4. All rules have corresponding test coverage in compliance matrix
5. Affects CLI interface, agent patterns, planner node contracts
6. Node reuse proven by tests; Confidence: Very High for implementation