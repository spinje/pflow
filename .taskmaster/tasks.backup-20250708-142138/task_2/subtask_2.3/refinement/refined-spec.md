# Refined Specification for Subtask 2.3

## Clear Objective
Enhance the pflow CLI with comprehensive help text showing all input methods, improve error messages with namespace prefixes and helpful suggestions, and ensure proper Unix-compliant behavior including exit codes and signal handling.

## Context from Knowledge Base
- Building on: Direct command pattern from 2.2, three input modes (args/stdin/file)
- Avoiding: Complex JSON error structures (save for runtime), color output (MVP simplicity)
- Following: Click conventions, Unix standards, error namespace pattern from docs
- **Cookbook patterns to apply**: Not applicable - pure CLI enhancement task

## Technical Specification

### Inputs
- Existing CLI structure in `src/pflow/cli/main.py`
- Current error handling for file/stdin/args conflicts
- Existing help text in main command docstring

### Outputs
- Enhanced help text with comprehensive examples
- Improved error messages with `cli:` namespace prefix
- Proper signal handling for Ctrl+C
- Documentation of -- separator for flag handling
- All existing tests passing plus new tests for error cases

### Implementation Constraints
- Must use: Click framework patterns, existing direct command structure
- Must avoid: Breaking changes to existing functionality, complex error structures
- Must maintain: 100% test coverage, type annotations for all functions

## Success Criteria
- [ ] Help text shows examples for all three input methods (args, stdin, file)
- [ ] Help text explains -- separator for passing flags to nodes
- [ ] Help text demonstrates => operator usage in various scenarios
- [ ] Error messages include `cli:` prefix following namespace convention
- [ ] Error messages provide helpful suggestions where applicable
- [ ] Ctrl+C (SIGINT) handled gracefully with exit code 130
- [ ] All existing tests pass
- [ ] New tests added for enhanced error scenarios
- [ ] Exit codes remain Click defaults (1 for errors, 2 for usage)

## Test Strategy
- Unit tests: Error message format validation, help text content verification
- Integration tests: Signal handling, various error scenarios
- Manual verification: Help text readability, error message clarity

## Dependencies
- Requires: Existing CLI from subtasks 2.1 and 2.2
- Impacts: Future planner integration will use improved error patterns

## Decisions Made
- Error format: Use simple namespace prefix (e.g., "cli: Cannot specify...") not full JSON structure (User confirmed via evaluation.md)
- Help detail: Comprehensive examples covering all input methods (User confirmed via evaluation.md)
- Exit codes: Stick with Click defaults for now (User confirmed via evaluation.md)
- -- separator: Document prominently in help text (User confirmed via evaluation.md)
- Colors: Plain text only for MVP (User confirmed via evaluation.md)
- Signal handling: Implement basic SIGINT handler (User confirmed via evaluation.md)

## Implementation Details

### 1. Enhanced Help Text Structure
```
pflow - Plan Once, Run Forever

Natural language to deterministic workflows.

Usage:
  pflow [OPTIONS] [WORKFLOW]...
  pflow --file PATH
  command | pflow

Options:
  --version        Show version and exit
  -f, --file PATH  Read workflow from file
  --help           Show this message and exit

Examples:
  # CLI Syntax - chain nodes with => operator
  pflow read-file --path=data.txt => llm --prompt="Summarize"

  # Natural Language - use quotes for commands with spaces
  pflow "read the file data.txt and summarize it"

  # From File - store complex workflows
  pflow --file workflow.txt

  # From stdin - pipe from other commands
  echo "analyze this text" | pflow

  # Passing flags to nodes - use -- separator
  pflow -- read-file --path=data.txt => process --flag

Notes:
  - Input precedence: --file > stdin > command arguments
  - Use -- to prevent pflow from parsing node flags
  - Workflows are collected as raw input for the planner
```

### 2. Error Message Improvements
Current errors:
- "Cannot specify both --file and command arguments"
- "Cannot specify both stdin and command arguments"

Enhanced errors:
- "cli: Cannot specify both --file and command arguments. Use either --file OR provide a workflow as arguments."
- "cli: Cannot use stdin input when command arguments are provided. Use either piped input OR command arguments."
- "cli: File not found: 'missing.txt'. Check the file path and try again."

### 3. Signal Handling
```python
import signal
import sys

def handle_sigint(signum, frame):
    """Handle Ctrl+C gracefully."""
    click.echo("\ncli: Interrupted by user", err=True)
    sys.exit(130)  # Standard Unix exit code for SIGINT

# Register in main()
signal.signal(signal.SIGINT, handle_sigint)
```

### 4. Additional Error Cases to Handle
- Empty workflow validation (currently accepts empty input)
- File read permission errors
- File encoding errors (suggest UTF-8)
- Extremely long input (set reasonable limit)

## Next Steps
After refinement is complete, the implementation phase will:
1. Update help text in the main command docstring
2. Enhance all error messages with namespace and suggestions
3. Add signal handling for clean interruption
4. Add validation for edge cases
5. Write comprehensive tests for all new functionality
6. Ensure make check passes with no issues
