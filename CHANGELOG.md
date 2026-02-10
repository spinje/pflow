# Changelog

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
