# Task 126 Review: Structured Output for Claude Code Node

## Metadata

- **Implementation Date**: 2026-05-15 (single day; SDK 0.2.82 released same day)
- **Branch**: `feat/claude-code-structured-output`
- **Commits**: `8cadd39c` (plan handoff + SDK bump) → `464d8181` (progress log) → `73128956` (implementation) → `6954cfb4` (post-impl fixes)
- **Follow-up issue**: [#398](https://github.com/spinje/pflow/issues/398) — Centralized JSON Schema syntactic validation
- **Companion docs**: `task-126.md` (what/why), `implementation/implementation-plan.md` (how), `implementation/phase-0-findings.md` (SDK smoke-test discoveries), `implementation/progress-log.md` (chronological journey including 3 verification passes)

## Executive Summary

Replaced Claude Code's prompt-injected + regex-extracted structured output with `claude_agent_sdk` v0.2.82's native `output_format`/`ResultMessage.structured_output`. JSON Schema is now the canonical user-facing format on both `llm` and `claude-code` nodes. Soft-failures additionally write `shared["__warnings__"][node_id]` so workflow status surfaces as `DEGRADED` (agent-visible without knowing the `_schema_error` side-channel). Scope grew during implementation to include four cross-cutting fixes — memo cache warning rehydration, validator/runtime preflight parity, narrowed SDK exception swallow, and a new `pflow guide claude-code` topic — none of which were in the original plan.

## Implementation Overview

### What Was Built

**Core swap** (`src/pflow/nodes/claude/claude_code.py`, ~1060 lines, ~50% rewrite):
- Deleted: `_build_schema_prompt` + 4-helper regex chain (`_extract_json`, `_extract_json_from_code_block`, `_extract_json_from_raw_object`, `_extract_json_from_last_brace`).
- Added: `ClaudeAgentOptions.output_format={"type": "json_schema", "schema": <user-schema>}` wired in `_build_claude_options`; `structured_output` read directly from `ResultMessage` in `_run_claude_session`.
- Added: module-import-time probe (`claude_code.py:78-83`) that raises `ImportError` if `ResultMessage` lacks `structured_output` annotation. Protects against silent SDK field renames.
- Added: `_validate_schema` rejects empty `{}`, legacy Python-alias format, top-level non-object (including missing `type` and `oneOf`/`anyOf`/`allOf`/`enum` at root — Phase 0 + follow-up probe showed API rejects all of these).
- Added: `prep()` cross-check requires `max_turns >= 2` when `output_schema` is set.
- Added: `_emit_schema_resolved_null_warning` for templated `output_schema: ${upstream.field}` that resolved to None (silent downgrade catcher).
- Added: `_emit_soft_fail_signal` + `_store_schema_result` + `_build_schema_warning_context` helpers — soft-fail writes go through one path; warning context packs schema properties, result preview, and SDK error metadata (`errors`, `stop_reason`, `api_error_status`) for agent diagnosis.
- Sticky `is_error_from_sdk` accumulator across multiple `ResultMessage`s.
- Narrowed `_run_claude_session` exception swallow to `ProcessError` only when a prior `ResultMessage(is_error=True)` was seen; other exceptions re-raise to `exec_fallback` so remediation messages survive.

**Static validator parity** (`src/pflow/core/workflow/validator.py:165-166, 675-812`, +152 lines):
- New step 9: `_validate_node_param_semantics` → `_validate_claude_code_params`. Statically mirrors `_validate_schema` + `max_turns` cross-check so `--validate-only` and `--dry-run` reject what `prep()` would reject.
- Templated values (`${...}` strings) defer to runtime via the guard at `validator.py:704-705`.

**Memo cache rehydration** (`src/pflow/runtime/engine/instrumentation.py:348-405, 476-479`):
- Reserved keys `__pflow_stats__` and `__pflow_warnings__` stripped from `shared[node_id]` on replay.
- `__pflow_warnings__` rehydrates to root `shared["__warnings__"][node_id]` so cached DEGRADED runs stay DEGRADED.
- `write_memo_cache` persists `shared["__warnings__"][node_id]` into the cached blob under the reserved key.

**Type-vocabulary cleanup** (`src/pflow/core/types.py`):
- Deleted the "fourth surface" carve-out comment (lines 8-12 in pre-state). Its premise — that Python-alias type names were load-bearing in the prompt template — was removed by deleting `_build_schema_prompt`.

**Guide** (new `src/pflow/guide/nodes/claude-code.md` + 4 wiring edits):
- New topic; renders via `pflow guide claude-code`, integrated with dynamic registry-interface injection (`guide/__init__.py:_TOPIC_TO_NODE_TYPES`).
- Added to entry menu, capability-map fallback, save_service reserved names (`save_service.py:RESERVED_WORKFLOW_NAMES`).
- Deliberately user-facing: no SDK internals, no `__warnings__` channel mentions.

**Agent-facing reframing** (`src/pflow/mcp_server/resources/instructions/*.md`, `instruction_resources.py`, `guide/core.md`):
- Replaced "NEVER use LLM for structured extraction" prescriptions with "use templates for existing structured data; use `output_schema` on `llm`/`claude-code` for model-derived structured data." Claude Code constraints (top-level object, `max_turns >= 2`) noted.

**Examples + docs** (3 `.pflow.md` files + README + reference + architecture):
- Hard cutover from Python-alias format to JSON Schema. No back-compat shim.

**Tests** (+~700 lines net):
- Real `@dataclass ResultMessage` mock replaces auto-Mock (load-bearing ordering: must register on `mock_sdk_types` BEFORE `sys.modules` injection — `tests/CLAUDE.md` pitfall #17).
- 5 obsolete tests deleted, 4 rewritten, 15+ new (legacy-detection, top-level-object enforcement, oneOf/anyOf/allOf rejection, max_turns guard, sticky `is_error`, soft-fail kind variants, null-templated, narrow exception swallow, black-box api_warning_detector invariant, memo cache rehydration, validator parity for `--validate-only`/`--dry-run`).

### Implementation Approach

Hard cutover, no back-compat (CLAUDE.md "no users yet"). Prework SDK bump + Phase 0 smoke test landed plan-altering API constraints before any code was written. Implementation followed `implementation-plan.md` for the core swap, then accumulated four scope expansions found by review/verification:

1. **Code-review checkpoint** uncovered exception swallow + memo cache warning loss + registry exposure of `__warnings__` as template output + agent-instruction framing drift.
2. **Manual CLI verification** revealed `--validate-only` / `--dry-run` accepted what `prep()` rejected → added validator step 9.
3. **Independent adversarial verification** (review-validation-consistency + review-silent-failures + review-feature-interactions) caught the validator template-deferral regression (rejected `${upstream.schema}` composition), the `_run_claude_session` hard-error swallow, and the null-templated silent downgrade.
4. **Open-item probe** (oneOf/anyOf/allOf) confirmed runtime rejection → tightened both validators.

## Files Modified/Created

### Core Changes

- `src/pflow/nodes/claude/claude_code.py` — central refactor. New surface area: import probe, `_validate_schema` constraints, `_emit_schema_resolved_null_warning`, `_emit_soft_fail_signal`, `_store_schema_result`, `_build_schema_warning_context`. Narrowed `_run_claude_session` exception handling. Removed: `_build_schema_prompt`, `_build_prompt`, `_build_system_prompt`, 4 `_extract_json*` helpers.
- `src/pflow/core/workflow/validator.py` — added step 9 (`_validate_node_param_semantics`) + `_validate_claude_code_params` + `_looks_like_legacy_python_alias_schema` + `_claude_code_param_error`. Defer-on-template guard at line 704.
- `src/pflow/runtime/engine/instrumentation.py` — `apply_memo_hit` strips reserved keys + rehydrates warnings to root; `write_memo_cache` persists warnings under `__pflow_warnings__`.
- `src/pflow/core/types.py` — deleted fourth-surface carve-out comment.
- `src/pflow/core/workflow/save_service.py` — `"claude-code"` added to `RESERVED_WORKFLOW_NAMES`.
- `src/pflow/guide/nodes/claude-code.md` (new), `guide/__init__.py`, `guide/entry.md`, `guide/core.md`, `guide/CLAUDE.md` — new topic + integration.
- `src/pflow/mcp_server/resources/instruction_resources.py` + 2 instruction `.md` files — reframed structured-data guidance.
- `pyproject.toml`, `uv.lock` — `claude-agent-sdk>=0.2.82`.

### Test Files

- `tests/test_nodes/test_claude/test_claude_code.py` — 628 lines net delta. Real `@dataclass` `ResultMessage` mock; 15+ new tests.
- `tests/test_cli/test_validate_only.py` — new `TestValidateOnlyClaudeCodeStructuredOutput` class (5 cases).
- `tests/test_cli/test_dry_run.py` — `test_dry_run_rejects_claude_code_invalid_schema_before_plan`.
- `tests/test_cli/test_guide.py` — direct topic rendering + `.pflow.md` workflow-scoped auto-detection.
- `tests/test_runtime/test_memoization_integration.py` — cache warning rehydration regression test.
- `tests/CLAUDE.md` — pitfall #17 updated with the `@dataclass` ordering invariant.
- `tests/shared/markdown_utils.py:119` — comment updated (output_schema is node-agnostic now).

**Critical tests** (catch real regressions, not coverage):
- `test_non_process_error_after_is_error_re_raises` — pins the narrow exception swallow against reverting to catch-all `except Exception`.
- `test_soft_fail_output_shape_not_classified_as_api_warning` — black-box pin: claude-code's `{result, _schema_error, llm_usage}` shape never reaches `api_warning_detector._is_validation_error` because `extract_error_message` is shape-gated. Adding an `error`/`ok`/`success`/`status` key for debug visibility would break this test before regression ships.
- `test_sdk_error_with_structured_output_no_node_id_falls_back_to_schema_error` — pins the `setdefault("_schema_error", ...)` fallback when `node_id` is unbound (test paths).
- Memo cache rehydration test — pins DEGRADED preservation across cache hits.
- `TestValidateOnlyClaudeCodeStructuredOutput` + dry-run mirror — pins validator/runtime preflight parity.

## Integration Points & Dependencies

### Incoming Dependencies (consumers of this work)

- **`runtime/workflow_trace.py:457-466`** consumes `shared["__warnings__"]` to flip workflow status → `DEGRADED`. This is the agent-visible signal.
- **`runtime/engine/instrumentation.py`** memo cache reads/writes the new `__pflow_warnings__` reserved key.
- **CLI `--validate-only` and `--dry-run`** consume validator step 9 output.
- **`pflow guide claude-code`** consumes the new topic + registry interface injection.
- **`save_service.RESERVED_WORKFLOW_NAMES`** protects the new guide name from clobbering.
- **Future**: issue #398 (centralized JSON Schema validator) will share `_looks_like_legacy_python_alias_schema` + the JSON Schema markers set with LLM node.

### Outgoing Dependencies

- **`claude_agent_sdk>=0.2.82`** for `ClaudeAgentOptions.output_format` + `ResultMessage.structured_output`. Floor pinned in `pyproject.toml`. Import probe at `claude_code.py:78-83` guards against future field renames in the SDK.
- **`runtime/compilation/compiler.py:299`** sets `self.node_id` — retrieved via `getattr(self, "node_id", None)` in `post()`. Pattern mirrored from `nodes/llm/llm.py:795`.
- **`runtime/template_resolver.TemplateResolver`** (validator step 9 uses substring `${` for template detection — not the full extractor; sufficient because the runtime `_validate_schema` does the dict-shape check anyway).

### Shared Store Keys

| Key | Type | Producer | Purpose |
|---|---|---|---|
| `result` | `str` \| `dict` \| `list` \| primitive | always written | Free-form text, parsed JSON on schema success, or raw text on soft-fail |
| `_schema_error` | `str` | soft-fail paths only | Human-readable message. Written via `setdefault` — first writer wins (null-template warning beats later soft-fail signal). |
| `__warnings__[node_id]` | `dict{kind, text, context}` | soft-fail paths only | Root-level warning channel → flips workflow status to DEGRADED. Kinds: `claude_code.schema_not_satisfied`, `claude_code.sdk_error_no_structured_output`, `claude_code.sdk_error_with_structured_output`, `claude_code.output_schema_resolved_to_null` |
| `llm_usage` | `dict` | always written (`{}` if metadata unavailable) | Token counts, cost, duration, session_id |
| `_claude_progress` | `list[dict]` | always written if non-empty | Streaming progress events for tracing |
| `_claude_tools` | `list[dict]` | always written if non-empty | Tool-use audit trail |

**Reserved memo-cache-only keys** (NEVER appear in live `shared[node_id]`):
- `__pflow_stats__` — engine duration metadata for `--dry-run` historical estimates.
- `__pflow_warnings__` — node warning blob (rehydrated to root `shared["__warnings__"][node_id]` on cache hit).

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative rejected |
|---|---|---|
| Native SDK `output_format`, hard cutover | Provider-enforced compliance; no prompt boilerplate competing with user system prompt; no regex parsing. No users → no back-compat cost. | Keep prompt-injection but switch the format to JSON Schema — still fragile, still requires regex extraction. |
| Soft-fail (`action="default"` + `_schema_error` + `__warnings__`) | Claude Code sessions are expensive (~$0.05+) and agentic; raw text is often salvageable. Retries would burn $$ on the same model behavior. | Hard-error like LLM node — too costly for agentic sessions. |
| `__warnings__` channel (new) | Agent-visible DEGRADED status without requiring agents to know about `_schema_error` side-channel. Reuses existing trace mechanism. | Make schema misses route through `on-error:` edges — would surprise authors and require explicit error handlers on every claude-code node. |
| `setdefault("_schema_error", msg)` | First-writer-wins so null-template warning (written in `prep`) survives later soft-fail writes (written in `post`). | Last-writer-wins (`shared["_schema_error"] = msg`) — null-template warning would be silently stomped. |
| Top-level `type: object` enforced at prep + preflight | Phase 0 + follow-up probe: API rejects ALL non-object top-level schemas (incl. `oneOf`/`anyOf`/`allOf`/`enum`/missing-type) with a 400 surfacing as opaque `is_error=True`. | Trust SDK to surface clear error — opaque 400 message blamed the model, not the schema. |
| `max_turns >= 2` enforced | Phase 0: `max_turns: 1` fails for structured output with "Reached maximum number of turns" — not actionable. | Document only — users would still hit it without preflight catch. |
| Module-import-time SDK probe | `getattr(ResultMessage, "structured_output", None)` would silently return None on rename → soft-fail every call → "model didn't comply" blame on model. Loud import failure is correct. | Runtime probe on first call — failure mode is delayed and per-workflow. |
| Validator step 9 mirrors runtime `_validate_schema` | Without it, `--validate-only` and `--dry-run` give clean preflight for workflows that fail immediately at runtime. Asymmetric preflight is worse than no preflight. | Trust prep() — silent CLI/--dry-run drift. |
| Defer-on-template policy at validator | Composition pattern `output_schema: ${upstream.schema}` is valid and tested live. Hard-rejecting templates at preflight would block this. | Hard-reject templates at preflight — caught by user-reported regression during verification pass. |
| Narrow exception swallow to `ProcessError` only | SDK pairs `ResultMessage(is_error=True)` with non-zero CLI exit (raised as `ProcessError`). Catch-all `except Exception` was hiding `CLINotFoundError` ("install with: npm…") and `CLIConnectionError` ("run `claude doctor`") remediation paths. | Catch-all `except Exception` — silently drops every actionable SDK error after the first `is_error=True`. |
| Memo cache reserved keys | Without `__pflow_warnings__` persistence, cached DEGRADED runs replay as SUCCESS (silent demotion). | Don't cache warnings — replay would re-run the node, defeating cache. |

### Technical Debt Incurred

- **Validator step 9 manually mirrors runtime `_validate_schema`.** Two places to update when constraints change. Issue #398 will consolidate this for both `llm` and `claude-code` nodes.
- **Legacy-format heuristic has false-positive risk.** `_looks_like_legacy_python_alias_format` checks if any value is a dict with `type ∈ {str, int, bool, list, dict, float}` AND no JSON Schema markers at root. A schema like `{"my_field": {"type": "str"}}` with intentional non-standard usage would be rejected. No users today; acceptable.
- **Soft-fail message strings are unpinned except via `api_warning_detector` black-box test.** A future reword adding `"error"`/`"ok"`/`"success"`/`"status"` keys (not strings) to claude-code output would flip soft-fail → hard error. The pin test catches the SHAPE drift, not message text drift.
- **LLM node has the same `node_id is None` guard pattern.** Same blind-spot for direct `node.run()` test paths. Deliberately not fixed here — consistency between the two nodes matters more than fixing one. Both should be fixed together if the gap matters.
- **`__pflow_warnings__` reserved key is engine-private.** Implicitly couples `claude_code.py`'s warning writes to `instrumentation.py`'s cache handling. If any other node starts writing root-level `__warnings__` from `post()`, it gets cache-rehydration for free — but the coupling is undocumented outside `apply_memo_hit`'s docstring.

## Testing Implementation

### Test Strategy Applied

1. **Real `@dataclass ResultMessage` mock** replaces auto-Mock. Auto-Mock's `isinstance()` checks succeed silently against any type, masking real behavioral bugs (e.g., the import probe relies on `__annotations__` — auto-Mock has it as a `MagicMock` attribute, not the real dict).
2. **Black-box invariant tests** preferred over substring-string tests. The `api_warning_detector` pin tests the production property (output shape doesn't match detector's extraction gates), not message text equality.
3. **Defer-on-template guard tested via composition pattern** — `composed-schema.pflow.md` scratchpad workflow exercises upstream code node → JSON Schema → claude-code consumer. Lives in `scratchpads/manual-pflow-verification/` (not committed) but tested via direct unit tests.
4. **Symmetric coverage for `--validate-only` and `--dry-run`** — every static check in `_validate_claude_code_params` has paired tests in both CLI test files.
5. **Real-API smoke test** — `Phase 5.4` ran `examples/nodes/claude-code/claude-code-schema.pflow.md` against the real Anthropic API via Claude Max subscription. Live structured output succeeded; 4 nodes completed; templates `${review.result.*}` resolved cleanly. Confirmed zero-config subscription auth path.

### Critical Test Cases

- `test_non_process_error_after_is_error_re_raises` — guards the narrow swallow against future catch-all regression.
- `test_soft_fail_output_shape_not_classified_as_api_warning` — black-box pin against `api_warning_detector` extraction-gate invariant.
- `test_top_level_{oneOf,anyOf,allOf,missing_type}_schema_rejected` — pins follow-up probe findings.
- `test_top_level_object_with_oneOf_accepted` — pins that combinators INSIDE an object wrapper still work (the workaround is sound).
- `test_dry_run_rejects_claude_code_invalid_schema_before_plan` — pins validator/runtime preflight parity.
- `test_sdk_error_with_structured_output_no_node_id_falls_back_to_schema_error` — pins `setdefault` fallback for test paths.
- Memo cache rehydration test — pins DEGRADED preservation across cache hits.
- `test_claude_code_guide_documents_structured_output_without_internals` — guards guide-user-facingness (e.g., reworded "SDK" → "provider error" caught here).

## Unexpected Discoveries

### Gotchas Encountered

1. **Anthropic API rejects non-object top-level schemas in tool-use wrappers.** The SDK passes our `output_format` through as a custom tool's `input_schema`. The LLM node has no such restriction (LiteLLM/OpenAI accept top-level arrays/primitives). This is **Claude-Code-specific** and required explicit user-facing documentation.
2. **`max_turns: 1` opaque failure.** Structured output requires at least 2 turns (one to plan, one to emit). SDK raises "Reached maximum number of turns" with no hint it's schema-related.
3. **Schema typos like `type: intger` are silently accepted by the API.** No 400; model produces free-form text; soft-fail says "model didn't comply" — misleading. Motivates #398.
4. **Memo cache replay silently demotes DEGRADED → SUCCESS.** Found via cross-feature review (review-feature-interactions agent). Without `__pflow_warnings__` rehydration, every cached schema soft-fail loses the warning signal. This was the highest-impact silent-failure bug uncovered.
5. **`_run_claude_session`'s catch-all `except Exception` hid every SDK exception after the first `ResultMessage(is_error=True)`.** Users lost `CLINotFoundError` → "install with: npm install -g …", `CLIConnectionError` → "run `claude doctor`" remediation paths. Found via review-silent-failures agent.
6. **Templated `output_schema: ${upstream.field}` resolving to None silently downgrades to free-form.** Workflow status returned `success` instead of `degraded`. Workflow author got no signal their schema reference missed. Found via independent adversarial verification.
7. **Validator template-deferral asymmetry.** First-draft validator hard-rejected `output_schema: ${...}` strings ("got str"). Pre-Task-126 code accepted them via runtime resolution. The fix (5-line guard) restored the composition pattern.
8. **Auto-Mock `ResultMessage` was a latent bug.** `isinstance(msg, ResultMessage)` would TypeError at runtime because the mock was an instance, not a class. Caught by codebase-searcher before tests ran. Fixed via real `@dataclass`.
9. **Subscription auth (Claude Pro/Max) needs zero config.** No `ANTHROPIC_API_KEY` required; the bundled `claude` CLI auto-detects OAuth keychain. Setting `ANTHROPIC_API_KEY` forces pay-as-you-go billing. Phase 5 docs updated.

### Edge Cases Found

- Top-level `oneOf` / `anyOf` / `allOf` / `enum` / `const` / missing-`type` all fail at the API. Original plan said "may pass" — wrong. All rejected at preflight now.
- Empty `{}` schema is a typo, not a no-op — rejected.
- `output_schema = None` (key absent) is a no-op; `output_schema: ${none-producing-template}` is DEGRADED-worthy.
- Sticky `is_error_from_sdk` across multi-message streams (defensive — Phase 0 didn't observe multi-message, but the logic is correct).
- `node_id` is None in direct `node.run()` test paths → `__warnings__` write skipped but `_schema_error` still written via `setdefault`.

## Patterns Established

### Reusable Patterns

**1. Module-import-time SDK field-presence probe** (`claude_code.py:78-83`):
```python
if "structured_output" not in getattr(ResultMessage, "__annotations__", {}):
    raise ImportError(
        "claude_agent_sdk.types.ResultMessage has no 'structured_output' field. "
        "pflow's Claude Code node requires claude-agent-sdk>=0.2.82 ..."
    )
```
Loud at import time beats silent `getattr(..., None)` returning None at runtime. Use this for any external library whose attribute layout matters.

**2. Reserved memo-cache keys for root-level shared state** (`instrumentation.py:apply_memo_hit`, `write_memo_cache`):
```python
reserved_keys = {"__pflow_stats__", "__pflow_warnings__"}
restored = {k: v for k, v in cached_output.items() if k not in reserved_keys}
cached_warning = cached_output.get("__pflow_warnings__")
if cached_warning is not None:
    shared.setdefault("__warnings__", {})[node_id] = cached_warning
```
Any future node writing root-level shared state (`shared["__warnings__"]`, `shared["__errors__"]`, etc.) from `post()` needs cache rehydration or DEGRADED → SUCCESS silent demotion will hit. Add to the reserved set.

**3. Per-node static param semantics validator step** (`validator.py:_validate_node_param_semantics`):
```python
def _validate_node_param_semantics(workflow_ir):
    diagnostics = []
    for node in workflow_ir.get("nodes", []):
        if node.get("type") != "claude-code":
            continue
        diagnostics.extend(WorkflowValidator._validate_claude_code_params(node.get("id"), node.get("params", {})))
    return diagnostics
```
Per-node static checks that mirror runtime `prep()`. Mandatory whenever a node adds a `prep`-only constraint with high false-acceptance cost (failed runtime calls cost $$).

**4. Defer-on-template guard** (`validator.py:704-705`):
```python
if isinstance(output_schema, str) and "${" in output_schema:
    return []  # defer to runtime resolution
```
Static validators that can't resolve templates must defer, not reject. Symmetric with `max_turns`' `try/except int()` defer policy.

**5. First-writer-wins via `setdefault` for soft-fail signals** (`claude_code.py:_emit_soft_fail_signal`):
```python
shared.setdefault("_schema_error", msg)  # earlier null-template warning wins
if node_id is not None:
    shared.setdefault("__warnings__", {})[node_id] = {...}
```
Multiple code paths may write soft-fail signals (prep-time null-template detection, post-time schema-not-satisfied). First-writer-wins preserves the earliest, most-specific diagnosis.

**6. Black-box invariant test for cross-feature contracts**:
```python
def test_soft_fail_output_shape_not_classified_as_api_warning():
    shared = {"review": <produced_shape>}
    assert detect_api_warning("review", shared) is None
```
Pin against production property (output shape vs. detector's extraction gates), not internals (message string substrings). A future contributor adding an `error` key to debug claude-code output breaks this test before the regression ships.

**7. `@dataclass` test mock for SDK types** (test pattern):
```python
@dataclass
class ResultMessage:
    structured_output: Any = None
    is_error: bool = False
    ...
```
`@dataclass` auto-populates `__annotations__`, which the import probe checks. Register on `mock_sdk_types.ResultMessage` BEFORE the `sys.modules[...]` assignment.

### Anti-Patterns to Avoid

- **Catch-all `except Exception` in SDK loops.** Hides every actionable SDK error type. Narrow to the specific exception class that pairs with the soft-fail state.
- **Pinning message strings via equality.** Brittle to rewording. Pin via substring (`"X" in shared["_schema_error"]`) or, better, via the production invariant (output shape).
- **Auto-Mock for classes used in `isinstance()` checks.** `isinstance(x, AutoMock_instance)` raises TypeError. Use real `@dataclass` or real class.
- **Hard-reject templated values at static validators.** Composition patterns like `${upstream.schema}` are legitimate. Defer to runtime.
- **Writing soft-fail signals without `setdefault`.** Earlier prep-time signals get stomped by later post-time ones.

## Breaking Changes

### API/Interface Changes

- **`output_schema` syntax** on `claude-code` nodes: Python-alias format → JSON Schema. Hard cutover. Legacy format produces a clear migration error at `prep()` time.
- **Result type** on schema success: previously a dict with auto-filled `None` for missing optional fields; now matches the SDK's `structured_output` exactly (missing optional fields are simply absent).
- **Result type** on schema soft-fail: was a dict-with-Nones; now raw text string + `_schema_error` + `__warnings__` signal. Downstream nodes that previously accessed `${node.result.field}` after a soft-fail now need to branch on `${node._schema_error}` first.
- **Registry interface no longer exposes `__warnings__`** as a node output. The DEGRADED behavior is documented in prose; `${node.__warnings__}` will not resolve via template (it's root-level, not node-level).

### Behavioral Changes

- Schema soft-failures now flip workflow status to `DEGRADED` (was: `success` with side-channel `_schema_error` only).
- `max_turns < 2` with `output_schema` is rejected at preflight (was: opaque SDK error at runtime).
- Top-level non-object schemas rejected at preflight (was: opaque API 400 at runtime).
- Templated `output_schema` resolving to None now emits a `claude_code.output_schema_resolved_to_null` warning (was: silent downgrade to free-form mode).
- Memo cache replay preserves DEGRADED status (was: silently demoted to SUCCESS).
- `claude-code` is now a reserved workflow name (was: collision possible with the new `pflow guide claude-code` topic).

## Future Considerations

### Extension Points

- **Issue #398 (centralized JSON Schema validation)** will likely add a new step between current 8 and 9 in `WorkflowValidator.validate()`. The per-node step 9 should remain — it handles node-specific constraints beyond JSON Schema syntactic validity (top-level object enforcement, max_turns guard).
- **`_build_schema_warning_context`** already threads SDK 0.2.82's new `errors` / `stop_reason` / `api_error_status` fields into the warning context. Future UX work could surface these in `pflow ... --output-format json` warnings without further node changes.
- **Memo cache reserved-key pattern** is the template for any new root-level shared state. Add to the `reserved_keys` set in `apply_memo_hit` and the corresponding write in `write_memo_cache`.
- **`pflow guide claude-code`** topic uses the same registry-interface-injection pattern as other node topics. Future agentic nodes should follow this pattern (entry: `_TOPIC_TO_NODE_TYPES` mapping).

### Scalability Concerns

- The legacy-format heuristic walks all values of the schema dict at every `prep()`. Negligible at current usage; non-issue.
- Validator step 9 walks all nodes at every validation call. Trivial cost.

## AI Agent Guidance

### Quick Start for Related Tasks

**If you're working on Task 99 (Expose pflow Tools to Claude Code Node):**
1. Read `_build_claude_options` (`claude_code.py:545-589`) — this is where SDK options get wired. Adding tools means extending `options_kwargs`.
2. Don't add `__warnings__` keys unless you also follow the reserved-cache-key pattern in `instrumentation.py`.
3. The `allowed_tools` / `disallowed_tools` params already exist; check `_validate_tools` and `_validate_disallowed_tools` first.

**If you're working on Issue #398 (centralized JSON Schema validation):**
1. Read `_looks_like_legacy_python_alias_schema` in both `claude_code.py:287-294` AND `validator.py:783-789`. These are duplicated. Your job is to consolidate.
2. The JSON Schema markers set `{"type", "$ref", "$schema", "oneOf", "anyOf", "allOf", "enum", "const"}` is the same in both places.
3. Add validation between current steps 8 and 9 in `WorkflowValidator.validate()`. The per-node step 9 should remain for node-specific constraints (top-level-object, max_turns).
4. The LLM node has NO top-level-object restriction (LiteLLM accepts arrays/primitives). Don't apply Claude Code's constraint there.

**If you're adding `__warnings__` writes from any node's `post()`:**
1. Use `shared.setdefault("__warnings__", {})[node_id] = {kind, text, context}` shape.
2. Add your node's `__pflow_warnings__` reserved-key handling to `instrumentation.py:apply_memo_hit` and `write_memo_cache` — OR confirm the existing wildcard handling covers you (it does, as of 6954cfb4).
3. The `kind` field is a dotted string namespaced by node type: `"<node_type>.<reason>"`. Reused kinds: `schema_not_satisfied`, `sdk_error_no_structured_output`, `sdk_error_with_structured_output`, `output_schema_resolved_to_null`.
4. DEGRADED workflow status is automatic via `runtime/workflow_trace.py:457-466` — you don't write status directly.

**If you're modifying `_validate_schema` or `_validate_claude_code_params`:**
1. UPDATE BOTH. They mirror each other intentionally. Drift is silently breaking — runtime rejects what preflight accepts (or vice versa).
2. Use the defer-on-template guard for any templated value: `if isinstance(value, str) and "${" in value: return [] / pass`.
3. New cases need paired tests in `test_claude_code.py` + `test_validate_only.py` + `test_dry_run.py`.

### Common Pitfalls

1. **Reverting the narrow exception swallow** to catch-all `except Exception` in `_run_claude_session`. Breaks `test_non_process_error_after_is_error_re_raises`. Hides `CLINotFoundError` / `CLIConnectionError` remediation messages.
2. **Removing `setdefault("_schema_error", ...)` in favor of `=`** — null-template warning gets clobbered by later soft-fail signals. Breaks templated-schema-resolving-to-None UX.
3. **Adding `error`/`ok`/`success`/`status` keys to claude-code's `shared[node_id]` output**. Will trigger `api_warning_detector._is_validation_error` and flip soft-fail → hard error. Breaks `test_soft_fail_output_shape_not_classified_as_api_warning`.
4. **Forgetting to use `@dataclass` when adding fields to the test `ResultMessage` mock.** The import probe checks `__annotations__`. Auto-Mock's `__annotations__` is a `MagicMock` attribute, not a real dict.
5. **Registering `mock_sdk_types.ResultMessage` AFTER `sys.modules["claude_agent_sdk.types"] = mock_sdk_types`.** The import probe runs at the SDK import line, before the late registration. Re-read `tests/CLAUDE.md` pitfall #17.
6. **Assuming schema misses route through `- on-error:` edges.** They don't — `post()` always returns `"default"`. Workflow authors must branch on `${node._schema_error}` (or check `DEGRADED` status).
7. **Adding back `_build_prompt` / `_build_system_prompt` as wrappers.** They were inlined intentionally; the schema framing they used to do is now handled by the SDK.

### Test-First Recommendations

Before modifying claude_code.py or validator.py step 9, run:
```bash
uv run pytest tests/test_nodes/test_claude/ tests/test_cli/test_validate_only.py tests/test_cli/test_dry_run.py tests/test_runtime/test_memoization_integration.py -q
```
Should report ~105+ passed. If a baseline fails before your changes, you have an environment issue (likely sandbox `uv` panic class — see progress log "Verification blockers").

After modifying `_validate_schema`:
```bash
uv run pytest tests/test_nodes/test_claude/test_claude_code.py -k "validate_schema or schema_rejected or top_level" -q
uv run pytest tests/test_cli/test_validate_only.py::TestValidateOnlyClaudeCodeStructuredOutput -q
uv run pytest tests/test_cli/test_dry_run.py::test_dry_run_rejects_claude_code_invalid_schema_before_plan -q
```

After modifying memo cache or warning writes:
```bash
uv run pytest tests/test_runtime/test_memoization_integration.py -q
```

For end-to-end smoke (subscription required — zero config if logged into `claude` CLI):
```bash
unset ANTHROPIC_API_KEY
uv run pflow examples/nodes/claude-code/claude-code-schema.pflow.md
```
Expect: `success: true`, structured `review.result` dict, `${review.result.*}` templates resolve in downstream `write-file` nodes.

---

*Generated from implementation context of Task 126 (commits 8cadd39c → 6954cfb4 on `feat/claude-code-structured-output`)*
