# Task 35: Migrate Template Syntax from $variable to ${variable}

## ID
35

## Title
Migrate Template Syntax from $variable to ${variable}

## Description
Change the template variable syntax from `$variable` to `${variable}` to provide explicit boundaries, eliminate parsing ambiguities, and align with industry standards. This will solve issues with variables adjacent to underscores, periods, and other characters that currently require awkward workarounds.

## Status
in progress

## Dependencies
None
<!-- This is a standalone change to the template system. While it affects multiple components, it doesn't depend on other tasks being completed first. -->

## Priority
medium

## Details
The current template syntax `$variable` has several problems that make it difficult to use in real-world scenarios:

### Current Problems
1. **Ambiguous boundaries** - The parser cannot reliably determine where a variable name ends
   - `$week_number_report.md` - Is it `week_number_report` or `week_number`?
   - `$var.md` - Required complex regex fixes to handle period as punctuation
   - Variables before underscores or within filenames cause parsing errors

2. **Complex regex pattern** - Current pattern uses complex lookaheads/lookbehinds that are fragile:
   ```python
   (?<!\$)\$([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)(?=\s|$|[^\w])
   ```

3. **Forces unnatural naming** - Users must use hyphens or rearrange text to avoid parsing errors:
   - `reports/week_$week_number-report.md` (ugly workaround)
   - `reports/week-$week_number.md` (would fail)

### Proposed Solution
Adopt `${variable}` syntax with explicit boundaries, similar to bash, JavaScript, Docker, and other tools:
- `reports/week_${week_number}_report.md` - Works perfectly
- `data_${timestamp}.backup.json` - Clear boundaries
- `${user}-${date}.log` - No ambiguity

### Implementation Changes Required

#### Core Components (6 files)
1. **template_resolver.py** - Update regex pattern and replacement logic at specific lines
2. **template_validator.py** - Update validation pattern and error messages at specific lines
3. **planning/prompts/workflow_generator.md** - Update ALL examples for LLM generation (12+ examples)
4. **planning/nodes.py** - Update error suggestions at lines 1123, 1125
5. **planning/context_builder.py** - Update template examples
6. **planning/prompts/README.md** - Update example at line 24

#### Test Updates (50+ files)
- All test files with template assertions need updating
- Core test files: test_template_resolver.py, test_template_validator.py
- Integration tests with template usage

#### Documentation Updates (230+ occurrences)
- CLI reference examples
- Core concepts documentation
- Architecture documentation
- Example JSON workflows in examples/ directory

### New Regex Pattern
The new pattern will be simpler and more robust:
```python
TEMPLATE_PATTERN = re.compile(r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}")
```

Benefits:
- Simpler than current pattern but keeps negative lookbehind for escape sequences
- Supports hyphens in variable names: `${user-id}`
- Unambiguous start `${` and end `}`
- Industry-standard syntax

### MVP Context
Since we're building an MVP with zero users:
- No backward compatibility needed
- No migration code required
- Clean slate approach - delete saved workflows in ~/.pflow/workflows/
- All existing workflows will be regenerated with new syntax

## Test Strategy
Comprehensive testing will ensure the new syntax works correctly across all components:

### Unit Tests
- **Template Resolver Tests**: Verify new regex pattern matches `${var}` syntax correctly
- **Path Variable Tests**: Ensure `${node.field}` and `${data.nested.value}` still work
- **Edge Case Tests**: Test variables with hyphens, underscores, and in various contexts
- **Validation Tests**: Ensure template validator correctly identifies valid/invalid syntax

### Integration Tests
- **Planner Generation**: Verify planner generates workflows with new syntax
- **Template Resolution**: End-to-end tests with actual workflow execution
- **Namespacing Compatibility**: Ensure templates work with namespace system
- **CLI Workflow Tests**: Test workflows with templates passed via CLI

### Test Data Updates
- Update all existing test workflows to use `${variable}` syntax
- Create new test cases for previously problematic patterns:
  - `file_${var}_backup.txt`
  - `${var1}_${var2}.json`
  - `path/to/${dir}/${file}.md`

### Verification Checklist
- [ ] All template variables resolve correctly
- [ ] Path traversal (`${node.field.subfield}`) works
- [ ] No regression in existing functionality
- [ ] Planner generates correct syntax
- [ ] Error messages show new syntax
- [ ] Documentation examples are correct