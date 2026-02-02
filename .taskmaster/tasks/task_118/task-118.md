# Task 118: Code Block Linting and Shell Node Variable Injection

## Description

Add full linting support for code blocks in markdown workflows (ruff for Python, shellcheck for shell) and refactor the shell node to inject template variables as bash variables instead of inline string replacement. This makes both Python and shell blocks genuinely lintable with standard tooling.

## Status

not started

## Priority

medium

## Problem

Task 107 (markdown workflow format) ships with minimal code block validation: `ast.parse()` for Python syntax and `yaml.safe_load()` for YAML config blocks. This catches syntax errors but misses:

- **Python**: Undefined names, unused imports, common bugs (ruff catches these)
- **Shell**: Quoting issues, bash pitfalls (shellcheck catches these)

Shell blocks have a deeper problem: template variables like `${fetch.response}` are replaced **inline** in the command string. This means:
- The shell command is not valid bash on its own (can't lint it)
- `${fetch.response}` looks like bash variable expansion, confusing both tools and humans
- There's no separation between pflow template syntax and bash syntax

The Python code node (Task 104) already solved this — template variables are in the `inputs` param, not inside the code. Shell should follow the same pattern.

## Solution

Three parts:

### 1. Shell node refactor: variable injection

Change shell nodes from inline template replacement to variable injection:

**Current behavior** (inline replacement):
```bash
# pflow replaces ${fetch.response} with the actual value in the string
curl -s "https://api.example.com/${endpoint}" | jq '.name'
```

**New behavior** (variable injection):
```bash
# pflow injects variables at the top, command is clean bash
endpoint='api.example.com/users'

curl -s "https://${endpoint}" | jq '.name'
```

This makes the shell command valid bash that shellcheck can lint.

### 2. ruff integration for Python code blocks

- Generate wrapper code around each Python code block (declaring input variables so ruff doesn't flag them as undefined)
- Run `ruff check` on the wrapped code
- Parse ruff output and map line numbers back to markdown source
- Evaluate whether ruff should be a runtime dependency (~26 MB binary) or optional

### 3. `pflow validate --lint` command

- Extract code blocks from markdown workflows
- Run ruff on Python blocks, shellcheck on shell blocks
- Report errors with markdown line numbers
- Graceful degradation if shellcheck isn't installed (it's not a Python package)

## Design Decisions

- **Shell refactor bundled with linting**: The shell variable injection and shellcheck linting are interdependent — linting shell blocks is pointless without clean bash, and the refactor's value is proven by linting working
- **ruff as potential runtime dependency**: ~26 MB, about 9% of current install size. Already a dev dependency. Decision on runtime vs optional deferred to implementation
- **shellcheck is external**: Not a Python package — can't be bundled. `pflow validate --lint` should work without it (just skip shell linting with a message)
- **Wrapper generation for ruff**: Python code blocks have injected input variables (bare type annotations like `records: list[dict]`). ruff needs these declared as actual assignments to avoid false "undefined name" errors

## Dependencies

- Task 107: Markdown Workflow Format — must be implemented first (this task lints markdown code blocks)
- Task 104: Python Code Node — already implemented, defines the input injection pattern that shell should follow

## Implementation Notes

### Shell node refactor considerations

- Template values may contain newlines, quotes, special characters — bash variable assignment needs proper escaping
- The `inputs` pattern from the code node could be reused: declare inputs in node params, inject as bash variables
- Existing shell workflows use `${node.output}` inline — this is a breaking change to shell node behavior
- Need to convert existing example workflows and verify equivalent behavior
- Consider: should shell nodes get an `inputs` param like code nodes?

### ruff wrapper generation

The code node convention: bare type annotations (`records: list[dict]`) are inputs injected by pflow. ruff sees these as undefined. The wrapper needs to:
1. Parse type annotations from the code block
2. Generate assignment stubs: `records: list[dict] = ...  # type: ignore`
3. Prepend to the code block
4. Run ruff on the combined file
5. Offset line numbers by the header size when mapping back

### Template variable handling in shell

Currently `${...}` in shell commands is ambiguous — is it pflow template or bash variable? After refactor:
- Bash `${var}` = actual bash variables (including pflow-injected ones)
- No pflow `${...}` syntax inside shell commands
- Template resolution happens in the `inputs` param (frontmatter), not in the command string

## Verification

- Existing shell workflows produce identical results after refactor (behavior preservation)
- `pflow validate --lint` catches ruff errors in Python blocks with correct line numbers
- `pflow validate --lint` catches shellcheck errors in shell blocks with correct line numbers
- Template variables in shell work correctly with the injection pattern (including values with special characters, newlines, quotes)
- ruff doesn't produce false positives on code block input declarations
- Graceful behavior when shellcheck is not installed
- Performance: linting doesn't add unacceptable latency to validation

## Open Questions

- Should ruff be a runtime dependency or optional (`pflow validate --lint` fails gracefully if not installed)?
- Should shell nodes get a formal `inputs` param like code nodes, or inject all template-referenced values automatically?
- How to handle shell commands that genuinely need bash variable expansion (`$HOME`, `$PATH`) alongside pflow-injected variables?
