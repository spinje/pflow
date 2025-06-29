# Knowledge Synthesis for Subtask 6.3

## Relevant Patterns from Previous Tasks

- **Test-As-You-Go Development**: [Used in subtask 6.1] - Examples should be created alongside documentation, tested immediately
- **Clear Error Messages**: [Used in subtask 6.1] - ValidationError provides path and suggestions, examples should demonstrate this
- **Comprehensive Test Organization**: [Used in subtask 6.1] - Tests organized by concern (valid/invalid/errors/edge cases)
- **Graceful JSON Configuration Loading**: [From patterns.md] - Examples should show proper JSON error handling

## Known Pitfalls to Avoid

- **Boolean Value Confusion**: [From subtask 6.1] - Ensure examples use proper Python boolean values in code
- **Incomplete Documentation**: [General principle] - Module already has basic docstring, need to enhance without duplication
- **Unrealistic Examples**: [General principle] - Examples should reflect real pflow use cases

## Established Conventions

- **Module Structure**: [From subtask 6.1] - ir_schema.py contains schema, validation, and error handling
- **Schema Design**: [From subtask 6.1] - Uses 'type' field (not 'registry_id'), nodes as array with 'id' field
- **Import Pattern**: [From subtask 6.1] - `from pflow.core import validate_ir`
- **Error Format**: [From subtask 6.1] - User-friendly paths like "nodes[0].type"

## Codebase Evolution Context

- **Schema Implemented**: [Subtask 6.1] - FLOW_IR_SCHEMA defines the structure
- **Validation Complete**: [Subtask 6.1/6.2] - validate_ir() with custom business logic
- **Basic Examples Exist**: [Subtask 6.1] - Module docstring has minimal valid/invalid examples
- **Tests Show Patterns**: [Subtask 6.1] - 29 test cases demonstrate various IR structures

## Key Insights from Previous Subtasks

1. **Documentation Already Started**: The module has a basic docstring with simple examples
2. **Tests as Documentation**: The test file contains many IR examples that could inform documentation
3. **Real Use Cases Needed**: Current examples are minimal - need realistic workflow examples
4. **Template Variables**: Tests show template variable support ($variable) already works
5. **Mappings Examples**: Tests include mapping examples but documentation could be clearer

## Documentation Gaps to Fill

1. **Complex Workflow Examples**: Multi-node workflows with edges and actions
2. **Template Variable Usage**: Clear examples of $variable syntax in params
3. **Mapping Pattern Examples**: When and how to use proxy mappings
4. **Error Message Examples**: What users see for common mistakes
5. **Integration Examples**: How IR connects to planner output and converter input
