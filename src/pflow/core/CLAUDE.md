# Core Module

Shared parsing, diagnostics, configuration, and execution utilities.

## Task Navigation

| Task | Start here |
|---|---|
| Change markdown parsing or source attribution | `markdown_parser.py`; author-content YAML in `yaml_utils.py` |
| Change IR shape or declared types | `ir_schema.py::FLOW_IR_SCHEMA`, `validate_ir`; `types.py::TypeSpec` |
| Add an error or change diagnostic rendering | `exceptions.py`, `diagnostic.py`, `diagnostic_render.py` — see below |
| Change node lifecycle/retry primitives | `node.py`; node patterns in `../nodes/CLAUDE.md` |
| Change human-decision payloads | `gate.py`; execution policy belongs in `runtime/engine/gate.py` |
| Change save/load, validation, discovery, or static graphs | `workflow/CLAUDE.md` |
| Change LLM requests, normalization, or provider policy | `llm_client.py::complete`, `litellm_runtime.py`, `llm_reasoning_map.py` |
| Change model/key selection or settings | `llm_config.py`, `llm_providers.py`, `settings.py` |
| Change prompt-cache rendering/overlap/TTL | `prompt_cache.py`, `prompt_refs.py`, `cache_overlap.py`, `cache_ttl.py`; capabilities in `llm_capabilities.py` |
| Change cache recommendations or analysis reports | `prompt_cache_analysis/CLAUDE.md` |
| Change stdin or terminal progress | `shell_integration.py`, `output_controller.py` |
| Change usage aggregation or trace reports | `metrics.py`, `llm_usage.py`, `trace_tree.py`, `trace_report.py` |
| Read persisted traces | `trace_io.py::load_trace_file` — shared JSONL reconstruction boundary |
| Change input coercion, name rules, or redaction | `param_coercion.py`, `validation_utils.py`, `security_utils.py` |
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
must not depend on the renderer. Template errors carry `unresolved_references`,
including permissive-mode warnings. `OutputResolutionError` carries per-output
`output_failures` with their own source locations and no node attribution. Keep
these structures rather than canned suggestions. Context-key conventions live in
`runtime/template_validation/CLAUDE.md`.

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
those comparisons as observed billing.

## llm_config.py and settings.py

`get_model_for_feature()` always supplies a model; `get_default_workflow_model()`
can return `None`. Default-model detection is cached; `clear_model_cache()`
resets process state for tests or changed keys.

`resolve_provider_api_key()` owns environment/settings precedence and aliases.
Keep presence checks and request keys on this resolver. Settings injection records
provenance so genuinely exported environment aliases still take precedence.

Settings saves are atomic and permission-restricted. Node filtering happens at
registry **load**, not storage; MCP matching includes tool/server aliases.
Workflow input precedence is separately owned by
`runtime/compilation/ir_preparation.py::prepare_inputs`, not the provider resolver.

## Shell and progress boundaries

`stdin_has_data()` recognizes real pipes: Unix FIFO detection, Windows pipe-handle
detection. Readiness polling can hang on external-agent character-device stdin.

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
compatibility checks. See `architecture/core-concepts/data-type-coercion.md`.

`coerce_param_for_node()` only converts dict/list to JSON for expected `str`.
`coerce_workflow_input()` handles declared workflow types and warns rather than
raising on failed coercion. Do not interchange these pipeline stages.

`is_valid_parameter_name()` checks names, including reserved `__*__` keys;
template-reference grammar lives in `runtime/template_resolver.py`. Neither check
escapes values or guarantees shell safety. External MCP schema names follow a
separate discovery/argument path; incoming MCP execution-name validation does not
establish universal coverage.

Redaction uses whole-word sensitive-name matching plus explicitly supplied keys.
Use `security_utils` instead of substring matching. Arbitrary secrets embedded in
values may remain visible; this is not universal secret detection.

## Other local constraints

- `execution_cache.py` supports probe-then-read-fields storage. Its recorded
  24-hour TTL is not enforced on retrieval.
- `tts.py` uses a separate direct-HTTP/WAV interface. Missing credentials raise
  `MissingApiKeyError`; other synthesis failures become `TTSSynthesisError` so
  narration can fall back to captions. `wav_duration()` returns zero for invalid
  audio rather than aborting playback pacing.
