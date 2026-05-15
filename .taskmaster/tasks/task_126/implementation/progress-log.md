# Task 126 Progress Log

## Status

| Phase | Status | Commit |
|---|---|---|
| Prework: SDK upgrade to 0.2.82 | ✅ done | `8cadd39c` |
| Phase 0: SDK smoke test | ✅ done | `8cadd39c` |
| Phase 1: Refactor claude_code.py | ⏳ next | — |
| Phase 2: Tests | pending | — |
| Code review checkpoint | pending | — |
| Phase 3: Examples + docs | pending | — |
| Phase 4: types.py + CHANGELOG | pending | — |
| Phase 5: Final verification | pending | — |

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
