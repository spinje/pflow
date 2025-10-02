# Task 71 Implementation Guide

## Quick Start

This task adds CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery - the same way the planner works internally. Total time: ~4-5 hours.

## Key Insight

Agents need to describe what they want to build in natural language and receive complete, curated information - not browse catalogs. We're exposing the planner's discovery approach as CLI commands.

## What to Build

### 1. `pflow discover-nodes` Command (1.5 hours)
**Location**: `src/pflow/cli/commands/discover.py` (new file)

**Key Points**:
- Takes rich natural language query: "I need to analyze GitHub PRs and create reports"
- Reuses ComponentBrowsingNode logic for LLM selection
- Returns FULL interface details (inputs, outputs, examples) for relevant nodes only
- Groups by category for readability

**Implementation Pattern**:
```python
# 1. Load all nodes from Registry
# 2. Use LLM to select relevant ones (like ComponentBrowsingNode)
# 3. Build detailed context with build_nodes_context()
# 4. Return complete specifications
```

### 2. `pflow discover-workflows` Command (1.5 hours)
**Location**: `src/pflow/cli/commands/discover.py`

**Key Points**:
- Takes rich natural language query: "I need to analyze pull requests"
- Reuses WorkflowDiscoveryNode logic for LLM selection
- Returns COMPLETE metadata (flow, capabilities, examples, stats)
- Includes execution statistics and usage examples

**Implementation Pattern**:
```python
# 1. Load all workflows from WorkflowManager
# 2. Use LLM to find relevant ones (like WorkflowDiscoveryNode)
# 3. Build detailed context with build_workflows_context()
# 4. Return complete workflow specifications
```

### 3. `pflow workflow save` Command (30 min)
**Location**: `src/pflow/cli/commands/workflow.py`

**Key Points**:
- Load workflow from file path
- Use `WorkflowManager.save()` to store in library
- Validate name format: lowercase with hyphens, max 30 chars
- Add `--delete-draft` and `--force` options

### 4. `pflow workflow describe --json` Enhancement (15 min)
**Location**: `src/pflow/cli/commands/workflow.py`

**Just Add**: `--json` option to existing command for structured output

### 5. Agent Instructions Document (1 hour)
**Location**: Create `docs/AGENT_INSTRUCTIONS.md`

**Must Emphasize**:
- Discovery-first workflow (describe intent → get everything needed)
- Single commands provide complete information
- File organization (local drafts vs global library)
- How file path resolution works

## Important Implementation Notes

### LLM Integration Required
The discovery commands MUST use LLM for intelligent selection:
- Extract/reuse logic from ComponentBrowsingNode
- Extract/reuse logic from WorkflowDiscoveryNode
- Handle LLM failures gracefully (fallback to broader results)

### Context Builders May Need Enhancement
Check if these functions return enough detail:
- `build_nodes_context()` - needs full interface specs
- `build_workflows_context()` - needs all metadata

### Reuse Existing Code
- ComponentBrowsingNode selection logic - for discover-nodes
- WorkflowDiscoveryNode selection logic - for discover-workflows
- `Registry.load()` - for loading all nodes
- `WorkflowManager.list_all()` - for loading all workflows
- `WorkflowManager.save()` - for saving to library
- `validate_ir()` - for workflow validation

### File Path Support Already Works!
The `pflow execute` command ALREADY supports:
- `.pflow/workflows/draft.json` - relative paths ✅
- `~/.pflow/workflows/saved.json` - home expansion ✅
- `draft.json` - current directory ✅
- `my-workflow` - saved names ✅

No changes needed to execute command!

## The Agent Experience

```bash
# 1. DISCOVER with rich query (gets everything needed)
$ pflow discover-nodes "I need to analyze GitHub PRs and create reports"
# Returns: Complete interface specs for github-get-pr, llm, write-file, etc.

$ pflow discover-workflows "PR analysis"
# Returns: Full details of pr-analyzer workflow with flow, capabilities, examples

# 2. CREATE workflow locally based on discovered info
$ mkdir -p .pflow/workflows
# Agent creates: .pflow/workflows/draft.json

# 3. TEST with explicit file path
$ pflow execute .pflow/workflows/draft.json --param repo="owner/repo"

# 4. SAVE to library when working
$ pflow workflow save .pflow/workflows/draft.json my-pr-analyzer "Analyzes PRs"

# 5. REUSE from anywhere
$ pflow execute my-pr-analyzer --param repo="owner/repo"
```

## Testing Checklist

### Discovery Commands
- [ ] Rich queries return only relevant components
- [ ] Full interface details included (not just names)
- [ ] LLM failures handled gracefully
- [ ] Performance within 2 seconds

### Save Command
- [ ] Name validation works (lowercase, hyphens, max 30 chars)
- [ ] Saves to ~/.pflow/workflows/
- [ ] --delete-draft removes source
- [ ] --force overwrites existing

### Integration
- [ ] Complete workflow: discover → create → test → save
- [ ] Agent can build workflow from discovered information
- [ ] Saved workflows execute from any location

## Philosophy

Remember: We're exposing the planner's proven discovery approach to agents. They describe what they want in natural language and receive complete, curated information - not catalogs to browse. This is the magic that makes the planner work, now available via CLI.

The key is **rich queries with complete responses** - agents get everything they need in one shot.