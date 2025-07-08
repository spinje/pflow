# Task 8 Project Context: Build Comprehensive Shell Pipe Integration

## Task Overview

**Task ID**: 8
**Title**: Build comprehensive shell pipe integration
**Priority**: High
**Dependencies**: Task 3 (Execute a Hardcoded 'Hello World' Workflow - DONE)
**Description**: Implement full Unix pipe support for stdin/stdout handling and shell integration

## Current System State

### Existing Infrastructure
1. **CLI Framework** (Task 2 - DONE)
   - Click-based CLI with direct command execution
   - Basic stdin detection: `not sys.stdin.isatty()`
   - Input handling priority: file > stdin > args
   - Signal handling for SIGINT already present

2. **Workflow Execution** (Task 3 - DONE)
   - Complete pipeline: JSON → Registry → Compiler → Flow execution
   - Shared storage dict created at line 89 in main.py
   - Flow execution with proper error handling

3. **File Nodes** (Task 11 - DONE)
   - Working read-file and write-file nodes
   - Shared store integration patterns established
   - Natural interface conventions (shared['content'])

### Current Limitations
- ❌ stdin treated as workflow input only (not data)
- ❌ No automatic population of shared['stdin']
- ❌ No streaming support for large files
- ❌ No stdout output for pipe chaining
- ❌ Limited exit code handling
- ❌ No SIGPIPE handling

## Architecture Requirements

### Core Design Principles
1. **Unix Philosophy Compliance**
   - Do one thing well (shell integration)
   - Work together (pipe chaining)
   - Text streams as universal interface

2. **Dual-Mode stdin Handling**
   - **Workflow mode**: stdin contains workflow definition
   - **Data mode**: stdin contains data for workflow execution

3. **Reserved Key Pattern**
   - `shared["stdin"]` - reserved for piped input
   - Nodes check stdin as fallback for missing data
   - Template variable support ($stdin)

## Critical Design Decisions (from user decisions)

1. **Streaming Architecture**: Use temporary files for large inputs (>10MB)
2. **Binary vs Text**: Auto-detect and use separate keys (stdin vs stdin_binary)
3. **Output Source**: Configurable output key with smart defaults
4. **Interactive Mode**: Batch mode by default with --interactive flag

## Implementation Patterns from Research

### From Simon Willison's llm CLI
- stdin detection: `if not sys.stdin.isatty():`
- Binary handling: `sys.stdin.buffer.read()`
- Fragment handling with "-" for stdin
- Signal handling patterns

### From pflow Knowledge Base
- Empty stdin handling with CliRunner
- Non-conflicting CLI operators
- Click validation override patterns
- Shell operator conflict avoidance

### From Unix Philosophy
- Silence is golden (minimal output)
- Proper exit codes (0 success, 130 for SIGINT)
- Line-oriented output
- No interactive prompts in pipe mode

## Key Implementation Components

### 1. Shell Integration Module
**Location**: `src/pflow/core/shell_integration.py`
**Responsibilities**:
- stdin detection and reading
- Streaming support for large files
- Signal handling (SIGINT, SIGPIPE)
- Exit code management
- Binary/text data handling

### 2. CLI Integration
**Location**: Modify `src/pflow/cli/main.py`
**Changes**:
- Dual-mode stdin detection (workflow vs data)
- Populate shared['stdin'] before flow execution
- stdout output from shared store
- Modified validation logic

### 3. Testing Infrastructure
**Location**: `tests/test_shell_integration.py`
**Coverage**:
- Unit tests with mocked stdin
- Integration tests with subprocess
- Signal handling tests
- Binary data tests
- Large file streaming tests

## Success Criteria

1. ✅ `cat data.txt | pflow --file workflow.json` works
2. ✅ Large files stream without memory exhaustion
3. ✅ Proper exit codes (0 success, non-zero failure)
4. ✅ Ctrl+C handled gracefully (exit code 130)
5. ✅ Broken pipes handled without errors
6. ✅ Workflows can output to stdout for chaining
7. ✅ Both text and binary data supported
8. ✅ Batch mode by default, interactive optional

## Essential Documentation References

### pflow Documentation
1. **Primary**: `docs/features/shell-pipes.md` - Complete specification
2. **Architecture**: `docs/architecture/architecture.md` section 5.1.4
3. **Shared Store**: `docs/core-concepts/shared-store.md`
4. **CLI Runtime**: `docs/features/cli-runtime.md`

### Research Files
1. `external-patterns.md` - Simon Willison's patterns and Unix best practices
2. `stdin-handling-patterns.md` - Comprehensive stdin handling approaches
3. `unix-pipe-philosophy.md` - Unix integration principles
4. `previously_defined_subtasks.md` - Original subtask breakdown

## Applied Knowledge from Previous Tasks

### Task 2 (CLI Patterns)
- Direct command execution pattern
- Click context usage (ctx.obj)
- stdin detection already implemented
- Error namespace convention

### Task 3 (Integration Patterns)
- Shared storage injection point (line 89)
- Error propagation patterns
- Testing approaches

### Task 11 (File Node Patterns)
- Shared store conventions
- Natural interface patterns
- Error handling approaches

## Domain Understanding Summary

Task 8 bridges Unix shell conventions with pflow's workflow execution model. The key innovation is enabling dual-mode stdin handling - treating stdin as either workflow definition OR as data for workflows. This requires careful modification of existing validation logic while maintaining backward compatibility.

The implementation must feel natural to Unix users, following established conventions for pipes, exit codes, and signal handling. Success means pflow becomes a first-class citizen in Unix pipelines, enabling powerful compositions like:

```bash
find . -name "*.log" | pflow analyze-logs | grep ERROR | wc -l
```

This comprehensive context ensures intelligent task decomposition based on deep domain understanding.
