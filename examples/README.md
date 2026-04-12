# pflow Examples

Workflow examples in `.pflow.md` format. Start with `core/` for fundamentals, then explore `advanced/` and `real-workflows/` for real-world patterns.

## Running Examples

```bash
# Run any workflow file
uv run pflow examples/core/minimal.pflow.md

# Validate without executing
uv run pflow --validate-only examples/core/simple-pipeline.pflow.md
```

## Directory Structure

### core/
Fundamental patterns — start here:

- **minimal.pflow.md** — Simplest valid workflow (single node)
- **simple-pipeline.pflow.md** — Sequential 3-node pipeline with edges
- **template-variables.pflow.md** — `${variable}` syntax for dynamic workflows
- **error-handling.pflow.md** — Action-based routing for error recovery
- **proxy-mappings.pflow.md** — Shared store interface adaptation
- **stdin-echo.pflow.md** — Receiving input from Unix pipes

### advanced/
Complex workflows with companion `.md` explanations:

- **content-pipeline.pflow.md** — File processing with validation
- **file-migration.pflow.md** — Multi-step file migration with error handling

### invalid/
Deliberately broken files for testing the parser. Used by `tests/test_docs/test_example_validation.py`.

### nested/
Nested workflow examples — a main workflow calling sub-workflows.

### nodes/
Node-specific examples (claude-code).

### real-workflows/
Production-quality workflows with their own READMEs:

- **generate-changelog/** — Generate changelogs from git history
- **release/** — Release automation
- **vision-scraper/** — Web scraping with vision models

### MCP examples
- **mcp-http/** — MCP HTTP transport setup and testing
- **mcp-integration/** — MCP client integration demos (Python)
- **mcp-pflow/** — Using pflow as an MCP server

## Workflow Format

Workflows use `.pflow.md` (markdown):

```markdown
# Workflow Title

Description of what this workflow does.

## Steps

### step-name

Description of what this step does.

- type: shell
- command: echo "hello"
```

For the full format reference, run `uv run pflow guide`.
