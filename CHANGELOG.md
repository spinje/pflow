# Changelog

## v0.11.0 (2026-04-05)

- Removed built-in `git`, `github`, `test`, and `echo` nodes and their related configuration settings [#203](https://github.com/spinje/pflow/pull/203)
- Removed the workflow trace analysis script (`analyze.py`) in favor of the new execution reports feature [#147](https://github.com/spinje/pflow/pull/147) ([Task 108](.taskmaster/tasks/task_108/task-review.md))
- Changed the diagnostic system to use a single unified `Diagnostic` type and standardized rendering format for all error and warning reporting [#218](https://github.com/spinje/pflow/pull/218), [#221](https://github.com/spinje/pflow/pull/221) ([Task 143](.taskmaster/tasks/task_143/task-review.md), [Task 144](.taskmaster/tasks/task_144/task-review.md))
- Changed CLI error output to provide a consistent JSON structure across all error paths [#177](https://github.com/spinje/pflow/pull/177) ([Task 137](.taskmaster/tasks/task_137/task-review.md))
- Changed the execution core to an orchestration engine with a compile-once mechanism for sub-workflows, significantly improving batch processing performance [#191](https://github.com/spinje/pflow/pull/191) ([Task 135](.taskmaster/tasks/task_135/task-review.md))
- Changed unknown parameter validation from non-blocking warnings to blocking validation errors [#135](https://github.com/spinje/pflow/pull/135)
- Changed output auto-detection to be unified across the CLI, JSON, and MCP interfaces [#180](https://github.com/spinje/pflow/pull/180)
- Changed batch nodes to report a `DEGRADED` status for items that succeed with empty outputs
- Added the `pflow visualize` command for generating Mermaid workflow flowcharts with configurable depth and direction [#222](https://github.com/spinje/pflow/pull/222) ([Task 145](.taskmaster/tasks/task_145/task-review.md))
- Added execution reports via `--report`, `--report-dir` flags, and the `pflow trace report` command to generate markdown trace directories with rendered prompts, costs, and diagnostics [#147](https://github.com/spinje/pflow/pull/147) ([Task 108](.taskmaster/tasks/task_108/task-review.md))
- Added a memoization cache for workflow iteration, including `--cache`/`--no-cache` CLI flags, the `--only NODE` flag, and a `cache: false` node property [#152](https://github.com/spinje/pflow/pull/152), [#216](https://github.com/spinje/pflow/pull/216) ([Task 106](.taskmaster/tasks/task_106/task-review.md))
- Added workflow dependency bundling to `pflow workflow save` to package workflows as self-contained folders alongside all file dependencies [#137](https://github.com/spinje/pflow/pull/137) ([Task 130](.taskmaster/tasks/task_130/task-review.md))
- Added support for referencing external files in code-block parameters (e.g., `prompt: ./prompt.md`, `code: ./script.py`, `command: ./deploy.sh`) [#134](https://github.com/spinje/pflow/pull/134) ([Task 129](.taskmaster/tasks/task_129/task-review.md))
- Added recursive sub-workflow validation at parse time to catch structural errors before execution begins [#164](https://github.com/spinje/pflow/pull/164) ([Task 136](.taskmaster/tasks/task_136/task-review.md))
- Added `inputs` parameter as template context available to any node type [#162](https://github.com/spinje/pflow/pull/162)
- Added support for per-item parameter overrides in batch nodes
- Added a hint to `pflow registry list` suggesting `pflow mcp sync` when no results are found but matching MCP server names exist
- Fixed sub-workflow relative path and file reference resolution to correctly use the parent workflow directory instead of the current working directory [#207](https://github.com/spinje/pflow/pull/207), [#226](https://github.com/spinje/pflow/pull/226)
- Fixed batch nodes to properly abort with a `RuntimeError` when all items fail under `error_handling: continue` to prevent downstream nodes from processing invalid data [#157](https://github.com/spinje/pflow/pull/157)
- Fixed batch processing `continue` error handling, LLM timeout handling, and JSON decoding error handling [#141](https://github.com/spinje/pflow/pull/141) ([Task 131](.taskmaster/tasks/task_131/task-review.md))
- Fixed detection of sub-workflow error actions during batch processing [#145](https://github.com/spinje/pflow/pull/145) ([Task 131](.taskmaster/tasks/task_131/task-review.md))
- Fixed a bug where batch nodes swallowed compilation errors when `error_handling: continue` was set
- Fixed propagation of LLM costs and cross-cutting keys through nested workflows [#126](https://github.com/spinje/pflow/pull/126)
- Fixed an issue where the registry cache would not refresh after an application upgrade [#143](https://github.com/spinje/pflow/pull/143)
- Fixed the workflow engine to properly recognize "end" and error-only successors as intentional workflow termination [#201](https://github.com/spinje/pflow/pull/201), [#211](https://github.com/spinje/pflow/pull/211)
- Fixed a bug in Python code nodes where type annotations in YAML inputs (e.g., `key: type = value`) were incorrectly included in the resolved value
- Fixed zombie thread stream corruption in the code node that caused intermittent output capture failures [#139](https://github.com/spinje/pflow/pull/139)
- Fixed error on duplicate known section headings and raw string parsing for single-line YAML parameters in the Markdown parser [#196](https://github.com/spinje/pflow/pull/196), [#217](https://github.com/spinje/pflow/pull/217)
- Fixed a bug in the workflow executor where the workflow IR could be concurrently mutated during compilation
- Fixed an issue in the batch executor where permissive batch template errors were not correctly propagated to the parent store
- Fixed validation correctness for bash syntax, double validation, and compiler data flow [#173](https://github.com/spinje/pflow/pull/173)
- Fixed template deduplication, child input resolution, and concurrency in workflow execution [#167](https://github.com/spinje/pflow/pull/167)
- Fixed error display gaps in the CLI and various agent UX inconsistencies [#170](https://github.com/spinje/pflow/pull/170), [#175](https://github.com/spinje/pflow/pull/175)
- Fixed cache invalidation for sub-workflow changes and phantom cost reporting [#158](https://github.com/spinje/pflow/pull/158)
- Improved execution reports with input/output token breakdowns, batch item labels, compact summaries, sub-workflow cost rollups, LLM parameters in metadata, and item counts [#151](https://github.com/spinje/pflow/pull/151) ([Task 108](.taskmaster/tasks/task_108/task-review.md))
- Improved Markdown parsing to detect orphaned content in known sections and provide actionable error messaging for undefined inputs or unquoted colons in YAML parameter values [#150](https://github.com/spinje/pflow/pull/150), [#213](https://github.com/spinje/pflow/pull/213)
- Improved validation warning suppression in the `visualize` command to reduce output noise
- Improved trace reports to include source inputs for Code nodes, response bodies for HTTP nodes, and a summary of batch anomalies

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
