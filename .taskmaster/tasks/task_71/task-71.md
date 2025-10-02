# Task 71: Complete CLI Commands and Create Agent Instructions

## ID
71

## Title
Complete CLI Commands and Create Agent Instructions

## Description
Add CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery. These commands mirror the planner's discovery approach - agents provide rich descriptions of what they want to build, and receive complete, detailed information about relevant components. Create comprehensive instructions showing agents how to use this discovery-first workflow.

## Status
not started

## Dependencies
- LLM integration (same as used by planner)
- All required service functionality already exists in the codebase

## Priority
high

## Details

### The Paradigm Shift

After extensive analysis, we discovered that pflow already has ~24 CLI commands with 95% of the logic needed. Instead of building complex MCP infrastructure, we're taking the radically simpler approach:

1. Add 2 new discovery commands that use LLM for intelligent selection
2. Add 1 new save command for workflow library management
3. Enhance 1 existing command with JSON output
4. Create clear agent instructions
5. Test with agents using just CLI
6. Only build MCP (Task 72) if CLI proves insufficient

### Key Insight: Discovery Like the Planner

The breakthrough is that agents need the same discovery approach as the planner:
- **Rich queries**: "I need to analyze GitHub PRs and create reports"
- **Intelligent selection**: LLM understands intent and selects relevant components
- **Complete information**: Full interface details, not just names
- **Single-shot discovery**: Everything needed in one command

### Key Discoveries

1. **Execute Already Supports File Paths**:
   - `.pflow/workflows/draft.json` - relative paths ✅
   - `~/.pflow/workflows/saved.json` - home expansion ✅
   - `draft.json` - current directory ✅
   - `my-workflow` - saved workflow names ✅

2. **Workflow Describe Already Exists**:
   - `pflow workflow describe <name>` shows inputs/outputs ✅
   - Needs `--json` option for agents

3. **MCP Discovery Already Works**:
   - `pflow mcp list` - lists servers ✅
   - `pflow mcp tools` - lists tools ✅
   - `pflow mcp info <tool>` - tool details ✅

### CLI Commands to Add/Enhance

#### 1. `pflow discover-nodes` Command (NEW)

**Purpose**: Discover all nodes needed for a specific task

**How it works**:
- Takes rich natural language query
- Uses LLM to select relevant nodes (like ComponentBrowsingNode)
- Returns FULL interface details for each node
- Groups by category for readability

**Example**:
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
[... complete details for all relevant nodes ...]
```

#### 2. `pflow discover-workflows` Command (NEW)

**Purpose**: Discover existing workflows that match a task description

**How it works**:
- Takes rich natural language query
- Uses LLM to find relevant workflows (like WorkflowDiscoveryNode)
- Returns COMPLETE workflow metadata
- Includes flow, capabilities, usage examples

**Example**:
```bash
$ pflow discover-workflows "I need to analyze pull requests"

## pr-analyzer
**Description**: Comprehensive PR analysis workflow
**Version**: 1.2.0
**Node Flow**: github-get-pr >> extract-diff >> llm >> format-report >> write-file
**Inputs**:
  - repo: str (required) - GitHub repository
  - pr_number: int (required) - Pull request number
**Outputs**:
  - report_path: str - Path to generated report
  - summary: str - Brief summary of analysis
**Capabilities**:
  - Analyzes code changes
  - Identifies potential issues
  - Suggests improvements
**Example Usage**:
  pflow execute pr-analyzer --param repo="owner/repo" --param pr_number=123
**Execution Stats**:
  - Used 47 times
  - Average duration: 3.2s
```

#### 3. `pflow workflow save` Command (NEW)

**Purpose**: Save a draft workflow file to the global library

**Usage**:
```bash
pflow workflow save .pflow/workflows/draft.json my-workflow "Description"
```

**Implementation**:
- Location: `src/pflow/cli/commands/workflow.py`
- Use `WorkflowManager.save()` (already has validation)
- Add `--delete-draft` option

#### 4. `pflow workflow describe` Enhancement

**Current**: Shows inputs/outputs in text format
**Enhancement**: Add `--json` option for agent consumption

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

Create comprehensive `AGENT_INSTRUCTIONS.md` that shows:

#### 1. Discovery-First Workflow
```bash
# Discover everything needed for your task
pflow discover-nodes "analyze GitHub PRs and create reports"
pflow discover-workflows "PR analysis"

# You now have:
# - All relevant node interfaces with full details
# - Any existing workflows you can reuse or learn from
```

#### 2. Workflow Creation Process
```bash
# Create local draft
mkdir -p .pflow/workflows
# Agent creates: .pflow/workflows/draft.json using discovered information

# Test with explicit file path
pflow execute .pflow/workflows/draft.json --param key=value

# Fix errors by editing JSON
# Re-execute (checkpoint resumes from failure)

# Save to library when working
pflow workflow save .pflow/workflows/draft.json my-workflow "Description"

# Now usable from anywhere
pflow execute my-workflow --param key=value
```

#### 3. File Path Resolution

**Critical for agents to understand**:
- Contains `/` or ends with `.json` → File path
- Otherwise → Saved workflow name

Examples:
- `pflow execute draft.json` → Loads from current directory
- `pflow execute .pflow/workflows/draft.json` → Loads from path
- `pflow execute my-workflow` → Loads from `~/.pflow/workflows/`

## Implementation Plan

### Phase 1: Add `discover-nodes` Command (1.5 hours)

- Location: `src/pflow/cli/commands/discover.py` (new file)
- Reuse ComponentBrowsingNode logic for LLM selection
- Reuse `build_nodes_context()` for full details formatting
- Handle LLM failures gracefully

### Phase 2: Add `discover-workflows` Command (1.5 hours)

- Location: `src/pflow/cli/commands/discover.py`
- Reuse WorkflowDiscoveryNode logic for LLM selection
- Reuse `build_workflows_context()` for rich metadata
- Include capabilities and execution stats

### Phase 3: Add `workflow save` Command (30 min)

- Location: `src/pflow/cli/commands/workflow.py`
- Thin wrapper around `WorkflowManager.save()`
- Add validation and `--delete-draft` option

### Phase 4: Enhance `workflow describe` (15 min)

Add `--json` option to existing command for structured output.

### Phase 5: Create Agent Instructions (1 hour)

Comprehensive guide emphasizing:
- Discovery-first approach (rich queries)
- Complete information in single commands
- File organization (local vs global)
- Error handling with checkpoints

## Test Strategy

### Discovery Command Tests
- Rich queries return relevant components only
- Full interface details included
- LLM failures handled gracefully
- Performance within 2 seconds

### Save Command Tests
- Validates and saves correctly
- `--delete-draft` removes source
- Name validation works

### Integration Tests
- Full cycle: discover → create → execute → save
- Agent can build complete workflow
- Checkpoint resumption works

## Why This Approach is Superior

1. **Matches Planner Pattern**: Proven discovery approach
2. **Single-Shot Discovery**: Everything in one command
3. **Complete Information**: No follow-up queries needed
4. **Intelligent Selection**: LLM understands intent
5. **Immediate Value**: 4-5 hours implementation vs 20 for MCP

## Success Criteria

✅ `pflow discover-nodes` returns full interface details for relevant nodes
✅ `pflow discover-workflows` returns complete workflow metadata
✅ Both discovery commands use LLM for intelligent selection
✅ `pflow workflow save` promotes drafts to library
✅ `pflow workflow describe --json` provides structured data
✅ AGENT_INSTRUCTIONS.md explains discovery-first approach
✅ Agents can build complete workflows with single discovery commands
✅ Total implementation under 5 hours

## Notes

The key insight: Agents need the same rich, intelligent discovery that the planner uses internally. By exposing the planner's discovery nodes as CLI commands, agents get:
1. **Rich Queries** - Natural language descriptions of intent
2. **Intelligent Selection** - LLM picks exactly what's needed
3. **Complete Information** - Full details, no follow-ups
4. **Proven Pattern** - Reuses planner's successful approach

This transforms the agent experience from browsing catalogs to describing intent and receiving curated, complete information.