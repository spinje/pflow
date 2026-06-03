# Plan: Shrink the trace — per-run interning + canonical LLM prompt/system (issue #382)

> **Audience:** an AI agent implementing this in isolation. Everything needed is here. Trust
> code over this doc — re-verify any `file:line` before editing (line numbers drift).
> **Branch/worktree:** `feat/issue-382-shrink-trace-interning`.
> **Do NOT** `git add/commit/push` unless the user explicitly asks (hard repo rule).
> **What "done" looks like:** §13 — the acceptance checklist, the measurable size target, and the
> explicit non-goals (where to stop). Read it before you start so you build toward the target.

---

## 1. Context — why this change

Real workflow traces (`~/.pflow/debug/workflow-trace-*.json`) reach 100MB+. The bulk is
**duplicated content**, on two axes:

1. **Cross-event / cross-tier flow** — a node's generated content reappears, byte-identical, in
   every downstream node's inputs, prompts, and resolutions, across batch items and nested tiers.
2. **Within-event redundancy** — each LLM event stores the same resolved prompt in **3–4 fields**
   (`llm_prompt`, `node_output.prompt`, `template_resolutions.prompt.resolved`, and on the parent
   event `node_params.prompt`), and the same effective system in 2–3 fields.

The trace must stay a **searchable, plaintext, agent-greppable** debug artifact (Task 108: full
content, no truncation). So **compression/gzip is ruled out** — it makes the file opaque.

This change does three complementary things, all on the **current end-dumped JSON tree** (no
span/streaming redesign — that is deferred to Task 133):

- **(A) Per-run content interning** — at dump time, every large string leaf (≥ ~1 KB) becomes a
  content-addressed ref `{"$pflow_blob": "<hash>"}`, and the unique content is stored **once** in a
  `blobs: {hash: content}` map. Resolved back at load time. Kills the cross-event duplication
  losslessly and generically. **Disk-encoding only; in-memory is always plain content.**
- **(B) Canonical LLM prompt/system** ("honest event model") — for LLM events, the prompt lives in
  exactly **one** field (`llm_prompt`) and the effective system in **one** field (`llm_system`);
  the redundant copies are stripped at the single node-aware layer that already creates those
  fields. Removes the within-event repetition at the root (legibility + simpler typed-trace
  contract for the future Task 133 / #370 work).
- **(C) Cache-block prompt capture** — for a prewarm batch, each item's user prompt is captured as
  the cache-rendered **blocks** (`list[dict]`) the API actually received, instead of one flat
  string. Because the shared static-prefix block is byte-identical across all N items, interning
  collapses it to **one blob** (instead of N copies). System content already gets this for free
  (`llm_system` is already block-shaped when cache-rendered).

**Intended outcome:** dramatically smaller traces, an LLM event that is trivial to reason about
(one prompt field, one system field), and a single clean read/write seam — with zero loss of
searchable content and no consumer behavior change after resolution.

### Why these three together (the synergy)
(B) makes (C) clean: with **one** canonical prompt field, (C) is just "that field holds blocks when
prewarm built them, else the flat string" — base interning (A) dedupes whatever leaves remain. No
per-field special-casing. The degraded prewarm path (blocks not built) falls back to a flat string
— exactly the `system_blocks if system_blocks else system` rule already in the code.

---

## 2. The one rule (internalize this)

> **The LLM-event recording layer owns the prompt and system. They surface in exactly one
> canonical field each — `llm_prompt` / `llm_system`, each `str | list[dict]`. The redundant
> `node_output` and `template_resolutions` copies (and the dead `node_params.prompt`) are stripped
> at that same node-aware layer, AFTER promotion. Interning is a dumb, shape-agnostic leaf-walk
> that dedupes whatever leaves remain. One renderer handles `str`-or-blocks for both sections.**

Interning never knows about prompts, blocks, or caching. Canonicalization never touches the generic
template resolver. Each concern stays in one place.

---

## 3. Locked decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| Compression | **None** — plaintext + interning | Trace must stay searchable/greppable (load-bearing). |
| Ref sentinel | **`{"$pflow_blob": "<hash>"}`** | Unique sentinel (not the issue's literal `$blob`) eliminates the (tiny) risk that real user output shaped `{"$blob": ...}` gets misresolved. Correctness rests on byte-identical round-trip; user content is the one input tests can't enumerate. |
| Blob map placement | **Trailer** (`blobs` is the LAST top-level key) | Reader sees metadata + event tree first, blob bodies as an appendix. `json.dump` preserves insertion order. Streaming (Task 133) uses inline-first-occurrence — neither top nor trailer — so this is decided purely on today's readability. |
| Hash | **md5**, `usedforsecurity=False` + `# noqa: S324` | Content-addressing, not security. Matches the repo idiom (`runtime/cache.py:400`). |
| Empty blobs | **Always emit `"blobs": {}`** | One code path; `resolve_blobs` already tolerates absent for old traces. |
| Resolve factoring | **One `resolve_blobs(trace)`** with a generic recursive walk | Simplest to read (YAGNI). The walk is shape-agnostic, which is the load-bearing future-proofing. A `substitute_refs(obj, map)` split for the future jsonl reader is a 2-minute extraction *then*, not now — leave a one-line comment noting it. |
| Format bump | **`2.4.0 → 2.5.0`** | All 5 consumer gates use `format_version.startswith("2.")` → forward-compatible. NOT purely additive (it removes the redundant LLM copies), but there are **no external consumers** (no users yet) and all in-repo consumers are updated together; old traces still render. Changelog comment must say so explicitly. |
| `intern_blobs` purity | **Pure — rebuild, never mutate** | `save_to_file` sets `trace_data["nodes"] = self.events`, which **aliases the live in-memory event dicts**. Mutating would corrupt the live tree and break the "in-memory always plain" invariant. A generic walk that returns new dicts/lists satisfies this for free. |
| (C) scope | **Batch-only** | Prewarm is gated on batch (`batch_alias`/`unresolved_batch_prompt`), so `user_message_blocks` never exists off the batch path. The non-batch trace_hook path is **untouched**; the LLM adapter (`llm_client.py`) is **untouched**. |
| `_format_resolutions` | **Keep both branches; update only the `elif llm_prompt` body** | The `if "prompt" in resolutions` branch still serves non-LLM nodes that happen to have a templated param literally named `prompt` (we only strip for LLM events). No test deletion. Only the `elif event["llm_prompt"]` path needs the str-or-blocks renderer (a list there would otherwise `TypeError` on join). |
| LLM-node gate | **Reuse `_should_write_cache_metadata(node_type_name)`** (`instrumentation.py:289-305`, returns `node_type_name == "LLMNode"`) | The codebase's canonical, allowlist LLM-trace gate (already imported by both strip sites). Its name reads cache-specific, so **recommend introducing a clearly-named alias `is_llm_node_type(node_type_name)`** and having `_should_write_cache_metadata` delegate to it — pure legibility, behavior-identical (`== "LLMNode"`). Do NOT use the loose `"LLM" in node_type` substring check (report-layer heuristic) or `trace_loading._is_llm_node` (operates on IR dicts, wrong input). |
| Renderer | **Extract a shared str-or-blocks body helper** | `_format_cached_system` (`trace_report.py:1182-1187`) already renders `str` verbatim / `list[dict]` as fenced ` ```json `. Extract just that body (`append value if str, else fenced json.dumps(…, indent=2, default=str)`) into a helper; both `## Cached System` and the `## Prompt` `elif` call it after their own header. The cached-system "Skipped chunks" footer stays caller-specific. |
| Warmup item | **Leave as-is** | The warmup trace item (`batch_executor.py:762-772`) carries only the trivial `llm_prompt: "Reply with: OK"`; the real static prefix flows via `user_message_blocks` and is **not captured on the item**. So it contributes **zero** prefix copies — byte-neutral. Routing blocks there would need a return-shape change to `_execute_synthetic_warmup` (blocks are out of scope at the capture site); not worth it. |
| Strip `node_output.prompt` despite it being a "declared output" | **Yes, strip it (accept the narrow `--only` caveat)** | `shared["prompt"]` is documented (`llm.py:909`) as *"Rendered prompt actually sent to the model (populated for **tracing/audit**)"* — its declared purpose **is** the trace, now fulfilled by canonical `llm_prompt`. `post` still writes `shared["prompt"]` at runtime, so a live `${node.prompt}` reference still resolves; **only** `--only` snapshot **re-seeding** of `${node.prompt}` is affected (the trace no longer persists it). No workflow references `${node.prompt}` today (grepped src/tests/examples), and referencing a node's *sent prompt* downstream is an odd pattern. Reversible. **Document the caveat** in `runtime/CLAUDE.md` (Phase 5). *(Surfaced by review; this is the one judgment call — veto if you'd rather keep `node_output.prompt`, but note that keeping it on batch items would defeat (C)'s dedup.)* |

---

## 4. Module structure & files

### New module: `src/pflow/core/trace_io.py` (pure; stdlib only)
Home for the interning encoding + the single trace loader. Imports only `json`, `hashlib`,
`pathlib`, `typing`. Placed in `core/` so all three readers (one in `runtime/`, two in `core/`) can
import it with **no import cycle**. Verified: layering is strictly `runtime/ → core/` (core→runtime
edges are deliberately lazy; `trace_report.py:20` is the one eager exception). A stdlib-only `core/`
module is importable by `runtime/workflow_trace.save_to_file` (`runtime → core`, sanctioned) and by
the two `core/` readers (intra-core) with zero new cross-layer edges. No existing blob/loader utility
exists today (the `{"__type":"base64"}` binary convention is unrelated — do not reuse its sentinel).

Contents:
```python
INTERN_MIN_BYTES = 1024          # ~1 KB; measured-robust, not a sensitive knob. One constant.
BLOB_SENTINEL = "$pflow_blob"

def intern_blobs(trace: dict[str, Any]) -> dict[str, Any]:
    """Return a COPY of `trace` with large string leaves replaced by {BLOB_SENTINEL: hash},
    plus a trailing "blobs": {hash: content} map. Pure — does not mutate input.
    Skips reserved (`__`-prefixed) keys' VALUES (mirrors _sanitize_for_json)."""

def resolve_blobs(trace: dict[str, Any]) -> dict[str, Any]:
    """Inverse of intern_blobs. No-op if "blobs" absent (older/un-interned traces).
    Generic shape-agnostic walk. (Future jsonl reader: build the blob map from inline
    declarations instead of trace["blobs"], then reuse this substitution.)"""

def load_trace_file(path: Path) -> dict[str, Any]:
    """Read + parse + resolve. THE single disk-read seam (and the future jsonl migration point)."""
    return resolve_blobs(json.loads(path.read_text(encoding="utf-8")))
```

Walk rules (both functions):
- Recurse generically over `dict`/`list`; **never** hardcode `events`/`batch_items`/`sub_workflow_events`.
- **`intern_blobs` must allocate a NEW `dict`/`list` at every level** — never return an input
  sub-container even when no leaf in it was interned (a "no large leaf → return same sub-dict"
  short-circuit would alias input into output and silently break the purity invariant). Build the
  `blobs` accumulator **fresh inside `intern_blobs`** and thread it as an explicit argument —
  **never a mutable default** (`def _walk(o, blobs={})` is the classic process-wide leak; doubly bad
  here since traces are written from long-lived processes and test suites).
- Intern only `str` leaves whose `len(s.encode("utf-8")) >= INTERN_MIN_BYTES`. **`str`-only is
  load-bearing** — `resolve_blobs` substitutes the *same* `blobs[h]` object into N positions; that's
  safe only because strings are immutable. Add a comment at the leaf test: never extend interning to
  `dict`/`list` blobs without revisiting the shared-reference substitution.
- Defensively skip the VALUE under any `str` key starting with `__` (reserved keys — Task 156). (In
  practice `_sanitize_for_json` already removed `__`-keys per-field at record time, leaving only
  `__metrics__` with small numeric content — so this is belt-and-suspenders, not load-bearing.)
- In `resolve_blobs`, a node is a ref iff it is a dict whose only key is `BLOB_SENTINEL` with a `str`
  value; tolerate a missing hash by leaving the ref untouched. **Degrade gracefully on a malformed
  `blobs` map** — if `trace["blobs"]` is absent or not a dict, return the trace unchanged (no-op);
  never `KeyError`/`TypeError`.
- Import `trace_io` **eagerly at top-level** in `workflow_trace.py` (stdlib-only target → no cycle;
  don't defensively make it lazy).

### Files modified
- `src/pflow/core/trace_io.py` — **new** (above).
- `src/pflow/runtime/workflow_trace.py` — bump version; call `intern_blobs` in `save_to_file`;
  route `_iter_workflow_traces` through `load_trace_file`; canonicalize in `record_node_execution`.
- `src/pflow/core/prompt_cache_analysis/trace_loading.py` — route `_load_trace_explicit` (`:159`)
  through `load_trace_file`.
- `src/pflow/core/trace_report.py` — route `generate_report` (`:633`) through `load_trace_file`;
  extract a shared str-or-blocks renderer from `_format_cached_system` and use it for `## Prompt`.
- `src/pflow/runtime/engine/batch_executor.py` — canonicalize per-item in `_capture_item_trace`;
  capture `user_message_blocks` for (C).
- `src/pflow/nodes/llm/llm.py` — mirror `user_message_blocks` into `shared` in `LLMNode.post`
  (next to the existing `system_blocks` seam at `:1247-1249`).

---

## 5. Phase 1 — Interning core (pure, isolated, fully tested). PAUSE after this phase.

1. Create `src/pflow/core/trace_io.py` with `INTERN_MIN_BYTES`, `BLOB_SENTINEL`, `intern_blobs`,
   `resolve_blobs`, `load_trace_file` (§4). Use `hashlib.md5(s.encode("utf-8"),
   usedforsecurity=False).hexdigest()` with `# noqa: S324`.
2. Unit tests (`tests/test_core/test_trace_io.py`):
   - **Round-trip identity (core invariant):** `resolve_blobs(intern_blobs(t)) == t` for several
     dicts incl. nested `batch_items`, `batch_items[].events`, `sub_workflow_events`, blocks
     (`list[dict]` with `cache_control`), and `__`-reserved keys.
   - **Threshold:** `< INTERN_MIN_BYTES` stays inline; `>=` becomes a ref.
   - **Reserved-key protection:** a large value under a `__pflow_stats__` key is NOT interned.
   - **Dedup:** two identical large leaves ⇒ one `blobs` entry; both refs share the hash.
   - **Block leaf:** a `>=1 KB` block `text` is interned; sibling `cache_control` stays inline;
     round-trip restores byte-identical.
   - **Backward-compat:** `resolve_blobs` / `load_trace_file` is a no-op on a trace with no `blobs`.
   - **Trailer + searchability:** dumped file is valid JSON, `blobs` is the last key, unique content
     appears in plaintext exactly once.
   - **Purity:** `intern_blobs(t)` does not mutate `t`.

**STOP for review.** This is the load-bearing logic.

---

## 6. Phase 2 — Wire interning (write + read seams)

1. **Write:** in `WorkflowTraceCollector.save_to_file` (`workflow_trace.py:771`), wrap the dump:
   `json.dump(intern_blobs(trace_data), f, indent=2, default=str)` (currently `:850`). Interning
   runs AFTER `_sanitize_for_json` (already done per-field at record time), so it only sees clean
   `str` values. Bump `TRACE_FORMAT_VERSION` to `"2.5.0"` (`:23`) and update the changelog comment
   (`:21-22`): adds top-level `blobs` map + `{"$pflow_blob"}` refs; canonical `llm_prompt`/
   `llm_system`; removed redundant LLM prompt/system copies.
2. **Read:** route all three content readers through `load_trace_file`:
   - `workflow_trace.py:105` (`_iter_workflow_traces` — shared by `--only` seeding, the dry-run
     planner `--only` path via `execution/plan.py:509`, AND analyze-cache autoload; **highest-stakes**).
     **PRESERVE the existing `try/except (json.JSONDecodeError, OSError): continue` wrapper**
     (`workflow_trace.py:104-108`) around the `load_trace_file` call — autoload globs many candidates
     and one corrupt file must not abort iteration. (`load_trace_file` itself does a bare
     `json.loads`; the robustness lives at this call site + `resolve_blobs`'s graceful degradation.)
   - `prompt_cache_analysis/trace_loading.py:159` (`_load_trace_explicit`).
   - `trace_report.py:633` (`generate_report`).
   - **Leave alone:** `trace_report.py:175` (report-dir marker, not a trace), `report.py:41` &
     `trace_loading.py:327` (filename globs — no content read; `report.py:41` hands its path to
     `generate_report`).
3. Fix the stale comment at `workflow_trace.py:554-555` ("LLM node does NOT write prompt to shared")
   — it is false and misled prior research.
4. Tests:
   - **`--only` regression:** seed from an interned trace; assert `shared[node_id]` holds resolved
     content, not a `{"$pflow_blob"}` ref (guards live execution via `seed_snapshot_into_shared`).
   - **Dry-run planner `--only`:** also assert `--dry-run --only` against an interned trace seeds
     resolved content (same seam via `execution/plan.py:509` → `load_snapshot_or_raise`).
   - **Malformed-file resilience:** a corrupt trace file in the autoload glob is skipped, not fatal
     (guards the preserved `try/except`).
   - **Report + analyze-cache** on an interned trace render real content, not refs.
   - **Version-pin test:** update `tests/test_runtime/test_trace_format_2_2.py:27`
     (`assert TRACE_FORMAT_VERSION == "2.4.0"`) → `"2.5.0"`, rename the function.

---

## 7. Phase 3 — Canonical LLM prompt/system (B). PAUSE after this phase.

Strip the redundant copies for **LLM events only**, at the node-aware recording layer, **after** the
`llm_prompt`/`llm_system` promotion (which reads the LIVE store, so stripping the stored copies is
order-safe).

**Keys to strip (LLM events only), gated by `_should_write_cache_metadata(node_type)`:**

| Path | Insert strip after | Strip `prompt` from | Strip `system` from (keep `node_params.system`) |
|---|---|---|---|
| **Parent** `record_node_execution` (`workflow_trace.py`) | line **525** (`_add_llm_data` call), before append at **527** — `node_type` is param #2, in scope | `event["node_output"]`, `event["template_resolutions"]`, `event["node_params"]` (3 dicts) | `event["node_output"]`, `event["template_resolutions"]` (2 dicts) |
| **Batch item** `_capture_item_trace` (`batch_executor.py`) | line **866** (promotion loop), before sub-workflow block at **868** | `item_event["node_output"]`, `item_event["template_resolutions"]` (2 dicts; items have **no** `node_params`) | `item_event["node_output"]`, `item_event["template_resolutions"]` |

- Use `.pop(key, None)` everywhere (keys may be absent — static prompt, non-LLM-shaped output).
- **Rationale for the asymmetry:** `node_params.prompt` has **zero readers** (dead — `_format_llm_params`
  skips it via its `_skip` set at `trace_report.py:927`), so it's stripped. `node_params.system` IS
  rendered as the `## System` config line (`trace_report.py:933-937`, the raw configured system,
  distinct from the effective `llm_system`), so it's **kept**.
- **⚠️ ALIASING HAZARD (batch path):** `item_event["template_resolutions"] = last_resolutions` at
  `batch_executor.py:851-852` is a **reference, not a copy** (unlike the parent path, which copies via
  `_sanitize_for_json`). Popping keys would mutate the caller's shared `last_resolutions`. **Copy
  before stripping**, e.g. `item_event["template_resolutions"] = {k: v for k, v in last_resolutions.items()
  if k not in ("prompt", "system")}`. This filter is **allowlist-by-exclusion** (drop ONLY
  `prompt`/`system`) — it MUST preserve every other key, notably `template_resolutions["workflow"]["resolved"]`
  (read for sub-workflow/batch attribution at `trace_tree.py:629-652`). Don't broaden the filter.
- **⚠️ THREADING:** `_capture_item_trace` does NOT currently receive `node_type`. Add a
  `node_type_name: str` param and pass `config.node_type_name` from the 3 call sites
  (`batch_executor.py:363,377,404`, all have `config` in scope); gate the strip on it.
- **Gate placement:** node-type-aware at these two sites only — **never** a magic-string
  `key == "prompt"` filter in the generic resolver (`template_resolution.py:461-464`), which would
  wrongly hit a shell/code node with a param legitimately named `prompt`.

**Order-safety (verified):** in both paths the `llm_prompt`/`llm_system` promotion reads the LIVE
store (parent: `self.llm_prompts`/`self.llm_systems` + the `node_output` arg from
`instrumentation.py:544`; batch: local `node_output = item_shared.get(node_id)` at `:846`), NOT the
stored `event` copies. Stripping the stored copies AFTER promotion never breaks promotion.

**Consumers (verified safe):**
- `## Prompt` — `_format_resolutions` (`trace_report.py:1258-1262`): LLM events now hit the
  `elif event.get("llm_prompt")` branch (their `template_resolutions.prompt` is gone). **Keep** the
  `if "prompt" in resolutions` branch (serves non-LLM nodes with a literal `prompt` param — robust,
  no test deletion). The `elif` body must use the str-or-blocks helper (Phase 4) since `llm_prompt`
  can become a list (today it appends `event["llm_prompt"]` raw → would `TypeError` on join).
- `## Cached System` — `_format_cached_system` reads `event.get("llm_system")` (`trace_report.py:1176`),
  **not** the stripped `node_output.system`/`template_resolutions.system`. So system stripping does
  not blank this section. ✅ (This was the highest-risk spot; confirmed clear.)
- `## System` config line — reads `node_params["system"]` (kept). ✅
- **Minor fidelity change to note:** for a *templated* `system` param (e.g. `- system: ...${persona}...`),
  the raw `${...}` template currently appears under `## Resolved Parameters` (the `_format_resolutions`
  catch-all). After stripping `template_resolutions.system`, that raw template no longer shows there
  (the *effective* system still renders via `## Cached System`). Acceptable, intentional. Confirm no
  test asserts a templated `system` under `## Resolved Parameters`. (Prompt has no such loss — its raw
  template was never surfaced; only `.resolved` was rendered.)

Tests:
- Engine-produced (mock adapter) LLM event — **this is the REAL strip coverage** (the existing
  `TestTraceFixtureBuilderShapeParity` only compares top-level key sets on a `node_output` that never
  had `prompt`/`system`, so it's a no-op there and does NOT prove the strip). Assert
  `node_output`/`template_resolutions`/`node_params` no longer carry `prompt`/`system` (except
  `node_params.system` kept); `llm_prompt`/`llm_system` present and correct.
- Report `## Prompt` renders from `llm_prompt` (covered by existing `test_llm_prompt_fallback`,
  `test_trace_report.py:763`); `## System` config line still renders from `node_params.system`.
- **Must still pass (regression guards):** the batch-seam test
  `test_trace_integration.py:1176-1211` (`test_each_batch_item_llm_captures_own_rendered_prompt` —
  asserts `llm_prompt`, the canonical field) and the system live-fallback test
  `test_workflow_trace.py:1870-1888`.
- Non-LLM node with a templated `prompt` param: its `template_resolutions.prompt` is NOT stripped;
  `## Prompt` still renders via the `if` branch.

**STOP for review.** This is the trace-shape change.

---

## 8. Phase 4 — Cache-block prompt capture (C)

For prewarm batches, capture the user prompt as the blocks the API received, so the shared prefix
dedupes under interning (A). Batch-only; non-batch + adapter untouched.

1. **Producer seam:** in `LLMNode.post` (`llm.py` ~`:1240-1249`), mirror the user blocks into shared,
   next to the existing system seam:
   ```python
   rendered_user_blocks = prep_res.get("user_message_blocks")   # list[dict] | None (None on degraded path)
   if isinstance(rendered_user_blocks, list):
       shared["user_message_blocks"] = rendered_user_blocks
   ```
   (Keep the existing `shared["prompt"] = rendered_prompt` flat write — transport for the
   degraded/non-prewarm path and the canonical fallback.)
2. **Promote in capture — EXPLICIT ORDERED SEQUENCE inside `_capture_item_trace`** (the existing loop
   at `:859-866` already sets `llm_prompt` from the flat `prompt` via its `("prompt","llm_prompt")`
   tuple — **that entry will clobber the blocks unless handled**). Do, in this order:
   1. **Remove `("prompt","llm_prompt")` from the `:859-866` promotion loop** (keep `("response","llm_response")`
      and `("system","llm_system")`). Make the blocks-or-flat decision the *single* writer of `llm_prompt`.
   2. Read the ORIGINAL local `node_output` (`:846`, NOT `item_event["node_output"]`):
      `blocks = node_output.get("user_message_blocks")`; set
      `item_event["llm_prompt"] = blocks if isinstance(blocks, list) else node_output.get("prompt")`
      (guard the flat path with the existing `isinstance(..., str)` check).
   3. `pop("user_message_blocks", None)` from the stored `item_event["node_output"]` (a shallow copy,
      so this is safe) so it isn't a 4th copy.
   4. Then the Phase-3 strip (copy-then-filter `template_resolutions`; `pop` `prompt`/`system` from
      `item_event["node_output"]`).
   - `llm_prompt` is now `str | list[dict]`, symmetric with `llm_system`.
   - **Aliasing note:** the promoted blocks list is the SAME object as the live per-item
     `node_output["user_message_blocks"]` list. Safe today (only read by sanitize/intern, both pure) —
     add a one-line comment that it must not be mutated in place downstream.
3. **Warmup item: no change** (locked decision §3). It carries only `"Reply with: OK"`, not the
   prefix, so it contributes zero prefix copies — byte-neutral. (Blocks aren't in scope at its
   capture site; routing them is a separable follow-up only if report parity is ever wanted.)
4. **Renderer:** extract the str-or-blocks body of `_format_cached_system`
   (`trace_report.py:1182-1187`) into a helper, e.g.:
   ```python
   def _append_str_or_blocks(value: str | list[Any], lines: list[str]) -> None:
       if isinstance(value, str):
           lines.append(value)
       else:
           lines.append("```json")
           lines.append(json.dumps(value, indent=2, default=str))
           lines.append("```")
   ```
   Call it from `_format_cached_system` (after its `## Cached System` header, before the
   "Skipped chunks" footer) and from the `## Prompt` `elif` (after the `"## Prompt", ""` header).
   For a flat `str` this is byte-identical to today's output; blocks render as fenced JSON. Keep the
   `if "prompt" in resolutions` branch's `str(resolved)` rendering as-is (non-LLM, always a string).

Tests:
- Prewarm batch (mock adapter, ≥2 items, a ≥1 KB shared static prefix): assert each item's
  `llm_prompt` is `list[dict]`; the static-prefix block `text` resolves to ONE shared blob across
  all N items; only the per-item suffix block differs. (The warmup item carries no prefix — §3 — so
  it's not part of this assertion.)
- **Degraded path** (prefix below min-cache-tokens / images / alignment fail → `user_message_blocks`
  is None): `llm_prompt` is the flat `str`; canonical single field intact.
- Report renders blocked `## Prompt` (fenced JSON) and `## Cached System` identically (shared
  renderer).
- **Per-item report FILE path** (distinct from the top-level event): `trace_report._build_batch_item_file`
  (`:712` → `_format_resolutions` at `:1491` → join at `:1494`) also renders `## Prompt` and would
  `TypeError` on a `list[dict]` without the shared helper. The single `_format_resolutions` fix covers
  both call sites, but **add an explicit test that renders a prewarm batch's per-item file** with a
  blocked `llm_prompt` — not just the top-level event.

---

## 9. Phase 5 — Fixtures, full suite, docs

- Run `python -m tests.fixtures.cache_analysis._generate`; diff committed fixtures
  (`tests/fixtures/cache_analysis/*.json`). They are already in the clean shape (no `prompt`/
  `system` in `node_output`, no `template_resolutions`), so expect **no change**. The drift guard is
  `test_trace_tree.py` `test_committed_cache_analysis_fixtures_match_generator_output`. Regenerate +
  commit ONLY if they actually change.
- Run `TestTraceFixtureBuilderShapeParity` (`tests/test_core/test_trace_tree.py`) — if the
  engine-produced `node_output` shape changed, confirm the builder
  (`tests/shared/trace_fixture_builder.py`) still agrees (it already emits the clean shape).
- `make test && make check` (ruff + mypy). Type everything (`dict[str, Any]`, etc.).
- **Task 159 baseline:** run `.taskmaster/tasks/task_159/baseline/verify.sh`, then **inspect and
  classify any drift** (do not assume clean): cases that read the *committed* old-version fixtures and
  compare *analyze/report output* should stay clean (interning is transparent after resolve;
  canonicalization is validated against the already-clean fixtures). BUT a case that *re-records a raw
  trace* and diffs raw bytes will legitimately drift on the `format_version` (`2.4.0→2.5.0`), the new
  `blobs` trailer, and the removed LLM `prompt`/`system` copies — that is **expected** drift; update
  that committed expected file deliberately. Only a change in *resolved output* (rendered content
  differs) is a regression → **STOP and investigate.** (Don't blanket-run `regenerate.sh`.)
- Awareness (no action required): stale hardcoded old-version strings in test helpers
  (`trace_fixture_builder.py:257` `"2.2.0"`, `test_only_snapshot.py:80,300`) still pass the
  `startswith("2.")` gate — leave them; they are not missed updates.
- Docs: update `src/pflow/runtime/CLAUDE.md` (WorkflowTraceCollector section) — document the 2.5.0
  on-disk shape (`blobs`/`$pflow_blob` trailer, canonical `llm_prompt`/`llm_system`, `load_trace_file`
  read seam), the invariant **blobs exist only on disk; in-memory is always plain content**, and the
  **`--only` caveat**: LLM `prompt`/`system` are no longer persisted in `node_output`, so an `--only`
  snapshot can't re-seed `${node.prompt}`/`${node.system}` (canonical in `llm_prompt`/`llm_system`;
  live runs are unaffected since `post` still writes `shared["prompt"]`).

---

## 10. Edge cases (handle explicitly)

- **User content shaped like a ref:** mitigated by the unique `$pflow_blob` sentinel; `resolve_blobs`
  tolerates a missing hash (leaves the ref) rather than crashing.
- **Blocks with `cache_control`:** only the `>=1 KB` `text` leaf is interned; marker dicts stay
  inline; round-trip restores exactly.
- **Shared prefix < 1 KB:** not interned (stays inline) — fine, it's small; threshold is uniform.
- **Non-templated LLM prompt:** no `template_resolutions.prompt` to strip; `node_output.prompt`
  stripped; `llm_prompt` sourced from the trace_hook.
- **Non-LLM node with a literal `prompt` param:** NOT stripped (gate is LLM-node-type); renders via
  the `if "prompt" in resolutions` branch. (Robust > clean-but-fragile.)
- **Degraded prewarm (no blocks built):** `llm_prompt` is a flat `str`; the canonical single field
  still holds; nothing special-cased.
- **Strip ordering:** always strip the stored copies AFTER the `llm_prompt`/`llm_system` promotion
  (which reads the live store). Never reorder.
- **Batch `template_resolutions` aliasing:** `item_event["template_resolutions"]` is a *reference* to
  the caller's `last_resolutions` (`batch_executor.py:851-852`), not a copy. Copy-then-strip (build a
  new filtered dict); never `pop` in place, or you mutate a shared object.
- **Old traces (2.2.0–2.4.0):** `resolve_blobs` is a no-op (no `blobs` key); they still contain the
  redundant fields and still render — readers prefer `llm_prompt`/`template_resolutions` which are
  present in old traces too.
- **Transient memory at dump:** `intern_blobs` builds a copy, so peak memory briefly holds the live
  tree + interned tree + blobs map. Acceptable — this is a disk fix at end-of-run; peak memory is
  explicitly out of scope (no observed OOM).

---

## 11. Verification status (all specifics pinned)

Every implementation specific above was verified against current branch code via
`pflow-codebase-searcher` passes. Resolved: LLM-node gate (`_should_write_cache_metadata` ==
`"LLMNode"`); exact strip insertion lines (parent after `workflow_trace.py:525`; batch after
`batch_executor.py:866`); `node_params.prompt` dead / `node_params.system` rendered;
`core/trace_io.py` cycle-free (layering is `runtime → core`); `_format_cached_system` body to extract
(`trace_report.py:1182-1187`) and that it sources system from `event["llm_system"]`; warmup item
carries no prefix (no change). Two hazards captured in Phase 3 (batch `template_resolutions`
aliasing; threading `node_type` into `_capture_item_trace`).

The few items the implementer should still confirm hands-on (cheap, non-blocking): the exact
engine-produced non-batch `node_output` keys (a live run dump — the strip is idempotent either way);
and that the `## Prompt` flat-string output is byte-identical after the renderer swap (covered by a
report test + the Task 159 baseline).

**Plan review (4 specialist agents — structural integrity, consumer completeness, feature
interactions, concurrency safety):** no critical design errors. Consumer/read-path enumeration
confirmed COMPLETE (exactly 3 disk content readers; only `trace_report.py` reads the stripped fields;
all bypass paths — sub-workflow child collectors, warmup item, fixture builders — handled). Both
flagged hazards (batch `template_resolutions` aliasing; `intern_blobs` purity vs `self.events`
aliasing) confirmed real with correct mitigations. All review findings have been folded into the
phases above (the promotion-loop clobber ordering in Phase 4, the `try/except` preservation +
`resolve_blobs` graceful degradation in Phase 2/§4, the no-mutable-default / new-container-per-level
/ str-only walk rules in §4, the per-item report-file test in Phase 4, the baseline drift
reclassification in Phase 5, the templated-`system` fidelity note in Phase 3).

---

## 12. Verification (end-to-end)

- `uv run pytest tests/test_core/test_trace_io.py` — interning unit tests (Phase 1).
- `uv run pytest tests/test_runtime/test_trace_format_2_2.py tests/test_runtime/test_trace_integration.py
  tests/test_core/test_trace_report.py tests/test_core/test_trace_tree.py` — version, batch seam,
  report rendering, fixture drift.
- **Manual e2e:** run a small LLM workflow with a large prompt through the CLI
  (`uv run pflow <wf>.pflow.md`), then inspect the on-disk trace in `~/.pflow/debug/`:
  - `jq 'keys' <trace>` → `blobs` present (last key); `jq '.blobs | length' <trace>` → > 0.
  - An LLM event has `llm_prompt`/`llm_system` but NO `node_output.prompt`, no
    `template_resolutions.prompt`, no `node_params.prompt`.
  - `uv run pflow report <trace>` resolves and renders full content (no `$pflow_blob` refs visible).
  - For a prewarm batch (≥2 items, ≥1 KB shared prefix): `jq` the items' `llm_prompt` → `list[dict]`
    blocks; the prefix block `text` is one `{"$pflow_blob": h}` shared across items.
- `make test && make check`.
- `.taskmaster/tasks/task_159/baseline/verify.sh` → inspect/classify drift per Phase 5 (transparent on
  fixture-output cases; expected version/`blobs`/shape drift only on re-recorded raw-trace cases).

---

## 13. Definition of Done

The phases above are the *how*; this is *what "done" means* — check all of it before declaring the
issue resolved.

### Acceptance checklist (ALL must hold)
- [ ] `src/pflow/core/trace_io.py` exists; `intern_blobs` / `resolve_blobs` / `load_trace_file` are
      pure and unit-tested; **round-trip identity** (`resolve_blobs(intern_blobs(t)) == t`) holds for
      nested `batch_items` / `sub_workflow_events`, `list[dict]` blocks with `cache_control`, and
      `__`-reserved keys.
- [ ] `TRACE_FORMAT_VERSION == "2.5.0"`; a freshly written trace has a top-level `blobs` **trailer**
      and large string leaves encoded as `{"$pflow_blob": "<hash>"}`.
- [ ] All **three** disk content readers go through `load_trace_file`; **no consumer ever sees a raw
      `$pflow_blob` ref** — `--report`, `analyze-cache`, and `--only` seeding all render/seed fully
      resolved content. A corrupt trace in the autoload glob is skipped, not fatal.
- [ ] LLM events are **canonical**: exactly one prompt field (`llm_prompt`) and one effective-system
      field (`llm_system`); `node_output` / `template_resolutions` carry **no** `prompt`/`system`,
      and there is **no** `node_params.prompt`; `node_params.system` is **kept**.
- [ ] Prewarm-batch items capture `llm_prompt` as `list[dict]` blocks; the shared static-prefix block
      **dedupes to ONE blob** across all N items; the degraded path falls back to a flat `str` with
      the canonical single field intact.
- [ ] `## Prompt` (top-level **and** per-item report file) and `## Cached System` render
      `str`-or-blocks correctly via the shared helper.
- [ ] `make test && make check` green; the named regression guards still pass
      (`test_each_batch_item_llm_captures_own_rendered_prompt`, the system live-fallback test,
      `test_llm_prompt_fallback`); Task 159 baseline drift is **classified** (no resolved-output
      regression — only expected version/`blobs`/shape drift on re-recorded cases).
- [ ] `runtime/CLAUDE.md` documents the 2.5.0 on-disk shape, the `load_trace_file` seam, the
      "blobs exist only on disk; in-memory is always plain" invariant, and the `--only` caveat.

### Measurable success (the point of the issue — confirm, don't assume)
- [ ] **Interning (A) shrinks a real trace, losslessly.** Concrete repeatable check: run
      `intern_blobs` over the committed `.taskmaster/tasks/task_159/baseline/_shared/fixtures/`
      `live-gemini-lyrics-generator.trace.json` (9.4 MB, *already* hand-cleaned). Expect **≈40% /
      ≈3 MB** removed (exact-duplicate large-leaf bytes) and `resolve_blobs(...)` **byte-identical**
      to the original. A raw, *uncleaned* production trace shrinks substantially more (canonicalization
      + interning subsume the hand-minimizer's lossy dedup).
- [ ] **Canonicalization (B) + blocks (C) reduce within-event/per-batch duplication on a fresh run.**
      Record a small prewarm-batch LLM workflow; confirm each item's prompt appears **once**
      (as `llm_prompt`), and the shared prefix is a single shared blob — not N inline copies.
- [ ] **Searchability preserved.** Every unique large string still appears in plaintext **exactly
      once** in the file (greppable); the hash is a unique join key (`grep <hash>` finds the
      definition + every use; `jq '.blobs[h]'` returns the content).

### Explicit non-goals (where to STOP — do not scope-creep)
- **Peak / transient memory** — interning at dump-time does not (and is not meant to) reduce it;
  theorized, not observed. Out of scope.
- **Streaming / jsonl span-model event log** — Task 133 D1/D2/D3, deferred. Keep the walk generic so
  the future migration is small, but build none of it now.
- **Global cross-run blob store + GC** — far-future, gated on *observed* cross-run dedup.
- **Sub-leaf / content-defined chunking** beyond the existing cache-block boundaries — would break
  searchability; not in scope. (C) only captures blocks the API *already* produced.
- **Retiring the task_159 hand-minimizer** — separate; do not regress the baseline oracle.
- **The LLM adapter (`llm_client.py`) and the non-batch trace_hook capture path** — untouched.
