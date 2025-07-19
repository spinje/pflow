# Task 17 Natural Language Planner - Integration Braindump

## Critical Context for Memory Reset

This document captures EVERYTHING about the current state of Task 17 research integration. You are analyzing research files in `.taskmaster/tasks/task_17/research/` and integrating insights into the implementation details document.

## THE MOST CRITICAL INSIGHT: Meta-Workflow Architecture

### What We Just Discovered
The Natural Language Planner is NOT just a workflow generator. It's a **META-WORKFLOW** that:
1. **Discovers or creates** workflows
2. **Extracts parameters** from natural language ("1234" from "fix github issue 1234")
3. **Maps parameters** to template variables ($issue_number → "1234")
4. **Confirms** with the user
5. **EXECUTES** the workflow with mappings

This means for MVP, EVERY execution goes through the full planner workflow. The planner doesn't just generate and hand off - it orchestrates the entire lifecycle.

### Why This Matters
- The planner includes execution nodes, not just generation
- Parameter mapping is integral to the planner, not a separate system
- This explains why the planner needs PocketFlow's complex branching

## Current Task Status

### What You're Doing
You're analyzing files in `.taskmaster/tasks/task_17/research/` one by one and integrating valid insights into:
- **Primary**: `.taskmaster/tasks/task_17/task-17-context-and-implementation-details.md`
- **Secondary**: `scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`

### Files Already Processed

**IMPORTANT**: The task-17-context-and-implementation-details.md document already contains integrations from OTHER research files that were processed before this session. The document was already comprehensive when you started.

**Files YOU processed in this session:**
1. ✅ **pocketflow-patterns.md** - REJECTED most content as it contained:
   - Hardcoded pattern libraries (anti-pattern)
   - Variable inference logic (anti-pattern)
   - Wrong dependencies (Tasks 18, 19 don't exist)
   - KEPT: Template-driven architecture concept, resolution order validation

2. ✅ **planner-core-insights.md** - Carefully integrated:
   - KEPT: "Find or Build" pattern, success metrics, semantic discovery
   - CORRECTED: Implementation order, oversimplified template handling
   - DISCOVERED: Meta-workflow architecture (critical insight!)

### Files Already Integrated (Before This Session)
The document already contained extensive content from other research files, including:
- Advanced implementation patterns (Progressive Enhancement, Multi-Validator, etc.)
- Flow design patterns (Diamond Pattern, Retry Loop)
- Testing patterns
- Performance considerations
- Multiple anti-patterns

You can identify which sections existed before by looking at the comprehensive structure that was already there.

### Files Possibly Still to Process
Check the research directory for any files not yet integrated:
- `claude-artifacts-v3.md`
- `ambiguity-log.md`
- `workflow-generation-study.md`
- `architectural-insights.md`
- `planner-integration-patterns.md`
- Any others in the directory

## Key Architectural Decisions Made

### 1. Template Variables Are Sacred
- LLM MUST generate `$issue` not "1234"
- Variables enable "Plan Once, Run Forever"
- Runtime resolution, not planning-time resolution

### 2. LLM Generates Complete Mappings
- No inference, no guessing
- LLM provides full `variable_flow` mappings
- System only validates, never infers

### 3. Semantic Discovery Without Embeddings
- Use LLM directly for semantic matching
- "analyze costs" → "aws-cost-analyzer"
- No separate embedding infrastructure

### 4. PocketFlow Only for Planner
- Planner is the ONLY component using PocketFlow
- Everything else uses traditional Python
- This is because of the complex retry/branching logic

## Critical Files and Their Truth Status

### Source of Truth Files
1. **`scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`** - THE source of truth for decisions
2. **`.taskmaster/tasks/task_17/task-17-context-and-implementation-details.md`** - Implementation guidance

### Implementation Structure
```
src/pflow/planning/
├── nodes.py          # All planner nodes (discovery, generator, validator, etc.)
├── flow.py           # create_planner_flow() - the meta-workflow
├── ir_models.py      # Pydantic models for IR generation
├── utils/
└── prompts/
    └── templates.py  # Prompt templates
```

### Key Dependencies
- **Task 14**: Structure documentation (enables path-based mappings) ✅ Done
- **Task 15/16**: Context builder with two-phase discovery ✅ Done
- **LLM Library**: Simon Willison's `llm` with `claude-sonnet-4-20250514`
- **JSON IR Schema**: Already defined in `src/pflow/core/ir_schema.py`

## Anti-Patterns Discovered

### From pocketflow-patterns.md
1. **Hardcoded Pattern Libraries** - Don't create fixed workflow patterns
2. **Variable Inference Logic** - Don't guess variable sources
3. **Template Enhancement** - Don't modify LLM output
4. **Direct CLI Parsing** - MVP routes everything through LLM

### General Anti-Patterns
1. **Stateful Nodes** - All state in shared dict
2. **Complex Actions** - Keep actions as simple strings
3. **Missing variable_flow** - LLM must provide complete mappings

## The Meta-Workflow Implementation

```python
# Simplified view of the planner meta-workflow
class WorkflowDiscoveryNode(Node):
    """Find existing workflow or return not_found"""

class GeneratorNode(Node):
    """Generate new workflow with template variables"""

class ParameterExtractionNode(Node):
    """Extract params from natural language"""

class ParameterMappingNode(Node):
    """Map extracted params to template variables"""

class ConfirmationNode(Node):
    """Show user what will execute"""

class WorkflowExecutionNode(Node):
    """Execute the workflow with mappings"""

# Flow connections
discovery → found → param_extract
discovery → not_found → generator → validator → param_extract
param_extract → param_map → confirm → execute
```

## Success Metrics
- ≥95% success rate for NL → workflow
- ≥90% approval rate (users accept without modification)
- Fast discovery (LLM call + parsing)
- Clear approval (users understand what executes)

## Template Variable System

### Example Flow
```
User: "fix github issue 1234"
↓
Planner generates workflow with: params: {"issue": "$issue_number"}
↓
Planner extracts: {"issue": "1234"}
↓
Planner maps: {"$issue_number": "1234"}
↓
Execution: Workflow runs with mapping applied
```

### Critical: Workflows ALWAYS use templates
- Never hardcode extracted values
- Always use $variables in saved workflows
- Mappings happen at execution time

## What Makes This Integration Challenging

1. **Research files contain misinformation** - Must critically evaluate everything
2. **Meta nature is confusing** - Workflows creating workflows
3. **Template variables are subtle** - Easy to confuse with parameters
4. **MVP vs v2.0 differences** - MVP routes everything through planner

## Current State of Documents

### task-17-context-and-implementation-details.md
- ✅ Added meta-workflow architecture section
- ✅ Added complete implementation pattern with all nodes
- ✅ Added template-driven architecture section
- ✅ Added semantic discovery approach
- ✅ Added success metrics
- ✅ Added comprehensive anti-patterns

### task-17-planner-ambiguities.md
- ✅ Added critical clarification about meta-workflow
- Original sections remain authoritative

## Integration Approach

When analyzing each research file:
1. **Read critically** - Assume it may contain errors
2. **Cross-reference** with ambiguities doc (source of truth)
3. **Extract valid insights** - What aligns with established architecture
4. **Identify contradictions** - What conflicts with truth
5. **Document anti-patterns** - What NOT to do
6. **Ask clarifying questions** - When genuinely ambiguous

## Key Concepts to Remember

1. **Planner is special** - Only component using PocketFlow
2. **Templates enable reuse** - Core to "Plan Once, Run Forever"
3. **LLM does heavy lifting** - Generates complete mappings
4. **Discovery is semantic** - Not string matching
5. **Execution included** - Planner doesn't just generate

## File Paths for Quick Reference

- Research files: `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/research/`
- Context doc: `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/task-17-context-and-implementation-details.md`
- Ambiguities: `/Users/andfal/projects/pflow/scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`

## CRITICAL: What You Just Learned

The user clarified that the planner is a meta-workflow that includes execution. This changes everything about how we think about the planner. It's not just generating workflows - it's orchestrating the entire lifecycle from discovery through execution.

This insight came from asking about "parameter extraction vs template variables" which revealed the fundamental meta nature of the system.
