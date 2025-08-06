# Prompt Externalization and Testing Strategy

## Overview

This document proposes externalizing LLM prompts from code into separate files with an automated test mapping system. This approach would improve prompt maintainability, testing clarity, and enable advanced prompt engineering workflows.

## Problem Statement

As the Natural Language Planner grows, we're accumulating:
- Multiple LLM-based nodes with complex prompts embedded in code
- Increasing number of expensive LLM integration tests
- Difficulty tracking which tests need to run when prompts change
- Challenges in prompt version control and performance testing

Current issues:
1. **Visibility**: Prompt changes are buried in code diffs
2. **Testing Confusion**: Unclear which LLM tests validate which prompts
3. **Performance Testing**: Hard to A/B test different prompt versions
4. **Maintenance**: Prompts mixed with code logic makes both harder to maintain

## Proposed Solution

### 1. File Structure

Organize prompts in dedicated directories with CLAUDE.md files for AI agent instructions:

```
src/pflow/planning/prompts/
├── CLAUDE.md                          # Test mappings and instructions
├── discovery/
│   ├── workflow_discovery.txt         # WorkflowDiscoveryNode prompt
│   ├── component_browsing.txt         # ComponentBrowsingNode prompt
│   └── README.md                      # Discovery prompts documentation
├── generation/
│   ├── workflow_generation.txt        # GeneratorNode prompt
│   ├── parameter_extraction.txt       # ParameterDiscoveryNode prompt
│   └── README.md
├── validation/
│   ├── workflow_validation.txt        # ValidatorNode prompt
│   └── error_feedback.txt             # Error feedback formatting
└── benchmarks/
    ├── results/                        # Performance test results
    └── experiments/                    # A/B test variants
```

### 2. Prompt File Format

Each prompt file would use a simple template format:

```text
# prompts/discovery/workflow_discovery.txt
# Purpose: Determine if existing workflow matches user request
# Node: WorkflowDiscoveryNode
# Template Variables: {discovery_context}, {user_input}
# Last Updated: 2024-01-30
# Performance Baseline: 95% accuracy on test set

You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

Available workflows and nodes:
{discovery_context}

User request: {user_input}

Analyze whether any existing workflow COMPLETELY satisfies this request. A complete match means the workflow does everything the user wants without modification.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false.
```

### 3. CLAUDE.md Test Mapping

The CLAUDE.md file would provide automatic instructions to AI agents:

```markdown
# Prompt Test Management

**CRITICAL**: This directory contains LLM prompt templates. When modifying ANY prompt file, you MUST run the corresponding tests listed below before committing changes.

## Why This Matters

Prompt changes can significantly impact system behavior. Even small wording changes can affect:
- Routing decisions (Path A vs Path B)
- Component selection accuracy
- Parameter extraction quality
- Workflow generation correctness

## Test Requirements by Prompt File

### discovery/workflow_discovery.txt

**Purpose**: Controls Path A/Path B routing decision

**Required Tests**:
```bash
# Test basic functionality
RUN_LLM_TESTS=1 pytest tests/test_planning/test_discovery_llm_integration.py::test_workflow_discovery_with_real_llm -xvs

# Test happy path (finding existing workflows)
RUN_LLM_TESTS=1 pytest tests/test_planning/test_discovery_happy_path.py::test_real_llm_finds_workflow -xvs

# Test confidence thresholds
RUN_LLM_TESTS=1 pytest tests/test_planning/test_discovery_happy_path.py::test_borderline_confidence_triggers_path_b -xvs
```

**Key Metrics to Validate**:
- Path A selection rate should be >80% for exact matches
- Confidence scores should be >0.85 for exact matches
- False positive rate should be <5%

**Common Issues**:
- Making prompt too lenient → False positives (wrong workflows selected)
- Making prompt too strict → Missing valid matches (unnecessary generation)

### discovery/component_browsing.txt

**Purpose**: Selects building blocks for workflow generation

**Required Tests**:
```bash
RUN_LLM_TESTS=1 pytest tests/test_planning/test_discovery_llm_integration.py::test_component_browsing_with_real_llm -xvs
```

**Key Metrics to Validate**:
- Should select 20-50% more components than minimally needed (over-inclusive)
- Must include all critical components for the use case
- Selection reasoning should be logical

### generation/workflow_generation.txt

**Purpose**: Generates new workflow IR from components

**Required Tests**:
```bash
RUN_LLM_TESTS=1 pytest tests/test_planning/test_generation_llm.py::test_workflow_generation -xvs
RUN_LLM_TESTS=1 pytest tests/test_planning/test_generation_llm.py::test_template_variable_usage -xvs
```

**Key Metrics to Validate**:
- Generated workflows must use template variables (not hardcoded values)
- IR structure must be valid
- All required nodes must be connected

## Quick Test Commands

### Test All Changed Prompts
```bash
# Detects which prompts changed and runs their tests
./scripts/test_changed_prompts.sh
```

### Test Specific Category
```bash
# Test all discovery prompts
RUN_LLM_TESTS=1 pytest tests/test_planning/ -k "discovery" --llm-only

# Test all generation prompts
RUN_LLM_TESTS=1 pytest tests/test_planning/ -k "generation" --llm-only
```

### Performance Benchmarking
```bash
# Run performance benchmarks for a prompt
python scripts/benchmark_prompt.py prompts/discovery/workflow_discovery.txt
```

## Prompt Change Workflow

1. **Before Making Changes**:
   - Run baseline tests to ensure they pass
   - Note current performance metrics

2. **Make Your Changes**:
   - Edit the prompt file
   - Update the header comment with change reason

3. **Test Your Changes**:
   - Run ALL tests listed for that prompt
   - Compare metrics with baseline

4. **Document Results**:
   - If performance improved, update baseline in prompt header
   - If performance degraded, consider reverting or document tradeoff

## Emergency Rollback

If a prompt change causes production issues:
```bash
# Revert to previous version
git checkout HEAD~1 -- src/pflow/planning/prompts/discovery/workflow_discovery.txt

# Run tests to confirm fix
RUN_LLM_TESTS=1 pytest tests/test_planning/test_discovery_llm_integration.py -xvs
```
```

### 4. Code Integration

Nodes would load prompts from files:

```python
# src/pflow/planning/nodes.py
from pathlib import Path

class WorkflowDiscoveryNode(Node):
    """Entry point node that routes between workflow reuse and generation."""

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        super().__init__(max_retries=max_retries, wait=wait)
        self._prompt_template = None

    @property
    def prompt_template(self) -> str:
        """Load prompt template from file (cached)."""
        if self._prompt_template is None:
            prompt_file = Path(__file__).parent / "prompts/discovery/workflow_discovery.txt"
            if not prompt_file.exists():
                # Fallback to embedded prompt for backward compatibility
                return self._get_default_prompt()

            content = prompt_file.read_text()
            # Strip header comments
            lines = content.split('\n')
            prompt_lines = [l for l in lines if not l.startswith('#')]
            self._prompt_template = '\n'.join(prompt_lines).strip()

        return self._prompt_template

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute semantic matching against existing workflows."""
        prompt = self.prompt_template.format(
            discovery_context=prep_res["discovery_context"],
            user_input=prep_res["user_input"]
        )

        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(prompt, schema=WorkflowDecision, temperature=prep_res["temperature"])
        # ... rest of implementation
```

### 5. Testing Infrastructure

#### Test Detection Script

```bash
#!/bin/bash
# scripts/test_changed_prompts.sh

# Detect changed prompt files
CHANGED_PROMPTS=$(git diff --name-only HEAD | grep "prompts/.*\.txt$")

if [ -z "$CHANGED_PROMPTS" ]; then
    echo "No prompt files changed"
    exit 0
fi

echo "Changed prompts detected:"
echo "$CHANGED_PROMPTS"

# Extract test commands from CLAUDE.md based on changed files
for prompt in $CHANGED_PROMPTS; do
    prompt_name=$(basename "$prompt")
    echo "Running tests for $prompt_name..."

    # Parse CLAUDE.md to find tests for this prompt
    # (Implementation would extract and run the appropriate test commands)
done
```

#### Benchmark System

```python
# scripts/benchmark_prompt.py
import json
import time
from pathlib import Path
from typing import Dict, List

def benchmark_prompt(prompt_file: Path, test_cases: List[Dict]) -> Dict:
    """Benchmark a prompt against test cases."""
    results = {
        "prompt_file": str(prompt_file),
        "timestamp": time.time(),
        "test_cases": len(test_cases),
        "metrics": {}
    }

    for test_case in test_cases:
        # Run prompt with test case
        # Measure: accuracy, confidence, latency
        pass

    return results

def compare_prompts(prompt_a: Path, prompt_b: Path) -> Dict:
    """A/B test two prompt versions."""
    # Run both prompts on same test set
    # Compare metrics
    pass
```

## Benefits

### 1. **Improved Visibility**
- Prompt changes clearly visible in git diffs
- Easy to review prompt modifications in PRs
- Can track prompt evolution over time

### 2. **Automated Testing**
- CLAUDE.md ensures AI agents know which tests to run
- Clear mapping from prompts to tests
- Reduces chance of breaking changes

### 3. **Better Prompt Engineering**
- Easy A/B testing of prompt variants
- Performance benchmarking infrastructure
- Can build prompt libraries

### 4. **Maintainability**
- Separation of concerns (prompts vs code logic)
- Easier to update prompts without touching code
- Can have prompt specialists work on prompts

### 5. **Version Control**
- Clean prompt history
- Easy rollback of prompt changes
- Can tag prompt versions for releases

## Implementation Plan

### Phase 1: Infrastructure (2-3 hours)
1. Create prompts directory structure
2. Implement prompt loading in base Node class
3. Create CLAUDE.md with initial mappings
4. Build test detection script

### Phase 2: Migration (3-4 hours)
1. Extract prompts from existing nodes
2. Update nodes to load from files
3. Verify all tests still pass
4. Update documentation

### Phase 3: Tooling (2-3 hours)
1. Create benchmark system
2. Build A/B testing framework
3. Add prompt validation/linting
4. Create performance dashboard

## Considerations and Tradeoffs

### Pros
- Clear separation of concerns
- Better testing visibility
- Enables advanced prompt workflows
- Improved maintainability

### Cons
- Additional files to manage
- Potential deployment complexity
- Need to handle missing prompt files
- Template variable validation needed

## Future Enhancements

1. **Prompt Versioning**: Support multiple prompt versions with feature flags
2. **Prompt Compilation**: Optimize prompts for production (minification, caching)
3. **Prompt Analytics**: Track prompt performance in production
4. **Prompt Marketplace**: Share prompts across projects/teams
5. **Dynamic Prompts**: Support conditional logic in prompts
6. **Localization**: Multi-language prompt support

## Migration Strategy

If adopting this approach:

1. **Start Small**: Begin with one node (e.g., WorkflowDiscoveryNode)
2. **Validate Benefits**: Ensure the approach improves workflow
3. **Gradual Rollout**: Migrate other nodes incrementally
4. **Maintain Compatibility**: Keep embedded prompts as fallback
5. **Document Patterns**: Create best practices guide

## Conclusion

Externalizing prompts with automated test mappings would provide significant benefits for maintainability, testing, and prompt engineering. The CLAUDE.md pattern ensures AI agents automatically understand test requirements, reducing the cognitive load of managing LLM tests.

This approach aligns with the project's philosophy of clear separation of concerns and making system behavior transparent and testable.
