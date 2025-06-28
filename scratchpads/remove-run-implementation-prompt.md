# Implementation Prompt: Remove `run` Subcommand and Change Operator

## Context
The current pflow implementation incorrectly uses a `run` subcommand (`pflow run node1 >> node2`), but all documentation shows direct usage (`pflow node1 >> node2`). Additionally, the `>>` operator conflicts with shell output redirection, requiring users to quote it.

## Task
Refactor the pflow CLI to:
1. Remove the `run` subcommand, allowing direct workflow execution
2. Change the flow operator from `>>` to `->` to avoid shell conflicts

## Current State
```bash
# What we have (incorrect)
pflow run node1 ">>" node2
pflow version

# What we want (matches docs)
pflow node1 -> node2
pflow --version
```

## Implementation Instructions

Please implement the changes described in the comprehensive plan at:
`/Users/andfal/projects/pflow/scratchpads/remove-run-change-operator-plan.md`

### Key Changes:
1. **Restructure CLI** (`src/pflow/cli/main.py`):
   - Change from `@click.group()` to `@click.command()`
   - Move all `run` command logic into `main`
   - Add `--version` flag instead of version subcommand
   - Update help text to show `->` examples

2. **Update Tests**:
   - Remove "run" from all test invocations in `tests/test_cli_core.py`
   - Change all `>>` to `->` in test files
   - Update `tests/test_cli.py` for `--version` flag

3. **Preserve Functionality**:
   - Keep all three input modes (args, stdin, file)
   - Maintain context storage in `ctx.obj`
   - Ensure error handling remains intact

### Important Notes:
- Do NOT update documentation files (only code and tests)
- The `->` operator should work without quotes
- All existing tests should pass after modifications
- Preserve the type annotations and error messages

### Testing:
After implementation, verify:
```bash
# These should all work
pflow read-file --path=input.txt -> llm --prompt="Summarize"
echo "read-file -> process" | pflow
pflow --file=workflow.txt
pflow --version
```

### Success Criteria:
1. No references to "run" subcommand remain in code
2. No references to ">>" operator remain in code
3. All tests pass with new structure
4. Direct workflow execution works: `pflow node1 -> node2`
5. The -> operator works without needing quotes

Please follow the detailed plan and implement these changes carefully, ensuring all tests pass and functionality is preserved.
