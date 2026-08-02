# Changelog

## v0.15.1 (2026-08-02)

- Improved pflow's auto-selected models by updating Anthropic from `anthropic/claude-sonnet-4-5` to `anthropic/claude-sonnet-5`, Google from `gemini/gemini-3-flash-preview` to `gemini/gemini-3.5-flash-lite`, and OpenAI from `openai/gpt-5.2` to `openai/gpt-5.6-luna`. The discovery and filtering fallback now also uses Sonnet 5. [#605](https://github.com/spinje/pflow/pull/605)
- Fixed passing the validated API key to LiteLLM and surfaced provider error text [#605](https://github.com/spinje/pflow/pull/605)

## v0.15.0 (2026-07-18)

- Changed autonomous agent execution by replacing the `claude-code` node with a unified `agent` node. Workflows must now declare `backend: claude` or `backend: codex`; both backends share structured output, session resume, and usage metadata. [#593](https://github.com/spinje/pflow/pull/593) ([Task 177](.taskmaster/tasks/task_177/task-review.md))
- Added a web UI approval bridge in `pflow ui` that allows users to answer paused gates (Approve, Deny, or select escalation options) and trigger run resumption directly from the browser. [#579](https://github.com/spinje/pflow/pull/579) ([Task 176](.taskmaster/tasks/task_176/task-review.md))
- Added Windows compatibility support, ensuring proper Git Bash resolution for POSIX shell steps, correct UTF-8 console and file I/O, detached UI-spawned runs, appropriate Win32 settings permission handling, and robust stdin redirection on Windows. [#564](https://github.com/spinje/pflow/pull/564) ([Task 116](.taskmaster/tasks/task_116/task-review.md))
- Added durable resume tokens and non-TTY gate support, causing non-interactive runs with unapproved gates to pause durably (exit code 4) and output a token that can be listed with `pflow resume list` and answered with `pflow resume <token> --approve yes|no` or `--choose "<answer>"`. [#563](https://github.com/spinje/pflow/pull/563) ([Task 171](.taskmaster/tasks/task_171/task-review.md))
- Added agent voice narration features in `pflow ui`, featuring "point & say" visual target focus, persistent caption overlays, self-pacing walkthroughs driven by browser playback telemetry beacons, and configuration management commands (`pflow settings llm set-tts-model` and `set-tts-voice`). [#560](https://github.com/spinje/pflow/pull/560) ([Task 174](.taskmaster/tasks/task_174/task-review.md))
- Added the `pflow resume` CLI command to continue a failed or interrupted run (including Ctrl+C/SIGKILL) from its failed step without re-executing completed upstream nodes, while verifying workflow drift and caching outputs. [#559](https://github.com/spinje/pflow/pull/559) ([Task 164](.taskmaster/tasks/task_164/task-review.md))
- Fixed `agent` parameter validation to raise structured `PflowError` diagnostics instead of leaking standard Python exceptions. [#597](https://github.com/spinje/pflow/pull/597)
- Fixed the `llm` node to perform local validation of structured outputs against the defined `output_schema` before continuing, correctly falling back to error edges if validation fails. [#600](https://github.com/spinje/pflow/pull/600)
- Fixed MCP tool output guidance to show declared nested paths under the canonical `result.*` namespace. [#583](https://github.com/spinje/pflow/pull/583)
- Fixed transient Windows file locks when saving MCP server configuration by retrying atomic replacements. [#586](https://github.com/spinje/pflow/pull/586)
- Fixed the `mcp` node to strip `_*_source_line` sidecar parameters from forwarded tool arguments. [#588](https://github.com/spinje/pflow/pull/588)
- Fixed trace corruption at the LiteLLM boundary by deep-copying messages to prevent in-place modification. [#587](https://github.com/spinje/pflow/pull/587)
- Improved the `pflow describe` CLI command to support describing local workflow files (e.g., `./drafts/workflow.pflow.md`) in addition to saved workflows. [#596](https://github.com/spinje/pflow/pull/596)

## v0.14.0 (2026-07-03)

- Removed the obsolete `storage_mode` parameter. [#523](https://github.com/spinje/pflow/pull/523)
- Removed outdated subcommand alias notes from the main CLI `--help` output.
- Changed `claude-code` nodes to default to subscription billing, requiring users to explicitly configure `use_api_key: true` to opt into API-key-based Anthropic billing. [#455](https://github.com/spinje/pflow/pull/455)
- Changed the caching defaults to optimize for safety: only `llm` nodes cache by default, while side-effecting nodes like `shell`, `code`, and `http` now default to uncached execution unless explicitly configured with `cache: true`. [#441](https://github.com/spinje/pflow/pull/441) ([Task 161](.taskmaster/tasks/task_161/task-review.md))
- Changed the `pflow visualize` command to `pflow mermaid`. [#496](https://github.com/spinje/pflow/pull/496) ([Task 168](.taskmaster/tasks/task_168/task-review.md))
- Changed MCP nodes to no longer copy top-level result fields into `${node.field}` or create a `{server}_{tool}_result` alias; access tool output via `${node.result.field}`. [#490](https://github.com/spinje/pflow/pull/490)
- Changed the internal `worktree-pflow` developer command to prevent overwriting existing git worktrees by default.
- Changed the developer `code-review` skill to `deep-review` to offer scales of configurable agent counts, an 8-tiered evaluation battery, and `/deep-review` planning modes.
- Added the interactive `pflow ui` command and visualization dashboard, serving a Vite-powered React Flow graph of workflow structures, nested sub-workflows, loops, and data flow. [#496](https://github.com/spinje/pflow/pull/496) ([Task 168](.taskmaster/tasks/task_168/task-review.md))
- Added a live execution overlay to the web UI allowing real-time monitoring of active node states, along with a "This run" side panel detailing cost, input/output data, and token counts. [#543](https://github.com/spinje/pflow/pull/543) ([Task 173](.taskmaster/tasks/task_173/task-review.md))
- Added the capability to launch, inspect, and replay workflows directly from the web UI with automatically generated input forms and selective run pre-fills. [#547](https://github.com/spinje/pflow/pull/547) ([Task 175](.taskmaster/tasks/task_175/task-review.md))
- Added human-in-the-loop approval gates (`approval: required`) to pause workflows before a step executes, and added support for agent-raised escalations (`result.escalation`) with a CLI pre-approve flag (`--auto-approve`). [#554](https://github.com/spinje/pflow/pull/554) ([Task 125](.taskmaster/tasks/task_125/task-review.md))
- Added an agent-to-browser interaction channel, enabling terminal-driven highlight, focus, and camera frame commands (`focus`, `frame`, `clear-focus`) to dynamically control active browser views. [#527](https://github.com/spinje/pflow/pull/527) ([Task 169](.taskmaster/tasks/task_169/task-review.md))
- Added a real-time, streamable JSONL transport for trace file execution, offering crash-tail resilience and partial execution trace recovery on failures. [#530](https://github.com/spinje/pflow/pull/530) ([Task 172](.taskmaster/tasks/task_172/task-review.md)), [#525](https://github.com/spinje/pflow/pull/525) ([Task 133](.taskmaster/tasks/task_133/task-review.md))
- Added a declarative stateful loop modifier (`loop:`) to run nodes repeatedly using `while:` or `until:` conditions, plus a `carry:` configuration block to thread outputs as inputs into subsequent iterations. [#472](https://github.com/spinje/pflow/pull/472) ([Task 166](.taskmaster/tasks/task_166/task-review.md)), [#445](https://github.com/spinje/pflow/pull/445) ([Task 162](.taskmaster/tasks/task_162/task-review.md))
- Added support for literal values and default fallbacks inside template coalesce expressions (e.g., `${item.label ?? "untitled"}`), allowing seamless fall-throughs on absent fields. [#441](https://github.com/spinje/pflow/pull/441) ([Task 161](.taskmaster/tasks/task_161/task-review.md))
- Added self-healing capability to `claude-code` node outputs, performing automatic scalar type coercion and retry-resumes if model JSON deviates from the expected schema. [#465](https://github.com/spinje/pflow/pull/465)
- Added declarative, per-node retry and exponential backoff configuration via the `retry:` schema block. [#471](https://github.com/spinje/pflow/pull/471)
- Added thinking budget configuration parameters (`reasoning_effort` and `reasoning_max_tokens`) to manage reasoning depth for LLM nodes. [#446](https://github.com/spinje/pflow/pull/446)
- Added a plan-to-code agentic coding harness for structured, agent-driven in-code development workflows. [#466](https://github.com/spinje/pflow/pull/466) (Task 163)
- Added a validation guard in repository task scripts to reject impossible date shapes for `--since` task filters and protect against out-of-root executions.
- Fixed the `--only NODE` execution flag to run targets against a frozen snapshot of the last full run instead of re-executing active, side-effecting upstream nodes. [#443](https://github.com/spinje/pflow/pull/443)
- Fixed python `code` nodes to treat type-annotated assignments (e.g., `x: list[str] = [...]`) as local scope variables rather than undeclared workflow inputs. [#331](https://github.com/spinje/pflow/pull/331)
- Fixed static type validation to allow generic python lists (`list[T]` or `list`) to satisfy downstream parameters expecting typed lists like `list[str]`. [#460](https://github.com/spinje/pflow/pull/460)
- Fixed sub-workflow failures to cleanly bubble up structured diagnostics to the parent execution boundary, showing exact error locations. [#522](https://github.com/spinje/pflow/pull/522)
- Fixed LLM model ID checks to occur during compile-time workflow validation, preventing model mismatch failures from occurring mid-run after wasting upstream cost. [#439](https://github.com/spinje/pflow/pull/439)
- Fixed cost estimation logic in dry-run planning to accurately align with actual engine costs and downstream batch loop costs. [#506](https://github.com/spinje/pflow/pull/506)
- Fixed `${...}` template handling inside flow-style YAML files to prevent parser crashes on unquoted inline maps. [#482](https://github.com/spinje/pflow/pull/482)
- Fixed tracking of `input_tokens` across diverse LLM-producing nodes to ensure uniform accounting for cached and uncached prompts. [#492](https://github.com/spinje/pflow/pull/492)
- Fixed core-node refresh operations to preserve synced MCP tools rather than clearing them from the active registry. [#462](https://github.com/spinje/pflow/pull/462)
- Fixed CLI option parsing to reject invalid or stray flags placed after the workflow file argument instead of silently ignoring them. [#454](https://github.com/spinje/pflow/pull/454)
- Fixed the batch `errors` output field to always return a list (even when empty) rather than a null value. [#484](https://github.com/spinje/pflow/pull/484)
- Fixed error routing inside MCP protocol execution to cleanly propagate errors rather than swallowing or misrouting them. [#491](https://github.com/spinje/pflow/pull/491)
- Fixed result warning detectors and validation policies for MCP nodes to prevent false alarms on valid raw JSON-string outputs. [#508](https://github.com/spinje/pflow/pull/508), [#490](https://github.com/spinje/pflow/pull/490)
- Fixed the API warning detector to defer to the node's actual execution success/error status, preventing false positive warnings on handled routing decisions. [#519](https://github.com/spinje/pflow/pull/519)
- Fixed the `--report` CLI command to display accurate input tokens and labeled agent-call counts. [#463](https://github.com/spinje/pflow/pull/463)
- Fixed validation warnings for empty-input batches to print as neutral, non-degrading CLI advisories rather than noisy `DEGRADED` warnings. [#450](https://github.com/spinje/pflow/pull/450)
- Fixed static validation diagnostics for assigned orphan python annotations to offer helpful remove-or-add suggestions. [#477](https://github.com/spinje/pflow/pull/477)
- Improved tracing efficiency and significantly shrunk trace sizes (up to 33% reduction losslessly) via per-run disk-boundary interning and canonical LLM prompt/system deduplication. [#382](https://github.com/spinje/pflow/pull/382) ([Task 165](.taskmaster/tasks/task_165/task-review.md))
- Improved UI server robustness with automatic onerror reconnect handling for SSE connections and browser connection pool optimization to release the 6-connection cap on multi-tab live-overlay viewers. [#529](https://github.com/spinje/pflow/pull/529), [#539](https://github.com/spinje/pflow/pull/539)
- Improved CLI `pflow run` summary outputs with airy line spacing, metadata re-ordered above output data, and clear output labels. [#469](https://github.com/spinje/pflow/pull/469)
- Improved `pflow report` CLI summaries to surface cost, token, and node call totals as prominent headline figures. [#435](https://github.com/spinje/pflow/pull/435)
- Improved Mermaid visualization (`pflow mermaid`) to render `loop:` nodes with distinct `⟳` badges and self-looping dependency edges. [#452](https://github.com/spinje/pflow/pull/452)
- Improved large guide outputs inside the CLI by framing content with read-completeness headers and trailing end-markers. [#509](https://github.com/spinje/pflow/pull/509)
- Improved CLI user experience by redirecting invalid validation verbs (`pflow validate <wf>`, `pflow check <wf>`) to the correct `--validate-only` flag with helpful instructions. (Task 118)

## v0.13.0 (2026-05-26)

- Changed underlying LLM integration library to LiteLLM, introducing a robust, pflow-owned adapter, typed exception handling, and a centralized provider registry. Model names now require provider prefixes (e.g., `openai/gpt-4o`). [#356](https://github.com/spinje/pflow/pull/356) ([Task 158](.taskmaster/tasks/task_158/task-review.md))
- Added provider-level prompt caching via declarative `## Cache` blocks in workflow files, supporting multi-breakpoint prompt caching for Anthropic models and dynamic TTLs for Gemini models. [#378](https://github.com/spinje/pflow/pull/378), [#391](https://github.com/spinje/pflow/pull/391), [#412](https://github.com/spinje/pflow/pull/412) ([Task 159](.taskmaster/tasks/task_159/task-review.md))
- Added `pflow analyze-cache` CLI command to analyze workflow caching opportunities, estimate token metrics, and project cost savings from traces or parameters. [#378](https://github.com/spinje/pflow/pull/378) ([Task 159](.taskmaster/tasks/task_159/task-review.md))
- Added cost telemetry, synthetic cache warmup (`prewarm: true` on LLM nodes), and a deterministic offline pricing map for LiteLLM models to improve cost estimation. [#384](https://github.com/spinje/pflow/pull/384), [#415](https://github.com/spinje/pflow/pull/415)
- Added native SDK structured output via JSON Schema for `claude-code` nodes, integrating soft-failure reporting that marks workflow status as `DEGRADED`. [#399](https://github.com/spinje/pflow/pull/399) ([Task 126](.taskmaster/tasks/task_126/task-review.md))
- Added `pflow settings llm providers` CLI command for finding and auto-discovering LLM environment variables. [#420](https://github.com/spinje/pflow/pull/420)
- Fixed prewarm diagnostics to correctly account for declared `prompt_cache` chunks during analysis. [#417](https://github.com/spinje/pflow/pull/417)
- Fixed `reasoning_effort` mapping for Anthropic Opus 4.7 models and bumped LiteLLM to 1.86.1. [#368](https://github.com/spinje/pflow/pull/368)
- Fixed `cost_usd` evaluation for LLM models added to LiteLLM after the bundled snapshot. [#423](https://github.com/spinje/pflow/pull/423)
- Fixed Claude node's output parsing by aligning 'Outputs' parse-hint with the accepted 'source' key, and clarified agent error messages by removing runtime-internal terms. [#427](https://github.com/spinje/pflow/pull/427)
- Fixed markdown parser to preserve blank lines inside multi-line YAML block scalars. [#387](https://github.com/spinje/pflow/pull/387)
- Fixed linting warnings for input-less shell-nodes to properly surface and offer both cache resolutions. [#425](https://github.com/spinje/pflow/pull/425)
- Fixed path resolving for dotted output (`-o`) CLI destinations. [#400](https://github.com/spinje/pflow/pull/400)
- Improved `pflow analyze-cache` command with advanced cost projection models, additional prompt cache warnings, and robust diagnostic outputs. [#396](https://github.com/spinje/pflow/pull/396), [#405](https://github.com/spinje/pflow/pull/405) ([Task 159](.taskmaster/tasks/task_159/task-review.md))
- Improved CLI execution UX with walk-to-failure hints and more compact batch-processing summaries. [#400](https://github.com/spinje/pflow/pull/400)

## v0.12.0 (2026-04-22)

### Removed
- Removed the `pflow workflow` and `pflow registry` command groups as part of a CLI refactor to flatten the command surface. [#275](https://github.com/spinje/pflow/pull/275) ([Task 151](.taskmaster/tasks/task_151/task-review.md))
- Removed the `workflow_ir` inline-IR escape hatch for sub-workflows. [#286](https://github.com/spinje/pflow/pull/286) ([Task 153](.taskmaster/tasks/task_153/task-review.md))

### Changed
- Changed the CLI to a flattened, agent-friendly structure with top-level commands like `list`, `find`, `describe`, and `probe` (renamed from `registry run`). [#275](https://github.com/spinje/pflow/pull/275) ([Task 151](.taskmaster/tasks/task_151/task-review.md))
- Changed the type vocabulary to use 7 canonical JSON Schema names (`string`, `number`, `integer`, `boolean`, `array`, `object`, `any`) for workflow inputs and outputs. [#290](https://github.com/spinje/pflow/pull/290) ([Task 154](.taskmaster/tasks/task_154/task-review.md))
- Changed the failed-node invariant so failed nodes no longer leak data into downstream template resolution, moving failure records to `shared["__failures__"]`. [#251](https://github.com/spinje/pflow/pull/251) ([Task 148](.taskmaster/tasks/task_148/task-review.md))
- Changed non-interactive output routing to follow Unix conventions where data flows to stdout and diagnostics flow to stderr. [#243](https://github.com/spinje/pflow/pull/243) ([Task 149](.taskmaster/tasks/task_149/task-review.md))
- Changed sub-workflow inputs to use a canonical `inputs:` dictionary form, rejecting undeclared inputs at both parse and runtime. [#286](https://github.com/spinje/pflow/pull/286) ([Task 153](.taskmaster/tasks/task_153/task-review.md))
- Changed `normalize_ir()` to return the normalized dictionary instead of `None` to allow for chaining.

### Added
- Added the `--dry-run` flag to provide execution plans with historical cost and duration estimates without invoking node side effects. [#320](https://github.com/spinje/pflow/pull/320) ([Task 156](.taskmaster/tasks/task_156/task-review.md))
- Added the `pflow guide` command, providing a topic-scoped system for delivering framework, node, and feature guidance. [#278](https://github.com/spinje/pflow/pull/278) ([Task 77](.taskmaster/tasks/task_77/task-review.md))
- Added support for dotted paths in the `--only` flag to target specific nodes in sub-workflows. [#338](https://github.com/spinje/pflow/pull/338)
- Added rich Mermaid visualizations supporting batch semantics, data-flow edges via template refs, and external IO wrapper subgraphs. [#228](https://github.com/spinje/pflow/pull/228) ([Task 146](.taskmaster/tasks/task_146/task-review.md))
- Added support for stdout routing symmetric with stdin, allowing specific outputs to be marked with `stdout: true`. [#282](https://github.com/spinje/pflow/pull/282)
- Added an exception boundary to the MCP server via a FastMCP subclass to prevent server-wide crashes on tool errors. [#328](https://github.com/spinje/pflow/pull/328)
- Added validate-time type checking for code-node input and result annotations. [#317](https://github.com/spinje/pflow/pull/317), [#324](https://github.com/spinje/pflow/pull/324)
- Added a `see_also` field to Diagnostics to provide selective guide topic links. [#313](https://github.com/spinje/pflow/pull/313)

### Fixed
- Fixed dry-run recursion for batch sub-workflows to correctly aggregate costs and durations. [#332](https://github.com/spinje/pflow/pull/332) ([Task 157](.taskmaster/tasks/task_157/task-review.md))
- Fixed issues where auto-detection shadowed dotted targets or populated unresolvable outputs when using the `--only` flag. [#344](https://github.com/spinje/pflow/pull/344), [#343](https://github.com/spinje/pflow/pull/343)
- Fixed batch processing to exclude failed items from the `results` array, ensuring downstream nodes receive clean data. [#265](https://github.com/spinje/pflow/pull/265)
- Fixed workflow and template validators to short-circuit on structural errors. [#330](https://github.com/spinje/pflow/pull/330)
- Fixed memoization cache key sorting and dry-run issues for heterogeneous batches. [#337](https://github.com/spinje/pflow/pull/337)
- Fixed trace aggregation correctness for loop recovery and routing failures. [#327](https://github.com/spinje/pflow/pull/327)
- Fixed the `--output-format json` flag to be orthogonal to stderr verbosity. [#257](https://github.com/spinje/pflow/pull/257)
- Fixed parent-to-child sub-workflow input boundaries to prevent silent dropping of undeclared parameters. [#286](https://github.com/spinje/pflow/pull/286) ([Task 153](.taskmaster/tasks/task_153/task-review.md))
- Fixed preservation of exception annotations during template resolution and engine execution. [#272](https://github.com/spinje/pflow/pull/272)
- Fixed silent failures in error pipelines when running on a cluster. [#298](https://github.com/spinje/pflow/pull/298)
- Fixed on-error recovery to correctly report DEGRADED status instead of SUCCESS. [#261](https://github.com/spinje/pflow/pull/261)
- Fixed prep-time failures to correctly route through the `error_action` dispatch. [#303](https://github.com/spinje/pflow/pull/303)
- Fixed shell node to emit a clean warning instead of a full traceback on timeout.
- Fixed a bug where parameter names using double underscores (`__dunder__`) could corrupt the shared store.
- Fixed validation of inline-static batch items against child input contracts. [#307](https://github.com/spinje/pflow/pull/307)
- Fixed Mermaid reference resolution and consolidated resolution logic. [#299](https://github.com/spinje/pflow/pull/299)
- Fixed workflow scan warnings leaking into unrelated CLI commands. [#280](https://github.com/spinje/pflow/pull/280)
- Fixed a template detection false positive for escaped variables ($${var}).

### Improved
- Improved the workflow validator to produce structured `Diagnostic` objects natively, enabling richer error reporting and suggestions. [#219](https://github.com/spinje/pflow/pull/219) ([Task 147](.taskmaster/tasks/task_147/task-review.md))
- Improved workflow security and reliability by wiring the `WorkflowValidator` into the save process. [#258](https://github.com/spinje/pflow/pull/258) ([Task 150](.taskmaster/tasks/task_150/task-review.md))
- Improved branch-target routing error messages in the markdown parser to be more actionable. [#312](https://github.com/spinje/pflow/pull/312)
- Improved node registry performance and accuracy by automatically refreshing when source files change. [#296](https://github.com/spinje/pflow/pull/296)
- Improved validation of output sources against nodes and declared inputs. [#264](https://github.com/spinje/pflow/pull/264)
- Improved template validation by correctly registering input keys and enabling input forwarding to sub-workflows. [#260](https://github.com/spinje/pflow/pull/260)

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
