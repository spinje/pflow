# Advanced PocketFlow Orchestration Patterns for Natural Language Planner

## Overview

Based on deep analysis of PocketFlow's 100-line implementation, this document provides advanced patterns specifically suited for Task 17's complex orchestration needs. These patterns go beyond basic node chaining to handle the sophisticated control flow required for reliable LLM-based planning.

## Core PocketFlow Insights

### Understanding PocketFlow's Execution Model

PocketFlow's elegance comes from its simple execution loop:
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

This means:
1. **Nodes are stateless** - All state lives in `shared`
2. **Actions are strings** - Not booleans or complex objects
3. **Edges are tuples** - `(from_node, action) -> to_node`
4. **Retries are per-node** - Not per-flow

## Advanced Patterns for Task 17

### 1. Progressive Enhancement Pattern

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

### 2. Multi-Validator Convergence Pattern

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

    def _validate_json(self, response, shared):
        try:
            workflow = json.loads(response)
            shared["parsed_workflow"] = workflow
            return True, []
        except json.JSONDecodeError as e:
            return False, [str(e)]
```

### 3. State Accumulation Pattern

PocketFlow's shared store enables powerful state accumulation:

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
                # Extract and remember the unknown node
                match = re.search(r"Unknown node: (\w+)", error)
                if match:
                    shared["learned_constraints"].add(
                        f"Don't use '{match.group(1)}' - it doesn't exist"
                    )

        # Use accumulated knowledge
        return "retry_with_learning"
```

### 4. Dynamic Flow Composition Pattern

PocketFlow allows runtime flow modification through edge manipulation:

```python
class DynamicRouterNode(Node):
    """Routes dynamically based on content analysis."""

    def exec(self, shared):
        user_input = shared["user_input"]

        # Analyze complexity
        complexity_indicators = {
            "simple": ["read", "write", "copy", "list"],
            "moderate": ["analyze", "process", "transform"],
            "complex": ["fix", "debug", "optimize", "refactor"]
        }

        complexity = "simple"
        for level, keywords in complexity_indicators.items():
            if any(keyword in user_input.lower() for keyword in keywords):
                complexity = level

        shared["complexity"] = complexity

        # Dynamic routing based on complexity
        return f"generate_{complexity}"
```

### 5. Checkpoint and Recovery Pattern

Leverage PocketFlow's post() method for checkpointing:

```python
class CheckpointNode(Node):
    """Creates recovery checkpoints."""

    def __init__(self, checkpoint_name):
        super().__init__()
        self.checkpoint_name = checkpoint_name

    def exec(self, shared):
        # Normal execution
        return "next"

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
        # On failure, can restore from checkpoint
        if "checkpoints" in shared and shared["checkpoints"]:
            last_checkpoint = shared["checkpoints"][-1]
            # Restore specific keys
            for key in ["generated_workflow", "validation_state"]:
                if key in last_checkpoint["shared_state"]:
                    shared[key] = last_checkpoint["shared_state"][key]

        return "recovery"
```

### 6. Parallel Attempt Pattern (Simulation)

While PocketFlow is synchronous, we can simulate parallel strategies:

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
```

## Flow Design Patterns

### 1. Diamond Pattern with Convergence

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

### 2. Retry Loop with Escape Hatch

```python
def create_retry_loop_flow():
    """Retry loop with maximum attempts."""
    flow = Flow("retry_planner")

    # Nodes with state tracking
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

## Testing PocketFlow Flows

### 1. Node Isolation Testing

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

### 2. Flow Path Testing

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

1. **Node Granularity**: Keep nodes focused - PocketFlow's overhead is minimal per node
2. **Shared Store Size**: While dictionary access is O(1), large objects in shared can impact memory
3. **Retry Strategy**: Use exponential backoff in exec() not just retry count
4. **Action String Optimization**: Keep action strings short - they're used as dict keys

## Anti-Patterns to Avoid

1. **Stateful Nodes**: Don't store state in node instances - use shared store
2. **Complex Actions**: Actions should be simple strings, not encoded data
3. **Deep Nesting**: Avoid flows within flows - flatten when possible
4. **Blocking Operations**: PocketFlow is synchronous - long operations block the flow

This document provides PocketFlow-specific patterns that leverage the framework's unique characteristics for building a robust natural language planner.
