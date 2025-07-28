# Task 21 Dependencies & Notes

## Dependencies

### Required Before Starting
- Task 20 (WorkflowNode) should be implemented or at least IR schema should be stable
- Understanding of current template validation system
- Familiarity with Pydantic schema validation

### This Task Enables
- Better Task 17 (Planner) integration - planner can know workflow requirements
- Future workflow discovery/documentation features
- Enhanced WorkflowNode validation capabilities
- Potential IDE/tooling support

## Relationship to Task 20 (WorkflowNode)

Task 20 implements the ability to execute workflows as nodes. Task 21 makes those workflows self-documenting by declaring their inputs. Together they enable:

1. **Without Task 21**: WorkflowNode works but users must guess child workflow parameters
2. **With Task 21**: WorkflowNode can validate param_mapping covers required inputs

## Implementation Notes

- Start simple - basic implementation first
- Focus on backward compatibility
- Don't over-engineer the type system
- Clear error messages are more important than complex validation

## Testing Considerations

Many of the tests will involve:
1. Creating workflows with various input configurations
2. Attempting to compile with different initial_params
3. Verifying validation behavior
4. Ensuring backward compatibility

Consider creating a test fixtures directory with sample workflows that have different input declaration patterns.
