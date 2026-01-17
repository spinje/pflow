# Task 33: Extract Planner Prompts to Markdown Files

## Description
Extract all inline prompts from the planning nodes to standalone markdown files in `src/pflow/planning/prompts/`, making them reviewable, maintainable, and testable. Create a simple loader that reads prompts from markdown files and formats them with variables, establishing patterns for prompt externalization with automatic validation.

## Status
done

## Completed
2025-08-15

## Dependencies
- Task 17: Natural Language Planner System - The planner nodes contain the inline prompts that need extraction
- Task 31: Refactor Test Infrastructure - Tests need to work with the new external prompt structure

## Priority
medium

## Details
The planning system had all prompts hardcoded as f-strings inside Python node classes, making them difficult to review, test, or modify. This task externalizes all prompts to markdown files while maintaining full functionality and adding validation to prevent template/code mismatches.

### Core Problems Being Solved
1. **Hidden Prompts**: Prompts buried in Python code are hard to review and optimize
2. **Difficult Testing**: Can't test prompts without running full planner
3. **No Validation**: Missing variables in templates go unnoticed until runtime
4. **Poor Maintainability**: Editing prompts requires understanding Python code structure
5. **Mixed Concerns**: Prompt logic mixed with execution logic

### Implementation Requirements
Created the following structure in `src/pflow/planning/prompts/`:
- `loader.py`: Simple functions to load and format prompts with bidirectional validation
- `discovery.md`: WorkflowDiscoveryNode prompt
- `component_browsing.md`: ComponentBrowsingNode prompt
- `parameter_discovery.md`: ParameterDiscoveryNode prompt with XML structure
- `parameter_mapping.md`: ParameterMappingNode prompt with XML structure
- `metadata_generation.md`: MetadataGenerationNode prompt with XML structure
- `workflow_generator.md`: WorkflowGeneratorNode prompt (most complex) with XML structure

### Loader Implementation
The loader (`src/pflow/planning/prompts/loader.py`) provides:
- `load_prompt(prompt_name: str) -> str`: Load a prompt from markdown file
- `format_prompt(template: str, variables: dict) -> str`: Format with bidirectional validation
- `extract_variables(template: str) -> set[str]`: Extract variable names from template

### Bidirectional Validation
The key innovation is automatic validation that ensures:
1. **All variables provided by code exist in template** - Catches when someone forgets `{{variable}}` in .md file
2. **All variables in template are provided by code** - Catches missing variables in Python code
3. **Clear error messages** - Shows exactly what's missing for easy debugging

### Prompt Format Evolution
Started with simple format but evolved to XML structure for better LLM parsing:

**Initial Pattern (Simple)**:
```markdown
You are a system that...

Available data:
{{context}}

User request: {{user_input}}
```

**Improved Pattern (XML Structure)**:
```markdown
You are a system that...

<available_data>
{{context}}
</available_data>

<user_request>
{{user_input}}
</user_request>

<optional_section>
{{optional_data}}
</optional_section>
```

### Key Design Decisions
- **Full Structure in Markdown**: All sections visible, even if sometimes empty
- **XML Tags for Structure**: Better prompt engineering practice for LLM parsing
- **"None" for Empty Values**: Clear signal to LLM when data unavailable
- **Python Only Formats Values**: Structure stays in markdown, Python just provides data
- **Header Skipping**: Automatically skip `# Title` headers in markdown files
- **Simple String Replacement**: Used `{{variable}}` syntax instead of complex templating

### Complex Prompt Handling
For prompts with dynamic sections (like WorkflowGeneratorNode):
- Base prompt fully in markdown with placeholders
- Dynamic sections built in Python (complex formatting logic)
- Pass formatted sections as variables
- All sections visible in template, use "None" when empty

### Test Fix Journey
Discovered that changing prompt structure broke integration tests due to mock detection:
1. **Initial Issue**: Tests failed with KeyError on 'parameters'
2. **Overengineered Fix**: Changed test fixtures unnecessarily
3. **Root Cause**: Mock detected "select" in XML tag `<selected_components>`
4. **Minimal Fix**: Changed mock condition from `"select"` to `"select all nodes"`
5. **Lesson**: Debug first, fix minimally

## Test Strategy

### Unit Tests (`test_prompt_loader.py`)
Created comprehensive tests for the loader:
- Normal operation with matching variables
- Missing variable in template detection
- Missing variable in code detection
- Typo in variable names
- Variable extraction from templates
- Empty template handling

### Integration Tests
All existing planning tests (311 tests) pass with external prompts:
- Discovery routing tests
- Component browsing tests
- Parameter extraction tests
- Workflow generation tests
- Metadata generation tests
- Full planner flow tests

### Validation Tests
Bidirectional validation ensures:
- Template changes that remove variables are caught
- Code changes that miss variables are caught
- Clear error messages guide fixes

## Implementation Highlights

### Files Created
- 6 prompt markdown files with XML structure
- 1 loader module with validation
- 1 comprehensive test file for loader
- Multiple planning documents in scratchpads

### Files Modified
- `src/pflow/planning/nodes.py`: All 6 nodes updated to use external prompts
- `tests/test_planning/integration/test_discovery_to_parameter_flow.py`: One-line fix for mock

### Patterns Established
1. **Simple prompts**: Use `{{variable}}` placeholders
2. **Complex prompts**: Use XML tags with all sections visible
3. **Dynamic content**: Pass as variables, use "None" for empty
4. **Validation**: Automatic bidirectional checking prevents mismatches

### Benefits Achieved
- **Reviewable**: All prompts visible in standalone files
- **Maintainable**: Edit prompts without touching Python
- **Testable**: Can test prompts in isolation
- **Validated**: Automatic checking prevents errors
- **Clean**: Separation of static content and dynamic logic

## Metrics
- **Prompts Extracted**: 6 (all planning nodes)
- **Lines of Prompts Moved**: ~400 lines
- **Tests Added**: 7 loader tests
- **Tests Passing**: 311 planning tests, 1217 total tests
- **Code Quality**: All checks pass (mypy, ruff, deptry)
- **Fix Complexity**: 1 line changed to fix test failures

## Future Opportunities
- Add prompt versioning for A/B testing
- Create prompt testing framework for quality validation
