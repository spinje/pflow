# Refined Specification for Subtask 6.3

## Clear Objective
Create comprehensive examples and enhance documentation for the JSON IR schema to help users understand and effectively use pflow's workflow representation format.

## Context from Knowledge Base
- Building on: Completed schema and validation from subtasks 6.1/6.2
- Avoiding: Over-engineering for MVP, duplication of test cases
- Following: Test-as-you-go pattern, clear error message philosophy
- **Cookbook patterns to apply**: pocketflow-flow (action routing), pocketflow-workflow (pipelines), pocketflow-text2sql (error handling)

## Technical Specification

### Documentation Enhancements

1. **Module Docstring Updates**:
   - Enhance existing docstring without removing current examples
   - Add section explaining design decisions (why 'type' not 'registry_id')
   - Include more complex example showing edges and template variables
   - Add section on common errors and their messages

2. **Function Docstring Enhancements**:
   - `validate_ir()`: Add more examples showing error cases
   - `ValidationError`: Document all attributes and usage
   - Helper functions: Ensure all have clear docstrings

### Example Files to Create

#### Core Examples (MVP Priority):
1. **examples/core/minimal.json**
   - Single node, no edges
   - Demonstrates absolute minimum valid IR

2. **examples/core/simple-pipeline.json**
   - 3-node sequential flow (read → transform → write)
   - Shows basic edge connections

3. **examples/core/template-variables.json**
   - Demonstrates $variable syntax in params
   - Shows variable flow through workflow

4. **examples/core/error-handling.json**
   - Try-catch pattern with action-based routing
   - Shows "error" action and fallback paths

5. **examples/core/proxy-mappings.json**
   - NodeAwareSharedStore proxy pattern
   - Input/output key transformations

#### Advanced Examples:
6. **examples/advanced/github-workflow.json**
   - Real-world GitHub issue automation
   - Complex template variables and conditions

7. **examples/advanced/content-pipeline.json**
   - Multi-stage content generation
   - Shows data flow through shared store

### Documentation Files to Create

1. **examples/README.md**
   - Index of all examples
   - Quick start guide
   - How to validate examples
   - Common patterns explained

2. **examples/core/[example].md** (for each core example)
   - Purpose and use case
   - Visual flow diagram (ASCII)
   - Node-by-node explanation
   - How to run/test
   - Common variations

### Invalid Examples for Testing

Create **examples/invalid/** directory with:
- `missing-version.json` - No ir_version field
- `duplicate-ids.json` - Nodes with same ID
- `bad-edge-ref.json` - Edge references non-existent node
- `wrong-types.json` - Invalid field types

Each with corresponding `.md` file showing expected error message.

## Success Criteria
- [ ] Module docstring enhanced with design rationale
- [ ] All functions have comprehensive docstrings
- [ ] 5 core example JSON files created and validated
- [ ] 2 advanced example JSON files created and validated
- [ ] 4 invalid example files with expected errors documented
- [ ] README.md ties everything together
- [ ] All examples pass validation when valid
- [ ] All invalid examples produce expected errors
- [ ] Examples demonstrate all IR features (templates, mappings, actions)

## Test Strategy
- Create test file `tests/test_ir_examples.py` to validate all examples
- Ensure valid examples pass `validate_ir()`
- Ensure invalid examples raise expected `ValidationError`
- Test that all JSON files are valid JSON syntax
- Verify documentation code snippets are accurate

## Dependencies
- Requires: Completed IR schema and validation (done)
- Impacts: Will help Task 4 (IR-to-Flow converter) with examples
- Impacts: Will help Task 17 (Planner) understand target format

## Decisions Made
- **Enhance existing + create new**: Keep basic examples in module, comprehensive ones separate
- **Focus on quality over quantity**: 5-7 solid examples rather than many poor ones
- **Test all examples**: Every example must be validated
- **Real-world focus**: Examples should reflect actual pflow use cases
