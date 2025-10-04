# Task 71 Handover: Critical Knowledge Transfer

**⚠️ TO THE IMPLEMENTING AGENT**: Read this entire document before starting ANY implementation. This contains hard-won insights that will save you hours. When you're done reading, just say "Ready to begin Task 71 implementation" - do NOT start coding yet.

## 🔴 The Most Critical Thing to Know

**The nodes can run standalone.** This isn't a hack or workaround - they were DESIGNED for it. Just:
```python
node = WorkflowDiscoveryNode()
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
action = node.run(shared)
```

I spent hours verifying this works. The test suite has 350+ examples proving it. DO NOT extract logic from nodes. DO NOT create wrapper functions. Just use them directly.

## 🚨 The Error Enhancement Trap

**YOU MUST MODIFY TWO FILES** for error enhancement to work:

1. **FIRST**: `src/pflow/execution/executor_service.py` - Extract the error data
2. **THEN**: `src/pflow/cli/main.py` - Display it

If you only update the CLI display layer, you'll be displaying data that doesn't exist. The error information is captured in the shared store but NOT currently extracted into ExecutionResult.errors.

**Critical discovery**: The function is `_build_error_list()` at line 218, NOT `_extract_error_from_shared()` (that doesn't exist). We wasted time looking for the wrong function name.

## 💡 Key Discoveries That Changed Everything

### 1. Direct Node Reuse Pattern
We originally thought we'd need to extract logic from planner nodes. Then we discovered they already work standalone:
- No Flow needed
- No special setup
- Just `node.run(shared)`
- This simplified the entire implementation from 10+ hours to 4 hours

### 2. The CLI Syntax Reality
There is NO `pflow execute` subcommand. The correct syntax is:
```bash
pflow --no-repair workflow.json param1=value param2=value
```
NOT:
```bash
pflow execute workflow.json --param param1=value  # WRONG
```

This affects all examples and documentation.

### 3. The --validate-only Decision
We debated between:
- Separate command: `pflow workflow validate`
- Flag: `pflow --validate-only`

We chose FLAG because:
- Validation happens during execution anyway
- Semantically cleaner (modifier not new action)
- Consistent with --no-repair pattern
- Parameters passed the same way as execution

### 4. Validation MUST Have All Parameters
Late addition to spec: ValidatorNode requires ALL required workflow parameters. This is intentional - validation means FULL validation, not partial. If a workflow has required inputs and they're not provided, validation MUST fail with clear error.

## 🔧 Exact Implementation Details You Need

### Function Locations (Verified)
- `_build_error_list()`: Line 218 in `executor_service.py` (NOT _extract_error_from_shared)
- `_handle_workflow_error()`: Line ~1034 in `main.py`
- CLI flags: Around line 2792 in `main.py`
- Command groups: `workflow.py` and `registry.py` in `src/pflow/cli/commands/`

### The Metadata Generation Verification
We verified MetadataGenerationNode only needs raw workflow IR, NOT ValidatorNode output:
```python
shared = {
    "generated_workflow": validated_ir,  # This is ALL it needs
    "user_input": "",                    # Optional
    "cache_planner": False,
}
```
This means --generate-metadata can be in MVP.

### LLM Model Defaults
Discovery nodes have built-in defaults:
- Model: `anthropic/claude-sonnet-4-0`
- Temperature: `0.0`
- No `node.set_params()` needed
- Just works out of the box

## ⚠️ Anti-Patterns to Avoid

### DON'T Do This:
```python
# Extracting logic from nodes
def discover_workflows(query):
    # Re-implementing node logic
    registry = Registry()
    # ... custom discovery logic ...
```

### DO This Instead:
```python
def discover_workflows(query):
    node = WorkflowDiscoveryNode()
    shared = {"user_input": query}
    node.run(shared)
    # Use results from shared
```

## 🎯 The User's Core Intent

The user wants agents to be first-class citizens in pflow development. They emphasized:
1. **Rich error context** - "just like the repair LLM sees" (but we found repair doesn't see enough either!)
2. **Discovery-first workflow** - agents describe intent, get curated results
3. **Pre-flight validation** - catch errors before execution side effects
4. **No JSON output needed** - agents can parse markdown

The user was very clear: enhanced error output is CRITICAL. They want agents to see the raw API responses, not generic messages.

## 📍 Where We Left Off

All documentation is complete and updated:
- Main task file updated with all changes
- Implementation reference has exact code snippets
- Research findings documented the journey
- Spec updated with validation parameter requirement

The implementation prompt is ready at `task-71-implementation-prompt.md`.

## 🔗 Critical Files You Must Read

In this exact order:
1. `VERIFIED_RESEARCH_FINDINGS.md` - Latest codebase verification results
2. `ERROR_FLOW_ANALYSIS.md` - Understand the two-layer requirement
3. `IMPLEMENTATION_REFERENCE.md` - Has EXACT code to use

## ❓ Open Questions We Didn't Resolve

1. Should discovery commands have a `--json` output option? (Decided: No for now)
2. Should we add `--model` flag to override LLM defaults? (Decided: Not in MVP)
3. Error output for JSON mode - how detailed? (Basic structure defined but could be richer)

## 🎁 The Hidden Gift

The infrastructure is BETTER than we initially thought. Everything we need already exists:
- Nodes designed for reuse
- Error data fully captured
- Context builders return formatted output
- Validation layers already implemented

You're not building new capabilities - you're exposing existing ones. This should give you confidence that the implementation will be straightforward if you follow the patterns.

## 🚀 Your Starting Point

1. Create progress log first
2. Run the context gathering with subagents as shown in the implementation prompt
3. Start with workflow discover - it's the simplest and proves the pattern
4. Test frequently with `pytest tests/test_cli/ -v`

## 💭 Final Wisdom

Trust the node reuse pattern even if it seems too simple. We spent hours verifying it works. The complexity is already handled inside the nodes - your job is just to call them and display results.

The hardest part isn't the implementation - it's believing it's this straightforward.

---

**Remember**: Do NOT start implementing yet. Read all the context files first, understand the patterns, then say "Ready to begin Task 71 implementation" when you're prepared to start.