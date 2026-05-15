# Phase 0 Smoke Test Findings — SDK 0.2.82

**Date**: 2026-05-15
**SDK version**: `claude_agent_sdk==0.2.82` (released hours earlier on 2026-05-15)
**CLI version**: `claude 2.1.142 (Claude Code)`
**Auth**: Claude Max subscription (no `ANTHROPIC_API_KEY` set)
**Test script**: `scratchpads/task_126/smoke_test.py`
**Raw output**: `scratchpads/task_126/smoke-output.txt`

## Summary

| Probe | Result | Notes |
|---|---|---|
| happy_path_object | ✅ pass | `structured_output={'risk_level':'high','score':10}`, num_turns=2 |
| array_top_level | ❌ **API 400** | `Input should be 'object'` — top-level non-object schemas rejected |
| primitive_string_enum | ❌ **API 400** | Same error as array_top_level |
| impossible_const | ❌ **API 400** | Same error (couldn't test impossible-schema branch with primitives) |
| no_schema_baseline | ✅ pass | Free-form text, works as expected |
| optional_fields_no_required | ✅ pass | Optional fields ABSENT (not None) when not produced |
| malformed_schema_intger | ⚠️ silently accepted | Schema typo `type: intger` did NOT error; model produced no structured output and returned free-form text |

## Plan-altering findings

### 1. ⚠️ Top-level schema MUST be `type: object`

```
API Error: 400 tools.9.custom.input_schema.type: Input should be 'object'
```

The CLI wraps `output_format` schemas as a custom tool's input_schema and the Anthropic API rejects non-object input schemas for tools. **Top-level `type: array`, `type: string`, `type: integer`, etc. all fail with the same 400.**

Note that this is the API's *tool-use limitation*, not a JSON Schema spec limitation. The LLM node's `output_schema` (which routes through LiteLLM's OpenAI-style `response_format`) does NOT have this restriction — OpenAI permits top-level arrays/primitives in JSON Schema.

**Implication for Task 126**:
- `_validate_schema` must reject top-level non-object schemas at prep time with a clear error. Without this, users get the opaque API 400 surfaced as `is_error=True` → "Claude CLI reported an error" soft-fail message — not actionable.
- The plan's "Top-level type: array → list" and "primitive structured_output" edge cases must be REMOVED from the Claude Code edge case table (they're impossible on this node).
- The plan's tests for `test_array_schema_top_level` and `test_primitive_structured_output` must be removed.
- Document the limitation in `docs/reference/nodes/claude-code.mdx` (workflow authors who write top-level array schemas on this node need to wrap them in objects, OR use the LLM node instead).

### 2. ⚠️ Malformed JSON Schema types are silently accepted by the API

Probe `malformed_schema_intger` sent `{"type": "object", "properties": {"x": {"type": "intger"}}, "required": ["x"]}`. The API did NOT return an error. The model produced free-form text (no structured output). `is_error=False`, `structured_output=None`.

**Implication**: schema typos fall through to our soft-fail path with the misleading "Model did not return structured output matching the schema" message — when the real issue is the schema typo. **Strengthens the case for the centralized validation in issue #398.**

Until #398 lands, schema typos result in:
- ✅ Soft-fail path triggers (`_schema_error` + `__warnings__` set)
- ❌ User sees "model didn't comply" instead of "your schema is malformed"

Consider adding a hint in the `_schema_error` message: *"If you suspect a schema typo, run `pflow validate` once issue #398 is resolved."* — small, low-cost, future-friendly UX.

### 3. `max_turns: 1` is insufficient for structured output

The happy-path probe needed `num_turns=2` to complete. With `max_turns=1` the SDK raises:
```
Claude Code returned an error result: Reached maximum number of turns (1)
```

Current `_validate_max_turns` (claude_code.py:260–271) allows `min=1`. **Recommendation**: raise minimum to `2` when `output_schema` is set, OR document this in the param docstring + raise a clearer error when it happens. Plan should mention this; implementation can be conservative (just doc).

### 4. `total_cost_usd` is informational, not billed

The smoke test consumed ~$0.20 worth of subscription quota total, but the user is on Claude Max — actually billed: $0. The `total_cost_usd` field on `ResultMessage` reports "what this would have cost via API" regardless of auth method.

**Implication**: when the Claude Code node propagates `total_cost_usd` into `shared["llm_usage"]["cost_usd"]`, downstream tools/dashboards see API-equivalent cost even when on subscription. Worth a docstring note. No code change required.

### 5. Subscription auth needs ZERO configuration

The `claude` CLI (bundled by `claude_agent_sdk`) auto-detects subscription auth via OAuth/keychain. The SDK shells out to this CLI; auth flows through transparently. Don't set `ANTHROPIC_API_KEY` — its presence would force API-key billing.

`claude auth status` confirms:
```json
{
  "loggedIn": true,
  "authMethod": "claude.ai",
  "apiProvider": "firstParty",
  "subscriptionType": "max"
}
```

No env var, settings file, or token setup required for the developer running Phase 5 tests or running migrated example workflows.

## Confirmed plan assumptions

- ✅ `ResultMessage.structured_output` is populated when `output_format` is set and the model complies — exactly as the plan expects
- ✅ Both `result` (text) and `structured_output` (parsed) are populated on success — the plan's "prefer structured_output, ignore result_text" logic is correct
- ✅ `is_error=True` correlates with the soft-fail path (`structured_output=None`)
- ✅ Optional fields (no `required`) are ABSENT (not None-filled) when the model doesn't produce them — matches plan's documented behavior
- ✅ Single `ResultMessage` per session (no multi-message streaming observed); sticky-`is_error` logic is defensive but no probe exercised it
- ✅ No `ANTHROPIC_API_KEY` needed; subscription auth via bundled CLI works flawlessly
- ✅ SDK 0.2.82 is field-compatible with everything the plan assumes (verified via test suite + this smoke test)

## SDK 0.2.82 new fields available (not used by plan, but noted for follow-ups)

`ResultMessage` in 0.2.82 has new fields beyond what 0.1.18 had:
- `errors: list` — structured per-error detail. Could enrich `__warnings__["context"]` in future
- `stop_reason: str` — e.g. `"end_turn"`, `"stop_sequence"`. Helpful for distinguishing failure modes
- `api_error_status` — distinguishes API errors from other failures
- `permission_denials` — irrelevant to structured output
- `deferred_tool_use`, `model_usage`, `uuid` — irrelevant to this task

Don't bake these into Task 126 (scope creep), but they're available if Phase 1 implementation finds a natural use.

## Cleanup

- `scratchpads/task_126/auth_probe.py` — minimal probe; can be deleted
- `scratchpads/task_126/smoke_test.py` — full probe; keep until Task 126 ships then delete in Phase 5.6
- `scratchpads/task_126/smoke-output.txt` — raw output log; delete with scratchpads at end of Task 126
- This file (`smoke-findings.md`) — keep until Task 126 ships, then either delete or move to `.taskmaster/tasks/task_126/implementation/` if useful as historical record
