# Search Strategy for Implementation Changes

## Pre-Implementation Searches

Run these searches to find all instances that need updating:

### 1. Find all "run" command references
```bash
# In code files
grep -r "\"run\"" src/ tests/ --include="*.py"
grep -r "'run'" src/ tests/ --include="*.py"
grep -r "\[\"run\"" tests/ --include="*.py"
grep -r "invoke.*run" tests/ --include="*.py"

# Check for run in comments/docstrings
grep -r "pflow run" src/ tests/ --include="*.py"
```

### 2. Find all ">>" operator references
```bash
# In code (note: >> might be in strings)
grep -r ">>" src/ tests/ --include="*.py"
grep -r '">>"' src/ tests/ --include="*.py"
grep -r "'>>" src/ tests/ --include="*.py"

# In test assertions
grep -r "Collected workflow.*>>" tests/
```

### 3. Find version command references
```bash
grep -r "version" src/pflow/cli/ tests/ --include="*.py"
grep -r "\[\"version\"\]" tests/ --include="*.py"
```

### 4. Find help text and docstrings
```bash
# Find docstrings that might have examples
grep -r "\"\"\"" src/pflow/cli/main.py
grep -r "Run a pflow" src/
```

## Post-Implementation Verification

After making changes, verify nothing was missed:

### 1. Ensure no "run" references remain
```bash
# Should return no results (except maybe in comments about removal)
grep -r "\.command\(\)" src/pflow/cli/main.py
grep -r "@main\.command" src/pflow/cli/main.py
grep -r "invoke.*\[\"run\"" tests/
```

### 2. Ensure no ">>" references remain
```bash
# Should return no results in code
grep -r ">>" src/ tests/ --include="*.py" | grep -v "comment"
```

### 3. Verify -> is used consistently
```bash
# Should find all the new -> usage
grep -r "\->" src/ tests/ --include="*.py"
grep -r " -> " tests/test_cli_core.py
```

## Key Files to Check

### Must Change:
1. `src/pflow/cli/main.py` - Core CLI structure
2. `tests/test_cli_core.py` - All workflow tests (19 tests)
3. `tests/test_cli.py` - Version command tests

### May Need Changes:
1. `src/pflow/cli/__init__.py` - Check imports
2. `pyproject.toml` - Entry point should stay the same
3. Any future files in `src/pflow/` that reference operators

## Regex Patterns for Find/Replace

### VSCode or sed patterns:
```regex
# Find: ["run",
# Replace: [

# Find: "'run'"
# Replace: Remove the argument

# Find: >>
# Replace: ->

# Find: "Collected workflow:
# Replace: "Collected workflow:

# Find: "Collected workflow from (args|stdin|file): (.*)>>(.*)"
# Replace: "Collected workflow from $1: $2->$3"
```

## Common Patterns to Update

### Test invocations:
```python
# Before
runner.invoke(main, ["run", "node1", ">>", "node2"])

# After
runner.invoke(main, ["node1", "->", "node2"])
```

### Test assertions:
```python
# Before
assert "Collected workflow from args: node1 >> node2" in result.output

# After
assert "Collected workflow from args: node1 -> node2" in result.output
```

### Help text:
```python
# Before
"""Run a pflow workflow from command-line arguments, stdin, or file."""

# After
"""pflow - workflow compiler for deterministic CLI commands.

Execute workflows using the -> operator to chain nodes.
"""
```
