# Task 134: Unify Output Auto-Detection

## Problem

Two `_find_auto_output()` implementations return different results for the same workflow — an active correctness bug. When a workflow finishes without declared outputs, pflow guesses which shared store key is "the output." CLI text mode and JSON/MCP mode use different priority orders:

| Location | Used by | Priority order |
|----------|---------|----------------|
| `workflow_output.py:_find_auto_output` | CLI text output | response > output > result > text > stdout |
| `success_formatter.py:_find_auto_output` | JSON output, MCP server | result > output > response > text > data > stdout |

A workflow producing both `response` and `result` shows different output depending on `--output-format`. An agent testing interactively sees one thing; consuming JSON programmatically sees another.

## What Was Done

Created a single shared `find_auto_output()` in `execution/formatters/output_utils.py`, used by both consumers.

Unified behavior:
- **Priority**: `result > response > output > text > data > stdout`
- **Search order**: Root first, then namespaces (root is where declared outputs live)
- **Validity filter**: Skips None and empty/whitespace strings
- **Key filter**: Skips `_` and `__` prefixed keys
- **Last-key fallback**: If no priority key matches, takes the last valid non-internal key
- **Warning**: CLI text mode emits stderr warning when auto-detection is used (not in `--print` mode)

## What Was Deferred

The original task spec also included formatter deduplication (step formatting, `_truncate_error_message`, batch formatting). These are deferred to Task 138 (Unified Execution Pipeline) which will restructure the files these functions live in. Fixing them now would be throwaway work.

Similarly, bare-node output extraction (`_extract_node_outputs` in MCP server, inline extraction in `registry_run.py`) is deferred — different use case from workflow output detection, and the registry run path will be unified in Task 138.

## Key Files

| Action | File |
|--------|------|
| Created | `src/pflow/execution/formatters/output_utils.py` — unified `find_auto_output()` |
| Created | `tests/test_execution/formatters/test_output_utils.py` — 27 tests |
| Modified | `src/pflow/cli/workflow_output.py` — deleted 3 local functions, imports shared version, added warning |
| Modified | `src/pflow/execution/formatters/success_formatter.py` — deleted local `_find_auto_output`, imports shared version |
| Modified | `tests/test_cli/test_workflow_output_handling.py` — updated priority assertions |
| Modified | `tests/test_execution/formatters/test_success_formatter.py` — updated imports |
| Modified | `src/pflow/cli/CLAUDE.md` — updated auto-detection docs |
| Modified | `src/pflow/execution/formatters/CLAUDE.md` — updated auto-detection docs |

## Design Decisions

1. **`result` first**: Most generic output key, works for all node types. LLM workflows writing `response` can use `--output-key response` for explicit control.
2. **Root before namespace**: Root-level keys are either declared outputs or explicitly written — they represent intentional output. Namespace values are incidental.
3. **Last-key fallback**: A workflow where the final node writes to a non-standard key (e.g., `shared["analysis"]`) should still show output rather than nothing. The `_` prefix convention protects truly internal keys.
4. **Lazy imports**: Both consumers use lazy `from ... import find_auto_output` inside function bodies, consistent with existing patterns and avoiding circular dependency risk.
