# Task 126: Implementation Plan — Structured Output for Claude Code Node

> **Read first**: `.taskmaster/tasks/task_126/task-126.md` (problem, design decisions, requirements). This file is the step-by-step *how*; the task spec is the *what & why*.

## Orientation

`claude_agent_sdk` v0.2.82 (current) has `ClaudeAgentOptions.output_format` and `ResultMessage.structured_output` natively. This plan replaces the current prompt-injection + regex-extraction approach with direct SDK usage, swaps the schema format from custom Python-alias to JSON Schema, and adds a `__warnings__` write so soft-failures surface as DEGRADED workflow status (agent-visible).

**Prework already completed** (before this plan is picked up):
- SDK pin bumped to `claude-agent-sdk>=0.2.82` in `pyproject.toml`; `uv.lock` resolved
- Existing Claude Code test suite passed against 0.2.82 (47/47)
- Phase 0 smoke test executed and findings captured in [`phase-0-findings.md`](./phase-0-findings.md)

**Read [`phase-0-findings.md`](./phase-0-findings.md) BEFORE Phase 1** — it contains plan-altering findings about:
- Top-level non-object schemas are rejected by the API → must validate in `_validate_schema`
- Schema typos like `type: intger` are silently accepted by the API (motivates issue #398)
- `max_turns: 1` is insufficient for structured output → validate to require `max_turns >= 2` when schema is set
- Subscription auth via the bundled `claude` CLI works zero-config (no `ANTHROPIC_API_KEY` needed)

All line numbers reference the **current pre-modification** file. The file gets shorter as deletions land — make changes in any order within a phase; line numbers don't shift between phases because each phase's anchors are unambiguous (method names, distinctive strings).

**Verification cadence**: `make test && make check` after Phases 1, 2, 3, 5.

## Anchor map — `src/pflow/nodes/claude/claude_code.py` (1033 lines)

| Symbol | Line range |
|---|---|
| Module docstring | 1–43 |
| SDK imports (`try/except ImportError`) | 54–74 |
| `ClaudeCodeNode` class | 93 |
| Class docstring | 94–180 |
| `__init__` | 182–185 |
| `_validate_schema` | 199–214 |
| `prep` | 348–407 |
| `exec` (sync entry) | 409–426 |
| `_exec_async` | 428–450 |
| `_build_claude_options` | 452–488 |
| `_execute_with_timeout` | 490–514 |
| `_run_claude_session` (SDK loop) | 516–559 |
| `_process_assistant_message` | 561–605 |
| `_extract_metadata` | 607–628 |
| `_create_completion_event` | 630–644 |
| `_log_session_results` | 646–663 |
| `post` | 665–679 |
| `exec_fallback` | 681–738 |
| `_build_prompt` | 740–766 |
| `_build_system_prompt` | 768–788 |
| `_build_schema_prompt` | 790–836 |
| `_store_results` | 838–939 |
| `_extract_json` + 3 helpers | 941–1033 |

**Reference patterns to mirror** (read these before implementing the corresponding section):
- `src/pflow/nodes/llm/llm.py:795` — how nodes retrieve `node_id` from `self`
- `src/pflow/nodes/llm/llm.py:289-301` — canonical `__warnings__` write shape
- `src/pflow/nodes/llm/llm.py:296` — guard pattern (`if node_id is not None:`)

---

## Phase 0 — SDK runtime smoke test  ✅ DONE (prework)

**Status**: Completed before plan handoff. Findings: [`phase-0-findings.md`](./phase-0-findings.md).

**Key plan-altering findings** propagated into the phases below:
1. **Top-level non-object schemas rejected by API** → Phase 1.2 must validate this
2. **`max_turns: 1` fails for structured output** (needs ≥ 2) → Phase 1.2 / `_validate_max_turns` should reject
3. **Schema typos silently fall through to soft-fail** → no plan change, but a hint in `_schema_error` is worth adding (see Phase 1.7)
4. **Subscription auth via bundled CLI works zero-config** → no `ANTHROPIC_API_KEY` needed for Phase 5 verification

**Smoke test artifacts** (delete in Phase 5.6):
- `scratchpads/task_126/smoke_test.py` — the script
- `scratchpads/task_126/smoke-output.txt` — raw output
- `scratchpads/task_126/auth_probe.py` — minimal auth probe (already redundant)
- (`phase-0-findings.md` is permanent — lives in `implementation/`)

**Original Phase 0 plan** (kept here as a reference for re-running probes if Phase 1 discovers SDK quirks):

<details>
<summary>Phase 0 plan as originally written (kept for reference)</summary>

The original Phase 0 section called for running an end-to-end smoke test via `scratchpads/task_126/smoke_test.py`. That script and its findings now exist. If implementation surprises emerge (e.g., a SDK behavior the plan didn't anticipate), re-run the smoke test or extend it with new probes.
</details>

---

## Phase 1 — Modify `src/pflow/nodes/claude/claude_code.py`

### 1.0 SDK field-presence probe at module import

Immediately after the existing `try: from claude_agent_sdk import ...` block (lines 54–74), append a runtime assertion:

```python
# Guard against SDK field renames that would silently break structured output.
# If claude_agent_sdk renames `structured_output` → `json_output` (or similar),
# the soft-fail path would trigger on every call with a misleading "model
# didn't comply" message. Fail at import time instead.
if "structured_output" not in getattr(ResultMessage, "__annotations__", {}):
    raise ImportError(
        "claude_agent_sdk.types.ResultMessage has no 'structured_output' field. "
        "pflow's Claude Code node requires claude-agent-sdk>=0.2.82 with native "
        "structured output support. Got an incompatible SDK version."
    )
```

### 1.1 Delete methods entirely

- `_build_schema_prompt` (790–836)
- `_extract_json` (941–965)
- `_extract_json_from_code_block` (967–985)
- `_extract_json_from_raw_object` (987–1005)
- `_extract_json_from_last_brace` (1007–1033)

### 1.2 Rewrite `_validate_schema` (199–214)

**Scope**: legacy-format detection + top-level-object enforcement (Claude-API-specific limit discovered in Phase 0). JSON Schema syntactic validity is deferred to issue #398.

**Key constraint from Phase 0 findings**: the Anthropic API rejects non-object top-level schemas when wrapped as a tool's `input_schema`. The SDK passes our `output_format` schema through this path, so workflow authors MUST use `type: object` at the top level. This is **specific to the Claude Code node** — the LLM node has no such restriction (LiteLLM/OpenAI accept top-level arrays/primitives in JSON Schema).

Replace the body of `_validate_schema` with:

```python
def _validate_schema(self, output_schema: Any) -> dict | None:
    """Validate output_schema parameter.

    - None: no schema requested (returns None)
    - {} (empty): likely a typo; raises with guidance
    - Non-dict: TypeError
    - Legacy Python-alias format: raises with migration guidance
    - Non-object top-level: raises (Anthropic API tool-use limitation)
    - Otherwise: returns as-is; SDK/CLI enforces remaining JSON Schema validity

    Note on schema typos (e.g. type: "intger"): the Anthropic API silently accepts
    them — schema typos will result in a soft-fail at runtime (structured_output is None)
    with a generic "model did not return structured output" message. Centralized JSON
    Schema syntactic validation is tracked in issue #398.
    """
    if output_schema is None:
        return None
    if not isinstance(output_schema, dict):
        raise TypeError(
            f"output_schema must be a dict (JSON Schema), got {type(output_schema).__name__}"
        )
    if not output_schema:
        raise ValueError(
            "output_schema is an empty dict. Did you forget to populate the schema body? "
            "Use a real JSON Schema (e.g. {\"type\": \"object\", \"properties\": {...}}) "
            "or remove the output_schema field entirely."
        )
    if self._looks_like_legacy_python_alias_format(output_schema):
        raise ValueError(
            "output_schema appears to use the legacy Python-alias format "
            "({\"field\": {\"type\": \"str\", ...}}). "
            "Use JSON Schema instead: {\"type\": \"object\", \"properties\": {...}, \"required\": [...]}. "
            "See docs/reference/nodes/claude-code.mdx for an example."
        )
    # Claude API limitation (verified in Phase 0 smoke test): the SDK wraps output_format
    # as a tool's input_schema, and the API rejects non-object top-level schemas with a
    # 400. Catch this at prep time with a clear error.
    top_level_type = output_schema.get("type")
    if top_level_type is not None and top_level_type != "object":
        raise ValueError(
            f"output_schema on claude-code nodes must have top-level type: object "
            f"(got type: {top_level_type!r}). "
            "The Anthropic API rejects non-object top-level schemas in tool input_schema "
            "wrappers. For array or primitive outputs, wrap in an object with a single "
            "property, e.g. {\"type\": \"object\", \"properties\": {\"items\": {\"type\": \"array\", "
            "\"items\": ...}}, \"required\": [\"items\"]}. "
            "(The LLM node has no such restriction.)"
        )
    return output_schema


@staticmethod
def _looks_like_legacy_python_alias_format(schema: dict) -> bool:
    """Detect the old custom Python-alias format.

    Heuristic: no top-level JSON Schema markers AND any value is a dict
    with type in {str, int, bool, list, dict, float} (Python alias).
    """
    JSON_SCHEMA_MARKERS = {"type", "$ref", "$schema", "oneOf", "anyOf", "allOf", "enum", "const"}
    if any(marker in schema for marker in JSON_SCHEMA_MARKERS):
        return False
    PYTHON_ALIAS_TYPES = {"str", "int", "bool", "list", "dict", "float"}
    # Check ALL values, not just the first.
    return any(
        isinstance(v, dict) and v.get("type") in PYTHON_ALIAS_TYPES
        for v in schema.values()
    )
```

**Note on `oneOf`/`anyOf`/`allOf` top-level**: the legacy-format detector accepts these as JSON Schema markers and skips the migration error. **Update post-impl** (oneOf follow-up probe): the top-level-type check now fires whenever `type` is missing OR set to anything other than `"object"`, with a combinator-aware error message. All four (`oneOf`/`anyOf`/`allOf`/`enum`-only) return HTTP 400 from the Anthropic API. To use combinators, nest them inside a `type: object` wrapper.

### 1.2b Enforce `max_turns >= 2` when `output_schema` is set

**Phase 0 finding**: with `max_turns=1`, the SDK raises `"Reached maximum number of turns (1)"` even for trivial structured-output prompts. The agent needs at least 2 turns to produce structured output (one to plan, one to emit). Catch this at prep time with a clear error rather than letting it surface as a generic SDK exception.

In `prep` (current line 348–407), after `_validate_schema` and `_validate_max_turns` are both called, add a cross-check:

```python
# Phase 0 finding: structured output requires the agent to take at least 2 turns
# (one to plan, one to produce). max_turns=1 fails with "Reached maximum number of turns".
if output_schema is not None and max_turns < 2:
    raise ValueError(
        f"max_turns must be >= 2 when output_schema is set (got {max_turns}). "
        "Structured output requires the agent to take at least one turn beyond producing "
        "the final response. Set max_turns to 2 or higher (default is typically sufficient)."
    )
```

Place this near the end of `prep`'s validation block, after both `output_schema` and `max_turns` have been individually validated.

### 1.3 Delete `_build_prompt` (740–766) — inline

After removing schema framing, the method becomes `return prep_res["prompt"]`. **Inline at the call site** in `_exec_async` (line 438):

```python
# Before:
prompt = self._build_prompt(prep_res)
# After:
prompt = prep_res["prompt"]
```

Delete the method entirely.

### 1.4 Delete `_build_system_prompt` (768–788) — inline

After removing schema-merge logic, the method becomes `return prep_res.get("system_prompt") or ""`. Inline at the call site in `_exec_async` (line 441):

```python
# Before:
system_prompt = self._build_system_prompt(prep_res)
# After:
system_prompt = prep_res.get("system_prompt") or ""
```

Delete the method.

### 1.5 Modify `_build_claude_options` (452–488)

After line 482 (the `resume` conditional block) and before line 485 (the `sandbox` conditional), add:

```python
# Native structured output: SDK translates this to --json-schema CLI flag.
# subprocess_cli.py:316-325 in the SDK silently ignores any output_format
# whose type != "json_schema" — the wrapping shape is mandatory.
if prep_res.get("output_schema"):
    options_kwargs["output_format"] = {
        "type": "json_schema",
        "schema": prep_res["output_schema"],
    }
```

### 1.6 Modify `_run_claude_session` (516–559)

**Initialize before the `async for` loop** (alongside `result_text`, `tool_uses`, `progress_events` at lines 529–533):

```python
structured_output: Any = None       # last-seen ResultMessage.structured_output
is_error_from_sdk: bool = False     # sticky — once True, stays True
```

**Modify the `ResultMessage` branch** (currently lines 545–547):

```python
elif isinstance(message, ResultMessage):
    metadata = self._extract_metadata(message)
    progress_events.append(self._create_completion_event(metadata))
    # Direct attribute access — Phase 1.0's import-time probe guarantees the field exists.
    structured_output = message.structured_output
    # Sticky-true: if ANY ResultMessage reports an error, retain that signal
    # even if a later message claims success. Prevents silent error swallowing
    # in streamed multi-message responses.
    is_error_from_sdk = is_error_from_sdk or message.is_error
```

**Add the two new fields to the return dict** at the end of the method (around lines 555–559):

```python
return {
    "result_text": result_text,
    "tool_uses": tool_uses,
    "progress_events": progress_events,
    "metadata": metadata,
    "structured_output": structured_output,
    "is_error_from_sdk": is_error_from_sdk,
    # NOTE: do NOT include output_schema — _store_results reads it from prep_res
}
```

### 1.7 Rewrite `_store_results` (838–939)

**New signature**: `_store_results(shared, prep_res, exec_res, node_id)`.

The usage-metrics block (current lines 866–895) stays **inline** — do not extract a helper. Reproduce the exact dict shape from the current implementation.

**Full replacement**:

```python
def _store_results(
    self,
    shared: dict[str, Any],
    prep_res: dict[str, Any],
    exec_res: dict[str, Any],
    node_id: str | None,
) -> None:
    """Store execution results in shared store.

    Result placement rules:
    - No schema: shared["result"] = raw text (str)
    - Schema + structured_output present: shared["result"] = parsed (dict/list/primitive)
    - Schema + structured_output missing: soft-fail — raw text in result,
      _schema_error string set, __warnings__ entry written → DEGRADED status
    - is_error=True AND structured_output present: prefer structured_output AS RESULT,
      BUT emit a warning so the SDK error signal isn't silently dropped
    """
    result_text = exec_res.get("result_text", "")
    structured_output = exec_res.get("structured_output")
    is_error_from_sdk = exec_res.get("is_error_from_sdk", False)
    has_schema = prep_res.get("output_schema") is not None
    progress_events = exec_res.get("progress_events", [])
    tool_uses = exec_res.get("tool_uses", [])
    metadata = exec_res.get("metadata", {})

    if progress_events:
        shared["_claude_progress"] = progress_events
    if tool_uses:
        shared["_claude_tools"] = tool_uses

    # Usage metrics — reproduce current shape inline (do not extract a helper).
    # See pre-modification lines 866-895 for the exact dict the current code builds.
    if metadata:
        usage = metadata.get("usage") or {}
        shared["llm_usage"] = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            # Keep whatever total computation the current code uses; verify against pre-mod source
            "total_tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
            "cost_usd": metadata.get("total_cost_usd"),
            "duration_ms": metadata.get("duration_ms"),
            "num_turns": metadata.get("num_turns"),
        }
    else:
        shared["llm_usage"] = {}

    # No schema path
    if not has_schema:
        shared["result"] = result_text
        return

    # Schema success path
    if structured_output is not None:
        shared["result"] = structured_output
        if is_error_from_sdk and node_id is not None:
            shared.setdefault("__warnings__", {})[node_id] = {
                "kind": "claude_code.sdk_error_with_structured_output",
                "text": (
                    "Claude CLI reported is_error=True but structured_output was produced. "
                    "Using structured_output as result; check provider for partial-response details."
                ),
                "context": {"node_type": "claude-code"},
            }
        return

    # Soft-fail path: schema set but no structured_output
    shared["result"] = result_text
    if is_error_from_sdk:
        msg = (
            "Claude CLI reported an error and did not produce structured output. "
            "Raw text stored in result."
        )
        kind = "claude_code.sdk_error_no_structured_output"
    else:
        msg = (
            "Model did not return structured output matching the schema. "
            "Raw text stored in result."
        )
        kind = "claude_code.schema_not_satisfied"
    shared["_schema_error"] = msg
    if node_id is not None:
        shared.setdefault("__warnings__", {})[node_id] = {
            "kind": kind,
            "text": msg,
            "context": {"node_type": "claude-code"},
        }
```

**Notes**:
- `__warnings__` shape matches `nodes/llm/llm.py:289-301`.
- `node_id is not None` guard matches `llm.py:296`.
- DEGRADED status is set automatically by `runtime/workflow_trace.py:457-466` when `__warnings__` is non-empty.

### 1.8 Update `post` (665–679)

Match the LLM node's `node_id` retrieval pattern:

```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    node_id = getattr(self, "node_id", None)  # set by compiler; see compilation/compiler.py:299
    self._store_results(shared, prep_res, exec_res, node_id)
    return "default"
```

(Reference: `src/pflow/nodes/llm/llm.py:795` for the canonical `getattr(self, "node_id", None)` pattern.)

### 1.9 Update docstrings — module AND class

Both the module-level docstring (lines 1–43) AND the class docstring (lines 94–180) declare an `Interface:` block. The registry's metadata extractor reads one; humans read both. Update both to prevent drift.

**Module docstring (around line 10)** — replace the `Params`/`Writes` lines:

```
- Params: output_schema: dict  # JSON Schema for structured outputs (optional)
- Writes: shared["result"]: str|dict  # Free-form text (str), or parsed JSON (dict/list/primitive) when output_schema is set, or raw text on soft schema failure
- Writes: shared["_schema_error"]: str  # Error message when schema is set but parsing failed (optional)
- Writes: shared["__warnings__"][node_id]: dict  # Workflow status -> DEGRADED on soft schema failure
```

**Class docstring "Output Schema Format" section (around lines 110–180)** — replace the Python-alias example with:

```
JSON Schema for structured outputs (optional):
  {"type": "object", "properties": {"field": {"type": "string"}}, "required": ["field"]}
```

**Pre-existing doc drift fix**: class docstring lines 126–127 omit `disallowed_tools` from the Params list. Add it (the code at line 374 reads `disallowed_tools` from params).

### 1.10 Imports cleanup

After all deletions, verify and remove unused imports (grep the file first):

```bash
grep -nE "^[[:space:]]*import (re|json)$|^[[:space:]]*from (re|json)" src/pflow/nodes/claude/claude_code.py
grep -nE "\b(re|json)\." src/pflow/nodes/claude/claude_code.py
```

Both `import re` and `import json` are very likely unused after this phase. Remove them if grep confirms no remaining references.

### 1.11 Modern type hints

Use `dict | None` not `Optional[dict]` for any signature touched in this task (`_validate_schema`, `_store_results`, anything new). Do NOT sweep-rewrite untouched signatures.

### Phase 1 verification

```bash
uv run pytest tests/test_nodes/test_claude/ -v
make check
```

Existing tests will fail until Phase 2 runs. That's expected; ensure the file compiles and imports cleanly first:

```bash
uv run python -c "from pflow.nodes.claude.claude_code import ClaudeCodeNode; print(ClaudeCodeNode)"
```

The import-time SDK probe should pass against the installed SDK 0.2.82.

---

## Phase 2 — Test mock + tests (`tests/test_nodes/test_claude/test_claude_code.py`)

### 2.1 Add real `ResultMessage` class — load-bearing ordering

Currently `ResultMessage` is auto-Mocked (`isinstance(x, AutoMock)` would `TypeError` if exercised — confirmed latent bug). The new tests need a real class.

In the module-level mock block (around lines 35–94), add a `@dataclass` class mirroring the SDK's shape. **Register on `mock_sdk_types.ResultMessage` BEFORE the `sys.modules["claude_agent_sdk.types"] = mock_sdk_types` line (line ~93)**:

```python
from dataclasses import dataclass

@dataclass
class ResultMessage:
    """Test mock mirroring claude_agent_sdk.types.ResultMessage (v0.2.82+)."""
    subtype: str = "success"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 1
    session_id: str = "test-session"
    total_cost_usd: float | None = None
    usage: dict | None = None
    result: str | None = None
    structured_output: Any = None
```

`@dataclass` populates `__annotations__` automatically. The Phase 1.0 import-time probe (`"structured_output" in ResultMessage.__annotations__`) passes against this class.

**Register**: add `mock_sdk_types.ResultMessage = ResultMessage` immediately after the existing `mock_sdk_types.AssistantMessage = AssistantMessage` (etc.) assignments. Confirm ordering: it MUST happen before `sys.modules["claude_agent_sdk.types"] = mock_sdk_types`.

### 2.2 Delete obsolete tests

| Test name | Line | Reason |
|---|---|---|
| `test_output_schema_invalid_keys` | 252 | "Valid Python identifier" check removed |
| `test_output_schema_too_complex` | 271 | "≤50 keys" cap removed |
| `test_schema_to_prompt_conversion` | 509 | `_build_schema_prompt` deleted |
| `test_json_extraction_strategies` | 774 | `_extract_json*` deleted |
| `test_schema_merged_with_user_prompt` | 675 | `_build_system_prompt` inlined; system_prompt pass-through doesn't need a dedicated test |

### 2.3 Rewrite tests — substring assertions

All `_schema_error` assertions must use substring matching (`"X" in shared["_schema_error"]`), never exact-string equality. Exact strings fragment on minor wording tweaks.

| Test | Line | What changes |
|---|---|---|
| `test_valid_task_with_schema` | 215 | Mock yields `ResultMessage(structured_output={"risk_level": "low", "issues": []}, is_error=False)`. Assert dict in `shared["result"]`; `"_schema_error" not in shared`; `"__warnings__" not in shared` (or no entry for this node_id) |
| `test_valid_json_response_storage` | 534 | Same pattern as above |
| `test_invalid_json_response_fallback` | 583 | Mock yields `ResultMessage(structured_output=None, result="raw text", is_error=False)`. Assert `shared["result"] == "raw text"`; `"Model did not return" in shared["_schema_error"]`; `shared["__warnings__"][node_id]["kind"] == "claude_code.schema_not_satisfied"` |
| `test_partial_json_response` → `test_sdk_is_error_branch` | 614 | Rename. Mock yields `ResultMessage(structured_output=None, is_error=True, result="error context")`. Assert `"Claude CLI reported an error" in shared["_schema_error"]`; `__warnings__[node_id]["kind"] == "claude_code.sdk_error_no_structured_output"` |

**Keep unchanged** (no schema involved):
- `test_no_response_content` (649)
- `test_post_method` (813)

**Behavior change to document**: with native SDK + JSON Schema `required`, "partial" responses no longer occur. The SDK either complies (full dict) or rejects (`is_error=True` / `structured_output=None`). The previous auto-fill-missing-keys-with-`None` behavior is gone — missing optional fields are simply absent from the result dict.

### 2.4 Add new tests

Each new test must set the node's params before running `prep` (follow whatever fixture pattern the existing test file uses — likely `claude_node.params = {...}` or a fixture parametrization).

```python
def test_output_schema_wrapped_and_passed_to_options(claude_node):
    """JSON Schema is wrapped in {"type": "json_schema", "schema": ...} and reaches ClaudeAgentOptions."""
    prep_res = {
        "prompt": "test",
        "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        # ... other required prep_res fields (model, max_turns, cwd, etc.)
    }
    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")
    assert mock_options.call_args.kwargs["output_format"] == {
        "type": "json_schema",
        "schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    }

def test_no_schema_means_no_output_format(claude_node):
    """Without output_schema, output_format kwarg is absent."""
    prep_res = {"prompt": "test", ...}  # no output_schema
    with patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options:
        claude_node._build_claude_options(prep_res, "")
    assert "output_format" not in mock_options.call_args.kwargs

def test_legacy_python_alias_schema_rejected(claude_node):
    """Old custom format raises with migration guidance."""
    with pytest.raises(ValueError, match="legacy Python-alias format"):
        claude_node._validate_schema(
            {"risk_level": {"type": "str", "description": "high/medium/low"}}
        )

def test_legacy_format_detection_checks_all_values(claude_node):
    """Detection must check ALL values, not just the first."""
    # First value is non-dict (e.g. metadata marker); second is legacy format
    schema = {"_meta": "comment", "risk": {"type": "str", "description": "..."}}
    with pytest.raises(ValueError, match="legacy Python-alias format"):
        claude_node._validate_schema(schema)

def test_oneOf_top_level_schema_accepted(claude_node):
    """JSON Schema with oneOf at top level (no top-level 'type') passes prep validation.
    May be rejected by API at runtime — surfaces via soft-fail path. Phase 0 didn't probe."""
    schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
    assert claude_node._validate_schema(schema) == schema

def test_top_level_array_schema_rejected(claude_node):
    """Phase 0 finding: API rejects non-object top-level schemas; catch at prep time."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"type": "array", "items": {"type": "string"}})

def test_top_level_primitive_schema_rejected(claude_node):
    """Phase 0 finding: type: string at top level is also rejected by API."""
    with pytest.raises(ValueError, match="top-level type: object"):
        claude_node._validate_schema({"type": "string", "enum": ["yes", "no"]})

def test_max_turns_too_low_with_schema_rejected(claude_node):
    """Phase 0 finding: structured output needs max_turns >= 2. Prep must reject 1."""
    # Set params with output_schema and max_turns=1; assert ValueError mentioning max_turns
    # Pattern: set claude_node.params = {"prompt": "test", "output_schema": {"type":"object",...}, "max_turns": 1, ...}
    # with pytest.raises(ValueError, match="max_turns must be >= 2"):
    #     claude_node.prep({})

def test_empty_schema_dict_rejected(claude_node):
    """Empty dict {} likely indicates a typo; raises."""
    with pytest.raises(ValueError, match="empty"):
        claude_node._validate_schema({})

def test_none_schema_returns_none(claude_node):
    """None means no schema; returns None silently."""
    assert claude_node._validate_schema(None) is None

def test_non_dict_schema_raises_typeerror(claude_node):
    """Non-dict raises TypeError."""
    with pytest.raises(TypeError):
        claude_node._validate_schema(["not", "a", "dict"])

def test_structured_output_stored_as_dict(claude_node, shared_store):
    """ResultMessage.structured_output flows directly to shared['result']."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    async def mock_response(*args, **kwargs):
        yield AssistantMessage(content=[TextBlock(text="done")])
        yield ResultMessage(structured_output={"x": "hello"}, is_error=False)
    with patch("pflow.nodes.claude.claude_code.query") as mock_query:
        mock_query.return_value = mock_response()
        # ... set params + run prep → exec → post lifecycle
    assert shared_store["result"] == {"x": "hello"}
    assert "_schema_error" not in shared_store
    assert "__warnings__" not in shared_store  # or node_id not in shared_store["__warnings__"]

def test_structured_output_none_writes_warning_and_schema_error(claude_node, shared_store):
    """Schema set + structured_output None: soft-fail + __warnings__ + _schema_error."""
    # mock yields ResultMessage(structured_output=None, result="raw", is_error=False)
    # assert shared["result"] == "raw"
    # assert "Model did not return" in shared["_schema_error"]
    # assert shared["__warnings__"][node_id]["kind"] == "claude_code.schema_not_satisfied"

def test_sdk_is_error_with_structured_output_emits_warning(claude_node, shared_store):
    """is_error=True + structured_output present: structured_output wins, but warning is emitted."""
    # mock yields ResultMessage(structured_output={"x": 1}, is_error=True)
    # assert shared["result"] == {"x": 1}
    # assert shared["__warnings__"][node_id]["kind"] == "claude_code.sdk_error_with_structured_output"

def test_nested_array_schema(claude_node, shared_store):
    """Array nested INSIDE an object works (top-level must be object per API limit)."""
    # Schema: {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}}, "required": ["items"]}
    # mock yields ResultMessage(structured_output={"items": ["a","b","c"]}, is_error=False)
    # assert shared["result"] == {"items": ["a","b","c"]}
    # assert isinstance(shared["result"]["items"], list)

def test_sticky_is_error_across_multiple_result_messages(claude_node, shared_store):
    """is_error=True on an early ResultMessage persists even if a later one is False."""
    # mock yields:
    #   ResultMessage(is_error=True, structured_output=None)
    #   ResultMessage(is_error=False, structured_output=None)
    # assert "Claude CLI reported an error" in shared["_schema_error"]
```

### 2.5 `tests/CLAUDE.md` pitfall #17 update

Update pitfall #17 to:
- Note that `ResultMessage` is now a real `@dataclass` in the test file (no longer auto-Mocked)
- Document the load-bearing ordering: `mock_sdk_types.ResultMessage = ResultMessage` MUST precede `sys.modules["claude_agent_sdk.types"] = mock_sdk_types`

### 2.6 `tests/shared/markdown_utils.py:119` comment update

Change the comment from `"Claude-code output schema"` to `"output_schema (JSON Schema) — node-agnostic"` so future maintainers don't mistake the helper for claude-code-specific. The behavior is unchanged.

### Phase 2 verification

```bash
uv run pytest tests/test_nodes/test_claude/ -v
make check
```

All tests should pass. If `make check` flags style issues on the new code, fix them.

---

## Phase 3 — Examples + docs

### 3.1 Example workflow files

For each of the 3 files below, convert the schema body inside the ` ```yaml output_schema ` block from Python-alias to JSON Schema using this rule:

```yaml
# Before (Python-alias, FLAT field map)
field_name:
  type: str       # → "string"
  type: int       # → "integer"
  type: bool      # → "boolean"
  type: list      # → "array" + add items
  type: float     # → "number"
  description: ...

# After (JSON Schema)
type: object
properties:
  field_name:
    type: string  # (etc.)
    description: ...
required: [field_name, ...]  # add for fields the workflow needs
```

**Files**:
- `examples/nodes/claude-code/claude-code-schema.pflow.md` (lines 33–52, 6 fields)
- `examples/nodes/claude-code/claude-code-debug.pflow.md` (lines 42–58, 6 fields)
- `examples/nodes/claude-code/claude-code-git-workflow.pflow.md` (lines 35–50 AND 71–81 — two `output_schema` blocks)

**Concrete example** for `claude-code-schema.pflow.md`:

```yaml
# Before:
overall_quality:
  type: str
  description: Code quality (excellent/good/fair/poor)
security_score:
  type: int
  description: Security score 1-10
issues:
  type: list
  description: List of issues
has_critical_issues:
  type: bool
  description: Whether critical issues exist

# After:
type: object
properties:
  overall_quality:
    type: string
    enum: [excellent, good, fair, poor]
    description: Code quality rating
  security_score:
    type: integer
    minimum: 1
    maximum: 10
    description: Security score 1-10
  issues:
    type: array
    items:
      type: string
    description: List of issues
  has_critical_issues:
    type: boolean
    description: Whether critical issues exist
required: [overall_quality, security_score, issues, has_critical_issues]
```

### 3.2 Example README

**`examples/nodes/claude-code/README.md`**:
- Lines 35, 67–79, 83, 130, 144 — update format references
- Line 83: `${node._schema_error}` documentation stays accurate (key name unchanged); add a sentence about `__warnings__` and DEGRADED status
- Line 144: change "eliminates regex parsing" → "delegates to the SDK's native structured-output mode"

### 3.3 User-facing docs

**`docs/reference/nodes/claude-code.mdx`**:
- Line 28 parameter table description: "JSON Schema for structured output"
- Lines 103–123: replace Python-alias example with JSON Schema example (use the converted `claude-code-schema.pflow.md` as the source of truth)
- Lines 175–184: same conversion
- Add a new paragraph documenting:
  - `shared["_schema_error"]` (set on soft-fail)
  - `shared["__warnings__"][node_id]` (workflow status → DEGRADED)
  - Distinction between schema_not_satisfied (model didn't comply) and sdk_error_no_structured_output (CLI reported an error)

### 3.4 Architecture doc

**`architecture/core-node-packages/claude-nodes.md`** — update BOTH lines 38 AND 39:

- Line 38 (Params): keep "JSON schema for structured outputs (optional)" — already accurate
- Line 39 (Writes): change `any  # Response - string or dict with schema keys` → `str|dict  # Free-form text (str), or parsed JSON (dict/list) when output_schema is set, or raw text on soft schema failure`
- Add a new `Writes:` line documenting `__warnings__[node_id]` and the DEGRADED signal

### 3.5 Validation gate

```bash
uv run pytest tests/test_docs/test_example_validation.py -v
```

The validator does NOT inspect `output_schema` content (`grep -rn output_schema src/pflow/core/workflow/` returns no matches), so migrated examples should pass. If any fail, inspect.

---

## Phase 4 — types.py, pyproject.toml, CHANGELOG

### 4.1 `src/pflow/core/types.py` — delete "fourth surface" comment

Lines 8–12 carve `output_schema` out of the S1 vocabulary because the Python-alias type names were embedded in the prompt template (`_build_schema_prompt`). After Phase 1.1 deletes that method, the reason no longer exists.

**Delete the comment block entirely.** Do not rewrite to a one-liner — the relevant information already lives in `docs/reference/nodes/{llm,claude-code}.mdx`.

### 4.2 `pyproject.toml` — bump SDK pin  ✅ DONE (prework)

Already applied as prework: `"claude-agent-sdk>=0.2.82"` (was `>=0.1.17`). Lockfile resolved to 0.2.82. Existing Claude Code test suite passed against the upgraded SDK (47/47).

**Implementing agent**: no action needed for 4.2. Verify with:
```bash
grep claude-agent-sdk pyproject.toml uv.lock | head -5
```
Should show `>=0.2.82` in `pyproject.toml` and `version = "0.2.82"` in `uv.lock`.

### 4.3 CHANGELOG entry

Add an entry in `CHANGELOG.md` documenting:
- **Breaking change**: any local workflow using the legacy `{"field": {"type": "str", ...}}` format on a `claude-code` node will now fail validation with a migration error pointing at JSON Schema docs
- **New behavior**: schema soft-failures now write to `shared["__warnings__"]` and surface as workflow status `DEGRADED` (visible in `pflow ... --output-format json`)
- **Registry refresh note**: PyPI users may see the old Interface description in `pflow registry list claude-code` until the next pflow version bump (editable dev installs refresh automatically via mtime)

---

## Phase 5 — Verification

### 5.1 Pre-Phase-3 checkpoint

After Phases 1 and 2 are complete (claude_code.py + tests rewritten, all tests pass, `make check` clean):

**Run `/code-review` on `src/pflow/nodes/claude/claude_code.py` and `tests/test_nodes/test_claude/test_claude_code.py`.** Resolve confirmed findings before proceeding to Phase 3.

### 5.2 Final quality gates

```bash
uv run pytest tests/test_nodes/test_claude/ -v
uv run pytest tests/test_docs/test_example_validation.py -v
make test          # full suite, 4,600+ tests
make check         # ruff + mypy
make test-e2e
```

### 5.3 Registry refresh

```bash
pflow registry list claude-code
```

Confirm the new Interface description appears (editable install — mtime triggers refresh).

### 5.4 Manual smoke test (real model call — subscription absorbs cost)

```bash
# Confirm no API key is set (use subscription auth)
unset ANTHROPIC_API_KEY  # if it happens to be set
uv run pflow examples/nodes/claude-code/claude-code-schema.pflow.md
```

If you're on a Claude Pro/Max/Team subscription, this is absorbed by the subscription (verified in Phase 0). If you don't have a subscription, set `ANTHROPIC_API_KEY` to use pay-as-you-go (~$0.05–0.50).

Verify:
- Workflow completes successfully
- Downstream nodes receive a parsed dict in `${review.result.*}`
- Template resolution works (e.g. `${review.result.overall_quality}`)
- No `_schema_error` in trace

### 5.5 Manual negative cases

1. **Legacy format inline**: hand-write a temporary `.pflow.md` with `{"risk_level": {"type": "str"}}` inline in a code block. Confirm CLI shows the migration error with guidance.
2. **Legacy format via file ref**: same legacy schema in `./schema.yaml`, referenced as `- output_schema: ./schema.yaml`. Confirm error surfaces. The error may not pinpoint the source file precisely (file_resolver does not preserve attribution); document that limitation if observed.
3. **Empty dict**: `{}` in the schema body. Confirm clear "empty" error.
4. **Top-level array schema**: `{"type": "array", "items": {"type": "string"}}` on a `claude-code` node. Confirm clear "top-level type: object" error pointing at the API limitation.
5. **`max_turns: 1` with schema**: Confirm clear "max_turns must be >= 2" error.

### 5.6 Cleanup

```bash
rm -rf scratchpads/task_126/   # Phase 0 smoke test artifacts
```

`phase-0-findings.md` lives in `.taskmaster/tasks/task_126/implementation/` and is preserved.

---

## Critical files reference

### Code to modify
| File | Phase |
|---|---|
| `src/pflow/nodes/claude/claude_code.py` | 1 — main refactor |
| `src/pflow/core/types.py` | 4.1 — delete lines 8–12 |
| `pyproject.toml` | 4.2 — bump claude-agent-sdk |
| `CHANGELOG.md` | 4.3 — new entry |

### Tests to modify
| File | Phase |
|---|---|
| `tests/test_nodes/test_claude/test_claude_code.py` | 2 — mock + tests |
| `tests/CLAUDE.md` | 2.5 — pitfall #17 |
| `tests/shared/markdown_utils.py` | 2.6 — line 119 comment |

### Docs/examples to modify
| File | Phase |
|---|---|
| `examples/nodes/claude-code/claude-code-schema.pflow.md` | 3.1 |
| `examples/nodes/claude-code/claude-code-debug.pflow.md` | 3.1 |
| `examples/nodes/claude-code/claude-code-git-workflow.pflow.md` | 3.1 |
| `examples/nodes/claude-code/README.md` | 3.2 |
| `docs/reference/nodes/claude-code.mdx` | 3.3 |
| `architecture/core-node-packages/claude-nodes.md` | 3.4 (lines 38 AND 39) |

### Files to READ for context (do not modify)
| File | Why |
|---|---|
| `src/pflow/nodes/llm/llm.py:795` | `node_id` retrieval pattern: `getattr(self, "node_id", None)` |
| `src/pflow/nodes/llm/llm.py:289-301` | Canonical `__warnings__` write shape |
| `src/pflow/nodes/llm/llm.py:296` | `if node_id is not None:` guard |
| `src/pflow/core/llm_client.py:300-304` | LLM node's schema → response_format wrapping (analog for our output_format wrapping) |
| `src/pflow/runtime/workflow_trace.py:457-466` | `__warnings__` → DEGRADED status mechanism |
| `src/pflow/runtime/compilation/compiler.py:299` | Where `node.node_id` is set at compile time |
| `claude_agent_sdk/types.py:587-680` (cache path) | SDK source: `ResultMessage` + `ClaudeAgentOptions` field definitions |
| `claude_agent_sdk/_internal/transport/subprocess_cli.py:316-325` | SDK source: only `{"type": "json_schema", "schema": ...}` is wired |

---

## Edge case resolutions (implementation decisions)

| Edge case | Implementation behavior |
|---|---|
| `output_schema = None` (key absent) | `_validate_schema` returns `None` → no-schema path |
| `output_schema = {}` (empty) | `_validate_schema` raises with "did you forget the schema body?" |
| `output_schema = [list, not, dict]` | `_validate_schema` raises `TypeError` |
| Legacy Python-alias format | `_validate_schema` raises with migration guidance |
| Legacy format where first value is non-dict | Detection iterates ALL values; still caught |
| JSON Schema with `oneOf`/`anyOf`/`allOf`/`enum`/`const` (no top-level `type`) | Rejected at prep (oneOf follow-up probe: API returns HTTP 400). Wrap in `{"type": "object", ...}`. |
| JSON Schema with `$ref` / external refs | Passed through to SDK; SDK/CLI decides |
| Top-level `type: array` or primitive (`type: string`, etc.) | `_validate_schema` raises (Phase 0 finding: API rejects non-object top-level schemas in tool input_schema wrapping). Workflow author must wrap in an object. |
| Top-level `oneOf`/`anyOf`/`allOf` (no top-level `type`) | Rejected at prep (post-impl finding); error message names the combinator. |
| Nested array (`{"type": "object", "properties": {"items": {"type": "array", ...}}}`) | Works normally; `structured_output` is the wrapping object |
| Multiple `ResultMessage` instances | Last `structured_output` wins; `is_error_from_sdk` is sticky-true (defensive — Phase 0 did not observe multi-message) |
| `structured_output` empty (`{}`) | Stored as-is — empty object is a valid structured response |
| `max_turns = 1` with output_schema | `prep` raises (Phase 0 finding: structured output needs ≥2 turns) |
| Schema typo (e.g. `type: intger`) | API silently accepts; soft-fail with generic "model did not return" message. Centralized validation in #398 will catch these early |
| `is_error=True` AND `structured_output` present | `structured_output` becomes `shared["result"]`; `__warnings__` written for visibility |
| `is_error=True` AND `structured_output` None | Soft-fail with CLI-error variant of `_schema_error` + `__warnings__` |
| SDK raises before any `ResultMessage` | Existing `exec_fallback` path (line 681) handles — hard error, retries |
| SDK has no `structured_output` field (version drift) | Phase 1.0 import-time probe raises `ImportError` |
| `node_id` is `None` (uncompiled node, direct test) | `__warnings__` write skipped; `_schema_error` still set; matches LLM node pattern |

---

## Out of scope (deliberately deferred)

- **`pflow guide` page for claude-code** — no existing page; file separately
- **Centralized JSON Schema syntactic validation** — see GitHub issue #398 (cross-cutting concern; per-node validation duplicates work)
- **`claude_client.py` adapter** analogous to `llm_client.py` — `claude_agent_sdk` has one consumer; premature abstraction
- **Per-node retry on schema mismatch** — soft-fail is the chosen semantics
- **Backwards compatibility shim** for legacy Python-alias format — no users (CLAUDE.md)
- **Legacy → JSON Schema converter tool** — out of scope per "no users"
- **JSON Schema validity validation at prep time** — deferred to #398

---

## Follow-up GitHub issue

Filed as **#398**: https://github.com/spinje/pflow/issues/398 — "Centralized JSON Schema validation for output_schema across nodes". Will be picked up after Task 126 ships.
