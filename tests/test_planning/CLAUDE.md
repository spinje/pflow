# Test Organization Guide for Planning System

This document is the **authoritative guide** for writing and organizing tests in the planning system. All AI agents and developers MUST follow these conventions.

## 🏗️ Directory Structure

```
tests/test_planning/
├── unit/                   # MOCKED tests - Fast, no external dependencies
│   ├── test_*_routing.py          # Flow control and action strings
│   ├── test_*_error_handling.py   # Error scenarios and fallbacks
│   ├── test_*_selection.py        # Component/workflow selection logic
│   ├── test_shared_store_*.py     # Data flow and store contracts
│   └── test_*_management.py       # Single component management logic
│
├── integration/            # MOCKED multi-component tests
│   ├── test_*_flow.py             # Multi-node flows with mocked LLM
│   └── test_*_integration.py      # Component integration tests
│
└── llm/                    # REAL LLM tests - Requires API, expensive
    ├── prompts/            # Tests that validate prompt structure/format
    │   └── test_*_prompts.py      # Break when prompts change
    ├── behavior/           # Tests that validate outcomes/decisions
    │   └── test_*.py               # Resilient to prompt tweaks
    └── integration/        # End-to-end flows with real components
        └── test_*_flow.py          # Complete path validation with real LLM
```

## 📋 Test Categories Explained

### Unit Tests (`unit/`)
**Purpose**: Validate individual components in isolation
**Run When**: Always - part of CI/CD
**Speed**: < 1 second per test
**Characteristics**:
- Mock all LLM calls
- Mock all external dependencies
- Test single component logic
- Verify error handling paths

### Integration Tests (`integration/`)
**Purpose**: Validate multiple components working together
**Run When**: On pull requests and before releases
**Speed**: < 2 seconds per test
**Characteristics**:
- Mock LLM calls
- Test multi-node flows
- May use real file operations (temp directories)
- Test complete user scenarios with mocked dependencies

### LLM Tests (`llm/`)
**Purpose**: Validate real LLM behavior
**Run When**: Selectively based on changes
**Speed**: 2-10 seconds per test
**Cost**: Real API calls ($$)

#### Prompt Tests (`llm/prompts/`)
**What**: Test that prompts produce expected LLM responses
**Breaks When**: Prompt text or structure changes
**Example**: "Does the discovery prompt correctly identify workflows?"

#### Behavior Tests (`llm/behavior/`)
**What**: Test outcomes regardless of exact prompt wording
**Breaks When**: Core logic or requirements change
**Example**: "Does Path A get triggered for high-confidence matches?"

#### Integration Tests (`llm/integration/`)
**What**: Test complete flows through multiple nodes
**Breaks When**: Node interactions or contracts change
**Example**: "Does discovery → browsing → generation flow work?"

## 📝 Test File Template

Every test file MUST start with this header:

```python
"""Test [specific functionality] [with mocks | with real LLM].

WHEN TO RUN:
- [Specific trigger condition 1]
- [Specific trigger condition 2]

WHAT IT VALIDATES:
- [Validation point 1]
- [Validation point 2]

DEPENDENCIES:
- [Any special requirements, API keys, etc.]
"""
```

### Example Unit Test File

```python
"""Test discovery node routing logic with mocked LLM.

WHEN TO RUN:
- Always (part of standard test suite)
- After modifying post() method logic
- After changing action string constants

WHAT IT VALIDATES:
- Correct routing: "found_existing" vs "not_found"
- Shared store updates for both paths
- WorkflowManager integration
"""

import pytest
from unittest.mock import Mock, patch
from pflow.planning.nodes import WorkflowDiscoveryNode


class TestDiscoveryRouting:
    """Test routing decisions in WorkflowDiscoveryNode."""

    def test_high_confidence_routes_to_path_a(self):
        """High confidence match should return 'found_existing'."""
        # Test implementation
```

### Example LLM Test File

```python
"""Test discovery prompt effectiveness with real LLM.

WHEN TO RUN:
- After modifying discovery prompt in WorkflowDiscoveryNode.exec()
- After changing prompt construction logic
- Before releases

WHAT IT VALIDATES:
- LLM correctly identifies exact workflow matches
- LLM correctly rejects partial matches
- Confidence scores are appropriate

DEPENDENCIES:
- Requires RUN_LLM_TESTS=1 environment variable
- Requires configured LLM API key (llm keys set anthropic)
"""

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)
```

## 🎯 Where to Put Your Test

Use this decision tree:

```
Is it testing real LLM behavior?
├── NO
│   ├── Testing single component?
│   │   └── unit/
│   │       ├── Testing routing/action strings? → test_*_routing.py
│   │       ├── Testing error handling? → test_*_error_handling.py
│   │       ├── Testing selection logic? → test_*_selection.py
│   │       └── Testing data flow? → test_shared_store_*.py
│   │
│   └── Testing multiple components?
│       └── integration/
│           ├── Testing complete flows? → test_*_flow.py
│           └── Testing component interactions? → test_*_integration.py
│
└── YES → llm/
    ├── Testing prompt format/structure? → prompts/test_*_prompts.py
    ├── Testing decisions/outcomes? → behavior/test_*.py
    └── Testing complete flows with real LLM? → integration/test_*_flow.py
```

## 🏃 Running Tests

### Quick Reference

```bash
# During development (fast feedback)
pytest tests/test_planning/unit -v

# After changing multi-component flows
pytest tests/test_planning/integration -v

# After changing a prompt
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts -v

# After changing logic
pytest tests/test_planning/unit -v
pytest tests/test_planning/integration -v
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior -v

# Before committing
pytest tests/test_planning/unit -v  # Must pass
pytest tests/test_planning/integration -v  # Should pass

# Before release
RUN_LLM_TESTS=1 pytest tests/test_planning -v  # Everything
```

### Systematic Approach

| What Changed | Run These Tests |
|-------------|-----------------|
| Prompt text | `llm/prompts/` for that component |
| Routing logic | `unit/test_*_routing.py` + `llm/behavior/` |
| Error handling | `unit/test_*_error_handling.py` |
| Shared store contract | `unit/test_shared_store_*.py` |
| Multi-node flows | `integration/` + `llm/integration/` |
| Node interactions | `integration/test_*_flow.py` |
| Major refactoring | Everything |

## ⚠️ Critical Rules

1. **NEVER put real LLM calls in unit/ or integration/ directories**
   - Use mocks for all LLM calls in these directories
   - Real LLM calls belong in llm/ directory only

2. **NEVER put integration tests in unit/ directory**
   - Unit tests test single components
   - Multi-component tests go in integration/

3. **ALWAYS use the standard pytest marker for LLM tests**
   ```python
   pytestmark = pytest.mark.skipif(
       not os.getenv("RUN_LLM_TESTS"),
       reason="LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
   )
   ```

4. **ALWAYS document test triggers in file header**
   - Be specific about when the test should run
   - Help future developers understand test purpose

5. **PREFER many focused test files over few large ones**
   - Each file should test one aspect
   - Makes it easy to run relevant tests

6. **NAME tests descriptively**
   - `test_finds_exact_match_workflow` ✅
   - `test_case_1` ❌

7. **ALWAYS use the North Star workflows as examples**
   - See the `architecture/vision/north-star-examples.md` for more information.
   - Search existing tests for examples of North Star workflows.

## 📊 Test Quality Standards

### Good Test Characteristics
- **Isolated**: Doesn't depend on other tests
- **Deterministic**: Same result every time
- **Fast**: Unit tests < 1s, Integration < 2s, LLM tests < 10s
- **Clear**: Obvious what's being tested
- **Valuable**: Tests real behavior, not implementation

### Coverage Expectations
- **Unit tests**: High coverage (>80%) of individual component logic
- **Integration tests**: Cover main multi-component flows
- **LLM prompt tests**: Cover critical prompt variations
- **LLM behavior tests**: Cover main success/failure paths
- **LLM integration tests**: Cover primary user journeys

## 🔄 Migration Guide for New Nodes

When adding tests for new planning nodes (e.g., ParameterDiscoveryNode):

1. **Create unit test files**:
   ```
   unit/test_parameter_routing.py
   unit/test_parameter_error_handling.py
   unit/test_parameter_extraction.py
   ```

2. **Create integration test files** (if node connects to others):
   ```
   integration/test_discovery_to_parameter_flow.py
   integration/test_parameter_management_integration.py
   ```

3. **Create LLM test files** (if node uses LLM):
   ```
   llm/prompts/test_parameter_prompts.py
   llm/behavior/test_parameter_extraction_accuracy.py
   ```

4. **Add LLM integration tests** (for end-to-end with real LLM):
   ```
   llm/integration/test_discovery_to_parameter_full_flow.py
   ```

## 📈 Future Patterns

As the planning system grows, maintain this structure:

```
tests/test_planning/
├── unit/
│   ├── discovery/        # When discovery tests grow large
│   ├── generation/       # For generation node tests
│   └── validation/       # For validation node tests
├── integration/
│   └── [organized by flow type when it grows]
└── llm/
    └── [same structure]
```

Only create subdirectories when a single node has >10 test files.

## 🚨 Common Mistakes to Avoid

1. **Putting integration tests in unit/ directory**
   - Unit tests are for single components only
   - Multi-component tests go in integration/

2. **Putting mocked tests in llm/ directory**
   - Even if testing LLM-related logic, mocked tests go in unit/ or integration/

3. **Not skipping LLM tests properly**
   - Always use the standard pytestmark

4. **Testing implementation instead of behavior**
   - Test what the node does, not how it does it

5. **Creating "test_everything.py" files**
   - Split tests by concern

6. **Forgetting test file headers**
   - Every file needs WHEN TO RUN and WHAT IT VALIDATES

## 📞 Quick Decision Helper

**Q: I changed the discovery prompt. What do I run?**
A: `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py`

**Q: I changed how errors are handled. What do I run?**
A: `pytest tests/test_planning/unit/test_discovery_error_handling.py`

**Q: I'm not sure what I broke. What do I run?**
A: Start with `pytest tests/test_planning/unit -v`, then run specific LLM tests based on what you changed

**Q: I'm about to commit. What do I run?**
A: `pytest tests/test_planning/unit -v` must pass

**Q: We're about to release. What do I run?**
A: `RUN_LLM_TESTS=1 pytest tests/test_planning -v` - everything

---

*This guide is authoritative. When in doubt, follow these patterns. If you need to deviate, document why in your PR.*
