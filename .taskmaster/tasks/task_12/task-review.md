# Task 12: General LLM Node Implementation - Comprehensive Review

## Executive Summary

Task 12 implements the **singular, general-purpose LLM node** for pflow - a critical infrastructure component that enables AI-powered text processing in workflows. This node wraps Simon Willison's `llm` library to provide a flexible, provider-agnostic interface for Large Language Model interactions. The implementation follows a "one node to rule them all" philosophy, preventing proliferation of prompt-specific nodes while maintaining maximum flexibility through configuration.

**Key Deliverables:**
- ✅ `LLMNode` class with full PocketFlow lifecycle implementation
- ✅ Registry-discoverable via `name = "llm"` attribute
- ✅ 24 comprehensive tests (22 spec criteria + extras)
- ✅ Plugin-based architecture for provider flexibility
- ✅ Token usage tracking for cost analysis
- ✅ Integration test suite with skip conditions

**System Impact:** Enables Task 17 (planner) to generate meaningful AI-powered workflows beyond basic file operations.

## Component Architecture

### File Structure
```
src/pflow/nodes/llm/
├── __init__.py          # Module exports: LLMNode
├── llm.py               # Core implementation: LLMNode class
└── README.md            # User documentation for LLM node usage

tests/test_nodes/test_llm/
├── test_llm.py              # 24 mocked tests covering all criteria
├── test_llm_integration.py  # 9 real API tests (skip by default)
└── TESTING.md               # Developer testing guide
```

### Class Implementation

#### LLMNode Class Hierarchy
```python
pocketflow.Node (base class)
    └── LLMNode (src/pflow/nodes/llm/llm.py)
```

#### Critical Class Attributes
```python
class LLMNode(Node):
    name = "llm"  # REQUIRED for registry discovery - DO NOT CHANGE
```

#### Method Contracts

| Method | Purpose | Critical Details |
|--------|---------|-----------------|
| `__init__(max_retries=3, wait=1.0)` | Initialize with retry support | Base class handles retry logic |
| `prep(shared)` | Extract/validate inputs | Parameter fallback: shared → params |
| `exec(prep_res)` | Call LLM API | NO try/except - let exceptions bubble |
| `post(shared, prep_res, exec_res)` | Store results | Extract usage, handle None gracefully |
| `exec_fallback(prep_res, exc)` | Error handling | Transform to helpful messages |

### Interface Documentation Format
```python
"""
Interface:
- Reads: shared["prompt"]: str  # Text prompt to send to model
- Reads: shared["system"]: str  # System prompt (optional)
- Writes: shared["response"]: str  # Model's text response
- Writes: shared["llm_usage"]: dict  # Token usage metrics
- Params: model: str  # Model to use (default: gpt-4o-mini)
- Params: temperature: float  # Sampling temperature (default: 0.7)
- Params: max_tokens: int  # Max response tokens (optional)
- Actions: default (always)
"""
```

## Integration Points

### 1. Registry Discovery
- **Mechanism**: `name = "llm"` class attribute
- **Scanner Path**: `src/pflow/registry/scanner.py` → finds LLMNode
- **Metadata Extraction**: Parses Interface docstring successfully
- **CLI Registration**: Available as `pflow llm` command

### 2. Shared Store Interaction
```python
# Parameter Fallback Pattern (CRITICAL):
prompt = shared.get("prompt") or self.params.get("prompt")
system = shared.get("system") or self.params.get("system")

# Output Storage:
shared["response"] = exec_res["response"]
shared["llm_usage"] = {...}  # Empty dict {} if None
```

### 3. Template Variable Support
- **Integration**: Runtime resolves variables BEFORE node execution
- **Example**: `--prompt="Summarize: $content"` → node receives resolved text
- **Node Responsibility**: None - just receives final strings

### 4. Planner Integration (Task 17)
- **Usage**: Planner can include `llm` nodes in generated workflows
- **Benefit**: Enables AI-powered workflows beyond file operations
- **Pattern**: `read-file >> llm --prompt="..."` workflows

## Design Decisions & Rationale

### 1. Single LLM Node Philosophy
**Decision**: One general `llm` node instead of many specific nodes
**Rationale**: Prevents node proliferation (analyze-code, write-content, etc.)
**Impact**: Simpler registry, easier maintenance, more flexible usage

### 2. Plugin Architecture
**Decision**: Core `llm` library only, plugins installed separately
**Rationale**: Users only install/pay for providers they use
**Impact**: Lighter dependencies, future-proof for new providers

### 3. Default Model Selection
**Decision**: `gpt-4o-mini` as default (OpenAI's default)
**Previous**: Was `claude-sonnet-4-20250514`, then `anthropic/claude-sonnet-4-0`
**Rationale**: Works with base `llm` installation, no plugin required

### 4. Temperature Clamping
**Decision**: Clamp to [0.0, 2.0] using `max(0.0, min(2.0, temp))`
**Rationale**: Prevent API errors from out-of-range values
**Implementation Location**: `prep()` method

### 5. Usage Tracking Structure
**Decision**: Specific field names with empty dict fallback
```python
{
    "model": "gpt-4o-mini",
    "input_tokens": 150,
    "output_tokens": 75,
    "total_tokens": 225,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
}
# OR {} if usage unavailable
```
**Rationale**: Enables cost analysis for "Plan Once, Run Forever" efficiency

## Dependency Management

### Core Dependencies
```toml
dependencies = [
    "llm>=0.19.0",  # Simon Willison's LLM library
]
```

### Optional Dependencies
```toml
[project.optional-dependencies]
anthropic = ["llm-anthropic>=0.17"]
all-llms = ["llm-anthropic>=0.17"]  # Expandable list
```

### Plugin Installation Pattern
```bash
# Users install plugins as needed:
pip install llm-anthropic  # For Claude
pip install llm-gpt4all    # For local models
pip install llm-ollama     # For Ollama
# OpenAI support is built into base llm
```

### API Key Management
1. **Persistent** (Recommended for development):
   ```bash
   llm keys set anthropic
   llm keys set openai
   ```
   Stored in: `~/.config/io.datasette.llm/keys.json`

2. **Environment Variables** (For CI/CD):
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export OPENAI_API_KEY="sk-..."
   ```

## Testing Architecture

### Test Distribution
- **Mocked Tests**: 24 tests in `test_llm.py` (always run)
- **Integration Tests**: 9 tests in `test_llm_integration.py` (optional)
- **Coverage**: All 22 specification criteria + edge cases

### Test Criteria Mapping
| Criteria | Test Method | Type |
|----------|------------|------|
| Prompt from shared | `test_prompt_from_shared` | Mock |
| Prompt from params | `test_prompt_from_params_fallback` | Mock |
| Missing prompt error | `test_missing_prompt_raises_error` | Mock |
| Temperature clamping | `test_temperature_*_clamped` | Mock |
| Usage tracking | `test_usage_data_stored_correctly` | Mock |
| API key errors | `test_needs_key_exception_handling` | Mock |
| Real API calls | `test_real_llm_call_basic` | Integration |

### Integration Test Activation
```bash
# Requirements:
pip install llm-anthropic  # Or relevant plugin
export RUN_LLM_TESTS=1     # Enable flag
export ANTHROPIC_API_KEY="..."  # Or use llm keys set

# Run:
pytest tests/test_nodes/test_llm/test_llm_integration.py
```

### Skip Conditions
```python
@pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="Set RUN_LLM_TESTS=1 to run real LLM tests"
)
@pytest.mark.skipif(
    not has_anthropic_api_key(),
    reason="Anthropic plugin or API key not available"
)
```

## Usage Patterns & Examples

### CLI Invocation
```bash
# Basic usage
pflow llm --prompt="Hello, world!"

# With parameters
pflow llm --prompt="Write a haiku" --temperature=0.3 --max_tokens=50

# With specific model
pflow llm --prompt="Explain quantum physics" --model="gpt-4"
```

### Workflow Integration
```bash
# Read file and summarize
pflow read-file --path=doc.txt >> llm --prompt="Summarize: $content"

# Chain multiple LLM calls
pflow llm --prompt="Generate title" >> llm --prompt="Expand on: $response"
```

### Parameter Precedence
1. **Shared store** (highest priority)
2. **CLI parameters** (fallback)
3. **Defaults** (last resort)

### Error Handling Patterns
```python
# In exec_fallback, errors are transformed:
"UnknownModelError" → "Run 'llm models' to see available models"
"NeedsKeyException" → "Set up with 'llm keys set <provider>'"
Generic errors → "LLM call failed after X attempts"
```

## Cross-Component Impacts

### Impact on Planner (Task 17)
- **Capability**: Planner can now generate AI-powered workflows
- **Integration**: Planner knows about `llm` node via registry
- **Usage**: Can include `--prompt` parameters with template variables

### Registry Scanning
- **Discovery**: Scanner finds LLMNode via `name` attribute
- **Metadata**: Successfully extracts Interface documentation
- **Naming**: Available as "llm" in node registry

### Runtime Compilation
- **IR Support**: LLM node parameters map to IR schema
- **Template Resolution**: Runtime handles `$variable` substitution
- **Execution**: Compiles to PocketFlow Node object correctly

### Shell Integration
- **Pipe Support**: Works with stdin/stdout piping
- **Parameter Parsing**: CLI handles all parameter types
- **Dual Mode**: Supports both workflow and direct execution

## Common Pitfalls & Solutions

### Pitfall 1: Usage Object is None
**Problem**: `response.usage()` can return None
**Solution**: Always check before accessing attributes
```python
usage_obj = response.usage()
if usage_obj:
    tokens = usage_obj.input
else:
    shared["llm_usage"] = {}
```

### Pitfall 2: Model Not Found
**Problem**: Plugin not installed for requested model
**Solution**: Install appropriate plugin
```bash
# Error: Unknown model: anthropic/claude-3-opus
pip install llm-anthropic
```

### Pitfall 3: Wrong Field Names
**Problem**: Using `input` instead of `input_tokens`
**Solution**: Use exact field names from spec
```python
"input_tokens": usage_obj.input,  # NOT "input": usage_obj.input
"output_tokens": usage_obj.output,  # NOT "output": usage_obj.output
```

### Pitfall 4: Try/Except in exec()
**Problem**: Breaks PocketFlow retry mechanism
**Solution**: Let exceptions bubble up
```python
def exec(self, prep_res):
    # NO try/except here!
    model = llm.get_model(prep_res["model"])
    return model.prompt(...)
```

### Pitfall 5: Forgetting name Attribute
**Problem**: Node not discovered by registry
**Solution**: Always include class attribute
```python
class LLMNode(Node):
    name = "llm"  # CRITICAL - DO NOT FORGET
```

## Future Considerations

### Potential Enhancements
1. **Structured Output** (v2.0)
   - JSON schema support
   - Pydantic model integration
   - Type-safe responses

2. **Multimodal Support** (v2.0)
   - Image attachments
   - Audio processing
   - Document analysis

3. **Advanced Features** (v3.0)
   - Tool/function calling
   - Conversation management
   - Streaming responses

### Performance Optimizations
- Response caching for identical prompts
- Batch processing for multiple prompts
- Async execution for parallel calls

### Cloud Platform Adaptations
- Remote execution via MCP servers
- Usage tracking aggregation
- Cost optimization strategies

## Quick Reference Tables

### File-to-Purpose Mapping
| File | Purpose |
|------|---------|
| `src/pflow/nodes/llm/llm.py` | Core LLMNode implementation |
| `src/pflow/nodes/llm/__init__.py` | Module exports |
| `tests/test_nodes/test_llm/test_llm.py` | Mocked unit tests |
| `tests/test_nodes/test_llm/test_llm_integration.py` | Real API tests |

### Method-to-Responsibility Mapping
| Method | Responsibility |
|--------|---------------|
| `prep()` | Input validation, parameter fallback, temperature clamping |
| `exec()` | LLM API call, response evaluation, usage capture |
| `post()` | Store response and usage in shared store |
| `exec_fallback()` | Transform exceptions to helpful messages |

### Error-to-Solution Mapping
| Error | Solution |
|-------|----------|
| "Unknown model" | Install plugin: `pip install llm-anthropic` |
| "API key required" | Set key: `llm keys set <provider>` |
| "No prompt" | Provide via `--prompt` or previous node output |
| "Temperature out of range" | Already clamped to [0.0, 2.0] |

### Test-to-Criteria Mapping
| Test Criteria | Coverage | Test Type |
|---------------|----------|-----------|
| All 22 spec criteria | ✅ 100% | Mocked |
| Real API interaction | ✅ 9 tests | Integration |
| Edge cases | ✅ Covered | Both |
| Error conditions | ✅ Comprehensive | Mocked |

## Lessons Learned

1. **Plugin Architecture Flexibility**: Making plugins optional was the right choice - reduces dependencies and allows user choice.

2. **Usage Tracking Importance**: Critical for demonstrating pflow's efficiency - must handle None gracefully.

3. **Test Separation Strategy**: Mocked tests as primary, integration as optional works perfectly for CI/CD.

4. **Error Message Quality**: Transforming cryptic errors to actionable messages significantly improves UX.

5. **Interface Documentation**: The structured format enables automatic metadata extraction and registry discovery.

## Implementation Checklist for Future Tasks

When implementing nodes that interact with the LLM node:

- [ ] Use shared store for passing prompts/responses
- [ ] Respect parameter fallback pattern (shared → params)
- [ ] Handle empty responses gracefully
- [ ] Check `llm_usage` for cost tracking
- [ ] Use template variables for dynamic content
- [ ] Test with mocked LLMNode for unit tests
- [ ] Document LLM node as dependency if required

## Final Notes

The LLM node represents a critical architectural decision: **one flexible node over many specific ones**. This design ensures maintainability, reduces complexity, and provides maximum flexibility. The plugin architecture ensures future compatibility with new LLM providers without code changes. The comprehensive test suite ensures reliability while keeping costs minimal through mocking.

**Key Insight**: The LLM node is not just a feature - it's the bridge that transforms pflow from a simple workflow tool into an AI-powered automation platform.
