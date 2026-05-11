# Plan: Surface per-call cache telemetry in `--report` and `analyze-cache` JSON

## Context

Stage 2 verification of Task 159 (`scratchpads/stage2-verification/song-creator/REPORT.md`) surfaced **Findings #4 and #5** as one connected gap: the cache telemetry an agent needs to verify "did caching fire on this call?" is recorded in the trace's `event["llm_call"]` dict but is invisible from both natural surfaces. To check whether cache reads/writes happened on a specific call, an agent must drop to raw trace JSON and parse it manually.

Concretely:
- `pflow run --report` per-node markdown shows the cached system block (`## Cached System`, added in trace 2.2.0) but NOT the per-call cache token observations the provider returned (`cache_creation_input_tokens`, `cache_read_input_tokens`) nor the engine-augmented memo signals (`cache_source`, `cache_key`, `cache_age_sec`).
- `pflow analyze-cache --format=json` per_call rows expose analyzer-computed projections (`cacheable_tokens_estimated`, `cache_ratio_pct`) but NOT the raw billing-relevant token splits — losing the creation-vs-read distinction that lets an agent reason about a specific run.

Outcome: a new `## Cache telemetry` markdown section in `--report` that surfaces the cache observations per LLM call (with a heading tag distinguishing fresh provider calls from cache replays without leaking pflow vocabulary), and 2 additive fields on per_call JSON rows (`cache_creation_input_tokens`, `cache_read_input_tokens`) carrying raw trace observations alongside the existing analyzer projections.

Also folds in: `thinking_tokens` rendering in `--report` metadata bullets (only when > 0). `thinking_tokens` belongs conceptually with input/output token counts, not with cache; placing it in metadata makes it visible regardless of caching state and keeps `## Cache telemetry` semantically tight.

## What changes (before / after)

### `--report` markdown — fresh provider call

**Before** (current `_build_node_file` output for an LLM event):

```
# creative-direction

- Type: LLMNode
- Time: 47000ms
- Status: success
- Model: anthropic/claude-haiku-4-5
- Tokens: 9,220 in / 850 out
- Cost: $0.0102

## Cached System

```json
[{"type": "text", "text": "Background"}, {"type": "text", "text": "Reference", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
```

## Prompt

Generate creative direction for "The Third Plate"...
```

**After** (new `## Cache telemetry` section between `## Cached System` and `## Prompt`; thinking bullet in metadata when present):

```
# creative-direction

- Type: LLMNode
- Time: 47000ms
- Status: success
- Model: anthropic/claude-haiku-4-5
- Tokens: 9,220 in / 850 out
- Cost: $0.0102

## Cached System

```json
[{"type": "text", "text": "Background"}, {"type": "text", "text": "Reference", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
```

## Cache telemetry

- Cache write: 0 tokens
- Cache read: 8,062 tokens
- Cache key: b2ce56961b2fa59a4bc0e598a3ae6b2f

## Prompt

Generate creative direction for "The Third Plate"...
```

### `--report` markdown — call served from a cached prior result

`cache_source` field is present on the trace event's `llm_call`. Heading carries a tag; result age renders as a bullet.

```
## Cache telemetry (cached result reused from prior run)

- Cache write: 0 tokens
- Cache read: 8,062 tokens
- Cache key: b2ce56961b2fa59a4bc0e598a3ae6b2f
- Result age: 560s
```

User-facing rendering does NOT include the literal strings `"memo"` or `"in_process"` — `cache_source` presence is a pure gate, never displayed.

### `--report` markdown — thinking enabled

Thinking bullet appears in metadata when `thinking_tokens > 0`. No section moved; just one bullet added inside `_format_node_metadata`.

```
- Tokens: 9,220 in / 850 out
- Thinking: 1,024 tokens
- Cost: $0.0102
```

### `--report` markdown — call without any cache activity

Workflow without `## Cache` declared, plain LLM call. `cache_creation == 0`, `cache_read == 0`, `cache_source` absent, `cache_chunks_skipped == []`. Section is **suppressed** entirely — same precedent as `_format_cached_system` skipping when `llm_system` is absent. No noise.

### `analyze-cache` per_call JSON — additive

```json
{
  "per_call": [
    {
      "node_path": "creative-direction",
      "model": "anthropic/claude-haiku-4-5",
      ...
      "cacheable_tokens_estimated": 8062,
      "cache_ratio_pct": 88,
      "cache_creation_input_tokens": 0,            // NEW
      "cache_read_input_tokens": 8062,             // NEW
      "data_source": "trace",
      ...
    }
  ]
}
```

Both fields are `null` when no trace data is available (greenfield analysis). Trace tier populates with the integer value the trace recorded (including 0).

## Design

### `cache_analysis/analyze.py` — extend `PerCallRow` and populate from trace

**`PerCallRow` dataclass** — add 2 fields adjacent to existing cache-related fields. Insertion site: after `cacheable_data_source: str = "unavailable"` and before `cost_usd: float | None = None` (currently around line 123 of the dataclass body, declarative file `src/pflow/core/cache_analysis/analyze.py`):

```python
# Stage 2 follow-up — Findings #4/#5: raw per-call cache token splits from
# the trace event's ``llm_call`` dict. ``None`` when no trace data; ``int``
# (including 0) when trace populated. Independent of the analyzer's
# ``cacheable_tokens_estimated`` projection — these are the observed splits,
# the projection is the SUM clamped to billed input.
cache_creation_input_tokens: int | None = None
cache_read_input_tokens: int | None = None
```

**`_build_per_call_row` population** — the function already receives `trace_llm_call: dict[str, Any] | None = None` (parameter at line 1044). The existing read pattern in `_estimate_row_tokens` (lines 1216-1218) is `int(trace_llm_call.get("cache_creation_input_tokens") or 0)`. Mirror it:

```python
# Insertion: inside _build_per_call_row body, before the return statement
# (around line 1156, after cost_value/cost_source assignment block).
trace_cache_creation: int | None = (
    int(trace_llm_call.get("cache_creation_input_tokens") or 0)
    if trace_llm_call is not None
    else None
)
trace_cache_read: int | None = (
    int(trace_llm_call.get("cache_read_input_tokens") or 0)
    if trace_llm_call is not None
    else None
)
```

Add to `return PerCallRow(...)` block (currently lines 1157-1175):

```python
    cache_creation_input_tokens=trace_cache_creation,
    cache_read_input_tokens=trace_cache_read,
```

Place after `cost_data_source=cost_source,` and before `workflow_path=workflow_path,` to mirror the dataclass field order.

### `cache_analysis/render_json.py` — emit 2 new keys

**`_per_call_to_dict`** (lines 162-196) — add 2 keys after `cache_ratio_pct`, before `data_source` (group with cache-related projections):

```python
"cache_ratio_pct": row.cache_ratio_pct,
"cache_creation_input_tokens": row.cache_creation_input_tokens,  # NEW
"cache_read_input_tokens": row.cache_read_input_tokens,           # NEW
"data_source": row.data_source,
```

No conditional logic. Both fields project unconditionally — `null` propagates naturally when `PerCallRow.cache_*_input_tokens` is `None`.

### `core/trace_report.py` — new helper + thinking bullet in metadata

**Add `_format_cache_telemetry` helper** (parallel to `_format_cached_system` at lines 794-817). Inserted immediately after `_format_cached_system` in source order:

```python
def _format_cache_telemetry(event: dict[str, Any], lines: list[str]) -> None:
    """Render the ``## Cache telemetry`` section.

    Surfaces per-call cache observations from the trace event's ``llm_call``
    dict so agents don't need to drop to raw trace JSON to verify caching.
    No-op when the event has no cache signal (no llm_call, all zero, no
    cached-replay marker, no skipped chunks). Mirrors ``_format_cached_system``
    in shape and naming.

    Heading carries ``(cached result reused from prior run)`` tag when the
    call was served from a cached prior result (gated on ``cache_source``
    presence, which is never itself rendered — the field's literal values
    are pflow-internal vocabulary).
    """
    llm_call = event.get("llm_call") or {}
    if not isinstance(llm_call, dict):
        return

    cache_creation = llm_call.get("cache_creation_input_tokens")
    cache_read = llm_call.get("cache_read_input_tokens")
    cache_key = llm_call.get("cache_key")
    cache_age_sec = llm_call.get("cache_age_sec")
    chunks_skipped = llm_call.get("cache_chunks_skipped") or []
    is_cached_replay = bool(llm_call.get("cache_source"))

    # Gate: render when there's any cache signal worth showing.
    has_signal = (
        is_cached_replay
        or (isinstance(cache_creation, int) and cache_creation > 0)
        or (isinstance(cache_read, int) and cache_read > 0)
        or bool(chunks_skipped)
    )
    if not has_signal:
        return

    if is_cached_replay:
        lines.append("## Cache telemetry (cached result reused from prior run)")
    else:
        lines.append("## Cache telemetry")
    lines.append("")

    if isinstance(cache_creation, int):
        lines.append(f"- Cache write: {cache_creation:,} tokens")
    if isinstance(cache_read, int):
        lines.append(f"- Cache read: {cache_read:,} tokens")
    if cache_key:
        lines.append(f"- Cache key: {cache_key}")
    if is_cached_replay and isinstance(cache_age_sec, (int, float)):
        lines.append(f"- Result age: {cache_age_sec:.0f}s")
    lines.append("")
```

**Wire into `_format_resolutions`** (lines 820-865). Single new line after the existing `_format_cached_system(event, lines)` call (line 831):

```python
    _format_cached_system(event, lines)
    _format_cache_telemetry(event, lines)  # NEW
```

This places `## Cache telemetry` between `## Cached System` and `## Prompt` rendering. Confirmed by verification: `_format_resolutions` is called from `_build_node_file:875` for top-level events AND from `_build_node_file:1064` for batch items — the new section appears in both per-node files and per-batch-item files (correct: batch items also have cache telemetry in their `llm_call`).

**Extend `_format_node_metadata`** (lines 701-726) — add `thinking_tokens` bullet when present and > 0. Insert after the existing `Tokens` bullet (line 715), before the `Cost` bullet:

```python
    lines.append(f"- Tokens: {tokens_in:,} in / {tokens_out:,} out")
    thinking_tokens = llm_call.get("thinking_tokens")  # NEW
    if isinstance(thinking_tokens, int) and thinking_tokens > 0:
        lines.append(f"- Thinking: {thinking_tokens:,} tokens")
    cost = llm_call.get("cost_usd")
```

`thinking_tokens` placement (metadata vs cache telemetry section) is a refinement on the user's D1=B choice: thinking is a token observation analogous to input/output, not a cache concept. Putting it in metadata avoids losing the signal on workflows where caching isn't active.

## Files to modify

### Production (3 files)

1. **`src/pflow/core/cache_analysis/analyze.py`**
   - Add 2 fields to `PerCallRow` dataclass after `cacheable_data_source` (~line 123 of dataclass body).
   - Add 2 trace-extraction lines in `_build_per_call_row` (around line 1156).
   - Add 2 kwargs to the `return PerCallRow(...)` block (lines 1157-1175).
   - **Net ~+15 LOC.**

2. **`src/pflow/core/cache_analysis/render_json.py`**
   - Add 2 keys to `_per_call_to_dict` (lines 162-196), positioned after `cache_ratio_pct`.
   - **Net ~+2 LOC.**

3. **`src/pflow/core/trace_report.py`**
   - Add `_format_cache_telemetry` helper (~40 LOC) after `_format_cached_system` (line 817).
   - Add 1 line in `_format_resolutions` to call the helper (after line 831).
   - Add 3 lines in `_format_node_metadata` for thinking-tokens bullet (after line 715).
   - **Net ~+45 LOC.**

### Tests (3 files)

4. **`tests/test_core/test_cache_analysis_renderers.py`** — add 2 tests after the prompt_body_cleanup pattern at lines 1918-1946.

   ```python
   def test_render_json_includes_cache_creation_and_read_tokens() -> None:
       """Per_call rows surface raw trace cache token splits."""
       row = _make_per_call_row(
           cache_creation_input_tokens=1500,
           cache_read_input_tokens=8062,
           data_source="trace",
       )
       base = _make_analysis()
       analysis = CacheAnalysis(**{**base.__dict__, "per_call": (row,)})
       payload = render_json(analysis)
       row_dict = payload["per_call"][0]
       assert row_dict["cache_creation_input_tokens"] == 1500
       assert row_dict["cache_read_input_tokens"] == 8062

   def test_render_json_per_call_cache_tokens_null_on_greenfield() -> None:
       """No trace data → cache token fields are null."""
       row = _make_per_call_row(
           cache_creation_input_tokens=None,
           cache_read_input_tokens=None,
           data_source="estimator",
       )
       base = _make_analysis()
       analysis = CacheAnalysis(**{**base.__dict__, "per_call": (row,)})
       payload = render_json(analysis)
       row_dict = payload["per_call"][0]
       assert row_dict["cache_creation_input_tokens"] is None
       assert row_dict["cache_read_input_tokens"] is None
   ```

   Where `_make_per_call_row` is the existing test helper (search for it in this file; the test_render_json_includes_prompt_body_cleanup_key pattern at line 1918 shows similar helper usage). If no such helper exists, use direct `PerCallRow(...)` construction.

5. **`tests/test_core/test_cache_analysis_analyze.py`** — add 1 brownfield end-to-end test mirroring the existing pattern around line 1844 (where `cacheable_tokens_estimated == 800` is asserted from a trace with `cache_creation=600, cache_read=200`):

   ```python
   def test_per_call_row_carries_raw_cache_token_splits_from_trace() -> None:
       """_build_per_call_row populates cache_creation/cache_read from trace_llm_call."""
       # Build a synthetic trace with cache_creation=1500, cache_read=8062 (typical
       # Anthropic mid-run shape). Run analyze() end-to-end. Assert per_call row carries
       # the splits raw, NOT just the sum (which would lose the creation-vs-read distinction).
       # Mirrors the test at line 1844 but asserts on the new fields.
       ...
       row = next(r for r in analysis.per_call if r.node_path == "test-node")
       assert row.cache_creation_input_tokens == 1500
       assert row.cache_read_input_tokens == 8062
       assert row.data_source == "trace"
   ```

   Mutation contract: reverting either of the new `_build_per_call_row` extraction lines (back to `None`) makes this test fail.

6. **`tests/test_core/test_trace_report.py`** — add a new test class `TestCacheTelemetrySection` after `TestCachedSystemSection` (~line 523). Tests mirror the existing TestCachedSystemSection style (`_make_event(**overrides)` + `_build_node_file(event)` + substring/index assertions).

   ```python
   class TestCacheTelemetrySection:
       """Trace 2.2.0 follow-up: per-call cache telemetry section.

       Mirrors TestCachedSystemSection's shape (helper-based event construction +
       substring/index assertions on the rendered markdown).
       """

       def test_renders_section_when_cache_creation_nonzero(self) -> None:
           event = _make_event(
               llm_call={
                   "cache_creation_input_tokens": 1500,
                   "cache_read_input_tokens": 0,
                   "cache_key": "abc123",
               },
           )
           md = _build_node_file(event)
           assert "## Cache telemetry" in md
           assert "Cache write: 1,500 tokens" in md
           assert "Cache read: 0 tokens" in md
           assert "Cache key: abc123" in md

       def test_renders_section_when_cache_read_nonzero(self) -> None:
           event = _make_event(
               llm_call={
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 8062,
                   "cache_key": "def456",
               },
           )
           md = _build_node_file(event)
           assert "## Cache telemetry" in md
           assert "Cache read: 8,062 tokens" in md

       def test_omitted_when_no_cache_signal(self) -> None:
           """Plain LLM call without any cache activity: section suppressed."""
           event = _make_event(
               llm_call={
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0,
                   "cache_key": "xyz",  # cache_key alone is not a cache-firing signal
                   "cache_chunks_skipped": [],
               },
           )
           md = _build_node_file(event)
           assert "## Cache telemetry" not in md

       def test_omitted_when_no_llm_call(self) -> None:
           """Non-LLM events have no llm_call → no cache telemetry section."""
           event = _make_event()  # no llm_call override
           md = _build_node_file(event)
           assert "## Cache telemetry" not in md

       def test_cached_replay_heading_tag_appears(self) -> None:
           """When cache_source is present (memo replay), heading carries the tag."""
           event = _make_event(
               llm_call={
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 8062,
                   "cache_source": "memo",
                   "cache_key": "abc",
                   "cache_age_sec": 559.99,
               },
           )
           md = _build_node_file(event)
           assert "## Cache telemetry (cached result reused from prior run)" in md
           assert "Result age: 560s" in md

       def test_cached_replay_heading_tag_does_not_leak_pflow_vocabulary(self) -> None:
           """User-facing rendering must not surface 'memo' or 'in_process'."""
           event = _make_event(
               llm_call={
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 8062,
                   "cache_source": "memo",
                   "cache_key": "abc",
                   "cache_age_sec": 559.99,
               },
           )
           md = _build_node_file(event)
           # cache_source's literal values must never appear in rendered output.
           assert "memo" not in md.lower()
           assert "in_process" not in md.lower()

       def test_section_appears_between_cached_system_and_prompt(self) -> None:
           """Order: ## Cached System → ## Cache telemetry → ## Prompt."""
           event = _make_event(
               llm_system="System content",
               llm_call={
                   "cache_creation_input_tokens": 1500,
                   "cache_read_input_tokens": 0,
                   "cache_key": "abc",
               },
               template_resolutions={"prompt": {"template": "Hi", "resolved": "Hi there"}},
           )
           md = _build_node_file(event)
           cached_idx = md.index("## Cached System")
           telemetry_idx = md.index("## Cache telemetry")
           prompt_idx = md.index("## Prompt")
           assert cached_idx < telemetry_idx < prompt_idx

       def test_renders_when_chunks_skipped_present(self) -> None:
           """Skipped chunks alone is a cache signal — section renders even with zero tokens."""
           event = _make_event(
               llm_call={
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0,
                   "cache_key": "abc",
                   "cache_chunks_skipped": ["foo"],
               },
           )
           md = _build_node_file(event)
           assert "## Cache telemetry" in md

       def test_thinking_tokens_renders_in_metadata_when_nonzero(self) -> None:
           """Thinking goes in metadata bullets, not the cache telemetry section."""
           event = _make_event(
               llm_call={
                   "model": "anthropic/claude-haiku-4-5",
                   "input_tokens": 100,
                   "output_tokens": 50,
                   "thinking_tokens": 1024,
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0,
               },
           )
           md = _build_node_file(event)
           assert "- Thinking: 1,024 tokens" in md
           # Thinking renders in metadata, not Cache telemetry
           # (cache telemetry section is suppressed when no cache signal).
           assert "## Cache telemetry" not in md

       def test_thinking_tokens_omitted_in_metadata_when_zero(self) -> None:
           event = _make_event(
               llm_call={
                   "model": "anthropic/claude-haiku-4-5",
                   "input_tokens": 100,
                   "output_tokens": 50,
                   "thinking_tokens": 0,
               },
           )
           md = _build_node_file(event)
           assert "Thinking" not in md
   ```

## Existing functions/utilities reused

- `_format_cached_system` (`trace_report.py:794-817`) — the architectural sibling. New `_format_cache_telemetry` mirrors its signature `(event: dict, lines: list) -> None`, in-place append, no-op gate, section heading + blank line + bullets + trailing blank line.
- `_format_node_metadata` (`trace_report.py:701-726`) — extended with thinking bullet, mirrors existing `Tokens` and `Cost` bullet patterns (`f"- Label: ...":,` formatting).
- `_estimate_row_tokens` cache-extraction pattern (`analyze.py:1216-1218`) — `int(trace_llm_call.get("cache_creation_input_tokens") or 0)` mirrored verbatim in `_build_per_call_row`.
- `_per_call_to_dict` (`render_json.py:162-196`) — flat projection of `PerCallRow`. Extended additively.
- `TraceFixtureBuilder.llm_event` (`tests/shared/trace_fixture_builder.py:11-45`) — already accepts `cache_creation_input_tokens`, `cache_read_input_tokens` as kwargs (defaults `0`). **No builder extension needed for fresh-call tests.**
- `TraceFixtureBuilder.cached_llm_event_with_call` (`tests/shared/trace_fixture_builder.py:57-108`) — already accepts `cache_source` (default `"memo"`), `cache_key`, `cache_age_sec`. **No builder extension needed for cached-replay tests.**
- `_make_event` test helper (`test_trace_report.py:59-74`) — minimal event builder accepting `**overrides`. New test class uses it directly.
- `_make_analysis` + `CacheAnalysis(**{**base.__dict__, ...})` pattern (`test_cache_analysis_renderers.py` around line 1918) — JSON-shape test recipe. Mirrored verbatim.

## Edge cases (covered by tests above)

| Case | Expected behavior | Test |
|---|---|---|
| LLM event with `cache_creation > 0`, no replay | Section renders, no heading tag | `test_renders_section_when_cache_creation_nonzero` |
| LLM event with `cache_read > 0`, no replay | Section renders, no heading tag | `test_renders_section_when_cache_read_nonzero` |
| LLM event with `cache_source="memo"` | Section renders WITH `(cached result reused from prior run)` tag | `test_cached_replay_heading_tag_appears` |
| LLM event with `cache_source="in_process"` | Same as above (presence-gate, not value-gate) | (covered by replay test; both values trigger the same path) |
| LLM event with all-zero caches, no replay, no chunks_skipped | Section suppressed | `test_omitted_when_no_cache_signal` |
| Non-LLM event (no `llm_call`) | Section suppressed | `test_omitted_when_no_llm_call` |
| Memo-replay with all-zero cache tokens | Section renders (replay tag is the signal) | (covered by `test_cached_replay_heading_tag_appears` — cache_creation=0, cache_read=8062) |
| `cache_chunks_skipped` non-empty, all-zero cache tokens | Section renders (skipped chunks is itself a signal) | `test_renders_when_chunks_skipped_present` |
| User-facing text leaks `"memo"` or `"in_process"` | NEVER. Pure presence gate. | `test_cached_replay_heading_tag_does_not_leak_pflow_vocabulary` |
| Section ordering: `Cached System → Cache telemetry → Prompt` | Lock | `test_section_appears_between_cached_system_and_prompt` |
| `thinking_tokens > 0` | Bullet renders in metadata, NOT cache telemetry section | `test_thinking_tokens_renders_in_metadata_when_nonzero` |
| `thinking_tokens == 0` | Bullet suppressed | `test_thinking_tokens_omitted_in_metadata_when_zero` |
| Batch item LLM event | Section renders inside `item-N.md` files (calls `_format_resolutions` from `trace_report.py:1064`) | (covered implicitly by `_format_resolutions` reuse; no new test needed) |
| JSON: trace populated | New keys carry int values | `test_render_json_includes_cache_creation_and_read_tokens` |
| JSON: greenfield (no trace) | New keys are `null` | `test_render_json_per_call_cache_tokens_null_on_greenfield` |
| `_build_per_call_row` end-to-end with trace | New PerCallRow fields populated from `trace_llm_call` | `test_per_call_row_carries_raw_cache_token_splits_from_trace` |

## Verification

### Pre-implementation grep checks (auto-format may have shifted lines)

```bash
grep -n "@dataclass" src/pflow/core/cache_analysis/analyze.py | head -5
# Confirm PerCallRow decorator (expected ~line 81)

grep -n "def _build_per_call_row\|def _per_call_to_dict\|def _format_cached_system\|def _format_resolutions\|def _format_node_metadata" \
    src/pflow/core/cache_analysis/analyze.py \
    src/pflow/core/cache_analysis/render_json.py \
    src/pflow/core/trace_report.py
# Confirm signatures still at expected lines

grep -n "cache_creation_input_tokens\|cache_read_input_tokens" src/pflow/core/trace_report.py
# Expect zero matches — confirms the new section is the only entry point
```

### Unit + integration

```bash
make test       # ~+12 new tests, no updates to existing tests
make check      # ruff + ruff-format + mypy + deptry green
```

Per-file expectations:
- `tests/test_core/test_cache_analysis_renderers.py` — +2 tests
- `tests/test_core/test_cache_analysis_analyze.py` — +1 test
- `tests/test_core/test_trace_report.py` — new `TestCacheTelemetrySection` class with ~10 tests

### End-to-end against real Stage 2 fixtures (free — no LLM cost)

```bash
# Fresh provider call (cache_source absent on creative-direction):
uv run pflow analyze-cache scratchpads/stage2-verification/song-creator/song-creator.pflow.md \
  --from-trace scratchpads/stage2-verification/song-creator/RUN-HAIKU-FINAL-trace.json \
  --format=json | jq '.per_call[0] | {node_path, cache_creation_input_tokens, cache_read_input_tokens, data_source}'
# Expect: cache_creation_input_tokens=0, cache_read_input_tokens=8062, data_source="trace"

# Cached-replay rerun (cache_source="memo" on all events):
uv run pflow analyze-cache scratchpads/stage2-verification/song-creator/song-creator.pflow.md \
  --from-trace scratchpads/stage2-verification/song-creator/RUN-HAIKU-RERUN-trace.json \
  --format=json | jq '.per_call[0] | {node_path, cache_creation_input_tokens, cache_read_input_tokens}'
# Expect: cache_creation_input_tokens=0, cache_read_input_tokens=8062
```

For `--report` rendering verification: easiest path is to construct a synthetic trace JSON via `TraceFixtureBuilder` in a one-off script, OR re-run an existing workflow with `--report`. Existing Stage 2 trace JSONs don't have a corresponding `--report` directory; reading from one would require a fresh run. Optional, not blocking.

Manual sanity check on the empirical traces (no LLM cost):

```bash
python3 -c "
import json
for label, path in [
    ('FRESH', 'scratchpads/stage2-verification/song-creator/RUN-HAIKU-FINAL-trace.json'),
    ('REPLAY', 'scratchpads/stage2-verification/song-creator/RUN-HAIKU-RERUN-trace.json'),
]:
    with open(path) as f: data = json.load(f)
    ev = data['nodes'][0]
    lc = ev.get('llm_call', {})
    print(f'{label} {ev[\"node_id\"]}:')
    for k in ('cache_creation_input_tokens', 'cache_read_input_tokens', 'cache_source', 'cache_key', 'cache_age_sec'):
        print(f'  {k} = {lc.get(k, \"<absent>\")}')"
```

Expected output confirms the gate logic:
- FRESH `creative-direction`: `cache_creation=0`, `cache_read=8062`, `cache_source=<absent>` → renders `## Cache telemetry` (no tag)
- REPLAY `creative-direction`: `cache_creation=0`, `cache_read=8062`, `cache_source="memo"`, `cache_age_sec=559.99` → renders `## Cache telemetry (cached result reused from prior run)` with `- Result age: 560s`

### Mutation contracts

Each new test must fail with a clear assertion when the production guard is reverted. Specific reverts to attempt before declaring done:
- Drop the `is_cached_replay` gate from `_format_cache_telemetry` heading → `test_cached_replay_heading_tag_appears` fails (heading doesn't carry tag).
- Replace `is_cached_replay` boolean with literal `cache_source` value rendering → `test_cached_replay_heading_tag_does_not_leak_pflow_vocabulary` fails ("memo" appears in output).
- Drop the `cache_source` presence check from the gate (always render) → `test_omitted_when_no_cache_signal` fails (section appears with all zeros).
- Move thinking bullet into `_format_cache_telemetry` instead of `_format_node_metadata` → `test_thinking_tokens_renders_in_metadata_when_nonzero` fails (bullet not in metadata) AND `test_omitted_when_no_cache_signal` fails (section now renders for thinking-only events).
- Swap `_format_cache_telemetry` and `_format_cached_system` call order → `test_section_appears_between_cached_system_and_prompt` fails.
- Revert `cache_creation_input_tokens` extraction to `None` in `_build_per_call_row` → `test_per_call_row_carries_raw_cache_token_splits_from_trace` fails.
- Drop the new keys from `_per_call_to_dict` → `test_render_json_includes_cache_creation_and_read_tokens` fails.

## Out of scope (not in this PR)

1. **`cache_chunks_skipped` re-rendering inside `## Cache telemetry`** — already shown in `## Cached System`. No duplication. The chunks_skipped non-empty IS a section gate, but the chunks list itself stays in the existing section.
2. **`thinking_budget` rendering** — only `thinking_tokens` (the actual count). Budget is a request parameter; tokens is the observation. The latter is the agent-relevant signal.
3. **`cost_data_source` integration with new fields** — `cache_creation_input_tokens` is null when `data_source != "trace"`. `data_source` is the existing tier discriminator; consumers reading the new fields cross-reference it. No new tier label.
4. **MCP server `analyze_cache` tool docstring update** — verification confirmed the docstring documents only `per_call[].data_source`, not the full field list. New fields are additive and don't require docstring update.
5. **`cache_analysis/CLAUDE.md` update** — verification confirmed the doc doesn't enumerate per_call fields. No update required (could be added separately if a per_call shape table is desired).
6. **OpenAI provider verification** — the new fields render correctly for OpenAI fold-style providers (cache_creation always 0; cache_read carries `cached_tokens` from `prompt_tokens_details`). Tests use Anthropic-shaped fixtures; OpenAI shape is structurally identical.
