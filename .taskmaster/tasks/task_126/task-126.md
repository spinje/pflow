# Task 126: Structured Output for Claude Code Node

## Description

Migrate the Claude Code node's `output_schema` from a custom Python-alias format with prompt-injection + regex JSON extraction to **native `claude_agent_sdk` structured output**, using **JSON Schema** as the user-facing format (consistent with the LLM node, Task 66). Soft-failures additionally emit a `__warnings__` entry so workflow status becomes `DEGRADED` (agent-visible).

## Status

Ready for implementation. Prework completed:
- SDK upgraded to `claude-agent-sdk>=0.2.82` (`pyproject.toml` + `uv.lock`); existing test suite passes (47/47 Claude Code tests)
- Phase 0 smoke test executed; findings captured in [`implementation/phase-0-findings.md`](./implementation/phase-0-findings.md)

Implementation plan: [`implementation/implementation-plan.md`](./implementation/implementation-plan.md).

## Priority

medium

## Dependencies

- Task 42: Claude Code Agentic Node (done)
- Task 66: Structured Output for LLM Node (done — sets the LLM node baseline this task aligns with)

## Problem

The Claude Code node already supports `output_schema`, but in a custom format inconsistent with the LLM node:

```yaml
# Current Claude Code (Python-alias custom format)
risk_level:
  type: str          # ← Python alias, not JSON Schema
  description: high/medium/low
score:
  type: int
  description: 1-10
```

```yaml
# Current LLM node (real JSON Schema, since Task 66)
type: object
properties:
  risk_level: { type: string, enum: [high, medium, low] }
  score: { type: integer, minimum: 1, maximum: 10 }
required: [risk_level, score]
```

The current Claude Code implementation works via:
1. **Prompt-injection** — `_build_schema_prompt` embeds a 30-line "RESPOND WITH JSON ONLY" instruction block into the system prompt, with the Python-alias type names rendered literally (e.g., `"<str: high/medium/low>"`)
2. **Regex extraction** — three fallback strategies (`_extract_json_from_code_block`, `_extract_json_from_raw_object`, `_extract_json_from_last_brace`) attempt to recover JSON from the model's free-form text response

Costs of the status quo:
- **Inconsistent user-facing syntax** between LLM and Claude Code nodes (workflow authors write JSON Schema for one, custom format for the other)
- **Fragile** — relies on the model honoring prompt instructions; no provider-side enforcement
- **Verbose system prompt** competes with the user's own system_prompt
- **Regex extraction** can silently mis-parse complex/nested JSON
- **`core/types.py:8-12`** carved `output_schema` out of the type-vocabulary unification (Task 154) specifically because the Python-alias names were embedded in the prompt template — an architectural debt

`claude_agent_sdk` v0.2.82+ now natively supports structured output via `ClaudeAgentOptions.output_format={"type": "json_schema", "schema": ...}`, which the SDK forwards to the underlying CLI via `--json-schema`. The CLI returns the parsed result as `ResultMessage.structured_output: Any`. This makes prompt-injection and regex extraction unnecessary.

## Solution

Replace the prompt-injection + regex-extraction approach with direct SDK usage:

1. Pass the user's `output_schema` (now JSON Schema) to `ClaudeAgentOptions.output_format` (SDK handles wire-format and provider negotiation)
2. Read `ResultMessage.structured_output` directly — already parsed by the CLI
3. Delete `_build_schema_prompt`, `_extract_json`, and the three extraction helpers
4. Add `_validate_schema` legacy-format detection that points old workflows at the new format
5. Migrate the 3 example workflows + docs to JSON Schema

Preserve the existing **soft-failure** semantics (`action="default"`, `shared["_schema_error"]` set when the schema isn't satisfied — diverges from the LLM node's hard-error path because Claude Code agentic sessions are expensive and downstream nodes may still want the raw text). Additionally write a `__warnings__` entry so workflow status surfaces as `DEGRADED` — important for agent-readable error visibility.

## Design Decisions

### Native SDK `output_format`, not prompt-injection upgrade

The Claude Code SDK (`claude_agent_sdk>=0.2.82`) natively translates `output_format` to a `--json-schema` CLI flag that constrains the model's final output at the provider level. This is strictly better than prompt-injection: provider-enforced compliance, no regex parsing of free-form text, no verbose prompt boilerplate competing with the user's own system_prompt.

Alternative considered: keep prompt-injection but switch the format to JSON Schema. Rejected — still fragile, still requires regex extraction, still bloats the system prompt.

### JSON Schema, hard cutover (no backwards compatibility)

Per `CLAUDE.md`: "We have NO USERS yet. No backwards compatibility concerns." The Python-alias format is a Task-42-era artifact predating the LLM node's JSON Schema adoption. Aligning both nodes on JSON Schema gives workflow authors a single mental model.

A legacy-format detector in `_validate_schema` produces a clear migration error for any local workflow still using the old format. No silent acceptance, no shim, no dual-format support.

### Soft-failure preserved (action="default" + `_schema_error`), with `__warnings__` added

The LLM node returns `action="error"` on schema parse failure — hard error, retry path possible. The Claude Code node has historically returned `action="default"` with `shared["_schema_error"]` set, treating schema failure as graceful degradation.

Reason for the divergence: Claude Code sessions are expensive (~$0.05+ per attempt) and often agentic (file edits, tool use). On schema failure, the raw text is frequently still useful for downstream nodes to salvage. Forcing a hard error and triggering retries can waste $$ on the same model behavior.

**New in this task**: also write `shared["__warnings__"][node_id] = {kind, text, context}` so workflow status transitions to `DEGRADED` (via `runtime/workflow_trace.py:457-466`). This makes schema failures visible to AI agents reading `pflow ... --output-format json` without requiring them to know about the `_schema_error` side-channel.

### `is_error=True` AND `structured_output` present: prefer `structured_output`

The CLI may report `is_error=True` for non-fatal sub-errors while still producing valid structured output. Treat as success (use `structured_output` as the result), but emit a `__warnings__` entry so the error signal isn't silently dropped.

### Top-level `type: object` enforced (Claude-API-specific limitation)

Phase 0 smoke test discovered that the Anthropic API rejects non-object top-level schemas when the SDK wraps `output_format` as a tool's `input_schema` (error: `400 tools.9.custom.input_schema.type: Input should be 'object'`). This affects `type: array`, `type: string`, `type: integer`, and other primitive top-level types.

This is **specific to the Claude Code node** — the LLM node has no such restriction (LiteLLM/OpenAI accept top-level non-object schemas).

`_validate_schema` catches this at prep time with a clear error pointing the user at the workaround (wrap in `{"type": "object", "properties": {"items": <user_schema>}}`) and noting the LLM node alternative. Without this check, users would see the opaque API 400 surface as a `is_error=True` soft-fail with the generic "Claude CLI reported an error" message.

### `max_turns >= 2` enforced when `output_schema` is set

Phase 0 smoke test discovered that `max_turns: 1` is insufficient for structured output — the agent needs at least 2 turns (one to plan, one to emit). The SDK raises `"Reached maximum number of turns (1)"` otherwise. `prep` catches this cross-cutting constraint with a clear error.

### Empty schema `{}` is an error, not a no-op

`output_schema: None` (key absent) = "no schema requested" → no-op (correct).
`output_schema: {}` (empty dict) → almost certainly a user typo (e.g., forgot to populate the YAML block). Raise with explicit guidance instead of silently disabling structured output.

### Sticky `is_error` across multiple `ResultMessage`s

If the SDK streams multiple `ResultMessage`s in one session, `is_error=True` on any of them persists through subsequent messages (`is_error_from_sdk = is_error_from_sdk or message.is_error`). Prevents silent error swallowing when a later message claims success after an intermediate failure.

### SDK field-presence probe at module import

`hasattr(ResultMessage, "__annotations__") and "structured_output" in ResultMessage.__annotations__` — fails the import loudly if the SDK is too old or has renamed the field. Without this, a renamed field would silently return `None` via `getattr`, and every Claude Code workflow would soft-fail with a "model didn't comply" message blaming the model when pflow is at fault.

### JSON Schema syntactic validation deferred to issue #398

Neither node currently validates that `output_schema` is itself well-formed JSON Schema (typos like `type: intger`, malformed nesting, etc.). Adding this to the Claude Code node alone would duplicate logic with the LLM node, which deserves the same treatment.

The architecturally correct placement (`WorkflowValidator` step between current 8 and 9, with a `JSON_SCHEMA_PARAMS` frozenset) is a cross-cutting concern. Filed as **GitHub issue #398**. This task trusts the SDK boundary, matching the LLM node's current behavior; the follow-up issue adds local validation to both nodes uniformly.

### Inline `_build_prompt` and `_build_system_prompt`

After removing schema-related framing, both methods become one-liner pass-throughs. Inline at call sites — top-10% codebases avoid trivial wrapper methods.

### Delete the `core/types.py` "fourth surface" carve-out

The comment at `core/types.py:8-12` exists specifically because the Python-alias names were load-bearing in `_build_schema_prompt`'s template strings. After this task, the comment's premise no longer holds. Delete entirely (don't rewrite) — the relevant information lives in the user-facing docs.

## Requirements

### User-facing behavior

- Workflow authors write JSON Schema in ` ```yaml output_schema ` blocks on `claude-code` nodes, identical syntax to LLM nodes
- **Top-level MUST be `type: object`** on this node (Claude API tool-input-schema limitation discovered in Phase 0; the LLM node has no such restriction). For array/primitive outputs, wrap in an object. Validation surfaces a clear error at `prep` time.
- `oneOf`/`anyOf`/`allOf` at the top level pass `prep` validation; runtime success depends on the API (Phase 0 did not probe — may also be rejected)
- Schemas can be inlined or referenced via `- output_schema: ./schema.yaml` (no change to file_resolver behavior)
- The legacy Python-alias format (`{"field": {"type": "str", ...}}`) produces a clear migration error at `prep` time
- Empty schema `{}` produces a clear "did you forget the schema body?" error
- `max_turns >= 2` is enforced at `prep` time when `output_schema` is set (Phase 0 finding: structured output needs at least 2 turns)
- Auth: subscription users (Claude Pro/Max/Team via the bundled `claude` CLI's OAuth login) work zero-config — no `ANTHROPIC_API_KEY` needed. Setting `ANTHROPIC_API_KEY` forces pay-as-you-go billing.

### Result placement (`shared["result"]`)

- No schema set: free-form text (`str`)
- Schema set + `structured_output` populated: parsed dict / list / primitive
- Schema set + `structured_output` is `None`: raw text fallback (preserves Claude Code's soft-fail tradition)

### Error/warning signaling

- Soft-fail (schema set but unsatisfied): `shared["_schema_error"]` set to a human-readable string AND `shared["__warnings__"][node_id]` set to `{kind, text, context}` → workflow status `DEGRADED`
- `is_error=True` + `structured_output` present: `structured_output` becomes `shared["result"]` BUT a `__warnings__` entry is still emitted
- `kind` strings: `"claude_code.schema_not_satisfied"` (model didn't comply) and `"claude_code.sdk_error_no_structured_output"` (CLI reported error) and `"claude_code.sdk_error_with_structured_output"` (CLI errored but structured output is usable)
- Hard errors (SDK raises, timeout, network) continue to flow through existing `exec_fallback` — unchanged

### Compatibility / drift protection

- Module-import-time probe raises `ImportError` if `claude_agent_sdk.types.ResultMessage` lacks the `structured_output` field — prevents silent failures when the SDK is too old or has renamed the field
- `pyproject.toml` `claude-agent-sdk` floor bumped to `>=0.2.82` (already done as prework before plan handoff; lockfile resolved to 0.2.82, existing test suite passes)

### Documentation parity

- Module docstring AND class docstring on `claude_code.py` both updated (registry reads one; humans read both)
- `docs/reference/nodes/claude-code.mdx`, `architecture/core-node-packages/claude-nodes.md`, and `examples/nodes/claude-code/README.md` all reflect JSON Schema format + the new `__warnings__`/`DEGRADED` behavior
- 3 example workflows under `examples/nodes/claude-code/` migrated to JSON Schema
- `core/types.py` "fourth surface" carve-out comment (lines 8–12) deleted
- `tests/CLAUDE.md` pitfall #17 updated to describe the new `ResultMessage` mock class

### Test coverage

- New tests for: `output_format` wiring, legacy-format rejection, all-values legacy detection, `oneOf` top-level (accepted by prep), top-level array/primitive (rejected by prep), `max_turns: 1` with schema rejected, empty `{}` rejection, `None` no-op, structured_output as dict, `__warnings__` writes on soft-fail and `is_error+structured_output`, sticky `is_error` across multi-message streams
- Existing tests for "valid Python identifier keys" / "≤50 keys" / `_build_schema_prompt` / `_extract_json*` deleted
- All `_schema_error` assertions use substring matching (`"X" in shared["_schema_error"]`), not exact equality

### Verification

- `make test` passes (full suite)
- `make check` passes (ruff + mypy)
- `tests/test_docs/test_example_validation.py` passes (migrated examples remain valid)
- `pflow registry list claude-code` shows the updated Interface description
- One migrated example runs end-to-end against the real API and produces structured downstream data accessible via templates like `${review.result.field}`

## Out of scope

- **Centralized JSON Schema syntactic validation across all nodes** — see GitHub issue #398
- **`pflow guide` page for claude-code** — no existing page; file as a separate task
- **`claude_client.py` adapter** module analogous to `llm_client.py` — `claude_agent_sdk` has one consumer; premature
- **Per-node retry on schema mismatch** — soft-fail is the chosen semantics
- **Backwards-compatibility shim** for the legacy Python-alias format — no users
- **Legacy → JSON Schema converter tool** — out of scope per "no users yet"

## References

- **Implementation plan**: [`implementation/implementation-plan.md`](./implementation/implementation-plan.md) (the step-by-step *how*)
- **Follow-up issue**: [#398](https://github.com/spinje/pflow/issues/398) — Centralized JSON Schema validation for `output_schema` across nodes
- **Builds on**: Task 66 (LLM structured output, completed), Task 42 (Claude Code Agentic Node, completed)
- **Related tasks**: Task 143 (Unified Diagnostic System), Task 147 (Validator Produces Diagnostics Natively), Task 150 (WorkflowValidator on save path), Task 154 (Type Vocabulary Coherence — claude_code carve-out resolved by this task), Task 158 (LiteLLM migration — LLM node's structured output path post-migration)
- **Starting-context braindump** (pre-Task 158, partially outdated): [`starting-context/braindump-task66-completed-task126-next.md`](./starting-context/braindump-task66-completed-task126-next.md)
- **SDK reference**: `claude_agent_sdk>=0.2.82` — `ClaudeAgentOptions.output_format`, `ResultMessage.structured_output`
