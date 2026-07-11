---
name: "create-task"
description: "Create task file from discussion context"
---

# Create Task

Capture the current discussion into a task file that will guide implementation.

## Input

Task ID: **the user's request**

If this is a number (e.g., "107"), create a task file for **what was just discussed** in this conversation, using that number as the task ID.

If empty, ask the user for a task ID.

**Output**: `.taskmaster/tasks/task_<id>/task-<id>.md`

## What You're Creating

A task file is a handoff document. A future agent (or you in a new session) will read this to understand:
- What we decided to build
- Why it matters
- Key design decisions made
- How to verify it works

**Source**: Your context window. Everything discussed about this task is your primary input.

## When to Stop and Ask

If you lack clarity on ANY of these, ask before writing:
- What the task accomplishes (the goal)
- Why it's needed (the problem it solves)
- Key technical approach (how it should be built)

Don't guess at fundamentals. It's better to ask than to document assumptions.

## Template

```markdown
# Task <id>: <title>

## Description

<2-3 sentences: what this does and why it matters>

## Status

<not started | in progress | done | blocked>

## Priority

<high | medium | low>

## Problem

What's wrong today? Why do we need this?

## Solution

What are we building? High-level approach.

## Design Decisions

Key choices made during discussion:
- Decision 1: We chose X because Y
- Decision 2: We'll do A, not B, because C

## Dependencies

What must exist first?
- Task N: <title> — <why it's needed>

Or "None" if no dependencies.

## Requirements

Specific, testable things the implementation must satisfy. Group by area when there are many.
Not "what we're building" (that's Solution) or "how we'll test it" (that's Verification) —
this is "what properties must hold."

## Implementation Notes

Technical details, integration points, edge cases discussed.

## Verification

How do we know it works?
- Key test scenarios
- Acceptance criteria

## References

Files, docs, prior tasks, or external resources relevant to implementation.
Omit if nothing was referenced.
```

## Section Guidance

**Solution vs. Requirements vs. Verification — what goes where:**
- **Solution**: The approach. *What* we're building and *how* at a high level. ("Markdown format with YAML frontmatter, `## heading` for nodes, code blocks for prompts/scripts.")
- **Requirements**: Properties the implementation must satisfy. Specific, testable, grouped by area. ("Parser must handle nested YAML frontmatter." "Invalid enum values produce blocking error with available choices listed.")
- **Verification**: How we confirm it works. Test scenarios, acceptance criteria, edge cases to exercise. ("Existing workflows converted to markdown produce equivalent IR.")

If something is both a requirement and a test scenario, put it in Requirements. Verification can reference requirements ("All requirements from Parser section verified").

## Guidelines

1. **Write for a fresh reader** — They weren't in this conversation
2. **Capture decisions, not just facts** — "We chose X because Y" is more valuable than "We'll use X"
3. **Be specific about scope** — What's in vs. out?
4. **Link to context** — Reference files, examples, or prior tasks discussed
5. **Omit the obvious** — Don't pad with boilerplate
6. **Include references** — Link to files, docs, prior tasks, or existing patterns that the implementer will need
7. **Status defaults to "not started"** — Unless discussed otherwise
8. **Priority defaults to "medium"** — Unless explicitly discussed

## Example

```markdown
# Task 107: Implement Markdown Workflow Format

## Description

A new workflow authoring format using markdown that compiles to IR. Optimizes for LLM authoring with literate programming, lintable code blocks, and token efficiency.

## Status

not started

## Priority

medium

## Problem

JSON workflows have significant friction:
- Prompts require `\n` escaping on single lines
- Shell/jq commands need quote escaping
- No linting — errors only at runtime
- Documentation separate from workflow
- ~20-40% more tokens than necessary

## Solution

Markdown format with:
- YAML frontmatter for metadata (inputs, outputs, edges)
- `## heading` for node IDs
- Simple `key: value` for node parameters
- Language-tagged code blocks:
  - ` ```prompt ` — LLM prompts
  - ` ```shell ` — Shell commands (lintable with shellcheck)
  - ` ```python ` — Python code (lintable with ruff/mypy)
- Prose documentation inline between nodes

## Design Decisions

- **Markdown → IR, not → JSON**: Compile to internal representation, not JSON files
- **Python over jq**: Task 104's Python node replaces most shell transforms
- **Edges explicit**: Declared in frontmatter, not inferred from references
- **Literate workflows**: Documentation IS the workflow file

## Dependencies

- Task 104: Python Script Node — Enables lintable data transformations in markdown
- Task 49: PyPI Release — Complete first to not delay v0.6.0

## Requirements

### Parser
- Parse YAML frontmatter into metadata dict (inputs, outputs, edges)
- Split document into nodes at `## heading` boundaries
- Extract `key: value` pairs as node parameters (string, int, float, bool, list)
- Extract language-tagged code blocks (`prompt`, `shell`, `python`)
- Preserve prose between nodes as documentation (accessible at runtime, not executed)

### Compilation
- Markdown → IR produces identical IR structure as existing JSON → IR
- All existing node types must be expressible in markdown format
- Edges declared in frontmatter YAML, not inferred from references
- Variable references in code blocks (`{{input.name}}`) validated against declared inputs

### Error Handling
- Syntax errors report file path + line number + human-readable message
- Missing required fields (no `## heading`, no frontmatter) produce specific error types
- Duplicate node IDs (duplicate `## heading`) produce blocking error
- Unknown `key:` parameters produce warning, not error (forward compatibility)

### Linting Integration
- Shell code blocks extractable to temp files for `shellcheck` validation
- Python code blocks extractable to temp files for `ruff`/`mypy` validation
- Lint errors map back to original markdown line numbers

### Constraints
- No new runtime dependencies beyond one markdown parsing library
- UTF-8 only (no encoding detection)

## Implementation Notes

Parser approach:
1. Use existing markdown library (mistune, markdown-it-py)
2. Extract YAML frontmatter
3. Identify nodes by `## heading`
4. Parse inline `key: value` parameters
5. Extract code blocks by language tag
6. Compile to existing IR structure

Error messages should be semantic with line numbers since markdown always parses successfully.

## Verification

- Parser correctly extracts frontmatter, nodes, code blocks
- Round-trip: markdown → IR → execution works
- Linting tools (shellcheck, ruff) work on extracted code blocks
- Existing workflows converted to markdown produce equivalent IR
- Token count comparison shows expected reduction

## References

- Existing JSON workflow parser: `src/parsers/json_workflow.py`
- IR data structures: `src/core/ir.py`
- Task 104 progress log: `.taskmaster/tasks/task_104/implementation/progress-log.md`
```

## MVP Context

We're building an MVP with zero users:
- No backwards compatibility concerns
- No migration code needed
- Breaking changes are fine
- Favor simple, direct solutions

Don't over-engineer. Describe what was discussed, not an idealized version. 
And remember this task spec is the what and why. The how and implementation details lives in the implementation plan.
