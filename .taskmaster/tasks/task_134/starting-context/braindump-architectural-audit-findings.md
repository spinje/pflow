# Braindump: Architectural Audit Findings for Task 134

> Date: 2026-03-27
> Source: Deep architectural audit of compounding issues (scratchpads/architectural-debt/compounding-issues.md)

## What the task spec already covers

The spec correctly identifies 3 implementations with different priority orders and proposes unifying them. It notes `executor_service._extract_default_output` is likely dead code. The key files and risks are documented.

## What the task spec is MISSING

### 1. There are 5 implementations, not 3

The audit found TWO additional implementations the spec doesn't mention:

| # | Implementation | Priority order | Location |
|---|---|---|---|
| 4 | **MCP node extraction** | node_type namespace > all non-input, non-`__` keys | `mcp_server/services/execution_service.py:622` (`_extract_node_outputs`) |
| 5 | **Registry run (CLI)** | Same algorithm as #4, duplicated inline | `cli/commands/registry_run.py:269-272` |

These use a DIFFERENT algorithm than the 3 workflow output detectors — they look for the node-type key in shared store, then fall back to filtering all non-reserved keys. This is a separate concept ("what did a bare node write?") but it's duplicated between CLI and MCP with no shared code.

When unifying, decide: should bare-node output extraction share code with workflow output detection, or should they be explicitly separate? They serve different use cases (single node vs multi-node workflow) but the duplication is a maintenance risk.

### 2. There's an active correctness bug

CLI text mode uses `response > output > result > text > stdout` priority. JSON/MCP uses `result > output > response > text > data > stdout`. **A workflow producing both `response` and `result` keys shows different output depending on the output format flag.** An agent testing in text mode and then consuming JSON output gets different data.

This is the review-agent-ux finding from the audit. It's not just a consistency issue — it's an active correctness bug that will eventually cause an agent to use wrong output data.

### 3. Success output quality for AI agents

The audit graded success output quality:
- **JSON mode**: Well-structured, parseable, includes execution steps and metrics. The `result` object uses `parse_json_or_original()` — JSON strings get auto-parsed into nested objects. Good for agents.
- **Text mode**: Routes ALL output to stderr in non-interactive mode (`workflow_output.py:79-84`). Claude Code agents capturing stdout get nothing. Counter to Unix conventions.
- **MCP mode**: Returns text via `format_success_as_text()`, not JSON. An LLM agent must parse "Workflow output:\n\n" to extract the actual result. No reliable programmatic way to check success/degraded/failed state.

### 4. The `data` key exists in JSON but not CLI text

JSON/MCP includes `data` in its priority list; CLI text does not. If a node writes to `shared[node_id]["data"]`, JSON mode finds it; text mode doesn't. This is a subtle gap beyond just priority ordering.

### 5. The `last-key fallback` in JSON mode

`success_formatter.py:_find_auto_output` has a last-key fallback — if no priority key matches, it takes the last key in the namespace dict (heuristic: "likely to be the final result"). CLI text mode does NOT have this fallback. A workflow where the node output uses non-standard keys (e.g., `"analysis"`) would show output in JSON mode (via fallback) but nothing in text mode.

## Recommendation

When implementing Task 134:
1. Start by documenting all 4 remaining implementations (~~the spec's 3~~ now 2 workflow-output detectors after Task 137 deleted `executor_service._extract_default_output`, + the 2 bare-node extractors)
2. Fix the priority order divergence FIRST (this is the correctness bug)
3. Decide on `data` key and last-key fallback — include in unified implementation or not?
4. Consider the bare-node extraction separately — it's a different use case
5. Consider the stderr routing issue for text mode — this affects agent UX but is probably a separate fix
6. **NEW (from Task 137 Layer 5)**: Deduplicate step formatting (`_format_node_status_line` vs `_format_execution_step`) and `_truncate_error_message` — same files, same refactoring pass

## Reference

Full analysis: `scratchpads/architectural-debt/compounding-issues.md` (Issue 2)
