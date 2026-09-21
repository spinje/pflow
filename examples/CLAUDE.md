# Examples

Workflow examples also serve as regression fixtures. Start with `examples/README.md` for the example index. Bundling and external-file-reference scenarios have local verification notes in `examples/bundling/TESTING.md` and `examples/file-references/TESTING.md`.

## Directory map

Selected starting points; fixture-specific test contracts follow below.

```text
examples/
├── core/                  # Fundamental workflow patterns
├── advanced/              # More involved patterns
├── nodes/                 # Examples by node type
├── nested/                # Parent/child workflows
├── agent-orchestration/   # Multi-agent harnesses
├── real-workflows/        # Larger task workflows
├── bundling/              # Workflows with bundled assets
├── file-references/       # External prompts, scripts, and config
├── mcp-http/              # HTTP transport examples
├── mcp-integration/       # MCP client integration
├── mcp-pflow/             # pflow MCP server examples
├── *.pflow.md             # Root workflow examples
└── *_demo.py              # Python API demos
```

## Test owners

Test-owner paths below are repository-relative; fixture paths are relative to `examples/`. Check references to the particular fixture before changing, renaming, moving, or deleting it; this table is not an exhaustive consumer list.

| Owner | Contract |
|-------|----------|
| `tests/test_docs/test_example_validation.py` | Runs full `WorkflowValidator` validation on collected, parseable examples, with dummy inputs and resolved file references. Excludes `invalid/`, `legacy/`, and `real-workflows/`; see MCP caveat below. Separately checks that `invalid/` examples fail parsing, schema validation, or full workflow validation. |
| `tests/test_core/test_ir_examples.py` | Pins named core/advanced/invalid files, parser behavior, and IR schema validation; this is not full workflow validation. |
| `tests/test_integration/test_failed_node_invariant.py` | Runs `error-handling/` fixtures through `WorkflowRunner` and pins diagnostic text, fixes, and source lines. See `examples/error-handling/README.md`. Even prose or blank-line edits can change these assertions. |
| `tests/test_runtime/fixtures/baseline_workflows.py` | Canonical example paths and inputs for prompt-cache hash baselines, shared by regeneration and verification. |
| `tests/test_integration/test_plan_to_code_harness.py` | Parses the shipped `agent-orchestration/plan-to-code/` workflows and pins routing/loop/output contracts. |
| `tests/test_core/test_graph_build.py` | Uses real graph fixtures, including `nested/deep-research/`, the plan-to-code validate-fix workflow, and `core/stateful-loop-tournament.pflow.md`. |

## Environment-dependent validation

`test_example_validation.py` skips a workflow only when its missing direct node types are all `mcp-*` tools supplied by configured servers. Any missing non-MCP type still fails.

That pre-scan checks only top-level `node.type`; it cannot see missing MCP types inside a referenced sub-workflow before recursive validation. This is why `real-workflows/` is excluded wholesale. Parse failures outside `invalid/` are also skipped by collection, so this suite does not prove every example parses or runs successfully.
