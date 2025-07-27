# Task 17: Architecture and Design Patterns

This file contains the core architectural decisions, design patterns, and anti-patterns for the Natural Language Planner implementation.

## Critical Insight: The Meta-Workflow Architecture

### The Planner IS a Meta-Workflow with Two Paths That Converge

The Natural Language Planner is fundamentally a **meta-workflow** - a PocketFlow workflow that orchestrates the entire lifecycle of finding or creating workflows based on user intent. It implements two distinct paths that converge at a critical parameter extraction and verification point.

```mermaid
graph TD
    START[User: "fix github issue 1234"] --> WD[WorkflowDiscoveryNode]

    WD --> CHECK{Complete workflow exists?}

    CHECK -->|YES: Found 'fix-issue'| FOUND_PATH[Path A: Reuse Existing]
    CHECK -->|NO: Must create| CREATE_PATH[Path B: Generate New]

    %% Path A: Direct reuse
    FOUND_PATH --> PE[ParameterExtractionNode<br/>Extract: "1234" → issue_number<br/>Verify: All params available?]

    %% Path B: Generation
    CREATE_PATH --> CB[ComponentBrowsingNode<br/>Find building blocks:<br/>nodes + sub-workflows]
    CB --> GEN[GeneratorNode<br/>LLM creates workflow<br/>Designs params: $issue_number]
    GEN --> VAL[ValidatorNode<br/>Validate IR structure]
    VAL -->|invalid| GEN
    VAL -->|valid| META[MetadataGenerationNode<br/>Extract name, description,<br/>inputs, outputs]
    META --> PE

    %% Convergence point
    PE --> VERIFY{Can map user input<br/>to workflow params?}
    VERIFY -->|YES| PP[ParameterPreparationNode<br/>Format for execution]
    VERIFY -->|NO| ERROR[Cannot Execute:<br/>Missing required params]

    PP --> RES[ResultPreparationNode<br/>Package for CLI]
    RES --> END[Return to CLI]

    style PE fill:#9ff,stroke:#333,stroke-width:4px
    style VERIFY fill:#ff9,stroke:#333,stroke-width:3px
    style WD fill:#f9f,stroke:#333,stroke-width:4px
```

### Key Architectural Implications

1. **Two distinct paths**: Path A (reuse) and Path B (generate) handle different scenarios
2. **Separate discovery nodes**: WorkflowDiscoveryNode finds complete solutions, ComponentBrowsingNode finds building blocks
3. **Parameter extraction as convergence**: Both paths meet at ParameterExtractionNode
4. **Verification gate**: Parameter extraction verifies the workflow can actually execute
5. **Clean separation**: Planner plans, runtime resolves templates
6. **Every MVP execution is meta**: Even reusing existing workflows goes through the full planner
7. **Clear separation** - Planner prepares, CLI executes

### MVP vs Future Architecture

**MVP (All planning through planner, execution in CLI):**
```
User Input: "fix github issue 1234"
    ↓
[Planner Meta-Workflow]
    ├─> Discovery: Does "fix-issue" workflow exist?
    ├─> Parameter Extraction: {"issue_number": "1234"}
    ├─> Verification: Can workflow execute with these params?
    ├─> Workflow contains: {"params": {"issue": "$issue_number"}}
    └─> Returns to CLI: (workflow_ir, metadata, parameter_values)
    ↓
[CLI Takes Over - Separate from Planner]
    ├─> Shows approval: "Will run fix-issue with issue=1234"
    ├─> Saves workflow: ~/.pflow/workflows/fix-issue.json
    └─> Executes: Runs workflow with parameter substitution
```

**v2.0+ (Direct execution for known workflows):**
```
pflow fix-issue --issue=1234  # Bypasses planner entirely
```

### CRITICAL CLARIFICATION: What the Planner Includes

**The planner is a meta-workflow that creates workflows and prepares them for execution by the CLI.** This division of responsibilities is fundamental:

**The Planner Workflow Includes**:
- Discovery: Find existing workflow or determine need to create
- Generation: Create new workflow if needed (with template variables)
- Parameter Extraction: Extract "1234" from "fix github issue 1234"
- Parameter Mapping: Prepare extracted values for template variable substitution
- Result Preparation: Package workflow IR + parameter values for CLI

**The CLI then handles**:
- Confirmation: Show user what will execute
- Execution: Actually run the workflow with parameter substitution

This means the planner doesn't just generate and hand off - it orchestrates discovery, generation, and parameter mapping, then returns structured results to the CLI for execution.

**MVP Architecture**: Every natural language request goes through the planner
```
"fix github issue 1234" → Planner finds/creates → Extracts params → Returns to CLI → CLI executes
```

**Future v2.0+**: Known workflows can be executed directly

### Prerequisites Completed

All task dependencies have been successfully implemented, enabling the planner to leverage their functionality.

## Node IR Integration (Task 19)

The planner leverages the Node IR (Node Intermediate Representation) implemented in Task 19, which fundamentally improves how the planner can generate and validate workflows.

### What Node IR Provides

1. **Pre-parsed Interface Metadata**: All node capabilities are parsed at scan-time and stored in the registry
   ```json
   {
     "github-get-issue": {
       "interface": {
         "inputs": [{"key": "repo", "type": "str", "description": "Repository"}],
         "outputs": [{"key": "issue_data", "type": "dict", "structure": {...}}],
         "params": ["token"],
         "actions": ["default", "error"]
       }
     }
   }
   ```

2. **Accurate Validation**: Template variables are validated against actual node outputs, not heuristics
   - Before: Only "magic" names like `$result`, `$content` would validate
   - After: ANY variable name that a node writes will validate correctly

3. **Variable Name Freedom**: The planner can generate meaningful variable names
   ```python
   # Before Task 19: Had to use magic names
   {"params": {"data": "$result"}}  # Limited to predefined names

   # After Task 19: Use meaningful names
   {"params": {"config": "$api_configuration"}}  # Any name nodes write works
   {"params": {"issue": "$github_issue_data"}}   # Descriptive and valid
   ```

### How the Planner Uses Node IR

1. **ComponentBrowsingNode**: Accesses pre-parsed interface data through context builder
2. **GeneratorNode**: Can generate workflows using any variable names that nodes actually write
3. **ValidatorNode**: Uses registry with interface data to validate template variables accurately
4. **ParameterExtractionNode**: Knows exactly what variables are available from node outputs

### Critical Benefits for Workflow Generation

1. **Path Validation**: Can verify complex paths like `$issue_data.user.login` exist
2. **Type Information**: Knows that `issue_data` is a dict with specific structure
3. **No False Positives**: Workflows that should work will validate correctly
4. **Better Error Messages**: "Template variable $api_config has no valid source" instead of guessing

This eliminates the previous limitation where the validator would reject valid workflows simply because they used non-standard variable names.

### Node IR Design Principles

1. **No Fallbacks**: If interface data is missing in the registry, operations fail immediately with clear errors. There are no fallbacks to parsing or guessing - this ensures consistency and reliability.
2. **Single Source of Truth**: Registry is the authoritative source for node capabilities - all consumers use the same pre-parsed data.
3. **Parse Once**: All interface parsing happens at scan-time, not runtime, improving performance and consistency.


## Architectural Decision: PocketFlow for Planner Orchestration

### Core Decision
The Natural Language Planner is the **ONLY** component in the entire pflow system that uses PocketFlow for internal orchestration. This decision is based on the planner's unique complexity requirements.

### The Meta-Layer Concept: Using PocketFlow to Create PocketFlow Workflows

The planner embodies a powerful **meta architecture** - it is a PocketFlow workflow that creates other PocketFlow workflows for CLI execution. This creates an elegant philosophical alignment:

1. **The Tool and The Product**: The planner uses PocketFlow internally to help users create their own PocketFlow workflows
2. **Dogfooding at Its Best**: By using PocketFlow for the planner, we validate the framework's capabilities for complex orchestration
3. **Shared Benefits**: The planner gets the same reliability benefits (retry logic, error handling) that it provides to users

**Critical Boundary**: This meta approach applies ONLY to the planner. All other pflow components (CLI, registry, compiler, runtime) use traditional Python code. The planner is special because it needs:
- Complex branching (found vs create paths)
- Sophisticated retry strategies (LLM generation)
- State accumulation across attempts
- Multi-path execution flows

This intentional boundary ensures we use PocketFlow where it adds genuine value, not everywhere.

### Complex Control Flow Visualization
```
User Input
    ├─> Natural Language ─> Generate Context ─> LLM Planning ─┐
    │                                                          │
    ├─> CLI Syntax ─────> Parse CLI ─────────────────────────┤
    │                                                          │
    └─> Ambiguous ──────> Classify ─> (Branch to above) ─────┘
                                                               │
                                                               v
                                                        Validate Output
                                                               │
                                ┌──────────────────────────────┤
                                │                              │
                                v                              v
                           Valid Output                   Invalid Output
                                │                              │
                                v                              v
                        Check Templates                  Retry with Feedback
                                │                              │
                                v                              └──> Back to LLM
                         Resolve Templates
                                │
                                v
                            Final Output
```

### Justification for PocketFlow Usage
The planner genuinely benefits from PocketFlow's orchestration capabilities due to:
- **Multiple Entry Points**: Natural language, CLI syntax, and ambiguous input requiring classification
- **Complex retry strategies** with multiple approaches
- **Self-correcting loops** for LLM validation and error recovery
- **Branching logic** based on LLM responses and validation outcomes
- **Progressive enhancement** of generated workflows
- **Multiple fallback paths** for different error types
- **State accumulation** across retry attempts

### Why Traditional Code Fails Here
Traditional nested if/else approach quickly becomes unmaintainable:
```python
# Traditional approach becomes a nightmare
def generate_workflow(user_input, llm_client, validator):
    # Classify input
    if ">>" in user_input:
        input_type = "cli"
    elif user_input.startswith('"'):
        input_type = "natural"
    else:
        # Now we need another classification step...

    # Generate with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if input_type == "natural":
                # Build context
                context = build_context()

                # Call LLM
                for llm_attempt in range(3):
                    try:
                        response = llm_client.generate(...)
                        break
                    except:
                        if llm_attempt == 2:
                            # Now what?

                # Parse response
                try:
                    workflow = json.loads(extract_json(response))
                except:
                    # Need to retry with structure...
                    # Getting deeply nested already!

                # Validate
                if not validator.validate(workflow):
                    # Need to retry with errors...
                    # Even more nesting!
```

The traditional approach quickly becomes:
- Deeply nested
- Hard to test
- Difficult to modify
- Impossible to visualize

### Implementation Pattern - The Complete Meta-Workflow
```python
# The planner meta-workflow that handles EVERYTHING

class WorkflowDiscoveryNode(Node):
    """Find complete workflows that match user INTENT, regardless of parameters."""
    def prep(self, shared):
        # Extract user input for discovery
        return shared["user_input"]

    def exec(self, user_input):
        # Load workflows during execution
        saved_workflows = self._load_saved_workflows()  # From ~/.pflow/workflows/

        # Match based on intent, not parameter presence
        prompt = f"""
        User wants to: {user_input}

        Available workflows:
        {self._format_workflows(saved_workflows)}

        Which workflow would satisfy the user's INTENT?
        Ignore whether specific parameters (like issue numbers) are provided.
        Match based on what the user wants to accomplish.

        Return the workflow name or 'none' if no intent match.
        """

        match = self.llm.complete(prompt)
        return {
            "match": match,
            "saved_workflows": saved_workflows
        }

    def post(self, shared, prep_res, exec_res):
        """Store results and determine next action."""
        if exec_res["match"] != 'none':
            shared["found_workflow"] = exec_res["saved_workflows"][exec_res["match"]]
            return "found_existing"
        else:
            return "not_found"

class ComponentBrowsingNode(Node):
    """Browse for components to build NEW workflows (only if no complete workflow found)"""
    def prep(self, shared):
        # Extract user input for browsing
        return shared["user_input"]

    def exec(self, user_input):
        from pflow.planning.context_builder import build_discovery_context, build_planning_context

        # Step 1: Lightweight browse
        discovery_context = build_discovery_context()

        components = self._browse_for_building_blocks(
            user_input,
            discovery_context
        )

        # Step 2: Get details for selected components only
        # Note: Task 19 made this ~75 lines simpler and faster - uses pre-parsed interface data
        planning_context = build_planning_context(
            components["node_ids"],
            components["workflow_names"]  # Sub-workflows as building blocks!
        )

        return {
            "planning_context": planning_context,
            "selected_components": components
        }

    def post(self, shared, prep_res, exec_res):
        """Store results and proceed to generation."""
        shared["planning_context"] = exec_res["planning_context"]
        shared["selected_components"] = exec_res["selected_components"]
        return "generate"

class ParameterExtractionNode(Node):
    """Extracts parameters AND verifies workflow executability (convergence point)

    This node works IDENTICALLY for both paths:
    - Takes user input + workflow (which already has template variables defined)
    - Extracts concrete values from natural language
    - Maps them to the workflow's template variables
    - Verifies all required parameters are available
    """
    def prep(self, shared):
        # Extract specific data needed for parameter extraction
        user_input = shared["user_input"]
        workflow = shared.get("found_workflow") or shared.get("generated_workflow")
        current_date = shared.get("current_date", datetime.now().isoformat()[:10])
        return user_input, workflow, current_date

    def exec(self, prep_res):
        # Unpack the tuple from prep
        user_input, workflow, current_date = prep_res

        # Extract concrete values
        extracted = self._extract_from_natural_language(user_input, workflow, current_date)
        # Example: {"issue_number": "1234"} from "fix github issue 1234"

        # CRITICAL: Verify all required params are available
        required = self._get_required_params(workflow)
        missing = required - set(extracted.keys())

        return {
            "extracted": extracted,
            "missing": missing
        }

    def post(self, shared, prep_res, exec_res):
        """Store results and determine if execution can proceed."""
        if exec_res["missing"]:
            shared["missing_params"] = exec_res["missing"]
            shared["extraction_error"] = f"Workflow cannot be executed: missing {exec_res['missing']}"
            return "params_incomplete"

        shared["extracted_params"] = exec_res["extracted"]
        return "params_complete"

    def _extract_from_natural_language(self, user_input: str, workflow: dict, current_date: str) -> dict:
        """Extract parameters with intelligent interpretation of temporal and contextual references."""

        # Use LLM to extract and interpret
        prompt = f"""
        Extract parameters from user input: "{user_input}"
        Current date: {current_date}

        Expected parameters for workflow: {workflow.get('inputs', [])}

        Interpret temporal references:
        - "last month" → specific month (e.g., "2024-11")
        - "since January" → "2024-01-01"
        - "yesterday" → specific date
        - "Q1" → "2024-01-01 to 2024-03-31"

        Return extracted parameters as JSON with interpreted values.
        """

        response = self.llm.prompt(prompt, schema=ParameterDict)
        return response.json()

class ParameterPreparationNode(Node):
    """Prepares parameters for runtime substitution"""
    def prep(self, shared):
        """Get extracted parameters."""
        return shared.get("extracted_params", {})

    def exec(self, prep_res):
        """Pass through parameters unchanged."""
        # Simply pass through the extracted parameters
        # Runtime proxy will handle template substitution transparently
        return prep_res

    def post(self, shared, prep_res, exec_res):
        """Store parameter values for CLI."""
        shared["parameter_values"] = exec_res
        return "prepare_result"

class GeneratorNode(Node):
    """Generates new workflow if none found"""
    def prep(self, shared):
        # Extract specific data for generation
        return shared["user_input"], shared["planning_context"]

    def exec(self, prep_res):
        # Unpack the tuple
        user_input, planning_context = prep_res

        # Generate complete workflow with template variables
        # CRITICAL: The LLM must handle ALL workflow generation in one call:
        # 1. Design the workflow structure (node selection and sequencing)
        # 2. Identify dynamic values (like "1234" in "fix issue 1234")
        # 3. Create template variables (like $issue_number) instead of hardcoding
        # 4. Use template paths for data access ($data.field.subfield)
        # 5. Avoid collisions through descriptive node IDs
        # 6. Produce complete JSON IR with all required fields:
        #    - ir_version, nodes (with params), edges
        # 7. Ensure data flow integrity (outputs properly connect to inputs)
        workflow = self._generate_workflow(
            user_input,
            planning_context
        )
        return workflow

    def post(self, shared, prep_res, exec_res):
        """Store generated workflow and proceed to validation."""
        shared["generated_workflow"] = exec_res
        return "validate"

class ValidatorNode(Node):
    """Validates generated workflow structure"""
    def prep(self, shared):
        """Get workflow to validate."""
        return shared.get("generated_workflow", {})

    def exec(self, prep_res):
        """Validate workflow structure."""
        validation_result = self._validate_workflow(prep_res)
        return validation_result

    def post(self, shared, prep_res, exec_res):
        """Determine next action based on validation result."""
        if exec_res["is_valid"]:
            return "valid"
        else:
            shared["validation_errors"] = exec_res["errors"]
            return "invalid"

class MetadataGenerationNode(Node):
    """Extract metadata from validated workflow

    Only runs after successful validation. Extracts suggested_name,
    description, inputs, and outputs from the workflow structure.
    """
    def prep(self, shared):
        """Get validated workflow."""
        return shared.get("generated_workflow", {})

    def exec(self, prep_res):
        """Extract metadata from workflow."""
        workflow = prep_res
        return {
            "name": self._extract_name(workflow),
            "description": self._extract_description(workflow),
            "inputs": self._extract_inputs(workflow),
            "outputs": self._extract_outputs(workflow)
        }

    def post(self, shared, prep_res, exec_res):
        """Store metadata and continue to parameter extraction."""
        shared["workflow_name"] = exec_res["name"]
        shared["workflow_description"] = exec_res["description"]
        shared["workflow_inputs"] = exec_res["inputs"]
        shared["workflow_outputs"] = exec_res["outputs"]
        return "param_extract"

class ResultPreparationNode(Node):
    """Prepares the final results to return to the CLI"""
    def prep(self, shared):
        """Gather all results for CLI."""
        return {
            "workflow_ir": shared.get("found_workflow") or shared.get("generated_workflow"),
            "workflow_name": shared.get("workflow_name", "custom-workflow"),
            "workflow_description": shared.get("workflow_description", "Generated workflow"),
            "workflow_inputs": shared.get("workflow_inputs", []),
            "workflow_outputs": shared.get("workflow_outputs", []),
            "parameter_values": shared.get("parameter_values", {})
        }

    def exec(self, prep_res):
        """Package results for CLI."""
        return {
            "workflow_ir": prep_res["workflow_ir"],
            "workflow_metadata": {
                "suggested_name": prep_res["workflow_name"],
                "description": prep_res["workflow_description"],
                "inputs": prep_res["workflow_inputs"],
                "outputs": prep_res["workflow_outputs"]
            },
            "parameter_values": prep_res["parameter_values"]
        }

    def post(self, shared, prep_res, exec_res):
        """Store final output and complete."""
        shared["planner_output"] = exec_res
        return "complete"

# The complete planner meta-workflow (returns results to CLI)
def create_planner_flow():
    flow = Flow("planner_meta_workflow")

    # All nodes
    discovery = WorkflowDiscoveryNode()
    browsing = ComponentBrowsingNode()
    param_extract = ParameterExtractionNode()
    param_prep = ParameterPreparationNode()
    generator = GeneratorNode()
    validator = ValidatorNode()
    metadata = MetadataGenerationNode()
    result_prep = ResultPreparationNode()

    # Main flow with two paths
    # Path A: Found existing workflow
    flow.add_edge(discovery, "found_existing", param_extract)

    # Path B: Generate new workflow
    flow.add_edge(discovery, "not_found", browsing)
    flow.add_edge(browsing, "generate", generator)
    flow.add_edge(generator, "validate", validator)
    flow.add_edge(validator, "valid", metadata)
    flow.add_edge(validator, "invalid", generator)  # Retry
    flow.add_edge(metadata, "param_extract", param_extract)

    # Both paths converge at parameter extraction
    flow.add_edge(param_extract, "params_complete", param_prep)
    flow.add_edge(param_extract, "params_incomplete", result_prep)  # Missing params
    flow.add_edge(param_prep, "prepare_result", result_prep)

    return flow
```

### Concrete Shared State Example
The planner's shared state accumulates throughout execution:
```python
shared = {
    # Initial input
    "user_input": "fix github issue 123",
    "input_type": "natural_language",

    # Discovery phase
    "llm_context": "Available nodes: github-get-issue, llm, ...",
    "available_workflows": ["analyze-logs", "fix-issue", ...],

    # Generation attempts
    "attempt_count": 2,
    "previous_errors": ["Missing repo parameter", "Invalid JSON"],
    "learned_constraints": {"Don't use 'analyze-code' - it doesn't exist"},

    # Current state
    "llm_response": "{'nodes': [...], 'edges': [...]}",
    "generated_workflow": {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "get", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
            {"id": "fix", "type": "llm", "params": {"prompt": "Fix issue: $issue_data"}}
        ],
        "edges": [{"from": "get", "to": "fix"}]
    },

    # Validation results
    "validation_result": "missing_params",
    "validation_errors": ["Node 'llm' requires 'prompt' parameter"],

    # Final output prepared for CLI
    "planner_output": {
        "workflow_ir": {...},  # Contains nodes with $variables in params
        "workflow_metadata": {
            "suggested_name": "fix-issue",
            "description": "Fix a GitHub issue",
            "inputs": ["issue_number"],
            "outputs": ["pr_url"]
        },
        "parameter_values": {
            "issue_number": "123"  # Extracted from natural language
        }
    }
}
```

### What This Means for Implementation
1. **All other components use traditional Python** - No PocketFlow elsewhere
2. **Planner gets retry/fallback benefits** - Built-in fault tolerance
3. **Clear architectural boundary** - Only planner uses flow patterns internally
4. **Performance is not a concern** - Nodes are just method calls; LLM dominates execution time

## Planner Implementation Architecture Decision

### The Two Layers of pflow

This decision goes to the heart of pflow's architectural philosophy:

1. **User Layer**: Natural language → JSON IR → Saved workflows ("Plan Once, Run Forever")
2. **System Layer**: Infrastructure that enables the user layer

The planner sits firmly in the system layer. It's not a workflow that users discover with "find me a workflow that generates workflows" - it's the infrastructure that makes workflow generation possible.

**Why This Matters:**
- JSON IR is for **what users want to do** (their workflows)
- Python code is for **how the system works** (our infrastructure)
- The planner is "how", not "what"

### Pocketflow's Design Philosophy

According to pocketflow's "Agentic Coding" guide:
- Pocketflow is specifically designed to be **easy for AI agents to understand and modify**
- The framework provides clear patterns for system implementation
- Infrastructure components should follow the nodes.py + flow.py pattern

### The Decision: Python PocketFlow Code

**Resolution**: The planner is infrastructure and belongs in the system layer as Python pocketflow code. This follows the framework's design philosophy perfectly and maintains proper architectural boundaries.

**Benefits**:
- Direct debugging with Python tools
- Version control shows meaningful diffs
- Natural test writing
- Follows established patterns
- Comprehensive documentation available in the `pocketflow/` repo
- Source just 100 lines of code and extremely easy to grasp for AI agents

## Directory Structure Decision

### ✅ RESOLVED
Use `src/pflow/planning/` for the planner implementation.

**Rationale**:
- Maintains consistency with existing module structure (`src/pflow/nodes/` for CLI nodes)
- Aligns with the ambiguities document specification
- Preserves `src/pflow/flows/` for potential future use for packaged pflow CLI workflows (not user-generated)
- Follows the established pattern of organizing by functionality rather than implementation detail

**Implementation Structure**:
```
src/pflow/planning/
├── __init__.py       # Module exports
├── nodes.py          # Planner nodes (discovery, generator, validator, metadata, parameter extraction)
├── flow.py           # create_planner_flow() - orchestrates the nodes
├── ir_models.py      # Pydantic models for IR generation
├── utils/            # Helper utilities
└── prompts/
    └── templates.py  # Prompt templates
```

## What the Planner Returns to CLI

### Structure of Planner Output

The planner returns a structured result that contains everything the CLI needs for execution:

```python
{
    "workflow_ir": {
        # Complete IR with template variables (now with path support)
        "ir_version": "0.1.0",
        "nodes": [...],
        "edges": [...],
        # mappings field omitted in MVP (v2.0 feature)
    },
    "workflow_metadata": {
        "suggested_name": "fix-issue",
        "description": "Fixes a GitHub issue and creates a PR",
        "inputs": ["issue_number", "repo_name"],
        "outputs": ["pr_url", "pr_number"]
    },
    "parameter_values": {
        # Extracted and interpreted values from natural language
        "issue_number": "1234",
        "repo_name": "pflow"  # Could be inferred from context
    }
}
```

### CLI Execution Flow

Upon receiving the planner output, the CLI:

1. **Shows Approval**
   ```
   Generated workflow: fix-issue
   Description: Fixes a GitHub issue and creates a PR
   Will execute with:
     - issue_number: 1234
     - repo_name: pflow

   Approve and save? [Y/n]:
   ```

2. **Saves Workflow** (if approved)
   - Saves IR to `~/.pflow/workflows/{suggested_name}.json`
   - Preserves template variables for future reuse
   - Records metadata for discovery

3. **Executes Workflow**
   - Uses `compile_ir_to_flow()` to create executable
   - Substitutes parameter values for template variables
   - Runs with proper shared store isolation

### Parameter Substitution at Runtime

The runtime proxy transparently handles template variable substitution:
```python
# Workflow contains: {"prompt": "Fix issue: $issue_data"}
# At runtime:
# 1. CLI parameters: {"issue_number": "1234"} → substituted first
# 2. Shared store: {"issue_data": "...actual issue..."} → substituted during execution
# Node sees: {"prompt": "Fix issue: ...actual issue..."}
```

This enables the "Plan Once, Run Forever" philosophy:
- First time: Generate workflow with template variables in params
- Future runs: `pflow fix-issue --issue=5678`
- Runtime proxy handles all substitution transparently

## PocketFlow Execution Model Deep Dive

### Understanding prep() Purpose and Patterns
The `prep()` method in PocketFlow serves a specific purpose: to extract and prepare specific data from the shared store for `exec()`. This separation of concerns keeps `exec()` focused and testable.

```python
def prep(self, shared):
    # Extract specific data needed by exec()
    return shared["user_input"], shared["context"]

def exec(self, prep_res):
    user_input, context = prep_res
    # exec() receives clean, focused inputs
```

**When to return the entire shared dict:**
The only common exception is when using `exec_fallback()` for error handling, since `exec_fallback()` only receives `prep_res` and the exception, not the shared dict:

```python
def prep(self, shared):
    # Return shared when exec_fallback needs access to it
    return shared

def exec_fallback(self, prep_res, exc):
    shared = prep_res  # Access shared through prep_res
    shared["error"] = str(exc)
    return "error"
```

For most nodes, `prep()` should extract specific data to maintain clean separation of concerns.

### prep() Method Best Practices

**Preferred Pattern - Simple Extraction**:
```python
def prep(self, shared):
    return shared["user_input"]  # Single value
    # OR
    return shared["user_input"], shared["context"]  # Multiple values as tuple
```

**When to Return Entire Shared Dict**:
- When exec_fallback needs access to shared state
- When tracking complex attempt history
- Always add a comment explaining why

### Core Execution Loop Understanding
PocketFlow's elegance comes from its simple execution model:
```python
# From pocketflow/__init__.py
while current_node:
    node = self.nodes[current_node]
    node.prep(shared)

    # Retry logic is built into this loop
    for retry in range(node.max_retries):
        try:
            action = node.exec(shared)
            break
        except Exception as e:
            if retry == node.max_retries - 1:
                action = node.exec_fallback(shared, e)

    node.post(shared)
    current_node = edges.get((current_node, action))
```

### Key Technical Constraints
1. **Nodes are stateless** - All state MUST live in `shared` dict
2. **Actions are strings** - Not booleans or complex objects
3. **Edges are tuples** - `(from_node, action) -> to_node`
4. **Retries are per-node** - Not per-flow
5. **Synchronous execution** - No async/parallel (simulated only)

## Advanced Implementation Patterns

### Three-Tier Validation Architecture

**Architecture Context**: The planner itself is implemented as a pocketflow flow with multiple nodes. Validation happens within the planner flow using pocketflow's patterns.

The planner uses a progressive static validation approach that catches issues at the earliest possible stage:

#### 1. **Syntactic Validation** (via Pydantic)
- Ensures well-formed JSON structure through Pydantic models
- Type-safe generation with `model.prompt(prompt, schema=FlowIR)`
- Immediate feedback on structural issues
- **Catches**: Malformed JSON, missing required fields, type mismatches

#### 2. **Static Analysis** (node and parameter validation)
- Verifies all referenced nodes exist in registry
- Checks parameter names and types match node metadata from the registry's interface field
- Validates template variable syntax using actual node outputs from registry (Task 19 enables this)
- Detects circular dependencies and unreachable nodes
- **Catches**: Unknown nodes, invalid parameters, structural issues

#### 3. **Data Flow Analysis** (execution order validation)
This is NOT mock execution - it's static analysis that tracks data flow:
- **What it does**: Traverses nodes in execution order, tracking which keys are available in the shared store at each step
- **How it works**: Uses node metadata (inputs/outputs) from the registry's pre-parsed interface field to verify data dependencies are satisfied
- **Generic approach**: No per-node implementation needed - just uses interface metadata from registry
- **Example**: If `github-get-issue` writes `issue_data`, then `llm` can use `$issue_data.title`
- **Catches**: Missing inputs, overwritten outputs, unresolved template variables, invalid template paths

### Error Recovery Architecture

**Implementation Note**: This validation is performed by a `ValidatorNode` within the planner flow. When validation fails, it returns actions like "validation_failed" that route back to the generator node with specific error feedback.

Each validation tier provides specific error information that guides recovery:

1. **Pydantic/Syntactic Errors** → Retry with format hints
   - "Expected 'nodes' array, got object"
   - "Missing required field 'type' in node"

2. **Static Analysis Errors** → Retry with specific fixes
   - "Node 'analyze-code' not found. Did you mean 'claude-code'?"
   - "Parameter 'temp' invalid. Did you mean 'temperature'?"
   - "Circular dependency: A → B → C → A"

3. **Data Flow Errors** → Retry with flow corrections
   - "Node 'llm' requires 'prompt' but no node produces it"
   - "Key 'summary' is written by multiple nodes"
   - "Template variable $code_report has no source"

### Error-Specific Recovery Strategies

| Error Type | Recovery Strategy | Max Retries |
|------------|------------------|-------------|
| Malformed JSON | Add format example to prompt | 2 |
| Unknown node | Suggest similar nodes from registry | 3 |
| Missing data flow | Add hint about node outputs | 3 |
| Template unresolved | Show available variables | 2 |
| Circular dependency | Simplify to sequential flow | 1 |

### Progressive Enhancement Pattern
For LLM planning, each retry should enhance the prompt with specific guidance:

```python
class ProgressiveGeneratorNode(Node):
    """Generator that enhances prompt on each retry."""

    def __init__(self):
        super().__init__(max_retries=3)
        # Concise, targeted enhancements based on common errors
        self.enhancement_levels = [
            "",  # Level 0: Base prompt with all necessary info
            "\nEnsure all template variables ($var) are used correctly in params.",  # Level 1
            "\nSimplify: use fewer nodes and ensure $variables match shared store keys.",  # Level 2
            "\nUse basic nodes only. Template variables should match data flow naturally."  # Level 3
        ]

    def prep(self, shared):
        """Prepare data for workflow generation."""
        attempt = shared.get("generation_attempts", 0)

        # Build on previous errors if retrying
        enhancement = self.enhancement_levels[min(attempt, len(self.enhancement_levels)-1)]

        # Include specific error feedback if available
        if attempt > 0 and "validation_errors" in shared:
            error_summary = self._summarize_errors(shared["validation_errors"])
            enhancement = f"{enhancement}\nPrevious issues: {error_summary}"

        prompt = shared["base_prompt"] + enhancement

        return {
            "prompt": prompt,
            "attempt": attempt
        }

    def exec(self, prep_res):
        """Generate workflow using enhanced prompt."""
        # Generate with structured output
        response = self.model.prompt(
            prep_res["prompt"],
            schema=WorkflowIR,
            temperature=0  # Deterministic
        )

        return {
            "response": response.text(),
            "attempt": prep_res["attempt"]
        }

    def post(self, shared, prep_res, exec_res):
        """Store results and track attempt history."""
        shared["llm_response"] = exec_res["response"]
        shared["generation_attempts"] = exec_res["attempt"] + 1

        # Track attempt history
        if "attempt_history" not in shared:
            shared["attempt_history"] = []
        shared["attempt_history"].append({
            "attempt": exec_res["attempt"] + 1,
            "enhancement": prep_res["prompt"],
            "timestamp": time.time()
        })

        return "validate"

    def _summarize_errors(self, errors):
        """Format errors for prompt - they're already prompt-ready!"""
        # Validation produces prompt-ready errors, just join them
        # Example errors from validation:
        # - "Unknown template variable $issue_title - ensure it matches shared store key"
        # - "Unknown node 'github-fix-issue' - did you mean 'github-get-issue'?"
        # - "Node 'llm' missing required param 'prompt'"
        return "; ".join(errors[:3])  # Limit to 3 to avoid prompt bloat
```

### Validation with Fixable Error Approach
All validation errors are treated as opportunities for improvement:

```python
class ValidationNode(Node):
    """Validates generated workflows treating all errors as fixable."""

    def prep(self, shared):
        """Get workflow to validate."""
        return shared.get("generated_workflow", {})

    def exec(self, prep_res):
        """Validate the workflow."""
        workflow = prep_res

        # Comprehensive validation
        validation_result = self._validate_workflow(workflow)

        return validation_result

    def post(self, shared, prep_res, exec_res):
        """Store results and determine next action."""
        if exec_res["is_valid"]:
            shared["validated_workflow"] = prep_res  # Store the validated workflow
            return "success"

        # All errors are fixable with proper guidance
        errors = exec_res["errors"]
        shared["validation_errors"] = errors

        # Categorize error for targeted retry
        primary_issue = self._identify_primary_issue(errors)
        shared["primary_validation_issue"] = primary_issue

        # Check retry count
        attempts = shared.get("generation_attempts", 0)
        if attempts >= 3:
            # Even at max retries, we consider it fixable
            # but route to a simpler approach
            return "simplify_request"

        # Route back with specific feedback
        return "retry_with_feedback"

    def _identify_primary_issue(self, errors):
        """Identify the main issue to address first."""
        # Prioritize errors for clearer feedback
        for error in errors:
            if "template variable" in error:
                return "template_variable_issue"
            elif "unknown node" in error.lower():
                return "invalid_nodes"
            elif "ir_version" in error or "structure" in error:
                return "invalid_structure"
        return "general_validation_error"

    def _validate_workflow(self, workflow):
        """Perform comprehensive validation with prompt-ready error messages.

        Note: Node outputs are NOT in the workflow IR - they come from registry metadata.
        Template validation happens separately using registry data.
        """
        errors = []

        # Check structure
        if "ir_version" not in workflow:
            errors.append("Add 'ir_version': '0.1.0' to the workflow")
        if "nodes" not in workflow or not workflow.get("nodes"):
            errors.append("Add a 'nodes' array with at least one node")

        # Check for unknown nodes
        for node in workflow.get("nodes", []):
            if node.get("type") not in self.registry:
                node_type = node.get("type", "unknown")
                similar = self._get_similar_nodes(node_type)
                if similar:
                    errors.append(f"Unknown node '{node_type}' - did you mean '{similar[0]}'?")
                else:
                    errors.append(f"Unknown node '{node_type}' - use 'claude-code' for complex operations")

        # Check template variables in params
        for node in workflow.get("nodes", []):
            # Check if node has template variables in params
            for param_key, param_value in node.get("params", {}).items():
                if isinstance(param_value, str) and '$' in param_value:
                    # Extract template variables including paths like $issue_data.user.login
                    template_vars = re.findall(r'\$(\w+(?:\.[\w\[\]]+)*)', param_value)
                    for var in template_vars:
                        # Just note that it has templates - runtime will handle resolution
                        # No need to validate mappings since they don't exist
                        pass

            # Check if nodes that typically need inputs have appropriate params
            if self._node_typically_needs_input(node.get("type")):
                if "prompt" not in node.get("params", {}):
                    errors.append(
                        f"Node '{node['id']}' ({node['type']}) typically needs a 'prompt' parameter"
                    )

        return {
            "is_valid": len(errors) == 0,
            "errors": errors
        }

    def _generate_error_hint(self, errors):
        """Generate LLM-friendly hints for validation errors."""
        if any("Unknown node" in e for e in errors):
            return "Use only nodes from the available node list provided in the context"
        elif any("circular dependency" in e.lower() for e in errors):
            return "Ensure your workflow doesn't have cycles - each node should flow forward"
        elif any("template variable" in e.lower() or "$" in e for e in errors):
            return "Check that all $variables reference data from earlier nodes or CLI parameters"
        elif any("prompt" in e.lower() for e in errors):
            return "LLM nodes typically need a 'prompt' parameter with the text to process"
        else:
            return "Check the workflow structure and ensure all nodes are properly connected"

```

### Topological Sort for Data Flow Analysis

The data flow analysis requires traversing nodes in execution order. This helper function determines that order:

```python
def get_execution_order(nodes, edges):
    """
    Determine node execution order from edges using topological sort.
    Returns nodes in the order they would execute.
    Raises ValueError if circular dependencies are detected.
    """
    # Build adjacency list and in-degree count
    graph = {node['id']: [] for node in nodes}
    in_degree = {node['id']: 0 for node in nodes}

    for edge in edges:
        graph[edge['from']].append(edge['to'])
        in_degree[edge['to']] += 1

    # Find nodes with no dependencies
    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    ordered = []

    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)

        # Process dependent nodes
        for next_id in graph[node_id]:
            in_degree[next_id] -= 1
            if in_degree[next_id] == 0:
                queue.append(next_id)

    if len(ordered) != len(nodes):
        raise ValueError("Circular dependency detected in workflow")

    # Return nodes in execution order
    node_map = {n['id']: n for n in nodes}
    return [node_map[node_id] for node_id in ordered]
```

### Attempt History Tracking Pattern
Track attempts to avoid repeating mistakes and provide context:

```python
class AttemptHistoryMixin:
    """Mixin for tracking attempt history in planner nodes."""

    def track_attempt(self, shared, phase, outcome, details=None):
        """Track each attempt for debugging and learning."""
        if "attempt_history" not in shared:
            shared["attempt_history"] = []

        attempt_record = {
            "attempt": len(shared["attempt_history"]) + 1,
            "phase": phase,  # "generation", "validation", etc.
            "outcome": outcome,  # "success", "failed", "retry"
            "timestamp": time.time()
        }

        if details:
            attempt_record["details"] = details

        # Include specific errors if validation failed
        if phase == "validation" and "validation_errors" in shared:
            attempt_record["errors"] = shared["validation_errors"][:3]  # Limit size

        shared["attempt_history"].append(attempt_record)

    def get_attempt_summary(self, shared):
        """Get concise summary of attempts for prompt enhancement."""
        history = shared.get("attempt_history", [])
        if not history:
            return ""

        # Summarize key issues from previous attempts
        issues = []
        for attempt in history[-2:]:  # Look at last 2 attempts only
            if "errors" in attempt:
                for error in attempt["errors"]:
                    if "Missing template variable" in error or "Unknown template variable" in error:
                        issues.append("missing template variables in params")
                    elif "Unknown node" in error:
                        # Extract node name if possible
                        match = re.search(r"Unknown node[: ]+(\w+)", error)
                        if match:
                            issues.append(f"invalid node '{match.group(1)}'")

        return "; ".join(set(issues)) if issues else ""

# Usage in generator node
class WorkflowGeneratorNode(Node, AttemptHistoryMixin):
    def prep(self, shared):
        # Extract specific data needed for generation
        return shared["user_input"], shared["planning_context"], shared.get("generation_attempts", 0)

    def exec(self, prep_res):
        # Unpack the tuple
        user_input, planning_context, generation_attempts = prep_res

        # Generate workflow...
        response = self.model.prompt(
            self._build_prompt(user_input, planning_context),
            schema=WorkflowIR
        )

        return {
            "response": response,
            "attempt": generation_attempts
        }

    def post(self, shared, prep_res, exec_res):
        # Track generation attempt
        self.track_attempt(shared, "generation", "started")

        if exec_res["response"]:
            self.track_attempt(shared, "generation", "success",
                             {"model": "claude-sonnet-4-20250514"})
            shared["generated_workflow"] = exec_res["response"]
        else:
            self.track_attempt(shared, "generation", "failed",
                             {"error": "No response from LLM"})

        return "validate"
```

### Checkpoint and Recovery Pattern
Save state for recovery:

```python
class CheckpointNode(Node):
    """Creates recovery checkpoints."""

    def __init__(self, checkpoint_name):
        super().__init__()
        self.checkpoint_name = checkpoint_name

    def prep(self, shared):
        # Return shared so we can access it in exec_fallback if needed
        return shared

    def post(self, shared, prep_res, exec_res):
        # Save checkpoint after successful execution
        checkpoint = {
            "name": self.checkpoint_name,
            "timestamp": time.time(),
            "shared_state": shared.copy()
        }

        if "checkpoints" not in shared:
            shared["checkpoints"] = []
        shared["checkpoints"].append(checkpoint)

    def exec_fallback(self, prep_res, exc):
        # prep_res is the shared dict (from prep method)
        shared = prep_res

        # On failure, restore from checkpoint
        if "checkpoints" in shared and shared["checkpoints"]:
            last_checkpoint = shared["checkpoints"][-1]
            for key in ["generated_workflow", "validation_state"]:
                if key in last_checkpoint["shared_state"]:
                    shared[key] = last_checkpoint["shared_state"][key]
        return "recovery"
```

### Parallel Strategy Simulation Pattern
Simulate parallel execution within synchronous PocketFlow:

```python
class ParallelStrategyNode(Node):
    """Simulates parallel execution of multiple strategies."""

    def prep(self, shared):
        # Return base prompt from shared
        return shared.get("base_prompt", "")

    def exec(self, prep_res):
        base_prompt = prep_res

        strategies = [
            ("concise", "Generate a minimal workflow"),
            ("detailed", "Generate a comprehensive workflow"),
            ("hybrid", "Balance between simple and complete")
        ]

        results = {}
        best_score = -1
        best_strategy = None

        for strategy_name, strategy_prompt in strategies:
            # Try each strategy
            response = call_llm(f"{base_prompt}\n{strategy_prompt}")

            # Score the response
            score = self._score_response(response)
            results[strategy_name] = {
                "response": response,
                "score": score
            }

            if score > best_score:
                best_score = score
                best_strategy = strategy_name

        # Return results to be stored in post
        return {
            "strategy_results": results,
            "selected_strategy": best_strategy,
            "best_response": results[best_strategy]["response"]
        }

    def post(self, shared, prep_res, exec_res):
        # Store all results for debugging
        shared["strategy_results"] = exec_res["strategy_results"]
        shared["selected_strategy"] = exec_res["selected_strategy"]
        shared["llm_response"] = exec_res["best_response"]

        return "validate"

    def _score_response(self, response):
        """Score response based on validity, complexity, completeness."""
        score = 0
        try:
            # Valid JSON?
            json.loads(response)
            score += 40
        except:
            return 0

        # Has required nodes?
        if "nodes" in response:
            score += 30

        # Reasonable complexity?
        node_count = len(json.loads(response).get("nodes", []))
        if 2 <= node_count <= 10:
            score += 30

        return score
```

### Dynamic Input Classification Pattern
Smart routing based on input analysis:

```python
class ClassifyInputNode(Node):
    """Dynamically classify and route input."""

    def prep(self, shared):
        # Return user input for classification
        return shared.get("user_input", "")

    def exec(self, prep_res):
        user_input = prep_res

        # Smart classification
        if self._looks_like_cli(user_input):
            return {
                "input_type": "cli_syntax",
                "action": "parse_cli"
            }
        elif self._looks_like_natural(user_input):
            return {
                "input_type": "natural_language",
                "action": "natural_language"
            }
        else:
            # Ambiguous - need more analysis
            return {
                "input_type": "ambiguous",
                "action": "ask_user"
            }

    def post(self, shared, prep_res, exec_res):
        # Store classification result
        shared["input_type"] = exec_res["input_type"]
        return exec_res["action"]  # Return the routing action

    def _looks_like_cli(self, input_str):
        """Check if input looks like CLI syntax."""
        return ">>" in input_str or "--" in input_str

    def _looks_like_natural(self, input_str):
        """Check if input looks like natural language."""
        return input_str.startswith('"') and input_str.endswith('"')
```

### Conditional Validation Pattern
Different validation outcomes trigger different paths:

```python
class ConditionalValidatorNode(Node):
    """Validates with conditional retry logic."""

    def prep(self, shared):
        # Return workflow to validate
        return shared.get("generated_workflow", {})

    def exec(self, prep_res):
        workflow = prep_res
        result = self.validator.validate(workflow)

        return {
            "is_valid": result.is_valid,
            "is_fixable": result.is_fixable,
            "errors": result.errors
        }

    def post(self, shared, prep_res, exec_res):
        if exec_res["is_valid"]:
            return "success"
        elif exec_res["is_fixable"]:
            # Some errors can be automatically fixed
            shared["validation_errors"] = exec_res["errors"]
            return "retry_with_fixes"
        else:
            # Fatal errors require different approach
            shared["fatal_errors"] = exec_res["errors"]
            return "fallback_strategy"
```

## Flow Design Patterns

### Diamond Pattern with Convergence

### Unified Discovery Pattern

**Key Insight**: The context builder already solved the discovery problem! We can use the same pattern for everything.

This pattern is formalized by Task 15 which splits the context builder into discovery and planning phases, preventing LLM overwhelm while enabling workflow reuse.

#### Critical Architectural Refinements:

1. **Workflows ARE building blocks** - Other workflows can be used inside new workflows
2. **Two different contexts needed**:
   - **Discovery context**: Just names and descriptions (for finding what to use)
   - **Planning context**: Full interface details (only for selected nodes/workflows)
3. **Separation of concerns**: Discovery vs. implementation planning

#### The Two-Phase Architecture:

**Phase 1: Discovery Context (lightweight browsing)**
- Load all nodes (names + descriptions only)
- Load all workflows (names + descriptions only)
- LLM selects which components to use
- Minimal information prevents cognitive overload

**Phase 2: Planning Context (detailed interfaces)**
- Load full details ONLY for selected nodes/workflows
- LLM plans the shared store layout and connections
- Generate IR with proper mappings
- Focused context enables accurate planning

#### Architectural Benefits:

1. **Workflows as first-class citizens** - Can compose workflows from other workflows
2. **Focused contexts** - Discovery gets minimal info, planning gets full details
3. **Performance** - Don't load full interface details for 100+ nodes during discovery
4. **Clarity** - LLM isn't overwhelmed with irrelevant interface details
5. **Scalability** - Pattern works regardless of node/workflow count

#### Implementation Architecture:

```python
# Discovery phase via Task 15's build_discovery_context()
discovery_context = build_discovery_context()
# Returns lightweight markdown with names + descriptions

# Planning phase via Task 15's build_planning_context()
planning_context = build_planning_context(
    selected_nodes,
    selected_workflows
)
# Returns detailed interface specifications
```

**Key Architectural Principle**: Workflows are just reusable node compositions - they should appear alongside nodes as building blocks!

## Testing PocketFlow Flows

### Node Isolation Testing
Test individual nodes without running full flow:

```python
def test_node_in_isolation():
    """Test nodes without running full flow."""
    node = ProgressiveGeneratorNode()
    shared = {"base_prompt": "test prompt", "generation_attempts": 2}

    # First call prep to get data for exec
    prep_res = node.prep(shared)

    # Simulate retry behavior
    node.cur_retry = 2  # Simulate third attempt
    exec_res = node.exec(prep_res)

    # Call post to update shared state
    action = node.post(shared, prep_res, exec_res)

    assert "workflow" in exec_res
    assert shared["generation_attempts"] == 3
```

### Flow Path Testing
Test specific execution paths:

```python
def test_specific_flow_path():
    """Test specific execution path."""
    flow = create_planner_flow()

    # Mock specific nodes to control path
    with patch.object(WorkflowGeneratorNode, 'exec', return_value='validate'):
        with patch.object(ValidatorNode, 'exec', return_value='invalid'):
            shared = {"user_input": "test"}
            result = flow.run(shared)

            # Verify we took the retry path
            assert "attempts" in result
            assert result["attempts"] > 1
```

## Performance Considerations

### Node Design Guidelines
1. **Node Granularity**: Keep nodes focused - PocketFlow's overhead is minimal per node
2. **Shared Store Size**: While dictionary access is O(1), large objects in shared can impact memory
3. **Retry Strategy**: Use exponential backoff in exec() not just retry count
4. **Action String Optimization**: Keep action strings short - they're used as dict keys

### Optimization Strategies
- Cache LLM responses when possible
- Use prep() for expensive initialization
- Minimize shared store copying in checkpoints
- Consider memory usage of attempt history

## Anti-Patterns to Avoid

### Critical Anti-Patterns
1. **Stateful Nodes**: Don't store state in node instances - use shared store
   ```python
   # ❌ WRONG
   class BadNode(Node):
       def __init__(self):
           self.counter = 0  # Don't do this!

   # ✅ CORRECT
   class GoodNode(Node):
       def prep(self, shared):
           return shared.get("counter", 0)

       def exec(self, prep_res):
           return prep_res + 1

       def post(self, shared, prep_res, exec_res):
           shared["counter"] = exec_res
   ```

2. **Complex Actions**: Actions should be simple strings, not encoded data
   ```python
   # ❌ WRONG
   return json.dumps({"action": "retry", "reason": "error"})

   # ✅ CORRECT
   return "retry_on_error"
   ```

3. **Deep Nesting**: Avoid flows within flows - flatten when possible
4. **Blocking Operations**: PocketFlow is synchronous - long operations block the flow

### Planner-Specific Anti-Patterns (From Research Analysis)

5. **Single Discovery Node**: Don't merge workflow and component discovery
   ```python
   # ❌ WRONG - Trying to handle both cases in one node
   class DiscoveryNode(Node):
       def exec(self, shared):  # WRONG: exec() should never receive shared directly!
           # Confused logic trying to both find complete workflows
           # AND browse for components in the same node

   # ✅ CORRECT - Two distinct nodes with clear purposes
   # WorkflowDiscoveryNode: finds COMPLETE workflows only
   # ComponentBrowsingNode: browses for building blocks when no complete match
   ```

6. **Hardcoded Pattern Libraries**: Don't create fixed workflow patterns
   ```python
   # ❌ WRONG - Rigid and inflexible
   WORKFLOW_PATTERNS = {
       "github_fix": ["github-get-issue", "claude-code", "git-commit"],
       "document_analysis": ["read-file", "llm", "write-file"]
   }

   # ✅ CORRECT - Let LLM compose based on context
   # Provide examples in prompts, not hardcoded patterns
   ```

6. **Variable Inference Logic**: Don't try to "guess" variable sources
   ```python
   # ❌ WRONG - Brittle hardcoded inference
   def _infer_variable_source(self, variable: str, workflow: dict):
       if variable == "issue" or variable == "issue_data":
           for node in workflow["nodes"]:
               if node["type"] == "github-get-issue":
                   return f"{node['id']}.outputs.issue_data"

   # ✅ CORRECT - Use simple template variables in params
   # LLM puts $variables directly in node params
   # Runtime proxy handles resolution transparently
   ```

7. **Template Enhancement After Generation**: Don't modify LLM output
   ```python
   # ❌ WRONG - Second-guessing the LLM
   if len(prompt) < 50:  # "Too simple"
       workflow["nodes"][i]["params"]["prompt"] = enhance_prompt(prompt)

   # ✅ CORRECT - Trust LLM or retry with feedback
   # If output is insufficient, retry with specific guidance
   ```


9. **Mixing Validation with Generation**: Keep concerns separated
   ```python
   # ❌ WRONG - Inference during validation
   def validate_templates(self, workflow):
       # Try to guess where variables come from
       if "$issue" in prompt:
           # Infer it must come from github-get-issue...

   # ✅ CORRECT - Simple validation only
   def validate_templates(self, workflow):
       # Just check that $variables are used consistently
       # Runtime proxy handles actual resolution
   ```

10. **Unstructured Iterative Loops**: Don't use endless refinement loops
    ```python
    # ❌ WRONG - Endless loop without clear termination
    while not is_perfect(workflow):
        workflow = regenerate_with_vague_feedback(workflow)

    # ✅ CORRECT - Structured retry with specific feedback via PocketFlow
    # PocketFlow handles retry routing based on validation results
    generator - "validation_failed" >> enhance_prompt >> generator
    validator - "missing_nodes" >> error_feedback >> generator
    # Max retries enforced, specific error feedback provided
    ```

11. **Executing User Workflows Within Planner**: Don't have the planner execute user workflows
    ```python
    # ❌ WRONG - Planner executing user workflows directly
    class WorkflowExecutionNode(Node):
        def exec(self, shared):  # WRONG: exec() should never receive shared directly!
            flow = compile_ir_to_flow(workflow_ir)
            result = flow.run(...)  # Planner running user workflow

    # ✅ CORRECT - Planner returns results for CLI execution
    class ResultPreparationNode(Node):
        def prep(self, shared):
            # Extract specific data
            return shared.get("workflow_ir"), shared.get("parameter_values")

        def exec(self, prep_res):
            workflow_ir, parameter_values = prep_res
            # Package the results
            return {
                "workflow_ir": workflow_ir,
                "parameter_values": parameter_values
            }

        def post(self, shared, prep_res, exec_res):
            shared["planner_output"] = exec_res
            # CLI handles execution from here
    ```

12. **Code Generation Instead of Workflows**: We're not generating Python
    ```python
    # ❌ WRONG - Generating executable code
    generated_code = """
    def workflow():
        result = github.get_issue(123)
        fix = ai.generate_fix(result)
    """

    # ✅ CORRECT - Generate workflow IR
    workflow = {
        "nodes": [
            {"id": "get-issue", "type": "github-get-issue"},
            {"id": "fix", "type": "claude-code"}
        ]
    }
    ```

12. **Complex State in Planner**: Planner should be stateless
    ```python
    # ❌ WRONG - Maintaining state across requests
    class Planner:
        def __init__(self):
            self.previous_workflows = []
            self.user_preferences = {}

    # ✅ CORRECT - Each request is independent
    def plan_workflow(user_input: str, context: str) -> dict:
        # Stateless - each call is independent
        return generate_workflow(user_input, context)
    ```

13. **Wrong Model Selection**: Don't use incorrect model names
    ```python
    # ❌ WRONG - Using wrong model names
    model = "gpt-4" if complex else "gpt-3.5-turbo" # Wrong!
    model = llm.get_model("claude-3-5-sonnet-latest")  # Wrong!
    model = llm.get_model("gpt-4o-mini")  # Wrong!

    # ✅ CORRECT - Use specified model consistently
    model = llm.get_model("claude-sonnet-4-20250514")
    ```

14. **Template Fallback System**: Don't use predefined templates
    ```python
    # ❌ WRONG - Falling back to rigid templates
    if generation_failed:
        return PREDEFINED_TEMPLATES["github_workflow"]

    # ✅ CORRECT - Retry with better guidance
    if generation_failed:
        return "retry_with_simplified_request"
    ```

15. **Direct CLI Parsing**: MVP routes everything through LLM
    ```python
    # ❌ WRONG - Complex CLI parsing logic
    if ">>" in user_input:
        nodes = parse_cli_syntax(user_input)
        return compile_nodes(nodes)

    # ✅ CORRECT - Everything through LLM for MVP
    # Both natural language and CLI-like syntax go to LLM
    return llm_planner.generate_workflow(user_input)
    ```

16. **Missing Critical Fields**: Workflows need required fields
    ```python
    # ❌ WRONG - Incomplete workflow structure
    workflow = {
        "nodes": [...],
        "edges": [...]
    }

    # ✅ CORRECT - Complete JSON IR structure per schema
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [...],  # Contains $variables in params
        "edges": [...],
        "start_node": "n1",  # Optional
        "mappings": {...}     # Optional proxy mappings
    }
    ```

17. **Using Non-Existent Fields**: NEVER use template_inputs or variable_flow - They DO NOT EXIST!
    ```python
    # ❌ WRONG - These fields DO NOT EXIST in the IR schema!
    # This is a critical anti-pattern - these were NEVER implemented
    workflow = {
        "template_inputs": {  # DOES NOT EXIST - will cause validation errors
            "llm": {"prompt": "Fix: $issue"}
        },
        "variable_flow": {    # DOES NOT EXIST - will cause validation errors
            "issue": "github-get-issue.outputs.issue_data"
        }
    }

    # ✅ CORRECT - Use template variables directly in params
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "llm", "type": "llm",
             "params": {"prompt": "Fix: $issue_data"}}  # Templates go in params!
        ],
        "edges": []
    }
    # Runtime proxy automatically resolves $issue_data from shared["issue_data"]
    ```

18. **Complex Variable Mappings**: Don't create elaborate mapping structures
    ```python
    # ❌ WRONG - Over-engineering variable resolution
    # Don't create mapping structures to specify where variables come from
    # Don't try to map template variables to sources
    # The runtime proxy handles ALL of this transparently

    # ✅ CORRECT - Simple naming convention
    # Just use $variables in params:
    # - $issue_number → runtime proxy finds it in CLI params
    # - $issue_data → runtime proxy finds it in shared["issue_data"]
    # No mappings needed - just consistent naming!
    ```

19. **Using PocketFlow Everywhere Internally**: Don't over-apply the meta concept
    ```python
    # ❌ WRONG - Using PocketFlow for simple components
    # "IR compiler uses PocketFlow"
    # "Shell integration uses PocketFlow"
    # "Registry uses PocketFlow"

    # ✅ CORRECT - Only the planner uses PocketFlow
    # Everything else uses traditional Python:
    # - CLI: Click framework
    # - Registry: Standard Python classes
    # - Compiler: Direct Python functions
    # - Runtime: Traditional execution logic

    # The planner is the ONLY exception due to its unique complexity
    ```

20. **Proxy Mappings in MVP**: Don't implement proxy mappings based on research files
    ```python
    # ❌ WRONG - Research files mention proxy mappings extensively
    # Don't look for "proxy_mappings" field in nodes (it doesn't exist)
    # Don't implement proxy mapping generation logic
    # The schema has top-level "mappings" but it's a v2.0 feature

    # ✅ CORRECT - Use template variables with path support for MVP
    # Template paths like $issue_data.user.login handle 90% of use cases
    # Proxy mappings are explicitly deferred to v2.0
    # Focus on the simpler, more elegant template variable solution
    ```

- Include examples in prompts showing correct `$variable` and `$data.field` usage

## Key Implementation Principles

### From Research Analysis
1. **Focused Complexity** - PocketFlow only where it truly adds value
2. **Clear Boundaries** - Planner is special, everything else is traditional
3. **Selective Dogfooding** - Validates PocketFlow for its best use case
4. **Stateless Design** - All state in shared store, nodes are pure
5. **String Actions** - Keep routing simple with string-based actions

### Decision Criteria for Future Changes
Use PocketFlow when a component has:
- Complex retry strategies with multiple approaches
- Self-correcting loops (e.g., LLM validation)
- Genuinely complex branching logic
- Multiple interdependent external API calls
- Benefits from visual flow representation

Use traditional code for everything else.

### Why Only the Planner?

The planner is unique in pflow's architecture because it:

1. **Orchestrates Multiple Complex Operations**: Discovery → Generation → Validation → Parameter Mapping → Result Preparation
2. **Requires Sophisticated Error Recovery**: Different strategies for different LLM failures
3. **Has True Branching Logic**: Found workflow vs create new, with completely different paths
4. **Benefits from State Accumulation**: Learning from failed attempts to improve prompts
5. **Creates Its Own Product**: A PocketFlow workflow creating other PocketFlow workflows

No other component in pflow has this level of orchestration complexity. The CLI parses arguments, the registry scans files, the compiler transforms data structures - all straightforward operations best implemented with traditional code.

### The Meta-Layer Philosophy

The planner's use of PocketFlow creates a beautiful symmetry:
- **Users** describe workflows in natural language
- **Planner** (a PocketFlow workflow) interprets and creates workflows
- **Result** is a PocketFlow workflow for users

This is intentional dogfooding at the most appropriate level - using the framework where it genuinely adds value, not forcing it everywhere.

## Error Context Enrichment for Development Debugging

### Enriched Error Context Pattern

During development, the planner's complex orchestration benefits greatly from rich error context. This pattern captures comprehensive debugging information when failures occur:

```python
class PlannerNodeBase(Node):
    """Base class for planner nodes with enhanced error tracking."""

    def enrich_error_context(self, shared, exc, context=None):
        """Enrich error with debugging context for development."""
        error_info = {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "node_name": self.__class__.__name__,
            "timestamp": time.time(),

            # Planner-specific context
            "user_input": shared.get("user_input"),
            "input_type": shared.get("input_type"),  # natural vs cli
            "execution_path": shared.get("execution_path", []),  # Which nodes executed

            # LLM debugging context
            "generation_attempts": shared.get("generation_attempts", 0),
            "last_prompt_length": len(shared.get("planning_prompt", "")),
            "context_size": len(shared.get("planning_context", "")),
            "selected_components": shared.get("selected_components", []),

            # Validation context
            "validation_errors": shared.get("validation_errors", []),
            "attempt_history": shared.get("attempt_history", [])[-3:],  # Last 3 attempts

            # Additional context
            "custom_context": context or {}
        }

        # Track execution path
        if "execution_path" not in shared:
            shared["execution_path"] = []
        shared["execution_path"].append(self.__class__.__name__)

        # Store error
        shared["last_error"] = error_info
        shared["error_history"] = shared.get("error_history", [])
        shared["error_history"].append(error_info)

        return error_info
```

### Applied to Key Planner Nodes

```python
class WorkflowGeneratorNode(PlannerNodeBase):
    def prep(self, shared):
        # Note: Returning shared dict here because exec_fallback needs access to it
        # exec_fallback only receives prep_res and exc, not shared directly
        # This is a valid pattern when error handling needs full context
        return shared

    def exec_fallback(self, prep_res, exc):
        """Enhanced fallback with debugging context."""
        # prep_res is the shared dict
        shared = prep_res

        # Enrich with generation-specific context
        context = {
            "llm_model": "claude-sonnet-4-20250514",
            "temperature": 0,
            "retry_attempt": self.cur_retry,
            "prompt_enhancements": shared.get("prompt_enhancements", []),
            "last_llm_response": shared.get("llm_response", "")[:500]  # First 500 chars
        }

        error_info = self.enrich_error_context(shared, exc, context)

        # Log for development debugging
        print(f"\n[Generator Error] Attempt {self.cur_retry + 1}/{self.max_retries}")
        print(f"Error Type: {error_info['error_type']}")
        print(f"User Input: {error_info['user_input']}")
        print(f"Validation Errors: {error_info['validation_errors']}")

        return "generation_failed"

class ValidatorNode(PlannerNodeBase):
    def prep(self, shared):
        # Return both workflow and shared for access in exec
        return {
            "workflow": shared.get("generated_workflow", {}),
            "shared": shared
        }

    def exec(self, prep_res):
        workflow = prep_res["workflow"]
        validation_result = self._validate_workflow(workflow)

        if not validation_result["is_valid"]:
            # Enrich validation errors with context
            errors_with_context = []
            for error in validation_result["errors"]:
                error_context = {
                    "error": error,
                    "workflow_nodes": [n["type"] for n in workflow.get("nodes", [])],
                    "workflow_size": len(str(workflow)),
                    "has_template_vars": any("$" in str(workflow))
                }
                errors_with_context.append(error_context)

            return {
                "is_valid": False,
                "errors_with_context": errors_with_context
            }

        return {"is_valid": True}

    def post(self, shared, prep_res, exec_res):
        if not exec_res["is_valid"]:
            shared["validation_errors"] = exec_res["errors_with_context"]
            shared["validation_failure_count"] = shared.get("validation_failure_count", 0) + 1
            return "invalid"

        return "valid"
```

### Development-Time Benefits

This enriched error context immediately reveals:

1. **LLM Generation Issues**:
   ```python
   "error_context": {
       "user_input": "fix github issue 1234 and notify team on slack",
       "generation_attempts": 3,
       "last_prompt_length": 15234,  # Prompt might be too long
       "validation_errors": [
           {"error": "Unknown node 'slack-notify'", "workflow_nodes": ["github-get-issue", "slack-notify"]},
           {"error": "Template variable $team_channel not defined"}
       ]
   }
   ```

2. **Path-Specific Failures**:
   ```python
   "execution_path": ["WorkflowDiscoveryNode", "ComponentBrowsingNode", "GeneratorNode", "ValidatorNode"],
   # Shows it went through Path B (generation) not Path A (reuse)
   ```

3. **Progressive Enhancement Tracking**:
   ```python
   "attempt_history": [
       {"attempt": 1, "error": "Missing edges in IR"},
       {"attempt": 2, "error": "Invalid node ID format", "enhancement": "Added structure example"},
       {"attempt": 3, "error": "Template path validation failed", "enhancement": "Simplified prompt"}
   ]
   ```

### Usage During Development

```python
# In development/debugging mode
def create_planner_flow(debug=False):
    flow = Flow("planner_meta_workflow")

    if debug:
        # Add execution tracking
        shared["debug_mode"] = True
        shared["start_time"] = time.time()
        shared["execution_path"] = []

    # ... rest of flow setup ...

    return flow

# When running tests or debugging
result = planner_flow.run({
    "user_input": "complex natural language request",
    "debug_mode": True
})

if result.get("last_error"):
    # Rich debugging output
    print(json.dumps(result["last_error"], indent=2))
```

This pattern accelerates development by making failures immediately understandable, showing not just what failed but why and in what context.

---
*Continued in task-17-implementation-guide.md and task-17-core-concepts.md*
