# PocketFlow Patterns for Task 17: Implement LLM-based Workflow Generation Engine

## Task Context

- **Goal**: Create the core engine that transforms natural language into template-driven workflows
- **Dependencies**: Tasks 15 (LLM client), 16 (context builder), 18 (prompts), 19 (template resolver)
- **Constraints**: Single-shot generation, deterministic output, template-driven design

## Overview

Task 17 is the heart of pflow's planning system. It transforms user intent (natural language or CLI syntax) into deterministic, template-driven workflows that embody "Plan Once, Run Forever". This is NOT a code generator - it's a workflow composer that creates reusable execution plans.

## Core Patterns from Advanced Analysis

### Pattern: Template-Driven Workflow Architecture
**Found in**: Tutorial-Cursor, Cold Email show template composition
**Why It Applies**: Templates are the key to workflow reusability

```python
# Core insight: Workflows are templates with variable substitution
workflow = {
    "nodes": [...],  # Static structure
    "template_inputs": {  # Dynamic content
        "claude-code": {
            "prompt": "Fix this issue:\n$issue\n\nGuidelines:\n$coding_standards",
            "dependencies": ["issue", "coding_standards"]
        }
    },
    "variable_flow": {  # Variable sources
        "issue": "github-get-issue.outputs.issue_data",
        "coding_standards": "read-file.outputs.content"
    }
}
```

### Pattern: Semantic Workflow Understanding
**Found in**: AI Paul Graham (complex flows without regeneration)
**Why It Applies**: LLM understands intent, not just syntax

```python
def interpret_user_intent(user_input: str) -> Dict:
    """LLM interprets both natural language and CLI-like syntax"""
    # These all produce the same workflow:
    # 1. "fix github issue 123"
    # 2. "I need to resolve the bug in issue 123"
    # 3. "github-get-issue --issue=123 >> claude-code"

    # LLM understands:
    # - "fix" implies: get issue → code solution → create PR
    # - "123" is an issue number
    # - Missing steps can be inferred
```

### Pattern: Workflow Pattern Library
**Found in**: Reusable flows across all repos
**Why It Applies**: Common patterns accelerate planning

```python
WORKFLOW_PATTERNS = {
    "github_fix": [
        "github-get-issue",
        "claude-code",  # With template: "Fix: $issue"
        "git-commit",
        "git-push",
        "github-create-pr"
    ],
    "document_analysis": [
        "read-file",
        "llm",  # With template: "Analyze: $content"
        "write-file"
    ],
    "video_summary": [
        "yt-transcript",
        "llm",  # With template: "Summarize: $transcript"
        "write-file"
    ]
}
```

## Relevant Cookbook Examples

- `cookbook/pocketflow-thinking`: Reasoning chains for workflow planning
- `cookbook/pocketflow-agent`: Decision-making without loops
- `cookbook/Danganronpa`: Programmatic flow construction

## Core Implementation Pattern

### The Workflow Generation Engine

```python
# src/pflow/planning/workflow_compiler.py
import json
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

@dataclass
class WorkflowIntent:
    """Parsed user intent"""
    action: str  # "fix", "analyze", "summarize"
    target: str  # "github issue", "file", "video"
    parameters: Dict[str, Any]  # {"issue_number": "123"}
    context: Optional[str] = None  # Additional instructions

class WorkflowCompiler:
    """Core engine for template-driven workflow generation"""

    def __init__(self, llm_client, context_builder, prompt_templates):
        self.llm = llm_client
        self.context_builder = context_builder
        self.prompts = prompt_templates
        self.pattern_library = self._load_pattern_library()

    def compile_request(self, user_input: str, registry_metadata: Dict) -> Dict[str, Any]:
        """Transform any input into executable workflow"""

        # 1. Build comprehensive context
        node_context = self.context_builder.build_context(registry_metadata)

        # 2. Generate workflow with templates
        workflow = self._generate_workflow(user_input, node_context)

        # 3. Validate and enhance
        workflow = self._enhance_with_patterns(workflow)
        self._validate_workflow(workflow)

        # 4. Optimize template resolution
        workflow["resolution_order"] = self._calculate_resolution_order(workflow)

        return workflow

    def _generate_workflow(self, user_input: str, node_context: str) -> Dict:
        """Single-shot workflow generation with templates"""

        # Build comprehensive prompt
        prompt = self._build_generation_prompt(user_input, node_context)

        # Generate with deterministic settings
        response = self.llm.call_llm(
            prompt=prompt,
            temperature=0.0,  # Deterministic
            model="claude-3-sonnet-20240229"
        )

        # Parse response (handle both JSON and wrapped JSON)
        workflow = self._parse_llm_response(response)

        # Ensure template structure exists
        if "template_inputs" not in workflow:
            workflow = self._infer_templates(workflow)

        return workflow

    def _build_generation_prompt(self, user_input: str, node_context: str) -> str:
        """Create rich prompt with examples and patterns"""

        # Detect if input looks like CLI syntax
        is_cli_like = ">>" in user_input or "--" in user_input

        prompt_parts = [
            self.prompts.WORKFLOW_GENERATION_HEADER,
            f"\nUser Input: {user_input}",
            f"\nInput Type: {'CLI-like syntax' if is_cli_like else 'Natural language'}",
            "\nAvailable Nodes:",
            node_context,
            "\nWorkflow Patterns:",
            self._format_pattern_examples(),
            "\nTemplate Variable Guidelines:",
            self._get_template_guidelines(),
            "\nGenerate a complete workflow with:",
            "1. All required nodes in correct sequence",
            "2. Template strings for dynamic inputs (use $variables)",
            "3. Variable flow mapping sources to consumers",
            "4. Natural, descriptive shared store keys",
            "\nOutput only valid JSON."
        ]

        return "\n".join(prompt_parts)

    def _infer_templates(self, workflow: Dict) -> Dict:
        """Infer template structure from workflow if not provided"""

        workflow["template_inputs"] = {}
        workflow["variable_flow"] = {}

        # Analyze nodes to infer template needs
        for i, node in enumerate(workflow["nodes"]):
            node_type = node["type"]
            node_id = node["id"]

            # Common patterns for template inference
            if node_type == "llm" and i > 0:
                # LLM usually processes previous node's output
                prev_node = workflow["nodes"][i-1]
                workflow["template_inputs"][node_id] = {
                    "prompt": f"Process this: ${prev_node['id']}_output"
                }
                workflow["variable_flow"][f"{prev_node['id']}_output"] = \
                    f"{prev_node['id']}.outputs.primary"

            elif node_type == "claude-code":
                # Claude-code typically needs complex prompts
                if any(n["type"] == "github-get-issue" for n in workflow["nodes"][:i]):
                    workflow["template_inputs"][node_id] = {
                        "prompt": "Fix this issue:\n$issue"
                    }
                    workflow["variable_flow"]["issue"] = \
                        "github-get-issue.outputs.issue_data"

        return workflow

    def _enhance_with_patterns(self, workflow: Dict) -> Dict:
        """Apply known patterns to enhance workflow"""

        # Detect workflow pattern
        node_sequence = [n["type"] for n in workflow["nodes"]]

        # Apply pattern enhancements
        if node_sequence[:2] == ["github-get-issue", "claude-code"]:
            # GitHub fix pattern - ensure proper templates
            if "template_inputs" not in workflow:
                workflow["template_inputs"] = {}

            # Enhance claude-code prompt if basic
            claude_node_id = workflow["nodes"][1]["id"]
            if claude_node_id in workflow.get("template_inputs", {}):
                current_prompt = workflow["template_inputs"][claude_node_id].get("prompt", "")
                if len(current_prompt) < 50:  # Too simple
                    workflow["template_inputs"][claude_node_id]["prompt"] = \
                        self._get_enhanced_prompt("github_fix", current_prompt)

        return workflow

    def _get_enhanced_prompt(self, pattern: str, base_prompt: str) -> str:
        """Get pattern-specific enhanced prompt"""

        ENHANCED_PROMPTS = {
            "github_fix": """<instructions>
1. Understand the issue described below
2. Search the codebase for relevant files
3. Implement necessary changes to fix the issue
4. Write tests to verify the fix
5. Ensure all existing tests still pass
6. Return a detailed report of changes made
</instructions>

$issue""",
            "code_analysis": """Analyze the following code:

$content

Provide:
1. Summary of functionality
2. Potential issues or bugs
3. Suggestions for improvement
4. Security considerations"""
        }

        return ENHANCED_PROMPTS.get(pattern, base_prompt)

    def _calculate_resolution_order(self, workflow: Dict) -> List[str]:
        """Calculate optimal order for template resolution"""

        # Extract dependencies
        dependencies = {}
        for node_id, templates in workflow.get("template_inputs", {}).items():
            deps = set()
            for template in templates.values():
                # Extract all $variables
                variables = re.findall(r'\$\{?(\w+)\}?', str(template))
                deps.update(variables)
            dependencies[node_id] = deps

        # Topological sort for resolution order
        resolved = []
        available_vars = {"stdin"} if workflow.get("expects_stdin") else set()

        # Add initial variables from workflow context
        available_vars.update(workflow.get("initial_variables", {}).keys())

        nodes_to_resolve = [n["id"] for n in workflow["nodes"]]
        max_iterations = len(nodes_to_resolve) * 2  # Prevent infinite loops

        for _ in range(max_iterations):
            if not nodes_to_resolve:
                break

            progress = False
            for node_id in nodes_to_resolve[:]:
                if dependencies.get(node_id, set()).issubset(available_vars):
                    resolved.append(node_id)
                    nodes_to_resolve.remove(node_id)

                    # Add outputs from this node
                    node_type = next(n["type"] for n in workflow["nodes"]
                                    if n["id"] == node_id)
                    # Would lookup from registry - simplified here
                    available_vars.update(self._get_node_outputs(node_type, node_id))
                    progress = True

            if not progress and nodes_to_resolve:
                raise ValueError(
                    f"Circular dependency or missing variables for nodes: {nodes_to_resolve}"
                )

        return resolved

    def _get_node_outputs(self, node_type: str, node_id: str) -> set:
        """Get output variables from a node"""
        # Simplified - would lookup from registry
        OUTPUT_PATTERNS = {
            "github-get-issue": ["issue", "issue_title", "issue_number"],
            "claude-code": ["code_report", "files_modified"],
            "llm": ["response"],
            "read-file": ["content", "file_path"],
            "write-file": ["written_file"]
        }

        base_outputs = OUTPUT_PATTERNS.get(node_type, ["output"])
        # Prefix with node_id if needed to avoid collisions
        return {f"{node_id}_{out}" if node_id != node_type else out
                for out in base_outputs}

    def _validate_workflow(self, workflow: Dict):
        """Comprehensive workflow validation"""

        # Structure validation
        required_fields = ["nodes", "edges", "start_node"]
        for field in required_fields:
            if field not in workflow:
                raise ValueError(f"Missing required field: {field}")

        # Node validation
        node_ids = {n["id"] for n in workflow["nodes"]}
        if workflow["start_node"] not in node_ids:
            raise ValueError(f"Start node '{workflow['start_node']}' not found")

        # Edge validation
        for edge in workflow["edges"]:
            if edge["from"] not in node_ids:
                raise ValueError(f"Edge source '{edge['from']}' not found")
            if edge["to"] not in node_ids:
                raise ValueError(f"Edge target '{edge['to']}' not found")

        # Template validation
        if "template_inputs" in workflow:
            self._validate_templates(workflow)

        # Natural key validation
        self._validate_natural_keys(workflow)

    def _validate_templates(self, workflow: Dict):
        """Validate all template variables have sources"""

        variable_flow = workflow.get("variable_flow", {})

        for node_id, templates in workflow["template_inputs"].items():
            for input_key, template in templates.items():
                if not isinstance(template, str):
                    continue

                # Extract variables
                variables = re.findall(r'\$\{?(\w+)\}?', template)

                for var in variables:
                    if var not in variable_flow:
                        # Try to infer source
                        inferred = self._infer_variable_source(var, workflow)
                        if inferred:
                            variable_flow[var] = inferred
                        else:
                            raise ValueError(
                                f"Template variable ${var} in {node_id} has no source"
                            )

    def _infer_variable_source(self, variable: str, workflow: Dict) -> Optional[str]:
        """Try to infer variable source from workflow structure"""

        # Common patterns
        if variable == "issue" or variable == "issue_data":
            # Look for GitHub issue node
            for node in workflow["nodes"]:
                if node["type"] == "github-get-issue":
                    return f"{node['id']}.outputs.issue_data"

        elif variable == "content":
            # Look for file reading node
            for node in workflow["nodes"]:
                if node["type"] in ["read-file", "git-show"]:
                    return f"{node['id']}.outputs.content"

        return None

    def _validate_natural_keys(self, workflow: Dict):
        """Ensure natural, non-conflicting keys"""

        # Check for generic key names that should be more specific
        generic_keys = {"data", "output", "result", "value", "input"}

        for node in workflow["nodes"]:
            node_id = node["id"]

            # Check template inputs
            if node_id in workflow.get("template_inputs", {}):
                for key in workflow["template_inputs"][node_id]:
                    if key in generic_keys:
                        raise ValueError(
                            f"Node {node_id} uses generic key '{key}'. "
                            f"Use descriptive keys like 'issue_data' or 'file_content'"
                        )

    def _parse_llm_response(self, response: str) -> Dict:
        """Parse LLM response, handling various formats"""

        # Try direct JSON parsing
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```',
                              response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object in text
        json_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
                              response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse workflow from LLM response: {response[:200]}...")

    def _format_pattern_examples(self) -> str:
        """Format workflow patterns as examples"""

        examples = []
        for pattern_name, node_sequence in self.pattern_library.items():
            examples.append(f"{pattern_name}: {' >> '.join(node_sequence)}")

        return "\n".join(examples)

    def _get_template_guidelines(self) -> str:
        """Provide template variable guidelines"""

        return """
Template Variable Rules:
1. Use $variable_name for dynamic values
2. Variables reference shared store values
3. Common variables:
   - $issue (from github-get-issue)
   - $content (from read-file)
   - $transcript (from yt-transcript)
   - $code_report (from claude-code)
4. Variables enable workflow reuse with different inputs
5. Each variable must have a source in variable_flow
"""

    def _load_pattern_library(self) -> Dict[str, List[str]]:
        """Load common workflow patterns"""

        return {
            "github_fix": [
                "github-get-issue",
                "claude-code",
                "git-commit",
                "git-push",
                "github-create-pr"
            ],
            "code_review": [
                "github-get-pr",
                "git-diff",
                "llm",
                "github-add-comment"
            ],
            "document_analysis": [
                "read-file",
                "llm",
                "write-file"
            ],
            "batch_processing": [
                "list-files",
                "llm",
                "write-file"
            ]
        }
```

## Advanced Patterns

### Pattern: Multi-Stage Template Composition
**Source**: Complex workflows from analysis
**Description**: Templates can reference multiple variables

```python
def compose_multi_stage_template(context: Dict) -> str:
    """Create complex templates with multiple variables"""

    template = """<context>
Project: $project_name
Issue: $issue_title
Previous attempts: $previous_solutions
</context>

<task>
$task_description
</task>

<constraints>
$coding_standards
</constraints>

Please provide a solution that addresses all constraints.
"""

    return template
```

### Pattern: Workflow Optimization
**Source**: Performance requirements
**Description**: Optimize generated workflows

```python
def optimize_workflow(workflow: Dict) -> Dict:
    """Optimize workflow for performance"""

    # 1. Merge consecutive LLM calls with same model
    workflow = self._merge_llm_calls(workflow)

    # 2. Identify cacheable nodes
    workflow = self._mark_cacheable_nodes(workflow)

    # 3. Optimize template resolution order
    workflow["resolution_order"] = self._optimize_resolution_order(workflow)

    return workflow
```

### Pattern: Error Recovery Planning
**Source**: Robust workflow generation
**Description**: Plan for potential failures

```python
def add_error_recovery(workflow: Dict) -> Dict:
    """Add error recovery information"""

    workflow["error_recovery"] = {
        "retry_nodes": ["github-get-issue", "claude-code"],
        "fallback_paths": {
            "claude-code": "llm"  # Fallback to simpler LLM if Claude fails
        },
        "validation_points": ["after_code_generation", "before_git_push"]
    }

    return workflow
```

## Testing Patterns

```python
def test_workflow_generation_engine():
    """Test comprehensive workflow generation"""

    # Setup
    engine = WorkflowCompiler(mock_llm, mock_context, prompts)

    # Test natural language
    workflow = engine.compile_request(
        "fix github issue 123",
        {"github-get-issue": {...}, "claude-code": {...}}
    )

    # Verify template-driven structure
    assert "template_inputs" in workflow
    assert "variable_flow" in workflow
    assert workflow["template_inputs"]["claude-code"]["prompt"] == "Fix this issue:\n$issue"

    # Test CLI-like syntax
    workflow = engine.compile_request(
        "github-get-issue --issue=123 >> claude-code",
        registry_metadata
    )

    # Should produce similar workflow
    assert len(workflow["nodes"]) >= 2
    assert workflow["nodes"][0]["type"] == "github-get-issue"

def test_template_validation():
    """Test template variable validation"""

    workflow = {
        "template_inputs": {
            "llm": {"prompt": "Analyze $content and $metadata"}
        },
        "variable_flow": {
            "content": "read-file.outputs.content"
            # Missing metadata source!
        }
    }

    with pytest.raises(ValueError, match="metadata"):
        engine._validate_templates(workflow)
```

## Implementation Checklist

- [ ] Parse both natural language and CLI-like syntax
- [ ] Generate workflows with template variables
- [ ] Validate all templates have sources
- [ ] Calculate resolution order
- [ ] Apply workflow patterns
- [ ] Ensure natural key naming
- [ ] Support workflow reuse
- [ ] Handle edge cases gracefully

## Summary

Task 17's workflow generation engine is the brain of pflow. It:

1. **Interprets any input** - Natural language or CLI syntax
2. **Generates templates** - Not just static workflows
3. **Enables reuse** - Same workflow, different parameters
4. **Validates thoroughly** - Catches errors early
5. **Optimizes execution** - Resolution order, patterns

The key insight: **Workflows are templates** that can be instantiated with different parameters, enabling "Plan Once, Run Forever".
