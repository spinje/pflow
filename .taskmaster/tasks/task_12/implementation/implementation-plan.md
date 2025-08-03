# Task 12: LLM Node Implementation Plan

## Summary
Implement a general-purpose LLM node that wraps Simon Willison's `llm` library for text processing in pflow workflows. This is the ONLY LLM node in pflow - preventing proliferation of prompt-specific nodes.

## Critical Understanding from Research

### LLM Library API Patterns
- `llm.get_model(model_id)` - Returns model instance, raises `UnknownModelError`
- `model.prompt(prompt, **kwargs)` - Returns lazy Response object
- `response.text()` - Forces evaluation and returns complete text
- `response.usage()` - Returns Usage object with input/output/details fields (can be None)
- Usage object has: `input`, `output`, `details` attributes

### PocketFlow Node Pattern
- Inherit from `Node` (not BaseNode)
- `name = "llm"` class attribute for registry discovery
- prep() → exec() → post() lifecycle
- NO try/except in exec() - let exceptions bubble for retry mechanism
- exec_fallback() for error handling after retries exhausted
- Parameters set via set_params(), not constructor

### Testing Pattern
- Test full lifecycle with prep/exec/post
- Mock external dependencies (llm.get_model)
- Test retry behavior with transient failures
- Verify error messages are helpful
- Focus on behavior over implementation

## Implementation Tasks

### Phase 1: Setup and Structure (15 min)
1. **Create package directory structure**
   - Create `src/pflow/nodes/llm/` directory
   - Create empty `__init__.py` and `llm.py` files

2. **Create progress log**
   - Initialize `.taskmaster/tasks/task_12/implementation/progress-log.md`

### Phase 2: Core Implementation (45 min)
3. **Implement LLMNode class**
   - Add class with `name = "llm"` attribute
   - Write enhanced Interface docstring
   - Implement prep() with parameter fallback pattern
   - Implement exec() without try/except
   - Implement post() with usage tracking
   - Implement exec_fallback() with error transformations

4. **Update module exports**
   - Update `src/pflow/nodes/llm/__init__.py` with exports

### Phase 3: Testing (60 min)
5. **Create test structure**
   - Create `tests/test_nodes/test_llm/` directory
   - Create `test_llm.py` with test class

6. **Implement unit tests**
   - Mock llm.get_model() and response chain
   - Test all 22 criteria from spec:
     * Prompt extraction (shared vs params)
     * Temperature clamping (< 0, > 2, boundaries)
     * System/max_tokens parameter handling
     * Usage tracking (with data, None case)
     * Error transformations (UnknownModelError, NeedsKeyException)
     * Edge cases (empty prompt, empty response)

7. **Add integration tests** (if time permits)
   - Use actual llm library with mock responses
   - Test real usage data extraction

### Phase 4: Integration (15 min)
8. **Update dependencies**
   - Add `llm>=0.19.0` to pyproject.toml

9. **Manual testing**
   - Test `pflow llm --prompt="Hello"`
   - Verify registry discovery
   - Test with stdin data

### Phase 5: Verification (15 min)
10. **Deploy test-writer-fixer subagent**
    - Verify all 22 test criteria covered
    - Check test quality and edge cases
    - Fix any missing coverage

11. **Run validation**
    - Run `make test`
    - Run `make check`
    - Fix any issues

## Task Dependencies and Parallelization

**Sequential Tasks** (must be done in order):
1. Create package structure → Implement LLMNode → Update exports
2. Create test structure → Write tests → Run tests

**Parallel Opportunities**:
- After LLMNode implemented: Can parallelize test writing (split 22 criteria)
- Documentation updates can happen alongside testing

## Risk Assessment

### High Risk Areas
1. **Usage data extraction** - Usage object can be None, must handle gracefully
2. **Temperature clamping** - Must use max(0.0, min(2.0, temp)) pattern
3. **Registry discovery** - Must have `name = "llm"` attribute

### Mitigation Strategies
1. Defensive programming for usage object access
2. Explicit temperature clamping in prep()
3. Early verification of registry discovery

## Key Implementation Details

### Parameter Fallback Pattern
```python
def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
    # Check shared first, then params
    prompt = shared.get("prompt") or self.params.get("prompt")
    system = shared.get("system") or self.params.get("system")
```

### Usage Extraction (CORRECTED)
```python
def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
         exec_res: Dict[str, Any]) -> str:
    usage_obj = exec_res.get("usage")
    if usage_obj:
        details = getattr(usage_obj, 'details', {}) or {}
        shared["llm_usage"] = {
            "model": exec_res.get("model", "unknown"),
            "input_tokens": usage_obj.input,
            "output_tokens": usage_obj.output,
            "total_tokens": usage_obj.input + usage_obj.output,
            "cache_creation_input_tokens": details.get('cache_creation_input_tokens', 0),
            "cache_read_input_tokens": details.get('cache_read_input_tokens', 0)
        }
    else:
        shared["llm_usage"] = {}
```

### Error Transformation
```python
def exec_fallback(self, prep_res: Dict[str, Any], exc: Exception) -> None:
    error_msg = str(exc)
    if "UnknownModelError" in error_msg:
        raise ValueError(f"Unknown model: {prep_res['model']}. Run 'llm models' to see available models.")
    elif "NeedsKeyException" in error_msg:
        raise ValueError(f"API key required. Set up with 'llm keys set <provider>'.")
    else:
        raise ValueError(f"LLM call failed after {self.max_retries} attempts.")
```

## Success Criteria Checklist
- [ ] `pflow llm --prompt="Hello"` works
- [ ] Registry auto-discovers the node
- [ ] All 22 test criteria pass
- [ ] `make test` passes with no regressions
- [ ] `make check` passes (linting, type checking)
- [ ] Usage tracking works with correct field names
- [ ] Error messages are helpful and guide to solutions
- [ ] Temperature clamping works correctly
- [ ] Empty response is handled (not treated as error)

## Notes and Discoveries
- LLM library handles its own internal retries for API failures
- Our PocketFlow retry (max_retries=3) is for complete node failures only
- Response objects are lazy - must call .text() to force evaluation
- Usage can be None - always check before accessing attributes
- Default model must be exactly "claude-sonnet-4-20250514"
