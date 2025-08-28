# Make Check Error Analysis - 12 Remaining Issues

## Error Categories

### 1. Complexity Issues (C901) - 6 errors
**These require refactoring to reduce cyclomatic complexity**
- `src/pflow/cli/mcp.py:158` - sync() function complexity: 13 > 10
- `src/pflow/cli/mcp.py:242` - tools() function complexity: 21 > 10 (MOST COMPLEX)
- `src/pflow/nodes/mcp/node.py:381` - _extract_result() complexity: 14 > 10
- `src/pflow/planning/context_builder.py:74` - _group_nodes_by_category() complexity: 12 > 10
- `src/pflow/runtime/compiler.py:213` - _instantiate_nodes() complexity: 11 > 10

### 2. Security Issues - 5 errors
**Shell injection risk (S602)**
- `src/pflow/nodes/shell/shell.py:195` - subprocess with shell=True

**Insecure temp file usage (S108)**
- `tests/test_nodes/test_shell/test_improved_behavior.py:194` - hardcoded /tmp
- `tests/test_nodes/test_shell/test_improved_behavior.py:202` - hardcoded /tmp
- `tests/test_nodes/test_shell/test_security_improvements.py:266` - hardcoded /tmp
- `tests/test_nodes/test_shell/test_security_improvements.py:270` - hardcoded /tmp
- `tests/test_nodes/test_shell/test_security_improvements.py:367` - hardcoded /tmp

### 3. Exception Handling - 1 error
**Missing exception chaining (B904)**
- `tests/test_nodes/test_shell/test_security_improvements.py:196` - raise without 'from'

## Parallel Deployment Strategy

### Wave 1: Low-Hanging Fruit (4 parallel agents)
These are independent files with straightforward fixes:

1. **Agent 1**: Fix test_improved_behavior.py (2 S108 errors)
   - Replace hardcoded /tmp with tempfile.gettempdir()

2. **Agent 2**: Fix test_security_improvements.py (4 errors: 3 S108 + 1 B904)
   - Replace hardcoded /tmp with tempfile.gettempdir()
   - Add 'from e' to exception re-raising

3. **Agent 3**: Fix compiler.py complexity (C901 - simplest with score 11)
   - Extract helper methods to reduce cyclomatic complexity

4. **Agent 4**: Fix context_builder.py complexity (C901 - score 12)
   - Extract helper methods to reduce cyclomatic complexity

### Wave 2: Medium Complexity (if needed)
- Fix mcp.py sync() complexity
- Fix node.py _extract_result() complexity

### Wave 3: High Complexity (requires careful analysis)
- Fix mcp.py tools() complexity (score 21 - needs major refactoring)
- Fix shell.py security issue (needs careful security analysis)