# Integration Points and Testing Strategy for Natural Language Planner

## Overview

Task 17 (Natural Language Planner) is the central orchestration component that ties together multiple subsystems. This document clarifies integration points with related tasks and provides a comprehensive testing strategy for the PocketFlow-based implementation.

## Integration Architecture

```
User Input → Task 17 (Planner) → JSON IR Output
              ↓         ↑         ↓
          Task 16    Task 18   Task 19
         (Context)  (Prompts)  (Parser)
```

## Detailed Integration Points

### 1. Task 16: Planning Context Builder

**Purpose**: Formats registry metadata into LLM-consumable context

**Integration Interface**:
```python
# Task 16 provides this function
def build_planning_context(registry: Dict[str, Any]) -> str:
    """Convert registry to formatted context for LLM."""
    # Returns markdown-formatted string with node descriptions
    return formatted_context

# Task 17 uses it in ContextBuilderNode
class ContextBuilderNode(Node):
    def exec(self, shared):
        # Get registry from shared store
        registry = shared.get("registry", {})

        # Call Task 16's function
        context = build_planning_context(registry)

        # Store for next node
        shared["llm_context"] = context
        return "generate"
```

**Key Considerations**:
- Task 16 must be implemented as a standalone module
- Context format must be stable (changes break prompts)
- Performance: Context building should be <50ms
- Size limits: Keep context under 8k tokens

### 2. Task 18: Planner Prompt Templates

**Purpose**: Provides versioned prompt templates for different scenarios

**Integration Interface**:
```python
# Task 18 provides this module
class PlannerPrompts:
    # Base templates
    NATURAL_LANGUAGE_TEMPLATE = """
    Request: {user_request}
    Available Nodes:
    {node_context}

    Generate a workflow that...
    """

    CLI_SYNTAX_TEMPLATE = """
    CLI Command: {cli_input}
    Available Nodes:
    {node_context}

    Parse this CLI-style workflow...
    """

    ERROR_RECOVERY_TEMPLATES = {
        "missing_node": "The node '{node}' doesn't exist. Available nodes: {alternatives}",
        "invalid_json": "Please output only valid JSON, no explanations.",
        "too_complex": "Simplify to a linear flow: input → process → output"
    }

    @staticmethod
    def get_prompt(template_name: str, **kwargs) -> str:
        """Get formatted prompt with variables filled."""
        template = getattr(PlannerPrompts, template_name)
        return template.format(**kwargs)
```

**Integration in Task 17**:
```python
class WorkflowGeneratorNode(Node):
    def exec(self, shared):
        # Determine template based on input type
        template_name = ("NATURAL_LANGUAGE_TEMPLATE"
                        if shared["input_type"] == "natural"
                        else "CLI_SYNTAX_TEMPLATE")

        # Get prompt from Task 18
        prompt = PlannerPrompts.get_prompt(
            template_name,
            user_request=shared["user_input"],
            node_context=shared["llm_context"]
        )

        # Use prompt for generation
        response = call_llm(prompt)
```

### 3. Task 19: Planner Response Parser

**Purpose**: Validates and transforms LLM output into clean JSON IR

**Integration Interface**:
```python
# Task 19 provides these functions
class PlannerResponseParser:
    @staticmethod
    def extract_json(llm_response: str) -> dict:
        """Extract JSON from LLM response, handling markdown blocks."""
        # Handle ```json blocks
        # Strip explanatory text
        # Return parsed JSON

    @staticmethod
    def validate_workflow_structure(workflow: dict) -> List[str]:
        """Validate workflow has required structure."""
        errors = []
        # Check nodes array exists
        # Check edges array exists
        # Validate node IDs are unique
        # Check edge references exist
        return errors

    @staticmethod
    def normalize_workflow(workflow: dict) -> dict:
        """Normalize to canonical format."""
        # Add missing defaults
        # Convert node types to lowercase
        # Ensure consistent ID format
        return normalized
```

**Integration in Task 17**:
```python
class WorkflowValidatorNode(Node):
    def exec(self, shared):
        raw_response = shared["llm_response"]

        try:
            # Use Task 19's parser
            workflow = PlannerResponseParser.extract_json(raw_response)
            errors = PlannerResponseParser.validate_workflow_structure(workflow)

            if errors:
                shared["validation_errors"] = errors
                return "retry"

            # Normalize for consistency
            workflow = PlannerResponseParser.normalize_workflow(workflow)
            shared["generated_workflow"] = workflow
            return "success"

        except json.JSONDecodeError as e:
            shared["parse_error"] = str(e)
            return "retry"
```

### 4. Task 12: General LLM Node (Dependency)

**Purpose**: Planner needs LLM node in registry to generate workflows

**Integration Requirements**:
- Task 12 must be completed and registered before Task 17
- LLM node metadata must be in registry
- Planner should recognize "llm" as a valid node type

### 5. Task 9: Shared Store Collision Detector (Runtime Dependency)

**Purpose**: Validates generated workflows won't have store conflicts

**Integration Point**:
```python
# Optional validation in WorkflowValidatorNode
def validate_shared_store_usage(workflow):
    """Check for potential shared store conflicts."""
    # This uses Task 9's collision detection
    from pflow.core.collision_detector import check_workflow_collisions

    conflicts = check_workflow_collisions(workflow)
    if conflicts:
        return ["Shared store conflict: " + c for c in conflicts]
    return []
```

## Comprehensive Testing Strategy

### 1. Unit Tests for Each PocketFlow Node

```python
# tests/test_planner_nodes.py
import pytest
from pflow.flows.planner.nodes import (
    IntentClassifierNode,
    ContextBuilderNode,
    WorkflowGeneratorNode,
    WorkflowValidatorNode
)

class TestIntentClassifierNode:
    def test_natural_language_classification(self):
        node = IntentClassifierNode()
        shared = {"user_input": "fix the bug in main.py"}

        action = node.exec(shared)

        assert action == "natural"
        assert shared["input_type"] == "natural_language"

    def test_cli_syntax_classification(self):
        node = IntentClassifierNode()
        shared = {"user_input": "read-file => analyze => write-report"}

        action = node.exec(shared)

        assert action == "cli"
        assert shared["input_type"] == "cli_syntax"

    def test_ambiguous_input_defaults_to_natural(self):
        node = IntentClassifierNode()
        shared = {"user_input": "=>"}

        action = node.exec(shared)

        assert action == "natural"
```

### 2. Integration Tests for Complete Flow

```python
# tests/test_planner_integration.py
from pflow.flows.planner import create_planner_flow
from unittest.mock import Mock, patch

class TestPlannerFlow:
    @patch('pflow.flows.planner.nodes.call_llm')
    def test_successful_workflow_generation(self, mock_llm):
        # Setup
        mock_llm.return_value = '''
        {
            "nodes": [
                {"id": "read", "type": "read-file"},
                {"id": "analyze", "type": "llm"}
            ],
            "edges": [
                {"from": "read", "to": "analyze"}
            ]
        }
        '''

        # Create flow with dependencies
        flow = create_planner_flow(
            registry=sample_registry,
            prompt_templates=mock_templates
        )

        # Execute
        shared = {"user_input": "analyze the error log"}
        result = flow.run(shared)

        # Verify
        assert "generated_workflow" in result
        assert len(result["generated_workflow"]["nodes"]) == 2
        assert mock_llm.call_count == 1

    @patch('pflow.flows.planner.nodes.call_llm')
    def test_retry_on_invalid_json(self, mock_llm):
        # First attempt returns invalid JSON
        mock_llm.side_effect = [
            "Here's your workflow: {invalid json}",
            '{"nodes": [], "edges": []}'  # Valid on retry
        ]

        flow = create_planner_flow(registry={})
        result = flow.run({"user_input": "test"})

        assert mock_llm.call_count == 2
        assert "generated_workflow" in result
```

### 3. Error Recovery Tests

```python
# tests/test_planner_error_recovery.py
class TestErrorRecovery:
    def test_missing_node_recovery(self):
        """Test recovery when LLM uses non-existent node."""
        generator = WorkflowGeneratorNode()
        validator = WorkflowValidatorNode()

        shared = {
            "llm_response": '{"nodes": [{"type": "github-fix-issue"}]}',
            "registry": {"github-get-issue": {}, "claude-code": {}}
        }

        # Validation should fail
        action = validator.exec(shared)
        assert action == "retry"
        assert "Unknown node type" in shared["validation_errors"][0]

        # Recovery should suggest alternatives
        recovery = RecoveryStrategies.suggest_alternative_node(
            {"missing_node": "github-fix-issue"},
            shared["registry"]
        )
        assert "github-get-issue" in recovery
```

### 4. Performance and Load Tests

```python
# tests/test_planner_performance.py
import time
import pytest

class TestPlannerPerformance:
    @pytest.mark.performance
    def test_context_building_performance(self):
        """Context building should be fast even with large registry."""
        large_registry = {f"node_{i}": {} for i in range(100)}

        start = time.time()
        context = build_planning_context(large_registry)
        duration = time.time() - start

        assert duration < 0.05  # 50ms budget
        assert len(context) < 50000  # Reasonable size

    @pytest.mark.performance
    def test_planner_latency(self):
        """End-to-end planning should meet latency target."""
        flow = create_planner_flow(registry=sample_registry)

        start = time.time()
        result = flow.run({"user_input": "simple task"})
        duration = time.time() - start

        assert duration < 0.8  # 800ms target
```

### 5. Contract Tests with Dependencies

```python
# tests/test_planner_contracts.py
class TestPlannerContracts:
    def test_context_builder_contract(self):
        """Verify Task 16 interface compatibility."""
        from pflow.planning.context_builder import build_planning_context

        # Test with minimal registry
        context = build_planning_context({"test-node": {"description": "Test"}})

        assert isinstance(context, str)
        assert "test-node" in context
        assert "## Available Nodes" in context

    def test_prompt_template_contract(self):
        """Verify Task 18 interface compatibility."""
        from pflow.planning.prompts import PlannerPrompts

        prompt = PlannerPrompts.get_prompt(
            "NATURAL_LANGUAGE_TEMPLATE",
            user_request="test",
            node_context="nodes"
        )

        assert isinstance(prompt, str)
        assert "test" in prompt
        assert "nodes" in prompt
```

### 6. End-to-End Scenario Tests

```python
# tests/test_planner_scenarios.py
SCENARIO_TESTS = [
    {
        "name": "github_workflow",
        "input": "fix github issue 123",
        "expected_nodes": ["github-get-issue", "claude-code", "github-create-pr"],
        "expected_template_vars": ["issue"]
    },
    {
        "name": "file_processing",
        "input": "read all logs and summarize errors",
        "expected_nodes": ["read-file", "llm", "write-file"],
        "expected_template_vars": ["file_pattern", "output_path"]
    }
]

@pytest.mark.parametrize("scenario", SCENARIO_TESTS)
def test_scenario(scenario):
    flow = create_planner_flow(registry=full_registry)
    result = flow.run({"user_input": scenario["input"]})

    workflow = result["generated_workflow"]
    node_types = [n["type"] for n in workflow["nodes"]]

    for expected in scenario["expected_nodes"]:
        assert expected in node_types
```

## Testing Infrastructure

### Mock Fixtures

```python
# tests/fixtures/planner_fixtures.py
@pytest.fixture
def mock_llm_success():
    """Mock LLM that returns valid workflow."""
    with patch('pflow.flows.planner.nodes.call_llm') as mock:
        mock.return_value = '{"nodes": [], "edges": []}'
        yield mock

@pytest.fixture
def sample_registry():
    """Minimal registry for testing."""
    return {
        "read-file": {"inputs": ["file_path"], "outputs": ["content"]},
        "llm": {"inputs": ["prompt"], "outputs": ["response"]},
        "write-file": {"inputs": ["content", "file_path"], "outputs": []}
    }
```

### Test Execution Strategy

1. **Unit Tests First**: Test each node in isolation
2. **Integration Tests**: Test the complete flow with mocks
3. **Contract Tests**: Verify interfaces with dependencies
4. **Scenario Tests**: Test real-world use cases
5. **Performance Tests**: Ensure latency targets are met
6. **Load Tests**: Verify behavior under stress

## Debugging and Monitoring

### Flow Execution Tracing

```python
# Enable detailed tracing for debugging
import logging
logging.getLogger("pocketflow").setLevel(logging.DEBUG)

# Custom trace handler for planner
class PlannerTraceHandler:
    def on_node_start(self, node_name, shared_keys):
        print(f"→ {node_name}: {shared_keys}")

    def on_node_complete(self, node_name, action, duration):
        print(f"← {node_name} [{duration:.2f}s] → {action}")
```

### Key Metrics to Monitor

1. **Success Rate**: % of successful workflow generations
2. **Retry Rate**: Average retries per request
3. **Latency**: P50, P95, P99 response times
4. **Token Usage**: Average tokens per request
5. **Error Distribution**: Most common failure modes

This comprehensive testing strategy ensures the natural language planner integrates correctly with all dependencies and maintains reliability under various conditions.
