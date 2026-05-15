# Task 126 Progress Log

## Status

| Phase | Status | Commit |
|---|---|---|
| Prework: SDK upgrade to 0.2.82 | ✅ done | `8cadd39c` |
| Phase 0: SDK smoke test | ✅ done | `8cadd39c` |
| Phase 1: Refactor claude_code.py | ✅ done | — |
| Phase 2: Tests | ✅ done | — |
| Code review checkpoint | ✅ done | — |
| Phase 3: Examples + docs | ✅ done | — |
| Phase 4: types.py + CHANGELOG | ✅ done | — |
| Phase 5: Final verification | ⚠️ partial; blockers documented | — |

GH follow-up issue filed: [#398](https://github.com/spinje/pflow/issues/398).

## 2026-05-15 — Prework complete

`claude-agent-sdk` floor bumped `>=0.1.17` → `>=0.2.82`. Latest published version is 0.2.82 (released same day); chose it over 0.1.81 (last 0.1.x) per user direction. Field compatibility verified before bump: `ClaudeAgentOptions.output_format` and `ResultMessage.structured_output` both present; old-version fields are a strict subset of 0.2.82's.

`uv lock` resolved cleanly. `uv sync` installed. **Existing test suite passes: 47/47 Claude Code tests** against the upgraded SDK without code changes — confirms field-level backwards compatibility.

## 2026-05-15 — Phase 0 complete

Smoke test run via Claude Max subscription (no `ANTHROPIC_API_KEY` set). Detailed findings: `phase-0-findings.md`. Plan-altering surprises propagated into `implementation-plan.md`:

| Phase 0 surprise | Plan change |
|---|---|
| API rejects non-object top-level schemas (`type: array`, primitives) with `400 tools.9.custom.input_schema.type: Input should be 'object'` | `_validate_schema` (Phase 1.2) now rejects at prep time with clear error pointing to wrapper workaround. `test_array_top_level_schema` and `test_primitive_top_level_schema` removed; `test_top_level_array_schema_rejected` + `test_top_level_primitive_schema_rejected` added. Edge case table updated. |
| `max_turns: 1` fails for structured output with opaque "Reached maximum number of turns" | New Phase 1.2b added: cross-cutting validation in `prep` requires `max_turns >= 2` when `output_schema` is set. New test `test_max_turns_too_low_with_schema_rejected`. |
| Schema typos (e.g. `type: intger`) silently accepted by API → soft-fail with misleading "model didn't comply" message | No code change in Task 126 (would duplicate logic with LLM node). Documented in `_validate_schema` docstring; concretely motivates #398. |
| Subscription auth via bundled `claude` CLI works zero-config | Phase 5.4 manual-smoke wording updated to drop API-key requirement for subscription users. |

## Open items for implementing agent

1. **First task**: Phase 1 of `implementation-plan.md` — refactor `src/pflow/nodes/claude/claude_code.py`. Read `phase-0-findings.md` first (linked from plan's Orientation section).

2. **`oneOf`/`anyOf`/`allOf` top-level untested**: Phase 0 only probed `type: array` and primitive top-levels. `_validate_schema` currently passes these through (no top-level `type` key → no rejection). If real-world usage shows the API also rejects these wrappers, tighten the validation. Test `test_oneOf_top_level_schema_accepted` may need updating if behavior is discovered different.

3. **SDK 0.2.82 added fields not yet used** (`ResultMessage.errors`, `stop_reason`, `api_error_status`). Not in scope; mentioned in `phase-0-findings.md` if a natural use emerges during Phase 1.

4. **Scratchpads cleanup at Phase 5.6**: `scratchpads/task_126/` contains the smoke test script + raw output. Not committed. Delete in Phase 5.6.

## Decisions made during prework (not in task spec or plan)

- **Target SDK**: 0.2.82 (latest, released same-day) over 0.1.81 (last 0.1.x). User-directed choice. Risk acknowledged: 0.2.x is a fresh major bump; rolling back to 0.1.81 remains an option if Phase 1+ surfaces 0.2-specific breakage.
- **`_build_llm_usage` extraction**: confirmed inline (no helper). Plan was ambiguous; pinned in `implementation-plan.md` Phase 1.7.
- **`node_id` retrieval pattern**: confirmed `getattr(self, "node_id", None)` per `llm.py:795`; skip `__warnings__` if `None` per `llm.py:296`. Plan was ambiguous; pinned in Phase 1.8.
- **Test mock for `ResultMessage`**: `@dataclass` (auto-populates `__annotations__` for the Phase 1.0 import probe). Plan was ambiguous; pinned in Phase 2.1.

## 2026-05-15 — Implementation pass complete

Replaced Claude Code schema prompt injection and regex JSON extraction with native SDK structured output:
`ClaudeAgentOptions.output_format={"type": "json_schema", "schema": ...}` and `ResultMessage.structured_output`.
`output_schema` now uses JSON Schema, rejects legacy Python-alias format, rejects empty dicts, rejects explicit non-object top-level `type`, and requires `max_turns >= 2` when schema is set.

Code review checkpoint found two runtime issues beyond the original step list:

| Finding | Resolution |
|---|---|
| SDK can yield `ResultMessage(is_error=True)` and then raise when the CLI exits non-zero, bypassing `post()` and losing intended soft-fail warnings | `_run_claude_session` now preserves accumulated result state when an error `ResultMessage` was seen before the trailing SDK exception; tests cover both `is_error` with and without structured output. |
| Memo cache replay dropped root `__warnings__`, turning cached schema soft-failures from DEGRADED into SUCCESS | Memo writes now persist node warnings under reserved `__pflow_warnings__`; memo replay rehydrates `shared["__warnings__"][node_id]` while keeping reserved metadata out of `shared[node_id]`. Regression test added. |
| Registry Interface exposed `__warnings__` as a template-visible node output | Removed from Interface blocks and docs output table; kept DEGRADED behavior documented in prose. Registry metadata test added. |
| Agent-facing guidance still framed structured extraction as LLM-only or prompt-only | Updated core guide and MCP instruction resources to recommend templates for existing structured data and `output_schema` on `llm`/`claude-code` for model-derived structured data. |

Deliberate deviations / non-changes:
- Kept top-level `oneOf` / `anyOf` / `allOf` accepted at prep time. Reviewers recommended rejecting schemas without `type: object`, but the implementation plan explicitly says these pass prep and may fail at runtime; changing that would be a product decision, not an implementation correction.
- Did not add local JSON Schema syntactic validation despite reviewer recommendation. The task explicitly defers centralized JSON Schema validation for both LLM and Claude Code nodes to issue #398; adding it here would create node drift.
- Did not implement template-validator enrichment from static Claude Code schemas. That is useful, but not in Task 126's plan and would touch template validation/batch behavior broadly; should be a follow-up after #398 or alongside it.

Verification performed:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_nodes/test_claude/ tests/test_docs/test_example_validation.py tests/test_runtime/test_memoization_integration.py -q` → `71 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_markdown_parser.py::TestCodeBlockParsing::test_yaml_output_schema_block -q` → `1 passed`
- Registry metadata probe confirmed outputs are `result`, `_schema_error`, `llm_usage` and params include `output_schema`, `disallowed_tools`, `max_turns`.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy` → success.
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m deptry src` → success.
- Focused ruff on modified Python files → success.

Verification blockers / residual failures:
- Near-full sandbox pytest command reached `6780 passed, 19 skipped, 8 failed`. Five failures are subprocess tests invoking Homebrew `uv`, matching the sandbox-testing skill's known `uv` panic class (`Attempted to create a NULL object` / `Tokio executor failed`). Three additional workflow-executor/sub-workflow tests fail in isolation in files untouched by this task (`test_failed_node_invariant.py`, `test_prep_error_action.py`), returning `error` instead of expected routed actions or missing child trace events; treated as pre-existing branch blockers, not Task 126 regressions.
- Full `ruff check .` fails on unrelated existing RUF043/RUF059 issues in tests outside this task. Focused ruff on modified Python files is clean.
- Manual real Claude API smoke was not run because network/API workflows are outside this sandbox's reliable verification envelope; Phase 0 already covered real SDK/auth behavior and this pass preserved those findings.

Cleanup:
- Removed Phase 0 scratch artifacts from `scratchpads/task_126/`.

## 2026-05-15 — Guide follow-up

Added the missing `src/pflow/guide/nodes/claude-code.md` topic so `pflow guide claude-code` and workflow-scoped guide detection include the Claude Code node. Integrated it like the other node topics: dynamic registry interface injection, entry-menu and fallback listing, reserved workflow-name protection, and tests for direct topic rendering plus `.pflow.md` auto-detection.

Kept the guide intentionally user-facing: it explains when to choose `claude-code`, the JSON Schema object-root requirement, `max_turns >= 2` with `output_schema`, and downstream result access. It deliberately does not mention SDK fields, warning-channel internals, or pflow implementation details.

Verification:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_cli/test_guide.py -q` -> `63 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check src/pflow/guide src/pflow/core/workflow/save_service.py tests/test_cli/test_guide.py` -> success
- `HOME=/private/tmp/pflow-test-home .venv/bin/pflow guide claude-code` rendered the new topic with Parameters and Outputs appended from the registry.

## 2026-05-15 — Manual CLI verification follow-up

Manual pflow CLI verification created scratch workflows under `scratchpads/manual-pflow-verification/` and exercised:

- `pflow --help`
- `pflow guide core claude-code shell code file branching batch sub-workflows prompt-caching`
- adjacent `pflow guide llm http mcp`
- `--validate-only`, `--dry-run`, `--print`, `--output-format json`, `--only`, `-o`
- `probe`, `read-fields`, `visualize`, `report`, `save`, `describe`, saved-name execution
- real shell/code/file/sub-workflow execution with template JSON auto-parsing and branch convergence

Finding: `claude-code` invalid `output_schema` shapes were rejected by normal execution prep, but `--validate-only` and `--dry-run` accepted them. This meant agents could get a clean preflight for workflows that would fail immediately at runtime before the SDK call.

Fix: added static Claude Code structured-output parameter checks to `WorkflowValidator`, covering:

- explicit non-object top-level `output_schema.type`
- empty schema dict
- legacy Python-alias schema format
- `max_turns < 2` when `output_schema` is set
- non-dict literal `output_schema`

Regression tests:

- `tests/test_cli/test_validate_only.py::TestValidateOnlyClaudeCodeStructuredOutput`
- `tests/test_cli/test_dry_run.py::test_dry_run_rejects_claude_code_invalid_schema_before_plan`

Verification:

- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_cli/test_validate_only.py tests/test_cli/test_dry_run.py tests/test_nodes/test_claude/test_claude_code.py tests/test_runtime/test_memoization_integration.py -q` -> `105 passed`
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check src/pflow/core/workflow/validator.py tests/test_cli/test_validate_only.py tests/test_cli/test_dry_run.py` -> success
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy` -> success
- Post-fix near-full sandbox pytest command reached `6790 passed, 19 skipped, 4 failed`. All four failures are subprocess tests invoking `/opt/homebrew/bin/uv`, matching the sandbox `uv` panic class (`Attempted to create a NULL object` / `Tokio executor failed`).

Residual manual observation: an unauthenticated Claude CLI can yield `is_error=True` with result text like `Not logged in · Please run /login`; current Task 126 semantics treat schema-path SDK error results as DEGRADED soft-failures and memo-cacheable node outputs. That behavior is explicitly pinned by existing tests, so this pass did not change it.

## 2026-05-15 — Independent verification pass + three fixes

Adversarial CLI verification (real `claude` subscription auth, no API key) executed both happy path and edge cases through `pflow --validate-only`, `--dry-run`, and `--output-format json`. Live structured-output run succeeded: `{"status": "ok"}`, $0.087, ~14s. Confirmed cleanly working: DEGRADED propagation through batch/sub-workflow/`--only`, memo cache replay via `__pflow_warnings__`, recursive sub-workflow validation, all literal `_validate_claude_code_params` branches, registry exposes `_schema_error` as an output and hides `__warnings__`.

Three real bugs found and fixed.

| Finding | Fix | Verification |
|---|---|---|
| **#1 Validator regression**: Templated `output_schema: ${upstream.field}` rejected at preflight ("got str") even though runtime `_validate_schema` handles it correctly. Confirmed via `git stash` round-trip — pre-Task 126 accepted the composition pattern. Asymmetric within the same method (`max_turns` defers on `int()` failure; `output_schema` hard-rejects) and across nodes (LLM node has no equivalent gate). Zero test coverage. | `validator.py:701-706`: 5-line guard that defers template strings (substring `${`) to runtime, matching the `max_turns` policy. | Live `composed-schema.pflow.md`: upstream code node builds JSON Schema → claude consumes via template → returns `{"status": "ok"}`, status `success`. Manual breaking tests for empty/array/legacy/max_turns=1 still reject at preflight (no regression). |
| **#2 Hard-error swallowing in `_run_claude_session`**: Once `is_error_from_sdk` was set on any earlier `ResultMessage`, the catch-all `except Exception` silently swallowed every subsequent raise — including `CLINotFoundError`, `CLIConnectionError`, `ProcessError`. Users lost the remediation messages in `exec_fallback` ("Install with: npm install -g …", "Run `claude doctor`"). | `claude_code.py:624-639`: narrowed the swallow to `ProcessError` only (the actual SDK pairing with `ResultMessage(is_error=True)`). Other exception types re-raise so the Node retry path delivers them to `exec_fallback`. | Two unit tests: `test_sdk_is_error_branch` (updated) and `test_sdk_is_error_with_structured_output_emits_warning` (updated) now use `ProcessError` with stderr; new `test_non_process_error_after_is_error_re_raises` asserts `CLIConnectionError` propagates instead of being swallowed. |
| **#3 Templated `output_schema` resolving to `None` silently downgraded to free-form mode**: `_validate_schema(None)` returns None; `_build_claude_options` skipped wiring `output_format`; the run returned plain text with workflow status `success`. Author who wrote `output_schema:` got no signal that their schema reference missed. | `claude_code.py:418-424` + new `_emit_schema_resolved_null_warning` helper: detects "key present in `self.params` and value is None" in `prep()`, writes `__warnings__[node_id]` with kind `claude_code.output_schema_resolved_to_null`; falls back to `_schema_error` when no `node_id` is bound. | Live `null-templated-schema.pflow.md`: upstream returns None → claude runs free-form → workflow status `degraded`, warning surfaces with the new kind in both `warnings` and `diagnostics` JSON arrays. Three unit tests cover the three branches. |

ProcessError test mock at `test_claude_code.py:68-75` updated so `str(exc)` returns the stderr text — matches the real SDK behavior and lets `sdk_exception_text` capture something meaningful.

Verification:
- `uv run pytest --ignore=tests/test_llm` → `6820 passed, 10 skipped` (5 net new tests).
- `uv run ruff check` on touched files → clean.
- `uv run mypy` → `Success: no issues found in 207 source files`.
- Live `composed-schema.pflow.md` run → `success`, structured `{"status": "ok"}`.
- Live `null-templated-schema.pflow.md` run → `degraded`, new warning visible.
- Six existing breaking-test workflows under `scratchpads/manual-pflow-verification/breaking/` all still produce the correct preflight verdict.

Three reviewer agents (review-validation-consistency, review-silent-failures, review-feature-interactions) ran in parallel against the original implementation; their full transcripts informed the three fixes plus a residual non-blocking observation: soft-fail message text does not currently overlap with `api_warning_detector`'s `"schema error"`/`"does not match"` patterns, but the messages are not pinned by a regression test — a future reword that includes those substrings would silently flip soft-fail → hard error. Worth pinning if message text changes.

Out of scope for this pass (deliberate):
- Finding #4 (warning lost when `node_id is None` and `is_error AND structured_output present`) — test-only path; the LLM node uses the same `node_id is not None` guard. Documented but not fixed.
- Finding #5 (api_warning_detector pattern collision regression test) and #6 (docstring clarification that soft-fail returns `"default"`) — user-scoped to critical-only.
- Centralized JSON Schema syntactic validation across nodes — already tracked at issue [#398](https://github.com/spinje/pflow/issues/398).

## 2026-05-15 — Remaining verification findings (#4 / #5 / #6) addressed

| Finding | Fix | Verification |
|---|---|---|
| **#4 Soft-fail signal lost when `node_id is None`**: in `_store_results`, the `is_error_from_sdk AND structured_output present` branch wrote `__warnings__[node_id]` only when `node_id` was bound — leaving callers in the test / direct-`node.run()` path with no signal at all. The no-output branch already wrote `_schema_error` unconditionally; this branch did not. | Added `_emit_soft_fail_signal` helper that writes `_schema_error` via `setdefault` (preserves prior writes) and `__warnings__[node_id]` when bound. Both schema-path branches now route through it. Also extracted a `_store_schema_result` helper to keep `_store_results` under the C901 complexity limit. Docstring + `_schema_error` interface description updated to broaden the semantics ("set when structured output was unavailable, the SDK reported an error alongside the output, or the schema reference resolved to None"). | New unit test `test_sdk_error_with_structured_output_no_node_id_falls_back_to_schema_error`. Existing `test_sdk_is_error_with_structured_output_emits_warning` still passes. |
| **#5 No regression pin for soft-fail message strings vs `api_warning_detector`**: original reviewer concern was that a future reword of the soft-fail message into a `VALIDATION_PATTERNS` substring (e.g. `"schema error"`, `"does not match"`) would silently flip soft-fail → hard error. My first draft tested the message strings against `_is_validation_error` directly, which immediately fired on `"required fields"` — but `extract_error_message` is shape-gated (only fires on `ok: false` / `success: false` / `status: "error"` / GraphQL `errors` / `error` key), so claude-code's `{result, _schema_error, llm_usage}` shape never reaches `_is_validation_error` in production. False alarm. | Rewrote the test as a black-box integration check: build the exact `shared[node_id]` shape `_store_results` produces on the schema-not-satisfied path, then call `detect_api_warning("review", shared)` and assert it returns `None`. The invariant is now the actual production property (output shape doesn't match the detector's extraction gates), not a message-string equality. A future contributor adding an `error`/`ok`/`success`/`status` key to claude-code output for debug visibility breaks this test before the regression ships. | New unit test `test_soft_fail_output_shape_not_classified_as_api_warning`. |
| **#6 Docstring did not document the `default`-only routing contract**: workflow authors wiring `- on-error: handler` could reasonably expect schema misses to route there; they don't. | Class docstring `Note:` block adds an explicit "Routing:" paragraph. Module + class `_store_results` docstring gains a "Lifecycle action" rule. `docs/reference/nodes/claude-code.mdx` Output table gets an `always returns default` paragraph. `src/pflow/guide/nodes/claude-code.md` adds a new "Recovering from schema soft-failures" section with a code-node branching pattern using `${node._schema_error ?? ""}`. `examples/nodes/claude-code/README.md` calls out the same invariant where it lists the soft-fail signals. | `pflow guide claude-code` rendered the new section. Existing guide-internals test (`test_claude_code_guide_documents_structured_output_without_internals`) caught a phrasing slip — "SDK" was banned from the user-facing guide; reworded to "provider error". |

Verification:
- `uv run pytest --ignore=tests/test_llm` → `6822 passed, 10 skipped` (2 net new tests, no regressions).
- `uv run ruff check src/pflow/nodes/claude/claude_code.py …` → success (`_store_schema_result` + `_emit_soft_fail_signal` extraction kept `_store_results` under C901 limit of 10; the original Fix #4 in-place edit pushed it to 11).
- `uv run mypy` → `Success: no issues found in 207 source files`.
- Live `claude-code-structured-valid.pflow.md` re-run (cached) → `success`, `result: {"status": "ok"}`. No regression to happy path.
- All 14 breaking-test workflows under `scratchpads/manual-pflow-verification/breaking/` still produce the correct preflight verdict.

Deliberate non-change:
- Did NOT touch the LLM node's analogous `node_id is None` guard. The LLM node has the same pattern at `nodes/llm/llm.py:296`; this passes loses signal in the same way for the same reason. Consistency between the two nodes is preferable to one-off divergence; if the gap matters, fix both together in a follow-up touching both call sites.

## 2026-05-15 — oneOf/anyOf/allOf follow-up probe + tightening

Wrote `scratchpads/task_126_oneof_probe/probe.py` to close the open item Phase 0 left unanswered: do top-level combinator schemas work? Result: **all four (`oneOf`/`anyOf`/`allOf`/`enum`) return `api_error_status=400` from the Anthropic API**, same class as the Phase 0 `type: array`/primitive findings.

Tightened both runtime and static validators:
- `claude_code.py::_validate_schema` now requires `top_level_type == "object"` (was: rejected only when `type` was set to a non-`"object"` value; missing `type` slipped through).
- New `_top_level_object_error` helper produces case-specific guidance: combinator-only schemas get a message naming the offending combinator; non-`"object"` types get the wrapping advice.
- `validator.py::_validate_claude_code_params` mirrors the same logic so `--validate-only` and `--dry-run` reject these at preflight instead of letting them fail at runtime.

Tests:
- Flipped `test_oneOf_top_level_schema_accepted` → `test_top_level_oneOf_schema_rejected`.
- Added `test_top_level_{anyOf,allOf,missing_type}_schema_rejected`.
- Added `test_top_level_object_with_oneOf_accepted` to pin that combinators INSIDE an object wrapper still work.
- Added two `TestValidateOnlyClaudeCodeStructuredOutput` cases: oneOf root + missing top-level type.

Doc propagation:
- `task-126.md` requirements and design decisions reflect the rejection (no longer "may pass").
- `implementation-plan.md` edge case table updated.

Also fixed unrelated pre-existing test-suite issues that were blocking `ruff check .` and turned up during verification:
- 3× RUF043: raw-string the `pytest.raises(match=...)` regex patterns in `test_workflow_resolver_contract.py`, `test_execution_workflow.py`, `test_plan_workflow.py`.
- 22× RUF059: prefix unused unpacked variables with `_` in `test_instrumented_wrapper.py`, `test_prepare_inputs_coercion.py`, `test_settings_env_integration.py`, `test_array_notation.py`.

Verification:
- `uv run pytest tests/test_nodes/test_claude/ tests/test_cli/test_validate_only.py tests/test_cli/test_dry_run.py -q` → `108 passed`
- `uv run python -m ruff check .` → clean.
- Pre-existing "fails in sandbox" tests (`test_failed_node_invariant.py`, `test_prep_error_action.py`) run clean on real dev environment: 39 passed in isolation, 1869 passed in the full `tests/test_runtime tests/test_integration` sweep.

## 2026-05-15 — Phase 5.4 manual real-API smoke test

Ran `examples/nodes/claude-code/claude-code-schema.pflow.md` against the real Anthropic API via Claude Max subscription (no `ANTHROPIC_API_KEY`). Reviewed an intentionally-flawed Python file (command injection + SQL injection).

End-to-end result: `success: true`, `warnings: []`, `diagnostics: []`. All 4 nodes completed (`read_code`, `review`, `save_review`, `save_improved`). The `review` node returned a fully-conformant dict with all 6 required fields including `overall_quality: "poor"` (enum constraint honored), `security_score: 2` (1-10 minimum/maximum honored), and `has_critical_issues: true` (correctly typed boolean). Templates `${review.result.*}` resolved cleanly into both downstream `write-file` nodes — `.improved.py` and `.review.md` artifacts were produced with no escaping or template-resolution artifacts. Duration: 54.7s, API-equivalent cost: $0.135 (subscription: $0 billed), 2.6k output tokens, 19.8k cache-creation tokens.

This closes the last open item from the plan's Phase 5 checklist. No regression to the happy path.
