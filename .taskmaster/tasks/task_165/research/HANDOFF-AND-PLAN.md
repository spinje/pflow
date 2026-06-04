# Issue #382 — Shrink the trace (per-run content interning): Handoff + Plan

> **Status:** Research complete and cross-verified. Approach decided. No code written yet.
> **Branch / worktree:** `feat/issue-382-shrink-trace-interning` at
> `/Users/andfal/projects/pflow-feat-issue-382-shrink-trace-interning`
> **Repo:** `spinje/pflow`. GitHub issue: **#382**.
> **Author of this handoff:** prior research agent. Everything below is tagged with a trust
> level. Trust **code over docs** (this codebase's manifesto) — re-verify anything marked
> `[ASSUMED]` or `[STALE-RISK]` before leaning on it.

---

## 0. TL;DR for the impatient

- **What we're building:** per-run **content interning** for the workflow trace. At dump time,
  every large string leaf (≥ ~1 KB) is replaced by `{"$blob": "<hash>"}` and stored once in a
  top-of-file `blobs: {hash: content}` map. At load time it's resolved back. Net effect: the
  dominant duplication (the same generated content re-inlined across hundreds of events / nesting
  tiers) collapses to one copy per unique blob.
- **Format bump:** `2.4.0 → 2.5.0` (additive; the `format_version.startswith("2.")` consumer gate
  is preserved).
- **LOCKED DECISIONS (from the user):**
  1. **NO gzip / NO compression.** The trace must stay **searchable** (plaintext, greppable,
     `jq`-able, agent-readable). This is the load-bearing requirement that picks interning over
     compression.
  2. **Interning-only. Do NOT do the "Change A" field surgery** (dropping `node_params.prompt` /
     `node_output.prompt`). Reasons in §4. Interning subsumes the within-event dedup anyway.
  3. **Design interning as a pure on-disk encoding detail, encapsulated at the I/O boundary**
     (one intern step on write, one resolve step on read). No consumer changes, no `TraceTree`
     changes. See §6.
- **Threshold (~1 KB) is NOT a sensitive knob** — measured (§2). Don't agonize over it.

---

## 1. How we got here / what the user asked

- The session began from the GitHub-issue worktree assignment for #382. There is **no
  `/start-work` skill** in this harness, so the issue was fetched via `gh issue view 382`.
- The user directed: read `task_133` docs personally, then fan out searcher subagents to verify
  **every** assumption, plus one agent to mine prior task reviews (flagged possibly stale).
- **Subagent caveat:** `pflow-codebase-searcher` (the agent type CLAUDE.md mandates) is **NOT
  registered** in this harness. Available agent types: `claude, claude-code-guide, Explore,
  general-purpose, Plan, statusline-setup`. CLAUDE.md forbids `Explore`, so research was done with
  `general-purpose` agents (same read/search tooling, keeps file dumps out of context). **If you
  spawn more searchers, do the same.**
- 6 searcher agents ran; all findings below are their cross-checked output plus direct reads.
- The user's quality bar (quoted): *"prioritize simplicity of the FINAL code, not how easy it is
  to get there… the right solution that the top 10% of codebases similar to this one would
  implement… simple code optimized for AI agents to understand and add features to."* Do not
  overengineer; do not sprinkle special cases.

---

## 2. The REAL problem, measured (supersedes the stale 53MB→12MB prose)

The famous "53MB → 12MB" L-8 number from `task_159/baseline/BASELINE-AUDIT.md` is **prose only —
not reproducible** (no committed raw trace, no committed trim script). Treat it as directional.

But we found a real artifact + a real precedent and measured directly:

- **Committed baseline trace:** `.taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json`
  = **9.44 MB**, `format_version 2.2.0`, 15 top-level events (real lyrics-generator: 25 LLM nodes,
  3-level nested, ~80–180 LLM calls).
- **This file is already aggressively de-duplicated.** It was produced by
  `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/minimize-trace-fixture.py`
  (135 lines), which (a) writes **compact** JSON (`separators=(",",":")`) and (b) hand-drops
  `llm_response`, `prompt`, `llm_system`, `template_resolutions.prompt/system`,
  `node_params.inputs/system`, `node_output.system`, **and a hardcoded list of ~60
  workflow-specific string keys** (`draft_lyrics`, `chorus_text`, `analysis_emotional`, …). The
  raw production trace was therefore **much larger than 9.4 MB** (all that content, plus indent=2
  pretty-print whitespace).

**Measured exact-duplicate string-leaf bytes in the already-cleaned 9.4 MB file** (script: walk all
string *values*, group ≥ threshold by md5, `dup = total − unique`):

| threshold | big leaves | total | unique blobs | unique bytes | **duplicate (interning removes)** |
|---|---|---|---|---|---|
| 256 B | 907 | 8.02 MB | 440 | 4.82 MB | **3.20 MB (40%)** |
| 1 KB  | 730 | 7.91 MB | 383 | 4.78 MB | **3.13 MB (40%)** |
| 2 KB  | 587 | 7.72 MB | 352 | 4.74 MB | **2.98 MB (39%)** |

Takeaways:
1. **Threshold barely matters** (256 B vs 2 KB ⇒ 3.20 vs 2.98 MB). Duplication is in *large*
   leaves. ~1 KB is fine; don't tune it speculatively.
2. **The dominant axis is cross-event / cross-tier content flow, not the within-event 4× prompt.**
   A node produces content → it appears in that node's `node_output` → then in every downstream
   node's `node_params.inputs` and `template_resolutions.inputs.resolved` → then inside their
   `llm_prompt` → then repeated across batch items and sub-workflow tiers. Same bytes, many homes.
3. **The `minimize-trace-fixture.py` script IS the argument for interning.** A human had to
   maintain ~60 hardcoded domain key names to dedupe ONE workflow's trace, lossily. Content-
   addressed interning does this generically and losslessly. (After #382 ships, that minimizer
   could in principle be retired / replaced — see §10.)

> **Re-measurement status:** the user said "remeasure if you need to." The 9.4 MB measurement
> above is on the *cleaned* fixture; interning on a *raw* trace will save substantially more
> (the cleaning already removed the worst offenders). If you want a raw-trace number, record one
> (needs `GEMINI_API_KEY`; ~$1–3, ~10–30 min — see the gemini case README) or build a synthetic
> large trace. **Not a blocker** — the win and the threshold are already well-characterized.

---

## 3. Verified findings (verdict table)

All `file:line` are in `src/pflow/` unless noted. Verified against current code on this branch.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Prompt materialized 4× per LLM event | **CONFIRMED (empirical run)** | `llm_prompt`, `node_params.prompt`, `node_output.prompt`, `template_resolutions.prompt.resolved` all = resolved prompt |
| 2 | `node_params.prompt` is dead (no readers) | **CONFIRMED** | Incidental key in the *generic* `node.params` dict (`workflow_trace.py:512`); the one LLM-params reader skips `prompt` (`trace_report.py:927`) |
| 3 | `node_output.prompt` is dead | **REFUTED — it is LOAD-BEARING** | Written by `LLMNode.post` at `nodes/llm/llm.py:1240-1242`; consumed as the parallel-batch capture seam (`engine/batch_executor.py:861`) and as the `llm_prompt` fallback (`workflow_trace.py:556-558`). The comment at `workflow_trace.py:554-555` ("LLM node does NOT write prompt to shared") is **STALE/WRONG**. |
| 4 | Only `template_resolutions.prompt.resolved` + `llm_prompt` are read | **CONFIRMED** | `## Prompt` prefers `resolutions["prompt"]["resolved"]`, falls back to `llm_prompt` (`trace_report.py:1258-1262`) |
| 5 | All consumers funnel through `TraceTree` | **PARTIAL** | 6 analyzer sites use `TraceTree.from_dict`; `trace_report.py` **bypasses** TraceTree and hand-walks the raw dict for all content |
| 6 | `$blob` resolution belongs in `TraceTree` | **INSUFFICIENT alone** | 3 sites read raw `node_output` outside TraceTree — incl. **live `--only` seeding**. ⇒ resolve at the **disk-load boundary** instead (§6) |
| 7 | Trace dumped uncompressed + pretty-printed | **CONFIRMED** | `json.dump(trace_data, f, indent=2, default=str)` — `workflow_trace.py:850` |
| 8 | `_sanitize_for_json` only filters `__`-keys + bytes; no truncation | **CONFIRMED** | `workflow_trace.py:614-641`; keeps `__metrics__` |
| 9 | 4 `startswith("2.")` gate sites | **REFUTED — there are 5** | issue missed `trace_report.py:639-640`. None break on 2.5.0 |
| 10 | 4 committed fixtures + builder | **CONFIRMED, but on 2.2.0** | `tests/fixtures/cache_analysis/*.json`; builder `tests/shared/trace_fixture_builder.py` hardcodes `2.2.0` |
| 11 | L-8 53MB→12MB | **UNVERIFIED / not reproducible** | prose only; see §2 |
| 12 | `TRACE_FORMAT_VERSION = "2.4.0"` | **CONFIRMED** | `workflow_trace.py:23` |
| 13 | Reusable hash utility exists | **CONFIRMED** | `cache.py:400` md5 + `_deterministic_json` (`cache.py:79`); `workflow_trace.py` already imports `hashlib` |

---

## 4. Why interning-only (drop the "Change A" field surgery)

The issue's Part A ("honest event model": drop `node_params.prompt` + `node_output.prompt`) should
**not** be implemented as field surgery, because:

1. **One of the two fields is load-bearing** (finding #3). Removing `node_output.prompt` breaks
   per-item parallel-batch prompt capture.
2. **Interning already removes the disk cost** — both fields become ~30-byte `{"$blob": …}` refs
   pointing at the single shared blob. The duplication is gone without touching any field.
3. **Change A's only *independent* benefit is peak memory**, which is a **theorized** problem (no
   observed OOM; the observed problem is 100 MB *files*). The manifesto says solve observed
   problems. And interning-at-dump wouldn't fix peak memory anyway (the duplicate in-RAM copies
   live until the dump regardless) — only a producer refactor would, which is the most invasive
   path and out of scope.
4. **Final-code simplicity (the user's priority):** field surgery adds *permanent* complexity
   (node-type-gated key scrubbing of generic dicts, a re-routed batch seam, shape-parity test
   churn). Interning is one uniform mechanism. Strictly simpler final code.

> If peak memory ever becomes a *measured* problem, address it then as a separate change.

### Alternatives considered and rejected
- **gzip / compression** — simplest code, biggest ratio (~10–20×), but makes the file **opaque**.
  **Rejected by the user**: the trace must stay **searchable**. (Task 108 contract: agents read
  full content.) This is the decisive constraint.
- **Compact separators only** (`separators=(",",":")`) — trivial, but (a) insufficient (doesn't
  touch content duplication, the dominant axis) and (b) makes the file *less* readable (one giant
  line). Rejected.
- **Resolve inside `TraceTree` only** — insufficient (finding #6): the load-bearing `--only`
  seeder and the report renderer never go through `TraceTree`.

---

## 5. Constraints the implementation MUST respect

- **[VERIFIED] Task 108 — no truncation / full content is the point.** `workflow_trace.py:401`
  docstring + `# No truncation` comments at lines 560/571/576. Interning is *reference
  indirection*, not truncation: resolution must reconstitute **byte-identical** content. After a
  `resolve_blobs`, the dict must equal the pre-intern dict exactly. (Add a round-trip test.)
- **[VERIFIED] Task 156 — reserved dunder keys.** `__pflow_stats__` / `__pflow_warnings__` ride
  *inside* output blobs; `cache.py` collapses `__…__` keys for hashing; readers must be
  absent-tolerant. **Do NOT intern values under `__`-prefixed keys.** Mirror `_sanitize_for_json`'s
  existing `__`-special-casing. Intern only *content leaves*.
- **[VERIFIED] Searchability (user).** Output stays plaintext JSON. The `blobs` map is plaintext
  and greppable. Keep it human-navigable: blobs map at the **top** of the file (json.dump
  preserves insertion order), so a reader sees structure first and can resolve refs by scrolling.
- **[VERIFIED] Forward-compat gate.** All 5 consumer gates use `format_version.startswith("2.")`
  ⇒ a 2.5.0 bump is forward-compatible. Keep the additive contract; don't add an exact-version
  check anywhere.
- **Never intern non-content:** keys, `node_id`, `node_type`, `model`, `format_version`,
  timestamps, numeric/scalars. Only large *string* leaves (and only `str` — `_sanitize_for_json`
  has already removed bytes by the time we intern).

---

## 6. The chosen design — interning as an encapsulated on-disk encoding

**Principle:** `$blob` exists **only in the file on disk**. Everything in memory — during the run
and after a load — is plain content. Two small symmetric pure functions; nothing else in the
codebase knows blobs exist.

```
in-memory trace_data  --intern_blobs()-->  {blobs, ...refs...}  --json.dump-->  disk
disk  --json.load-->  {blobs, ...refs...}  --resolve_blobs()-->  plain trace_data  --> consumers
```

### Write side — ONE choke point (already exists)
- `WorkflowTraceCollector.save_to_file` (`workflow_trace.py:771`), immediately before the
  `json.dump` at **`workflow_trace.py:850`**.
- Sanitization already ran at record time (per-field), so by dump time `trace_data` is JSON-safe
  (no bytes, no `__trace_collector__`, etc.). Interning runs **after** sanitize, as the last
  transform before write — it only ever sees clean values.
- Sole production caller of `save_to_file`: `cli/commands/run.py:134` (`_save_trace_and_report`,
  trace-gated). In tests it's monkeypatched off by default (`tests/conftest.py:268-271`, opt in
  via the `trace_files` marker).

### Read side — ONE choke point (small refactor; net simplification)
Today **three** places each do their own `json.load` of a trace file:
- `workflow_trace.py:105` — `_iter_workflow_traces` (shared by BOTH `--only` snapshot seeding AND
  analyze-cache autoload). **This is the highest-stakes path: `seed_snapshot_into_shared`
  (`workflow_trace.py:384-387`) copies raw `node_output` into `shared[node_id]` for a live `--only`
  run — an unresolved `{"$blob":…}` would corrupt real execution.**
- `trace_loading.py:159` — `_load_trace_explicit` (analyze-cache `--from-trace`).
- `trace_report.py:633` — `generate_report` (`--report` / `pflow report`).

> Note: `trace_report.py:175` is a *report-dir marker* read (`_REPORT_MARKER_VERSION`), NOT a trace
> file. Leave it alone.

**Plan:** introduce a single loader and route all three through it:

```python
# new, e.g. in workflow_trace.py (or a small trace_io module)
def load_trace_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return resolve_blobs(data)        # no-op for pre-2.5.0 traces (no "blobs" key)
```

Because every disk read now returns fully-resolved plain dicts, **no consumer and `TraceTree`
need any change** — they keep reading `node_output` / `llm_prompt` exactly as today.
(Top-10% codebases have a single trace loader anyway; this is a cleanup independent of interning.)

### The two pure functions (~40–60 lines total)
```python
INTERN_MIN_BYTES = 1024  # ~1 KB; measured-robust (see §2). One module constant.

def intern_blobs(trace: dict) -> dict:
    """Return a copy of `trace` with large string leaves replaced by {"$blob": h},
    and a top-level "blobs": {h: content} map. Pure; does not mutate input."""
    blobs: dict[str, str] = {}
    def go(o):
        if isinstance(o, dict):
            return {k: (v if _is_reserved(k) else go(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [go(v) for v in o]
        if isinstance(o, str) and len(o.encode("utf-8")) >= INTERN_MIN_BYTES:
            h = hashlib.md5(o.encode("utf-8")).hexdigest()  # content address, not security
            blobs[h] = o
            return {"$blob": h}
        return o
    body = go(trace)              # trace has no "blobs" key yet
    return {"blobs": blobs, **body}

def resolve_blobs(trace: dict) -> dict:
    """Inverse of intern_blobs. No-op if "blobs" absent (older/un-interned traces)."""
    blobs = trace.get("blobs")
    if not isinstance(blobs, dict):
        return trace
    def go(o):
        if isinstance(o, dict):
            if set(o) == {"$blob"} and isinstance(o.get("$blob"), str):
                return blobs.get(o["$blob"], o)   # tolerate missing → leave ref (don't crash)
            return {k: go(v) for k, v in o.items()}
        if isinstance(o, list):
            return [go(v) for v in o]
        return o
    out = go({k: v for k, v in trace.items() if k != "blobs"})
    return out
```
- `_is_reserved(k)`: `isinstance(k, str) and k.startswith("__")` — mirrors `_sanitize_for_json`,
  protects Task-156 reserved keys. (Decide: also skip a tiny allowlist of structural keys? Not
  needed — those are short scalars below threshold anyway. Keep it simple.)
- **md5 is for content-addressing, not security.** Match the existing idiom; this repo annotates
  md5 with `# noqa: S324` / `usedforsecurity=False` (`cache.py:400`, `workflow_trace.py:54`). Add
  the same.
- **Collision risk:** md5 over trace blobs is fine (content-addressed; a collision needs two
  *different* large strings with the same md5 — not a practical concern for a debug artifact).
  If you want zero-doubt, use `sha256` and truncate to 16 hex — negligible cost. Pick one and note
  it.
- **Factor resolve as `substitute_refs(obj, blob_map)` + a thin `resolve_blobs(trace)` wrapper.**
  The substitution ("given hash→content, replace `{"$blob": h}`") is the durable, format-independent
  part; only *building the map* is format-specific (read `trace["blobs"]` now; accumulate inline
  declarations when streaming lands — see §13). This split makes the future jsonl reader a tiny add.
- **Keep the walk shape-agnostic** — recurse generically over any dict/list; do **not** hardcode
  `events`/`batch_items`/`sub_workflow_events` traversal. Interning is orthogonal to tree-vs-flat
  (Task 133), so a generic walk survives the future tree→jsonl shape change untouched (§13).
- These two functions are **exact inverses on the content** (round-trip identity, modulo the
  `blobs` key). That invariant is the core test (§8).

### Why not also touch `TraceTree.from_dict`?
Not needed if all disk reads go through `load_trace_file` (they return resolved dicts). Adding
resolution in `from_dict` too would be redundant double-work. **Keep it in ONE place (the loader).**
The in-memory `TraceTree(events=…)` constructions at `workflow_trace.py:601,765` and
`trace_report.py:319,335` operate on never-interned data and are unaffected.

---

## 7. Break surface / what to touch (complete)

### Producer
- `workflow_trace.py:23` — bump `TRACE_FORMAT_VERSION` to `"2.5.0"`; update the changelog comment
  at lines 21–22 (additive: top-level `blobs` map + `{"$blob"}` leaf refs).
- `workflow_trace.py:850` (`save_to_file`) — call `intern_blobs(trace_data)` before `json.dump`.
- Add `intern_blobs` / `resolve_blobs` / `load_trace_file` (this module, or a new small
  `trace_io.py` — prefer same module to avoid a new import surface unless it gets crowded).

### Read sites → route through `load_trace_file`
- `workflow_trace.py:105` (`_iter_workflow_traces`) — **critical** (`--only` + analyze-cache).
- `trace_loading.py:159` (`_load_trace_explicit`).
- `trace_report.py:633` (`generate_report`).

### Consumers — NO CHANGE (get resolved dicts for free). Confirm by test:
- All 6 `TraceTree.from_dict` analyzer sites in `prompt_cache_analysis/` (context.py,
  trace_loading.py, token_estimation.py, cost_estimation.py, stages/*).
- `trace_report.py` raw-dict content rendering (node_output/llm_*/template_resolutions/etc.).
- `seed_snapshot_into_shared` (`workflow_trace.py:384-387`) — fed by `_iter_workflow_traces`, so
  resolved upstream. **Add a regression test that an interned trace seeds correctly.**

### Format gates — VERIFY they still pass on 2.5.0 (all `startswith("2.")`, so they do):
`trace_report.py:639-640`, `workflow_trace.py:113`, `trace_loading.py:165-166`,
`stages/discrepancy/diagnose.py:37-38`, and the issue-missed 5th — all four named + the 5th. No
edits expected; just confirm none became exact-version checks.

### Fixtures (all `format_version 2.2.0`, generated)
- `tests/fixtures/cache_analysis/{parent-child-trace, parent-child-grandchild-trace,
  parent-child-memo-hit-trace, parent-child-erroring-trace}.json`.
- Generator: `python -m tests.fixtures.cache_analysis._generate` (see
  `tests/fixtures/cache_analysis/_generate.py`). **Decision:** these fixtures' leaves are small
  (below the 1 KB threshold) so interning likely produces an **empty `blobs: {}`** and unchanged
  events — meaning they may not need regen at all for *content*, only if you choose to add the
  `blobs` key. Verify: run `_generate`, diff. The drift-guard test
  `test_trace_tree.py:308` (`test_committed_cache_analysis_fixtures_match_generator_output`) will
  tell you. Regenerate + commit only if they actually change.

### Tests to update (ranked break-surface; see §8 for strategy)
- **Hard version pin:** `tests/test_runtime/test_trace_format_2_2.py:27`
  (`assert TRACE_FORMAT_VERSION == "2.4.0"`, fn `test_format_version_is_2_4_0`) → bump to
  `"2.5.0"` and rename. (Soft `== TRACE_FORMAT_VERSION` asserts track the constant; safe.)
- **Shape-parity / drift:** `tests/test_core/test_trace_tree.py` —
  `TestTraceFixtureBuilderShapeParity` (≈148/180/225/271) and
  `test_committed_cache_analysis_fixtures_match_generator_output` (≈308).
- **Literal content asserts** that would break **only if interning leaked into in-memory data**
  (it must NOT): `test_trace_integration.py` (`event.get("llm_prompt") == "<literal>"` at ~748,
  806, 1122–1123, 1211), `test_batch_prewarm.py:743`, `test_template_wrapper_resolve.py:305`.
  These read **in-memory** collector events (never interned) — so they should **still pass
  unchanged**. If any breaks, your interning leaked into the in-memory path → bug.
- High-volume field-touching files (for awareness; mostly unaffected if encapsulation holds):
  `test_trace_report.py` (224), `test_workflow_trace.py` (199), `test_trace_tree.py` (177),
  `test_cache_analysis_analyze.py` (122), `test_trace_integration.py` (109).

---

## 8. Test strategy (test-as-you-go; a task without tests is incomplete)

1. **Round-trip identity (the core invariant):** for several trace dicts (incl. nested
   `batch_items`, `batch_items[].events`, `sub_workflow_events`, and reserved `__`-keys),
   `resolve_blobs(intern_blobs(t))` deep-equals `t`. This is the load-bearing correctness test.
2. **Threshold behavior:** strings `< INTERN_MIN_BYTES` stay inline; `≥` become `{"$blob"}`.
3. **Reserved-key protection:** a large value under a `__pflow_stats__` / `__…__` key is NOT
   interned.
4. **Dedup:** two identical large leaves ⇒ one `blobs` entry; both refs share the hash.
5. **Searchability sanity:** the dumped file is valid JSON, `blobs` is top-level, and the unique
   content appears in plaintext (greppable) exactly once.
6. **Backward-compat:** `resolve_blobs` is a no-op on a 2.4.0/2.2.0 trace (no `blobs` key) —
   `load_trace_file` returns it unchanged.
7. **End-to-end (real producer, not just the builder):** run a small LLM workflow through
   `WorkflowRunner` (mock adapter) with a large prompt; assert the **on-disk** file has `blobs` +
   refs, and that `load_trace_file` round-trips to full content. (Fixtures don't match real
   producer shape — tests/CLAUDE.md pitfall #19 — so an end-to-end test is mandatory.)
8. **`--only` regression:** seed from an interned trace; assert `shared[node_id]` gets resolved
   content, not a `{"$blob"}` ref. (Guards the live-execution path.)
9. **`--report` + `analyze-cache --from-trace`** on an interned trace render real content, not
   literal refs.

### Baselines — necessary, not sufficient (the `verify.sh` no-regen oracle)
The Task 159 baseline suite (`.taskmaster/tasks/task_159/baseline/`, run via `./verify.sh`) is a
strong **complementary** oracle, but understand exactly what it does and doesn't cover for THIS
change:
- **What it proves (high value):** interning is meant to be *transparent after resolve*, so the
  correct outcome is **`verify.sh` passes CLEAN with NO regeneration.** Surfaces 03/10
  (`--from-trace` against the committed 9.4 MB fixture), 12 (lyrics-generator), and 15 (`--only`,
  `--report`, partial traces) render real-shaped data; byte-identical output without touching any
  `expected-*` is the strongest signal that interning is invisible to every consumer. **Do NOT run
  `regenerate.sh`** — that would mask a regression. Drift = something leaked; investigate.
- **What it does NOT cover:** the committed fixtures are **old-format (2.2.0), un-interned**. So
  the baselines exercise the **read / backward-compat** path (and confirm `resolve_blobs` is a
  correct no-op on un-interned traces) but **barely touch the new write/intern path**. Nothing in
  the committed suite verifies a freshly-written 2.5.0 trace is interned correctly and re-read
  properly.
- **Close the gap:** (a) the end-to-end real-producer test (§8.7) covers write→read round-trip in
  `make test`; (b) optionally **regenerate ONE live-recording fixture with the new code** so it
  actually contains `blobs`/`$blob`, and point a `--from-trace` baseline at it — that adds suite
  coverage for *reading an actually-interned trace*. (Regenerating that fixture needs a raw trace:
  re-record with `GEMINI_API_KEY` (~$1–3) or run `intern_blobs` over an existing raw trace.)

**Bottom line:** the full safety net is three layers — `make test`+`make check` (primary),
`verify.sh` clean-with-no-regen (transparency on real data), and one interned fixture (new-path
read coverage). Baselines alone are not enough.

Run `make test` and `make check` (ruff + mypy) before declaring done. Type everything
(`dict[str, Any]`, etc.); add `# noqa: S324` on md5.

---

## 9. Implementation plan (phased; pause for review after Phase 1)

**Phase 0 — (optional) ground the numbers.** Skip unless you want a raw-trace figure. The win and
threshold are already characterized (§2).

**Phase 1 — the interning core (pure, isolated, fully tested).**
- Add `intern_blobs`, `resolve_blobs`, `load_trace_file`, `INTERN_MIN_BYTES` (+ `_is_reserved`).
- Unit tests §8.1–§8.6. No wiring yet. **Pause here for review** — this is the load-bearing logic.

**Phase 2 — wire write side.**
- `save_to_file`: intern before `json.dump`. Bump `TRACE_FORMAT_VERSION` → `2.5.0` + changelog
  comment. Fix the version-pin test (`test_trace_format_2_2.py:27`).

**Phase 3 — wire read side.**
- Route `workflow_trace.py:105`, `trace_loading.py:159`, `trace_report.py:633` through
  `load_trace_file`. Add the `--only` seeding regression test (§8.8) and the report/analyze-cache
  resolution tests (§8.9).

**Phase 4 — fixtures + full suite.**
- Run `_generate`; diff committed fixtures; regenerate+commit only if changed. Run shape-parity /
  drift tests; update only what genuinely changed. `make test && make check`.

**Phase 5 — docs.**
- Update `src/pflow/runtime/CLAUDE.md` (WorkflowTraceCollector section) to document the 2.5.0
  `blobs`/`$blob` on-disk encoding and the `load_trace_file` read choke point. Note for future
  agents: "blobs exist only on disk; in-memory is always plain."
- Optionally update the issue/Task 133 cross-refs.

**Do NOT** `git add/commit/push` unless the user explicitly asks (CLAUDE.md hard rule).

---

## 10. Remaining unknowns / things to re-verify before/while building

- **[DECIDE] Hash function:** md5 (matches repo idiom) vs sha256-truncated (zero collision doubt).
  Recommend md5 for consistency; note the choice. `[low stakes]`
- **[VERIFY] Empty-blobs case:** confirm `intern_blobs` on a trace with no large leaves emits
  `"blobs": {}` and otherwise-identical events, and that this is acceptable in fixtures (or gate:
  omit the key when empty? — simpler to always emit it; pick one and test).
- **[VERIFY] `node_output.prompt` end-to-end after interning:** since we are NOT removing it,
  confirm the parallel-batch seam still works with interned values (it should — refs resolve
  before any consumer; the seam operates on in-memory pre-dump data anyway). Add to §8.7 if cheap.
- **[VERIFY] No other disk trace reader exists.** Agents found only the 3 read sites + filename/
  metadata-only globs (`report.py:41`, `trace_loading.py:327`) + MCP `trace_path` echo (no content
  read). Re-grep `json.load` / `workflow-trace` / `glob` / `~/.pflow/debug` before finalizing, in
  case the tree changed.
- **[STALE-RISK] The misleading comment** at `workflow_trace.py:554-555` ("LLM node does NOT write
  prompt to shared") is wrong (finding #3). Consider fixing it while you're in the file (it caused
  a real cross-agent contradiction during research).
- **[OUT OF SCOPE but adjacent] #357 asymmetry:** `_METADATA_KEY_SUFFIXES` (3 suffixes,
  `cache.py:30-34`) vs the config-hash filter (`instrumentation.py:164`, 1 suffix `_source_line`).
  Real, still open, in the same storage area — **do not fix here**, just don't be surprised by it.
- **[OPPORTUNITY] Retire `minimize-trace-fixture.py`?** Once interning ships, the committed
  baseline fixture could be regenerated from a raw trace via plain interning instead of the lossy
  60-key hand-list. **Out of scope for #382** (don't regress the task_159 baseline oracle), but
  worth a note to whoever owns that baseline.
- **Peak memory** is explicitly deferred (theorized, not observed). If it ever becomes real, it's
  a separate producer-side change.

---

## 11. Key file:line reference card

| Thing | Location |
|---|---|
| `TRACE_FORMAT_VERSION = "2.4.0"` → bump | `runtime/workflow_trace.py:23` (changelog 21–22) |
| `save_to_file` / `json.dump(...indent=2...)` → intern before | `runtime/workflow_trace.py:771` / `:850` |
| `_sanitize_for_json` (no truncation; `__`-key filter) | `runtime/workflow_trace.py:614-641` |
| `_iter_workflow_traces` `json.loads` (→ load_trace_file) | `runtime/workflow_trace.py:78` / `:105` |
| `seed_snapshot_into_shared` (raw node_output → live shared) | `runtime/workflow_trace.py:384-387` |
| stale wrong comment | `runtime/workflow_trace.py:554-555` |
| LLMNode writes `shared["prompt"]/["system"]` (batch seam) | `nodes/llm/llm.py:1240-1249` |
| batch per-item fallback to `node_output["prompt"]` | `engine/batch_executor.py:861` |
| `_load_trace_explicit` `json.loads` (→ load_trace_file) | `core/prompt_cache_analysis/trace_loading.py:159` (gate :165) |
| `generate_report` `json.load` (→ load_trace_file) | `core/trace_report.py:633` (gate :639-640) |
| `## Prompt` reader (resolved preferred, llm_prompt fallback) | `core/trace_report.py:1258-1262` |
| `TraceTree.from_dict` (analyzer choke point; NO change needed) | `core/trace_tree.py:89-102` |
| md5 + `_deterministic_json` idiom to reuse | `runtime/cache.py:400` / `:79` |
| version-pin test → bump+rename | `tests/test_runtime/test_trace_format_2_2.py:27` |
| shape-parity / drift tests | `tests/test_core/test_trace_tree.py` (~140, 308) |
| committed fixtures (2.2.0) + generator | `tests/fixtures/cache_analysis/*.json` + `_generate.py` |
| fixture builder (hardcodes 2.2.0) | `tests/shared/trace_fixture_builder.py` |
| sole `save_to_file` prod caller | `cli/commands/run.py:134` |
| measured baseline trace (9.4 MB, cleaned) | `.taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json` |
| prior dedup precedent (60-key hand minimizer) | `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/minimize-trace-fixture.py` |

---

## 12. Source docs read (for the next agent)
- `.taskmaster/tasks/task_133/task-133.md` — architecture decision record (merge rejected; #382 =
  honest model + per-run interning on current tree; span model deferred). **Most authoritative.**
- `.taskmaster/tasks/task_133/starting-context/braindump-storage-architecture-session.md` — the
  reasoning trail + "to re-verify before building #382" list.
- `.taskmaster/tasks/task_159/baseline/README.md` and `.../10-live-recordings/05-gemini-lyrics-generator/README.md`
  + `minimize-trace-fixture.py` — the real artifact, the precedent, and how it was produced.
- Root CLAUDE.md (manifesto: verify against code; simplicity for AI agents; no git ops without ask;
  show before you code; decisions need options + recommendation + STOP for stakes ≥3).
- `src/pflow/runtime/CLAUDE.md` — WorkflowTraceCollector / `--only` snapshot / batch-seam details.

> **Open decision still owned by the user** (none block Phase 1): none currently — gzip is ruled
> out, interning-only is chosen, threshold is settled. If a raw-trace re-measurement is wanted,
> that's a Phase-0 choice. Otherwise proceed to Phase 1.

---

## 13. Forward-compatibility with the deferred streaming / jsonl format (Task 133 D1–D3)

**The streaming span-model event log is OUT OF SCOPE for #382** (deferred, gated behind static
Task 155 + the live-UI overlay; the *design* lives in `task_133.md` D1/D2/D3, not the
implementation). Do **not** build any of it now — span IDs, `seq`, trailers, `parent_id`/`run_id`
correlation, inline ordering. The manifesto forbids pre-paying for speculative design, and Task 133
explicitly defers it.

But a few **near-zero-cost** factoring choices in Phase 1 keep the future migration tiny. Task 133
(braindump §D3) already pinned what the rework will be: *"the only rework here is 'top-of-file blob
table → inline-first-occurrence ordering' — small, and not worth pre-paying now."*

**Why placement changes but logic doesn't.** A top-of-file `blobs` map (what #382 writes) works
for a batch end-dump because the whole map is known before writing. A **live tailer can't** write a
complete header up front — it doesn't yet know all blobs — so the streaming format emits each blob
**inline at first occurrence**, giving backward-only refs (a forward tailer never hits an undefined
ref; a crash-truncated log stays self-consistent). The `{"$blob": "<hash>"}` ref convention and the
*substitution* logic are **identical** in both formats; only **where blobs are declared** changes.

**Bake in now (all are just good factoring, not extra complexity):**
1. **Shape-agnostic walk** — `intern_blobs`/`resolve_blobs` recurse over any dict/list; never
   hardcode `events`/`batch_items`/`sub_workflow_events`. Interning is orthogonal to tree-vs-flat
   (Task 133 confirmed), so the same walk works on today's nested tree AND a future flat jsonl
   event log, unchanged.
2. **`substitute_refs(obj, blob_map)` as a pure, format-independent function** (see §6). Today a
   thin `resolve_blobs(trace)` builds `blob_map` from `trace["blobs"]` and calls it. The future
   jsonl reader builds `blob_map` by accumulating inline blob declarations as it streams, then
   calls the *same* `substitute_refs`. The durable contract = (ref shape + content hash +
   substitution); the swappable part = map construction.
3. **Content-addressed, position-independent hashing** (md5/sha of content). Same content dedupes
   to the same blob whether top-map or inline-first — no change needed when ordering flips.
4. **`load_trace_file` is THE migration seam.** When the on-disk format becomes jsonl, you swap a
   jsonl parser in behind that single function; every consumer keeps receiving plain resolved
   dicts. (The tree⇄flat reassembly — `TraceTree.from_event_log` — is a separate, larger job and is
   **D1's**, not ours.)

**What we are NOT solving and is genuinely deferred (don't let it leak into #382):**
- The two **write-side** choke points D1 names: today each sub-workflow gets its own collector
  (save/restore around `engine.run` via `__trace_collector__`); streaming requires unifying that
  into span-context correlation — a collector + executor change, not a format change.
- D2 run-level aggregates → trailer `run_complete` event (and its Task-164 graceful-vs-crash
  discriminator).
- D3 global monotonic `seq` via a single append lock.

Net: #382 ships a self-contained disk fix on the current tree. If Phase 1 keeps the walk generic
and factors `substitute_refs`, the eventual streaming migration touches only the blob *placement*
(writer) and the *map-building* half of the reader — exactly the "small rework" Task 133 predicted.
