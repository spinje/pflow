# Knowledge Synthesis for Subtask 2.3

## Relevant Patterns from Previous Tasks

### CLI Testing Patterns
- **CliRunner for all tests**: Task 1.3 established using click.testing.CliRunner - Mandatory for consistency
- **Exit code handling**: Task 1.3 discovered click.group() returns exit code 2 without commands - Important for error testing
- **Context storage testing**: Task 2.2 showed how to test ctx.obj storage - May be relevant for error context

### Click Framework Patterns
- **@click.group() architecture**: Task 1.2 established modular command structure - Foundation for all CLI work
- **Direct command execution**: Task 2.2 removed 'run' subcommand - Must follow this simpler pattern
- **click.UNPROCESSED type**: Task 2.1 used for raw argument collection - Preserves special characters

### Input Handling Patterns
- **Empty stdin detection**: Task 2.2 discovered CliRunner behavior issue - Check content, not just tty status
- **Mutually exclusive validation**: Task 2.2 implemented clear error messages - Good UX pattern to follow
- **-- separator for flags**: Task 2.1 discovered this Unix standard - Must be documented in help text

## Known Pitfalls to Avoid

### Click-specific Pitfalls
- **Option parsing conflict**: Task 2.1 found Click parses --flags unless -- separator used - Critical for help text
- **Direct flag parsing**: Click treats --options as its own unless separated - Must educate users
- **CliRunner stdin simulation**: Task 2.2 found it provides non-tty stdin even when empty - Test edge cases

### Documentation Pitfalls
- **Assuming vs verifying**: Task 2.2 found 'run' subcommand was incorrectly added in decomposition - Always verify against docs
- **Operator conflicts**: Task 2.2 tested multiple operators (>>, >>>, ->) and found conflicts - Use => operator consistently

## Established Conventions

### Code Organization
- **Module structure**: Task 1 established __init__.py + main.py pattern - Must maintain consistency
- **Type annotations**: Task 2.1 found they're mandatory for mypy - All functions need type hints
- **Import organization**: Minimal exports in __init__.py - Keep it clean

### Testing Conventions
- **100% coverage goal**: Tasks 1 and 2 achieved this - Continue the standard
- **Test file organization**: test_cli_core.py for CLI tests - Add error tests there
- **Edge case testing**: Empty inputs, conflicting inputs - Test thoroughly

### CLI Conventions
- **Direct command pattern**: `pflow <workflow>` not `pflow run <workflow>` - Established in 2.2
- **=> operator usage**: Chosen to avoid shell conflicts - Use in all examples
- **Input precedence**: file > stdin > args - Established in 2.2

## Codebase Evolution Context

### Recent Major Changes
- **Operator change**: >> changed to => in Task 2.2 - All examples must use =>
- **Command structure**: Removed 'run' subcommand in Task 2.2 - Simpler CLI interface
- **Context introduction**: First use of ctx.obj in Task 2.2 - Available for error handling

### Current State
- **CLI foundation complete**: Basic structure, version command, raw input collection
- **Three input modes working**: args, stdin, file - All tested and functional
- **Ready for enhancement**: Error handling and help text are logical next steps

### Impact on This Task
- Must build on direct command pattern (no 'run' subcommand)
- Must use => operator in all help examples
- Can leverage ctx.obj for error context if needed
- Should add to existing test_cli_core.py file
