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
│   └── test_*_mocked.py           # Other mocked scenarios
│
└── llm/                    # REAL LLM tests - Requires API, expensive
    ├── prompts/            # Tests that validate prompt structure/format
    │   └── test_*_prompt.py        # Break when prompts change
    ├── behavior/           # Tests that validate outcomes/decisions
    │   └── test_*.py               # Resilient to prompt tweaks
    └── integration/        # End-to-end flows with real components
        └── test_*_flow.py          # Complete path validation
```

## 📋 Test Categories Explained

### Unit Tests (`unit/`)
**Purpose**: Validate logic without external dependencies
**Run When**: Always - part of CI/CD
**Speed**: < 1 second per test
**Characteristics**:
- Mock all LLM calls
- Mock file I/O when needed
- Test pure logic and data flow
- Verify error handling paths

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
├── NO → unit/
│   ├── Testing routing/action strings? → test_*_routing.py
│   ├── Testing error handling? → test_*_error_handling.py
│   ├── Testing selection logic? → test_*_selection.py
│   └── Testing data flow? → test_shared_store_*.py
│
└── YES → llm/
    ├── Testing prompt format/structure? → prompts/test_*_prompt.py
    ├── Testing decisions/outcomes? → behavior/test_*.py
    └── Testing complete flows? → integration/test_*_flow.py
```

## 🏃 Running Tests

### Quick Reference

```bash
# During development (fast feedback)
pytest tests/test_planning/unit -v

# After changing a prompt
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts -v

# After changing logic
pytest tests/test_planning/unit -v
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior -v

# Before committing
pytest tests/test_planning/unit -v  # Must pass

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
| Node interactions | `llm/integration/` |
| Major refactoring | Everything |

## ⚠️ Critical Rules

1. **NEVER put real LLM calls in unit/ directory**
   - Use mocks for all external dependencies
   - Real calls belong in llm/ directory only

2. **ALWAYS use the standard pytest marker for LLM tests**
   ```python
   pytestmark = pytest.mark.skipif(
       not os.getenv("RUN_LLM_TESTS"),
       reason="LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
   )
   ```

3. **ALWAYS document test triggers in file header**
   - Be specific about when the test should run
   - Help future developers understand test purpose

4. **PREFER many focused test files over few large ones**
   - Each file should test one aspect
   - Makes it easy to run relevant tests

5. **NAME tests descriptively**
   - `test_finds_exact_match_workflow` ✅
   - `test_case_1` ❌

6. **Try to use the North Star workflows as much as possible**
   - See the `docs/vision/north-star-examples.md` for more information.
   - Search existing tests for examples of North Star workflows.

## 📊 Test Quality Standards

### Good Test Characteristics
- **Isolated**: Doesn't depend on other tests
- **Deterministic**: Same result every time
- **Fast**: Unit tests < 1s, LLM tests < 10s
- **Clear**: Obvious what's being tested
- **Valuable**: Tests real behavior, not implementation

### Coverage Expectations
- **Unit tests**: High coverage (>80%) of logic paths
- **LLM prompt tests**: Cover critical prompt variations
- **LLM behavior tests**: Cover main success/failure paths
- **Integration tests**: Cover primary user journeys

## 🔄 Migration Guide for New Nodes

When adding tests for new planning nodes (e.g., ParameterDiscoveryNode):

1. **Create unit test files**:
   ```
   unit/test_parameter_routing.py
   unit/test_parameter_error_handling.py
   unit/test_parameter_extraction.py
   ```

2. **Create LLM test files** (if node uses LLM):
   ```
   llm/prompts/test_parameter_prompt.py
   llm/behavior/test_parameter_extraction_behavior.py
   ```

3. **Add integration tests** (if node connects to others):
   ```
   llm/integration/test_browsing_to_parameter_flow.py
   ```

## 📈 Future Patterns

As the planning system grows, maintain this structure:

```
tests/test_planning/
├── unit/
│   ├── discovery/        # When discovery tests grow large
│   ├── generation/       # For generation node tests
│   └── validation/       # For validation node tests
└── llm/
    └── [same structure]
```

Only create subdirectories when a single node has >10 test files.

## 🚨 Common Mistakes to Avoid

1. **Putting mocked tests in llm/ directory**
   - Even if testing LLM-related logic, mocked tests go in unit/

2. **Not skipping LLM tests properly**
   - Always use the standard pytestmark

3. **Testing implementation instead of behavior**
   - Test what the node does, not how it does it

4. **Creating "test_everything.py" files**
   - Split tests by concern

5. **Forgetting test file headers**
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
