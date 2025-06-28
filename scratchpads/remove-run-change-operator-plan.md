# Comprehensive Plan: Remove `run` Subcommand and Change `>>` to `->`

## Overview
This plan details all changes needed to:
1. Remove the unnecessary `run` subcommand, enabling direct usage: `pflow node1 -> node2`
2. Change the flow operator from `>>` to `->` to avoid shell redirection conflicts

## Rationale
- The `run` subcommand was incorrectly added during task decomposition
- All documentation shows direct usage without subcommands
- The `>>` operator conflicts with shell output redirection, requiring quotes
- The `->` operator has no shell conflicts and is equally intuitive

## Impact Analysis

### Current State
```bash
# Current (incorrect)
pflow run node1 ">>" node2
pflow run --file workflow.txt
echo "node1 >> node2" | pflow run

# With version
pflow version
```

### Desired State
```bash
# Desired (matches docs)
pflow node1 -> node2
pflow --file workflow.txt
echo "node1 -> node2" | pflow
pflow "analyze this file"

# With version
pflow --version
```

## Detailed Changes Required

### 1. CLI Structure Changes

#### File: `src/pflow/cli/main.py`

**Current Structure:**
```python
@click.group()
def main() -> None:
    """pflow - workflow compiler for deterministic CLI commands."""
    pass

@main.command()
def version() -> None:
    """Show the pflow version."""
    click.echo("pflow version 0.0.1")

@main.command()
@click.pass_context
@click.option("--file", "-f", type=click.Path(exists=True), help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def run(ctx: click.Context, file: str | None, workflow: tuple[str, ...]) -> None:
    """Run a pflow workflow from command-line arguments, stdin, or file."""
    # ... implementation ...
```

**New Structure:**
```python
@click.command()
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--file", "-f", type=click.Path(exists=True), help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def main(ctx: click.Context, version: bool, file: str | None, workflow: tuple[str, ...]) -> None:
    """pflow - workflow compiler for deterministic CLI commands.

    Execute workflows using the -> operator to chain nodes:

    \b
    Examples:
      pflow read-file --path=input.txt -> llm --prompt="Summarize"
      pflow "analyze the Python files and find bugs"
      echo "read-file -> process" | pflow
      pflow --file=workflow.txt
    """
    if version:
        click.echo("pflow version 0.0.1")
        ctx.exit(0)

    # ... rest of the run implementation ...
```

### 2. Test Updates

#### File: `tests/test_cli.py`
- Update all tests that use `["version"]` to use `["--version"]`
- Remove any tests specific to the command group structure

#### File: `tests/test_cli_core.py`
- Remove all `"run"` from command invocations
- Update all instances of `>>` to `->`
- Update expected output messages

**Example changes:**
```python
# Before
result = runner.invoke(main, ["run", "node1", ">>", "node2"])

# After
result = runner.invoke(main, ["node1", "->", "node2"])
```

### 3. Documentation Updates

While we're not updating documentation in this task, we should note all files that would need updates in a real scenario:

**Files with `>>` operator references:**
- `/docs/reference/cli-reference.md` - Main CLI documentation
- `/docs/prd.md` - Product requirements
- `/docs/features/planner.md` - Planner documentation
- `/docs/architecture/architecture.md` - Architecture docs
- `/docs/core-concepts/schemas.md` - Schema examples
- `/docs/features/mvp-scope.md` - MVP examples
- Many more...

**Note:** Since documentation updates are out of scope, we'll focus only on code changes.

### 4. Error Messages and Help Text

All error messages and help text in the code need to be updated to:
- Remove references to the `run` command
- Change `>>` to `->` in examples

### 5. Future Considerations

#### Planner Integration
When the planner is implemented, it will need to:
- Generate flows with `->` instead of `>>`
- Parse CLI syntax with `->` operator

#### Parser Logic
Any future parsing logic looking for flow operators needs to search for `->` instead of `>>`

## Implementation Steps

### Phase 1: Core CLI Changes
1. Backup current implementation
2. Restructure `main.py` to remove command group
3. Move `run` logic into `main`
4. Add `--version` flag
5. Update help text and examples

### Phase 2: Test Updates
1. Update `test_cli.py` for new structure
2. Update `test_cli_core.py` to remove "run" from all invocations
3. Replace all `>>` with `->` in tests
4. Update expected output messages
5. Run tests incrementally to ensure each change works

### Phase 3: Validation
1. Test all three input modes (args, stdin, file)
2. Verify --version flag works
3. Test error cases
4. Ensure -> operator works without quotes
5. Full test suite execution

## Migration Notes

### For Users
If this were a released product, we'd need to:
1. Announce the breaking change
2. Provide migration guide
3. Update all documentation
4. Consider supporting both operators temporarily

### For Developers
- All workflow files using `>>` need to change to `->`
- Any scripts invoking `pflow run` need updates
- Shell aliases may need updates

## Testing Checklist

### Manual Testing Commands
```bash
# Basic flow
pflow read-file --path=input.txt -> llm --prompt="Summarize"

# Natural language
pflow "analyze this codebase"

# Stdin
echo "read-file -> process" | pflow

# File input
pflow --file=workflow.txt

# Version
pflow --version

# Help
pflow --help

# Errors
pflow --file=nonexistent.txt
pflow -> invalid
```

### Automated Test Coverage
- [ ] All existing tests pass with modifications
- [ ] No "run" command references remain
- [ ] No ">>" operator references remain
- [ ] Version flag works correctly
- [ ] Help text is accurate
- [ ] Error messages are updated

## Risks and Mitigations

### Risk 1: Missing Updates
**Risk:** Some instances of "run" or ">>" might be missed
**Mitigation:** Use comprehensive grep searches before and after

### Risk 2: Breaking Changes
**Risk:** This is a breaking change from current implementation
**Mitigation:** Since we're pre-release, this is acceptable

### Risk 3: Documentation Drift
**Risk:** Code will not match documentation that uses ">>"
**Mitigation:** Note this as technical debt for documentation update

## Success Criteria

1. `pflow node1 -> node2` works without quotes
2. All three input modes work (args, stdin, file)
3. No references to "run" subcommand in code
4. No references to ">>" operator in code
5. All tests pass
6. Help text accurately reflects new usage

## Rollback Plan

If issues arise:
1. Git revert to previous commit
2. Re-run tests to ensure stability
3. Analyze what went wrong
4. Create more incremental plan

## Future Enhancements

After this change:
1. Update all documentation (separate task)
2. Implement natural language planner with -> operator
3. Add shell completion for -> operator
4. Consider supporting multiple operators (->>, =>, etc.)
