# Workflow Generator Test Failure Analysis

## Current Performance: 61.5% (8/13 passed)

### Failed Tests Analysis

#### 1. `output_mapping_fix` ❌
**Issue**: Declared but unused inputs: {'output_path'}
**Root Cause**: The prompt doesn't emphasize strongly enough that ALL declared inputs MUST be used as template variables
**Fix Needed**: Strengthen the requirement that every input must be used

#### 2. `fix_validation_errors` ❌
**Issues**:
- Missing required input: repository
- Should not declare 'output_file' as input (it's node output)
**Root Cause**: The validation error handling section needs clearer instructions on:
- Adding missing inputs based on template variable errors
- Removing unused inputs based on "never used" errors
**Fix Needed**: Better validation error recovery instructions

#### 3. `comprehensive_documentation_generator` ❌
**Issues**:
- Too few nodes: 6 < 8
- Missing required input: docs_output
**Root Cause**: Complex workflows with many steps aren't being fully generated
**Fix Needed**: Emphasize breaking down complex requests into all necessary steps

#### 4. `data_analysis_pipeline` ❌
**Issue**: Too few nodes: 4 < 5
**Root Cause**: Multiple outputs (report AND visualization) not being handled separately
**Fix Needed**: Clarify that each output typically needs its own write-file node

#### 5. `full_release_pipeline` ❌
**Issue**: Too many nodes: 14 > 12
**Root Cause**: Over-generation for ultra-complex workflows
**Fix Needed**: Balance between completeness and efficiency

### Passed Tests ✅
- `complex_data_flow` - Correctly handled node outputs as data source
- `parameter_vs_output` - Distinguished user inputs from node outputs
- `changelog_pipeline` - Generated proper 6-node workflow
- `content_generation_trap` - Avoided declaring "content" as input
- `release_automation` - Handled 4-5 node workflow well
- `migration_workflow` - Proper sequencing of critical operations
- `multi_output_workflow` - Generated multiple write operations
- `multi_source_weekly_report` - Combined multiple data sources

## Key Patterns in Failures

1. **Validation Error Recovery** - Not parsing and fixing errors correctly
2. **Input Declaration Issues** - Unused inputs or missing required inputs
3. **Node Count** - Either too few (missing steps) or too many (over-generating)
4. **Complex Workflow Breakdown** - Not fully decomposing complex requests

## Prompt Improvements Needed

### Priority 1: Strengthen Input Requirements
- Every declared input MUST be used
- Parse template variable errors to add missing inputs
- Remove inputs mentioned in "never used" errors

### Priority 2: Better Step Decomposition
- Complex requests need ALL steps generated
- Each distinct output typically needs its own write operation
- 8-10 node workflows are normal for complex tasks

### Priority 3: Improve Validation Recovery
- Clearer parsing of specific error types
- Step-by-step fix instructions
- Examples of common error fixes

### Priority 4: Clarify Output Handling
- Multiple outputs need multiple write nodes
- Each analysis/generation typically produces separate output

## Target Areas for Prompt Enhancement

1. **CRITICAL Requirements** section - Make input usage absolutely clear
2. **Validation Errors** section - Add specific fix patterns
3. **Complex Workflows** section - Guide on breaking down into steps
4. **Examples** - Add a complex 8+ node example