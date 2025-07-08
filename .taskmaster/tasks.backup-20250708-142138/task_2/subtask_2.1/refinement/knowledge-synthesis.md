# Knowledge Synthesis for Subtask 2.1

## Relevant Patterns from Previous Tasks

### Click CLI Architecture Pattern
- **Pattern**: Use @click.group() with modular command structure for extensibility
- **Where it was used**: Task 1 - main.py implementation
- **Why it's relevant**: We're adding a new subcommand to the existing click.group()
- **Key learning**: Commands are added as `@main.command()` decorators on functions

### Module Structure Pattern
- **Pattern**: Separate __init__.py and main.py files for clean separation
- **Where it was used**: Task 1 - src/pflow/cli/ structure
- **Why it's relevant**: We're modifying the existing main.py file
- **Application**: Add our 'run' command in main.py alongside existing version command

### Testing Strategy Pattern
- **Pattern**: Use click.testing.CliRunner for all CLI tests
- **Where it was used**: Task 1 - tests/test_cli.py
- **Why it's relevant**: We need to test the new 'run' command
- **Application**: Create tests in tests/test_cli_core.py as specified

## Known Pitfalls to Avoid

### Click Exit Code Pitfall
- **Pitfall**: click.group() returns exit code 2 when no command provided
- **Where it failed**: Task 1 testing initially expected code 0
- **How to avoid**: Expect correct exit codes in tests (2 for no command, 0 for success)

### Package Manager Pitfall
- **Pitfall**: Using pip instead of uv pip
- **Where it failed**: Task 1 noted project uses uv package manager
- **How to avoid**: Always use `uv pip` commands, not plain `pip`

### Path Pitfall
- **Pitfall**: Expecting pflow command in PATH without venv activation
- **Where it failed**: Task 1 manual testing
- **How to avoid**: Use .venv/bin/pflow or activate venv for testing

## Established Conventions

### CLI Command Naming Convention
- **Convention**: Commands use kebab-case (e.g., 'read-file')
- **Where decided**: Project context and Task 1 patterns
- **Must follow**: Name our command 'run' as specified (single word, lowercase)

### Docstring Convention
- **Convention**: Each command has a clear docstring explaining its purpose
- **Where decided**: Task 1 main.py implementation
- **Must follow**: Add descriptive docstring to the 'run' command

### Import Convention
- **Convention**: Clean __init__.py exports with __all__ declaration
- **Where decided**: Task 1 implementation
- **Must follow**: No changes needed to __init__.py for this task

## Codebase Evolution Context

### CLI Foundation Established
- **What changed**: Task 1 created basic CLI structure with click.group()
- **When**: Completed before this task
- **Impact on this task**: We have a working foundation to build upon

### Entry Point Configured
- **What changed**: pyproject.toml has pflow entry point configured
- **When**: Task 1.1
- **Impact on this task**: No changes needed to pyproject.toml

### Test Framework Setup
- **What changed**: tests/test_cli.py created with CliRunner pattern
- **When**: Task 1.3
- **Impact on this task**: We'll create tests/test_cli_core.py following same pattern

## Key Insights for Implementation

1. **Existing Structure**: The click.group() is already set up in main.py, we just need to add a new command
2. **Argument Collection**: Use click's `nargs=-1` to collect all arguments as a tuple
3. **Raw Preservation**: Join arguments to preserve special operators like `>>`
4. **Temporary Output**: Print collected args for development verification
5. **Test Location**: Create new test file as specified, don't modify existing test_cli.py
