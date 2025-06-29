# Task 17: LLM-based Workflow Generation - PocketFlow Implementation Guide

## Overview
This task implements the natural language workflow generator - the heart of pflow's AI capabilities. It uses PocketFlow to orchestrate the complex flow of understanding user intent, generating workflows, validating them, and self-correcting errors.

## PocketFlow Architecture

### Flow Structure
```
ParseInput >> ClassifyIntent >> BuildContext >> GenerateWorkflow >> ValidateOutput >> ResolveTemplates >> Success
     |              |                |                |                   |                  |
     v              v                v                v                   v                  v
ParseError    AmbiguousInput   ContextError      LLMError         ValidationError    TemplateError
                    |                                |                   |
                    v                                v                   v
              ClarifyIntent                    RetryWithFeedback   RetryWithErrors
```

### Key Nodes

#### 1. IntentClassifierNode
```python
class IntentClassifierNode(Node):
    """Classify user input type with smart heuristics"""
    def exec(self, shared):
        user_input = shared["user_input"]

        # Clear CLI syntax
        if ">>" in user_input:
            shared["intent_type"] = "cli_syntax"
            return "parse_cli"

        # Quoted natural language
        if user_input.startswith('"') and user_input.endswith('"'):
            shared["intent_type"] = "natural_language"
            shared["nl_query"] = user_input.strip('"')
            return "build_context"

        # Check for node names (heuristic)
        known_nodes = shared["registry"].list_nodes()
        node_matches = sum(1 for node in known_nodes if node in user_input.lower())

        if node_matches >= 2:
            # Likely CLI syntax
            shared["intent_type"] = "probable_cli"
            return "parse_cli"
        else:
            # Assume natural language
            shared["intent_type"] = "probable_natural"
            shared["nl_query"] = user_input
            return "build_context"
```

#### 2. ContextBuilderNode
```python
class ContextBuilderNode(Node):
    """Build rich context for LLM with available capabilities"""
    def __init__(self, registry):
        super().__init__()
        self.registry = registry

    def exec(self, shared):
        query = shared["nl_query"]

        # Build comprehensive context
        context = {
            "available_nodes": self._get_node_descriptions(),
            "common_patterns": self._get_workflow_patterns(),
            "constraints": self._get_system_constraints(),
            "examples": self._get_relevant_examples(query)
        }

        # Add previous attempts if retrying
        if "previous_attempts" in shared:
            context["previous_attempts"] = shared["previous_attempts"]
            context["errors_to_avoid"] = shared["validation_errors"]

        shared["llm_context"] = context
        return "generate"

    def _get_relevant_examples(self, query):
        """Find examples similar to user query"""
        # Smart example selection based on query keywords
        examples = []

        if "file" in query.lower():
            examples.append(self.FILE_WORKFLOW_EXAMPLE)
        if "github" in query.lower() or "issue" in query.lower():
            examples.append(self.GITHUB_WORKFLOW_EXAMPLE)
        if "analyze" in query.lower() or "sentiment" in query.lower():
            examples.append(self.ANALYSIS_WORKFLOW_EXAMPLE)

        return examples[:3]  # Limit context size
```

#### 3. WorkflowGeneratorNode
```python
class WorkflowGeneratorNode(Node):
    """Generate workflow using LLM with retry and self-correction"""
    def __init__(self, llm_client):
        super().__init__(max_retries=3, wait=2)
        self.llm = llm_client
        self.attempt_count = 0

    def exec(self, shared):
        self.attempt_count += 1

        # Build prompt with increasing structure on retries
        prompt = self._build_prompt(
            query=shared["nl_query"],
            context=shared["llm_context"],
            attempt=self.attempt_count,
            previous_error=shared.get("generation_error")
        )

        # Generate with appropriate model
        response = self.llm.generate(
            prompt=prompt,
            model="gpt-4" if self.attempt_count > 1 else "gpt-3.5-turbo",
            temperature=0.3 if self.attempt_count > 2 else 0.7
        )

        # Extract JSON workflow
        try:
            workflow = self._extract_json(response)
            shared["generated_workflow"] = workflow
            shared["generation_response"] = response
            return "validate"
        except JSONParseError as e:
            shared["generation_error"] = f"Invalid JSON: {e}"
            if self.attempt_count < 3:
                return "retry_structured"
            else:
                return "fallback_template"

    def _build_prompt(self, query, context, attempt, previous_error):
        if attempt == 1:
            # First attempt - natural prompt
            return f"""Create a pflow workflow for: "{query}"

Available nodes: {context['available_nodes']}

Examples:
{context['examples']}

Return a valid JSON workflow."""

        elif attempt == 2:
            # Second attempt - more structure
            return f"""Previous attempt failed: {previous_error}

Create a pflow workflow for: "{query}"

You MUST return ONLY valid JSON in this exact format:
{{
    "nodes": [
        {{"id": "node1", "type": "node_name", "config": {{}}}}
    ],
    "edges": [
        {{"from": "node1", "to": "node2"}}
    ]
}}

Available nodes: {json.dumps(context['available_nodes'], indent=2)}"""

        else:
            # Final attempt - maximum structure
            return f"""This is your final attempt. The previous error was: {previous_error}

Task: {query}

Step 1: List the nodes you will use (from available nodes below)
Step 2: Create the JSON workflow

CRITICAL: Return ONLY the JSON, no explanation.

Available nodes:
{json.dumps(context['available_nodes'], indent=2)}

JSON:"""
```

#### 4. WorkflowValidatorNode
```python
class WorkflowValidatorNode(Node):
    """Validate generated workflow with detailed feedback"""
    def __init__(self, validator):
        super().__init__()
        self.validator = validator

    def exec(self, shared):
        workflow = shared["generated_workflow"]

        # Comprehensive validation
        result = self.validator.validate(workflow)

        if result.is_valid:
            shared["validated_workflow"] = workflow
            return "check_templates"

        # Categorize errors for smart retry
        if self._is_fixable_error(result.errors):
            shared["validation_errors"] = result.errors
            shared["error_category"] = "fixable"

            # Add to attempt history
            attempts = shared.get("previous_attempts", [])
            attempts.append({
                "workflow": workflow,
                "errors": result.errors
            })
            shared["previous_attempts"] = attempts

            return "retry_with_feedback"
        else:
            shared["fatal_errors"] = result.errors
            return "validation_failed"

    def _is_fixable_error(self, errors):
        """Determine if errors can be fixed by retry"""
        fixable_patterns = [
            "unknown node type",
            "missing required config",
            "invalid edge reference",
            "disconnected nodes"
        ]

        for error in errors:
            if any(pattern in error.lower() for pattern in fixable_patterns):
                return True
        return False
```

#### 5. TemplateFallbackNode
```python
class TemplateFallbackNode(Node):
    """Fallback to template matching when generation fails"""
    def exec(self, shared):
        query = shared["nl_query"]

        # Find best matching template
        templates = self._load_templates()
        best_match = self._find_best_template(query, templates)

        if best_match:
            shared["template_workflow"] = best_match["workflow"]
            shared["template_params"] = self._extract_parameters(query, best_match)
            shared["used_fallback"] = True
            return "resolve_template"
        else:
            shared["error"] = "Could not generate workflow or find matching template"
            return "generation_failed"
```

## Implementation Plan

### Phase 1: Core Generation Flow
1. Create `src/pflow/flows/generator/` structure
2. Implement intent classification
3. Build context system
4. Create basic LLM integration

### Phase 2: Smart Retry System
1. Implement retry with feedback
2. Add attempt history tracking
3. Create error categorization
4. Build progressive prompting

### Phase 3: Validation & Correction
1. Integrate workflow validator
2. Implement error analysis
3. Create self-correction loop
4. Add template fallback

### Phase 4: Advanced Features
1. Example selection algorithm
2. Multi-model support (GPT-3.5/4)
3. Temperature adjustment
4. Quality scoring

## Testing Strategy

### Unit Tests
```python
def test_retry_with_feedback():
    """Test that generator improves with feedback"""
    generator = WorkflowGeneratorNode(mock_llm)

    # First attempt returns invalid workflow
    mock_llm.responses = [
        '{"nodes": [{"type": "invalid_node"}]}',  # Bad node
        '{"nodes": [{"id": "n1", "type": "read_file", "config": {"path": "test.txt"}}]}'  # Fixed
    ]

    shared = {
        "nl_query": "read test.txt file",
        "llm_context": {...}
    }

    # First attempt fails
    result1 = generator.exec(shared)
    assert result1 == "validate"

    # Add validation error
    shared["generation_error"] = "Unknown node: invalid_node"

    # Retry succeeds
    result2 = generator.exec(shared)
    assert result2 == "validate"
    assert mock_llm.call_count == 2
```

### Integration Tests
```python
def test_full_generation_flow():
    """Test complete natural language to workflow"""
    flow = create_generator_flow(llm_client, validator)

    result = flow.run({
        "user_input": '"analyze sentiment of customer reviews and save summary"'
    })

    assert result["validated_workflow"] is not None
    assert len(result["validated_workflow"]["nodes"]) >= 3
    assert "llm" in str(result["validated_workflow"])
```

## Prompt Engineering Patterns

### Progressive Structure
1. **Attempt 1**: Natural, conversational
2. **Attempt 2**: Structured with format
3. **Attempt 3**: Step-by-step with examples

### Context Window Management
```python
def _optimize_context(self, context, max_tokens=2000):
    """Keep context within token limits"""
    # Prioritize: current errors > examples > patterns > nodes
    optimized = {
        "errors": context.get("errors", [])[:5],
        "examples": context.get("examples", [])[:2],
        "nodes": self._summarize_nodes(context["nodes"])
    }
    return optimized
```

## Benefits of PocketFlow Approach

1. **Smart Retries**: Each retry improves based on feedback
2. **Clear Flow**: Complex logic is visually apparent
3. **State History**: Full attempt history for debugging
4. **Error Recovery**: Multiple fallback strategies
5. **Testability**: Each decision point is testable

## LLM Integration Patterns

### Model Selection
```python
class ModelSelectorNode(Node):
    """Choose appropriate model based on complexity"""
    def exec(self, shared):
        query_complexity = self._assess_complexity(shared["nl_query"])
        attempt = shared.get("attempt_count", 1)

        if query_complexity > 0.7 or attempt > 1:
            shared["model"] = "gpt-4"
            shared["temperature"] = 0.3
        else:
            shared["model"] = "gpt-3.5-turbo"
            shared["temperature"] = 0.7

        return "generate"
```

### Response Caching
```python
class CachedGeneratorNode(WorkflowGeneratorNode):
    """Cache successful generations for similar queries"""
    def __init__(self, llm_client, cache):
        super().__init__(llm_client)
        self.cache = cache

    def exec(self, shared):
        cache_key = self._get_cache_key(shared["nl_query"])

        if cached := self.cache.get(cache_key):
            shared["generated_workflow"] = cached
            shared["cache_hit"] = True
            return "validate"

        result = super().exec(shared)

        if result == "validate":
            self.cache.set(cache_key, shared["generated_workflow"])

        return result
```

## Performance Optimizations

1. **Parallel Validation**: Validate structure and nodes concurrently
2. **Lazy Context**: Only load examples when needed
3. **Response Streaming**: Process LLM output as it arrives
4. **Smart Caching**: Cache successful patterns

## Future Extensions

1. **Fine-tuned Models**: Train on successful workflows
2. **User Feedback Loop**: Learn from corrections
3. **Multi-turn Clarification**: Ask for details
4. **Workflow Optimization**: Suggest improvements
