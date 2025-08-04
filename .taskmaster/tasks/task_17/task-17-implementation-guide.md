# Task 17: Implementation Guide

This file contains concrete implementation details, code examples, and integration guidance for the Natural Language Planner.

## Important: Understanding Node Parameter Patterns

All pflow nodes implement a universal fallback pattern where ANY input can also be provided as a parameter. The context builder shows only "exclusive parameters" (params that are NOT also inputs) to avoid redundancy, but the planner can set any value via params.

Example: Even though `file_path` is listed as an input (not parameter), this works:
```json
{"type": "read-file", "params": {"file_path": "config.json"}}
```

This flexibility is crucial for workflow generation and is available on ALL nodes.

## MVP Context: Natural Language Only

**Critical**: In the MVP, users NEVER provide CLI-style parameters. Everything goes through natural language:
- ✅ `pflow "generate changelog from closed issues"`
- ❌ `pflow generate-changelog --state=closed --limit=20` (this is post-MVP)

This affects how we think about "initial parameters" - they're always extracted from natural language by the planner, never provided as CLI flags by users.

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
            # Extract current attempt count
            return shared.get("attempts", 0)

        def exec(self, prep_res):
            current_attempts = prep_res
            new_attempts = current_attempts + 1
            if new_attempts > 3:
                return {"attempts": new_attempts, "action": "max_attempts"}
            return {"attempts": new_attempts, "action": "continue"}

        def post(self, shared, prep_res, exec_res):
            # Update shared with new attempt count
            shared["attempts"] = exec_res["attempts"]
            return exec_res["action"]

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
            "user_input": shared["user_input"],
            "planning_context": shared.get("planning_context", ""),
            "generation_attempts": shared.get("generation_attempts", 0),
            "validation_errors": shared.get("validation_errors", [])
        }

    def exec(self, prep_res):
        """Generate workflow with progressive enhancement."""
        # Use attempt count for progressive enhancement
        attempt = prep_res["generation_attempts"]

        # Build base prompt
        base_prompt = self._build_prompt(prep_res["user_input"], prep_res["planning_context"])

        if attempt > 0:
            # Add specific error feedback to prompt
            prompt = enhance_prompt_with_errors(base_prompt, prep_res["validation_errors"])
        else:
            prompt = base_prompt

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
        self.model = llm.get_model("gpt-4o-mini")  # Default from Task 12

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

### Actual Context Builder Output Formats

**Discovery Context** (lightweight browsing):
```markdown
## Available Nodes

### File Operations
### read-file
Read content from a file and add line numbers for display

### write-file
Write content to a file

## Available Workflows

### text-analyzer (workflow)
Analyzes text using AI and returns insights
```

**Planning Context** (detailed interfaces):
```markdown
## Selected Components

### read-file
Read content from a file and add line numbers for display

**Inputs**:
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs**:
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed

**Parameters**: none
```

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

### Design Decision: Simple Python F-Strings

**Resolution**: Use simple Python f-strings in code for prompt templates
- Define prompts as constants in prompts.py or inline
- Use f-strings for variable substitution
- Easy to implement and modify
- Sufficient for MVP prompts

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
   - Use for browsing available components (nodes + workflows)
   - Formats information for LLM consumption
   - **Note**: Task 19 simplified the context builder - it now uses pre-parsed interface data from the registry
2. **JSON IR Schema** - Defines valid workflow structure
3. **Registry** - Can be accessed directly for validation
   - Use registry instance to verify node types exist
   - Access interface metadata for template validation
   - Context builder uses registry internally for discovery
4. **LLM Library** - Simon Willison's `llm` with structured outputs
5. **General LLM Node** (Task 12) - Required in registry so planner can generate workflows with LLM nodes
   - Note: Planner doesn't USE Task 12's code, it just needs it to exist in the registry
   - Planner uses `llm` library directly for its own LLM calls inside its own nodes

### Clarification on Dependencies
- **Task 14**: Structure documentation (enables path-based mappings) ✅ Done
- **Task 15/16**: Context builder with two-phase discovery ✅ Done
- **Task 18**: Template variable system with path support ✅ Done
- **Task 12**: General LLM node (needed in registry for workflow generation)
- **Task 19**: Provides Node IR functionality that enables accurate template validation against actual node outputs

### Integration Requirements
1. **CLI Integration**: Planner receives raw input string from CLI
2. **Workflow Storage**: Saves to `~/.pflow/workflows/` with template variables
3. **Runtime Handoff**: Generates validated JSON IR for execution
4. **Error Reporting**: Clear, actionable error messages

### Integration with Existing Context Builder

**Design Decision**: Use context builder as-is
- Take markdown output directly from context builder
- Include in LLM prompts unchanged
- Simplest integration approach
- Avoid duplication of logic

The context builder (from Tasks 15/16) already provides exactly what the planner needs:
- Two-phase approach: discovery context (lightweight) and planning context (detailed)
- Unified format for both nodes and workflows
- Structure documentation showing available paths for template variables
- Filtered output excluding test nodes
- **CRITICAL**: The context builder output format must be EXACTLY preserved - the planner depends on it

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

### Registry Interaction Helpers

When implementing the planner nodes, use these helper functions to query the registry's Node IR data:

```python
def get_node_interface(node_type: str, registry_data: dict) -> dict:
    """Get the interface data for a specific node type."""
    if node_type in registry_data:
        return registry_data[node_type].get("interface", {})
    return {}

def get_node_outputs(node_type: str, registry_data: dict) -> list[dict]:
    """Get list of outputs a node writes to shared store."""
    interface = get_node_interface(node_type, registry_data)
    return interface.get("outputs", [])

def get_node_inputs(node_type: str, registry_data: dict) -> list[dict]:
    """Get list of inputs a node reads from shared store."""
    interface = get_node_interface(node_type, registry_data)
    return interface.get("inputs", [])

def can_nodes_connect(producer_type: str, consumer_type: str, registry_data: dict) -> dict:
    """Check if producer's outputs can satisfy consumer's inputs.

    Returns:
        Dict with 'compatible' bool and 'connections' list of valid mappings
    """
    producer_outputs = get_node_outputs(producer_type, registry_data)
    consumer_inputs = get_node_inputs(consumer_type, registry_data)

    connections = []

    # For each consumer input, check if producer provides it
    for input_spec in consumer_inputs:
        input_key = input_spec["key"]
        input_type = input_spec.get("type", "any")

        # Find matching output from producer
        for output_spec in producer_outputs:
            output_key = output_spec["key"]
            output_type = output_spec.get("type", "any")

            # Check if keys match (or could be mapped)
            if output_key == input_key:
                # Check type compatibility (simplified)
                if output_type == input_type or "any" in [output_type, input_type]:
                    connections.append({
                        "output": output_key,
                        "input": input_key,
                        "type": output_type
                    })
                    break

    return {
        "compatible": len(connections) > 0,
        "connections": connections,
        "missing_inputs": [inp["key"] for inp in consumer_inputs
                          if not any(c["input"] == inp["key"] for c in connections)]
    }

def get_available_paths(node_type: str, output_key: str, registry_data: dict) -> list[str]:
    """Get all valid paths for a node's output.

    Returns:
        List of valid template paths (e.g., ["$data", "$data.user", "$data.user.login"])
    """
    outputs = get_node_outputs(node_type, registry_data)
    paths = []

    for output in outputs:
        if output["key"] == output_key:
            # Add base path
            paths.append(f"${output_key}")

            # Add nested paths if structure exists
            if "structure" in output:
                def traverse_structure(structure: dict, prefix: str):
                    for field, info in structure.items():
                        field_path = f"{prefix}.{field}"
                        paths.append(field_path)

                        # Recurse if nested structure
                        if isinstance(info, dict) and "structure" in info:
                            traverse_structure(info["structure"], field_path)

                traverse_structure(output["structure"], f"${output_key}")
            break

    return paths

def validate_template_usage(template: str, available_outputs: dict, execution_params: list[str]) -> bool:
    """Check if a template will be valid at runtime.

    Args:
        template: Template string without $ prefix (e.g., "api_config.endpoint.url")
        available_outputs: Dict of {variable_name: output_spec} from previous nodes
        execution_params: List of parameter names provided to workflow

    Returns:
        True if template will validate, False otherwise
    """
    parts = template.split(".")
    base_var = parts[0]

    # Check execution params first (higher priority)
    if base_var in execution_params:
        return True  # Execution params are trusted to exist

    # Check node outputs
    if base_var not in available_outputs:
        return False

    # For simple variable reference
    if len(parts) == 1:
        return True

    # For nested path, check structure
    output_spec = available_outputs[base_var]
    current_structure = output_spec.get("structure", {})

    # If no structure info but type is dict/object, optimistically allow
    if not current_structure and output_spec.get("type") in ["dict", "object", "any"]:
        return True

    # Validate each path component exists
    for part in parts[1:]:
        if part not in current_structure:
            return False

        # Move deeper into structure
        if isinstance(current_structure[part], dict):
            current_structure = current_structure[part].get("structure", {})
        else:
            # Reached a leaf, no more traversal possible
            break

    return True
```

### Critical Interface Format Note

When working with interface data from the registry, remember that ALL fields use rich format:

```python
# interface["outputs"] is ALWAYS a list of dicts, NEVER simple strings:
outputs = interface["outputs"]
# Each output is: {"key": "content", "type": "str", "description": "File contents"}

# Same for inputs and params - always rich format with key/type/description
for input_spec in interface["inputs"]:
    key = input_spec["key"]        # Never just a string
    type_str = input_spec["type"]  # Type information available
    desc = input_spec["description"]  # Description for context

# This is guaranteed by MetadataExtractor's _normalize_to_rich_format()
# which ensures consistent structure across all interface data
```

### Registry Access Pattern

For the PocketFlow standard pattern of accessing the Registry through direct import and instantiation, see:
- **Architecture document**: Registry Access Pattern section (comprehensive example with both Registry and LLM)
- **patterns-and-conventions.md**: Complete DO/DON'T examples with rationale

Key principles: Direct imports for external services, shared store for data flow only, node autonomy.

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
        handle_planner_output(planner_output)  # CLI handles execution with execution_params
```

#### Planner Node Integration Examples

```python
# In src/pflow/planning/nodes.py

class ComponentBrowsingNode(Node):
    """Browse for building blocks when no complete workflow found."""
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

class ParameterDiscoveryNode(Node):
    """Extract named parameters from natural language early in Path B."""
    def prep(self, shared):
        return {
            "user_input": shared["user_input"],
            "selected_components": shared.get("selected_components", [])
        }

    def exec(self, prep_res):
        """Extract parameters WITH NAMES from natural language."""
        # Use LLM to intelligently extract named parameters
        prompt = f"""
        Extract parameters with appropriate names from: "{prep_res['user_input']}"

        Examples:
        - "generate changelog from last 20 closed issues" → {{"state": "closed", "limit": "20"}}
        - "analyze report.pdf from yesterday" → {{"file_path": "report.pdf", "date": "2024-01-15"}}
        - "deploy version 2.1.0 to staging" → {{"version": "2.1.0", "environment": "staging"}}

        Return a JSON object with parameter names and values.
        Consider context to choose appropriate parameter names.
        """

        response = self.llm.prompt(prompt, schema=ParameterDict)
        discovered_params = response.json()

        return discovered_params

    def post(self, shared, prep_res, exec_res):
        shared["discovered_params"] = exec_res  # Dict for generator context (NOT used by ParameterMappingNode)
        return "generate"

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
        # Registry helpers can be used to validate connections during generation
        # Example: Check if nodes can connect
        # compatibility = can_nodes_connect("github-get-issue", "llm", registry_data)
        # if compatibility["compatible"]:
        #     # Nodes can connect - github-get-issue outputs match llm inputs

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

#### Parameter Passing by CLI (After Planner Returns)
```python
# In CLI after receiving planner output
def execute_with_parameters(workflow_ir: dict, execution_params: dict) -> None:
    """Execute workflow with parameters from planner."""
    from pflow.runtime.compiler import compile_ir_to_flow
    from pflow.registry import Registry

    # Compile with initial parameters - runtime handles template resolution
    registry = Registry()
    flow = compile_ir_to_flow(
        workflow_ir,
        registry,
        initial_params=execution_params,  # Template resolution happens at runtime
        validate=True  # Validates all required params are provided
    )

    # Run with isolated shared store
    workflow_shared = {"stdin": stdin_data} if stdin_data else {}
    flow.run(workflow_shared)
```

### JSON IR to CLI Syntax Compilation

**Design Decision**: Compile JSON IR to CLI syntax
- Separate compiler step converts IR to CLI
- Single source of truth (JSON IR)
- Need to handle all IR features in CLI syntax

The planner generates JSON IR, but users need to see CLI syntax. A separate IR-to-CLI compiler maintains separation of concerns:

```python
def ir_to_cli_syntax(workflow_ir: dict, execution_params: dict) -> str:
    """Convert JSON IR to human-readable CLI syntax."""
    lines = []

    for i, node in enumerate(workflow_ir["nodes"]):
        # Build command line for node
        cmd = node["type"]

        # Add parameters
        for key, value in node.get("params", {}).items():
            if isinstance(value, str) and value.startswith("$"):
                # Show template variable
                cmd += f' --{key}="{value}"'
            else:
                # Show actual value
                cmd += f' --{key}="{value}"'

        # Add pipe operator except for last node
        if i < len(workflow_ir["nodes"]) - 1:
            cmd += " >>"

        lines.append(cmd)

    return "\n".join(lines)
```

This allows the planner to focus on generating valid IR while the CLI handles user-friendly display.

## Structured Output Generation with Pydantic

### Design Decision: Pydantic with Structured Output

**Resolution**: Use Pydantic models with LLM's structured output feature
- Type-safe construction with `model.prompt(prompt, schema=FlowIR)`
- Validate final output with existing JSONSchema
- Best of both worlds: type safety + comprehensive validation
- Leverages Simon Willison's LLM library capabilities

**Note**: While Pydantic ensures syntactically valid JSON, semantic validation (data flow and template path verification) is handled by the validation pipeline.

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
    # Note: Template variables use $var syntax, not {{var}}
    # Array indexing like $data[0] is NOT supported

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
model = llm.get_model(MODEL_NAME)  # Using configured model
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
        self.model = llm.get_model("gpt-4o-mini")  # Default from Task 12

    def prep(self, shared):
        """Prepare data including attempt tracking for progressive enhancement."""
        return {
            "user_input": shared["user_input"],
            "planning_context": shared.get("planning_context", ""),
            "generation_attempts": shared.get("generation_attempts", 0),
            "validation_errors": shared.get("validation_errors", []),
            "prompt_enhancements": shared.get("prompt_enhancements", [])
        }

    def exec(self, prep_res):
        """Generate workflow with progressive enhancement."""
        # Track attempts for progressive enhancement
        attempt = prep_res["generation_attempts"]

        # Build prompt with progressive enhancements
        prompt = self._build_prompt(prep_res, attempt)

        # Generate with structured output
        response = self.model.prompt(
            prompt,
            schema=FlowIR,
            temperature=0  # Deterministic
        )

        workflow_dict = json.loads(response.text())

        # Validate with JSONSchema
        validate_ir(workflow_dict)

        return {
            "workflow": workflow_dict,
            "attempt": attempt + 1
        }

    def _build_prompt(self, prep_res, attempt):
        """Build prompt with progressive enhancements based on retry attempt."""
        base_prompt = self._create_base_prompt(prep_res["user_input"], prep_res["planning_context"])

        # Add error context on retries
        if attempt > 0 and prep_res["validation_errors"]:
            base_prompt += "\n\nPrevious attempt had these issues:\n"
            for error in prep_res["validation_errors"][:3]:  # Limit to avoid prompt bloat
                base_prompt += f"- {error}\n"
            base_prompt += "\nPlease address these issues in your response."

        # Progressive guidance based on attempt
        if attempt >= 2:
            base_prompt += "\n\nIMPORTANT: Use only basic, well-known nodes. Include template variables ($var) directly in node params."

        return base_prompt

    def post(self, shared, prep_res, exec_res):
        """Store generated workflow and update attempt count."""
        shared["generated_workflow"] = exec_res["workflow"]
        shared["generation_attempts"] = exec_res["attempt"]
        return "validate"

    def exec_fallback(self, prep_res, exc):
        """Handle final failure after all retries."""
        # Log error with available context
        print(f"Generation failed after {prep_res['generation_attempts']} attempts")
        print(f"Error: {exc}")
        print(f"User input: {prep_res['user_input']}")
        return "generation_failed"
```

### Prompt Design for Template Variables

The prompt must explicitly guide the LLM to use template variables:

```python
def _create_base_prompt(self, user_input, planning_context):
    """Create prompt that emphasizes template variables."""
    return f"""Generate a workflow for: {user_input}

Available nodes:
{planning_context}

CRITICAL Requirements:
1. Use template variables ($variable) in params for ALL dynamic values
2. NEVER hardcode values like "1234" - use $issue_number instead
3. Template variables from user input start with $ (e.g., $issue_number)
4. Template variables from shared store also start with $ (e.g., $issue_data)
5. You can use ANY variable name that nodes write - check the registry!

Example of CORRECT usage:
- User says "generate changelog from closed issues"
- Generate: {{"params": {{"state": "$state", "limit": "$limit"}}}}
- NOT: {{"params": {{"state": "closed", "limit": "20"}}}}

Real workflow example:
- User says "summarize report.pdf and save to summary.txt"
- CORRECT: {{"params": {{"input": "$input_file", "output": "$output_file"}}}}
- WRONG: {{"params": {{"input": "report.pdf", "output": "summary.txt"}}}}

Task 19 enables meaningful variable names:
- If config-loader writes "api_config", use: {{"params": {{"config": "$api_config"}}}}
- If github-get-issue writes "issue_data", use: {{"params": {{"data": "$issue_data.title"}}}}

Template variables enable workflow reuse with different parameters.
The runtime will handle substitution transparently.
Generate complete JSON matching the IR schema with nodes, edges, and params."""
```

### Saving Generated Workflows

With WorkflowManager (Task 24), the planner can now save generated workflows:

```python
# In ResultPreparationNode or CLI after planner returns
from pflow.core.workflow_manager import WorkflowManager

workflow_manager = WorkflowManager()
saved_path = workflow_manager.save(
    name="generate-changelog",
    workflow_ir=generated_workflow,
    description="Generates changelog from closed issues"
)
```

### Template Variable Validation
The compiler handles template validation automatically when validate=True (default):

```python
# In the planner's ValidatorNode
discovered_params = {"issue_number": "1234", "repo": "pflow"}  # From ParameterDiscoveryNode

# ValidatorNode can now validate ALL templates:
# - $issue_number (from discovered_params)
# - $issue_data (from node outputs in registry)
errors = TemplateValidator.validate_workflow_templates(
    workflow,
    discovered_params,  # Named parameters discovered from NL
    self.registry      # Uses pre-parsed interface data from Task 19
)

# Note: In the planner, execution_params come from ParameterDiscoveryNode
# At runtime, they come from CLI flags (post-MVP) or saved values

# In the planner's validation node
from pflow.runtime.template_validator import TemplateValidator
from pflow.registry import Registry

def validate_templates_before_execution(workflow: dict, execution_params: dict, registry: Registry) -> None:
    """Validate that all template variables can be resolved.

    Task 19 update: Validator now requires registry to check actual node outputs.
    The planner just needs to handle validation errors gracefully.
    """
    # The validation API (updated in Task 19):
    errors = TemplateValidator.validate_workflow_templates(
        workflow,
        execution_params,
        registry  # Required to check actual node outputs
    )

    if errors:
        # Errors are human-readable strings like:
        # - "Template variable $api_config has no valid source"
        # - "Invalid template path: $data.missing.field"
        error_msg = "Template validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

# Even simpler - the compiler does this automatically:
try:
    flow = compile_ir_to_flow(
        workflow_ir,
        registry,
        initial_params=execution_params,
        validate=True  # Default - validates templates automatically
    )
except ValueError as e:
    # Handle validation errors
    print(f"Validation failed: {e}")
```

**Note**: The validator (updated in Task 19) now uses actual node outputs from the registry:
- Checks if variables are written by nodes in the workflow
- Validates complete paths like `$api_config.endpoint.url`
- No more guessing based on variable names - uses real interface metadata
- Example: Knows that `config-loader` writes `$api_config`, so it's valid
- Set `validate=False` only when some params come from runtime

### Example: LLM-Generated Complete Workflow
When user says "generate changelog from closed issues", the LLM generates:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "list", "type": "github-list-issues", "params": {"state": "$state", "limit": "$limit"}},
    {"id": "generate", "type": "llm", "params": {
      "prompt": "Generate a CHANGELOG.md entry from these issues:\n$issues\n\nGroup by type (feature/bug/enhancement) and include issue numbers."
    }},
    {"id": "write", "type": "write-file", "params": {"path": "CHANGELOG.md", "content": "$response"}},
    {"id": "commit", "type": "git-commit", "params": {"message": "Update changelog for release"}},
    {"id": "create_pr", "type": "github-create-pr", "params": {
      "title": "Update CHANGELOG.md",
      "body": "Automated changelog update from last $limit $state issues",
      "base": "main"
    }}
  ],
  "edges": [
    {"from": "list", "to": "generate"},
    {"from": "generate", "to": "write"},
    {"from": "write", "to": "commit"},
    {"from": "commit", "to": "create_pr"}
  ]
}
```

The planner returns this IR along with parameter values:
```json
{
  "workflow_ir": {...above...},
  "execution_params": {
    "issue_number": "123"  // Extracted from user input
  }
}
```

Template variables in params will be resolved by runtime:
- `$issue_number` → "123" (from CLI parameters)
- `$issue_data.title` → "Bug in login" (path traversal from shared store)
- `$code_report` → "Fixed by..." (from shared store during execution)

## Common Workflow Patterns

When generating workflows, the planner should recognize these common patterns:

### Pattern 1: Direct Variable Mapping
```python
# Node A writes "result", Node B reads "input"
# Generate: Node B with params: {"input": "$result"}
```

### Pattern 2: Nested Data Access (Enabled by Node IR)
```python
# Node writes complex structure (e.g., github-get-issue writes issue_data)
# Access specific fields: "$issue_data.author.login", "$issue_data.labels"
# The validator knows these paths exist from the registry's structure info
```

### Pattern 3: Multiple Outputs
```python
# Node writes multiple variables (all visible in registry interface)
# Can reference any: "$processed_data", "$metadata", "$error"
# Example: error handling with conditional edges based on $error presence
```

### Pattern 4: Variable Name Freedom (Task 19 Benefit)
```python
# Before: Limited to "magic" names
{"params": {"data": "$result"}}  # Had to use standard names

# After: Use meaningful names that nodes actually write
{"params": {"config": "$api_configuration"}}     # From config-loader
{"params": {"issue": "$github_issue_details"}}   # From github-get-issue
{"params": {"analysis": "$llm_analysis_result"}} # From llm node
```

### Pattern 5: Parameter vs Shared Store Choice
```python
# Due to universal fallback pattern, can provide values either way:
{"type": "processor", "params": {"input": "static-value"}}     # Static
{"type": "processor", "params": {"input": "$dynamic_value"}}   # Dynamic
```

## Testing Workflow Generation

### Template Variable Testing Priority

Test simple variables (`$issue_number`) first as they're most common. Path variables (`$data.field`) are a bonus feature but should also be tested.

### Design Decision: Hybrid Testing Approach

**Resolution**: Use hybrid approach with separate LLM test commands
- Unit tests: Mock all LLM calls for component testing
- Integration tests with mocked LLM: Run with `make test` (no cost)
- Integration tests with real LLM: Separate command (costs money)
- Balanced coverage, cost control, CI/CD friendly

**Implementation**:
- Mock LLM responses for all standard tests
- Create mocked integration test that simulates full planner flow
- Separate `make test-llm` command for real LLM integration test
- Real LLM test validates basic workflow generation only
- Always test the planner's internal LLM node (all LLM calls through pocketflow)

### Core Testing Strategy
Testing the workflow generation focuses on validating that the LLM produces complete, valid workflows with proper template variables in params.

```python
def test_workflow_generation_completeness():
    """Test that LLM generates complete workflows with template variables in params."""
    # Mock LLM to return a known good workflow with both simple and path variables
    mock_llm = MockLLM(returns={
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "get", "type": "github-get-issue",
             "params": {"issue_number": "$issue_number", "repo": "$repo_name"}},  # Simple vars
            {"id": "analyze", "type": "llm",
             "params": {"prompt": "Analyze: $issue_data"}},  # Simple var from shared
            {"id": "notify", "type": "send-message",
             "params": {"to": "$issue_data.author.login", "title": "$issue_data.title"}}  # Path vars
        ],
        "edges": [{"from": "get", "to": "analyze"}, {"from": "analyze", "to": "notify"}]
    })

    planner = create_planner_flow()
    result = planner.run({"user_input": "generate changelog from closed issues"})

    # Verify workflow structure
    assert "nodes" in result["workflow_ir"]
    assert "edges" in result["workflow_ir"]
    assert "execution_params" in result

    # Verify extracted parameters
    assert result["execution_params"]["issue_number"] == "123"

    # Verify template variables in params
    nodes = result["workflow_ir"]["nodes"]
    assert any("$" in str(node.get("params", {})) for node in nodes)
```

### Template Variable Validation Testing
```python
def test_template_validation_simple_and_path():
    """Test validation of both simple and path template variables."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "process", "type": "processor",
             "params": {
                 "file": "$input_file",  # Simple variable
                 "user": "$data.user.name",  # Path variable
                 "count": "$max_items"  # Another simple variable
             }}
        ]
    }

    # Test with missing simple variable
    params1 = {"data": {"user": {"name": "John"}}, "max_items": "10"}
    # Should fail - missing input_file

    # Test with missing path
    params2 = {"input_file": "test.txt", "max_items": "10", "data": {}}
    # Should fail - missing data.user.name

    # Test with all params
    params3 = {
        "input_file": "test.txt",
        "max_items": "10",
        "data": {"user": {"name": "John"}}
    }
    # Should pass
```

### Natural Language to Workflow Testing
```python
def test_natural_language_interpretation():
    """Test various natural language inputs produce correct workflows."""
    test_cases = [
        {
            "input": "generate changelog from closed issues",
            "expected_nodes": ["github-list-issues", "llm", "write-file", "git-commit"],
            "expected_template_vars": ["state", "limit", "issues", "response"]
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
            {"id": "n1", "type": "github-get-issue", "params": {"issue_number": "$issue_number"}},
            {"id": "n2", "type": "llm", "params": {"prompt": "Analyze issue: $issue_data"}},
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

## Workflow Storage Format

Workflows are stored with metadata that enables discovery and reuse:

```json
{
  "name": "generate-changelog",
  "description": "Generates changelog from closed issues and creates a PR",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {
      "state": {
        "description": "Issue state to filter (open/closed)",
        "required": true,
        "type": "string"
      },
      "limit": {
        "description": "Number of issues to include",
        "required": true,
        "type": "string"
      }
    },
    "outputs": {
      "pr_url": {
        "description": "URL of created pull request",
        "type": "string"
      },
      "pr_number": {
        "description": "Pull request number",
        "type": "string"
      }
    },
    "nodes": [...],
    "edges": [...]
  },
  "created_at": "2025-01-29T10:00:00Z",
  "updated_at": "2025-01-29T10:00:00Z",
  "version": "1.0.0"
}
```

**Key Fields**:
- `name`: Workflow identifier for execution (`pflow generate-changelog`)
- `description`: Natural language description for discovery matching
- `ir.inputs`: Expected parameters with schemas (Task 21 format - enables validation)
- `ir.outputs`: What the workflow produces with types (enables composition)
- `ir`: Complete JSON IR with template variables preserved

**Key Insight**: The description field is all we need for semantic matching. The LLM can understand "generate changelog from closed issues" matches a workflow described as "Generates changelog from closed issues and creates a PR".

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

### Workflow as Building Block Example

When ComponentBrowsingNode selects a workflow, it becomes a node:

```json
{
  "id": "analyze_step",
  "type": "workflow",
  "params": {
    "workflow_name": "text-analyzer",  // Saved workflow name
    "param_mapping": {
      "input_text": "$document_content"
    },
    "output_mapping": {
      "analysis": "document_analysis"
    }
  }
}
```

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

## Parameter vs Static Value Detection

The planner must decide which values in natural language should become parameters (reusable) vs static values (fixed).

### Context
- Example: "last 20 closed issues" - should "20" be parameterized as `$limit`?
- Affects reusability of saved workflows
- Critical for "Plan Once, Run Forever" philosophy

### Design Decision: LLM-based Heuristic Detection
- LLM intelligently detects what should be parameters
- Smart defaults based on context and patterns
- Numbers, IDs, URLs, dates typically become parameters
- Implementation: Prompt engineering guides LLM decisions

This leverages the LLM's intelligence to make smart parameter decisions, following the planner's philosophy as an LLM-powered system.

### Implementation Pattern
```python
def guide_parameter_detection(prompt: str) -> str:
    """Add guidance for parameter detection to prompt."""
    return prompt + """

    When generating workflows, identify dynamic values that should become template variables:
    - Numbers (e.g., "1234" → $issue_number)
    - IDs and identifiers → template variables
    - Dates (e.g., "yesterday" → $date)
    - URLs → template variables
    - File paths → template variables
    - Static text like prompts → keep as literal strings

    This enables workflow reuse with different parameters.
    """
```

## Concrete Integration Examples

### Accessing the Registry
```python
from pflow.registry import Registry

# In any planner node
class WorkflowDiscoveryNode(Node):
    def prep(self, shared):
        """Prepare for workflow discovery."""
        from pflow.planning.context_builder import build_discovery_context

        # For discovery: Use context builder (not direct registry access)
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
from pflow.registry import Registry

class ValidatorNode(Node):
    def __init__(self):
        super().__init__()
        self.registry = Registry()  # Direct instantiation following PocketFlow pattern

    def prep(self, shared):
        """Prepare data for validation."""
        workflow = shared.get("generated_workflow", {})
        discovered_params = shared.get("discovered_params", {})  # Already a dict!

        return {
            "workflow": workflow,
            "discovered_params": discovered_params
        }

    def exec(self, prep_res):
        """Execute validation."""
        from pflow.runtime.template_validator import TemplateValidator

        workflow = prep_res["workflow"]
        params = prep_res["discovered_params"]

        try:
            # 1. Validate structure first
            validate_ir(workflow)

            # 2. Validate templates using Task 19's registry-based validator
            errors = TemplateValidator.validate_workflow_templates(
                workflow, params, self.registry  # Use self.registry
            )

            if errors:
                # Task 19 provides accurate error messages based on actual node outputs
                return {
                    "is_valid": False,
                    "errors": errors,
                    "suggestion": "Ensure all template variables are either in parameters or written by nodes"
                }

            return {"is_valid": True}

        except ValidationError as e:
            # Structure validation error
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
            # Store appropriate error format
            if "errors" in exec_res:
                # Template validation errors (list of strings)
                shared["validation_errors"] = exec_res["errors"]
            else:
                # Structure validation error (dict)
                shared["validation_error"] = exec_res["error"]
            return "invalid"
        return "valid"
```

### CLI Input Routing to Planner

How the planner receives input from the CLI follows the MVP's unified approach.

**Context**:
- MVP routes all input through natural language planner (both quoted and unquoted)
- CLI collects raw string after 'pflow' command
- Planner must handle both natural language and CLI-like syntax

**Design Decision**: CLI passes raw string directly to planner
- Raw input string passed unchanged to planner
- No parsing or preprocessing in CLI
- Maximum flexibility for planner
- Aligns with MVP philosophy
- Implementation: `main.py` passes entire input string to planner

This approach keeps CLI simple and lets the planner handle all interpretation logic.

### CLI Integration Point
```python
# The CLI will invoke the planner like this:
from pflow.planning import create_planner_flow

# In cli/main.py
planner_flow = create_planner_flow()

# Nodes will import and instantiate Registry directly
# Following PocketFlow pattern - no dependency injection through shared
result = planner_flow.run({
    "user_input": ctx.obj["raw_input"],  # Raw string, no preprocessing
    "input_source": ctx.obj["input_source"],
    "stdin_data": ctx.obj.get("stdin_data"),
    "current_date": datetime.now().isoformat()
    # No registry in shared - nodes handle it internally
})

# Result contains the planner output (workflow IR + parameter values)
```

## User Approval Flow Implementation

### Design Decision: Natural CLI Syntax Display

**Resolution**: Show natural CLI syntax for approval
- Display each node with its natural parameters
- Show resolved values (not template variables) for this execution
- Simple Y/n prompt for approval
- Save on approval, execute after
- **Key benefit**: No complex notation needed for mappings or data flow
- **Clarification**: The approval prompt and workflow saving are handled by the CLI after the planner returns its results, not within the planner meta-workflow itself

### How It Works

With template paths, users see exactly what data is being accessed in a natural, readable format:

1. **Each node has its own parameter namespace** - `--prompt` on one node doesn't conflict with `--prompt` on another
2. **Natural paths everywhere** - Users see `$issue_data.author.login` directly in prompts
3. **Data flow is transparent** - Template paths show exactly where data comes from
4. **Intuitive understanding** - `$data.field` syntax is familiar to developers

### Example Display

```bash
# What user sees with template paths:
github-get-issue --issue=1234 >>
llm --prompt="Analyze issue #$issue_data.id: $issue_data.title (by $issue_data.author.login)"

# Clear data flow:
# 1. github-get-issue writes to shared["issue_data"]
# 2. llm's prompt directly references the paths it needs
# 3. No hidden mappings or transformations
```

### What Users See

```bash
$ pflow "generate changelog from closed issues"

Generated workflow:

github-list-issues --state=closed --limit=20 >>
llm --prompt="Generate changelog from: $issues" >>
write-file --path=CHANGELOG.md --content="$response" >>
git-commit --message="Update changelog"

Save as 'generate-changelog' and execute? [Y/n]: y
```

**Note**: The `$variables` shown are template placeholders that will be resolved from the workflow's data flow, not CLI parameters the user needs to provide.

## Batch Mode vs Interactive Mode

The planner needs to handle both interactive terminal sessions and automated/CI environments differently.

### Context
- Interactive mode: User at terminal, can respond to prompts
- Batch mode: Scripts, CI/CD, automated execution
- Missing parameters need different handling strategies

### The Clarification

**Interactive Mode** (default):
- TTY detection shows user at terminal
- Can prompt for missing parameters
- Shows progress indicators
- Allows Y/n approval prompts
- Example: `pflow "generate changelog"` → "From which state? (open/closed)"

**Batch Mode** (--batch flag or no TTY):
- No user interaction possible
- Missing parameters cause immediate failure
- No progress indicators (clean output)
- Auto-approve with --yes flag or fail
- Example: `pflow --batch "generate changelog"` → ERROR: Missing state parameter

### Implementation
```python
# Detect mode
interactive = sys.stdin.isatty() and not args.batch

# Handle missing parameters
if param_missing:
    if interactive:
        param = prompt_user(f"Enter {param_name}: ")
    else:
        raise MissingParameterError(f"Batch mode: {param_name} required")
```

**MVP Scope**: Basic batch mode support with --batch flag and TTY detection. Full CI/CD optimizations deferred to v2.0.

**Implications for task 17**: No modifications to the CLI should be made, the task 17 implementation will ONLY provide the interfaces the CLI-layer needs to interact with the planner. Keep it simple.

## Context Gathering Update (2025-07-19)

After thorough investigation of the codebase and documentation, I've discovered the following:

### 1. Context Builder Implementation (Task 15/16)
- Task 16 created the initial context builder
- Task 15 enhanced it with two-phase discovery support
- **build_discovery_context()**: Lightweight browsing with names/descriptions only
- **build_planning_context()**: Detailed interface info for selected components
- Workflow loading from `~/.pflow/workflows/` is already implemented
- Structure documentation (JSON + paths) shows available paths for template variables

### 2. Template Variable Resolution Implemented
Task 18 has fully implemented the template variable system. Templates are preserved in JSON IR and resolved at runtime through the `TemplateAwareNodeWrapper`. This enables the "Plan Once, Run Forever" philosophy where workflows can be reused with different parameters.

### 3. CLI Integration Status
- CLI accepts natural language (quoted) and CLI syntax (unquoted)
- Both currently echo back the input (planner not integrated yet)
- JSON workflows can be executed if valid IR provided
- Stdin data handling is implemented

### 4. Runtime Integration
- Compiler takes JSON IR and creates pocketflow Flow objects
- Supports node instantiation, parameter setting, and edge wiring
- Ready to execute flows generated by the planner

### 5. Key Architectural Clarifications
From planner.md:
- Planner is implemented as a pocketflow flow (not regular Python)
- MVP routes BOTH natural language and CLI syntax through LLM planner
- Template string composition is a core planner responsibility
- Workflows can use other workflows as building blocks

### 6. Implementation Architecture Confirmed
The planner will be implemented as Python pocketflow code:
```
src/pflow/planning/
├── nodes.py          # Planner nodes (discovery, generation, validation)
├── flow.py           # create_planner_flow()
├── ir_models.py      # Pydantic models for IR generation
├── utils/
└── prompts/
    └── templates.py  # Prompt templates
```

### 7. Testing Strategy
- Unit tests: Mock LLM calls for component testing
- Integration tests: Real LLM for critical paths
- MVP validation suite: 10-20 common patterns
- Test planners internal LLM node (all LLM calls through pocketflow)

### Summary
The investigation confirms the architectural decisions in this document are correct. Template variables will be preserved in JSON IR for runtime resolution, enabling workflow reusability. The two-phase context builder is ready, and the planner should be implemented as a pocketflow flow using the pattern established in Option B (Section 14).

## End-to-End Execution Example

### Complete Flow: "generate changelog from closed issues"

```python
# Initial shared state
shared = {
    "user_input": "generate changelog from closed issues",
    "input_source": "args"
}

# Path A: Existing Workflow Found
# 1. Discovery Phase
# → WorkflowDiscoveryNode executes
shared["available_workflows"] = ["generate-changelog", "analyze-logs", ...]
# → LLM matches "generate changelog" to "generate-changelog" workflow
shared["found_workflow"] = {
    "ir_version": "0.1.0",
    "nodes": [
        {"id": "list", "type": "github-list-issues", "params": {"state": "$state", "limit": "$limit"}},
        {"id": "generate", "type": "llm", "params": {"prompt": "Generate changelog: $issues"}}
    ],
    "edges": [{"from": "list", "to": "generate"}]
}
# → Returns "found_existing"

# 2. Parameter Mapping (Convergence Point)
# → ParameterMappingNode executes
# → Extract: "closed" and "20" from user input
# → Verify: workflow needs state and limit, we have them ✓
shared["extracted_params"] = {"state": "closed", "limit": "20"}  # Raw extraction from NL
# → Returns "params_complete"

# Path B: Generate New Workflow (if no match found)
# 1. Component Browsing
# → ComponentBrowsingNode finds relevant nodes/workflows

# 2. Parameter Discovery Phase (NEW - Path B only)
# → ParameterDiscoveryNode executes
# → Extracts: {"state": "closed", "limit": "20"} with names!
shared["discovered_params"] = {
    "state": "closed",
    "limit": "20"
}
# → Returns "generate"

# 3. Generation Phase
# → GeneratorNode executes with knowledge of discovered params
# → Can intelligently design workflow using $issue_number

# 4. Validation Phase
# → ValidatorNode can now validate ALL templates:
# → - $issue_number (from discovered_params)
# → - $issue_data (from node outputs in registry)

# 5. Metadata Generation
# → MetadataGenerationNode extracts workflow metadata

# 6. Parameter Mapping (Convergence Point - same as Path A)
# → ParameterMappingNode verifies all params available

# Both Paths Continue:
# 3. Parameter Preparation
# → ParameterPreparationNode executes
shared["execution_params"] = {
    "issue_number": "123"  # Formatted for execution
}
# → Returns "prepare_result"

# 4. Result Preparation
# → ResultPreparationNode prepares output for CLI
shared["planner_output"] = {
    "workflow_ir": shared["found_workflow"] or shared["generated_workflow"],
    "workflow_metadata": {
        "suggested_name": "generate-changelog",
        "description": "Generate changelog from closed issues",
        "inputs": ["state", "limit"],
        "outputs": ["changelog"]
    },
    "execution_params": {"state": "closed", "limit": "20"}
}
# → Returns "complete"

# 5. CLI Takes Over
# → Planner returns shared["planner_output"] to CLI
# → CLI shows approval: "Will run 'generate-changelog' with state=closed, limit=20"
# → User approves
# → CLI saves workflow to ~/.pflow/workflows/generate-changelog.json
# → CLI executes with parameter substitution
```

### ParameterMappingNode's Simplified Role

With ParameterDiscoveryNode extracting named parameters, ParameterMappingNode's job becomes:
1. Verify all required workflow parameters have values in discovered_params (or extracted values for Path A)
2. Handle any additional runtime parameters (e.g., environment variables)
3. Route to "params_incomplete" if any required params are missing

No complex mapping logic needed - the names are already aligned!

---
*See also: task-17-architecture-and-patterns.md and task-17-core-concepts.md*
