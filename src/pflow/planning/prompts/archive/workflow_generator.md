---
name: workflow_generator
test_path: tests/test_planning/llm/prompts/test_workflow_generator_prompt.py::TestWorkflowGeneratorPrompt
test_command: uv run python tools/test_prompt_accuracy.py workflow_generator
version: '1.2'
latest_accuracy: 100.0
test_runs: [100.0]
average_accuracy: 100.0
test_count: 15
previous_version_accuracy: 77.6
last_tested: '2025-09-08'
prompt_hash: 5e3ee361
last_test_cost: 0.495237
---

# Workflow Generator Prompt

Generate a workflow for: {{user_input}}

## Understanding the System

Workflows are **DATA PIPELINES** where:
1. **Users provide STARTING PARAMETERS** → These go in the "inputs" section
2. **Each node TRANSFORMS data** → Produces outputs for next nodes
3. **Later nodes CONSUME earlier outputs** → Using ${node_id.output} references
4. **The "inputs" section is the workflow's API** → What users can configure when running

Think of it like a recipe: inputs are the ingredients users bring, nodes are the cooking steps, and each step produces something the next step uses.

<available_nodes>
{{planning_context}}
</available_nodes>

## Core Pattern Rules

**🔴 If user provides it** → MUST go in "inputs" section as `${param_name}`
**🔴 If a node generates it** → MUST reference as `${node_id.output_key}`, NEVER in inputs
**🔴 If you declare an input** → You MUST use it as `${param}` in node params
**🔴 If you use `${variable}`** → It MUST be declared in inputs OR be a node output

## ⚠️ CRITICAL: Sequential Execution Required

**Every node can have ONLY ONE outgoing edge.** The system executes workflows sequentially, not in parallel.

Even when multiple operations could logically run in parallel (like "analyze data AND generate visualization"), you MUST chain them sequentially:

**❌ WRONG (parallel - not supported):**
```
filter_data → analyze_trends
           ↘ generate_visualization
```

**✅ CORRECT (sequential - required):**
```
filter_data → analyze_trends → generate_visualization
```

If multiple operations need the same data, pass it through the chain:
- First operation uses the data
- Second operation can reference BOTH the original data AND the first operation's output
- Example: `generate_viz` can use both `${filter_data.output}` AND `${analyze.response}`

## Workflow Complexity Guide

Break down the request into ALL necessary steps:
- **Simple request** (1-2 operations) → 2-3 nodes
- **Medium request** (3-4 operations) → 4-6 nodes
- **Complex request** (5+ operations) → 6-10+ nodes
- **Ultra-complex** (full pipeline) → 8-12+ nodes

Each distinct operation needs its own node:
- Fetching data → 1 node per source
- Each analysis/transformation → 1 node
- Each output file → 1 write-file node
- Each external action → 1 node

## Purpose Field Requirements

Every node MUST have a "purpose" field (10-200 chars) that:
- Explains its role in THIS specific workflow
- Is contextual, not generic
- ✅ GOOD: "Fetch closed issues for changelog generation"
- ❌ BAD: "Process data" or "Use LLM"
- Never include the actual values of input parameters in the purpose field
- ✅ GOOD: "Saves the response from the LLM to a file"
- ❌ BAD: "Saves the response from the LLM to cat-story.txt"

## REAL EXAMPLE - 6-Node Changelog Workflow:
```json
{
  "nodes": [
    {
      "id": "fetch_issues",
      "type": "github-list-issues",
      "purpose": "Fetch closed issues for changelog generation",
      "params": {
        "repo_owner": "${repo_owner}",      // ← User provides
        "repo_name": "${repo_name}",        // ← User provides
        "state": "closed",
        "limit": "${issue_limit}"           // ← User provides
      }
    },
    {
      "id": "categorize_issues",
      "type": "llm",
      "purpose": "Analyze and categorize issues by type (bug/feature/docs)",
      "params": {
        "prompt": "Categorize these issues by type:\n${fetch_issues.issues}"  // ← NODE OUTPUT!
      }
    },
    {
      "id": "generate_changelog",
      "type": "llm",
      "purpose": "Format categorized issues into changelog sections",
      "params": {
        "prompt": "Create changelog from categorized issues:\n${categorize_issues.response}"  // ← NODE OUTPUT!
      }
    },
    {
      "id": "save_changelog",
      "type": "write-file",
      "purpose": "Save formatted changelog to specified file",
      "params": {
        "file_path": "${changelog_path}",                    // ← User provides
        "content": "${generate_changelog.response}"          // ← NODE OUTPUT!
      }
    },
    {
      "id": "commit_changes",
      "type": "git-commit",
      "purpose": "Commit the new changelog file to version control",
      "params": {
        "message": "Add changelog for version ${version}",   // ← User provides
        "files": ["${changelog_path}"]                       // ← User provides
      }
    },
    {
      "id": "create_pr",
      "type": "github-create-pr",
      "purpose": "Open PR for changelog review and approval",
      "params": {
        "repo_owner": "${repo_owner}",                       // ← User provides
        "repo_name": "${repo_name}",                         // ← User provides
        "title": "Changelog for v${version}",                // ← User provides
        "body": "Automated changelog:\n${generate_changelog.response}",  // ← NODE OUTPUT!
        "head": "${branch_name}",                            // ← User provides
        "base": "main"
      }
    }
  ],
  "edges": [
    {"from": "fetch_issues", "to": "categorize_issues"},
    {"from": "categorize_issues", "to": "generate_changelog"},
    {"from": "generate_changelog", "to": "save_changelog"},
    {"from": "save_changelog", "to": "commit_changes"},
    {"from": "commit_changes", "to": "create_pr"}
  ],
  "inputs": {
    "repo_owner": {
      "description": "GitHub repository owner",
      "type": "string",
      "required": true
    },
    "repo_name": {
      "description": "GitHub repository name",
      "type": "string",
      "required": true
    },
    "issue_limit": {
      "description": "Number of issues to fetch",
      "type": "number",
      "required": false,
      "default": 30
    },
    "changelog_path": {
      "description": "Path to save changelog file",
      "type": "string",
      "required": false,
      "default": "CHANGELOG.md"
    },
    "version": {
      "description": "Version number for this changelog",
      "type": "string",
      "required": true
    },
    "branch_name": {
      "description": "Git branch for PR",
      "type": "string",
      "required": false,
      "default": "update-changelog"
    }
  },
  "outputs": {
    "pr_url": {
      "description": "URL of created pull request",
      "source": "${create_pr.pr_url}"
    }
  }
}
```

Notice how:
- **issues**, **categorized data**, **changelog content** are NODE OUTPUTS (never in inputs)
- Only things users configure (repo, version, paths) are in inputs
- Each node output feeds into the next as ${node_id.output}

## Workflow Structure Requirements

- Must include `"inputs"` field with user-configurable parameters
- Each input needs: description, type, required, and optional default
- Must include `"outputs"` field with `source` mapping to node outputs
- `"type"` for inputs/outputs must be one of: ['string', 'number', 'boolean', 'object', 'array']
  - ❌ **DON'T** use `"integer"` or `"float"` - use `"number"` instead
- **SEQUENTIAL execution only** - each node has exactly ONE outgoing edge
- **NO parallel edges** - even if operations are independent

## Common Mistakes to AVOID

❌ **DON'T declare node-generated data as inputs**
- Wrong: "content" in inputs when LLM generates it
- Right: Use ${generate_content.response}

❌ **DON'T hardcode discovered values**
- Wrong: "anthropic/pflow" in params
- Right: Use ${repo_owner}/${repo_name}

❌ **DON'T skip steps in complex workflows**
- Wrong: Combining multiple operations in one node
- Right: Separate node for each distinct operation

## Fixing Validation Errors (if provided)

<validation_errors>
{{validation_errors_section}}
</validation_errors>

If validation errors are provided above, fix them using these patterns:

**Error: "Template variable ${X} not defined in inputs"**
→ Add "X" to the inputs section with appropriate type and description

**Error: "Declared input 'Y' never used as template variable"**
→ Remove "Y" from inputs (it's likely a node output, not user input)

**Error: "Node type 'Z' not found in registry"**
→ Check available nodes for the correct name (e.g., 'github-list-commits' not 'github_commits')

**Error: "Workflow output 'W' must have description and source fields"**
→ Add both fields: {"description": "...", "source": "${node_id.output}"}

<discovered_parameters>
{{discovered_params_section}}
</discovered_parameters>

## CRITICAL: Parameter Usage Rules

1. **NEVER hardcode discovered values in node parameters**
   - ❌ WRONG: "channel_id": "C09C16NAU5B"
   - ✅ RIGHT: "channel_id": "${channel_id}"

2. **Use discovered values ONLY as defaults in the inputs section**
   - ✅ RIGHT: inputs: { "channel_id": {"type": "string", "default": "C09C16NAU5B"} }

3. **ALL node parameters MUST use template syntax**
   - Every parameter that references an input must use ${param_name}
   - No exceptions, even if you know the value

4. **The user input has been templatized**
   - You're seeing ${param_name} in the request - maintain this pattern
   - This ensures the workflow is reusable with different values