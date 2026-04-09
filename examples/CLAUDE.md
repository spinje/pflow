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

- `tests/test_docs/test_example_validation.py` — validates all `.pflow.md` files in `examples/` parse correctly and `examples/invalid/` fail correctly
- `tests/test_core/test_ir_examples.py` — similar validation of example files
- `tests/test_integration/test_failed_node_invariant.py` — executes each fixture in `examples/error-handling/` end-to-end via `WorkflowRunner` and asserts on rendered diagnostic text (source lines, paste-able fixes, structured failure blocks). See `examples/error-handling/README.md` for the per-fixture contract.

**Don't rename/move/delete files in `core/`, `advanced/`, `error-handling/`, or `invalid/` without checking these tests.**
