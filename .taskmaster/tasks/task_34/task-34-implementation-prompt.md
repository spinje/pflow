# Task 34: Prompt Accuracy Tracking System - Agent Instructions

## The Problem You're Solving

Developers improving LLM prompts currently have no visibility of test accuracy when editing prompt files. They must run tests separately, manually track improvements, and context-switch between editing and testing. This slows prompt iteration and makes it difficult to track progress toward 100% accuracy goals.

## Your Mission

Implement a lightweight accuracy tracking system that displays test accuracy directly in prompt markdown files using YAML frontmatter. Create a simple developer tool that runs tests and updates accuracy when improved, enabling rapid prompt iteration with immediate visibility of performance metrics.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_34/task_34.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_34/starting-context/`

**Files to read (in this order):**
1. `task-34-spec.md` - The specification (FOLLOW THIS PRECISELY - source of truth for requirements)

**Directory**: `.taskmaster/tasks/task_34/handoffs/`

**Files to read:**
1. `task_34-handover.md` - Critical tacit knowledge from design phase including discoveries about the prompt system

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-34-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

A developer-only tool for tracking prompt test accuracy directly in prompt markdown files. The system consists of:
1. YAML frontmatter added to each prompt file showing current accuracy
2. A standalone Python script (`test_runner.py`) that runs tests and updates accuracy
3. Integration with existing LLM tests to extract pass/fail metrics

Example prompt file with frontmatter:
```markdown
---
name: discovery
test_path: tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPromptSensitive
accuracy: 85.0
last_tested: 2024-01-15
---

# Discovery Prompt

You are a workflow discovery system...
{{user_input}}
{{discovery_context}}
```

Developer workflow:
```bash
cd src/pflow/planning/prompts
python test_runner.py discovery          # Run test, see results
python test_runner.py discovery --update # Update accuracy if improved
```

## Key Outcomes You Must Achieve

### Core Functionality
- Add frontmatter to all 6 prompt markdown files
- Create `test_runner.py` script that runs tests and calculates accuracy
- Parse and update frontmatter without breaking existing prompt loading
- Only update accuracy when it improves (reduces git noise)

### Developer Experience
- Single command to test any prompt
- Clear display of test results and accuracy
- Immediate visibility of current accuracy in prompt files
- Simple workflow: edit → test → update → commit

### Integration
- Work with existing test infrastructure in `tests/test_planning/llm/prompts/`
- Require `RUN_LLM_TESTS=1` environment variable for real LLM calls
- Preserve existing prompt loading in `loader.py`
- No impact on user-facing pflow CLI

## Implementation Strategy

### Phase 1: Core Infrastructure (2 hours)
1. Create `src/pflow/planning/prompts/test_runner.py` with basic structure
2. Implement frontmatter parsing and updating logic
3. Add test execution and result capture
4. Test with one prompt file (discovery.md)

### Phase 2: Test Integration (2 hours)
1. Modify test classes to expose accuracy metrics
2. Implement subprocess-based test execution with result parsing
3. Calculate accuracy from passed/failed test cases
4. Handle test failures and errors gracefully

### Phase 3: Apply to All Prompts (1 hour)
1. Add frontmatter to all 6 prompt files with initial accuracy
2. Verify each prompt's test path is correct
3. Run baseline tests for all prompts
4. Document current accuracy levels

### Phase 4: Developer Documentation (1 hour)
1. Create `src/pflow/planning/prompts/README.md` with usage instructions
2. Document the prompt improvement workflow
3. Add examples of successful iterations
4. Include troubleshooting guide

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Frontmatter Schema (Minimal)
```yaml
---
name: discovery              # Prompt identifier
test_path: tests/...         # Pytest path to run
accuracy: 85.0              # Current accuracy (0-100)
last_tested: 2024-01-15     # Date of last test (YYYY-MM-DD)
---
```
All fields are required. Keep it simple - no optional fields.

### Test Execution Pattern
The existing tests require the `RUN_LLM_TESTS=1` environment variable:
```python
# This MUST be set or tests will skip silently
env = os.environ.copy()
env['RUN_LLM_TESTS'] = '1'
result = subprocess.run(['pytest', test_path, '-v'], env=env, ...)
```

### Prompt Variable Format
Prompts use `{{variable}}` placeholders (double braces, not single):
```markdown
User request: {{user_input}}
Context: {{discovery_context}}
```

### Accuracy Update Logic
Only update when improved (handle LLM variance):
```python
current_accuracy = extract_accuracy(content)
new_accuracy = (passed / total * 100) if total > 0 else 0

# Only update if significantly better (>2% improvement)
if new_accuracy > current_accuracy + 2:
    update_frontmatter(prompt_file, new_accuracy)
```

### Existing Prompt Loading
The current `loader.py` doesn't handle frontmatter. You must:
1. Parse and skip frontmatter when loading prompts
2. Preserve backward compatibility
3. Return prompt content after the closing `---`

## Critical Warnings from Experience

### LLM Response Variance
LLM responses vary 2-3% between runs due to non-determinism. Only update accuracy on significant improvements (>2%) to avoid constant updates.

### Test Skip Trap
Tests skip silently without `RUN_LLM_TESTS=1`. Your test runner MUST set this environment variable or you'll get 0% accuracy with no errors.

### Orphaned Templates File
There's an unused `src/pflow/planning/prompts/templates.py` file. Ignore it - it's from an abandoned approach. Don't try to integrate with it.

### Git Noise is Acceptable
We discussed whether updating accuracy in source files creates git noise. Decision: It's worth it for developer experience. Commits showing accuracy improvements are valuable progress markers.

### Simplicity Over Framework
The user explicitly rejected complexity multiple times. Don't build a framework. A single Python script (~200 lines) is the target, not a system.

## Key Decisions Already Made

1. **Developer-only tool** - Not exposed through main pflow CLI
2. **Minimal frontmatter** - Only 4 required fields, no optional fields
3. **Single Python script** - `test_runner.py` as standalone tool
4. **Update only on improvement** - Reduces git noise
5. **Git commits show progress** - Accuracy in version control is intentional
6. **No regression detection** - Just track current accuracy
7. **No CI integration** - Manual developer tool only
8. **Round to 1 decimal** - e.g., 85.0% not 85.0371%

**📋 Note on Specifications**: The specification file (`task-34-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All 6 prompt files have frontmatter with accuracy
- ✅ `test_runner.py` successfully tests each prompt
- ✅ Accuracy only updates when improved
- ✅ Frontmatter parsing doesn't break existing prompt loading
- ✅ Developer can see accuracy when opening any prompt file
- ✅ Single command runs tests for any prompt
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ No changes to user-facing pflow CLI
- ✅ Documentation complete for developers

## Common Pitfalls to Avoid

1. **Building a framework** - Keep it simple, one Python script
2. **Exposing to users** - This is developer-only, not in main CLI
3. **Tracking too much** - Only track accuracy, not timing or tokens
4. **Complex test integration** - Use subprocess and parse output
5. **Forgetting RUN_LLM_TESTS** - Tests skip without this env var
6. **Over-engineering frontmatter** - 4 fields only, all required
7. **Fighting LLM variance** - Accept 2-3% variance as normal
8. **Breaking prompt loading** - Test that existing code still works

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Prompt System Analysis**
   - Task: "Analyze how prompts are currently loaded in src/pflow/planning/prompts/loader.py and identify how to add frontmatter parsing without breaking existing functionality"
   - Task: "Examine all 6 prompt files in src/pflow/planning/prompts/*.md to understand their current structure and {{variable}} usage"

2. **Test Infrastructure Discovery**
   - Task: "Analyze tests/test_planning/llm/prompts/ structure and identify how each test class validates prompt outputs"
   - Task: "Find the pattern for running specific test methods and extracting pass/fail counts"

3. **Integration Points**
   - Task: "Check how nodes load prompts and ensure frontmatter won't break them"
   - Task: "Verify no other code depends on prompt file format"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_34/implementation/implementation-plan.md`

Include task breakdown by component and clear subagent assignments.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_34/implementation/progress-log.md`

```markdown
# Task 34 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Create implementation plan with context gathering
2. Build `test_runner.py` with frontmatter parsing
3. Add subprocess test execution with result capture
4. Implement accuracy calculation and update logic
5. Add frontmatter to discovery.md and test
6. Apply to all 6 prompt files
7. Update loader.py to handle frontmatter
8. Create developer documentation
9. Run comprehensive tests
10. Verify no user-facing changes

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Implementing frontmatter parser
Attempting to parse YAML frontmatter from markdown files...

Result: Discovered that yaml.safe_load() works perfectly
- ✅ What worked: Split on '---\n' boundaries
- ❌ What failed: Initial regex approach was too complex
- 💡 Insight: Simple string split is more maintainable

Code that worked:
```python
def parse_frontmatter(content):
    if content.startswith('---\n'):
        parts = content.split('---\n', 2)
        metadata = yaml.safe_load(parts[1])
        prompt = parts[2] if len(parts) > 2 else ""
        return metadata, prompt
    return {}, content
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: Use pytest API to run tests
- Why it failed: Too complex to extract results
- New approach: Use subprocess and parse output
- Lesson: Simple solutions often better than "proper" APIs
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**What to test for this task**:
- Frontmatter parsing with various formats
- Accuracy calculation from test results
- Update logic (only on improvement)
- Backward compatibility of prompt loading
- Edge cases (empty files, no frontmatter, malformed YAML)

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Testing revealed loader compatibility issue
Discovered that loader.py uses simple file.read_text().
Need to strip frontmatter before returning prompt content.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** create a complex framework or abstraction layer
- **DON'T** add this to the main pflow CLI
- **DON'T** track metrics beyond accuracy (no timing, tokens, cost)
- **DON'T** implement regression detection or alerts
- **DON'T** integrate with CI/CD systems
- **DON'T** create multiple Python files - one script only
- **DON'T** modify how prompts work, only add tracking
- **DON'T** forget to set RUN_LLM_TESTS=1 environment variable

## Getting Started

1. Read the epistemic manifesto and all context files
2. Create your implementation plan with context gathering
3. Start with `test_runner.py` basic structure
4. Test with discovery.md first before applying to all prompts
5. Run frequently: `python test_runner.py discovery`

## Final Notes

- The user wants to see "accuracy: 85.0%" and think "I can beat that"
- This emotional feedback loop is the core value - preserve it
- Git commits showing "Improved discovery: 85% → 90%" are progress markers
- Keep the tool simple enough that any developer can understand it in 5 minutes
- The prompts were just refactored to markdown - this is fresh work

## Remember

You're building a tool that enables rapid prompt improvement through immediate visibility of test accuracy. The design prioritizes developer experience over engineering perfection. A developer should open a prompt file, see the current accuracy, make changes, test, and feel satisfaction when the number goes up. That emotional feedback loop drives continuous improvement.

This is not about building infrastructure - it's about making prompt improvement addictive through instant feedback. Keep it simple, make it work, help developers achieve 100% accuracy one prompt at a time. Think hard!