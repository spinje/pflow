# Task 17 Natural Language Planner - Integration Braindump

## Critical Context for Memory Reset

This document captures EVERYTHING about the current state of Task 17 research integration. You are analyzing research files in `.taskmaster/tasks/task_17/research/` and integrating insights into the implementation details document.

## THE MOST CRITICAL INSIGHT: Meta-Workflow Architecture with Two Paths

### What We Now Understand Correctly
The Natural Language Planner is a **META-WORKFLOW** that orchestrates the entire lifecycle of finding or creating workflows. It has TWO DISTINCT PATHS that converge at a critical verification point:

1. **Path A: Reuse Existing** - WorkflowDiscoveryNode finds complete workflow → ParameterExtractionNode
2. **Path B: Generate New** - WorkflowDiscoveryNode fails → ComponentBrowsingNode → GeneratorNode → ValidatorNode → MetadataGenerationNode → ParameterExtractionNode

Both paths CONVERGE at ParameterExtractionNode, which serves as a verification gate ensuring the workflow can actually execute.

### Critical Correction: The Planner Does NOT Execute User Workflows
The planner:
1. **Discovers or creates** workflows
2. **Extracts AND verifies** parameters can be satisfied
3. **Prepares structured output** for the CLI
4. **Returns to CLI** for approval and execution

The CLI handles:
1. **User approval** of the generated/found workflow
2. **Workflow storage** to ~/.pflow/workflows/
3. **Actual execution** with parameter substitution

### Why This Architecture Matters
- **Two paths converge** at parameter extraction for verification
- **Parameter extraction is a gate** - prevents execution if params missing
- **Clean separation** - planner plans, CLI executes
- **Every MVP execution** goes through the planner for natural language processing

## Current Task Status

### What You're Doing
You're analyzing files in `.taskmaster/tasks/task_17/research/` one by one and integrating valid insights into:
- **Primary**: `.taskmaster/tasks/task_17/task-17-context-and-implementation-details.md` (READ THE FULL FILE if you have not already)
- **Secondary**: `scratchpads/critical-user-decisions/task-17-planner-ambiguities.md` (READ THE FULL FILE if you have not already)

### Files Already Processed

**IMPORTANT**: The task-17-context-and-implementation-details.md document has been UPDATED to reflect the correct architecture with two paths converging at parameter extraction.

**Files processed and insights integrated:**
1. ✅ **pocketflow-patterns.md** - REJECTED most content as anti-patterns
2. ✅ **planner-core-insights.md** - Integrated valid insights
3. ✅ **Architecture corrections** - Fixed misconceptions about single discovery node

### Critical Resolutions (2025-07-22)
- ✅ **MetadataGenerationNode** added after ValidatorNode (only processes valid workflows)
- ✅ **Complete workflow matching** means fully satisfying user intent
- ✅ **Component browsing** includes workflows as sub-workflows
- ✅ **Two-stage parameter handling** clarified
- ✅ **Validation depth** includes template path verification
- ✅ **Retry limit** standardized at 3 for all nodes
- ✅ **Retry optimization** - validation failures skip metadata generation entirely

## Key Architectural Decisions Made

### 1. Two Distinct Discovery Nodes
- **WorkflowDiscoveryNode** - Finds COMPLETE workflows that satisfy entire intent
- **ComponentBrowsingNode** - Browses for building blocks (only executes if no complete match)
- These are SEPARATE nodes with different purposes

### 2. Parameter Extraction as Convergence and Verification
- Both paths converge at ParameterExtractionNode
- This node extracts parameters AND verifies executability
- If required params missing → cannot execute
- This is a critical gate preventing execution failures

### 3. Template Variables Are Sacred
- LLM MUST generate `$issue_number` not "1234"
- Variables enable "Plan Once, Run Forever"
- Runtime resolution by proxy, not planning-time resolution
- Templates go directly in node params

### 4. No Complex Mapping Structures
- No `template_inputs` or `variable_flow` fields (they don't exist!)
- Just use `$variables` directly in params
- Runtime proxy handles resolution transparently

### 5. PocketFlow Only for Planner
- Planner is the ONLY component using PocketFlow
- Everything else uses traditional Python
- This is because of the complex branching and retry logic

## Critical Files and Their Truth Status

### Source of Truth Files
1. **`scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`** - THE source of truth for decisions
2. **`.taskmaster/tasks/task_17/task-17-context-and-implementation-details.md`** - Updated implementation guidance

### Implementation Structure
```
src/pflow/planning/
├── nodes.py          # All planner nodes (discovery, browsing, generator, validator, etc.)
├── flow.py           # create_planner_flow() - the meta-workflow with two paths
├── ir_models.py      # Pydantic models for IR generation
├── utils/
└── prompts/
    └── templates.py  # Prompt templates
```

### Key Dependencies
- **Task 14**: Structure documentation (enables path-based mappings) ✅ Done
- **Task 15/16**: Context builder with smart context loading ✅ Done
- **LLM Library**: Simon Willison's `llm` with `claude-sonnet-4-20250514`
- **JSON IR Schema**: Already defined in `src/pflow/core/ir_schema.py`

## Anti-Patterns Discovered

### Critical Anti-Patterns
1. **WorkflowExecutionNode** - Planner NEVER executes user workflows
2. **Complex mapping structures** - No template_inputs or variable_flow
3. **Single discovery node** - Must have separate WorkflowDiscoveryNode and ComponentBrowsingNode
4. **Parameter extraction without verification** - Must verify executability
5. **Hardcoded values in workflows** - Always use template variables

### From Research Files
1. **Hardcoded Pattern Libraries** - Don't create fixed workflow patterns
2. **Variable Inference Logic** - Don't guess variable sources
3. **Template Enhancement** - Don't modify LLM output
4. **Direct CLI Parsing** - MVP routes everything through LLM

## The Correct Meta-Workflow Implementation

```python
# Correct view of the planner meta-workflow with two paths
class WorkflowDiscoveryNode(Node):
    """Find COMPLETE workflows that satisfy entire user intent"""
    def exec(self, shared):
        # Search for exact match that satisfies full intent
        # ONLY returns "found_existing" if workflow completely satisfies user request
        if found_complete_match:
            return "found_existing"
        else:
            return "not_found"

class ComponentBrowsingNode(Node):
    """Browse for building blocks ONLY if no complete workflow found

    Can select both individual nodes AND existing workflows to use as sub-workflows
    """
    def exec(self, shared):
        # Use smart context loading
        # Browse for components to build new workflow
        # Can include existing workflows as building blocks!
        return "generate"

class GeneratorNode(Node):
    """Generate new workflow with template variables in params

    Creates workflow structure with template variables (e.g., $issue_number)
    NOT hardcoded values
    """
    def exec(self, shared):
        # Generate workflow
        return "validate"

class ValidatorNode(Node):
    """Validate generated workflow structure

    Max retries: 3 for all error types
    Validates template paths exist using structure documentation
    Returns "valid" or "invalid" (back to generator)
    """
    def exec(self, shared):
        # Validate workflow
        if is_valid:
            return "valid"  # Proceed to metadata
        else:
            return "invalid"  # Back to generator

class MetadataGenerationNode(Node):
    """Extract metadata from VALIDATED workflow

    Only runs after successful validation
    Creates suggested_name, description, inputs, outputs based on the workflow
    """
    def exec(self, shared):
        workflow = shared["generated_workflow"]
        # Extract metadata from the validated workflow structure
        shared["workflow_metadata"] = extract_metadata(workflow)
        return "param_extract"

class ParameterExtractionNode(Node):
    """CONVERGENCE POINT - Extract params AND verify executability

    Two-stage process:
    1. For found workflows: Maps user values to existing template variables
    2. For generated workflows: Maps user values to template variables created by GeneratorNode
    """
    def exec(self, shared):
        # Extract parameters from natural language
        # Map concrete values (e.g., "1234") to template variables (e.g., $issue_number)
        # VERIFY all required params available
        if missing_params:
            return "params_incomplete"  # Cannot execute!
        return "params_complete"

class ParameterPreparationNode(Node):
    """Prepare parameters for CLI execution"""

class ResultPreparationNode(Node):
    """Package everything for CLI handoff"""

# Flow connections showing TWO PATHS
discovery → "found_existing" → param_extract  # Path A
discovery → "not_found" → browsing → generator → validator → metadata → param_extract  # Path B
validator → "invalid" → generator  # Retry loop (skips metadata)
# BOTH PATHS CONVERGE at param_extract
param_extract → "params_complete" → param_prep → result_prep
param_extract → "params_incomplete" → result_prep  # With error
```

## Success Metrics
- ≥95% success rate for NL → workflow
- ≥90% approval rate (users accept without modification)
- Fast discovery (LLM call + parsing)
- Clear approval (users understand what executes)
- Successful parameter verification (workflows only execute when params available)

## Template Variable System

### Correct Example Flow
```
User: "fix github issue 1234"
↓
[PLANNER META-WORKFLOW]
Path A (if workflow exists):
  WorkflowDiscoveryNode: Found 'fix-issue' workflow
  ↓
  ParameterExtractionNode:
    - Extract: {"issue_number": "1234"}
    - Verify: Workflow needs issue_number ✓
  ↓
  ResultPreparationNode: Package for CLI

Path B (if no workflow exists):
  WorkflowDiscoveryNode: No complete match
  ↓
  ComponentBrowsingNode: Find github-get-issue, claude-code nodes
    (Can also select existing workflows as sub-workflows!)
  ↓
  GeneratorNode: Create workflow with params: {"issue": "$issue_number"}
    (Creates template variables, not hardcoded "1234")
  ↓
  ValidatorNode: Validate structure (max 3 retries)
    - If invalid → back to GeneratorNode (metadata skipped)
    - If valid → continue
  ↓
  MetadataGenerationNode: Extract metadata (name, description, inputs, outputs)
    (Only runs on validated workflows)
  ↓
  ParameterExtractionNode: Maps "1234" → $issue_number
    (Two-stage: Generator creates templates, this node maps values)
  ↓
  ResultPreparationNode: Package for CLI

[CLI EXECUTION]
- Shows approval prompt
- Saves workflow (preserving $variables)
- Executes with parameter substitution
```

### Critical: Templates in Params
```json
{
  "nodes": [
    {
      "id": "get-issue",
      "type": "github-get-issue",
      "params": {"issue": "$issue_number"}  // Template directly in params!
    }
  ]
}
```

## What Makes This Integration Challenging

1. **Early misconceptions persist** - Must correct wrong understanding
2. **Two-path architecture is subtle** - Easy to miss the convergence
3. **Parameter extraction dual role** - Both extraction AND verification
4. **Separation of concerns** - Planner vs CLI responsibilities
5. **Template variables in params** - Not in separate structures

## Current State of Documents

### task-17-context-and-implementation-details.md
- ✅ UPDATED with correct two-path architecture
- ✅ Added mermaid diagram showing convergence
- ✅ Separated WorkflowDiscoveryNode and ComponentBrowsingNode
- ✅ Emphasized parameter extraction as verification
- ✅ Removed confusing "two-phase discovery" terminology
- ✅ Preserved all valuable patterns and anti-patterns

### task-17-planner-ambiguities.md
- Original sections remain authoritative
- Contains critical decisions about template variables

### New Architecture Documents
- ✅ Created task-17-planner-meta-workflow-architecture.md
- ✅ Created task-17-update-plan.md

## Integration Approach

When analyzing each research file:
1. **Check against correct architecture** - Two paths converging at parameter extraction
2. **Verify node names** - WorkflowDiscoveryNode vs ComponentBrowsingNode
3. **Look for anti-patterns** - WorkflowExecutionNode, complex mappings
4. **Extract valid insights** - What aligns with two-path architecture
5. **Document corrections** - What was wrong and why

## Key Concepts to Remember

1. **Two distinct paths** - Found vs Generate, converging at verification
2. **Parameter extraction verifies** - Not just extraction, but feasibility check
3. **Planner returns to CLI** - Never executes user workflows
4. **Templates in params** - Direct usage, no complex structures
5. **Smart context loading** - Not "two-phase discovery"

## Critical Corrections Made

1. **Removed WorkflowExecutionNode** - Planner doesn't execute
2. **Split discovery into two nodes** - WorkflowDiscoveryNode and ComponentBrowsingNode
3. **Emphasized convergence** - Both paths meet at parameter extraction
4. **Added verification role** - Parameter extraction ensures executability
5. **Clarified handoff** - Planner returns results to CLI

## File Paths for Quick Reference

- Research files: `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/research/`
- Context doc: `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/task-17-context-and-implementation-details.md`
- Ambiguities: `/Users/andfal/projects/pflow/scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`

## CRITICAL: Current Understanding

The planner is a meta-workflow with two distinct paths that converge at a verification point:
- **Path A**: Found existing workflow → verify parameters → return to CLI
- **Path B**: Generate new workflow → validate → verify parameters → return to CLI

The convergence at ParameterExtractionNode ensures that only executable workflows (with all required parameters available) proceed to execution. This prevents runtime failures and provides clear feedback when parameters are missing.

The planner NEVER executes user workflows - it only prepares them for CLI execution.
