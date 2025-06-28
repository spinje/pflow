# Knowledge Synthesis for Subtask 2.2

## Relevant Patterns from Previous Tasks

### Click Command Pattern with Raw Arguments
- **Pattern**: Use @main.command() with click.UNPROCESSED for raw argument collection
- **Where it was used**: Subtask 2.1 - Added 'run' command with nargs=-1
- **Why it's relevant**: We're enhancing the same command with additional input handling

### Unix Standard -- Separator Pattern
- **Pattern**: Use -- to stop Click from parsing options in collected arguments
- **Where it was used**: Subtask 2.1 - Discovered during testing with flags
- **Why it's relevant**: Must maintain this behavior while adding new input methods

### Type Annotation Pattern
- **Pattern**: All functions require explicit type annotations for mypy
- **Where it was used**: Subtask 2.1 - Fixed missing return type annotations
- **Why it's relevant**: New functions must include proper types from the start

### CliRunner Testing Pattern
- **Pattern**: Use click.testing.CliRunner for all CLI tests
- **Where it was used**: Task 1 and Subtask 2.1 - All CLI tests
- **Why it's relevant**: Must test new input handling modes

## Known Pitfalls to Avoid

### Click Option Parsing Pitfall
- **Pitfall**: Click tries to parse flags in arguments as its own options
- **Where it failed**: Subtask 2.1 manual testing
- **How to avoid**: Continue using -- separator, document clearly

### Empty Arguments Edge Case
- **Pitfall**: Empty argument handling can have subtle whitespace issues
- **Where it failed**: Subtask 2.1 test initially expected trailing space
- **How to avoid**: Test empty cases explicitly for all new input modes

### Virtual Environment Path Pitfall
- **Pitfall**: Commands not in PATH when using venv
- **Where it failed**: Task 1 manual testing
- **How to avoid**: Use .venv/bin/pflow for manual tests

## Established Conventions

### Module Structure Convention
- **Convention**: Keep all CLI commands in src/pflow/cli/main.py
- **Where decided**: Task 1 architecture
- **Must follow**: Add enhancements to existing 'run' command

### Test File Convention
- **Convention**: Core CLI tests go in tests/test_cli_core.py
- **Where decided**: Subtask 2.1 created this file
- **Must follow**: Expand existing test file with new test cases

### Error Handling Convention
- **Convention**: Clear, actionable error messages
- **Where decided**: Task 1 patterns and project philosophy
- **Must follow**: Add helpful error messages for invalid input

## Codebase Evolution Context

### Run Command Foundation Established
- **What changed**: Basic 'run' command now collects raw arguments
- **When**: Subtask 2.1 (just completed)
- **Impact on this task**: We enhance existing command, not create new one

### Click Context Not Yet Used
- **What changed**: Current implementation just echoes collected workflow
- **When**: Subtask 2.1 kept it simple
- **Impact on this task**: We'll introduce ctx.obj for storing raw input

### Test Suite Growing
- **What changed**: tests/test_cli_core.py created with 7 tests
- **When**: Subtask 2.1
- **Impact on this task**: Add new tests alongside existing ones

## Key Insights for Implementation

1. **Build on Existing Command**: Don't create new command, enhance the 'run' command from 2.1
2. **Multiple Input Modes**: Need to handle stdin, --file option, and existing argument modes
3. **Context Storage**: Must introduce click.Context and ctx.obj for first time
4. **Backwards Compatible**: Existing tests must continue to pass
5. **Documentation Critical**: Complex input handling needs clear examples
