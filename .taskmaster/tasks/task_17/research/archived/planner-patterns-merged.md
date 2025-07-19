# PocketFlow Patterns for Tasks 15-19: Planner Components

## Task Group Context

- **Tasks**: 16 (Context Builder), 17 (Workflow Generation), 18 (Prompts), 19 (Template Resolver)
- **Goal**: Create the planning system that transforms natural language into template-driven workflows
- **Dependencies**: Task 7 (metadata extraction provides node info)
- **Constraints**: MVP uses LLM for all input (natural language and CLI syntax)

## Overview

The planner components work together to convert user intent into executable workflows. Unlike simple prompt-to-code tools, pflow generates **deterministic, template-driven workflows** that can be reused with different parameters - embodying "Plan Once, Run Forever".

## Core Patterns from Advanced Analysis

### Pattern: Template-Driven Workflow Generation
**Found in**: Tutorial-Cursor, Cold Email, and 5 other repos
**Why It Applies**: Templates enable parameter substitution and workflow reuse

```python
# Not just code generation - template-driven workflow composition
workflow = {
    "nodes": [...],
    "template_inputs": {
        "claude-code": {
            "prompt": "Fix this issue: $issue",  # Template variable
            "dependencies": ["issue"]
        }
    },
    "variable_flow": {
        "issue": "github-get-issue.outputs.issue_data"
    }
}
```

### Pattern: Single-Shot Generation (No Agent Loops)
**Found in**: All 7 repositories avoid regeneration loops
**Why It Applies**: Deterministic planning without iterative refinement

```python
def generate_workflow(user_input, context):
    """Generate complete workflow in one LLM call"""
    # NO: while not valid: regenerate()
    # YES: Generate once with comprehensive context

    response = llm_client.call(
        prompt=build_complete_prompt(user_input, context),
        temperature=0,  # Deterministic
        max_retries=3   # Only for API failures, not validation
    )
    return parse_workflow(response)
```

### Pattern: Structured Context Provision
**Found in**: AI Paul Graham (10 nodes, zero collisions!)
**Why It Applies**: Rich context enables accurate planning

```python
def build_planning_context(registry):
    """Provide comprehensive node information"""
    return {
        "available_nodes": format_node_table(registry),
        "interface_patterns": extract_common_patterns(registry),
        "example_workflows": load_proven_examples(),
        "template_syntax": "$variable references shared store values"
    }
```

## Relevant Cookbook Examples

- `cookbook/pocketflow-thinking`: Chain-of-thought reasoning for planning
- `cookbook/Tutorial-Cursor`: Template-based code generation patterns
- `cookbook/pocketflow-agent`: Decision-making without loops

## Component Patterns

### Task 15: LLM API Client Pattern
**Purpose**: Simple, reliable API interface for planning

```python
# src/pflow/planning/llm_client.py
import os
from typing import Optional
import httpx  # or Simon Willison's llm package

class LLMClient:
    """Simple LLM API client for planning operations"""

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        # Consider using llm package for flexibility
        # import llm
        # self.model = llm.get_model("claude-3-sonnet")

    def call_llm(self, prompt: str, model: str = "claude-3-sonnet",
                 temperature: float = 0.0, max_retries: int = 3) -> str:
        """Call LLM with automatic retry for transient failures"""
        # Key patterns:
        # 1. Temperature=0 for deterministic planning
        # 2. Exponential backoff for API failures only
        # 3. Return text only - parsing happens elsewhere

        for attempt in range(max_retries):
            try:
                # Using httpx
                response = httpx.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": 4096
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()["content"][0]["text"]

            except httpx.TimeoutException:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                raise RuntimeError("LLM API timeout after retries")
```

### Task 16: Context Builder Pattern
**Purpose**: Format registry metadata for LLM consumption

```python
# src/pflow/planning/context_builder.py
from typing import Dict, List

def build_context(registry_metadata: Dict) -> str:
    """Build structured context for LLM planning"""
    # Pattern: Markdown tables for clarity
    context_parts = []

    # 1. Node catalog with natural interfaces
    context_parts.append("## Available Nodes\n")
    for node_id, metadata in registry_metadata.items():
        context_parts.append(f"### {node_id}")
        context_parts.append(f"**Purpose**: {metadata.get('description', 'No description')}")
        context_parts.append(f"**Inputs**: {', '.join(metadata.get('inputs', []))}")
        context_parts.append(f"**Outputs**: {', '.join(metadata.get('outputs', []))}")
        context_parts.append(f"**Parameters**: {format_params(metadata.get('params', {}))}")
        context_parts.append("")

    # 2. Interface patterns (natural keys)
    context_parts.append("## Common Patterns")
    context_parts.append("- GitHub nodes use 'issue_*' prefixed keys")
    context_parts.append("- LLM expects 'prompt', outputs 'response'")
    context_parts.append("- File operations use 'content', 'file_path'")

    # 3. Template syntax
    context_parts.append("## Template Variables")
    context_parts.append("Use $variable_name to reference shared store values")
    context_parts.append("Example: 'Fix this issue: $issue'")

    return "\n".join(context_parts)

def format_params(params: Dict) -> str:
    """Format parameters with types and defaults"""
    if not params:
        return "None"

    formatted = []
    for name, spec in params.items():
        if isinstance(spec, dict):
            formatted.append(f"{name} ({spec.get('type', 'any')}, default: {spec.get('default', 'none')})")
        else:
            formatted.append(f"{name} (default: {spec})")

    return ", ".join(formatted)
```

### Task 17: Workflow Generation Engine Pattern
**Purpose**: Core engine that creates template-driven workflows

```python
# src/pflow/planning/workflow_compiler.py
import json
from typing import Dict, Any

class WorkflowCompiler:
    """Generates template-driven workflows from natural language"""

    def __init__(self, llm_client, prompt_templates):
        self.llm = llm_client
        self.prompts = prompt_templates

    def compile_request(self, user_input: str, node_context: str) -> Dict[str, Any]:
        """Transform user input into workflow IR with templates"""

        # 1. Build comprehensive prompt
        prompt = self.prompts.WORKFLOW_GENERATION.format(
            user_input=user_input,
            node_context=node_context,
            template_examples=self._get_template_examples()
        )

        # 2. Single-shot generation (no loops!)
        response = self.llm.call_llm(prompt, temperature=0)

        # 3. Parse and validate
        try:
            workflow = json.loads(response)
            self._validate_workflow(workflow)
            return workflow
        except json.JSONDecodeError:
            # Extract JSON from response if wrapped in text
            workflow = self._extract_json(response)
            self._validate_workflow(workflow)
            return workflow

    def _validate_workflow(self, workflow: Dict):
        """Basic structural validation"""
        required = ["nodes", "edges", "start_node"]
        for field in required:
            if field not in workflow:
                raise ValueError(f"Missing required field: {field}")

        # Validate template variables are defined
        if "template_inputs" in workflow:
            self._validate_templates(workflow["template_inputs"],
                                   workflow.get("variable_flow", {}))

    def _validate_templates(self, templates: Dict, variable_flow: Dict):
        """Ensure all $variables have sources"""
        for node_id, inputs in templates.items():
            for input_key, template in inputs.items():
                # Find all $variables in template
                import re
                variables = re.findall(r'\$(\w+)', template)

                for var in variables:
                    if var not in variable_flow:
                        raise ValueError(
                            f"Template variable ${var} has no source in variable_flow"
                        )

    def _get_template_examples(self) -> str:
        """Provide examples of template-driven workflows"""
        return """
Example template-driven workflow:
{
    "nodes": [
        {"id": "github-get-issue", "type": "github-get-issue", "params": {}},
        {"id": "claude-code", "type": "claude-code", "params": {"temperature": 0.2}},
        {"id": "llm", "type": "llm", "params": {"model": "gpt-4"}}
    ],
    "edges": [
        {"from": "github-get-issue", "to": "claude-code"},
        {"from": "claude-code", "to": "llm"}
    ],
    "start_node": "github-get-issue",
    "template_inputs": {
        "claude-code": {
            "prompt": "Fix this issue:\\n$issue",
            "dependencies": ["issue"]
        },
        "llm": {
            "prompt": "Write a commit message for: $code_report",
            "dependencies": ["code_report"]
        }
    },
    "variable_flow": {
        "issue": "github-get-issue.outputs.issue_data",
        "code_report": "claude-code.outputs.code_report"
    }
}
"""
```

### Task 18: Prompt Templates Pattern
**Purpose**: Effective prompts for workflow generation

```python
# src/pflow/planning/prompts.py

class PlannerPrompts:
    """Prompt templates for planning operations"""

    # Pattern from analysis: Specific, structured prompts
    WORKFLOW_GENERATION = """You are a workflow planner for pflow, a tool that creates deterministic, reusable workflows.

Available nodes and their interfaces:
{node_context}

User request: {user_input}

Generate a JSON workflow that:
1. Uses template variables ($variable) for dynamic values
2. Connects nodes with natural shared store keys
3. Includes all necessary parameters
4. Maps template variables to node outputs

{template_examples}

Rules:
- Use simple, linear node sequences (no complex branching)
- Prefer natural key names (avoid generic 'data', 'output')
- Each node should have a single, clear purpose
- Template variables enable reuse with different parameters

Output only valid JSON matching the example structure.
"""

    ERROR_RECOVERY = """The previous workflow generation failed with this error:
{error_message}

Original request: {user_input}

Please generate a corrected workflow that addresses the error.
Focus on: {error_hint}

Output only valid JSON.
"""

    # Pattern: YAML for structured output (more reliable than JSON)
    YAML_WORKFLOW_GENERATION = """Generate a workflow in YAML format:

nodes:
  - id: node-name
    type: node-type
    params:
      param1: value1

edges:
  - from: node1
    to: node2

template_inputs:
  node-id:
    input_key: "Template with $variable"

Output only valid YAML.
"""
```

### Task 19: Template Resolver Pattern
**Purpose**: Validate template variables for planner

```python
# src/pflow/planning/utils.py
import re
from typing import Dict, Set, List

def validate_template_variables(template_str: str, available_vars: Set[str]) -> List[str]:
    """Validate that all template variables can be resolved"""
    # Pattern: Simple regex-based validation
    # This is NOT runtime resolution - just planning validation

    # Find all $variable or ${variable} patterns
    variables = re.findall(r'\$\{?(\w+)\}?', template_str)

    missing = []
    for var in variables:
        if var not in available_vars:
            missing.append(var)

    return missing

def extract_dependencies(workflow: Dict) -> Dict[str, Set[str]]:
    """Extract variable dependencies for each node"""
    dependencies = {}

    if "template_inputs" in workflow:
        for node_id, inputs in workflow["template_inputs"].items():
            node_deps = set()

            for input_key, template in inputs.items():
                if isinstance(template, str):
                    # Extract variables from template
                    variables = re.findall(r'\$\{?(\w+)\}?', template)
                    node_deps.update(variables)

            dependencies[node_id] = node_deps

    return dependencies

def build_resolution_order(workflow: Dict) -> List[str]:
    """Determine order for template resolution based on dependencies"""
    deps = extract_dependencies(workflow)

    # Simple topological sort
    resolved = []
    available_vars = set()

    # Add stdin if piped input expected
    if workflow.get("expects_stdin", False):
        available_vars.add("stdin")

    # Keep trying to resolve nodes until all done
    while len(resolved) < len(workflow["nodes"]):
        made_progress = False

        for node in workflow["nodes"]:
            node_id = node["id"]
            if node_id in resolved:
                continue

            # Check if all dependencies available
            node_deps = deps.get(node_id, set())
            if node_deps.issubset(available_vars):
                resolved.append(node_id)

                # Add this node's outputs to available vars
                node_type = node["type"]
                # Would look up actual outputs from registry
                # For now, simplified
                available_vars.add(f"{node_id}_output")
                made_progress = True

        if not made_progress:
            # Circular dependency or missing variable
            unresolved = [n["id"] for n in workflow["nodes"] if n["id"] not in resolved]
            raise ValueError(f"Cannot resolve nodes: {unresolved}")

    return resolved
```

## Patterns to Adopt

### Pattern: LLM Package Integration
**Source**: Simon Willison's llm package
**Compatibility**: ✅ Direct
**Description**: Consider using `llm` package for flexibility

```python
# Alternative implementation using llm package
import llm

def call_llm_simple(prompt: str, model: str = "claude-3-sonnet-20240229") -> str:
    """Simplified LLM calling with llm package"""
    model_instance = llm.get_model(model)
    response = model_instance.prompt(prompt, temperature=0)
    return response.text()
```

### Pattern: Deterministic Generation
**Source**: All successful repos use temperature=0
**Compatibility**: ✅ Direct
**Description**: Ensure reproducible workflow generation

### Pattern: Natural Language as DSL
**Source**: MVP design decision
**Compatibility**: ✅ Direct
**Description**: Treat CLI syntax as natural language

```python
def interpret_cli_syntax(user_input: str) -> str:
    """MVP: All input goes through LLM"""
    # Both work the same in MVP:
    # - "summarize this video"
    # - "yt-transcript --url=X >> llm --prompt='summarize'"

    # LLM interprets CLI-like syntax as domain-specific language
    return user_input  # Pass directly to LLM
```

## Patterns to Avoid

### Pattern: Iterative Refinement Loops
**Issue**: Non-deterministic, expensive, slow
**Alternative**: Single-shot generation with rich context

### Pattern: Code Generation
**Issue**: We're generating workflows, not code
**Alternative**: JSON/YAML IR generation only

### Pattern: Complex State Management
**Issue**: Planner should be stateless
**Alternative**: Each planning request independent

## Implementation Guidelines

1. **Keep LLM client simple** - Just API calls, no complex logic
2. **Rich context is key** - More context = better generation
3. **Templates enable reuse** - Core value proposition
4. **Validate early** - Catch errors in planner, not runtime
5. **Single-shot generation** - No loops or refinement

## Integration Example

```python
# How components work together
def plan_workflow(user_input: str):
    # 1. Get node metadata (Task 7 provides this)
    registry = get_node_registry()

    # 2. Build context (Task 16)
    context = build_context(registry)

    # 3. Create LLM client (Task 15)
    llm = LLMClient()

    # 4. Load prompts (Task 18)
    prompts = PlannerPrompts()

    # 5. Generate workflow (Task 17)
    compiler = WorkflowCompiler(llm, prompts)
    workflow = compiler.compile_request(user_input, context)

    # 6. Validate templates (Task 19)
    resolution_order = build_resolution_order(workflow)

    return workflow
```

## Testing Approach

```python
def test_planner_integration():
    # Mock LLM responses
    with patch('llm_client.call_llm') as mock_llm:
        mock_llm.return_value = json.dumps({
            "nodes": [...],
            "template_inputs": {...}
        })

        workflow = plan_workflow("fix github issue 123")

        # Verify workflow structure
        assert "template_inputs" in workflow
        assert "variable_flow" in workflow

def test_template_validation():
    # Test missing variable detection
    template = "Fix issue: $issue_data"
    available = {"issue"}  # Wrong name

    missing = validate_template_variables(template, available)
    assert missing == ["issue_data"]
```

## Summary

The planner components work together to convert user intent into reusable, template-driven workflows:

1. **LLM Client** (Task 15) - Simple, reliable API interface
2. **Context Builder** (Task 16) - Rich metadata formatting
3. **Workflow Engine** (Task 17) - Single-shot generation
4. **Prompt Templates** (Task 18) - Structured, effective prompts
5. **Template Resolver** (Task 19) - Variable validation

Key insight: **Templates enable "Plan Once, Run Forever"** - the same workflow can be reused with different parameters, delivering 10x efficiency gains.
