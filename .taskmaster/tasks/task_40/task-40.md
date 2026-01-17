# Task 40: Consolidate Workflow Validation into Unified System

## Description
Create a unified workflow validation system that ensures production has the same (or better) validation capabilities than tests. This consolidation addresses a critical gap where tests had data flow validation that production lacked, which could lead to workflows passing validation but failing at runtime.

## Status
done

## Completed
2025-08-24

## Dependencies
- Task 6: Define JSON IR schema - The validation system validates against the defined IR schema
- Task 17: Implement Natural Language Planner System - ValidatorNode is a key component that needs to use the unified validation

## Priority
high

## Details
This task consolidates all workflow validation logic into a single, reusable system that serves as the source of truth for both production and tests. Previously, validation logic was scattered across multiple components with tests having better validation than production, creating a dangerous gap.

### The Problem
- ValidatorNode had custom validation methods
- Tests had their own validation functions including data flow validation
- Data flow validation (execution order, circular dependencies) only existed in tests
- This could lead to workflows passing production validation but failing at runtime

### The Solution
Created a unified `WorkflowValidator` class that orchestrates all validation:
1. **Structural validation** - IR schema compliance (via existing `validate_ir`)
2. **Data flow validation** - Execution order and dependencies (NEW - extracted from tests)
3. **Template validation** - Variable resolution (via existing `TemplateValidator`)
4. **Node type validation** - Registry verification

### Key Components
- `src/pflow/core/workflow_data_flow.py` - Validates execution order and data dependencies
- `src/pflow/core/workflow_validator.py` - Unified validation orchestrator
- Modified `ValidatorNode` to use `WorkflowValidator` instead of custom methods
- Updated tests to use production validation instead of custom logic

### Implementation Approach
1. Created new modules without breaking existing code
2. Added shadow mode to ValidatorNode for gradual migration
3. Incrementally migrated to new system with feature flags
4. Removed old validation code only after confirming no regression

### Critical Design Decisions
- Single source of truth eliminates duplication and inconsistencies
- Data flow validation now runs in production, catching issues before runtime
- Maintained exact same interfaces to ensure zero breaking changes
- Used Kahn's algorithm for topological sort to determine execution order

## Test Strategy
Comprehensive testing ensures the new validation system maintains all existing functionality while adding new capabilities:

### New Test Coverage
- Unit tests for `workflow_data_flow.py` validating:
  - Forward reference detection
  - Circular dependency detection
  - Undefined input parameter detection
  - Topological sorting algorithm

- Unit tests for `WorkflowValidator` class:
  - All validation types run correctly
  - Selective validation skipping for mock nodes
  - Error accumulation from all validators

### Integration Testing
- ValidatorNode tests with data flow validation enabled/disabled
- Tests that ValidatorNode catches issues that were previously only caught in tests
- Full planner integration tests to ensure no regression

### Regression Testing
- All existing tests must pass without modification
- Maintained test compatibility through careful interface preservation
- Performance benchmarks to ensure <100ms impact
