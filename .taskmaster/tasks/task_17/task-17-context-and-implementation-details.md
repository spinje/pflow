# Task 17: Natural Language Planner - Context and Implementation Details

This document synthesizes key insights from research files to provide actionable implementation guidance for the Natural Language Planner System. It complements the ambiguities document by providing concrete architectural decisions and implementation patterns.

## Architectural Decision: PocketFlow for Planner Orchestration

### Core Decision
The Natural Language Planner is the **ONLY** component in the entire pflow system that uses PocketFlow for internal orchestration. This decision is based on the planner's unique complexity requirements.

### Justification for PocketFlow Usage
The planner genuinely benefits from PocketFlow's orchestration capabilities due to:
- **Complex retry strategies** with multiple approaches
- **Self-correcting loops** for LLM validation and error recovery
- **Branching logic** based on LLM responses and validation outcomes
- **Progressive enhancement** of generated workflows
- **Multiple fallback paths** for different error types
- **State accumulation** across retry attempts

### Implementation Pattern
```python
# The planner uses PocketFlow internally
class DiscoveryNode(Node):
    """Uses context builder to find available components"""

class GeneratorNode(Node):
    """Generates workflow using LLM with retries"""

class ValidatorNode(Node):
    """Three-tier validation with error feedback"""

class ApprovalNode(Node):
    """Shows CLI syntax for user approval"""

# Orchestrated as a flow
discovery >> generator >> validator >> approval
generator - "malformed_json" >> generator  # Self-retry
validator - "unknown_nodes" >> error_feedback >> generator
```

### What This Means for Implementation
1. **All other components use traditional Python** - No PocketFlow elsewhere
2. **Planner gets retry/fallback benefits** - Built-in fault tolerance
3. **Clear architectural boundary** - Only planner uses flow patterns internally

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
For LLM planning, each retry should enhance the prompt rather than repeat it:

```python
class ProgressiveGeneratorNode(Node):
    """Generator that enhances prompt on each retry."""

    def __init__(self):
        super().__init__(max_retries=4)
        self.enhancement_levels = [
            "",  # Level 0: Original prompt
            "\nPlease use only nodes from the registry above.",  # Level 1
            "\nSimplify the workflow to basic input->process->output.",  # Level 2
            "\nUse 'claude-code' node for any complex operations.",  # Level 3
        ]

    def exec(self, shared):
        # Use retry count to determine enhancement level
        level = getattr(self, 'cur_retry', 0)
        enhancement = self.enhancement_levels[min(level, len(self.enhancement_levels)-1)]

        prompt = shared["base_prompt"] + enhancement
        response = call_llm(prompt)

        shared["llm_response"] = response
        shared["enhancement_level"] = level

        # Always go to validation
        return "validate"

    def exec_fallback(self, shared, exc):
        # On final failure, go to fallback strategy
        shared["generation_error"] = str(exc)
        return "fallback"
```

### Multi-Validator Convergence Pattern
Multiple validation paths that converge on success:

```python
class MultiValidatorNode(Node):
    """Validates through multiple strategies."""

    def exec(self, shared):
        response = shared.get("llm_response", "")

        # Try multiple validation strategies
        validators = [
            ("json", self._validate_json),
            ("structure", self._validate_structure),
            ("semantics", self._validate_semantics)
        ]

        for val_name, validator in validators:
            is_valid, errors = validator(response, shared)
            shared[f"{val_name}_valid"] = is_valid
            shared[f"{val_name}_errors"] = errors

            if not is_valid:
                # Route to specific recovery
                return f"fix_{val_name}"

        # All validations passed
        return "success"
```

### State Accumulation Pattern
Learning from errors across attempts:

```python
class StateAccumulatorNode(Node):
    """Accumulates learning across attempts."""

    def prep(self, shared):
        # Initialize accumulator on first run
        if "attempt_history" not in shared:
            shared["attempt_history"] = []
        if "learned_constraints" not in shared:
            shared["learned_constraints"] = set()

    def exec(self, shared):
        # Record this attempt
        attempt = {
            "timestamp": time.time(),
            "input": shared.get("current_prompt"),
            "output": shared.get("llm_response"),
            "errors": shared.get("validation_errors", [])
        }
        shared["attempt_history"].append(attempt)

        # Learn from errors
        for error in attempt["errors"]:
            if "Unknown node" in error:
                match = re.search(r"Unknown node: (\w+)", error)
                if match:
                    shared["learned_constraints"].add(
                        f"Don't use '{match.group(1)}' - it doesn't exist"
                    )

        return "retry_with_learning"
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

## Open Questions and Decisions Needed

1. ~~**Directory Structure**: Which path to use?~~ **RESOLVED**: Use `src/pflow/planning/`
2. **Approval Node Placement**: Is approval part of the planner flow or separate?
3. **Error Feedback Node**: Should this be a separate node or part of validator?
4. **Retry Count Access**: Should we use `cur_retry` attribute or track in shared?
5. **Checkpoint Frequency**: After each successful node or only at key points?

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
