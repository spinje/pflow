# Task 17: Implementation Guide

This file contains concrete implementation details, code examples, and integration guidance for the Natural Language Planner.

## Flow Design Patterns (continued)

### Diamond Pattern with Convergence
Multiple paths that converge:

```python
def create_diamond_flow():
    """Multiple paths that converge."""
    flow = Flow("diamond_planner")

    # Nodes
    classifier = IntentClassifierNode()
    nl_generator = NaturalLanguageGeneratorNode()
    cli_parser = CLIParserNode()
    validator = UnifiedValidatorNode()

    # Diamond structure
    flow.add_node("classify", classifier)
    flow.add_node("nl_gen", nl_generator)
    flow.add_node("cli_parse", cli_parser)
    flow.add_node("validate", validator)

    # Edges creating diamond
    flow.add_edge("classify", "natural", "nl_gen")
    flow.add_edge("classify", "cli", "cli_parse")
    flow.add_edge("nl_gen", "done", "validate")
    flow.add_edge("cli_parse", "done", "validate")

    return flow
```

### Retry Loop with Escape Hatch
Controlled retry mechanism:

```python
def create_retry_loop_flow():
    """Retry loop with maximum attempts."""
    flow = Flow("retry_planner")

    class AttemptCounterNode(Node):
        def prep(self, shared):
            # Pass shared dict to exec for attempt counting
            return shared

        def exec(self, prep_res):
            shared = prep_res  # prep_res is the shared dict
            shared["attempts"] = shared.get("attempts", 0) + 1
            if shared["attempts"] > 3:
                return "max_attempts"
            return "continue"

    flow.add_node("counter", AttemptCounterNode())
    flow.add_node("generate", WorkflowGeneratorNode())
    flow.add_node("validate", ValidatorNode())

    # Loop with escape
    flow.add_edge("counter", "continue", "generate")
    flow.add_edge("counter", "max_attempts", "fallback")
    flow.add_edge("generate", "done", "validate")
    flow.add_edge("validate", "invalid", "counter")
    flow.add_edge("validate", "valid", "success")

    return flow
```

## Structured Generation with Smart Retry

### Core Principle: Generate Right, Retry Smart
The planner aims for **single-shot generation** success through comprehensive context, but uses **structured retry** when validation fails. This is NOT endless regeneration - it's targeted error correction through PocketFlow's routing:

```python
# The planner flow structure enables smart retry:
generator >> validator >> metadata >> param_extract
validator - "invalid_structure" >> error_feedback >> generator
validator - "invalid_paths" >> enhance_context >> generator
generator - "max_retries_exceeded" >> fallback_strategy
```

### How Structured Retry Works
1. **First Attempt**: Generate with comprehensive context
2. **Validation Failure**: Specific error identified (e.g., "template variable $issue not found in params")
3. **Targeted Retry**: Enhanced prompt with error-specific guidance
4. **Bounded Attempts**: Max retries enforced by PocketFlow node configuration

```python
class WorkflowGeneratorNode(Node):
    def __init__(self):
        super().__init__(max_retries=3)  # Bounded retries

    def prep(self, shared):
        """Prepare context for generation."""
        return {
            "base_prompt": shared.get("base_prompt", ""),
            "generation_attempts": shared.get("generation_attempts", 0),
            "validation_errors": shared.get("validation_errors", [])
        }

    def exec(self, prep_res):
        """Generate workflow with progressive enhancement."""
        # Use attempt count for progressive enhancement
        attempt = prep_res["generation_attempts"]

        if attempt > 0:
            # Add specific error feedback to prompt
            prompt = enhance_prompt_with_errors(prep_res["base_prompt"], prep_res["validation_errors"])
        else:
            prompt = prep_res["base_prompt"]

        # Generate workflow
        response = self.model.prompt(prompt, schema=WorkflowIR)

        return {
            "workflow": response.json(),
            "attempt": attempt + 1
        }

    def post(self, shared, prep_res, exec_res):
        """Store generated workflow and update attempt count."""
        shared["generated_workflow"] = exec_res["workflow"]
        shared["generation_attempts"] = exec_res["attempt"]
        return "validate"  # Always go to validation
```

### Rich Context Minimizes Retries
The key to minimizing retries is providing **comprehensive initial context**:
- All available nodes with descriptions
- Template syntax and examples
- Clear constraints and patterns
- Interface conventions
- Common error patterns to avoid

With sufficient context, most workflows succeed on first attempt. Retries handle edge cases with specific guidance.

## LLM Integration with Simon Willison's Library

### Preferred Implementation Pattern
Use Simon Willison's `llm` package for flexibility and structured outputs:

```python
import llm
from pydantic import BaseModel

class WorkflowGeneratorNode(Node):
    """Generates workflows using LLM with structured output."""

    def __init__(self):
        super().__init__(max_retries=3)  # For API failures only
        # Get model with proper configuration
        self.model = llm.get_model("claude-sonnet-4-20250514")

    def prep(self, shared):
        """Prepare context for workflow generation."""
        return {
            "user_input": shared["user_input"],
            "planning_context": shared["planning_context"]
        }

    def exec(self, prep_res):
        """Generate workflow using LLM."""
        # Build comprehensive prompt
        prompt = self._build_prompt(prep_res["user_input"], prep_res["planning_context"])

        # Generate with structured output (Pydantic schema)
        response = self.model.prompt(
            prompt,
            temperature=0,  # Deterministic
            schema=WorkflowIR,  # Pydantic model for type safety
            system="You are a workflow planner that generates complete JSON IR with template variables."
        )

        # Extract and validate
        workflow_dict = json.loads(response.text())
        validate_ir(workflow_dict)  # Existing validation

        return workflow_dict

    def post(self, shared, prep_res, exec_res):
        """Store generated workflow."""
        shared["generated_workflow"] = exec_res
        return "validate"
```

### Advantages of LLM Package
1. **Flexibility** - Easy to switch models
2. **Structured Output** - Built-in Pydantic support
3. **Consistent Interface** - Same API for different providers
4. **Better Error Handling** - Unified exception handling

## Structured Context Provision Pattern

### Building Rich Context for Planning
The context builder must provide comprehensive, well-structured information:

```python
def build_planning_context(selected_components: list[str], registry: Registry) -> str:
    """Build structured context optimized for LLM comprehension."""
    context_parts = []

    # 1. Available Components Section
    context_parts.append("## Available Components\n")
    for component_id in selected_components:
        if component_id in registry:
            metadata = registry[component_id]
            context_parts.extend([
                f"### {component_id}",
                f"**Description**: {metadata.get('description', 'No description')}",
                f"**Inputs**: {_format_interface(metadata.get('inputs', []))}",
                f"**Outputs**: {_format_interface(metadata.get('outputs', []))}",
                f"**Parameters**: {_format_params(metadata.get('params', {}))}",
                ""  # Empty line for readability
            ])

    # 2. Template Variable Guidelines
    context_parts.extend([
        "## Template Variables",
        "- Use $variable_name in params to reference dynamic values",
        "- CLI parameters: $issue_number, $date, $file_path",
        "- Shared store references: $issue_data, $content, $transcript",
        "- Runtime proxy resolves all template variables transparently",
        ""
    ])

    # 3. Workflow Examples
    context_parts.extend([
        "## Example Workflow Structure",
        "```json",
        _get_example_workflow(),
        "```",
        ""
    ])

    # 4. Interface Conventions
    context_parts.extend([
        "## Interface Conventions",
        "- GitHub nodes use 'issue_' prefixed keys",
        "- File operations use 'content' and 'file_path'",
        "- LLM nodes expect 'prompt' and output 'response'",
        "- Prefer descriptive keys over generic ones"
    ])

    return "\n".join(context_parts)
```

## Prompt Template Examples

### Workflow Generation Prompt
```python
WORKFLOW_GENERATION_PROMPT = """You are a workflow planner for pflow, a system that creates deterministic, reusable workflows.

Your task is to generate a complete JSON workflow including:
1. All required nodes in correct sequence
2. Template variables ($var) with path support ($var.field) for dynamic values
3. Natural, descriptive node IDs to avoid collisions
4. Simple, linear workflows (no branching)

{context}

User Request: {user_input}

Important Rules:
- Use $variables in params for dynamic values (e.g., "$issue_number", "$file_path")
- Template variables enable workflow reuse with different parameters
- Use simple, linear sequences (no complex branching for MVP)
- Each node should have a single, clear purpose
- Runtime will handle template substitution

Output only valid JSON matching this structure:
{{
  "ir_version": "0.1.0",
  "nodes": [
    {{"id": "n1", "type": "node-type", "params": {{"key": "$variable", "nested": "$data.field.subfield"}}}}
  ],
  "edges": [
    {{"from": "n1", "to": "n2"}}
  ],
  "start_node": "n1"  // Optional
}}
"""

ERROR_RECOVERY_PROMPT = """The previous workflow generation failed validation:
{error_message}

Original request: {user_input}

Please generate a corrected workflow that addresses the specific error.
Focus on: {error_hint}

Remember to use template variables ($var) in params for all dynamic values.

Output only valid JSON.
"""

TEMPLATE_VARIABLE_PROMPT = """Given this workflow, identify all template variables used in params:

Workflow: {workflow}

Identify:
1. CLI parameters (e.g., $issue_number, $date)
2. Shared store references (e.g., $issue_data, $content)

Output as JSON:
{{
  "cli_params": ["issue_number", "date"],
  "shared_refs": ["issue_data", "content"]
}}
"""
```

## Integration Points and Dependencies

### Critical Dependencies
1. **Context Builder** (Task 15/16) - Provides discovery and planning contexts
   - `build_discovery_context()` - For finding nodes/workflows (lightweight)
   - `build_planning_context()` - For detailed interface info (selected components only)
   - DO NOT access registry directly - always use context builder
   - **Note**: The context builder already filters out test nodes. The planner should not implement additional test node filtering.
2. **JSON IR Schema** - Defines valid workflow structure
3. **Node Registry** - Accessed ONLY through context builder, never directly
4. **LLM Library** - Simon Willison's `llm` with structured outputs
5. **General LLM Node** (Task 12) - Required in registry so planner can generate workflows with LLM nodes
   - Note: Planner doesn't USE Task 12's code, it just needs it to exist in the registry
   - Planner uses `llm` library directly for its own LLM calls inside its own nodes

### Clarification on Dependencies
- **Task 14**: Structure documentation (enables path-based mappings) ✅ Done
- **Task 15/16**: Context builder with two-phase discovery ✅ Done
- **Task 12**: General LLM node (needed in registry for workflow generation)
- **Tasks 18, 19**: These don't exist - ignore any references to them in research files

### Integration Requirements
1. **CLI Integration**: Planner receives raw input string from CLI
2. **Workflow Storage**: Saves to `~/.pflow/workflows/` with template variables
3. **Runtime Handoff**: Generates validated JSON IR for execution
4. **Error Reporting**: Clear, actionable error messages

### Context Builder Exclusive Parameter Pattern

The context builder shows only "exclusive parameters" - params that are NOT also inputs. However, due to the universal fallback pattern implemented in all pflow nodes, the planner can set ANY input as a parameter. This provides maximum flexibility when generating workflows.

For example, even though `file_path` is listed as an input (not a parameter) for read-file:
```json
{
  "type": "read-file",
  "params": {"file_path": "config.json"}  // Works! The node's fallback pattern handles this
}
```

This means the planner has complete freedom to provide values either through the shared store (dynamic) or through params (static), regardless of how they're categorized in the context builder output.

### Concrete Integration Implementation

#### CLI to Planner Integration
```python
# In src/pflow/cli/main.py
from pflow.planning import create_planner_flow

def process_natural_language(raw_input: str, stdin_data: Any = None) -> None:
    """Process natural language input through the planner."""
    # Create and run planner
    planner = create_planner_flow()
    shared = {
        "user_input": raw_input,
        "stdin_data": stdin_data,
        "current_date": datetime.now().isoformat()
    }

    # Run planner meta-workflow (returns workflow + params)
    planner.run(shared)

    # Extract results
    planner_output = shared.get("planner_output")
    if planner_output:
        handle_planner_output(planner_output)  # CLI handles execution
```

#### Planner Node Integration Examples

```python
# In src/pflow/planning/nodes.py

class DiscoveryNode(Node):
    """Uses context builder to find nodes and workflows."""
    def prep(self, shared):
        """Prepare discovery context."""
        from pflow.planning.context_builder import build_discovery_context
        return {
            "discovery_context": build_discovery_context(),
            "user_input": shared["user_input"]
        }

    def exec(self, prep_res):
        """Use LLM to find relevant components."""
        # Use LLM to find relevant components based on discovery context
        # ... LLM logic ...
        result = self._find_components(prep_res["user_input"], prep_res["discovery_context"])
        return result

    def post(self, shared, prep_res, exec_res):
        """Store discovery results."""
        shared["discovery_context"] = prep_res["discovery_context"]
        shared["discovery_result"] = exec_res
        return "found" if exec_res["found_components"] else "not_found"

class GeneratorNode(Node):
    """Generates workflow with registry validation."""
    def prep(self, shared):
        """Prepare planning context."""
        from pflow.planning.context_builder import build_planning_context

        # Get detailed planning context for selected nodes
        selected_nodes = shared.get("selected_nodes", [])
        planning_context = build_planning_context(selected_nodes, [])

        return {
            "planning_context": planning_context,
            "user_input": shared["user_input"]
        }

    def exec(self, prep_res):
        """Generate workflow using LLM."""
        # Generate workflow using LLM with planning context
        # ... LLM generation ...
        generated_ir = self._generate_workflow(prep_res["user_input"], prep_res["planning_context"])

        # Note: Node validation happens in ValidatorNode using registry metadata
        return generated_ir

    def post(self, shared, prep_res, exec_res):
        """Store generated IR."""
        shared["generated_ir"] = exec_res
        return "validate"

class ValidationNode(Node):
    """Uses existing IR validation."""
    def prep(self, shared):
        """Get IR to validate."""
        return shared.get("generated_ir", {})

    def exec(self, prep_res):
        """Validate the IR."""
        from pflow.core import validate_ir, ValidationError

        try:
            validate_ir(prep_res)
            return {"valid": True}
        except ValidationError as e:
            # e.path: "nodes[0].type"
            # e.message: "Unknown node type 'read-files'"
            # e.suggestion: "Did you mean 'read-file'?"
            return {
                "valid": False,
                "error": {
                    "path": e.path,
                    "message": e.message,
                    "suggestion": e.suggestion
                }
            }

    def post(self, shared, prep_res, exec_res):
        """Store validation result."""
        if exec_res["valid"]:
            return "valid"
        else:
            shared["validation_error"] = exec_res["error"]
            return "invalid"
```

#### Parameter Substitution by CLI (After Planner Returns)
```python
# In CLI after receiving planner output
def execute_with_parameters(workflow_ir: dict, parameter_values: dict) -> None:
    """Execute workflow with parameter substitution."""
    from pflow.runtime import compile_ir_to_flow
    from pflow.registry import Registry

    # Substitute template variables
    executable_ir = substitute_parameters(workflow_ir, parameter_values)

    # Compile and execute
    registry = Registry()
    flow = compile_ir_to_flow(executable_ir, registry)

    # Run with isolated shared store
    workflow_shared = {"stdin": stdin_data} if stdin_data else {}
    flow.run(workflow_shared)
```
## Structured Output Generation with Pydantic

### Hybrid Validation Approach
The planner uses Pydantic models for type-safe IR generation with the LLM, followed by JSONSchema validation:

```python
# src/pflow/planning/ir_models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class NodeIR(BaseModel):
    """Node representation for IR generation."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    type: str = Field(..., description="Node type from registry")
    params: Dict[str, Any] = Field(default_factory=dict)

class EdgeIR(BaseModel):
    """Edge representation for IR generation."""
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    action: str = Field(default="default")

class FlowIR(BaseModel):
    """Flow IR for planner output generation."""
    ir_version: str = Field(default="0.1.0", pattern=r'^\d+\.\d+\.\d+$')
    nodes: List[NodeIR] = Field(..., min_items=1)
    edges: List[EdgeIR] = Field(default_factory=list)
    start_node: Optional[str] = None
    # mappings field omitted in MVP - v2.0 feature

    def to_dict(self) -> dict:
        """Convert to dict for validation with existing schema."""
        return self.model_dump(by_alias=True, exclude_none=True)
```

**Important**: These models live in the planning module, separate from the core JSONSchema. They serve different purposes:
- **Pydantic models**: For type-safe generation with the LLM
- **JSONSchema**: For comprehensive validation of the final IR

### Direct LLM Usage - No Wrapper Needed

The planner uses Simon Willison's `llm` library directly without creating any wrapper abstractions. This follows the principle that thin wrappers add no value - the `llm` library already provides a clean, simple API:

```python
# Direct usage - no custom client or wrapper
model = llm.get_model("claude-sonnet-4-20250514")
response = model.prompt(prompt, schema=FlowIR)
```

This approach ensures we get all `llm` features immediately and avoid maintaining unnecessary abstraction layers.

### Integration with PocketFlow Retry Mechanism

The GeneratorNode leverages PocketFlow's built-in retry capabilities with progressive prompt enhancement:

```python
class WorkflowGeneratorNode(Node):
    """Generates workflows using LLM with structured output."""

    def __init__(self):
        super().__init__(max_retries=3, wait=1.0)
        self.model = llm.get_model("claude-sonnet-4-20250514")

    def prep(self, shared):
        """Prepare data including attempt tracking for progressive enhancement."""
        return shared  # Pass entire shared dict for comprehensive context

    def exec(self, prep_res):
        """Generate workflow with progressive enhancement."""
        shared = prep_res  # prep_res is the shared dict

        # Track attempts for progressive enhancement
        attempt = shared.get("generation_attempts", 0)
        shared["generation_attempts"] = attempt + 1

        # Build prompt with progressive enhancements
        prompt = self._build_prompt(shared, attempt)

        # Generate with structured output
        response = self.model.prompt(
            prompt,
            schema=FlowIR,
            temperature=0  # Deterministic
        )

        workflow_dict = json.loads(response.text())

        # Validate with JSONSchema
        validate_ir(workflow_dict)

        shared["generated_workflow"] = workflow_dict
        return "validate"

    def _build_prompt(self, shared, attempt):
        """Build prompt with progressive enhancements based on retry attempt."""
        base_prompt = self._create_base_prompt(shared)

        # Add error context on retries
        if attempt > 0 and "validation_errors" in shared:
            base_prompt += "\n\nPrevious attempt had these issues:\n"
            for error in shared["validation_errors"][:3]:  # Limit to avoid prompt bloat
                base_prompt += f"- {error}\n"
            base_prompt += "\nPlease address these issues in your response."

        # Progressive guidance based on attempt
        if attempt >= 2:
            base_prompt += "\n\nIMPORTANT: Use only basic, well-known nodes. Include template variables ($var) directly in node params."

        return base_prompt

    def exec_fallback(self, prep_res, exc):
        """Handle final failure after all retries."""
        shared = prep_res  # prep_res is the shared dict
        shared["generation_failed"] = True
        shared["final_error"] = str(exc)
        return "generation_failed"
```

### Prompt Design for Template Variables

The prompt must explicitly guide the LLM to use template variables:

```python
def _create_base_prompt(self, shared):
    """Create prompt that emphasizes template variables."""
    return f"""Generate a workflow for: {shared['user_input']}

Available nodes:
{shared['node_context']}

CRITICAL Requirements:
1. Use template variables ($variable) in params for ALL dynamic values
2. NEVER hardcode values like "1234" - use $issue_number instead
3. Template variables from user input start with $ (e.g., $issue_number)
4. Template variables from shared store also start with $ (e.g., $issue_data)

Example of CORRECT usage:
- User says "fix issue 1234"
- Generate: {{"params": {{"issue": "$issue_number"}}}}
- NOT: {{"params": {{"issue": "1234"}}}}

Template variables enable workflow reuse with different parameters.
The runtime will handle substitution transparently.
Generate complete JSON matching the IR schema with nodes, edges, and params."""
```

### Template Variable Resolution Order
The runtime proxy will handle template resolution transparently, but the planner should validate that all template variables can be resolved:

```python
def validate_template_variables(workflow: dict, parameter_values: dict, registry_metadata: dict) -> None:
    """Validate that all template variables in the workflow can be resolved.

    Critical: Node outputs come from registry metadata, NOT from the workflow IR.

    MVP approach:
    - Only validate base variables (ignore paths like .user.login)
    - Ignore array indices
    - Everything is treated as strings
    """
    # Extract all template variables from node params
    template_vars = set()
    for node in workflow.get("nodes", []):
        for param_value in node.get("params", {}).values():
            if isinstance(param_value, str):
                # Extract template variables including paths like $issue_data.user.login
                variables = re.findall(r'\$(\w+(?:\.[\w\[\]]+)*)', param_value)
                template_vars.update(variables)

    # Collect all available data sources
    available = set(parameter_values.keys())  # CLI parameters

    # Add outputs from all nodes (from registry, NOT from IR!)
    for node in workflow.get("nodes", []):
        node_type = node["type"]
        outputs = registry_metadata.get(node_type, {}).get("outputs", [])
        available.update(outputs)

    # Simple validation: check base variables exist
    missing = template_vars - available
    if missing:
        raise ValidationError(f"Template variables have no source: {missing}")
```

### Example: LLM-Generated Complete Workflow
When user says "fix github issue 123", the LLM generates:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "get_issue", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
    {"id": "analyze", "type": "claude-code", "params": {
      "prompt": "<instructions>Fix the issue described below</instructions>\n\nIssue #$get_issue.issue_data.number: $get_issue.issue_data.title\nReported by: $get_issue.issue_data.user.login\n\nDescription:\n$get_issue.issue_data.body"
    }},
    {"id": "commit", "type": "git-commit", "params": {"message": "Fix #$issue_number: $get_issue.issue_data.title"}},
    {"id": "push", "type": "git-push", "params": {}},
    {"id": "create_pr", "type": "github-create-pr", "params": {
      "title": "Fix: $get_issue.issue_data.title",
      "body": "Fixes #$issue_number\n\n$analyze.code_report"
    }}
  ],
  "edges": [
    {"from": "get_issue", "to": "analyze"},
    {"from": "analyze", "to": "commit"},
    {"from": "commit", "to": "push"},
    {"from": "push", "to": "create_pr"}
  ]
}
```

The planner returns this IR along with parameter values:
```json
{
  "workflow_ir": {...above...},
  "parameter_values": {
    "issue_number": "123"  // Extracted from user input
  }
}
```

Template variables in params will be resolved by runtime:
- `$issue_number` → "123" (from CLI parameters)
- `$get_issue.issue_data.title` → "Bug in login" (path traversal from shared store)
- `$analyze.code_report` → "Fixed by..." (from shared store during execution)

## Testing Workflow Generation

### Core Testing Strategy
Testing the workflow generation focuses on validating that the LLM produces complete, valid workflows with proper template variables in params.

```python
def test_workflow_generation_completeness():
    """Test that LLM generates complete workflows with template variables in params."""
    # Mock LLM to return a known good workflow
    mock_llm = MockLLM(returns={
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "get", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
            {"id": "fix", "type": "claude-code", "params": {"prompt": "Fix: $issue_data"}}
        ],
        "edges": [{"from": "get", "to": "fix"}]
    })

    planner = create_planner_flow()
    result = planner.run({"user_input": "fix github issue 123"})

    # Verify workflow structure
    assert "nodes" in result["workflow_ir"]
    assert "edges" in result["workflow_ir"]
    assert "parameter_values" in result

    # Verify extracted parameters
    assert result["parameter_values"]["issue_number"] == "123"

    # Verify template variables in params
    nodes = result["workflow_ir"]["nodes"]
    assert any("$" in str(node.get("params", {})) for node in nodes)
```

### Template Variable Validation Testing
```python
def test_template_validation_in_params():
    """Test that validation ensures template variables are properly used."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "llm", "type": "llm",
             "params": {"prompt": "Analyze $content and $metadata"}}
        ]
    }
    parameter_values = {
        "content": "file content"
        # Missing metadata parameter!
    }

    validator = validate_template_variables
    with pytest.raises(ValidationError, match="metadata"):
        validator.validate_templates(workflow)
```

### Natural Language to Workflow Testing
```python
def test_natural_language_interpretation():
    """Test various natural language inputs produce correct workflows."""
    test_cases = [
        {
            "input": "fix github issue 123",
            "expected_nodes": ["github-get-issue", "claude-code", "git-commit"],
            "expected_template_vars": ["issue_number", "issue_data", "commit_message"]
        },
        {
            "input": "analyze this youtube video",
            "expected_nodes": ["yt-transcript", "llm"],
            "expected_template_vars": ["url", "transcript"]
        }
    ]

    for case in test_cases:
        result = planner.run({"user_input": case["input"]})
        workflow = result["final_workflow"]

        # Verify expected nodes
        node_types = [n["type"] for n in workflow["nodes"]]
        for expected in case["expected_nodes"]:
            assert expected in node_types

        # Verify template variables exist in params
        all_params = []
        for node in workflow["nodes"]:
            if "params" in node:
                all_params.extend(str(v) for v in node["params"].values())

        for var in case["expected_template_vars"]:
            var_found = any(f"${var}" in param for param in all_params)
            assert var_found, f"Missing template variable ${var} in node params"
```

### Resolution Order Testing
```python
def test_resolution_order_calculation():
    """Test that resolution order correctly handles dependencies."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "n1", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
            {"id": "n2", "type": "claude-code", "params": {"prompt": "Fix issue: $issue_data"}},
            {"id": "n3", "type": "llm", "params": {"prompt": "Summarize: $code_report"}}
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"}
        ]
    }

    order = calculate_resolution_order(workflow)

    # n1 must come before n2, n2 must come before n3
    assert order.index("n1") < order.index("n2")
    assert order.index("n2") < order.index("n3")
```

## Component Browsing with Smart Context Loading

### Critical Distinction: Discovery is Browsing, Not Selecting
The discovery phase is fundamentally about **browsing** for potentially relevant components, not selecting a single match. The term "two-phase discovery" was confusing - it's really about smart context loading:

1. **Browse with lightweight context**: Cast a wide net to find potentially relevant components
2. **Load details conditionally**: Only get full interface details for selected components

**Browsing Characteristics**:
- Over-inclusive is better than missing components
- Returns MULTIPLE potentially relevant items
- Reduces cognitive load by filtering noise
- Like "show me everything related to GitHub operations"

**Why This Matters**:
1. **Workflow Reuse**: A workflow might be found among browsed components
2. **Node Composition**: Multiple nodes might be needed for new workflows
3. **Flexibility**: The planner can make final decisions with full context

### Implementation of Smart Context Loading

```python
class ComponentBrowsingNode(Node):
    """Browse available components using smart context loading."""

    def _browse_components(self, user_input: str, discovery_context: str) -> dict:
        """Browse with lightweight context."""
        prompt = f"""
        User wants to: {user_input}

        Available components:
        {discovery_context}

        Select ALL workflows and nodes that would help achieve this goal.
        Focus on: Would executing these components satisfy what the user wants?
        Be over-inclusive - it's better to include too many than miss important ones.

        Return lists of:
        - node_ids: Potentially useful nodes
        - workflow_names: Potentially useful workflows
        """

        response = self.llm.prompt(prompt, schema=ComponentSelection)
        return response.json()

    def prep(self, shared):
        """Prepare data for component browsing."""
        return {
            "user_input": shared["user_input"]
        }

    def exec(self, prep_res):
        """Execute component browsing with two-phase context loading."""
        # Step 1: Browse with lightweight context
        discovery_context = build_discovery_context()
        browsed = self._browse_components(prep_res["user_input"], discovery_context)

        # Step 2: Load details only for browsed components
        planning_context = build_planning_context(
            browsed["node_ids"],
            browsed["workflow_names"]
        )

        return {
            "planning_context": planning_context,
            "browsed_components": browsed
        }

    def post(self, shared, prep_res, exec_res):
        """Store results and proceed to generation."""
        shared["planning_context"] = exec_res["planning_context"]
        shared["browsed_components"] = exec_res["browsed_components"]
        return "generate"
```

This approach:
- **Browsing first**: Cast a wide net to find all potentially relevant components
- **Detailed loading second**: Get full interface details only for what's needed
- **No ranked lists for users**: All selection happens internally
- **Semantic understanding**: "analyze costs" finds "aws-cost-analyzer" through browsing

## Concrete Integration Examples

### Accessing the Registry
```python
from pflow.registry import Registry

# In any planner node
class WorkflowDiscoveryNode(Node):
    def prep(self, shared):
        """Prepare for workflow discovery."""
        from pflow.planning.context_builder import build_discovery_context

        # Use context builder for formatted discovery
        discovery_context = build_discovery_context()

        return {
            "discovery_context": discovery_context,
            "user_input": shared.get("user_input", "")
        }

    def exec(self, prep_res):
        """Execute workflow discovery."""
        # Use the discovery context from prep
        # Context builder provides:
        # - Formatted node descriptions
        # - Available workflows from ~/.pflow/workflows/
        # - Both as LLM-ready markdown

        # Would typically use LLM here with prep_res["discovery_context"]
        # to find matching workflows
        return {"found": False}  # Simplified example

    def post(self, shared, prep_res, exec_res):
        """Store discovery results."""
        shared["discovery_context"] = prep_res["discovery_context"]
        shared["discovery_result"] = exec_res
        return "found" if exec_res.get("found") else "not_found"
```

### Using IR Validation
```python
from pflow.core import validate_ir, ValidationError

class ValidatorNode(Node):
    def prep(self, shared):
        """Prepare data for validation."""
        from pflow.registry import Registry
        registry = Registry()

        workflow = shared.get("generated_workflow", {})
        # Get metadata only for nodes used in this workflow
        node_types = [node["type"] for node in workflow.get("nodes", [])]

        return {
            "workflow": workflow,
            "registry_metadata": registry.get_nodes_metadata(node_types),
            "parameter_values": shared.get("extracted_params", {})
        }

    def exec(self, prep_res):
        """Execute validation."""
        try:
            # First validate structure
            validate_ir(prep_res["workflow"])

            # Then validate template variables can be resolved
            validate_template_variables(
                prep_res["workflow"],
                prep_res["parameter_values"],
                prep_res["registry_metadata"]
            )

            return {"is_valid": True}
        except ValidationError as e:
            return {
                "is_valid": False,
                "error": {
                    "path": getattr(e, 'path', ''),
                    "message": str(e),
                    "suggestion": getattr(e, 'suggestion', '')
                }
            }

    def post(self, shared, prep_res, exec_res):
        """Store validation results."""
        if not exec_res["is_valid"]:
            shared["validation_error"] = exec_res["error"]
            return "invalid"
        return "valid"
```

### CLI Integration Point
```python
# The CLI will invoke the planner like this:
from pflow.planning import create_planner_flow
from pflow.registry import Registry

# In cli/main.py
registry = Registry()
planner_flow = create_planner_flow()

# Pass registry instance, not metadata
# The planner will call get_nodes_metadata() internally
result = planner_flow.run({
    "user_input": ctx.obj["raw_input"],
    "input_source": ctx.obj["input_source"],
    "stdin_data": ctx.obj.get("stdin_data"),
    "registry": registry  # Pass registry instance
})

# Result contains the planner output (workflow IR + parameter values)
```

## End-to-End Execution Example

### Complete Flow: "fix github issue 123"

```python
# Initial shared state
shared = {
    "user_input": "fix github issue 123",
    "input_source": "args"
}

# 1. Discovery Phase
# → WorkflowDiscoveryNode executes
shared["available_workflows"] = ["fix-issue", "analyze-logs", ...]
# → LLM matches "fix github issue" to "fix-issue" workflow
shared["found_workflow"] = {
    "ir_version": "0.1.0",
    "nodes": [
        {"id": "get-issue", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
        {"id": "fix", "type": "claude-code", "params": {"prompt": "Fix this issue: $issue_data"}}
    ],
    "edges": [{"from": "get-issue", "to": "fix"}]
}
# → Returns "found_existing"

# 2. Parameter Extraction (Convergence Point)
# → ParameterExtractionNode executes
# → Extract: "123" from user input
# → Verify: workflow needs issue_number, we have it ✓
shared["extracted_params"] = {"issue_number": "123"}
# → Returns "params_complete"

# 3. Parameter Preparation
# → ParameterPreparationNode executes
shared["parameter_values"] = {
    "issue_number": "123"  # Only CLI parameters, no complex mappings
}
# → Returns "prepare_result"

# 4. Result Preparation
# → ResultPreparationNode prepares output for CLI
shared["planner_output"] = {
    "workflow_ir": shared["found_workflow"],
    "workflow_metadata": {
        "suggested_name": "fix-issue",
        "description": "Fix a GitHub issue and create PR",
        "inputs": ["issue_number"],
        "outputs": ["pr_url"]
    },
    "parameter_values": {"issue_number": "123"}
}
# → Returns "complete"

# 5. CLI Takes Over
# → Planner returns shared["planner_output"] to CLI
# → CLI shows approval: "Will run 'fix-issue' with issue=123"
# → User approves
# → CLI saves workflow to ~/.pflow/workflows/fix-issue.json
# → CLI executes with parameter substitution
```

---
*See also: task-17-architecture-and-patterns.md and task-17-core-concepts.md*
