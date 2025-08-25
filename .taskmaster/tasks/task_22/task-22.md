# Task 43: Implement named workflow execution

## Description
Enable execution of saved workflows by name with parameters

## Status
pending

## Dependencies
- Task 17
- Task 21

## Priority
high

## Details
Extend CLI to support executing saved workflows by name: 'pflow fix-issue --issue=1234'. Create src/pflow/cli/execute.py with execute_named_workflow(name, params) function. Load workflow from ~/.pflow/workflows/<name>.json, validate against lockfile, apply runtime parameters to template variables, execute via IR compiler. This is the core user-facing command that delivers the 'Plan Once, Run Forever' value. Support parameter override and validation. Include helpful error messages for missing workflows or parameters. Reference docs: mvp-scope.md, cli-reference.md

## Test Strategy
Test workflow loading, parameter application, execution flow. Test error cases and parameter validation.