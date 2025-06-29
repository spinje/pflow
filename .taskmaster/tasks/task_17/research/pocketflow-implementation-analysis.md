# Task 17: LLM-based Workflow Generation - PocketFlow Implementation Analysis

## Why This is THE Perfect PocketFlow Use Case

The workflow generator is the most complex orchestration in pflow, with multiple paths, retry loops, and external dependencies. It's exactly what PocketFlow was designed for.

### The Complex Control Flow

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

### Why This MUST Use PocketFlow

#### 1. Multiple Entry Points
- Natural language queries
- CLI syntax with >> operators
- Ambiguous input needing classification

Traditional code would have complex if/else branches hiding the flow.

#### 2. LLM Retry Logic is Critical
```python
class PlanWorkflowNode(Node):
    def __init__(self, llm_client):
        super().__init__(max_retries=3, wait=2)  # Automatic retry!
        self.llm = llm_client

    def exec(self, shared):
        # Include previous error in prompt for better results
        previous_error = shared.get("previous_error", "")
        prompt = self.build_prompt(shared["query"], previous_error)

        response = self.llm.generate(prompt)
        shared["llm_response"] = response

        # Try to extract JSON
        try:
            workflow = extract_json(response)
            shared["generated_workflow"] = workflow
            return "validate"
        except JSONParseError:
            shared["parse_error"] = "Invalid JSON in response"
            return "retry_with_structure"
```

#### 3. Self-Correcting Loops
The generator needs multiple feedback loops:
- **Parsing failures** → Retry with structure emphasis
- **Validation failures** → Retry with specific errors
- **Missing templates** → Prompt for values
- **Quality issues** → Supervisor pattern

PocketFlow makes these loops explicit and manageable.

#### 4. State Accumulation for Learning
```python
shared = {
    "user_input": "fix github issue 123",
    "input_type": "natural_language",
    "llm_context": "Available nodes: ...",
    "attempt_count": 1,
    "previous_errors": ["Missing repo parameter"],
    "llm_response": "...",
    "generated_workflow": {...},
    "validation_result": "missing_params",
    "final_workflow": {...}
}
```

Each retry can see the full history!

### Real Implementation Benefits

#### Clear Retry Strategies
```python
class WorkflowGeneratorFlow(Flow):
    def __init__(self, llm_client, validator):
        # Different retry strategies for different failures
        parse = ParseInputNode()
        plan = PlanWorkflowNode(llm_client, max_retries=3)
        validate = ValidateWorkflowNode(validator)
        fix_json = FixJSONNode(llm_client, max_retries=2)
        fix_params = FixParamsNode(llm_client, max_retries=2)

        # Self-loops for different error types
        plan - "invalid_json" >> fix_json >> plan
        plan - "missing_params" >> fix_params >> plan
        validate - "error" >> plan  # Back to planning with error context
```

#### Testing Complex Flows
```python
def test_natural_language_with_retry():
    flow = create_generator_flow(mock_llm, validator)

    # First attempt returns invalid JSON
    mock_llm.responses = [
        "Here's the workflow: {invalid json}",
        '{"nodes": [...valid...]}'
    ]

    result = flow.run({"user_input": "test query"})

    # Flow automatically retried and succeeded!
    assert result["final_workflow"] is not None
    assert mock_llm.call_count == 2
```

### Why Traditional Code Fails Here

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

### Advanced PocketFlow Patterns

#### Dynamic Node Selection
```python
class ClassifyInputNode(Node):
    def exec(self, shared):
        user_input = shared["user_input"]

        # Smart classification
        if self._looks_like_cli(user_input):
            return "parse_cli"
        elif self._looks_like_natural(user_input):
            return "natural_language"
        else:
            return "ask_user"  # Another path!
```

#### Conditional Retries
```python
class ValidateWorkflowNode(Node):
    def exec(self, shared):
        workflow = shared["generated_workflow"]
        result = self.validator.validate(workflow)

        if result.is_valid:
            return "success"
        elif result.is_fixable:
            shared["validation_errors"] = result.errors
            return "retry_with_fixes"
        else:
            return "fatal_error"  # Some errors can't be fixed
```

### Performance Considerations

"But won't all these nodes be slow?"

NO! Because:
1. Nodes are just method calls
2. The expensive operation (LLM) dominates time
3. Clear flow makes optimization obvious
4. Can parallelize independent operations

### Conclusion

The workflow generator is not just a good fit for PocketFlow - it's exactly the kind of complex orchestration that PocketFlow was designed to handle. The alternative (traditional nested code) would be unmaintainable.

Using PocketFlow here provides:
- Clear retry strategies
- Explicit error handling paths
- Self-correcting loops
- Testable components
- Visual flow representation
- State accumulation for learning

This is the heart of pflow - it MUST be reliable, maintainable, and extensible.
