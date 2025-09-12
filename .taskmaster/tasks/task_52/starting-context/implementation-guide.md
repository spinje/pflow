# Task 52: Implementation Guide - Requirements and Planning Enhancement

This document captures all critical design decisions, implementation patterns, and architectural insights from the extensive design phase of Task 52. It serves as the authoritative implementation guide.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Pipeline Design](#pipeline-design)
3. [Node Specifications](#node-specifications)
4. [Output Formats](#output-formats)
5. [Conversation Architecture](#conversation-architecture)
6. [Error Handling](#error-handling)
7. [Implementation Patterns](#implementation-patterns)
8. [Critical Design Decisions](#critical-design-decisions)
9. [Common Pitfalls](#common-pitfalls)
10. [Examples](#examples)

## Architecture Overview

### The Core Insight

The planner enhancement adds two new nodes that fundamentally change how workflows are generated:
- **RequirementsAnalysisNode**: Extracts WHAT needs to be done (abstract operations)
- **PlanningNode**: Determines HOW to do it (execution blueprint)

These nodes work together with a **multi-turn conversation** between Planning and Generation only, enabling context accumulation and learning from validation errors.

### The Pipeline Transformation

**Current Path B (Generation)**:
```
Discovery → Component Browsing → Parameter Discovery → Generator → Validation
```

**New Path B**:
```
Discovery → Parameter Discovery → Requirements → Component Browsing → Planning → Generator → Validation
```

**Key Changes**:
1. Parameter Discovery moved earlier (provides templatization)
2. Requirements Analysis added (extracts abstract operations)
3. Planning added (creates execution blueprint)
4. Generator now continues a conversation started by Planning

## Pipeline Design

### The Two-Category Architecture

**Data Extraction Nodes** (Standalone LLM calls):
- ParameterDiscoveryNode - Extracts and templatizes parameters
- RequirementsAnalysisNode - Extracts abstract requirements
- ComponentBrowsingNode - Selects available components
- ParameterMappingNode - Maps parameters to workflow
- MetadataGenerationNode - Generates searchable metadata

**Reasoning/Generation Nodes** (Multi-turn conversation):
- PlanningNode - **STARTS** the conversation with requirements/components as context
- WorkflowGeneratorNode - **CONTINUES** the conversation to generate workflow
- WorkflowGeneratorNode (retry) - **CONTINUES** with validation errors for learning

### Why This Separation Matters

Data extraction doesn't need conversation context - it's just extracting structured data. The conversation is specifically for the **generation pipeline** where Planning reasons about HOW to fulfill requirements, and the Generator builds on that reasoning.

## Node Specifications

### RequirementsAnalysisNode

**Purpose**: Extract abstract operational requirements from templatized input

**Key Implementation Details**:
```python
class RequirementsAnalysisNode(Node):
    def exec(self, prep_res):
        # STANDALONE LLM call - NOT part of conversation
        model = llm.get_model(prep_res["model_name"])

        prompt = f"""Extract requirements from: {prep_res['templatized_input']}

        Requirements should:
        1. Be abstract operations (no specific values)
        2. Keep services explicit (GitHub, Slack, etc.)
        3. Each step does ONE thing
        """

        response = model.prompt(prompt, schema=RequirementsSchema, temperature=0.0)
        return parse_structured_response(response, RequirementsSchema)

    def post(self, shared, prep_res, exec_res):
        shared["requirements_result"] = exec_res

        if not exec_res["is_clear"]:
            shared["error"] = exec_res["clarification_needed"]
            return "clarification_needed"
        return "success"
```

### PlanningNode

**Purpose**: Create execution plan using available components

**Key Implementation Details**:
```python
class PlanningNode(Node):
    def exec(self, prep_res):
        # START the conversation here
        model = llm.get_model(prep_res["model_name"])
        conversation = model.conversation()

        # Build initial context from extracted data
        prompt = f"""Given these requirements:
        {json.dumps(prep_res['requirements_result']['steps'], indent=2)}

        Available components:
        {prep_res['browsed_components']['node_ids']}

        Create an execution plan. End with:
        ### Feasibility Assessment
        **Status**: FEASIBLE/PARTIAL/IMPOSSIBLE
        **Node Chain**: node1 >> node2 >> node3
        """

        response = conversation.prompt(prompt, temperature=0.3)
        plan_markdown = response.text()

        # Parse the structured ending
        parsed = self._parse_plan_assessment(plan_markdown)

        return {
            "plan_markdown": plan_markdown,
            "status": parsed["status"],
            "node_chain": parsed["node_chain"]
        }

    def _parse_plan_assessment(self, markdown: str) -> dict:
        """Extract Status and Node Chain from markdown."""
        import re

        status = "FEASIBLE"  # default
        node_chain = ""

        if match := re.search(r'\*\*Status\*\*:\s*(\w+)', markdown):
            status = match.group(1)

        if match := re.search(r'\*\*Node Chain\*\*:\s*([^\n]+)', markdown):
            node_chain = match.group(1).strip()

        return {"status": status, "node_chain": node_chain}

    def post(self, shared, prep_res, exec_res):
        shared["planning_result"] = exec_res
        shared["planner_conversation"] = prep_res["conversation"]  # CRITICAL!

        if exec_res["status"] == "IMPOSSIBLE":
            return "impossible_requirements"
        elif exec_res["status"] == "PARTIAL":
            return "partial_solution"
        return "continue"
```

### WorkflowGeneratorNode Updates

**Key Changes for Conversation**:
```python
class WorkflowGeneratorNode(Node):
    def prep(self, shared):
        return {
            "conversation": shared.get("planner_conversation"),  # Get from Planning
            "validation_errors": shared.get("validation_errors", []),
            "generation_attempts": shared.get("generation_attempts", 0)
        }

    def exec(self, prep_res):
        conversation = prep_res["conversation"]

        if not conversation:
            # Shouldn't happen, but fallback
            model = llm.get_model(prep_res["model_name"])
            conversation = model.conversation()
            # Would need to rebuild context

        # Determine prompt based on retry status
        if prep_res["validation_errors"] and prep_res["generation_attempts"] > 0:
            # RETRY - conversation already has plan and previous attempt
            errors = "\n".join(f"- {e}" for e in prep_res["validation_errors"])
            prompt = f"The workflow had these validation errors:\n{errors}\n\nPlease fix them."
        else:
            # FIRST ATTEMPT - conversation has plan
            prompt = "Now generate the JSON workflow based on the plan."

        response = conversation.prompt(prompt, schema=FlowIR, temperature=0.0)
        workflow = parse_structured_response(response, FlowIR)

        return {"workflow": workflow.model_dump(by_alias=True, exclude_none=True)}

    def post(self, shared, prep_res, exec_res):
        shared["generated_workflow"] = exec_res["workflow"]
        shared["generation_attempts"] = prep_res["generation_attempts"] + 1
        # PRESERVE conversation for potential retry
        shared["planner_conversation"] = prep_res["conversation"]
        return "validate"
```

## Output Formats

### RequirementsSchema

```python
class RequirementsSchema(BaseModel):
    is_clear: bool
    clarification_needed: Optional[str]
    steps: list[str]  # Abstract operations, NO template variables
    estimated_nodes: int
    required_capabilities: list[str]  # Services needed
    complexity_indicators: dict
```

**Example Output**:
```json
{
    "is_clear": true,
    "clarification_needed": null,
    "steps": [
        "Fetch filtered issues from GitHub repository",
        "Group issues by label categories",
        "Generate markdown changelog",
        "Write changelog to file",
        "Commit changes to repository"
    ],
    "estimated_nodes": 5,
    "required_capabilities": ["github_api", "text_generation", "file_io", "git_operations"],
    "complexity_indicators": {
        "has_conditional": false,
        "has_iteration": true,
        "has_external_services": true,
        "external_services": ["github", "git"]
    }
}
```

### Planning Output (Markdown)

The planning output is **unstructured markdown** with a **parseable ending**:

```markdown
## Workflow Plan

The user wants to create a changelog from GitHub issues. I'll need to fetch the closed issues,
organize them by their labels, and create a well-formatted markdown file.

First, I'll use github-list-issues to get the issues. This gives me the raw data with labels
and titles. Then I'll use the LLM to analyze and group them - issues labeled 'feature' go
under Features section, 'bug' under Bugs, etc.

Next, I'll format this into proper markdown with the version header and bullet points.
Finally, write to CHANGELOG.md and commit with git-commit.

The data flows linearly: issues → grouped_data → formatted_text → file → commit

### Feasibility Assessment
**Status**: FEASIBLE
**Missing Capabilities**: None
**Confidence**: High
**Node Chain**: github-list-issues >> llm >> write-file >> git-commit
```

## Conversation Architecture

### The Multi-Turn Flow

```python
# 1. Data extraction phase (no conversation)
param_discovery = model.prompt(...)     # Standalone - extracts & templatizes
requirements = model.prompt(...)        # Standalone - extracts requirements
components = model.prompt(...)          # Standalone - selects components

# 2. Generation phase (conversation starts)
conversation = model.conversation()

# Planning starts conversation with context
plan_response = conversation.prompt(
    f"Given requirements: {requirements}\nComponents: {components}\nCreate a plan..."
)

# Generator continues conversation
workflow_response = conversation.prompt(
    "Generate the JSON workflow based on the plan",
    schema=FlowIR
)

# On retry - conversation continues with error context
if validation_errors:
    retry_response = conversation.prompt(
        f"Fix these errors: {errors}",
        schema=FlowIR
    )
```

### Context Caching Benefits

With Anthropic's API, the conversation provides automatic context caching:
- Planning: 1000 tokens (full cost)
- Generation: 300 new tokens (70% cached)
- Retry 1: 200 new tokens (85% cached)
- Retry 2: 200 new tokens (90% cached)

**Result: ~70% cost reduction on retries**

## Error Handling

### Failure Modes and Routing

1. **Too Vague Input**
   - Detection: RequirementsAnalysisNode returns `is_clear: false`
   - Action: Return "clarification_needed" → ResultPreparationNode
   - User sees: "Please specify what needs to be processed and what operations to perform"

2. **Impossible Requirements**
   - Detection: PlanningNode returns `Status: IMPOSSIBLE`
   - Action: Return "impossible_requirements" → ResultPreparationNode
   - User sees: "Cannot fulfill requirements. Missing: kubernetes_deployment. Alternatives: Generate deployment YAML"

3. **Partial Solution**
   - Detection: PlanningNode returns `Status: PARTIAL`
   - Action: Return "partial_solution" → Continue or request user decision
   - User sees: "Can fulfill 3 of 5 requirements. Missing: real_time_monitoring"

### What Makes Input "Too Vague"

Input is too vague when we can't extract concrete steps:

**Too Vague** (missing action or target):
- "process the thing" - process what? how?
- "handle this" - handle what? do what?
- "the deployment" - do what with it?

**Clear Enough** (has action + target):
- "generate changelog" - action: generate, target: changelog
- "analyze code quality" - action: analyze, target: code quality

## Implementation Patterns

### Flow Routing Updates

In `src/pflow/planning/flow.py`:

```python
# Current routing (to be updated)
discovery_node - "not_found" >> component_browsing
component_browsing - "generate" >> parameter_discovery
parameter_discovery >> workflow_generator

# New routing
discovery_node - "not_found" >> parameter_discovery  # MOVED
parameter_discovery >> requirements_analysis         # NEW
requirements_analysis >> component_browsing
requirements_analysis - "clarification_needed" >> result_preparation  # NEW
component_browsing - "generate" >> planning         # NEW
planning >> workflow_generator
planning - "impossible_requirements" >> result_preparation  # NEW
planning - "partial_solution" >> workflow_generator  # Or custom handler
```

### Component Browsing Update

Add requirements consideration:

```python
def prep(self, shared):
    # Existing code...
    requirements = shared.get("requirements_result", {})

    # Add to context for prompt
    if requirements:
        context += f"\n\nConsider these requirements:\n"
        for req in requirements.get("steps", []):
            context += f"- {req}\n"
```

## Critical Design Decisions

### 1. Why Requirements Before Planning?

**Requirements define WHAT** (the problem):
- "Fetch filtered issues from GitHub"
- "Generate summary report"
- "Send notification"

**Planning defines HOW** (the solution):
- "Use github-list-issues to fetch"
- "Use llm to generate"
- "Use slack-post-message to send"

This is the natural cognitive flow - understand the problem before designing the solution.

### 2. Why Only Planning/Generator in Conversation?

**Data extraction doesn't need context**:
- Requirements extraction is pattern matching
- Component selection is capability matching

**Generation DOES need context**:
- Planning provides reasoning
- Generator builds on that reasoning
- Retries learn from previous attempts

### 3. Why Abstract Requirements?

Requirements with specific values become too narrow:
- ❌ "Fetch 20 closed issues" - too specific
- ✅ "Fetch filtered issues from GitHub" - reusable

But services must be explicit:
- ❌ "Fetch data from service" - too vague
- ✅ "Fetch issues from GitHub" - clear capability needed

### 4. Why Move Parameter Discovery?

Parameter Discovery creates `templatized_input` which Requirements needs:
- Original: "analyze data.csv and email to john@example.com"
- Templatized: "analyze ${input_file} and email to ${recipient}"
- Requirements sees abstracted version, avoiding value bias

## Common Pitfalls

### DON'T Put Everything in Conversation

❌ **Wrong**: Make all nodes part of conversation
✅ **Right**: Only Planning and Generator participate

### DON'T Include Values in Requirements

❌ **Wrong**: "Fetch 20 closed issues from GitHub"
✅ **Right**: "Fetch filtered issues from GitHub repository"

### DON'T Forget to Preserve Conversation

❌ **Wrong**: Create new conversation on retry
✅ **Right**: Pass `shared["planner_conversation"]` to retry

### DON'T Let Planning Suggest Any Nodes

❌ **Wrong**: Planning suggests nodes not in browsed_components
✅ **Right**: Planning only uses nodes from `browsed_components["node_ids"]`

### DON'T Parse Planning Output in Generator

❌ **Wrong**: Generator tries to parse planning markdown
✅ **Right**: Planning parses its own output, stores structured data

## Examples

### Example 1: Simple Workflow

**Input**: "read ${config_file} and extract version number"

**Requirements Output**:
```json
{
    "is_clear": true,
    "steps": [
        "Read content from configuration file",
        "Extract version information"
    ],
    "estimated_nodes": 2,
    "required_capabilities": ["file_io", "text_processing"]
}
```

**Planning Output**:
```markdown
Simple two-step workflow. Read the file, then use LLM to extract the version.

### Feasibility Assessment
**Status**: FEASIBLE
**Node Chain**: read-file >> llm
```

### Example 2: Impossible Requirements

**Input**: "deploy to kubernetes and monitor with prometheus"

**Requirements Output**:
```json
{
    "is_clear": true,
    "steps": [
        "Deploy application to Kubernetes cluster",
        "Configure Prometheus monitoring"
    ],
    "required_capabilities": ["kubernetes_api", "prometheus_integration"]
}
```

**Planning Output**:
```markdown
Cannot fulfill these requirements with available components.

### Feasibility Assessment
**Status**: IMPOSSIBLE
**Missing Capabilities**: kubernetes_api, prometheus_integration
**Alternatives**: Generate deployment YAML files, create monitoring config
**Node Chain**: None
```

### Example 3: Vague Input

**Input**: "process the data"

**Requirements Output**:
```json
{
    "is_clear": false,
    "clarification_needed": "Please specify: 1) What data to process 2) What type of processing 3) Expected output",
    "steps": [],
    "estimated_nodes": 0
}
```

## Testing Approach

### Unit Tests

```python
def test_requirements_extraction():
    node = RequirementsAnalysisNode()
    shared = {
        "templatized_input": "analyze ${input_file} and email to ${recipient}"
    }

    # Test abstraction
    result = node.run(shared)
    assert "Analyze file content" in shared["requirements_result"]["steps"]
    assert "${input_file}" not in str(shared["requirements_result"]["steps"])

def test_planning_conversation_start():
    node = PlanningNode()
    # Verify conversation is created and stored

def test_generator_conversation_continue():
    # Verify generator uses existing conversation
```

### Integration Tests

```python
def test_full_pipeline_with_retry():
    # Test that conversation persists across retry
    # Verify context accumulation
    # Check cost reduction from caching
```

## Implementation Checklist

- [ ] Move ParameterDiscoveryNode in flow.py routing
- [ ] Create RequirementsAnalysisNode class
- [ ] Create RequirementsSchema Pydantic model
- [ ] Create requirements_analysis.md prompt
- [ ] Create PlanningNode class
- [ ] Add planning markdown parser
- [ ] Create planning.md prompt
- [ ] Update WorkflowGeneratorNode to use conversation
- [ ] Update ComponentBrowsingNode to consider requirements
- [ ] Add new error routing paths
- [ ] Add conversation preservation in retry
- [ ] Create unit tests for new nodes
- [ ] Create integration tests for full pipeline
- [ ] Test conversation context caching
- [ ] Verify 3-retry limit still works
- [ ] Test all failure modes

## Final Notes

This enhancement fundamentally improves the planner by:
1. Understanding requirements before attempting generation
2. Creating a plan before implementation
3. Learning from validation errors through conversation
4. Failing fast with helpful messages for vague/impossible requests
5. Reducing costs through context caching

The key insight: The conversation is specifically for the **generation pipeline** (Planning→Generation→Retry), not the entire planner pipeline. This focused approach keeps the conversation small and relevant while maintaining the benefits of context accumulation.