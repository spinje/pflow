# Task 107: Implement Markdown Workflow Format

## Description

Replace JSON as the workflow file format with markdown (`.pflow.md`). The markdown format compiles to the same in-memory dict (IR) that JSON currently produces — all existing validation, compilation, and execution is reused unchanged. The format uses standard markdown structure (headings, code blocks, bullet-point properties) optimized for LLM authoring, with inline documentation that makes workflows self-explaining.

## Status
not started

## Priority
high

## Problem

JSON workflows have significant friction for the actual users (LLMs):

- **Prompt editing is painful**: prompts are single-line escaped strings (`"prompt": "Analyze this:\n\n${item}\n\nRules:\n- Be concise"`)
- **Data transformations are cryptic jq one-liners**: can't lint, can't test, errors only at runtime
- **Documentation is separate**: `workflow.json` + `README.md` = two files that drift apart
- **Token inefficiency**: escaped newlines, quotes everywhere — ~20-40% more tokens than necessary

LLMs are the users, not humans. LLMs already know markdown. We're pre-release with zero users, so there are no backwards compatibility concerns.

## Solution

Markdown replaces JSON as the **only** workflow file format. The internal dict (IR) stays the same — markdown is just a different way to produce it.

Three heading levels, one universal pattern for all entities:

```
#     Workflow title + description prose
##    Section (Inputs, Steps, Outputs)
###   Entity (input, node, or output)
        prose text      → description
        - key: value    → params (YAML list items)
        ```lang param```→ code blocks (content or structured data)
```

A custom line-by-line parser (~300-400 lines) produces the IR dict. No markdown library dependency — the format is a DSL using markdown syntax, not a markdown document.

## Design Decisions

All design decisions are documented with reasoning in `starting-context/format-specification.md` (27 decisions). Key choices:

- **Markdown-only**: JSON workflow files no longer supported as input. One parser, one format.
- **Markdown → dict, not → JSON**: `parse_markdown(content) -> MarkdownParseResult`. No JSON intermediate step.
- **Edges from document order**: linear only. Order of `###` headings in `## Steps` determines execution order.
- **Name from filename**: `my-workflow.pflow.md` → name `my-workflow`. The `#` heading is a display title.
- **No authoring frontmatter**: `## Inputs` / `## Steps` / `## Outputs` sections replace YAML frontmatter. Frontmatter is only for system metadata on saved workflows (added by pflow, never by agents).
- **One universal pattern**: inputs, nodes, and outputs ALL use `###` heading + prose + `- key: value` + code blocks.
- **`- key: value` parsed as YAML**: supports nesting naturally when needed.
- **Code block tag `language param_name`**: last word = param name, preceding word = language hint for editor highlighting.
- **Descriptions required**: all entities must have prose description. Documentation IS the workflow.
- **`*` for doc bullets, `-` for params**: avoids the `-` bullet footgun where LLM prose gets parsed as params.
- **Custom parser, no markdown library**: ~250-350 lines of state machine. Delegates YAML to PyYAML, Python syntax to `ast.parse()`.
- **Planner and repair gated, not removed**: prompts assume JSON format. Gated at entry points with comments, all code preserved.
- **MCP accepts raw markdown content or file paths**: agents write markdown, same format everywhere.
- **Save preserves original markdown content**: no IR-to-markdown serialization needed.

## Dependencies

- **Task 104: Python Code Node** — completed. Enables lintable `python code` blocks replacing jq.

## What's NOT in scope

- Full linting (ruff, shellcheck) → Task 118
- Required param pre-validation → [Issue #76](https://github.com/spinje/pflow/issues/76)
- Type stubs / mypy integration → future
- Shell node refactor for variable injection → Task 118
- IR-to-markdown serialization (save preserves original content)
- Multi-file workflows
- Planner/repair prompt rewrite for markdown (gated for now)
- Agent instruction rewrite (`pflow instructions create`) — Phase 5, collaborative with user

## Verification

**Parser correctness:**
- Parses complete workflows and produces correct IR dicts
- Handles all entity types (inputs, nodes, outputs) with correct param routing
- Extracts code blocks with correct param mapping
- Handles nested fences (4+ backticks)
- Tracks line numbers and produces markdown-native errors
- Rejects invalid workflows with clear, actionable error messages

**Execution equivalence:**
- Convert existing JSON example workflows to markdown
- Parse both → compare resulting IR dicts
- Execute markdown workflows end-to-end

**Integration:**
- CLI: `pflow workflow.pflow.md` works
- Saved workflows: `pflow workflow save` stores as `.pflow.md` with frontmatter
- MCP server: resolves and executes markdown workflows
- Nested workflows: markdown files referenced by workflow nodes
- Graceful error when `.json` file is passed

**Token efficiency:**
- Measure token count for same workflow in JSON vs markdown
- Expect 20-40% reduction

**Manual quality checks (optional, post-implementation):**
- Have an LLM generate a workflow in `.pflow.md` format from a natural language description — does it produce valid output without special prompting?
- Review error messages for a few common mistakes (missing type, bare code block, YAML typo) — are they clear and actionable?
- Open a `.pflow.md` file on GitHub — does it render as readable documentation?

## Implementation Documents

- `starting-context/format-specification.md` — complete format design (27 decisions, parsing rules, code block mapping, examples, verified codebase facts, integration points)
- `implementation/implementation-plan.md` — phased implementation plan (settled decisions, gotchas, file-by-file changes, test migration, risk assessment)

## Example Workflows for Conversion

These serve as both test cases and documentation:
- `examples/real-workflows/generate-changelog/workflow.json` — complex (17 nodes, batch, multiple outputs)
- `examples/real-workflows/webpage-to-markdown/workflow.json` — medium complexity
