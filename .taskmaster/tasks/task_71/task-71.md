# Task 71: Extend CLI Commands with tools for agentic workflow building

## Description
Add CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery. These commands mirror the planner's discovery approach - agents provide rich descriptions of what they want to build, and receive complete, detailed information about relevant components. Create comprehensive instructions showing agents how to use this discovery-first workflow.

## Status
done

## Completed
2025-10-03

## Dependencies
- LLM integration (same as used by planner)
- All required service functionality already exists in the codebase

## Priority
high

## Details

### The Paradigm Shift

After extensive analysis, we discovered that pflow already has the infrastructure needed. We're exposing the planner's internal capabilities as CLI commands:

1. Add 2 discovery commands that use LLM for intelligent selection
2. Add 1 validation flag for pre-flight checks (critical!)
3. Add 1 save command for workflow library management
4. Add 1 describe command for detailed node information
5. Enhance error output to show rich context
6. Create clear agent instructions (AGENT_INSTRUCTIONS.md)

### Key Insight: Discovery Like the Planner

The breakthrough is that agents need the same discovery approach as the planner:
- **Rich queries**: "I need to analyze GitHub PRs and create reports"
- **Intelligent selection**: LLM understands intent and selects relevant components
- **Complete information**: Full interface details, not just names
- **Pre-flight validation**: Check workflows before execution
- **Single-shot discovery**: Everything needed in one command

### Key Discoveries from Research

1. **Direct Node Reuse is Feasible**:
   - Planner nodes can run standalone with `node.run(shared)`
   - No Flow needed, just a shared dict
   - Test suite proves this with 350+ examples

2. **Validation is Critical**:
   - Agents have no way to validate before execution
   - Runtime failures are bad UX for iterative development
   - ValidatorNode provides 4-layer validation

3. **Context Builders are Ready**:
   - `build_nodes_context()` - lightweight browsing
   - `build_planning_context()` - full interface details
   - `build_workflows_context()` - rich workflow metadata

4. **Rich Error Data Exists but Hidden**:
   - Nodes capture full API responses in shared store
   - ExecutionResult.errors contains detailed error information
   - CLI currently shows generic "execution failed" message
   - Simple fix: pass and display ExecutionResult.errors

### CLI Commands to Add

#### 1. `pflow workflow discover` Command (NEW)

**Purpose**: Discover existing workflows that match a task description

**How it works**:
- Takes rich natural language query
- Uses WorkflowDiscoveryNode directly
- Returns matching workflows with metadata

**Example**:
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
```

#### 2. `pflow registry discover` Command (NEW)

**Purpose**: Discover nodes needed for a specific task

**How it works**:
- Takes rich natural language query
- Uses ComponentBrowsingNode directly
- Returns relevant nodes with full interfaces

**Example**:
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
[... other relevant nodes ...]
```

#### 3. `--validate-only` Flag (NEW - CRITICAL)

**Purpose**: Validate a workflow before execution

**How it works**:
- Added to main pflow CLI as a flag
- Uses ValidatorNode's 4-layer validation
- Checks: schema, templates, compilation, runtime readiness
- No side effects, pure validation

**Example**:
```bash
$ pflow --validate-only .pflow/workflows/draft.json repo=owner/repo pr_number=123

✓ Schema validation passed
✓ Template resolution passed
✓ Compilation check passed
✓ Runtime validation passed

Workflow is ready for execution!
```

#### 4. `pflow workflow save` Command (NEW)

**Purpose**: Save a draft workflow to the global library

**Usage**:
```bash
pflow workflow save .pflow/workflows/draft.json my-workflow "Description" [--generate-metadata]
```

**Features**:
- Uses WorkflowManager.save()
- Optional --generate-metadata for rich discovery ✅ **Verified: Can be in MVP**
- --delete-draft option

**Note on --generate-metadata**: ✅ Research confirmed MetadataGenerationNode only needs raw workflow IR, NOT ValidatorNode-specific output. Simple to implement - just pass workflow IR via shared store. See VERIFIED_RESEARCH_FINDINGS.md section 4 for details.

#### 5. `pflow registry describe` Command (NEW)

**Purpose**: Get detailed information about specific nodes

**How it works**:
- Takes one or more node IDs
- Uses build_planning_context() directly
- Returns full interface specifications

**Example**:
```bash
$ pflow registry describe github-get-pr llm

### github-get-pr
**Description**: Fetch pull request details from GitHub
**Inputs**:
  - repo: str (required) - Repository in owner/repo format
  - pr_number: int (required) - Pull request number
**Outputs**:
  - pr_title: str - Title of the pull request
  - pr_body: str - Description of the PR
[... complete details ...]
```

#### 6. Enhanced Error Output (CRITICAL)

**Purpose**: Show rich error context when execution fails

**How it works**:
- Enhances CLI to display ExecutionResult.errors details
- Especially important with --no-repair flag
- Shows raw API responses, not just generic messages
- Displays field-level validation errors
- Shows available fields for template errors
- Helps agents understand and fix errors

**Example for API error**:
```bash
$ pflow --no-repair draft.json repo=owner/repo

❌ Workflow execution failed at node: 'create-issue'
   Category: api_validation
   Message: HTTP 422 - Validation Failed

   API Response:
   - Field 'assignees': should be a list (got: string "alice")
   - Field 'body': too short (minimum: 30 chars)

   Documentation: https://docs.github.com/rest/issues
```

**Example for template error**:
```bash
❌ Workflow execution failed at node: 'process'
   Category: template_error
   Message: Template ${fetch.result.title} failed to resolve

   Available fields in 'fetch':
   - issues
   - total_count
   - incomplete_results

   💡 Tip: Use ${fetch.issues[0].title} instead
```

### File Organization for Agents

Agents need to understand WHERE to create files:

**Local Drafts** (project-specific):
```
./my-project/
└── .pflow/
    └── workflows/
        └── draft.json    # Agent creates/edits here
```

**Global Library** (reusable everywhere):
```
~/.pflow/
└── workflows/
    └── saved.json       # After using `workflow save`
```

### Agent Instructions Document

Create comprehensive `AGENT_INSTRUCTIONS.md` showing the complete workflow:

#### Complete Agent Workflow
```bash
# 1. Discover what exists
pflow workflow discover "analyze GitHub PRs"
pflow registry discover "fetch GitHub data and analyze"

# 2. Get specific node details if needed
pflow registry describe github-get-pr llm write-file

# 3. Create workflow JSON based on discoveries
mkdir -p .pflow/workflows
# Agent creates: .pflow/workflows/draft.json

# 4. VALIDATE before execution (critical!)
pflow --validate-only .pflow/workflows/draft.json repo=owner/repo pr_number=123
# Fix any validation errors...

# 5. Test execution
pflow --no-repair .pflow/workflows/draft.json repo=owner/repo pr_number=123
# Enhanced error output helps debug issues

# 6. Save with metadata when working
pflow workflow save .pflow/workflows/draft.json my-analyzer "PR analyzer" --generate-metadata
```

## Implementation Plan

### Phase 1: Add `workflow discover` Command (30 min)
- Location: `src/pflow/cli/commands/workflow.py`
- Create WorkflowDiscoveryNode instance
- Run with user query in shared dict
- Format and display results

### Phase 2: Add `registry discover` Command (30 min)
- Location: `src/pflow/cli/commands/registry.py`
- Create ComponentBrowsingNode instance
- Run with user query in shared dict
- Display planning context output

### Phase 3: Add `--validate-only` Flag (45 min)
- Location: `src/pflow/cli/main.py`
- Add flag to main CLI command
- Use ValidatorNode logic for validation
- Run 4-layer validation
- Return structured errors without execution

### Phase 4: Add `workflow save` Command (30 min)
- Location: `src/pflow/cli/commands/workflow.py`
- Thin wrapper around WorkflowManager.save()
- Add --generate-metadata and --delete-draft options

### Phase 5: Add `registry describe` Command (30 min)
- Location: `src/pflow/cli/commands/registry.py`
- Use build_planning_context() directly
- Accept multiple node IDs
- Display full specifications

### Phase 6: Enhance Error Output (30 min)
- Location: `src/pflow/cli/main.py`
- Display rich ExecutionResult.errors details
- Show node_id, category, available fields
- Especially important for --no-repair mode

### Phase 7: Create Agent Instructions (45 min)
- Comprehensive guide with complete workflow
- Emphasize discovery-first approach
- Include validation step
- Show error handling patterns

## Test Strategy

### Discovery Command Tests
- Rich queries return relevant components only
- Full interface details included
- LLM failures handled gracefully
- Direct node execution works

### Validation Command Tests
- All 4 validation layers work
- Returns specific actionable errors
- No side effects occur
- Works with partial parameters

### Save Command Tests
- Validates and saves correctly
- --generate-metadata creates rich metadata
- --delete-draft removes source
- Name validation works

### Integration Tests
- Full cycle: discover → create → validate → execute → save
- Agent can build complete workflow
- Validation catches errors before execution

## Why This Approach is Superior

1. **Direct Node Reuse**: No extraction needed, nodes work standalone
2. **Pre-flight Validation**: Catch errors before execution
3. **Rich Error Context**: Agents see exactly what went wrong
4. **Matches Planner Pattern**: Proven discovery approach
5. **Complete Information**: No follow-up queries needed
6. **Immediate Value**: ~4 hours implementation

## Success Criteria

✅ `pflow workflow discover` returns matching workflows with metadata
✅ `pflow registry discover` returns relevant nodes with full interfaces
✅ `pflow --validate-only` performs 4-layer validation without execution
✅ `pflow workflow save` promotes drafts to library with optional metadata
✅ `pflow registry describe` provides complete node specifications
✅ Enhanced error output shows rich context on failures
✅ AGENT_INSTRUCTIONS.md explains complete discovery → validation → execution flow
✅ Agents can build validated workflows with intelligent discovery
✅ Total implementation under 4 hours

## Notes

The key insight: Agents need pre-flight validation! The planner's nodes can be reused directly without extraction. By exposing these capabilities as CLI commands, agents get:
1. **Rich Queries** - Natural language descriptions of intent
2. **Intelligent Selection** - LLM picks exactly what's needed
3. **Pre-flight Validation** - Catch errors before execution
4. **Complete Information** - Full details, no follow-ups
5. **Proven Pattern** - Reuses planner's successful approach

## Implementation Notes

### LLM Model Configuration
✅ **Verified**: Discovery commands (workflow discover, registry discover) use planner nodes that have built-in defaults.

**Research findings** (see VERIFIED_RESEARCH_FINDINGS.md section 5):
1. ✅ WorkflowDiscoveryNode and ComponentBrowsingNode HAVE default model configs
2. ✅ CAN run without explicit `node.set_params()` calls
3. ✅ Default to: `anthropic/claude-sonnet-4-0` @ temperature `0.0`

**Implementation approach**: Proceed without explicit config - defaults are production-ready. Tests confirm this pattern works correctly.

**Optional enhancement**: Can add `--model` flag later if users need to override defaults.
