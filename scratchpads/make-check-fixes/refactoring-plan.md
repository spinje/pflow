# Complexity Refactoring Plan

## Current Status
- 6 functions exceed cyclomatic complexity of 10
- Need to reduce complexity through proper refactoring, not suppression

## Complexity Analysis

### 1. `src/pflow/cli/mcp.py:242` - tools() - Complexity: 21 (HIGHEST)
**Problem**: Too many branches for different display formats and error handling
**Solution**:
- Extract display formatting into separate functions
- Create helper for parameter/output formatting
- Separate error handling logic

### 2. `src/pflow/nodes/mcp/node.py:381` - _extract_result() - Complexity: 14
**Problem**: Multiple content type checks and extraction logic
**Solution**:
- Create content type handlers dictionary
- Extract each content type processing to its own method
- Use strategy pattern for content extraction

### 3. `src/pflow/cli/mcp.py:158` - sync() - Complexity: 13
**Problem**: Multiple nested conditions for server processing
**Solution**:
- Extract server connection logic
- Separate tool discovery from registration
- Create helper for error reporting

### 4. `src/pflow/planning/context_builder.py:74` - _group_nodes_by_category() - Complexity: 12
**Problem**: Too many category inference conditions
**Solution**:
- Extract category inference strategies
- Create category mapper class
- Use chain of responsibility pattern

### 5. `src/pflow/runtime/compiler.py:213` - _instantiate_nodes() - Complexity: 11
**Problem**: Mixed responsibilities - creation, wrapping, parameter injection
**Solution**:
- Extract node creation logic
- Separate wrapping logic
- Create parameter injector helper

## Implementation Priority
1. Start with compiler.py (simplest, score 11)
2. Then context_builder.py (score 12)
3. Then mcp sync (score 13)
4. Then mcp _extract_result (score 14)
5. Finally mcp tools (most complex, score 21)

## Refactoring Principles
- Extract methods for single responsibilities
- Use early returns to reduce nesting
- Create helper functions for repeated logic
- Use dictionaries/strategies for multiple conditionals
- Keep original behavior intact