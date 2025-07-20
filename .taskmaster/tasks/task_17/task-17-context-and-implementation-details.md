# Task 17: Natural Language Planner - Context and Implementation Details

This document synthesizes key insights from research files to provide actionable implementation guidance for the Natural Language Planner System. It complements the ambiguities document by providing concrete architectural decisions and implementation patterns.

## Critical Insight: The Meta-Workflow Architecture

### The Planner IS a Workflow That Creates and Prepares Workflows for Execution

The Natural Language Planner is fundamentally a **meta-workflow** - a PocketFlow workflow that:
1. **Discovers or creates** workflows based on user intent
2. **Extracts parameters** from natural language (e.g., "1234" from "fix issue 1234")
3. **Returns workflow with template variables** in params (e.g., `{"issue": "$issue_number"}`)
4. **Returns parameter values** to the CLI for runtime substitution

The planner orchestrates the planning phase, then hands off to the CLI for execution. The runtime handles all template resolution transparently via proxy pattern.

### MVP vs Future Architecture

**MVP (All planning through planner, execution in CLI):**
```
User Input: "fix github issue 1234"
    ↓
[Planner Meta-Workflow]
    ├─> Discovery: Does "fix-issue" workflow exist?
    ├─> Parameter Extraction: {"issue_number": "1234"}
    ├─> Workflow contains: {"params": {"issue": "$issue_number"}}
    └─> Returns: (workflow_ir, metadata, parameter_values)
    ↓
[CLI Execution]
    ├─> Shows approval: "Will run fix-issue with issue=1234"
    ├─> Saves workflow: ~/.pflow/workflows/fix-issue.json
    └─> Executes: Runs workflow with parameter substitution
```

**v2.0+ (Direct execution for known workflows):**
```
pflow fix-issue --issue=1234  # Bypasses planner entirely
```

### Key Architectural Implications

1. **The planner returns structured results** - IR + metadata + parameter values
2. **Template variables in params** - Simple `$variable` syntax in node params
3. **Clean separation of concerns** - Planner plans, runtime resolves templates
4. **Every MVP execution is meta** - Even reusing existing workflows goes through the full planner
5. **Branching is essential** - Found vs create paths within the same workflow
6. **Intent over parsing** - The goal is to understand user intent, not just parse words

## Architectural Decision: PocketFlow for Planner Orchestration

### Core Decision
The Natural Language Planner is the **ONLY** component in the entire pflow system that uses PocketFlow for internal orchestration. This decision is based on the planner's unique complexity requirements.

### The Meta-Layer Concept: Using PocketFlow to Create PocketFlow Workflows

The planner embodies a powerful **meta architecture** - it is a PocketFlow workflow that creates and executes other PocketFlow workflows. This creates an elegant philosophical alignment:

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

class ParameterPreparationNode(Node):
    """Prepares parameters for runtime substitution"""
    def exec(self, shared):
        params = shared["extracted_params"]

        # Simply pass through the extracted parameters
        # Runtime proxy will handle template substitution transparently
        shared["parameter_values"] = params
        return "prepare_result"

class GeneratorNode(Node):
    """Generates new workflow if none found"""
    def exec(self, shared):
        # Generate complete workflow with template variables
        workflow = self._generate_workflow(shared["user_input"])
        shared["generated_workflow"] = workflow
        return "extract_params"

class ResultPreparationNode(Node):
    """Prepares the final results to return to the CLI"""
    def exec(self, shared):
        workflow_ir = shared.get("found_workflow") or shared.get("generated_workflow")

        # Prepare what the planner returns to CLI
        shared["planner_output"] = {
            "workflow_ir": workflow_ir,
            "workflow_metadata": {
                "suggested_name": shared.get("workflow_name", "custom-workflow"),
                "description": shared.get("workflow_description", "Generated workflow"),
                "inputs": shared.get("workflow_inputs", []),
                "outputs": shared.get("workflow_outputs", [])
            },
            "parameter_values": shared["parameter_values"]
        }

        return "complete"

# The complete meta-workflow
def create_planner_flow():
    flow = Flow("planner_meta_workflow")

    # All nodes
    discovery = WorkflowDiscoveryNode()
    param_extract = ParameterExtractionNode()
    param_prep = ParameterPreparationNode()
    generator = GeneratorNode()
    validator = ValidatorNode()
    result_prep = ResultPreparationNode()

    # Main flow with branching
    flow.add_edge(discovery, "found", param_extract)
    flow.add_edge(discovery, "not_found", generator)
    flow.add_edge(generator, "success", validator)
    flow.add_edge(validator, "valid", param_extract)
    flow.add_edge(param_extract, "prepare_params", param_prep)
    flow.add_edge(param_prep, "prepare_result", result_prep)

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

## What the Planner Returns to CLI

### Structure of Planner Output

The planner returns a structured result that contains everything the CLI needs for execution:

```python
{
    "workflow_ir": {
        # Complete IR with template variables and proxy mappings
        "ir_version": "0.1.0",
        "nodes": [...],
        "edges": [...],
        "mappings": {...}  # Proxy mappings for shared store
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
            "\nEnsure all template variables ($var) are used correctly in params.",  # Level 1
            "\nSimplify: use fewer nodes and ensure $variables match shared store keys.",  # Level 2
            "\nUse basic nodes only. Template variables should match data flow naturally."  # Level 3
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
            if "template variable" in error:
                return "template_variable_issue"
            elif "unknown node" in error.lower():
                return "invalid_nodes"
            elif "ir_version" in error or "structure" in error:
                return "invalid_structure"
        return "general_validation_error"

    def _validate_workflow(self, workflow):
        """Perform comprehensive validation with prompt-ready error messages."""
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
                    # Extract template variables
                    template_vars = re.findall(r'\$\{?(\w+)\}?', param_value)
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
2. **Validation Failure**: Specific error identified (e.g., "template variable $issue not found in params")
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
2. Template variables ($var) in params for dynamic values
3. Natural, descriptive shared store keys
4. Optional proxy mappings for complex data routing

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
    {{"id": "n1", "type": "node-type", "params": {{"key": "$variable_or_value"}}}}
  ],
  "edges": [...],
  "start_node": "...",
  "mappings": {{...}}  // Optional proxy mappings if needed
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

    # Run planner meta-workflow
    planner.run(shared)

    # Extract results
    planner_output = shared.get("planner_output")
    if planner_output:
        handle_planner_output(planner_output)
```

#### Planner Node Integration Examples

```python
# In src/pflow/planning/nodes.py

class DiscoveryNode(Node):
    """Uses context builder to find nodes and workflows."""
    def exec(self, shared, prep_res):
        from pflow.planning.context_builder import build_discovery_context

        # Get lightweight discovery context
        discovery_context = build_discovery_context()
        shared["discovery_context"] = discovery_context

        # Use LLM to find relevant components
        # ... LLM logic ...
        return "found" or "not_found"

class GeneratorNode(Node):
    """Generates workflow with registry validation."""
    def exec(self, shared, prep_res):
        from pflow.planning.context_builder import build_planning_context
        from pflow.registry import Registry

        # Get detailed planning context for selected nodes
        selected_nodes = shared.get("selected_nodes", [])
        planning_context = build_planning_context(selected_nodes, [])

        # Generate workflow using LLM
        # ... LLM generation ...

        # Validate node types exist
        registry = Registry()
        for node in generated_ir["nodes"]:
            if node["type"] not in registry.get_all_node_types():
                raise ValueError(f"Unknown node type: {node['type']}")

        return "validate"

class ValidationNode(Node):
    """Uses existing IR validation."""
    def exec(self, shared, prep_res):
        from pflow.core import validate_ir

        try:
            validate_ir(shared["generated_ir"])
            return "valid"
        except ValidationError as e:
            shared["validation_errors"] = str(e)
            return "invalid"
```

#### Parameter Substitution in CLI
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
    # ❌ WRONG - Planner executing user workflows
    class WorkflowExecutionNode(Node):
        def exec(self, shared):
            flow = compile_ir_to_flow(workflow_ir)
            result = flow.run(...)  # Planner running user workflow

    # ✅ CORRECT - Planner returns results for CLI execution
    class ResultPreparationNode(Node):
        def exec(self, shared):
            shared["planner_output"] = {
                "workflow_ir": ...,
                "parameter_values": ...
            }
            # CLI handles execution
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

## Parameter Extraction and Interpretation

### Parameters Need Interpretation, Not Just Extraction
The planner must handle various types of natural language references that require interpretation:

- **Temporal references**: "yesterday", "last month", "Q3"
- **Contextual references**: "main branch", "current directory", "this repo"
- **Relative references**: "the latest", "previous version", "next sprint"

### Key Principles
1. **LLM handles interpretation**: The LLM understands context and converts references to concrete values
2. **Context provided**: Planner receives necessary context (current date, working directory, etc.)
3. **Values for execution only**: Interpreted values go in `parameter_values`, not in the saved workflow
4. **Templates remain generic**: Workflows always use `$variables` to maintain reusability

### Example Flow
```
User: "fix the bug from yesterday"
  ↓
Planner extracts: "yesterday" needs interpretation
  ↓
LLM interprets: Based on current date, "yesterday" → specific date
  ↓
Returns: parameter_values: {"date": "<interpreted-date>"}
  ↓
Workflow saved with: "$date" (template variable)
```

This separation ensures workflows remain reusable while handling natural language elegantly.

## Template-Driven Workflow Architecture

### Core Insight: Templates Enable Reusability
The fundamental innovation that enables "Plan Once, Run Forever" is that workflows use **template variables in params**, allowing the same workflow to be reused with different parameters.

```python
# Workflows use $variables directly in node params
workflow = {
    "ir_version": "0.1.0",
    "nodes": [
        # Static structure with dynamic values
        {"id": "get", "type": "github-get-issue",
         "params": {"issue": "$issue_number"}},  # CLI parameter

        {"id": "fix", "type": "claude-code",
         "params": {"prompt": "Fix issue: $issue_data\nStandards: $coding_standards"}},
         # $issue_data from shared store, $coding_standards from file read

        {"id": "commit", "type": "git-commit",
         "params": {"message": "$commit_message"}}  # From previous node
    ],
    "edges": [
        {"from": "get", "to": "fix"},
        {"from": "fix", "to": "commit"}
    ]
}
```

### Simple Design: Runtime Proxy Resolution
The system uses a **runtime proxy pattern** for template resolution:
1. **CLI parameters**: `$issue_number` → resolved from `--issue_number=1234`
2. **Shared store values**: `$issue_data` → resolved from `shared["issue_data"]`
3. **Transparent to nodes**: Nodes receive already-resolved values

This approach ensures:
- No complex mapping structures needed
- Simple naming convention ($var → shared["var"])
- Clear separation of concerns
- Easy to understand and debug

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
    mappings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

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

    def exec(self, shared):
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

    def exec_fallback(self, shared, exc):
        """Handle final failure after all retries."""
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
def validate_template_variables(workflow: dict, parameter_values: dict) -> None:
    """Validate that all template variables in the workflow can be resolved.

    This ensures that:
    1. CLI parameters have values provided
    2. Shared store references will be available when needed
    """
    # Extract all template variables from node params
    template_vars = set()
    for node in workflow.get("nodes", []):
        for param_value in node.get("params", {}).values():
            if isinstance(param_value, str):
                # Extract $variables from strings
                variables = re.findall(r'\$\{?(\w+)\}?', param_value)
                template_vars.update(variables)

    # Check CLI parameters are provided
    cli_params = {k for k in template_vars if k in parameter_values}
    missing_cli = cli_params - set(parameter_values.keys())
    if missing_cli:
        raise ValidationError(f"Missing CLI parameters: {missing_cli}")

    # Remaining vars should be resolvable from shared store
    # Runtime proxy will handle the actual resolution
```

### Example: LLM-Generated Complete Workflow
When user says "fix github issue 123", the LLM generates:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "get-issue", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
    {"id": "analyze", "type": "claude-code", "params": {
      "prompt": "<instructions>Fix the issue described below</instructions>\n\n$issue_data"
    }},
    {"id": "commit", "type": "git-commit", "params": {"message": "$commit_message"}},
    {"id": "push", "type": "git-push", "params": {}},
    {"id": "create-pr", "type": "github-create-pr", "params": {
      "title": "Fix: $issue_title",
      "body": "$code_report"
    }}
  ],
  "edges": [
    {"from": "get-issue", "to": "analyze"},
    {"from": "analyze", "to": "commit"},
    {"from": "commit", "to": "push"},
    {"from": "push", "to": "create-pr"}
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

Template variables in params will be resolved by runtime proxy:
- `$issue_number` → "123" (from CLI parameters)
- `$issue_data`, `$commit_message`, etc. → from shared store during execution

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
**Risk**: LLM uses incorrect template variables
**Mitigation**:
- Validate template variables match expected patterns
- Ensure CLI parameters are properly named
- Check that shared store keys will exist when needed
- Include examples in prompts showing correct $variable usage

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

1. **Orchestrates Multiple Complex Operations**: Discovery → Generation → Validation → Parameter Mapping → Execution
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

## Concrete Integration Examples

### Accessing the Registry
```python
from pflow.registry import Registry

# In any planner node
class WorkflowDiscoveryNode(Node):
    def exec(self, shared):
        from pflow.planning.context_builder import build_discovery_context

        # Use context builder for formatted discovery
        discovery_context = build_discovery_context()
        shared["discovery_context"] = discovery_context

        # Context builder provides:
        # - Formatted node descriptions
        # - Available workflows from ~/.pflow/workflows/
        # - Both as LLM-ready markdown
```

### Using IR Validation
```python
from pflow.core import validate_ir, ValidationError

class ValidatorNode(Node):
    def exec(self, shared):
        workflow = shared["generated_workflow"]

        try:
            validate_ir(workflow)
            return "valid"
        except ValidationError as e:
            # e.path: "nodes[0].type"
            # e.message: "Unknown node type 'read-files'"
            # e.suggestion: "Did you mean 'read-file'?"
            shared["validation_error"] = {
                "path": e.path,
                "message": e.message,
                "suggestion": e.suggestion
            }
            return "invalid"
```

### CLI Integration Point
```python
# The CLI will invoke the planner like this:
from pflow.planning import create_planner_flow

# In cli/main.py
planner_flow = create_planner_flow()
result = planner_flow.run({
    "user_input": ctx.obj["raw_input"],
    "input_source": ctx.obj["input_source"],
    "stdin_data": ctx.obj.get("stdin_data")
})

# Result contains the executed workflow output
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
# → Returns "found"

# 2. Parameter Extraction
# → ParameterExtractionNode executes
shared["extracted_params"] = {"issue": "123"}
# → Returns "map_params"

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
    "parameter_values": {"issue": "123"}
}
# → Returns "complete"

# 5. CLI Takes Over
# → Planner returns shared["planner_output"] to CLI
# → CLI shows approval: "Will run 'fix-issue' with issue=123"
# → User approves
# → CLI saves workflow to ~/.pflow/workflows/fix-issue.json
# → CLI executes with parameter substitution

# CLI execution results (not in planner's shared state)
execution_result = {
    "status": "success",
    "outputs": {"pr_url": "https://github.com/..."}
}
```

## Critical Success Factors

### What Makes Implementation Succeed

1. **Understand the Meta-Workflow Nature**
   - The planner orchestrates discovery, generation, and parameter mapping
   - Returns structured results for CLI to execute

2. **Template Variables are Sacred**
   - NEVER hardcode extracted values
   - Always preserve reusability

3. **Use Existing Infrastructure**
   - Don't reinvent validation, compilation, or registry access
   - Build on the solid foundation

4. **Test the Flow, Not Just Nodes**
   - Individual node testing isn't enough
   - Test complete paths through the meta-workflow

## Next Steps

With the directory structure resolved and patterns understood, the implementation should:
1. Create the planner module at `src/pflow/planning/` with PocketFlow patterns
2. Implement core nodes using the advanced patterns:
   - WorkflowDiscoveryNode with LLM semantic matching and integration with the context builder
   - GeneratorNode with progressive enhancement
   - ValidatorNode using existing validate_ir()
   - ParameterExtractionNode for NL → params
   - ParameterMappingNode for params → template vars
   - ResultPreparationNode to format output for CLI
3. Design flow with proper branching (found vs generate paths)
4. Add comprehensive testing for complete execution paths
5. Integrate with CLI using the exact pattern shown above

---

*Note: This document will be updated as additional research files are analyzed and integrated.*
