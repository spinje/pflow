# Real LLM Testing Plan for WorkflowGeneratorNode

## Critical Gap Identified
We have 38 tests with mocked LLM responses but ZERO real LLM tests. This is dangerous because:
- We don't know if the LLM can actually generate valid FlowIR
- Template variable preservation is untested with real models
- Structured output with Pydantic schema is unverified
- The prompt's effectiveness is unknown

## Test Categories Needed

### 1. Basic Generation Tests (`test_generator_llm_basic.py`)
- ✅ Test LLM generates valid FlowIR structure
- ✅ Test ir_version field is included
- ✅ Test nodes and edges arrays are present
- ✅ Test inputs field is created with proper structure

### 2. Template Variable Tests (`test_generator_template_preservation.py`)
- ✅ Test LLM uses $variable syntax
- ✅ Test LLM never hardcodes discovered values
- ✅ Test template paths work ($data.field.subfield)
- ✅ Test all template variables have inputs field entries

### 3. Parameter Management Tests (`test_generator_parameter_handling.py`)
- ✅ Test parameter renaming (filename → input_file)
- ✅ Test universal defaults vs request-specific values
- ✅ Test required vs optional parameter decisions
- ✅ Test discovered_params used as hints only

### 4. Workflow Constraints Tests (`test_generator_constraints.py`)
- ✅ Test linear workflows only (no branching)
- ✅ Test avoids multiple nodes of same type
- ✅ Test descriptive node IDs generated
- ✅ Test workflow_name usage for composition

### 5. Retry Mechanism Tests (`test_generator_retry.py`)
- ✅ Test fixes specific validation errors
- ✅ Test progressive enhancement (no simplification)
- ✅ Test max 3 errors included in retry prompt

### 6. Integration Tests (`test_generator_integration_llm.py`)
- ✅ Test complete Path B flow with real LLM
- ✅ Test convergence with ParameterMappingNode
- ✅ Test North Star examples end-to-end

## Test Implementation Strategy

### Phase 1: Core Validation (CRITICAL)
```python
# tests/test_planning/llm/behavior/test_generator_core.py
def test_llm_generates_valid_flowir():
    """Verify LLM can generate structurally valid FlowIR."""

def test_llm_preserves_template_variables():
    """Verify LLM uses $var syntax, never hardcodes."""

def test_llm_creates_proper_inputs_field():
    """Verify inputs field matches template variables."""
```

### Phase 2: Prompt Effectiveness
```python
# tests/test_planning/llm/prompts/test_generator_prompts.py
def test_template_emphasis_prompt_works():
    """Verify prompt causes LLM to use templates."""

def test_linear_constraint_prompt_works():
    """Verify prompt prevents branching workflows."""
```

### Phase 3: North Star Validation
```python
# tests/test_planning/llm/integration/test_generator_north_star.py
def test_generate_changelog_with_real_llm():
    """End-to-end test with generate-changelog."""

def test_issue_triage_with_real_llm():
    """End-to-end test with issue-triage-report."""
```

## Critical Test Cases

### 1. The Template Variable Test (MOST CRITICAL)
```python
def test_never_hardcodes_discovered_values():
    """The generator MUST NOT hardcode discovered parameter values."""
    shared = {
        "discovered_params": {"limit": "20", "repo": "pflow"},
        "planning_context": "...",
        "user_input": "list last 20 issues from pflow repo"
    }

    # Generated workflow MUST have:
    # - "$limit" not "20"
    # - "$repo" not "pflow"
```

### 2. The Inputs Contract Test
```python
def test_inputs_field_enables_convergence():
    """Inputs field must work with ParameterMappingNode."""
    # Generate workflow
    # Pass to ParameterMappingNode
    # Verify successful extraction
```

### 3. The Retry Test
```python
def test_fixes_specific_errors_on_retry():
    """Generator must fix only reported errors."""
    # First attempt with intentional issue
    # Provide specific error
    # Verify second attempt fixes only that error
```

## Implementation Order

1. **FIRST**: Basic FlowIR generation test (can it even work?)
2. **SECOND**: Template variable preservation (core requirement)
3. **THIRD**: Inputs field structure (enables convergence)
4. **FOURTH**: North Star examples (real-world validation)
5. **FIFTH**: Retry mechanism (robustness)

## Success Criteria

- [ ] At least 10 real LLM tests for GeneratorNode
- [ ] All tests pass with anthropic/claude-sonnet-4-0
- [ ] Template variable preservation verified
- [ ] North Star examples generate correctly
- [ ] Convergence with ParameterMappingNode validated

## Risk Assessment

**HIGH RISK**: Without these tests, we're shipping untested LLM functionality
**MITIGATION**: Implement comprehensive real LLM tests immediately

## Test File Structure

```
tests/test_planning/llm/
├── behavior/
│   ├── test_generator_core.py           # Core generation tests
│   └── test_generator_constraints.py    # Workflow constraints
├── prompts/
│   └── test_generator_prompts.py        # Prompt effectiveness
└── integration/
    └── test_generator_north_star.py     # End-to-end validation
```

## Next Steps

1. Create test_generator_core.py with basic validation
2. Verify template variable preservation
3. Test with North Star examples
4. Validate complete Path B flow
5. Document any prompt adjustments needed
