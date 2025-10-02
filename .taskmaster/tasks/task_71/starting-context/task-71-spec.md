# Feature: cli_agent_enablement

## Objective

Add CLI commands enabling AI agents to discover pflow capabilities.

## Requirements

- LLM integration must be available for discovery selection
- Registry module must expose node metadata via Registry.load()
- WorkflowManager must support list_all() and save() operations
- Context builder must provide build_nodes_context() with full details
- Context builder must provide build_workflows_context() with rich metadata
- Click command framework must be available
- Existing workflow describe command must be present
- File system must support ~/.pflow/workflows/ for global library
- File system must support ./.pflow/workflows/ for local drafts

## Scope

- Does not implement MCP server integration
- Does not modify existing execute command (already supports file paths)
- Does not implement nested workflow execution
- Does not modify existing MCP discovery commands
- Does not implement workflow generation (only discovery)

## Inputs

- `command`: str - CLI command name (discover-nodes, discover-workflows, workflow save, workflow describe)
- `query`: str - Rich natural language description for discover commands
- `file_path`: str - Path to workflow JSON file for save command
- `workflow_name`: str - Name for saved workflow (lowercase with hyphens)
- `description`: str - Human-readable workflow description
- `output_json`: bool - Flag to output as JSON instead of text
- `delete_draft`: bool - Flag to delete source file after save
- `force`: bool - Flag to overwrite existing workflow

## Outputs

Returns: Command-specific outputs via stdout

For `discover-nodes`:
- Markdown-formatted detailed node specifications for all relevant nodes
- Includes full interface details (inputs, outputs, descriptions, examples)
- Grouped by category

For `discover-workflows`:
- Markdown-formatted complete workflow details for all relevant workflows
- Includes node flow, inputs, outputs, capabilities, keywords, usage examples
- Includes execution statistics and metadata

For `workflow save`:
- Success: Confirmation message with saved location in ~/.pflow/workflows/
- Failure: Error message with reason

For `workflow describe --json`:
- JSON: {"name": str, "description": str, "inputs": dict, "outputs": dict, "nodes": list}

Side effects:
- `workflow save` creates file in ~/.pflow/workflows/ (global library)
- `workflow save --delete-draft` removes source file
- Creates AGENT_INSTRUCTIONS.md documentation file

## Structured Formats

```json
{
  "discover_nodes_output": {
    "format": "markdown",
    "sections": [
      {
        "category": "string",
        "nodes": [
          {
            "name": "string",
            "description": "string",
            "inputs": [{"key": "string", "type": "string", "required": "boolean", "description": "string"}],
            "outputs": [{"key": "string", "type": "string", "description": "string"}],
            "params": [{"key": "string", "type": "string", "default": "any", "description": "string"}],
            "examples": "string"
          }
        ]
      }
    ]
  },
  "discover_workflows_output": {
    "format": "markdown",
    "workflows": [
      {
        "name": "string",
        "description": "string",
        "version": "string",
        "node_flow": "string",
        "inputs": {},
        "outputs": {},
        "capabilities": ["string"],
        "keywords": ["string"],
        "example_usage": "string",
        "execution_stats": {}
      }
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

- `query` → `llm_selection` → `filtered_components` when discover commands process
- `draft_workflow` → `saved_workflow` when save command succeeds
- `local_file (./.pflow/workflows/)` → `global_file (~/.pflow/workflows/)` on save
- `local_file` → `deleted` when --delete-draft flag is used

## Constraints

- Discover commands require LLM for intelligent selection
- Query must be descriptive enough for LLM to understand intent
- Workflow names must match regex: ^[a-z0-9-]+$
- Workflow names must be ≤ 30 characters
- File path must exist and be readable for save command
- JSON output must be valid parseable JSON
- Local drafts must be in ./.pflow/workflows/ directory
- Global library must be in ~/.pflow/workflows/ directory

## Rules

1. discover-nodes must accept rich natural language query
2. discover-nodes must use LLM to select relevant nodes
3. discover-nodes must return full interface details for each node
4. discover-nodes must group nodes by category in output
5. discover-workflows must accept rich natural language query
6. discover-workflows must use LLM to select relevant workflows
7. discover-workflows must return complete workflow metadata
8. discover-workflows must include node flow and capabilities
9. Both discover commands must reuse planner's context building functions
10. workflow save must validate name format as lowercase with hyphens
11. workflow save must reject names over 30 characters
12. workflow save must load and validate workflow IR using validate_ir() before saving
13. workflow save must save to ~/.pflow/workflows/ directory using WorkflowManager.save()
14. workflow save --force must overwrite existing workflows
15. workflow save --delete-draft must remove source file after successful save
16. workflow describe --json must add JSON output to existing describe command
17. File path detection must check for "/" or ".json" extension
18. Non-path arguments to execute must resolve as workflow names from library
19. Commands must be added to src/pflow/cli/commands/workflow.py and new discover.py
20. AGENT_INSTRUCTIONS.md must document discovery and creation flow

## Edge Cases

- Query too vague → LLM returns best guess with all potentially relevant items
- Query mentions non-existent capability → return empty results with helpful message
- No workflows match query → return empty list with suggestion to create new
- No nodes match query → return error with suggestion to check available nodes
- Invalid workflow name format → reject with error message
- Duplicate workflow name without --force → reject with error message
- Invalid JSON in source file → reject with parse error
- LLM service unavailable → return error with fallback suggestion
- Query exceeds token limit → truncate intelligently
- Path with ~ expansion → expand to home directory

## Error Handling

- LLM failure → Exit with error suggesting to retry or use simpler query
- File not found → Exit with error message to stderr
- Invalid JSON → Exit with parse error details
- Permission denied → Exit with file access error
- Workflow validation failure → Exit with validation errors from validate_ir()
- Name already exists → Exit with conflict error unless --force
- Missing ~/.pflow/workflows/ directory → Create directory automatically

## Non-Functional Criteria

- Discover commands should complete within 2 seconds (including LLM call)
- Full details must be complete enough for agent to build workflows
- Output must be formatted for readability (markdown sections)
- Commands must preserve backward compatibility
- Must reuse existing planner context building functions

## Examples

### Example 1: Discover nodes for GitHub automation
```bash
$ pflow discover-nodes "I need to fetch GitHub issues, analyze them with AI, and save reports"

## GitHub Operations

### github-get-issue
**Description**: Fetch a specific GitHub issue with details
**Inputs**:
  - repo: str (required) - Repository in owner/repo format
  - issue_number: int (required) - Issue number to fetch
**Outputs**:
  - issue_title: str - Title of the issue
  - issue_body: str - Full issue description
  - issue_state: str - Current state (open/closed)

## AI/LLM Operations

### llm
**Description**: Process text using a language model
**Inputs**:
  - prompt: str (required) - The prompt to send
  - model: str (optional, default: "gpt-4") - Model to use
[...]
```

### Example 2: Discover existing workflows
```bash
$ pflow discover-workflows "I need to analyze pull requests"

## pr-analyzer
**Description**: Comprehensive PR analysis workflow
**Node Flow**: github-get-pr >> extract-diff >> llm >> format-report >> write-file
**Inputs**:
  - repo: str (required) - GitHub repository
  - pr_number: int (required) - Pull request number
**Outputs**:
  - report_path: str - Path to generated report
**Capabilities**:
  - Analyzes code changes
  - Identifies potential issues
  - Suggests improvements
**Example Usage**:
  pflow execute pr-analyzer --param repo="owner/repo" --param pr_number=123
```

### Example 3: Complete agent workflow
```bash
# Discover what's needed
$ pflow discover-nodes "analyze GitHub PRs and create reports"
$ pflow discover-workflows "PR analysis"

# Create workflow locally
$ mkdir -p .pflow/workflows
# [Agent creates .pflow/workflows/draft.json]

# Test it
$ pflow execute .pflow/workflows/draft.json --param repo="owner/repo"

# Save when working
$ pflow workflow save .pflow/workflows/draft.json my-pr-analyzer "Analyzes PRs" --delete-draft
```

## Test Criteria

1. discover-nodes with rich query returns relevant nodes only
2. discover-nodes returns full interface details not just names
3. discover-nodes groups output by category
4. discover-workflows with rich query returns relevant workflows only
5. discover-workflows returns complete metadata including flow
6. discover-workflows includes capabilities and keywords
7. Both discover commands use LLM for selection
8. Both discover commands handle LLM failures gracefully
9. workflow save creates file in ~/.pflow/workflows/ via WorkflowManager.save()
10. workflow save with invalid name "My Workflow" returns error
11. workflow save with name over 30 characters returns error
12. workflow save --force overwrites existing workflow
13. workflow save --delete-draft removes source file
14. workflow describe --json returns valid JSON with all metadata fields
15. File path "draft.json" is detected as path not workflow name
16. File path "./test.json" is detected and resolved correctly
17. Workflow name "my-workflow" resolves from ~/.pflow/workflows/
18. AGENT_INSTRUCTIONS.md is created with discovery examples
19. Commands complete within performance thresholds
20. All outputs provide sufficient detail for workflow creation

## Notes (Why)

- LLM-based discovery mimics planner's proven approach
- Rich queries enable single-shot discovery
- Full details eliminate need for follow-up commands
- Grouping and formatting aid comprehension
- Reusing planner functions ensures consistency
- Local vs global separation enables testing before saving

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 7                          |
| 3      | 2                          |
| 4      | 3                          |
| 5      | 4                          |
| 6      | 7                          |
| 7      | 5                          |
| 8      | 6                          |
| 9      | 7                          |
| 10     | 10                         |
| 11     | 11                         |
| 12     | 9                          |
| 13     | 9                          |
| 14     | 12                         |
| 15     | 13                         |
| 16     | 14                         |
| 17     | 15, 16                     |
| 18     | 17                         |
| 19     | Implementation tests       |
| 20     | 18                         |

## Versioning & Evolution

- v1.0.0 - Initial CLI commands with LLM-based discovery
- v1.1.0 - (Future) Add caching for repeated queries
- v1.2.0 - (Future) Add fallback keyword search when LLM unavailable
- v2.0.0 - (Future) MCP server integration from Task 72

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes LLM service is available and configured
- Assumes agents can process detailed markdown output effectively
- Assumes build_nodes_context() and build_workflows_context() can return full details
- Unknown optimal LLM model for discovery selection
- Unknown whether 2-second target achievable with LLM latency
- Unknown how well LLM will match vague queries

### Conflicts & Resolutions

- Original design had simple browse/search vs rich discovery - Resolution: Rich discovery matches planner approach better
- Keyword search vs LLM selection - Resolution: LLM provides superior matching for natural language
- JSON output vs markdown - Resolution: Markdown with full details more useful for LLM agents

### Decision Log / Tradeoffs

- Chose LLM-based discovery: Better matching vs added dependency and latency
- Chose full details in output: Complete information vs larger response size
- Chose to reuse planner functions: Consistency vs potential coupling
- Chose discover-* naming: Clarity of intent vs longer command names

### Ripple Effects / Impact Map

- Requires LLM configuration for CLI commands
- May need to modify context builders to return richer details
- Discovery functions from planner may need to be exposed
- Agent instructions must explain discovery-first workflow
- Performance testing needed with LLM integration

### Residual Risks & Confidence

- Risk: LLM latency makes commands slow - Mitigation: Cache common queries
- Risk: LLM misunderstands queries - Mitigation: Provide query examples in help text
- Risk: Too much detail overwhelms agents - Mitigation: Test with actual agents
- Risk: LLM service unavailable - Mitigation: Document fallback approaches
- Confidence: High for functionality, Medium for performance

### Epistemic Audit (Checklist Answers)

1. Assumed LLM availability, stable context builder functions, agent markdown processing
2. LLM unavailability would require fallback; context builders may need enhancement
3. Chose effectiveness (LLM matching) over simplicity (keyword search)
4. All rules have corresponding test coverage in compliance matrix
5. Affects planner code exposure, LLM configuration, agent workflow patterns
6. LLM performance uncertain; query matching quality uncertain; Confidence: High for value, Medium for implementation