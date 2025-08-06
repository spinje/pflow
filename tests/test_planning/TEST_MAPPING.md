# Test Mapping Guide for Discovery System

## 🎯 Quick Reference: What to Run When You Change Something

### If you changed nodes.py:

| What You Changed | Tests to Run | Command |
|-----------------|--------------|---------|
| WorkflowDiscoveryNode prompt (lines ~111-180) | `llm/prompts/test_discovery_prompt.py` | `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py -v` |
| ComponentBrowsingNode prompt (lines ~329-404) | `llm/prompts/test_browsing_prompt.py` | `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_browsing_prompt.py -v` |
| Discovery routing logic (`post()` lines ~180-219) | `unit/test_discovery_routing.py` | `pytest tests/test_planning/unit/test_discovery_routing.py -v` |
| Error handling (`exec_fallback()`) | `unit/test_discovery_error_handling.py` | `pytest tests/test_planning/unit/test_discovery_error_handling.py -v` |
| Model configuration (params) | `unit/test_shared_store_contracts.py` | `pytest tests/test_planning/unit/test_shared_store_contracts.py -v` |
| Path A logic (found_existing) | `unit/test_happy_path_mocked.py` + `llm/behavior/test_path_a_reuse.py` | `pytest tests/test_planning/unit/test_happy_path_mocked.py -v` |
| Component selection strategy | `unit/test_browsing_selection.py` | `pytest tests/test_planning/unit/test_browsing_selection.py -v` |
| Confidence thresholds | `llm/behavior/test_confidence_thresholds.py` | `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior/test_confidence_thresholds.py -v` |

## 📍 Code-to-Test Traceability Matrix

### `src/pflow/planning/nodes.py`

```python
class WorkflowDiscoveryNode(Node):
    # Lines 47-266

    def __init__(self):                    # Line 61 | Tested by: unit/test_shared_store_contracts.py::test_init_configurable_parameters_discovery
    def prep(self):                        # Line 70 | Tested by: unit/test_shared_store_contracts.py::test_prep_builds_discovery_context
    def exec(self):                        # Line 111 | Tested by: llm/prompts/test_discovery_prompt.py + unit tests
        # Lines 122-178: Prompt build    → llm/prompts/test_discovery_prompt.py::test_workflow_discovery_with_real_llm
        # Line 141: Lazy model loading   → unit/test_shared_store_contracts.py::test_model_configuration_via_params
        # Line 165: Parse response       → unit/test_shared_store_contracts.py::test_exec_extracts_nested_response_correctly
    def post(self):                        # Line 180 | Tested by: unit/test_discovery_routing.py::test_post_*
        # Lines 196-206: Path A routing  → unit/test_discovery_routing.py::test_post_routes_found_existing_path_a
        # Lines 207-217: Path B routing  → unit/test_discovery_routing.py::test_post_routes_not_found_path_b
    def exec_fallback(self):               # Line 219 | Tested by: unit/test_discovery_error_handling.py::test_exec_fallback_handles_llm_failure_discovery

class ComponentBrowsingNode(Node):
    # Lines 268-478

    def __init__(self):                    # Line 268 | Tested by: unit/test_browsing_selection.py::test_init_configurable_parameters
    def prep(self):                        # Line 277 | Tested by: unit/test_browsing_selection.py::test_prep_loads_registry_and_context
    def exec(self):                        # Line 329 | Tested by: llm/prompts/test_browsing_prompt.py + unit tests
        # Lines 341-402: Prompt build    → llm/prompts/test_browsing_prompt.py::test_component_browsing_with_real_llm
        # Line 381: Lazy model loading   → unit/test_browsing_selection.py::test_model_configuration_via_params
        # Line 385: Parse response       → unit/test_browsing_selection.py::test_exec_extracts_nested_response_correctly
    def post(self):                        # Line 404 | Tested by: unit/test_browsing_selection.py::test_post_*
        # Line 455: Always "generate"    → unit/test_browsing_selection.py::test_post_always_routes_to_generate
    def exec_fallback(self):               # Line 457 | Tested by: unit/test_discovery_error_handling.py::test_exec_fallback_handles_llm_failure_browsing
```

## 🏷️ Pytest Markers for Selective Testing

Add these markers to `pytest.ini`:

```ini
[tool.pytest.ini_options]
markers =
    # Component markers
    discovery: Tests for WorkflowDiscoveryNode
    browsing: Tests for ComponentBrowsingNode

    # Functionality markers
    discovery_routing: Tests routing logic (found_existing vs not_found)
    browsing_selection: Tests component selection logic
    error_handling: Tests exec_fallback and error scenarios
    params: Tests parameter configuration via self.params
    shared_store: Tests shared store contracts
    path_a: Tests Path A (workflow reuse) scenarios
    path_b: Tests Path B (generation) scenarios

    # Prompt-specific markers
    discovery_prompt: Tests sensitive to discovery prompt changes
    browsing_prompt: Tests sensitive to browsing prompt changes

    # Test type markers
    unit: Unit tests with mocked dependencies
    llm: Tests requiring real LLM API
    integration: End-to-end integration tests

    # Performance markers
    fast: Tests that run in <1s
    slow: Tests that take >1s (usually LLM tests)
```

## 🔄 Test Impact Analysis

### High-Impact Changes (Run Everything)
If you change these, run ALL tests:
- `_parse_structured_response()` method (internal parsing logic)
- PocketFlow lifecycle methods (prep/exec/post signatures)
- Shared store key names
- Action strings ("found_existing", "not_found", "generate")

```bash
# Run all unit tests (fast, always run these first)
pytest tests/test_planning/unit -v

# Run all LLM tests (slow, run when unit tests pass)
RUN_LLM_TESTS=1 pytest tests/test_planning/llm -v
```

### Medium-Impact Changes (Run Category)
| Change Type | Run These Tests | Command |
|------------|-----------------|---------|
| Discovery logic | Unit tests first | `pytest tests/test_planning/unit/test_discovery_*.py -v` |
| Browsing logic | Unit tests first | `pytest tests/test_planning/unit/test_browsing_*.py -v` |
| Error handling | Error tests only | `pytest tests/test_planning/unit/test_discovery_error_handling.py -v` |
| Shared store contracts | Contract tests | `pytest tests/test_planning/unit/test_shared_store_contracts.py -v` |

### Low-Impact Changes (Run Specific)
| Change | Run This |
|--------|----------|
| Log messages | Skip tests (no functional impact) |
| Comments | Skip tests |
| Type hints | `mypy src/pflow/planning/nodes.py` |
| Docstrings | `pytest tests/test_planning/unit/test_shared_store_contracts.py::test_init_configurable_parameters_discovery -v` |

## 📊 Test Coverage Report by Code Section

### Discovery Node Coverage (33 total tests)
- **__init__** (Line 61): 1 unit test
- **prep** (Line 70): 1 unit test
- **exec** (Line 111): 6 unit tests + 3 LLM tests
- **post** (Line 180): 4 unit tests
- **exec_fallback** (Line 219): 1 unit test
- **Path A scenarios**: 4 unit tests + 3 LLM tests

### Browsing Node Coverage (20 total tests)
- **__init__** (Line 268): 1 unit test
- **prep** (Line 277): 1 unit test
- **exec** (Line 329): 3 unit tests + 1 LLM test
- **post** (Line 404): 2 unit tests
- **exec_fallback** (Line 457): 1 unit test

## 🚀 Smart Test Commands

### 1. "I changed a prompt"
```bash
# Discovery prompt changed (lines 111-180 in nodes.py)
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py -v

# Browsing prompt changed (lines 329-404 in nodes.py)
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_browsing_prompt.py -v

# Both prompts changed
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts -v

# After prompt changes, verify behavior is still correct
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior -v
```

### 2. "I changed routing logic"
```bash
# Quick unit test check (mocked, fast)
pytest tests/test_planning/unit/test_discovery_routing.py -v

# Verify Path A still works with real LLM
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior/test_path_a_reuse.py -v

# Full integration test
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration -v
```

### 3. "I refactored error handling"
```bash
# Run all error handling tests
pytest tests/test_planning/unit/test_discovery_error_handling.py -v
```

### 4. "I changed model configuration"
```bash
# Unit tests for param handling
pytest tests/test_planning/unit/test_shared_store_contracts.py::test_model_configuration_via_params -v

# Verify with real LLM
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior/test_confidence_thresholds.py -v
```

### 5. "Pre-commit check" (ALWAYS RUN)
```bash
# Fast smoke test - run unit tests only
pytest tests/test_planning/unit --maxfail=3 -v

# If all pass, optionally run one LLM integration test
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_discovery_to_browsing.py::test_full_path_a_scenario -v
```

### 6. "Full regression before release"
```bash
# Step 1: All unit tests (fast, ~5 seconds)
pytest tests/test_planning/unit -v

# Step 2: All LLM tests (slow, ~30 seconds)
RUN_LLM_TESTS=1 pytest tests/test_planning/llm -v

# Or run everything at once
pytest tests/test_planning -v && RUN_LLM_TESTS=1 pytest tests/test_planning/llm -v
```

## 📝 Adding New Tests

### Where to Add Your Test

| Test Type | Location | Example |
|-----------|----------|---------|
| New prompt validation | `llm/prompts/test_{node}_prompt.py` | Testing prompt format/structure |
| New routing scenario | `unit/test_discovery_routing.py` | Testing post() routing logic |
| New error case | `unit/test_discovery_error_handling.py` | Testing exec_fallback() scenarios |
| New Path A scenario | `unit/test_happy_path_mocked.py` | Testing workflow reuse with mocks |
| New Path A with LLM | `llm/behavior/test_path_a_reuse.py` | Testing workflow reuse with real LLM |
| New selection strategy | `unit/test_browsing_selection.py` | Testing component selection logic |
| New integration scenario | `llm/integration/test_discovery_to_browsing.py` | Testing full flow |
| New confidence logic | `llm/behavior/test_confidence_thresholds.py` | Testing confidence scoring |

### Test Naming Convention
```python
def test_{node}_{functionality}_{scenario}():
    """Test that {node} {does something} when {condition}."""

# Examples from actual tests:
def test_post_routes_found_existing_path_a():
def test_post_routes_not_found_path_b():
def test_exec_fallback_handles_llm_failure_discovery():
def test_post_always_routes_to_generate():
```

## 🔍 Debugging Test Failures

### Quick Diagnosis
```bash
# List all tests in a file without running
pytest tests/test_planning/unit/test_discovery_routing.py --collect-only

# Run only the last failed test
pytest tests/test_planning --lf

# Stop at first failure
pytest tests/test_planning/unit --maxfail=1 -v

# Run tests matching a pattern
pytest tests/test_planning -k "routing" -v
```

### Prompt Change Impact
If LLM tests start failing after prompt changes:
1. First check if prompts are being built correctly:
   ```bash
   RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts -v
   ```
2. If prompt tests fail, the format changed - update expected structure
3. Then verify behavior is preserved:
   ```bash
   RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior -v
   ```
4. Finally run integration:
   ```bash
   RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration -v
   ```

## 🎯 Test Strategy by Change Type

### Prompt Changes
1. **Impact**: HIGH - Can change entire behavior
2. **Always Run First**: Unit tests (to catch obvious breaks)
3. **Then Run**: Prompt tests → Behavior tests → Integration tests
4. **Commands**:
   ```bash
   pytest tests/test_planning/unit -v  # Quick sanity check
   RUN_LLM_TESTS=1 pytest tests/test_planning/llm -v  # Full validation
   ```

### Logic Changes (routing, decisions)
1. **Impact**: MEDIUM - Affects flow control
2. **Always Run First**: Relevant unit tests
3. **Then Run**: Behavior tests if unit tests pass
4. **Commands**:
   ```bash
   pytest tests/test_planning/unit/test_discovery_routing.py -v
   pytest tests/test_planning/unit/test_happy_path_mocked.py -v
   # If those pass:
   RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior -v
   ```

### Error Handling Changes
1. **Impact**: LOW - Isolated to failure scenarios
2. **Run**: Error handling tests only
3. **Command**: `pytest tests/test_planning/unit/test_discovery_error_handling.py -v`

### Parameter/Config Changes
1. **Impact**: LOW - Affects configuration
2. **Run**: Contract tests
3. **Command**: `pytest tests/test_planning/unit/test_shared_store_contracts.py -v`

## 💡 Practical Developer Guide

### "I need to test my changes quickly"
```bash
# 1. Run only the most relevant unit test file (2-3 seconds)
pytest tests/test_planning/unit/test_discovery_routing.py -v

# 2. If that passes, run all unit tests (5 seconds)
pytest tests/test_planning/unit -v

# 3. Only if needed, run ONE LLM test to verify (10 seconds)
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_discovery_to_browsing.py::test_full_path_a_scenario -v
```

### "When should I run LLM tests?"
Run LLM tests ONLY when:
- You changed a prompt
- You changed confidence thresholds
- You changed how LLM responses are parsed
- Unit tests pass but you need final validation
- Before merging to main

### "What's the difference between unit/ and llm/ tests?"
- **unit/**: Fast (<1s each), mocked LLM responses, always run these
- **llm/prompts/**: Tests prompt structure, requires real LLM
- **llm/behavior/**: Tests decision logic, requires real LLM
- **llm/integration/**: End-to-end tests, slowest but most comprehensive

### "A test is failing, what do I check?"
1. **Read the test name** - It tells you exactly what it's testing
2. **Check the assertion** - What was expected vs what happened?
3. **Look at the fixture** - Is the test data still valid?
4. **Check recent changes** - Did you change the thing being tested?

### Test File Organization Reference
```
tests/test_planning/
├── unit/                         # ALWAYS RUN THESE (33 tests, ~5 seconds total)
│   ├── test_discovery_routing.py      # 5 tests - routing logic
│   ├── test_discovery_error_handling.py # 9 tests - error scenarios
│   ├── test_shared_store_contracts.py  # 8 tests - data contracts
│   ├── test_browsing_selection.py      # 7 tests - selection logic
│   └── test_happy_path_mocked.py       # 4 tests - Path A with mocks
│
└── llm/                          # RUN SELECTIVELY (10 tests, ~30 seconds total)
    ├── prompts/                  # Run when prompts change
    │   ├── test_discovery_prompt.py    # 3 tests
    │   └── test_browsing_prompt.py     # 1 test
    ├── behavior/                 # Run when logic changes
    │   ├── test_path_a_reuse.py        # 3 tests
    │   └── test_confidence_thresholds.py # 4 tests
    └── integration/              # Run before merging
        └── test_discovery_to_browsing.py # 1 test
```
