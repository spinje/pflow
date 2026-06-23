# Core Module

Foundational components for workflow parsing, validation, management, shell integration, error handling, metrics, and settings.

> For JSON auto-parsing and type coercion across the system, see `architecture/core-concepts/data-type-coercion.md`.

## Module Structure

```
src/pflow/core/
├── __init__.py              # Public API exports
├── node.py                  # Node lifecycle primitives (BaseNode, Node, wiring operators)
├── exceptions.py            # Exception hierarchy (incl. CompilationError, MaxNodeVisitsError)
├── diagnostic.py            # Diagnostic type, exception conversion, dedup
├── diagnostic_render.py     # format_diagnostic text renderer
├── ir_schema.py             # IR schema definition and validation
├── types.py                 # TypeSpec, CANONICAL_TYPES, PYTHON_ALIASES_AT_S1 — single source of truth for S1 vocabulary
├── json_utils.py            # Shared JSON parsing (try_parse_json, parse_json_or_original)
├── yaml_utils.py            # safe_load_preserving_templates — YAML load that shields ${...} templates (issue #482)
├── llm_config.py            # LLM model resolution, env injection, provider detection
├── llm_client.py            # pflow LiteLLM adapter (single seam for all LLM calls)
├── llm_providers.py         # Canonical provider metadata (prefixes, env vars)
├── llm_reasoning_map.py     # Provider/model → reasoning kwargs map
├── markdown_parser.py       # .pflow.md → IR dict parser
├── metrics.py               # Execution metrics collection
├── output_controller.py     # Interactive vs non-interactive output
├── param_coercion.py        # Type coercion: MCP (dict→JSON str) and CLI (str→declared type)
├── security_utils.py        # Sensitive parameter detection and masking
├── settings.py              # Settings with node filtering and env management
├── shell_integration.py     # Unix pipe and stdin handling
├── suggestion_utils.py      # "Did you mean" fuzzy matching
├── user_errors.py           # User-friendly CLI errors (UserFriendlyError, MCPError, OutputResolutionError)
├── validation_utils.py      # Parameter name validation, dummy parameter generation
├── llm_utils.py             # Shared LLM response parsing (parse_structured_response)
├── prompt_utils.py          # Prompt loading and formatting (load_prompt, format_prompt)
├── execution_cache.py       # Two-phase execution cache for probe
├── trace_report.py          # Execution report generation (--report flag, per-node .md files)
├── file_resolver.py         # External file reference detection and resolution
├── duration_format.py       # Human-readable duration formatting
├── trace_tree.py            # Tree-structured trace helpers
├── trace_io.py              # JSONL trace transport: inline-blob interning (intern_event_leaves) + reconstruct + JSONL-only load_trace_file
├── node_type_display.py     # Short display tags for node-class names (node_type_tag, is_llm_node_type)
├── workflow_id.py           # Synthetic ID for inline-workflow cache scoping (ir-hash:<md5>)
├── llm_capabilities.py      # Per-model capability table for prompt caching (Task 159)
├── llm_usage.py             # Shared LLM usage normalization helpers (Task 159)
├── litellm_runtime.py       # LiteLLM runtime policy — single seam for `import litellm` (Task 158)
├── prompt_cache.py          # Prompt cache rendering primitives + cache_control placement (Task 159)
├── prompt_refs.py           # Classify template refs in prompt bodies + `params.inputs` dealiasing (Task 159)
├── cache_overlap.py         # Overlap detection between cache groups and prompt body (Task 159)
├── cache_ttl.py             # TTL handling for prompt caching (Task 159)
├── prompt_cache_analysis/          # Prompt cache analysis package (see prompt_cache_analysis/CLAUDE.md)
├── workflow/                # Workflow lifecycle subdirectory (see workflow/CLAUDE.md)
│   ├── __init__.py          # Re-exports public API
│   ├── manager.py           # Workflow lifecycle (save/load/list/delete)
│   ├── save_service.py      # Shared save operations (CLI + MCP)
│   ├── validator.py         # Unified validation orchestrator
│   ├── data_flow.py         # Execution order and dependency validation
│   ├── status.py            # SUCCESS/DEGRADED/FAILED tri-state enum
│   ├── skill_service.py     # Publish workflows as AI agent skills (symlinks)
│   ├── context.py           # Workflow context for discovery (build_workflows_context)
│   ├── discovery.py         # LLM-powered workflow discovery (find_workflow)
│   └── prompts/
│       └── discovery.md     # Workflow discovery prompt template
└── CLAUDE.md
```

## Key Components — Non-Obvious Details

### exceptions.py

**Exception classes** — canonical home for all pflow exceptions. Hierarchy:
```
PflowError(Exception)                    <- base for all pflow errors
  |- SchemaValidationError               <- IR schema validation (message, path, suggestion)
  |- MarkdownParseError                  <- .pflow.md parse errors (line, suggestion)
  |- CompilationError                    <- IR compilation (phase, node_id, node_type, suggestion)
  |- WorkflowValidationError             <- pre-execution validation (summary, validation_errors)
  |- WorkflowNotFoundError               <- workflow lookup (workflow_name, similar_names, hint)
  |- WorkflowExistsError                 <- duplicate workflow save
  |- UnsupportedCacheTTLError            <- cache TTL not supported by provider (Task 159)
  |- ReportGenerationError               <- trace report generation failure
  |- OnlySnapshotMissingError            <- --only has no prior full-run trace to restore upstream from (issue #443)
  |- LoopConditionError                  <- loop `until`/condition evaluation failed (raised by runtime/engine/loop_control.py)
  |- LoopCarryError                      <- loop carry-state propagation failed (raised by runtime/engine/loop_control.py)
  |- LLMCallError                        <- LLM adapter base for ALL provider errors (raised by llm_client)
  |   |- UnknownModelError               <- model identifier not recognized (reason="unknown_name"|"missing_prefix")
  |   |- MissingApiKeyError              <- AuthenticationError or PermissionDeniedError (kind="missing_key"|"lacks_permission")
  |   |- InvalidRequestError             <- any other BadRequestError (schema, content policy, context window, ...)
  |   |- LLMTransientError               <- Timeout, RateLimitError, InternalServerError (retry loop catches)
  |   |- LLMResponseParseError           <- response doesn't parse against output_schema
  |   |- MissingSdkError                 <- provider SDK not installed (e.g. claude_agent_sdk)
  |- UserFriendlyError                   <- user_errors.py (title, explanation, suggestions)
  |   |- MCPError                        <- user_errors.py
  |   |- OutputResolutionError           <- user_errors.py (failures list)
MaxNodeVisitsError(RuntimeError)         <- intentionally NOT PflowError (loop guard)
```
`except PflowError` catches all pflow-specific exceptions except `MaxNodeVisitsError`. All exception imports should use `from pflow.core.exceptions import ClassName` (canonical path). Re-exports exist in `ir_schema.py` (`SchemaValidationError as ValidationError`) and `markdown_parser.py` (`MarkdownParseError`) for backward compatibility.

**When to use which exception** — pick the most specific one that fits:

| Context | Exception | Key attrs |
|---------|-----------|-----------|
| Node `exec()` body | Just raise — the engine catches, annotates with `_pflow_node_id`, and retries if applicable. Use `NonRetriableError` (from `nodes/file/exceptions.py`) for validation errors that should not retry. | — |
| IR schema validation (bad field types, missing required fields) | `SchemaValidationError` | `message`, `path="nodes[0].type"`, `suggestion="Use 'shell'"` |
| Markdown parsing failures (malformed `.pflow.md`) | `MarkdownParseError` | `message`, `line=42`, `suggestion="Add ## Steps"` |
| Compilation step failures (missing node types, bad config) | `CompilationError` | `message`, `phase="node_import"`, `node_id`, `node_type`, `suggestion` |
| Pre-execution validation (aggregated errors from validator) | `WorkflowValidationError` | `summary`, `validation_errors=[Diagnostic(...), ...]` |
| Workflow not found | `WorkflowNotFoundError` | `workflow_name`, `similar_names=["did-you-mean"]` |
| `--only <node>` run with no prior full-run trace to restore upstream from | `OnlySnapshotMissingError` | `only_node`, `suggestion` (defaults to "run the full workflow once, then retry --only"); raised by `runtime/workflow_trace.load_snapshot_or_raise` for BOTH the engine and the dry-run planner |
| LLM adapter — deterministic provider error (4xx that retry won't fix) | `LLMCallError` subclass — `UnknownModelError(reason)`, `MissingApiKeyError(kind)`, `InvalidRequestError`, or `LLMResponseParseError` | structured `model`, `reason`/`kind`, `provider_message` (raw upstream text — distinct from the pflow-wrapped `Diagnostic.message`); each subclass overrides `to_diagnostics()` to produce rich Diagnostics. LLMNode catches at `_call_llm` (preventing retry burn) and lifts `_diagnostic_context` into shared. |
| LLM adapter — transient error (timeout, rate limit, 5xx that retry may help) | `LLMTransientError` (subclass of `LLMCallError`) | carries `kind` discriminator + `provider_message`; LLMNode re-raises so the Node retry loop fires. Smart_filter / discovery callers catch the `LLMCallError` umbrella for graceful degradation. |
| User-facing errors with fix instructions (CLI/MCP) | `UserFriendlyError` | `title`, `explanation`, `suggestions=["step 1", "step 2"]` |
| MCP tool availability errors | `MCPError` (subclass of `UserFriendlyError`) | same + defaults |
| Output resolution failures (branch-dependent outputs) | `OutputResolutionError` (subclass of `UserFriendlyError`) | `failures=[{...}]` |

**Import**: Always `from pflow.core.exceptions import ClassName`. Never import exceptions from heavy modules (`ir_schema`, `markdown_parser`, `runtime`).

**Don't**: raise vanilla `Exception`, `ValueError`, or `RuntimeError` when a specific `PflowError` subclass fits. Vanilla exceptions get generic error handling — structured exceptions get rich error output with paths, suggestions, and correct categorization.

**Self-describing exceptions** — `PflowError` and most of its subclasses implement `to_diagnostics() -> list[Diagnostic]`. `MaxNodeVisitsError` also implements it despite intentionally not inheriting from `PflowError` (it's a `RuntimeError` because of the loop-guard use case). `exception_to_diagnostics()` is a thin dispatcher: call `to_diagnostics()` if present, else `_builtin_exception_diagnostic()` for stdlib types. When adding a new exception class, override `to_diagnostics()` rather than extending the dispatcher. `MarkdownParseError.raw_message` holds the message without the `Line N:` prefix/suggestion suffix — `to_diagnostics()` uses this for clean rendering.

**Error handling philosophy — producers are self-describing**: validators, exceptions, and runtime events all construct `Diagnostic` objects at the detection site. Never flatten structured data (paths, fuzzy matches, available fields, suggestions) into string messages for downstream code to reverse-engineer. CLI, JSON, and MCP all flow through the same `format_diagnostic()` pipeline — the only place rendering happens.

**Agent-facing messages speak the authoring surface, never runtime internals (FORBIDDEN)**: every string an agent/user reads (errors, suggestions, hints) must reference only what they author in `.pflow.md` — `- key:` bullets, `${node.output}` templates, `### step`/`## section` headings. NEVER the shared store (`shared[...]`), the `params` dict, the `prep`/`exec`/`post` lifecycle, IR shapes, or anything requiring pflow source to interpret. Agents only write markdown, so "set `shared['prompt']`" is unactionable. Correct model — `LLMNode`'s missing-prompt error: *"requires a 'prompt' parameter. Use template syntax like `- prompt: ${previous_node.output}`."* Exempt: docstring conventions like `Interface: - Writes: shared["result"]`, which the context builder rewrites to clean output-key names before agents see them. Enforced by the `review-agent-ux` reviewer (§12 "Internal Vocabulary Leaks").

**`Diagnostic.__hash__` excludes `context`, `title`, and `suggestions`** — load-bearing. Child workflow diagnostics flow through two independent paths (validation-time and runtime) that produce semantically-identical errors with potentially-different enrichment. Dedup only collapses them if identity ignores the display-only fields. Adding `context` to the hash silently breaks sub-workflow warning dedup. Hash identity tuple: `(severity, source, node_id, id or message)` — keep it that way. When `id` is `None` (legacy/un-migrated diagnostics, all today's code paths), the tuple falls back to `message`-keyed dedup, preserving sub-workflow warning dedup byte-for-byte. When `id` is set (cache-namespaced diagnostics introduced in Task 159), `id` is the dedup key and message variants for the same warning collapse correctly. Adding `id` to the tuple unconditionally would break legacy dedup — the conditional fallback (`id or message`) is what makes the change null-safe.

### diagnostic.py

`Diagnostic` dataclass, `Severity` enum, dedup, exception conversion. Identity (eq/hash) is `(severity, source, node_id, id or message)` — context, title, suggestions are display data. When `id` is `None` the tuple falls back to `message` (preserving sub-workflow dedup byte-for-byte); when `id` is set (cache-namespaced diagnostics from Task 159) it becomes the dedup key. Use `deduplicate_diagnostics()` for collections.

`normalize_runtime_warning()` accepts all three `__warnings__` value shapes: legacy strings, structured dicts (`kind`/`text`/`context`), and `Diagnostic` instances. The Diagnostic branch preserves catalog `id`, `severity`, and suggestions in the returned context so runtime fallback paths can render a clean message without losing typed metadata.

**`CATEGORY_TITLES`** maps diagnostic categories to human-readable titles. Used by both `executor_service.py` (error categorization) and `diagnostic_render.py` (error title rendering). Lives here because it's a data constant, not rendering logic.

**`exception_to_diagnostics()`** is a factory/dispatcher: calls `to_diagnostics()` on exceptions that implement it, falls back to `_builtin_exception_diagnostic()` for stdlib types. Creates `Diagnostic` instances — it does not render them. Used by both display-layer code (CLI, formatters) and execution pipeline code (`runner.py`).

### diagnostic_render.py

Text rendering for `Diagnostic` objects. Single public function: `format_diagnostic()`. Imports `Diagnostic`, `Severity`, `CATEGORY_TITLES` from `diagnostic.py` — dependency flows one way (render → model), never the reverse.

**Template error rendering** is structured, not prose: `Diagnostic.context["unresolved_references"]` is a list of per-reference dicts with `status` (`absent` / `failed` / `path_error`), `failure` (with category-aware data), `peer_suggestions`, `secondary_hint`, `did_you_mean`, `corrected_var`. The renderer (`_format_template_error_lines` → `_format_one_reference` → `_render_failure_data_block`) consumes this structure; agents reading JSON (`Diagnostic.to_dict()`) get the same data.

**WARNING-severity dispatch**: `_format_warning_or_info_diagnostic` is one-line by default, BUT `category="template_error"` warnings with `unresolved_references` dispatch to `_format_warning_template_error` which calls the same structured renderer as ERROR severity. Permissive-mode template errors carry the full structure; rendering must surface it.

**Multi-output errors** (from `OutputResolutionError`) carry `context["output_failures"]` — a list of per-output blocks with their own `template`, `source_file`, `source_line`. `_format_template_error_lines` iterates each block.

**`At:` location format** is `node 'X', file:line` (universal editor-click format), not `node 'X', file, line N`.

**Block fallbacks**: every `_render_*_failure_block` returns at least one line (`(no <type> details captured)`) so empty `data={}` doesn't produce a blank rendered block.

### ir_schema.py

**IR schema quick reference** (the shape agents and the compiler work with):
```python
{
    "ir_version": "0.1.0",                    # Required
    "nodes": [...],                            # Required - at least one
    "edges": [...],                            # Optional - node connections
    "start_node": "node-id",                   # Optional - defaults to first node
    "mappings": {...},                         # Optional - proxy mappings
    "inputs": {...},                           # Optional - workflow input declarations
    "outputs": {...},                          # Optional - workflow output declarations
    "template_resolution_mode": "strict"       # Optional - "strict" or "permissive"
}
# Node: {"id": "unique-id", "type": "node-type", "params": {...}, "cache": true/false (optional)}
```

Validates beyond schema structure: catches duplicate IDs, node reference integrity, and provides fix suggestions.

**Internal metadata fields** allowed by the schema (parser-injected, not user-facing):
- `nodes[i]._source_lines` — code block source line offsets (read by `python_code.py` for error attribution)
- `nodes[i]._routes_to_end` — authored success route to reserved `end`; parser metadata consumed by the graph model only, not a runtime edge
- `outputs[name]._source_line` — source line of the output `source:` declaration (read by `output_resolver` for `At:` rendering)

### markdown_parser.py

Line-by-line state machine: extracts H1 title/description, `## Inputs`/`## Steps`/`## Outputs` sections, `### entity` headings with `- key: value` params and fenced code blocks.

Returns `MarkdownParseResult(ir, title, description, metadata, source)`.

**Source line tracking** (load-bearing for template error `At:` rendering): `_Entity` carries three parallel lists — `yaml_items` (raw YAML strings), `yaml_item_lines` (1-based source line of each item's first `- `), and `yaml_item_keys` (parsed top-level key). `_build_output_dict` reads them to record `_source_line` on output dicts. The parallel lists are populated only by `_parse_yaml_items` and `_flush_yaml_item`; modifying one without the others corrupts the index. Code-block params get `_source_line = block.start_line + 1`.

**Parameter parsing** (`_parse_yaml_items`): Two parsing paths based on syntax. Single-line items use `_coerce_yaml_scalar` (raw string + YAML-like scalar coercion for bools, ints, floats, null, quoted strings, flow-style `{}`/`[]`). Multi-line items (indented continuations) use `yaml.safe_load()`. This eliminates YAML structural bugs (`: ` splitting, `#` comment stripping) while preserving type coercion. Intentionally diverges from PyYAML for edge cases (octal, hex, dates, scientific notation). Unterminated quotes error; inline `#` comments are NOT stripped.

**Template shielding in flow-style YAML** (issue #482): every site that YAML-parses author content that can carry `${...}` templates — `_coerce_yaml_scalar` (single-line flow values), `_parse_multiline_yaml_item`, the fenced `yaml`-config blocks in `_validate_code_blocks`/`_route_code_blocks_to_node`, plus `file_resolver`/`dependency_discovery` for external files — goes through `yaml_utils.safe_load_preserving_templates`, NOT raw `yaml.safe_load`. PyYAML reads the `{` in an unquoted `${...}` as a nested flow mapping, so `{ x: ${y} }` would otherwise fail where block/quoted forms parse. The helper masks templates → parses → restores, so inline ≡ block ≡ quoted everywhere. Frontmatter (`markdown_parser`/`manager`) stays on raw `yaml.safe_load` — it carries system metadata, never templates. New author-content YAML sites must use the shared helper or they reopen the bug.

**Multi-line item continuation**: a line continues the current `- key:` item if it is **blank OR indented ≥ the bullet's content column**. Blank lines are preserved verbatim so `|`/`>` block scalars with internal blank-line separators round-trip correctly through `yaml.safe_load`. Termination is only: dedented non-blank line, new `- ` bullet, heading, code-fence, or EOF. `_flush_yaml_item` strips trailing blanks before joining so single-line items stay on the `_coerce_yaml_scalar` fast path (preserving the PyYAML divergences noted above).

**Routing syntax**: `- next: node-id` (static routing), `- next: end` (terminal), `- on-error: node-id` (error routing). These are extracted from params into routing metadata during `_build_node_dict()` and used by `_build_edges()` to generate edges with action fields. Python code blocks are AST-scanned for `next: str = "literal"` assignments to generate additional routing edges.

**Branch target validation**: After edge generation, the parser validates that all branch targets (nodes reached via named action edges or `- on-error:` edges) have explicit `- next:` directives. Also validates that non-router nodes don't fall through into branch targets via document order, and that dynamic `next` assignments in code have corresponding `- next:` declarations. Raises `MarkdownParseError` with actionable fix suggestions.

**Validates at parse time**: missing descriptions, bare code blocks, duplicate params, unclosed fences, YAML syntax errors (multi-line/flow-style items), invalid node IDs, missing `## Steps`, orphaned content in known sections (content in `## Inputs`/`## Steps`/`## Outputs` outside any `### heading` — errors when zero entities parsed, warns when entities exist alongside orphaned content).

**Integration points**: CLI (`main.py`), WorkflowManager (`load`/`load_ir`), MCP resolver, runtime executor (nested workflows), workflow save service.

### shell_integration.py

**FIFO-only pipe detection**: `stdin_has_data()` uses `stat.S_ISFIFO()` (NOT `select()`). Returns True only for real shell pipes. Claude Code stdin is a character device → returns False, preventing hangs.

**StdinData three modes**:
- `text_data`: UTF-8 text under 10MB
- `binary_data`: Binary content under 10MB (detected via null byte sampling in first 8KB)
- `temp_path`: Auto-created temp file for content over 10MB

Memory limit configurable via `PFLOW_STDIN_MEMORY_LIMIT`.

**Stdin routing**: Stdin routes to workflow input declared with `"stdin": true`. Routing happens in CLI (`_route_stdin_to_params()`) before input validation. CLI params override piped stdin. Only one input per workflow can have `stdin: true`.

**Stdout routing** (symmetric, text mode only): One output may declare `"stdout": true` to pick which declared output streams to process stdout. Precedence: `-o` flag > `stdout: true` marker > single declared output (implicit) > first declared with a stderr warning. JSON mode is immune — it emits all declared outputs regardless of marker. See `cli/CLAUDE.md` for the full precedence table and the TTY-gated header behavior.

### workflow/

See `workflow/CLAUDE.md` for per-file details (storage format, validation pipeline, data flow algorithm, skill publishing, known issues).

### llm_client.py

The pflow-owned LiteLLM adapter — single seam for all LLM calls (LLMNode + 3 discovery callsites). Wraps `litellm.completion`. Owns: messages-list construction, reasoning-kwarg translation (delegating shape detection to `llm_reasoning_map`), `cache_control` placement (Phase B-G), translation of every LiteLLM exception to a typed `LLMCallError` subclass (deterministic → `UnknownModelError`/`MissingApiKeyError`/`InvalidRequestError`; transient → `LLMTransientError`), and response normalization to a stable `AdapterResponse` (with structured `warnings` for empty-content cases that surface to `__warnings__`).

**Cost determination is LiteLLM's responsibility**: the adapter reads `cost_usd` from `response._hidden_params["response_cost"]` (LiteLLM populates this from its built-in pricing data). When LiteLLM doesn't recognize the model (custom endpoints, brand-new releases), `cost_usd` is `None` — consumers handle that case via `.get("cost_usd")`. ClaudeCodeNode mirrors `total_cost_usd` (Claude SDK convention) into `cost_usd` at its own producer boundary, so every LLM-producing node writes the same key.

**Litellm is lazy-imported**: `import litellm` costs ~700ms (it eagerly loads handlers and Pydantic types for every provider it supports). To keep CLI invocations that don't need LLM calls fast (`pflow validate`, `--dry-run`, fully-cached runs, the future `analyze-cache`), the import lives inside `complete()` and `_classify_litellm_error()` — not at module top. The first `complete()` call in a process pays the import; subsequent calls resolve from `sys.modules` instantly. Side effect: the first LLM node's recorded duration is inflated by ~700ms (one node out of N per process). Cost predictions are token-based and unaffected; total wall-clock is honest. Tests must patch `litellm.completion` directly (NOT `pflow.core.llm_client.litellm.completion` — that path no longer exists as a module attribute).

### llm_config.py

**Two resolution chains** — easy to call the wrong one:
- `get_model_for_feature("discovery"|"filtering")`: feature setting → `default_model` → auto-detect (Anthropic → Gemini → OpenAI) → hardcoded fallback. **Never returns None.**
- `get_default_workflow_model()`: `default_model` → auto-detect → **None** (caller must handle).

**Key sources** (auto-detect): `os.environ` first, then `~/.pflow/settings.json` env section. LiteLLM reads from `os.environ` natively, so `inject_settings_env_vars()` (called early in CLI/MCP startup) pushes settings-stored keys into the environment for LiteLLM to find. User's actual environment takes priority over settings (won't override existing vars). Idempotent. Skipped under `PYTEST_CURRENT_TEST`.

**Module-level caching**: `get_default_llm_model()` caches result after first detection. Call `clear_model_cache()` in tests.

### metrics.py

**Metrics flow**: LLM usage is captured via trace events (WorkflowTraceCollector). Consumers call `trace.collect_llm_calls()` to get a flat list, then `MetricsCollector.get_summary(llm_calls)` aggregates costs.

**`is_warmup` filtering**: synthetic batch warmup items (created by `_execute_parallel` when `prewarm: true` + declared cache) carry `llm_call.is_warmup = True`. `MetricsCollector` excludes these from `total_calls` and `unavailable_models` (the "N calls" / "N calls with unavailable pricing" counters) but INCLUDES their `cost_usd` and tokens in totals. See `runtime/engine/CLAUDE.md` → "Synthetic Cache Warmup Item" for the full convention and all 8 filtering sites.

### output_controller.py

**`is_interactive()`** (ALL must pass): no `-p/--print`, stdin+stdout are TTY. Only `cli/mcp_sync.py` reads it (MCP discovery gating). **Progress during workflow execution is NOT TTY-gated** — `create_progress_callback()` always returns a callable; only `_handle_batch_progress`'s `\r` inline counter gates on `sys.stderr.isatty()` because `\r` renders as garbage in non-TTY capture.

**Progress indicators**: ✓ success, ✗ Failed (non-batch fatal), ⚠️ warning, ↻ cached, `[no matches]`/`[not found]` smart-handled shell tags.

**Partial-line state machine** — `_handle_node_start` writes `node_id...` with `nl=False` and sets `_partial_line_open=True`. Every completion handler (`_handle_node_complete`, `_handle_node_cached`, `_handle_node_warning`) calls `_ensure_node_line_open` first; if an interleaved write closed the partial, the lead-in re-emits in canonical `node_id...` shape so the completion text isn't orphaned. `_close_partial_line()` is idempotent.

**Invariant**: only `_handle_node_start` and `_ensure_node_line_open` may set `_partial_line_open=True`. Any new stderr writer that emits `nl=False` partial lines MUST route through these or the state machine desyncs silently. Direct `click.echo(..., nl=False, err=True)` or `sys.stderr.write` from inside a node lifecycle is a design smell — emit a progress event instead.

**Logger coordination** — `create_progress_callback` installs `_ProgressPartialLineFilter` on every root-logger `StreamHandler` whose `stream is sys.stderr`. The filter closes any open partial line as a side effect of `logger.*` emits (via weakref to the controller, never blocks records). Covers all `logger.warning`/`logger.error` sites in node code so `logger.warning("...")` during a live progress line doesn't produce `node_id...WARNING:...` corruption. The install is a silent no-op when no handler matches (e.g. `configure_logging` short-circuited under `PYTEST_CURRENT_TEST`) — subprocess tests must scrub that env var to get production-like logging behavior.

### settings.py

**Settings location**: `~/.pflow/settings.json`

**Structure**:
```json
{
  "version": "1.0.0",
  "registry": {
    "nodes": { "allow": ["*"], "deny": [] }
  },
  "runtime": { "template_resolution_mode": "strict" },
  "llm": { "default_model": null, "discovery_model": null, "filtering_model": null },
  "env": {
    "OPENAI_API_KEY": "sk-proj-...",
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```

**`runtime`**: `template_resolution_mode` overridable via `PFLOW_TEMPLATE_RESOLUTION_MODE` env var.

**`llm`**: `default_model` is shared fallback for all features. `discovery_model` and `filtering_model` override it for specific features. See `llm_config.py` for resolution chains.

**Env management**: `set_env`/`get_env`/`unset_env`/`list_env(mask_values=True)`. Plain text storage (industry standard for CLI tools — no keyring/encryption).

**Security**: Atomic save (tempfile + `os.replace()`), chmod 600 on save, permission validation warns on insecure files with secrets.

**Input precedence**: CLI params → settings.env → workflow defaults → error.

**Node filtering**: Allow/deny patterns with fnmatch. Filtering happens at Registry **load time**, not storage time. MCP nodes generate multiple match candidates: `mcp-{server}-{tool}` → also tries `{tool}` (hyphenated) and `{server}.{tool}`.

### user_errors.py

Three-part error structure: WHAT went wrong (title) → WHY it failed (explanation) → HOW to fix it (suggestions). `UserFriendlyError` has `to_diagnostics()` with a `_diagnostic_category` class variable (`"cli"` by default). `MCPError` overrides to `_diagnostic_category = "mcp"` and inherits the base `to_diagnostics()`.

`OutputResolutionError` overrides `to_diagnostics()` entirely. It produces a Diagnostic with `category="template_error"`, `node_id=None` (output errors are about the output declaration, not a node), and `context["output_failures"]` — a per-output list of structured blocks each with their own `template`, `source_file`, `source_line`, and `unresolved_references`. The renderer in `diagnostic_render.py` consumes this structure. **No canned suggestions** — the structured renderer emits per-reference fix hints. The base `__init__` builds a one-line summary explanation (matching `build_template_error_diagnostic` in `runtime/engine/template_errors.py`); legacy multi-line prose was removed because the renderer would otherwise duplicate it.

### validation_utils.py

**Forbidden in parameter names**: `$` (template conflict), `|><&;` (shell injection), spaces/tabs (CLI parsing). Allowed: hyphens, dots, numbers at start.

Validation utilities here are now limited to parameter-name rules and dummy-parameter generation. Structured validation suggestions are produced directly by validator Diagnostics at the source rather than reverse-engineered from flattened error strings.

**🚨 Security gaps identified**:
- Template variables NOT validated for dangerous characters
- Node parameters in IR NOT validated
- LLM-extracted parameters NOT validated
- MCP tool parameters NOT validated (external servers could provide dangerous names)

### execution_cache.py

Two-phase execution pattern for AI agents: (1) execute node → return structure-only + `execution_id`, (2) read specific fields → retrieve from `~/.pflow/cache/registry-run/`. TTL: 24h stored but **not enforced** in MVP.

### trace_report.py

Generates navigable markdown report directories from trace files. `generate_report(trace_path, output_path, only_node, total_nodes)` → `~/.pflow/reports/{name}/` with `summary.md` + per-node files (`01-node-id.md`). Batch/sub-workflow nodes get directories with nested files.

**Snapshot contract**: a report directory is one coherent generated artifact for
one trace. `generate_report()` renders into a temporary sibling directory,
writes `.pflow-report.json`, then replaces the target directory as a unit. Do
not append/update report files in place. Explicit output paths must be missing,
empty, or already marked with `.pflow-report.json`; auto
`~/.pflow/reports/{name}` paths are pflow-managed and may replace old unmarked
directories for migration.

**`--only` context**: When `only_node` and `total_nodes` are provided, summary shows `Nodes: N/M (--only 'X', K skipped)` instead of just `Nodes: N`. Only executed nodes get report files (skipped nodes aren't in the trace).

**Pipeline table**: `_row_status()` returns lowercase `success` / `failed` / `cached` for the new column shape (`| # | Node | Type | Status | Time | Tokens | Cost |`). Failure is checked before `cached` so a `(cached, !success)` event correctly shows `failed`. The table is **per-invocation** — under loop recovery it shows both visits (visit 1 failed, visit 2 success) even though the node's final aggregation state is success. Batch hosts are exploded into per-item rows with bracket labels (`node_id[index] (model-tail)`); synthetic `is_warmup` items are filtered. Rows are buffered and the table header is only emitted when at least one row survives the filter, so a warmup-only batch produces no `## Pipeline` section.

**Errors section — per-node, not per-event**: `_collect_errors(events, failed_node_ids=trace.get("failed_node_ids"))` reads the trace's authoritative `failed_node_ids` list when present (every post-GH-#240 trace) or, for a trace lacking it (a modern crash-truncated `incomplete` trace), derives per-node final state from the `status` enum. A node that failed on visit 1 and succeeded on visit 2 is NOT in `failed_node_ids` and correctly omitted from Errors. See GH #240. Both `_collect_errors` and `_resolve_final_status` are **modern-`status`-only** — the pre-status `success`-bool fallback was removed in #531 (single-object traces no longer load), so all event-level reads in this module use the `status` enum, never `event.get("success")`.

**Per-node files include**: metadata (type, timing, status, LLM model/tokens/cost, error), resolved inputs (`## Command` for shell, `## Prompt` for LLM, `## Code` + `## Inputs` for python), outputs (`## stdout`, `## stderr`, `## Result`, `## Response`), and a catch-all for remaining output keys.

**Consumer**: `cli/commands/run.py:_finalize_trace_and_report()` (CLI `--report` flag), `cli/commands/report.py` (`pflow report` command).

**Binary encoding convention**: `{"__type": "base64", "data": "..."}` — used project-wide for binary data in JSON. Sensitive params auto-masked before caching.

### file_resolver.py

Detects file path references in node params and batch items, reads the files, and substitutes their content into the IR before compilation. Called by `compile_workflow()` and validate-only paths.

**Detection heuristic**: starts with `./` or `../`, or contains `/` with recognized extension (.md, .txt, .py, .sh, .yaml, .yml, .json). Must not contain `${`, newlines, or `://` (URLs excluded).

**YAML-parsed params**: batch, output_schema, headers — file content is parsed with `yaml_utils.safe_load_preserving_templates` (shields `${...}` in flow style — issue #482). All other params get raw text content.

**Batch handling**: `node["batch"]` is at the node top level (NOT in params). If it's a string file reference, reads and YAML-parses. If it's a dict with inline items, walks items for file references in their values.

**Provenance**: Records original file paths in `node["_source_files"]` dict for error attribution.

### types.py

Single source of truth for the workflow-IR `type:` vocabulary. `CANONICAL_TYPES` = the 7 valid names (`string | number | integer | boolean | array | object | any`). `TypeSpec.parse(raw)` is the only entry point — raises `TypeVocabularyError` with structured context (fuzzy suggestions, Python-alias replacements) for the diagnostic pipeline. `TypeSpec.accepts(value)` is reserved for Task 120 (strict runtime enforcement); no production callers yet. Python annotations in code blocks use Python names, not these — see the S1↔S2 bridge in `src/pflow/guide/core.md`.

`outer_base_type(type_str)` strips a parameterized generic to its outer base name (`list[str]` → `list`, discarding the element type). It's the shared home for the `split("[")[0]` pattern; `is_type_compatible` (template validation) uses it so a canonical `array` source can satisfy a verbatim `list[str]` registry param (issue #460). Element types are never compared — consistent with code-node outputs, which also collapse to the bare collection type.

### param_coercion.py

**Two functions for different pipeline stages** — easy to confuse:
- `coerce_param_for_node(value, expected_type)`: For node execution. Intentionally narrow — only converts dict/list → JSON string when declared type is `"str"`. All other values pass through unchanged.
- `coerce_workflow_input(value, declared_type)`: For CLI/env inputs entering a workflow. `declared_type` is one of the 7 canonical S1 names; dispatch table maps each to a coercion function (e.g., `"integer"` → parse int from string). **Lenient**: warns on failure instead of erroring — lets downstream validation catch it. Python aliases are rejected upstream by `validate_ir`, so this function never sees them.

### security_utils.py

19 sensitive parameter names detected (password, token, api_key, secret, etc.). Case-insensitive matching. Used by MCP error sanitization and CLI rerun display.

## Imports — Not Exported (require direct imports)

These modules are NOT in `core/__init__.py` (require direct imports):
- `suggestion_utils` — used by CLI, runtime, formatters, MCP
- `security_utils` — used by MCP errors and CLI display
- `llm_config` — used by CLI startup, compiler, registry/smart_filter, discovery
- `llm_utils` — shared LLM response parsing (used by registry/smart_filter, discovery)
- `prompt_utils` — prompt loading/formatting (used by discovery functions)
- `execution_cache` — used by CLI probe

The `workflow/` subdirectory has its own `__init__.py` with full re-exports. Import from `pflow.core.workflow.manager`, `pflow.core.workflow.validator`, etc.

## Integration Map

| Consumer | Uses from core | Purpose |
|----------|---------------|---------|
| CLI (`cli/main.py`) | shell_integration, WorkflowManager, OutputController, MetricsCollector, UserFriendlyError | Pipe support, saves, display, metrics, error formatting |
| Compiler (`runtime/compilation/`) | validate_ir, validation_utils, SettingsManager | IR validation, param security, env loading |
| Execution (`execution/`) | WorkflowValidator, OutputController, WorkflowManager | Validation phase, display, metadata updates |
| Registry (`registry/`) | SettingsManager | Node filtering at load time |
| Runtime (`runtime/engine/instrumentation.py`) | MetricsCollector, OutputController | LLM usage capture, progress callbacks |
| MCP Server (`mcp_server/`) | workflow_save_service, suggestion_utils, security_utils | Save ops, suggestions, error sanitization |

## Critical Issues

**🚨 Security**: Parameter validation gaps — template variables, node params, LLM/MCP params not validated for shell special characters.

## Testing and Examples

Tests in `tests/test_core/` — comprehensive coverage for all components. See `examples/core/` (valid workflows) and `examples/invalid/` (parse error cases) tested by `test_ir_examples.py`.
