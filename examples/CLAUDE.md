# Examples

Workflow examples and demo scripts. Some are used by tests, others are reference-only.

> **README.md is stale** — references JSON IR format and `$variable` syntax (now `.pflow.md` and `${variable}`). Do not trust it.

## Directory Structure

```
examples/
├── core/                  # Fundamental patterns (minimal, pipeline, templates, stdin, error handling)
├── advanced/              # Complex workflows with companion .md explanations
├── error-handling/        # ⚠️ USED BY TESTS — edge-case error scenarios (test_failed_node_invariant.py)
├── invalid/               # ⚠️ USED BY TESTS — parse error test cases (test_example_validation.py)
├── nested/                # Nested workflow examples (main + sub-workflows)
├── nodes/                 # Node-specific examples (claude-code)
├── real-workflows/        # Real-world workflows (changelog, release, vision-scraper)
├── mcp-http/              # MCP HTTP transport examples
├── mcp-integration/       # MCP client integration demos (Python scripts)
├── mcp-pflow/             # pflow-as-MCP-server setup and testing
├── interfaces/            # Empty
├── scraped-*-test/        # Test fixture data for markdown parser edge cases
├── *.pflow.md             # Root-level workflow examples (batch, MCP, output validation)
├── *_demo.py              # Python demo scripts (registry, runtime feedback, shell node, workflow manager)
└── README.md              # ⚠️ STALE — references old JSON format
```

## Test Dependencies

- `tests/test_docs/test_example_validation.py` — runs the full `WorkflowValidator.validate()` 10-step pipeline (same as `pflow --validate-only`) on every `.pflow.md` under `examples/` that isn't in `invalid/` or `legacy/`, plus asserts `examples/invalid/` files fail parsing or schema validation.
- `tests/test_core/test_ir_examples.py` — similar validation of example files
- `tests/test_integration/test_failed_node_invariant.py` — executes each fixture in `examples/error-handling/` end-to-end via `WorkflowRunner` and asserts on rendered diagnostic text (source lines, paste-able fixes, structured failure blocks). See `examples/error-handling/README.md` for the per-fixture contract.

**Don't rename/move/delete files in `core/`, `advanced/`, `error-handling/`, or `invalid/` without checking these tests.**

### Environment-dependent examples

`test_example_validation.py` skips workflows whose ONLY unregistered node types match `mcp-*` — MCP tools supplied by user-configured servers (`mcp-filesystem`, `mcp-http/example-workflow`, `real-workflows/*` that reference Slack/Discord MCP tools). Workflows with any non-MCP unregistered type (typo like `wrte-file`, removed node type) still fail so regressions get caught.

Skip logic walks only top-level `node.type`. If a parent workflow references a sub-workflow file whose own nodes include unregistered MCP types, the recursive validator inside `WorkflowValidator._validate_sub_workflows` will still fail — the pre-scan won't see it. No shipped example currently has that shape; add a directory-level skip if it arises.
