# Implementation Plan for Subtask 6.3

## Objective
Create comprehensive examples and enhance documentation for the JSON IR schema to help users understand and effectively use pflow's workflow representation format.

## Implementation Steps

1. [ ] Enhance module docstring in ir_schema.py
   - File: src/pflow/core/ir_schema.py
   - Change: Add design decisions section, complex example, common errors
   - Test: Visual inspection, docstring renders correctly

2. [ ] Enhance function docstrings
   - File: src/pflow/core/ir_schema.py
   - Change: Add error examples to validate_ir(), document ValidationError attributes
   - Test: Docstrings complete and accurate

3. [ ] Create examples directory structure
   - File: examples/ (new directory)
   - Change: Create core/, advanced/, invalid/ subdirectories
   - Test: Directory structure exists

4. [ ] Create core example: minimal.json
   - File: examples/core/minimal.json
   - Change: Single node IR example
   - Test: Validates with validate_ir()

5. [ ] Create core example: simple-pipeline.json
   - File: examples/core/simple-pipeline.json
   - Change: 3-node sequential flow
   - Test: Validates with validate_ir()

6. [ ] Create core example: template-variables.json
   - File: examples/core/template-variables.json
   - Change: Demonstrates $variable syntax
   - Test: Validates with validate_ir()

7. [ ] Create core example: error-handling.json
   - File: examples/core/error-handling.json
   - Change: Action-based error routing
   - Test: Validates with validate_ir()

8. [ ] Create core example: proxy-mappings.json
   - File: examples/core/proxy-mappings.json
   - Change: NodeAwareSharedStore mappings
   - Test: Validates with validate_ir()

9. [ ] Create documentation for core examples
   - File: examples/core/[example].md for each
   - Change: Purpose, diagram, explanation
   - Test: Clear and helpful

10. [ ] Create advanced example: github-workflow.json
    - File: examples/advanced/github-workflow.json
    - Change: Real-world GitHub automation
    - Test: Validates with validate_ir()

11. [ ] Create advanced example: content-pipeline.json
    - File: examples/advanced/content-pipeline.json
    - Change: Multi-stage content generation
    - Test: Validates with validate_ir()

12. [ ] Create invalid examples
    - File: examples/invalid/*.json
    - Change: 4 invalid examples with different errors
    - Test: Each produces expected ValidationError

13. [ ] Create invalid example documentation
    - File: examples/invalid/*.md
    - Change: Expected error for each invalid example
    - Test: Errors match documentation

14. [ ] Create examples README
    - File: examples/README.md
    - Change: Index, quick start, patterns guide
    - Test: Comprehensive and navigable

15. [ ] Create test file for examples
    - File: tests/test_ir_examples.py
    - Change: Automated validation of all examples
    - Test: All tests pass

## Pattern Applications

### Cookbook Patterns
- **pocketflow-flow**: Adapt interactive flow pattern for error-handling.json
  - Specific code/approach: Action-based routing with multiple paths
  - Modifications needed: Simplify to show just error paths, not full interaction

- **pocketflow-workflow**: Use for content-pipeline.json
  - Specific code/approach: Sequential node execution pattern
  - Modifications needed: Show as IR rather than Python code

- **pocketflow-text2sql**: Inform error-handling.json design
  - Specific code/approach: Retry loop with error action
  - Modifications needed: Generalize beyond SQL to any error scenario

### Previous Task Patterns
- Using Test-As-You-Go from subtask 6.1 - create test_ir_examples.py immediately
- Following Clear Error Messages pattern - document expected errors clearly
- Avoiding Boolean confusion - ensure JSON examples use proper JSON syntax

## Risk Mitigations
- **Risk**: Examples don't reflect real use cases
  - **Mitigation**: Base on documented workflows from planner.md and workflow-analysis.md

- **Risk**: Documentation becomes stale
  - **Mitigation**: Test all examples automatically, include in CI

- **Risk**: Too many examples overwhelm users
  - **Mitigation**: Clear organization, start with minimal, progress to complex
