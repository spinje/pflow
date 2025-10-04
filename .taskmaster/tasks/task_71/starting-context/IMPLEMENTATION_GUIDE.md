# Task 71 Implementation Guide

## Quick Start

This task adds CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery - the same way the planner works internally. Critically includes validation for pre-flight checks. Total time: ~3-4 hours.

## Key Insight

Agents need to describe what they want to build in natural language and receive complete, curated information - not browse catalogs. We're exposing the planner's discovery approach as CLI commands. Plus, agents NEED pre-flight validation to catch errors before execution.

## What to Build

### 1. `pflow workflow discover` Command (30 min)
**Location**: `src/pflow/cli/commands/workflow.py`

**Key Points**:
- Takes rich natural language query: "I need to analyze pull requests"
- Uses WorkflowDiscoveryNode directly via `node.run(shared)`
- Returns matching workflows with full metadata
- Shows confidence score

**Implementation Pattern**:
```python
node = WorkflowDiscoveryNode()
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
action = node.run(shared)
# Results in shared["discovery_result"] and shared["found_workflow"]
```

### 2. `pflow registry discover` Command (30 min)
**Location**: `src/pflow/cli/commands/registry.py`

**Key Points**:
- Takes rich natural language query: "I need to fetch GitHub data"
- Uses ComponentBrowsingNode directly via `node.run(shared)`
- Returns relevant nodes with FULL interface details
- Outputs planning context directly

**Implementation Pattern**:
```python
node = ComponentBrowsingNode()
shared = {"user_input": query}
action = node.run(shared)
# Results in shared["planning_context"] with full details
```

### 3. `--validate-only` Flag (45 min) - CRITICAL
**Location**: `src/pflow/cli/main.py`

**Key Points**:
- Add flag to main CLI command
- Takes workflow and parameters like normal execution
- Uses ValidatorNode's 4-layer validation
- NO side effects - pure validation
- Returns specific, actionable errors

**Implementation Pattern**:
```python
# Add flag:
@click.option("--validate-only", is_flag=True, help="Validate without executing")

# In workflow_command:
if validate_only:
    node = ValidatorNode()
    shared = {"generated_workflow": workflow_ir, "workflow_inputs": params}
    action = node.run(shared)
    # Results in shared["validation_result"] with errors/success
    # Exit after displaying results
```

### 4. `pflow workflow save` Command (30 min)
**Location**: `src/pflow/cli/commands/workflow.py`

**Key Points**:
- Load workflow from file path
- Use `WorkflowManager.save()` directly
- Validate name format: lowercase with hyphens, max 30 chars
- Add `--delete-draft`, `--force`, and `--generate-metadata` options

### 5. `pflow registry describe` Command (30 min)
**Location**: `src/pflow/cli/commands/registry.py`

**Key Points**:
- Takes one or more node IDs as arguments
- Uses `build_planning_context()` directly
- Returns complete interface specifications
- Shows examples when available

### 6. Enhanced Error Output (30 min) - CRITICAL
**Location**: `src/pflow/cli/main.py`

**Key Points**:
- Display ExecutionResult.errors details instead of generic message
- Show node_id, category, message, available fields
- Especially important with --no-repair flag
- Helps agents understand and fix errors

**Implementation Pattern**:
```python
if result.errors:
    for error in result.errors:
        click.echo(f"✗ Failed at node: {error.get('node_id')}", err=True)
        click.echo(f"  Category: {error.get('category')}", err=True)
        click.echo(f"  Message: {error.get('message')}", err=True)
        # Show available fields if template error
```

## Important Implementation Notes

### Direct Node Reuse is KEY
The planner nodes work standalone! No extraction needed:
```python
# This is ALL you need:
node = SomePlannerNode()
shared = {"user_input": query}
action = node.run(shared)
# Access results from shared dict
```

### Nodes Handle Everything
- LLM integration ✅
- Error handling ✅
- Context building ✅
- Structured output ✅

### Validation is Critical
Without the validate command, agents must:
- Execute to find errors (bad!)
- Deal with partial execution
- Cannot iterate quickly
- Poor developer experience

### File Path Support Already Works!
The `pflow execute` command ALREADY supports:
- `.pflow/workflows/draft.json` - relative paths ✅
- `~/.pflow/workflows/saved.json` - home expansion ✅
- `draft.json` - current directory ✅
- `my-workflow` - saved names ✅

No changes needed to execute command!

## The Agent Experience

```bash
# 1. DISCOVER with rich queries
$ pflow workflow discover "I need to analyze PRs"
$ pflow registry discover "I need GitHub and LLM nodes"

# 2. GET DETAILS if needed
$ pflow registry describe github-get-pr llm

# 3. CREATE workflow locally
$ mkdir -p .pflow/workflows
# Agent creates: .pflow/workflows/draft.json

# 4. VALIDATE before execution (CRITICAL!)
$ pflow --validate-only .pflow/workflows/draft.json repo=owner/repo pr_number=123
# Fix any errors...

# 5. TEST with explicit file path
$ pflow --no-repair .pflow/workflows/draft.json repo=owner/repo pr_number=123
# Enhanced error output helps debug

# 6. SAVE to library when working
$ pflow workflow save .pflow/workflows/draft.json my-pr-analyzer "Analyzes PRs" --generate-metadata

# 7. REUSE from anywhere
$ pflow my-pr-analyzer repo=owner/repo pr_number=456
```

## Testing Checklist

### Discovery Commands
- [ ] Rich queries return only relevant components
- [ ] Full interface details included (not just names)
- [ ] Node execution works directly
- [ ] LLM failures handled gracefully

### Validation Command
- [ ] All 4 validation layers work
- [ ] Returns specific error messages
- [ ] No side effects occur
- [ ] Requires all required parameters (fails with clear error if missing)

### Save Command
- [ ] Name validation works (lowercase, hyphens, max 30 chars)
- [ ] Saves to ~/.pflow/workflows/
- [ ] --generate-metadata creates rich metadata
- [ ] --delete-draft removes source
- [ ] --force overwrites existing

### Registry Describe
- [ ] Multiple node IDs work
- [ ] Unknown nodes error gracefully
- [ ] Full specifications displayed

### Integration
- [ ] Complete workflow: discover → create → validate → test → save
- [ ] Agent can build workflow from discovered information
- [ ] Validation catches errors before execution
- [ ] Saved workflows execute from any location

## Common Pitfalls to Avoid

1. **DON'T extract logic from nodes** - Use them directly!
2. **DON'T create wrapper functions** - `node.run(shared)` is enough
3. **DON'T skip validation command** - It's critical for agent UX
4. **DON'T forget --generate-metadata** - Rich metadata helps discovery

## Philosophy

Remember: We're exposing the planner's proven discovery approach to agents. They describe what they want in natural language and receive complete, curated information - not catalogs to browse. Plus validation for safe iteration.

The magic is:
1. **Rich queries with complete responses** - everything in one shot
2. **Direct node reuse** - no extraction, just `node.run(shared)`
3. **Pre-flight validation** - catch errors before execution
4. **Intelligent selection** - LLM picks exactly what's needed