# Core Module

Shared parsing, diagnostics, configuration, and execution utilities.

## Task Navigation

| Task | Start here |
|---|---|
| Change markdown parsing or source attribution | `markdown_parser.py`; author-content YAML in `yaml_utils.py` |
| Change external content inlining or file provenance | `file_resolver.py::resolve_file_references` mutates IR in place and records `_source_files` (the authored reference, for diagnostics) and `_resolved_files` (the absolute path, same keys — a code step's `__file__`; source-location provenance, so `workflow_id` strips it from the content and step hashes); `FILE_RESOLVABLE_PARAMS` allowlists content params |
| Change `${…}` template syntax, resolution, or the unresolved/issues channels | `templates.py` — see **Template language** below |
| Change IR shape or declared types | `ir_schema.py::FLOW_IR_SCHEMA`, `validate_ir`; `types.py::TypeSpec` |
| Add an error or change diagnostic rendering | `exceptions.py`, `diagnostic.py`, `diagnostic_render.py` — see below |
| Change node lifecycle/retry primitives | `node.py`; node patterns in `../nodes/CLAUDE.md` |
| Change human-decision payloads | `gate.py`; execution policy belongs in `runtime/engine/gate.py` |
| Change save/load, validation, discovery, or static graphs | `workflow/CLAUDE.md` |
| Change LLM requests, normalization, or provider policy | `llm_client.py::complete`, `litellm_runtime.py`, `llm_reasoning_map.py` |
| Change model/key selection or settings | `llm_config.py`, `llm_providers.py`, `settings.py` |
| Change which catalog models `settings llm models` lists | `llm_providers.py::provider_models` (the callable rule, `CuratedProvider.catalog_groups`) |
| Change prompt-cache rendering/overlap/TTL | `prompt_cache.py`, `prompt_refs.py`, `cache_overlap.py`, `cache_ttl.py`; capabilities in `llm_capabilities.py` |
| Change cache recommendations or analysis reports | `prompt_cache_analysis/CLAUDE.md` |
| Change stdin or terminal progress | `shell_integration.py`, `output_controller.py` |
| Change usage aggregation or trace reports | `metrics.py`, `llm_usage.py`, `trace_tree.py`, `trace_report.py` |
| Read persisted traces | `trace_io.py::load_trace_file` — shared JSONL reconstruction boundary |
| Find a Run's trace, the trace filename grammar, the debug-dir listing | `trace_dir.py` — the directory listing is the index (ADR-0018): `list_traces` (one `os.scandir`), `find_trace`, the strict/lenient readers, `is_trace_locked`; shared by `runtime/` and `ui/` |
| Change input coercion, name rules, or redaction | `param_coercion.py`, `validation_utils.py`, `security_utils.py` |
| Show how a caller supplies a declared input (required/optional, placeholder, default) | `types.py::input_usage` / `usage_arguments` — every describing surface reads it; `tests/test_core/test_input_usage.py` pins each surface and the run's rule |
| Change probe result storage or UI narration | `execution_cache.py`; `tts.py::synthesize` |

Cross-package paths below are relative to `src/pflow/`.

## exceptions.py

**When to use which exception:** read the class definitions in `exceptions.py`
and `user_errors.py`. Import exceptions directly from `pflow.core.exceptions`,
not heavy parser/schema/runtime modules. Specific structured exceptions preserve
paths, suggestions, and categorization that generic exceptions lose.

Exceptions own `to_diagnostics()`; `exception_to_diagnostics()` dispatches without
rendering. Add exception behavior on the exception, not in a growing dispatcher.
When wrapping annotated exceptions, use `copy_pflow_annotations`: `raise ... from`
alone does not copy the execution context needed by the runner.

Validators and runtime producers also build `Diagnostic` at detection time.
Keep paths, suggestions, and available fields structured through CLI/JSON/MCP;
downstream code must not reverse-engineer them from prose.

**Agent-facing messages speak the authoring surface:** name `.pflow.md` bullets,
headings, and `${node.output}` references. Avoid shared-store, IR, or lifecycle
terminology that workflow authors cannot act on. Node Interface docstrings are a
separate convention translated by the context builder.

## diagnostic.py and diagnostic_render.py

Diagnostic identity is `(severity, source, node_id, id or message)`. Display
enrichment is excluded because child warnings arrive through both validation and
runtime with different context. Changing equality/hash can silently defeat their
deduplication. Use `deduplicate_diagnostics()` rather than inventing a second key.

`normalize_runtime_warning()` handles legacy strings, structured dictionaries,
and Diagnostics; preserve catalog IDs, severity, and suggestions.

Text rendering belongs in `diagnostic_render.py::format_diagnostic`; the model
must not depend on the renderer. A block renders from the redacted `context` that
`format_diagnostic` passes down, never `diagnostic.context` (ratchet:
`tests/test_core/test_diagnostic_render_redaction.py`). Template errors carry `unresolved_references`,
including permissive-mode warnings. `OutputResolutionError` carries per-output
`output_failures` with their own source locations and no node attribution. Keep
these structures rather than canned suggestions. Context-key conventions live in
`runtime/template_validation/CLAUDE.md`.

A failed step's stdout/stderr previewed in a diagnostic goes through `head_tail_preview`
(head + tail; tools write the cause last) — never a head-only `[:N]` slice.

## Template language (`templates.py`)

The whole `${…}` language is this one module: `parse` → an immutable `Template` of
`Text` / `Expression` / `Issue` segments (every unescaped `${` is an Expression or an
Issue), `parse_path` for a bare path, `lookup` as the one walk, `resolve` →
`Resolution`, the type-rule sets, `is_type_compatible` and `to_string`.
`TemplateResolver` is the permanent string-helper facade over them. It imports only
`pflow.core` — keep it a leaf (`tests/test_core/test_templates_module.py`). No other
module under `src/pflow/` writes a `${` regex or composes one from this module's
symbols (`tests/test_core/test_template_grammar_seam.py`; its allowlist names the
genuinely different languages). `web/src/graph/scan.ts` copies the grammar strings,
so a grammar change edits it in the same step.

- **Pick the view.** `Expression.references` is the dependency view — a dynamic
  index `${a[${i}].x}` contributes `a` and `i` (data flow, graph edges, unused
  inputs). `Expression.operands` / `TemplateResolver.extract_variables` is the value
  view — the whole `a[${i}].x` only (typing, absence, resolution). Reading the
  wrong one silently drops or invents a dependency.
- **A dynamic index is one Reference**: simple and type-preserving; the inner
  reference must resolve to an in-range `int` (not `bool`), or the whole reference
  is unresolved.
- **Two channels.** `Resolution.unresolved` (Expressions left literal) and
  `Resolution.issues` (Issues, and JSON inserts outside embedded code, carried
  verbatim) are the only judge of "unresolved"; never decide it by comparing or
  re-scanning resolved text — a resolved value may legitimately contain `${…}`. The channels stay separate so a
  surface can tolerate Issues without tolerating misses.
- **Author text only.** `parse` is `lru_cache`d; call it on template text from the
  IR. On resolved runtime values use the uncached `has_templates` /
  `has_references`.
- **Raw-path mode.** `resolve_value` / `variable_exists` take user-typed paths
  (`-o result.@type`, `read-fields result.dc:title`, `result.0`), split lexically
  with no identifier grammar, and feed the same walk. They are not templates: do
  not route them through `parse_path`, and do not accept raw paths inside `${…}`.
- **A JSON insert** `${x|json}` is an Expression with `as_json` (its `raw` keeps
  the suffix): never simple, its value entering text as `to_json`. Only embedded
  code fills it in — `resolve(…, embedded=True)` reads a string through
  `embedded_code`, a policy view whose Text may hold `${` (which params:
  `workflow/template_surfaces.py::param_mode`).
- **Escapes** (`$${…}`) consume through their brace-balanced `}` and yield a literal
  `${…}`; a bare `$$` is untouched. A code body is never parsed for resolution, so
  `$${` there is no escape (`workflow/template_surfaces.py::param_mode`). `TEMPLATE_PATTERN` / `SIMPLE_TEMPLATE_PATTERN`
  cannot see that consumption — over text that may hold `$${`, use `parse()`.
- **Type rules.** `is_type_compatible` is template-flow compatibility (a value may be
  auto-parsed or stringified on its way through `${…}`), not a literal-value check:
  a workflow input's value is typed by `param_coercion.coerce_declared_input` (see
  **Types, coercion, and security boundaries**). `to_string` is complex interpolation's
  stringification; `prompt_cache.deterministic_serialize` differs on
  purpose (canonical bytes for cache keys).
- **A declared input is never re-parsed** (ADR-0017): when the context carries
  `DECLARED_INPUT_TYPES_KEY`, a reference whose root is a declared non-`any` input
  is not JSON-parsed at the `auto_parse` leaf (judged by the `??` operand that
  supplied the value) nor mid-path (root-wide), and neither is a name bound to one by a
  single whole reference (`bound_declaration`; `PROTECTION_ONLY` when its type is
  unknown — a path into the input, a batch item); `unparsed_declared_text` names the
  text such a walk stopped at. Without the key, behaviour is unchanged — callers
  that resolve against a store get it from the store's installers.
- The validator walks declared structure over the same parse and rules, not the
  runtime walk (ADR-0006): `runtime/template_validation/CLAUDE.md`.

## markdown_parser.py

- Author content containing `${...}` must use
  `yaml_utils.safe_load_preserving_templates`: raw PyYAML misreads unquoted
  templates inside flow mappings. Frontmatter remains ordinary YAML metadata.
  This boundary also applies to external files and dependency discovery.
- Single-line bullets use `_coerce_yaml_scalar`, deliberately differing from
  PyYAML for dates, octal/hex, scientific notation, and inline `#`. Do not replace
  it with a uniform YAML load. Multiline continuation preserves internal blank
  lines so block scalars retain their content.
- Source attribution depends on `_Entity.yaml_items`, `yaml_item_lines`, and
  `yaml_item_keys` staying aligned. `_build_output_dict` uses that alignment for
  output `source:` locations; code-block offsets feed runtime diagnostics.
- Shape rules belong in `ir_schema.py`; semantic checks in
  `workflow/validator.py`. Parser-injected source/route metadata is not an
  authoring API; inspect the schema and consumers before changing it.

## llm_client.py

`complete()` is the LLM adapter boundary. Keep LiteLLM access lazy through
`litellm_runtime` so non-LLM commands avoid provider startup cost. Tests patch
`litellm.completion`, not a module-level `llm_client.litellm` attribute.

For registered providers, pass `llm_config.resolve_provider_api_key()` explicitly
unless overridden. Letting LiteLLM independently select a key can disagree with
pflow validation. `_mask_key_material` masks provider exception text before capture
because providers can echo credentials; response-parse failures need the same mask.

Cost normalization lives in `_normalize` and its helpers. `cost_usd` means paid
cost; unavailable pricing remains `None`. Agent backend estimates use
`api_equivalent_cost_usd` instead. Trace and analysis consumers must not treat
those comparisons as observed billing. Summaries classify each call as paid,
subscription-billed (the record carries the estimate key), or unpriced in one
place — `MetricsCollector.calculate_costs` — which the CLI/JSON summary, the
trace `llm_summary`, and `trace_report` all call; only human displays show the
estimate, always labelled (`subscription … · API-equivalent`, `~$` cells).

## llm_config.py and settings.py

`get_model_for_feature()` always supplies a model; `get_default_workflow_model()`
can return `None`. Default-model detection is cached; `clear_model_cache()`
resets process state for tests or changed keys.

`resolve_provider_api_key()` owns environment/settings precedence and aliases.
Keep presence checks and request keys on this resolver. Settings injection records
provenance so genuinely exported environment aliases still take precedence.

Settings saves are atomic and permission-restricted. `save()` refuses while
`load_error` is set (the file failed to load; writing defaults back would wipe it).
Every settings model keeps unknown keys (`extra="allow"`) so a typo survives a save;
`unknown_settings_keys` walks them at every level (Retention's misplaced-key check,
`settings show`'s omission); `runtime.trace_retention_days` is read only by
`runtime/trace_retention.py::retention_days` (env `PFLOW_TRACE_RETENTION_DAYS` first,
never written back). Node filtering happens at
registry **load**, not storage; MCP matching includes tool/server aliases.
Workflow input precedence is separately owned by
`runtime/compilation/ir_preparation.py::prepare_inputs`, not the provider resolver.

## Shell and progress boundaries

`stdin_has_data()` recognizes real pipes and regular-file redirects (Unix
`S_ISFIFO`/`S_ISREG`, Windows `FILE_TYPE_PIPE`/`FILE_TYPE_DISK`), never character
devices: readiness polling can hang on external-agent character-device stdin.

`OutputController.is_interactive()` gates interactive discovery, not all execution
progress. New writers must respect the `_ensure_node_line_open`/
`_close_partial_line` boundary; direct partial stderr writes inside nodes corrupt
completion labels. Emit progress events instead. `_ProgressPartialLineFilter`
coordinates logging with open progress lines. Subprocess checks of logging must
clear `PYTEST_CURRENT_TEST`, which can bypass production logger configuration.

Output-selection policy belongs in
`execution/formatters/output_utils.py::select_output_mode`.

## Metrics and reports

Usage aggregates from trace LLM calls through `MetricsCollector`. Warmup accounting
is owned by `runtime/engine/CLAUDE.md` → **Synthetic Cache Warmup Item**.

`trace_report.generate_report()` replaces one coherent report directory rather
than updating files in place. Explicit destinations must be missing, empty, or
marked with `.pflow-report.json`; automatic paths are pflow-managed. The pipeline
table is per invocation; Errors uses final node state. A recovered loop failure
must not become a final error. Use `failed_node_ids` when present and modern event
`status` otherwise.

## Types, coercion, and security boundaries

`TypeSpec.parse()` owns IR `type:` vocabulary; Python annotations use a different
vocabulary. `outer_base_type()` intentionally discards generic element types for
compatibility checks. See `architecture/core-concepts/data-type-coercion.md`;
template-flow compatibility is under **Template language** above.

`coerce_param_for_node()` only converts dict/list to JSON for expected `str`.
`coerce_declared_input()` types a workflow input by its declared type, once, where
it enters, and raises `InputTypeError` (never warns): text through
`TypeSpec.parse_text` (decision (b)'s grammar), typed values through
`TypeSpec.accepts`, `any` text from a CLI argument by lossless inference. It needs
the value's `InputSource` — the error names it. Do not interchange these pipeline stages.

`is_valid_parameter_name()` checks names, including the reserved `__*__` and `_pflow_*`
(`RESERVED_NAME_PREFIX`) forms — pflow's own root store keys; the runner applies it to every
caller's params (`check_parameter_names`) before adding its own;
template-reference grammar lives in `core/templates.py`. Neither check
escapes values or guarantees shell safety. External MCP schema names follow a
separate discovery/argument path; incoming MCP execution-name validation does not
establish universal coverage.

Redaction is two rules in `security_utils`: by NAME (`redact_sensitive`, whole-word matching
plus explicitly supplied keys — never substring matching) and by VALUE (`scrub_secret_values`
over `secret_values`: settings-stored values + strings under sensitive-named declared inputs,
8+ chars, #801). The value scrub runs on DATA before rendering: `build_run_outcome` (from the
recorded inputs `trace.inputs`; CLI JSON/stderr, MCP, the trailer's `json_output`; its
`RunOutcome.secrets` feeds `cli/workflow_output._handle_text_output`), `trace_report.generate_report`
and `ui/run_node.run_node_detail` (settings + `meta.inputs`), the trailer `warnings` write. A secret
produced mid-run, or exported only in the shell, is not in the set — that is the `secret: true` +
provenance design (#183).
Traces store resolved values raw for resume; a reader that displays trace content applies both
rules. `settings.env` is masked whole by value (`SettingsManager.list_env`), never by name —
`KEY`-suffixed provider names miss the rule.

## Other local constraints

- `execution_cache.py` supports probe-then-read-fields storage. Its recorded
  24-hour TTL is not enforced on retrieval.
- `tts.py` uses a separate direct-HTTP/WAV interface. Missing credentials raise
  `MissingApiKeyError`; other synthesis failures become `TTSSynthesisError` so
  narration can fall back to captions. `wav_duration()` returns zero for invalid
  audio rather than aborting playback pacing.
