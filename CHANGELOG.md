# Changelog

## v0.10.0 (2026-03-17)

- Removed the experimental natural language planning module, workflow repair system, and associated CLI flags (e.g., `--trace-planner`, `--auto-repair`) [#122](https://github.com/spinje/pflow/pull/122) ([Task 92](.taskmaster/tasks/task_92/task-review.md))
- Removed `param_mapping`, `output_mapping`, `isolated`, and `scoped` storage modes from nested workflows in favor of a simplified parameters-as-inputs API [#101](https://github.com/spinje/pflow/pull/101) ([Task 59](.taskmaster/tasks/task_59/task-review.md))
- Removed the duplicate `_claude_metadata` output from the Claude Code node, consolidating all token and cost metadata into a unified `llm_usage` output [#124](https://github.com/spinje/pflow/pull/124)
- Removed the unused `--timeout` flag from the `pflow registry run` command [#106](https://github.com/spinje/pflow/pull/106)
- Changed nested workflows to use a unified `workflow:` parameter (accepting both file paths and saved names), where child outputs are automatically exposed to the parent namespace [#101](https://github.com/spinje/pflow/pull/101) ([Task 59](.taskmaster/tasks/task_59/task-review.md))
- Changed documentation terminology to replace "re-planning" with "repeated workflow generation", reflecting the removal of the built-in planner
- Added support for branch convergence in conditional workflows via the `??` coalesce operator in templates and optional inputs (`str | None`) on code nodes [#109](https://github.com/spinje/pflow/pull/109)
- Added unified reasoning and thinking control for the LLM node (`reasoning_effort`, `reasoning_max_tokens`, `model_options`), mapping automatically to provider-specific parameters like Anthropic's `thinking_budget` or OpenAI's `reasoning_effort` [#99](https://github.com/spinje/pflow/pull/99)
- Added compile-time validation for `${item.field}` references inside batch nodes, providing actionable errors when referencing invalid fields before execution [#117](https://github.com/spinje/pflow/pull/117)
- Added per-node LLM cost computation (`cost_usd`) at execution time for both LLM and Claude Code nodes, making it accessible in the shared store and workflow templates [#113](https://github.com/spinje/pflow/pull/113), [#124](https://github.com/spinje/pflow/pull/124)
- Added `--timeout` and `--sse-timeout` CLI flags to `pflow mcp add` and ensured timeout settings are properly preserved in configuration files [#106](https://github.com/spinje/pflow/pull/106)
- Added a new debugging script and documentation section for analyzing workflow execution traces locally (`scripts/analyze-trace/analyze.py`)
- Fixed workflow output resolution to raise an `OutputResolutionError` with per-variable diagnosis instead of silently dropping unresolvable sources [#115](https://github.com/spinje/pflow/pull/115) ([Task 128](.taskmaster/tasks/task_128/task-review.md))
- Fixed the `??` coalesce operator silently failing when used in workflow `outputs` declarations and batch `items` templates [#112](https://github.com/spinje/pflow/pull/112) ([Task 128](.taskmaster/tasks/task_128/task-review.md))
- Fixed template validation to correctly recurse into nested dictionary and list parameters (such as code node `inputs`), catching hidden forward references and typos [#110](https://github.com/spinje/pflow/pull/110) ([Task 128](.taskmaster/tasks/task_128/task-review.md))
- Fixed an issue where the template validator blocked batch processing on workflow nodes and resolved parallel execution deepcopy failures [#104](https://github.com/spinje/pflow/pull/104)
- Fixed batch node to return an "error" action on partial item failures when `error_handling: continue` is set, enabling proper on-error routing
- Fixed workflow validation to properly reject required inputs when they are provided as empty strings

## v0.9.0 (2026-03-14)

- Added conditional branching to workflows. Nodes can now route execution based on errors (`- on-error: node-id`) or static and dynamic data-driven decisions (`- next: node-id` in markdown, `next: str = "node-id"` in Python code nodes). Includes parse-time validation to prevent silent fall-through in branch targets. [#96](https://github.com/spinje/pflow/pull/96) ([Task 38](.taskmaster/tasks/task_38/task-review.md))
- Added `output_schema` parameter to the LLM node to support guaranteed structured JSON responses via constrained decoding. Downstream nodes can now access parsed JSON fields directly as dictionaries instead of parsing strings. [#95](https://github.com/spinje/pflow/pull/95) ([Task 66](.taskmaster/tasks/task_66/task-review.md))
- Fixed state loss in stateful MCP servers (e.g., Playwright, databases) by keeping server sessions alive across workflow steps instead of restarting them for every node. [#94](https://github.com/spinje/pflow/pull/94) ([Task 127](.taskmaster/tasks/task_127/task-review.md))
- Fixed the ReadFile node corrupting file data by unconditionally prepending line numbers to the output. It now correctly returns raw file content.
- Improved MCP error reporting by unwrapping internal task groups to display specific, readable HTTP error messages (e.g., authentication failures) instead of generic Python tracebacks.
- Improved documentation to emphasize agent-led workflow creation and updated roadmap priorities to focus on workflow expressiveness and iteration speed.

## v0.8.0 (2026-02-10)

First public release on PyPI. Install with `uv tool install pflow-cli` or `pipx install pflow-cli`.

- Changed PyPI package name to `pflow-cli` (`pflow` was already taken on PyPI).
- Changed LLM node output to always return raw strings, preventing silent data loss when prose contains JSON code blocks. JSON fields remain accessible via dot notation (`${node.response.field}`).
- Added `pflow skill` command group to publish workflows as AI agent skills for Claude Code, Cursor, Codex, and Copilot [#81](https://github.com/spinje/pflow/pull/81) ([Task 119](.taskmaster/tasks/task_119/task-review.md))
- Added `pflow workflow history` command to view execution logs and previous inputs [#81](https://github.com/spinje/pflow/pull/81)
- Added execution duration tracking (last run and running average) to workflow metadata.
- Fixed CLI parameter parsing to respect declared input types, preventing numeric strings (e.g., Discord IDs) from being coerced to integers [#84](https://github.com/spinje/pflow/pull/84)
- Fixed contradictory validation error messages when accessing outputs from batch processing nodes [#86](https://github.com/spinje/pflow/pull/86)
- Fixed environment variable expansion in MCP server configurations to correctly resolve `${VAR}` in URLs and `settings.json` references.
- Fixed code node runtime errors to display workflow file line numbers instead of code-block relative lines.
- Improved workflow discovery matching accuracy by including node IDs and input names in the LLM context.
- Improved markdown parser error messages to identify nested backticks as the likely cause of untagged code blocks.

## v0.7.0 (2026-02-04)

- Removed `--description` and `--generate-metadata` flags from `workflow save` command [#80](https://github.com/spinje/pflow/pull/80)
- Removed legacy `${stdin}` shared store pattern in favor of explicit input routing [#73](https://github.com/spinje/pflow/pull/73)
- Replaced JSON workflow format with a new Markdown-based format (`.pflow.md`) that treats workflows as executable documentation [#80](https://github.com/spinje/pflow/pull/80) ([Task 107](.taskmaster/tasks/task_107/task-review.md))
- Added Python code node (`"type": "code"`) for in-process data transformation with native object inputs and AST-based type validation [#75](https://github.com/spinje/pflow/pull/75) ([Task 104](.taskmaster/tasks/task_104/task-review.md))
- Added automatic stdin routing via `"stdin": true` input property to support Unix-style workflow chaining [#73](https://github.com/spinje/pflow/pull/73) ([Task 115](.taskmaster/tasks/task_115/task-review.md))
- Added `disallowed_tools` parameter to `claude-code` node to block specific tools via allowlist patterns [#78](https://github.com/spinje/pflow/pull/78)
- Fixed pre-execution validation logic to ensure `--validate-only` catches unknown node types without tracebacks [#67](https://github.com/spinje/pflow/pull/67)
- Fixed template validation error when using nested dot-notation variables inside array brackets
- Improved validation to detect and reject JSON strings containing embedded template variables [#69](https://github.com/spinje/pflow/pull/69)
