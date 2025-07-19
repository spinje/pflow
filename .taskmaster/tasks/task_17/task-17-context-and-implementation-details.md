# Task 17: Natural Language Planner - Context and Implementation Details

This document synthesizes key insights from research files to provide actionable implementation guidance for the Natural Language Planner System. It complements the ambiguities document by providing concrete architectural decisions and implementation patterns.

## Critical Insight: The Meta-Workflow Architecture

### The Planner IS a Workflow That Creates AND Executes Workflows

The Natural Language Planner is fundamentally a **meta-workflow** - a PocketFlow workflow that:
1. **Discovers or creates** workflows based on user intent
2. **Extracts parameters** from natural language
3. **Maps parameters** to template variables
4. **Confirms** with the user
5. **Executes** the workflow with proper mappings

This is NOT two separate systems - it's ONE unified workflow that handles the entire lifecycle.

### MVP vs Future Architecture

**MVP (All execution through planner):**
```
User Input: "fix github issue 1234"
    ↓
[Planner Meta-Workflow]
    ├─> Discovery: Does "fix-issue" workflow exist?
    ├─> Parameter Extraction: {"issue": "1234"}
    ├─> Mapping: {"issue": "1234"} → $issue_number
    ├─> Confirmation: Show user what will run
    └─> Execution: Run workflow with mappings
```

**v2.0+ (Direct execution for known workflows):**
```
pflow fix-issue --issue=1234  # Bypasses planner entirely
```

### Key Architectural Implications

1. **The planner workflow includes execution** - It doesn't just generate IR and hand off
2. **Parameter mapping is integral** - Not a separate system or afterthought
3. **Every MVP execution is meta** - Even reusing existing workflows goes through the full planner
4. **Branching is essential** - Found vs create paths within the same workflow

## Architectural Decision: PocketFlow for Planner Orchestration

### Core Decision
The Natural Language Planner is the **ONLY** component in the entire pflow system that uses PocketFlow for internal orchestration. This decision is based on the planner's unique complexity requirements.

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
class ComponentDiscoveryNode(Node):
    """Browse available components (nodes + workflows) for potential relevance"""
    def exec(self, shared):
        user_input = shared["user_input"]

        # Phase 1: Use context builder's discovery context (lightweight)
        discovery_context = self.context_builder.build_discovery_context()

        # Browse for potentially relevant components
        selected_components = self._browse_components(user_input, discovery_context)

        # Phase 2: Get detailed context for selected components only
        planning_context = self.context_builder.build_planning_context(
            selected_components["node_ids"],
            selected_components["workflow_names"]
        )

        shared["selected_components"] = selected_components
        shared["planning_context"] = planning_context

        # Now determine if we can reuse an existing workflow
        if self._exact_workflow_match(selected_components["workflows"], user_input):
            shared["found_workflow"] = self._get_matching_workflow()
            return "found_existing"
        else:
            return "generate_new"

class ParameterExtractionNode(Node):
    """Extracts and interprets parameters from natural language"""
    def exec(self, shared):
        user_input = shared["user_input"]
        workflow = shared.get("found_workflow") or shared.get("generated_workflow")

        # Current time context for temporal interpretation
        current_date = shared.get("current_date", datetime.now().isoformat()[:10])

        # Extract AND interpret parameters
        # "fix github issue 1234" → {"issue": "1234"}
        # "analyze churn for last month" → {"period": "2024-11", "period_type": "month"}
        # "analyze churn since January" → {"start_date": "2024-01-01"}
        params = self._extract_and_interpret_parameters(user_input, workflow, current_date)
        shared["extracted_params"] = params
        return "map_params"

    def _extract_and_interpret_parameters(self, user_input: str, workflow: dict, current_date: str) -> dict:
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

class ParameterMappingNode(Node):
    """Maps extracted params to workflow template variables"""
    def exec(self, shared):
        params = shared["extracted_params"]
        workflow = shared.get("found_workflow") or shared.get("generated_workflow")

        # Map: {"issue": "1234"} → {"$issue_number": "1234"}
        mappings = self._create_mappings(params, workflow["template_inputs"])
        shared["parameter_mappings"] = mappings
        return "confirm"

class GeneratorNode(Node):
    """Generates new workflow if none found"""
    def exec(self, shared):
        # Generate complete workflow with template variables
        workflow = self._generate_workflow(shared["user_input"])
        shared["generated_workflow"] = workflow
        return "extract_params"

class ConfirmationNode(Node):
    """Shows user what will be executed"""
    def exec(self, shared):
        workflow = shared.get("found_workflow") or shared.get("generated_workflow")
        mappings = shared["parameter_mappings"]

        # Show: "Will run 'fix-issue' with issue=1234"
        if self._get_user_confirmation(workflow, mappings):
            return "execute"
        else:
            return "cancelled"

class WorkflowExecutionNode(Node):
    """Actually executes the workflow with mappings"""
    def exec(self, shared):
        workflow = shared.get("found_workflow") or shared.get("generated_workflow")
        mappings = shared["parameter_mappings"]

        # Execute the workflow with parameter substitution
        result = self._execute_workflow(workflow, mappings)
        shared["execution_result"] = result
        return "completed"

# The complete meta-workflow
def create_planner_flow():
    flow = Flow("planner_meta_workflow")

    # All nodes
    discovery = WorkflowDiscoveryNode()
    param_extract = ParameterExtractionNode()
    param_map = ParameterMappingNode()
    generator = GeneratorNode()
    validator = ValidatorNode()
    confirm = ConfirmationNode()
    execute = WorkflowExecutionNode()

    # Main flow with branching
    flow.add_edge(discovery, "found", param_extract)
    flow.add_edge(discovery, "not_found", generator)
    flow.add_edge(generator, "success", validator)
    flow.add_edge(validator, "valid", param_extract)
    flow.add_edge(param_extract, "map_params", param_map)
    flow.add_edge(param_map, "confirm", confirm)
    flow.add_edge(confirm, "execute", execute)

    # Error handling
    flow.add_edge(validator, "invalid", generator)  # Retry

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
    "generated_workflow": {...},

    # Validation results
    "validation_result": "missing_params",
    "validation_errors": ["Node 'llm' requires 'prompt' parameter"],

    # Final output
    "final_workflow": {...},
    "approval_status": "pending"
}
```

### What This Means for Implementation
1. **All other components use traditional Python** - No PocketFlow elsewhere
2. **Planner gets retry/fallback benefits** - Built-in fault tolerance
3. **Clear architectural boundary** - Only planner uses flow patterns internally
4. **Performance is not a concern** - Nodes are just method calls; LLM dominates execution time

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
├── nodes.py          # Planner nodes (discovery, generator, validator, approval)
├── flow.py           # create_planner_flow() - orchestrates the nodes
├── ir_models.py      # Pydantic models for IR generation
├── utils/            # Helper utilities
└── prompts/
    └── templates.py  # Prompt templates
```

## PocketFlow Execution Model Deep Dive

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
            "\nEnsure all template variables ($var) have complete mappings in variable_flow.",  # Level 1
            "\nSimplify: use fewer nodes and provide explicit variable_flow for ALL $variables.",  # Level 2
            "\nUse basic nodes only. Every $variable MUST have a source in variable_flow."  # Level 3
        ]

    def exec(self, shared):
        # Track attempt history
        attempt = shared.get("generation_attempts", 0)
        shared["generation_attempts"] = attempt + 1

        # Build on previous errors if retrying
        enhancement = self.enhancement_levels[min(attempt, len(self.enhancement_levels)-1)]

        # Include specific error feedback if available
        if attempt > 0 and "validation_errors" in shared:
            error_summary = self._summarize_errors(shared["validation_errors"])
            enhancement = f"{enhancement}\nPrevious issues: {error_summary}"

        prompt = shared["base_prompt"] + enhancement

        # Generate with structured output
        response = self.model.prompt(
            prompt,
            schema=WorkflowIR,
            temperature=0  # Deterministic
        )

        shared["llm_response"] = response.text()

        # Track attempt history
        if "attempt_history" not in shared:
            shared["attempt_history"] = []
        shared["attempt_history"].append({
            "attempt": attempt + 1,
            "enhancement": enhancement,
            "timestamp": time.time()
        })

        return "validate"

    def _summarize_errors(self, errors):
        """Create concise error summary for prompt enhancement."""
        # Keep it brief to avoid prompt bloat
        if "Missing variable mapping" in str(errors):
            return "Add variable_flow mappings"
        elif "Unknown node" in str(errors):
            return "Use only available nodes"
        else:
            return "Check workflow structure"
```

### Validation with Fixable Error Approach
All validation errors are treated as opportunities for improvement:

```python
class ValidationNode(Node):
    """Validates generated workflows treating all errors as fixable."""

    def exec(self, shared):
        workflow = shared.get("generated_workflow", {})

        # Comprehensive validation
        validation_result = self._validate_workflow(workflow)

        if validation_result["is_valid"]:
            shared["validated_workflow"] = workflow
            return "success"

        # All errors are fixable with proper guidance
        errors = validation_result["errors"]
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
            if "variable_flow" in error or "template variable" in error:
                return "missing_variable_mappings"
            elif "unknown node" in error.lower():
                return "invalid_nodes"
            elif "ir_version" in error or "structure" in error:
                return "invalid_structure"
        return "general_validation_error"

    def _validate_workflow(self, workflow):
        """Perform comprehensive validation."""
        errors = []

        # Check structure
        if "ir_version" not in workflow:
            errors.append("Missing ir_version field")
        if "nodes" not in workflow or not workflow.get("nodes"):
            errors.append("Missing or empty nodes array")

        # Check template variables have mappings
        if "template_inputs" in workflow:
            template_vars = self._extract_template_vars(workflow["template_inputs"])
            variable_flow = workflow.get("variable_flow", {})

            for var in template_vars:
                if var not in variable_flow:
                    errors.append(f"Missing variable mapping for ${var}")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors
        }
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
                    if "Missing variable mapping" in error:
                        issues.append("missing variable mappings")
                    elif "Unknown node" in error:
                        # Extract node name if possible
                        match = re.search(r"Unknown node[: ]+(\w+)", error)
                        if match:
                            issues.append(f"invalid node '{match.group(1)}'")

        return "; ".join(set(issues)) if issues else ""

# Usage in generator node
class WorkflowGeneratorNode(Node, AttemptHistoryMixin):
    def exec(self, shared):
        # Track generation attempt
        self.track_attempt(shared, "generation", "started")

        # Generate workflow...
        response = self.model.prompt(...)

        # Track outcome
        if response:
            self.track_attempt(shared, "generation", "success",
                             {"model": "claude-sonnet-4-20250514"})
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

    def post(self, shared):
        # Save checkpoint after successful execution
        checkpoint = {
            "name": self.checkpoint_name,
            "timestamp": time.time(),
            "shared_state": shared.copy()
        }

        if "checkpoints" not in shared:
            shared["checkpoints"] = []
        shared["checkpoints"].append(checkpoint)

    def exec_fallback(self, shared, exc):
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

    def exec(self, shared):
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
            response = call_llm(f"{shared['base_prompt']}\n{strategy_prompt}")

            # Score the response
            score = self._score_response(response, shared)
            results[strategy_name] = {
                "response": response,
                "score": score
            }

            if score > best_score:
                best_score = score
                best_strategy = strategy_name

        # Store all results for debugging
        shared["strategy_results"] = results
        shared["selected_strategy"] = best_strategy
        shared["llm_response"] = results[best_strategy]["response"]

        return "validate"

    def _score_response(self, response, shared):
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

    def exec(self, shared):
        user_input = shared["user_input"]

        # Smart classification
        if self._looks_like_cli(user_input):
            shared["input_type"] = "cli_syntax"
            return "parse_cli"
        elif self._looks_like_natural(user_input):
            shared["input_type"] = "natural_language"
            return "natural_language"
        else:
            # Ambiguous - need more analysis
            shared["input_type"] = "ambiguous"
            return "ask_user"  # Another path!

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

    def exec(self, shared):
        workflow = shared["generated_workflow"]
        result = self.validator.validate(workflow)

        if result.is_valid:
            return "success"
        elif result.is_fixable:
            # Some errors can be automatically fixed
            shared["validation_errors"] = result.errors
            return "retry_with_fixes"
        else:
            # Fatal errors require different approach
            shared["fatal_errors"] = result.errors
            return "fallback_strategy"
```

## Flow Design Patterns

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
        def exec(self, shared):
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
generator >> validator >> approval
validator - "invalid_structure" >> error_feedback >> generator
validator - "missing_mappings" >> enhance_context >> generator
generator - "max_retries_exceeded" >> fallback_strategy
```

### How Structured Retry Works
1. **First Attempt**: Generate with comprehensive context
2. **Validation Failure**: Specific error identified (e.g., "missing variable mapping for $issue")
3. **Targeted Retry**: Enhanced prompt with error-specific guidance
4. **Bounded Attempts**: Max retries enforced by PocketFlow node configuration

```python
class WorkflowGeneratorNode(Node):
    def __init__(self):
        super().__init__(max_retries=3)  # Bounded retries

    def exec(self, shared):
        # Use attempt count for progressive enhancement
        attempt = shared.get("generation_attempts", 0)

        if attempt > 0:
            # Add specific error feedback to prompt
            error_feedback = shared.get("validation_errors", [])
            prompt = enhance_prompt_with_errors(base_prompt, error_feedback)
        else:
            prompt = base_prompt

        # Generate workflow
        response = self.model.prompt(prompt, schema=WorkflowIR)
        shared["generated_workflow"] = response.json()
        shared["generation_attempts"] = attempt + 1

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

    def exec(self, shared):
        user_input = shared["user_input"]
        context = shared["planning_context"]

        # Build comprehensive prompt
        prompt = self._build_prompt(user_input, context)

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

        shared["generated_workflow"] = workflow_dict
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
        "- Use $variable_name to reference dynamic values",
        "- All variables must have sources in variable_flow",
        "- Common patterns: $issue, $content, $transcript",
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
2. Template variables ($var) for dynamic values
3. Complete variable_flow mappings
4. Natural, descriptive shared store keys

{context}

User Request: {user_input}

Important Rules:
- Generate COMPLETE variable_flow mappings - every $variable must have a source
- Use simple, linear sequences (no complex branching for MVP)
- Each node should have a single, clear purpose
- Template variables enable reuse with different parameters
- Do NOT infer or guess - specify everything explicitly

Output only valid JSON matching this structure:
{{
  "ir_version": "0.1.0",
  "nodes": [...],
  "edges": [...],
  "start_node": "...",
  "template_inputs": {{...}},
  "variable_flow": {{...}}
}}
"""

ERROR_RECOVERY_PROMPT = """The previous workflow generation failed validation:
{error_message}

Original request: {user_input}

Please generate a corrected workflow that addresses the specific error.
Focus on: {error_hint}

Remember to include complete variable_flow mappings for all template variables.

Output only valid JSON.
"""

TEMPLATE_VARIABLE_PROMPT = """Given this workflow, identify all template variables and their sources:

Workflow: {workflow}

For each $variable in template_inputs, specify where its value comes from in variable_flow.

Output as JSON:
{{
  "variable_flow": {{
    "var_name": "source.node.path",
    ...
  }}
}}
"""
```

## Integration Points and Dependencies

### Critical Dependencies
1. **Context Builder** (Task 15/16) - Provides discovery and planning contexts
2. **JSON IR Schema** - Defines valid workflow structure
3. **Node Registry** - Source of available components
4. **LLM Library** - Simon Willison's `llm` with structured outputs

### Integration Requirements
1. **CLI Integration**: Planner receives raw input string from CLI
2. **Workflow Storage**: Saves to `~/.pflow/workflows/` with template variables
3. **Runtime Handoff**: Generates validated JSON IR for execution
4. **Error Reporting**: Clear, actionable error messages

## Testing PocketFlow Flows

### Node Isolation Testing
Test individual nodes without running full flow:

```python
def test_node_in_isolation():
    """Test nodes without running full flow."""
    node = ProgressiveGeneratorNode()
    shared = {"base_prompt": "test prompt"}

    # Simulate retry behavior
    node.cur_retry = 2  # Simulate third attempt
    action = node.exec(shared)

    assert "Simplify the workflow" in shared["llm_response"]
    assert shared["enhancement_level"] == 2
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
       def exec(self, shared):
           shared["counter"] = shared.get("counter", 0) + 1
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

5. **Hardcoded Pattern Libraries**: Don't create fixed workflow patterns
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

   # ✅ CORRECT - LLM provides complete mappings
   # The LLM generates the full variable_flow mapping
   # System only validates, never infers
   ```

7. **Template Enhancement After Generation**: Don't modify LLM output
   ```python
   # ❌ WRONG - Second-guessing the LLM
   if len(prompt) < 50:  # "Too simple"
       workflow["template_inputs"][node_id]["prompt"] = enhance_prompt(prompt)

   # ✅ CORRECT - Trust LLM or retry with feedback
   # If output is insufficient, retry with specific guidance
   ```

8. **Complex Workflow Dependencies**: Don't hardcode task dependencies
   ```python
   # ❌ WRONG - False dependencies
   # "Dependencies": Tasks 15, 16, 18, 19  # Tasks 18, 19 don't exist!

   # ✅ CORRECT - Verify actual dependencies
   # Dependencies: Tasks 14 (structure docs), 15/16 (context builder)
   ```

9. **Mixing Validation with Generation**: Keep concerns separated
   ```python
   # ❌ WRONG - Inference during validation
   def validate_templates(self, workflow):
       if var not in variable_flow:
           # Try to infer source...
           inferred = self._infer_variable_source(var, workflow)

   # ✅ CORRECT - Pure validation
   def validate_templates(self, workflow):
       if var not in variable_flow:
           raise ValidationError(f"Template variable ${var} has no mapping")
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

11. **Code Generation Instead of Workflows**: We're not generating Python
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

13. **Wrong Model Selection**: Don't use GPT models
    ```python
    # ❌ WRONG - Using wrong models
    model = "gpt-4" if complex else "gpt-3.5-turbo"

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

16. **Missing Critical Fields**: Workflows need more than nodes/edges
    ```python
    # ❌ WRONG - Incomplete workflow structure
    workflow = {
        "nodes": [...],
        "edges": [...]
    }

    # ✅ CORRECT - Complete JSON IR structure
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [...],
        "edges": [...],
        "template_inputs": {...},  # Template variables
        "variable_flow": {...}     # Variable mappings
    }
    ```

## Intelligent Parameter Extraction and Interpretation

### Beyond Raw Value Extraction
The planner doesn't just extract raw values - it interprets them based on context:

```python
# Examples of intelligent interpretation:
"analyze churn for last month"
→ Current date: 2024-12-15
→ Interprets to: {"period": "2024-11", "period_type": "month"}

"analyze churn since January"
→ Current date: 2024-12-15
→ Interprets to: {"start_date": "2024-01-01", "end_date": "2024-12-15"}

"fix the bug from yesterday"
→ Current date: 2024-12-15
→ Interprets to: {"date": "2024-12-14"}

"generate Q3 report"
→ Current year: 2024
→ Interprets to: {"start_date": "2024-07-01", "end_date": "2024-09-30"}
```

### Implementation Approach
1. **Context Awareness**: Planner receives current date/time in shared state
2. **LLM Interpretation**: Uses LLM to understand temporal and contextual references
3. **Structured Output**: Returns properly formatted dates and periods
4. **Template Preservation**: Interpreted values are used for execution, not baked into saved workflows

This enables natural language like "last month" while maintaining workflow reusability.

## Template-Driven Workflow Architecture

### Core Insight: Templates Enable Reusability
The fundamental innovation that enables "Plan Once, Run Forever" is that workflows are **templates with variable substitution**, not static execution plans. This is why the same workflow can be reused with different parameters.

```python
# Workflows are templates that get instantiated with different values
workflow_template = {
    "nodes": [...],  # Static structure
    "template_inputs": {  # Dynamic content with $variables
        "claude-code": {
            "prompt": "Fix this issue:\n$issue\n\nGuidelines:\n$coding_standards",
            "dependencies": ["issue", "coding_standards"]
        }
    },
    "variable_flow": {  # LLM generates complete mappings
        "issue": "github-get-issue.outputs.issue_data",
        "coding_standards": "read-file.outputs.content"
    }
}
```

### Critical Design Decision: LLM Generates Complete Mappings
The LLM is responsible for generating **complete variable mappings**. There is NO inference or hardcoded patterns - the LLM explicitly specifies:
1. Template variables in prompts/parameters
2. Complete `variable_flow` mappings showing where each variable comes from
3. All data dependencies between nodes

This approach ensures:
- No brittle hardcoded logic
- Full flexibility for any workflow pattern
- Clear data flow that can be validated
- True generalization across different domains

### Template Variable Resolution Order
While the LLM generates the mappings, the system must validate and determine the correct resolution order:

```python
def calculate_resolution_order(workflow: dict) -> list[str]:
    """Calculate the order in which template variables can be resolved.

    This is pure validation - the LLM has already specified all mappings.
    We just need to ensure they can be resolved in a valid order.
    """
    # Extract dependencies from LLM-generated template_inputs
    dependencies = {}
    for node_id, templates in workflow.get("template_inputs", {}).items():
        deps = set()
        for template in templates.values():
            # Extract $variables from template strings
            variables = re.findall(r'\$\{?(\w+)\}?', str(template))
            deps.update(variables)
        dependencies[node_id] = deps

    # Topological sort to find valid execution order
    # This validates that the LLM's mappings are resolvable
    resolved = []
    available_vars = {"stdin"} if workflow.get("expects_stdin") else set()

    # ... topological sort algorithm ...

    # If we can't resolve all dependencies, the LLM's mappings are invalid
    if unresolved_nodes:
        raise ValidationError(f"Cannot resolve template variables for: {unresolved_nodes}")

    return resolved
```

### Example: LLM-Generated Complete Workflow
When user says "fix github issue 123", the LLM generates:

```json
{
  "nodes": [
    {"id": "get-issue", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
    {"id": "analyze", "type": "claude-code", "params": {}},
    {"id": "commit", "type": "git-commit", "params": {}},
    {"id": "push", "type": "git-push", "params": {}},
    {"id": "create-pr", "type": "github-create-pr", "params": {}}
  ],
  "template_inputs": {
    "analyze": {
      "prompt": "<instructions>Fix the issue described below</instructions>\n\n$issue_data"
    },
    "commit": {
      "message": "$commit_message"
    },
    "create-pr": {
      "title": "Fix: $issue_title",
      "body": "$code_report"
    }
  },
  "variable_flow": {
    "issue_number": "123",  // Initial parameter
    "issue_data": "get-issue.outputs.issue_data",
    "issue_title": "get-issue.outputs.title",
    "commit_message": "analyze.outputs.suggested_commit_message",
    "code_report": "analyze.outputs.report"
  }
}
```

The LLM has specified EVERYTHING - no inference needed.

## Risk Mitigation Strategies

### Hybrid Architecture Risk
**Risk**: Confusion about why only planner uses PocketFlow
**Mitigation**:
- Clear documentation in module docstring
- Explicit comments explaining the architectural decision
- Consistent pattern within the planner module

### Complex State Management
**Risk**: Difficult to track state across retries
**Mitigation**:
- Use PocketFlow's shared dict for retry context
- Clear logging of each attempt
- Preserve successful partial results
- Implement checkpoint pattern for recovery

### LLM Non-Determinism
**Risk**: Different outputs for same input
**Mitigation**:
- Structured output with Pydantic schemas
- Three-tier validation pipeline
- Clear success criteria (≥95% accuracy target)
- Progressive enhancement to guide LLM

### Template Variable Validation
**Risk**: LLM generates invalid variable mappings
**Mitigation**:
- Validate all template variables have sources
- Check resolution order is achievable
- Provide clear error messages for missing mappings
- Include examples in prompts showing complete mappings

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

## Testing Workflow Generation

### Core Testing Strategy
Testing the workflow generation focuses on validating that the LLM produces complete, valid workflows with proper template variables and mappings.

```python
def test_workflow_generation_completeness():
    """Test that LLM generates complete workflows with all mappings."""
    # Mock LLM to return a known good workflow
    mock_llm = MockLLM(returns={
        "nodes": [...],
        "template_inputs": {...},
        "variable_flow": {...}  # Must be complete!
    })

    planner = create_planner_flow()
    result = planner.run({"user_input": "fix github issue 123"})

    # Verify completeness
    assert "template_inputs" in result["final_workflow"]
    assert "variable_flow" in result["final_workflow"]

    # Verify ALL template variables have mappings
    template_vars = extract_template_variables(result["final_workflow"]["template_inputs"])
    variable_mappings = result["final_workflow"]["variable_flow"].keys()

    unmapped = template_vars - set(variable_mappings)
    assert not unmapped, f"Template variables without mappings: {unmapped}"
```

### Template Variable Validation Testing
```python
def test_template_validation_catches_missing_mappings():
    """Test that validation catches incomplete variable mappings."""
    workflow = {
        "template_inputs": {
            "llm": {"prompt": "Analyze $content and $metadata"}
        },
        "variable_flow": {
            "content": "read-file.outputs.content"
            # Missing metadata mapping!
        }
    }

    validator = TemplateValidator()
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

        # Verify template variables exist and have mappings
        for var in case["expected_template_vars"]:
            assert var in workflow["variable_flow"], f"Missing mapping for {var}"
```

### Resolution Order Testing
```python
def test_resolution_order_calculation():
    """Test that resolution order correctly handles dependencies."""
    workflow = {
        "nodes": [
            {"id": "n1", "type": "github-get-issue"},
            {"id": "n2", "type": "claude-code"},
            {"id": "n3", "type": "llm"}
        ],
        "template_inputs": {
            "n2": {"prompt": "$issue"},  # Depends on n1
            "n3": {"prompt": "Summarize: $code_report"}  # Depends on n2
        },
        "variable_flow": {
            "issue": "n1.outputs.issue_data",
            "code_report": "n2.outputs.report"
        }
    }

    order = calculate_resolution_order(workflow)

    # n1 must come before n2, n2 must come before n3
    assert order.index("n1") < order.index("n2")
    assert order.index("n2") < order.index("n3")
```

## Two-Phase Discovery: Browsing vs Selecting

### Critical Distinction: Discovery is Browsing, Not Selecting
The discovery phase is fundamentally about **browsing** for potentially relevant components, not selecting a single match:

**Browsing Characteristics**:
- Over-inclusive is better than missing components
- Returns MULTIPLE potentially relevant items
- Reduces cognitive load by filtering noise
- Like "show me everything related to GitHub operations"

**Why This Matters**:
1. **Workflow Reuse**: A workflow might be found among browsed components
2. **Node Composition**: Multiple nodes might be needed for new workflows
3. **Flexibility**: The planner can make final decisions with full context

### Implementation of Two-Phase Approach

```python
class ComponentDiscoveryNode(Node):
    """Browse available components using two-phase approach."""

    def _browse_components(self, user_input: str, discovery_context: str) -> dict:
        """Phase 1: Browse with lightweight context."""
        prompt = f"""
        User wants to: {user_input}

        Available components:
        {discovery_context}

        Browse and select ALL components that might be relevant.
        Be over-inclusive - it's better to include too many than miss important ones.

        Return lists of:
        - node_ids: Potentially useful nodes
        - workflow_names: Potentially useful workflows
        """

        response = self.llm.prompt(prompt, schema=ComponentSelection)
        return response.json()

    def _exact_workflow_match(self, browsed_workflows: list, user_input: str) -> bool:
        """After browsing, check if any workflow exactly matches intent."""
        if not browsed_workflows:
            return False

        # Now with detailed context, can make precise match determination
        for workflow in browsed_workflows:
            if self._matches_intent(workflow, user_input):
                return True
        return False
```

This approach:
- **Browsing first**: Cast a wide net to find all potentially relevant components
- **Detailed analysis second**: With full context, determine exact matches
- **No ranked lists for users**: All selection happens internally
- **Semantic understanding**: "analyze costs" finds "aws-cost-analyzer" through browsing

## Success Metrics and Targets

### Core Performance Targets
From the unified understanding of requirements:

1. **≥95% Success Rate**: Natural language → valid workflow generation
2. **≥90% Approval Rate**: Users approve generated workflows without modification
3. **Fast Discovery**: Near-instant workflow matching (LLM call + parsing)
4. **Clear Approval**: Users understand exactly what will execute

### Measuring Success
```python
# Track in shared state for monitoring
shared["metrics"] = {
    "generation_success": True,  # Did we produce valid IR?
    "user_approved": True,       # Did user approve without changes?
    "discovery_time_ms": 150,    # How long to find/generate?
    "total_attempts": 1,         # How many generation attempts?
}
```

## Open Questions and Decisions Needed

1. ~~**Directory Structure**: Which path to use?~~ **RESOLVED**: Use `src/pflow/planning/`
2. ~~**Approval Node Placement**: Is approval part of the planner flow or separate?~~ **RESOLVED**: Part of the meta-workflow as ConfirmationNode
3. **Error Feedback Node**: Should this be a separate node or part of validator?
4. **Retry Count Access**: Should we use `cur_retry` attribute or track in shared?
5. **Checkpoint Frequency**: After each successful node or only at key points?
6. **Template Variable Format**: Should we support both `$var` and `${var}` syntax?
7. **Workflow Storage Trigger**: Does the planner save new workflows automatically or prompt user?

## Next Steps

With the directory structure resolved and patterns understood, the implementation should:
1. Create the planner module at `src/pflow/planning/` with PocketFlow patterns
2. Implement core nodes using the advanced patterns:
   - DiscoveryNode with state accumulation
   - GeneratorNode with progressive enhancement
   - ValidatorNode with multi-validator convergence
   - ApprovalNode (placement TBD)
3. Design flow with retry loops and escape hatches
4. Add comprehensive testing for both nodes and flows
5. Integrate with existing context builder and CLI

---

*Note: This document will be updated as additional research files are analyzed and integrated.*
