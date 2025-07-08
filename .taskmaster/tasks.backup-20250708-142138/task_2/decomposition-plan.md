# Task 2 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_2/decomposition-plan.md`

*Created on: 2025-06-28*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 2 aims to create a basic CLI for argument collection using the click framework. The CLI will accept and collect all command-line arguments (including special operators like `>>`) as raw input without parsing or interpretation. This raw input will be passed to the planner in future phases. The task builds upon the existing click.group() structure from Task 1.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits perfectly because we need to: 1) Build the foundation with a basic 'run' subcommand, 2) Integrate argument collection that handles various input formats, 3) Polish with comprehensive tests and error handling. Each phase builds naturally on the previous one.

## Complexity Analysis
- **Complexity Score**: 3
- **Reasoning**: Low complexity as this is straightforward CLI implementation using established click patterns. No parsing logic required, just raw collection.
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Create 'run' subcommand with basic argument collection
**Description**: Add a 'run' subcommand to the existing click.group() in src/pflow/cli/main.py. This subcommand will use click's nargs=-1 feature to collect all arguments as a tuple, preserving special operators like `>>`. The command should accept workflow arguments and print them for verification during development.
**Dependencies**: None (builds on Task 1's foundation)
**Estimated Hours**: 2-3
**Implementation Details**:
- Add @main.command() decorator for 'run' subcommand
- Use @click.argument('workflow', nargs=-1) to collect all args
- Join arguments into a single string to preserve original input
- Add basic docstring explaining the command's purpose
- Temporarily print collected arguments for verification

**Test Requirements**:
- Test that 'pflow run' command exists and is callable
- Test argument collection with simple node names
- Test preservation of the `>>` operator in collected args
- Test handling of empty arguments

### Subtask 2: Implement proper input handling for various formats
**Description**: Enhance the 'run' command to properly handle different input formats including quoted natural language commands, unquoted CLI syntax with flags, and mixed formats. Add support for reading from stdin when input is piped. Store collected input in click context for future use by the planner.
**Dependencies**: [2.1]
**Estimated Hours**: 3-4
**Implementation Details**:
- Detect stdin input using sys.stdin.isatty()
- Read piped content when available
- Handle both quoted strings ("plan something") and unquoted syntax
- Store raw input in click context using ctx.obj dictionary
- Preserve all flags and parameters exactly as provided
- Add --file option to read workflow from file

**Test Requirements**:
- Test quoted natural language input collection
- Test unquoted CLI syntax with flags (--param=value)
- Test stdin pipe detection and reading
- Test file input option
- Test that context properly stores the raw input

### Subtask 3: Add comprehensive error handling and help text
**Description**: Polish the CLI with proper error handling, informative help text, and user-friendly error messages. Ensure the CLI follows Unix conventions and provides clear feedback for various error conditions. Update tests to cover all error scenarios.
**Dependencies**: [2.1, 2.2]
**Estimated Hours**: 2-3
**Implementation Details**:
- Add detailed help text for the 'run' command
- Implement error handling for invalid arguments
- Add proper exit codes (0 for success, non-zero for errors)
- Create clear error messages for common mistakes
- Ensure --help works properly for all commands
- Add examples to help text showing various input formats

**Test Requirements**:
- Test help text displays correctly
- Test error handling for malformed input
- Test proper exit codes for success/failure
- Test that error messages are clear and actionable
- Create tests/test_cli_core.py as specified in task description

## Relevant pflow Documentation

### Core Documentation
- `docs/reference/cli-reference.md` - Complete CLI syntax and design philosophy
  - Relevance: Defines the expected CLI behavior and syntax patterns
  - Key concepts: Raw argument collection, natural language vs CLI syntax
  - Applies to subtasks: All subtasks, especially 1 and 2

- `docs/features/cli-runtime.md` - How CLI arguments flow through the system
  - Relevance: Shows where collected arguments go after this task
  - Key concepts: Shared store initialization, argument passing to planner
  - Applies to subtasks: Subtask 2 for context storage

- `docs/architecture/architecture.md#5.1` - CLI layer architecture
  - Relevance: Provides architectural context for the CLI's role
  - Key concepts: "Type flags; engine decides" philosophy
  - Applies to subtasks: All subtasks for understanding scope

- `docs/features/mvp-scope.md` - MVP boundaries
  - Relevance: Clarifies what should/shouldn't be in this implementation
  - Key concepts: MVP focuses on basic functionality
  - Applies to subtasks: All subtasks to avoid over-engineering

## Relevant PocketFlow Documentation
Not directly applicable for this task as we're only building the CLI collection layer. PocketFlow integration comes in later tasks when implementing nodes and flows.

## Research References

### For All Subtasks:
- Apply patterns from `.taskmaster/tasks/task_2/research/external-patterns.md`
- Specifically: Consider click-default-group and shell integration patterns for future enhancement
- Adaptation needed: For MVP, implement basic collection first, enhance later

### Previously Suggested Subtasks:
- Reference: `.taskmaster/tasks/task_2/research/previously-suggested-subtasks.md`
- Key insight: Previous suggestions included directory creation and parsing - we're focusing only on collection per task requirements

## Key Architectural Considerations
- Build on existing click.group() from Task 1 - don't replace it
- No parsing of `>>` operator - just collect it as part of raw input
- Use click's built-in features (nargs=-1, context passing)
- Follow established patterns from Task 1 (modular commands, clean structure)
- Tests go in tests/test_cli_core.py as specified

## Dependencies Between Subtasks
- 2.2 requires 2.1 because it enhances the basic 'run' command
- 2.3 requires both 2.1 and 2.2 to add error handling to the complete implementation
- Subtasks should be done sequentially for clean development

## Success Criteria
- [ ] 'pflow run' command successfully collects all arguments
- [ ] Special operators like `>>` are preserved in collected input
- [ ] Both quoted and unquoted input formats work correctly
- [ ] Comprehensive tests in tests/test_cli_core.py
- [ ] Clear help text and error messages
- [ ] No parsing or interpretation of collected arguments

## Special Instructions for Expansion
- Focus on collection, not interpretation
- Each subtask should build incrementally on the previous
- Reference the specific documentation sections in subtask descriptions
- Ensure test requirements are specific and comprehensive
- Keep implementation simple - this is just the collection layer

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. It contains all context needed for intelligent subtask generation, including explicit references to project documentation and clear scope boundaries.
