# Task 174 Follow-up — Implementation Plan: Narration Pacing + Persistent Replayable Captions

Status: **ready for implementation** (anchors verified against current code 2026-07-04, after the
phase 1–5 work landed). Parent: `task-174.md` + `implementation-plan.md`. This plan **reopens two
of 174's locked v1 decisions** with new evidence (the live `voice-demo` walkthrough): "new point
interrupts the prior clip" and "ONE active say-callout globally". Both reopenings are recorded
below with rationale — they are not silent.

**Baseline** (capture before starting; last known green this session): `make test` Python suite
passing (8471+); `cd web && npx vitest run` = **709 passed / 51 files**. Any delta must be
explained. No new architecture, no server change.

**Scope split** — two composable changes, implementable independently:
- **Change A (CLI pacing)** — Python only. ~25 lines prod + ~50 test.
- **Change B (persistent replayable captions)** — frontend only. ~25 net lines prod (~80 written,
  replacing ~57) + ~130 test.

---

## 0. What you are building (one paragraph)

A narrated walkthrough today interrupts itself: each `pflow ui focus … --say` cuts off the prior
clip because point-and-say was tuned for *live* pointing, not *scripted* sequences. **Change A**:
the CLI already holds the WAV, so after dispatching it blocks for the clip's exact duration
(`frames/framerate`) — a sequence of `--say` commands then self-paces with zero new architecture;
`--no-wait` opts out. **Change B**: the on-canvas caption stops being a single ephemeral box and
becomes a *persistent per-target annotation* — multiple coexist (one per anchor), a new say to an
anchor that already has a box replaces just that box, each finished box grows a **Replay** button,
the user closes each, and `clear-focus` closes all. Together: clips play in order, captions persist,
everything is replayable, the user curates — and because every finished box is replayable, an
interrupted clip is *recoverable*, which is why Change A's simple CLI pacing is sufficient and a
server/client playback queue is **not** built.

### Design calls (all made — locked; rationale one line each)

| Call | Choice |
|---|---|
| Pacing owner | **CLI-side block by clip duration (sync).** NOT a server/client playback queue — that only earns its complexity for fire-and-forget async narration, which is theorized, not observed (solve-observed-not-theorized). |
| Pacing default | **ON by default** for `--say`; `--no-wait` opts out. The whole point is that "fire a sequence of says" paces itself with no flag; 174 is unmerged so changing the default costs nothing. |
| Duration source | `wav_duration(wav: bytes) -> float` in `core/tts.py` = `getnframes()/getframerate()`. **TOTAL** — returns `0.0` on any `wave.Error`/parse failure (keeps existing mocked-bytes CLI tests instant AND never crashes the point). |
| Sleep gate | Sleep only when `audio_b64 is not None` **and** the point delivered (`not _dispatch_failed(payload)`). Skip on caption-only, synthesis failure, or 0-window (nothing is playing → nothing to wait for). |
| Sleep placement | **After** the final `_send_point` (in `focus_cmd`, the `--open` re-send at `ui.py:700`) **and after** `_emit_payload` + all reporting — the report prints, then the CLI blocks. Blocking is the last thing the command does. |
| Report field | `narration.duration_s: float \| null` (null when no audio). |
| Narration carrier | Introduce a `Narration` NamedTuple `(caption, audio_b64, reason, reason_kind, duration_s)` with a `.report` dict property. Folds today's 4-tuple **and** the `payload["narration"] = {…}` dict duplicated in both `focus_cmd` (:705) and `frame_cmd` (:760). Passes the deletion test (deleting it re-spreads the dict). |
| Caption model | **Persistent per-target:** `Map<string, SayItem>` keyed by `refKey(anchorRef)`. A new say to an existing key overwrites that box; a different key coexists. Removes the single `sayCallout` + the separate `narrationBlocked` flag (both fold into the Map + a per-item status). |
| Per-box status | `"playing" \| "blocked" \| "done" \| "expired"`. `playing`→(audio `ended`)→`done`; `play()` reject→`blocked`; replay 404/reject→`expired`. |
| One clip at a time | Single `audioRef` stays. Starting a clip flips any other `"playing"` box → `"done"` (an interrupted clip is finished-and-replayable, not lost). |
| Replay | A per-box button shown when `status === "done"`; re-creates `Audio(url)`, plays; on 404/reject → `"expired"` (button gone). The **caption text always stays** (spec: caption = baseline, audio = enhancement) — only replay can expire. |
| `clear` verb | Clears the **whole** Map + pauses (close-all = clearing the agent's annotations). A bare focus/frame still leaves boxes alone (spec-locked); `selectRun` too. |
| Camera | **Unchanged.** Each say's point message frames its own target; every box stays `frameOnMount={false}`, so multiple boxes never fight the camera. |
| Audio store | **No server change.** The 16-clip LRU (`_AUDIO_STORE_MAX`, server.py:97) stays; a box that outlives its clip degrades to `"expired"` on replay. Bump the LRU only if a demo shows it biting — deferred, keeps ADR-0007's bounded posture. |
| Reused primitive | `refKey` (graph/flow, already imported at `GraphView.tsx:21`) keys the Map; `flatIdForRef` + `representativeFor` resolve each box's anchor per render (the existing `sayAnchorId` logic, applied per item). |

### Reopened v1 decisions (do not treat as re-litigation)
- **"new point interrupts prior clip"** → still true for *audio* (one clip at a time), but Change A
  paces so it isn't *triggered* in normal sequential narration, and Change B makes any interruption
  *recoverable* via Replay.
- **"ONE active say-callout globally"** → replaced by per-target persistence. This is **more**
  aligned with the spec's own "captions persist… the user dismisses" than the v1 single-caption
  compromise was; v1 collapsed to one box only to match the interrupt model, which B supersedes.

---

## Change A — CLI pacing (`src/pflow/core/tts.py`, `src/pflow/cli/commands/ui.py`)

### A1. `wav_duration` — `core/tts.py`
Add beside `synthesize` (the module already imports `wave`, `io`):
```python
def wav_duration(wav: bytes) -> float:
    """Seconds of audio in a WAV blob. TOTAL: 0.0 on any unparseable/empty input
    (mirrors synthesize()'s totality — a bad blob must never crash the caller's pacing)."""
    # try: with wave.open(io.BytesIO(wav)) as w: frames, rate = w.getnframes(), w.getframerate()
    #      return frames / rate if rate else 0.0
    # except Exception: return 0.0
```

### A2. `Narration` carrier — `ui.py`
Replace the `_resolve_narration` 4-tuple with a NamedTuple near `_SAY_MAX_CHARS` (:34):
```python
class Narration(NamedTuple):
    caption: str | None
    audio_b64: str | None
    reason: str | None
    reason_kind: str | None
    duration_s: float | None
    @property
    def report(self) -> dict[str, object]:
        return {"audio": self.audio_b64 is not None, "reason": self.reason,
                "reason_kind": self.reason_kind, "duration_s": self.duration_s}
```
- `_synthesize_say` (:407) additionally computes `duration_s`: on success, `wav_duration(audio)`
  from the RAW bytes **before** base64 (lazy `from pflow.core.tts import synthesize, wav_duration`);
  on any failure branch, `None`. Return `(audio_b64, reason, reason_kind, duration_s)`.
- `_resolve_narration` (:457) returns a `Narration`. The `say is None` case → `Narration(None, …)`.

### A3. Wire pacing into `focus_cmd` (:657) and `frame_cmd` (:751)
Both bodies collapse to: `n = _resolve_narration(say)`, dispatch via
`_send_point(…, n.caption, n.audio_b64, …)`, and `if say is not None: payload["narration"] = n.report`
(deletes the duplicated dict at :705 and :760). Then, as the **last** action (after `_emit_payload`
and every `click.echo` note, after `focus_cmd`'s `--open` re-send at :700 which already reuses the
same `audio_b64`):
```python
if wait and n.audio_b64 is not None and not _dispatch_failed(payload) and n.duration_s:
    time.sleep(n.duration_s)   # block so a sequence of --say commands self-paces; --no-wait skips
```
Add `@click.option("--no-wait", "wait", flag_value=False, default=True, help="Don't block until the
narration clip finishes (fire-and-forget; a rapid sequence will interrupt).")` to BOTH commands (a
shared decorator like `_say_option`, or inline on each). `time` is already imported (:14).
`_dispatch_failed` (unchanged) already means "0 windows or unresolved" → no clip anywhere → no wait.

### A4. Tests — `tests/test_core/test_tts.py`, `tests/test_cli/test_ui_commands.py`
- `test_tts.py`: `wav_duration` on a real 1s canned WAV ≈ 1.0 (±one frame); on `b"not a wav"` → 0.0;
  on `b""` → 0.0.
- `test_ui_commands.py` (patch `time.sleep`, patch `pflow.core.tts.synthesize` + `wav_duration`):
  - `focus … --say` (audio present, sent_to≥1) → `time.sleep` called once with the clip duration;
    `narration.duration_s` in the JSON payload.
  - `--no-wait` → `time.sleep` NOT called; still POSTs.
  - synthesis failure (caption-only) → `time.sleep` NOT called (no clip).
  - 0-window / unresolved (`_dispatch_failed`) → `time.sleep` NOT called.
  - `--open --say`: sleep happens once, AFTER the re-send (assert order: re-send then sleep).
  - regression: existing say tests still green (canned bytes → `wav_duration` ≈ 0 → `sleep(0)` no-op;
    confirm none of them assert on wall-clock).

---

## Change B — Persistent replayable captions (`web/src/views/GraphView.tsx`, `index.css`)

### B1. State — replace the single caption + flag (`GraphView.tsx:141-145`, `:636-641`)
```ts
type SayItem = { anchorRef: RFRef; caption: string; audioUrl: string | null;
                 status: "playing" | "blocked" | "done" | "expired" };
const [sayCallouts, setSayCallouts] = useState<Map<string, SayItem>>(() => new Map());
const audioRef = useRef<HTMLAudioElement | null>(null);   // still ONE clip at a time
```
Delete `sayCallout`, `narrationBlocked`, and the single `sayAnchorId` useMemo (:636). A pure
module-level helper replaces per-render anchor resolution:
```ts
function sayAnchorId(graph, anchorRef, representativeFor): string | null {
  const flatId = flatIdForRef(graph, anchorRef);
  const node = flatId ? graph.nodes.find((n) => n.id === flatId) : undefined;
  return node ? representativeFor(node) : null;
}
```

### B2. Playback — `playNarration(key)` + `ended` (replaces `:642-657`)
```ts
const setStatus = useCallback((key: string, status: SayItem["status"]) =>
  setSayCallouts((prev) => {
    const item = prev.get(key); if (!item) return prev;
    const next = new Map(prev); next.set(key, { ...item, status }); return next;
  }), []);
const playNarration = useCallback((key: string, url: string | null) => {
  audioRef.current?.pause(); audioRef.current = null;
  // Any box that was playing is now finished (interrupted → replayable, not lost).
  setSayCallouts((prev) => {
    const next = new Map(prev);
    for (const [k, it] of next) if (it.status === "playing") next.set(k, { ...it, status: "done" });
    return next;
  });
  if (!url) { setStatus(key, "done"); return; }   // caption-only: immediately "done" (nothing to replay-fail)
  const clip = new Audio(url); audioRef.current = clip;
  clip.onended = () => { if (audioRef.current === clip) setStatus(key, "done"); };
  clip.play().catch(() => { if (audioRef.current === clip) setStatus(key, "blocked"); });  // currency guard kept
}, [setStatus]);
```
(Keep the unmount cleanup `useEffect(() => () => audioRef.current?.pause(), [])`.)

### B3. Replay — per box
```ts
const replay = useCallback((key: string, url: string) => {
  audioRef.current?.pause();
  const clip = new Audio(url); audioRef.current = clip;
  setStatus(key, "playing");
  clip.onended = () => { if (audioRef.current === clip) setStatus(key, "done"); };
  clip.play().then(() => {}).catch(() => { if (audioRef.current === clip) setStatus(key, "expired"); });
}, [setStatus]);
```
(A 404 on an LRU-evicted clip lands in `.catch` → `"expired"` → button gone; caption stays.)

### B4. Handlers — the `say` arm + `clear` + close (`GraphView.tsx:751-757`, `:741-747`)
```ts
say: (target, caption, audioUrl) => {
  if (!graph) return;
  const anchorRef = target.kind === "node" ? target.ref : target.target;
  if (!flatIdForRef(graph, anchorRef)) return;      // stale ref → drop (unchanged)
  const key = refKey(anchorRef);
  setSayCallouts((prev) => new Map(prev).set(key, { anchorRef, caption, audioUrl, status: "playing" }));
  playNarration(key, audioUrl);
},
```
- `clear` handler: `audioRef.current?.pause(); setSayCallouts(new Map());` (close ALL — locked).
- `closeSay(key)`: pause if that box was playing, then `setSayCallouts` with the key deleted.
- Wire `say` into the `subscribe(...)` object exactly as today (deps untouched — web/CLAUDE.md).

### B5. Render — one box per entry (replaces `:1046-1067`)
```tsx
{graph && [...sayCallouts].map(([key, item]) => {
  const anchorId = sayAnchorId(graph, item.anchorRef, representativeFor);
  if (!anchorId) return null;                        // vanished node → hide that box
  return (
    <NodeCallout key={key} anchorId={anchorId} direction={direction} title="Agent"
                 frameOnMount={false} onClose={() => closeSay(key)}>
      <p className="say-caption">{item.caption}</p>
      {item.status === "blocked" && item.audioUrl && (
        <button className="say-unlock" onClick={() => replay(key, item.audioUrl!)}>▶ Play narration</button>)}
      {item.status === "done" && item.audioUrl && (
        <button className="say-replay" onClick={() => replay(key, item.audioUrl!)}>↻ Replay</button>)}
    </NodeCallout>
  );
})}
```
(`blocked` and `done` both call `replay` — the unlock gesture and the replay gesture are the same
"play this clip"; only the label/trigger differ.) The run callout at `:959` is untouched.

### B6. CSS — `index.css` (beside `.say-unlock` :2311)
Add `.say-replay` (same shape as `.say-unlock`; can share a selector). ~4 lines.

### B7. Tests — `GraphView.test.tsx` (say describe :1081) + `events`/interaction unaffected
`FakeAudio` (:1085) gains `onended: (() => void) | null = null` and `fireEnded() { this.onended?.(); }`.
- **Keep** (adapt only to the Map): anchors-a-caption, caption-only-no-clip, edge-target-anchor,
  close-pauses, blocked→unlock, unmount-pauses, stale-ref-drops.
- **Split** the old "second say replaces + currency guard":
  - same-target second say → ONE box, new caption (Map overwrite);
  - **different**-target second say → TWO boxes coexist (the new persistence);
  - keep the currency-guard assertion (rapid says → stale `AbortError` never flips a box to
    `blocked`).
- **New**:
  - `fireEnded()` on a playing clip → box status `done` → **Replay** button appears; clicking it
    calls `play()` again;
  - replay whose `play()` rejects (evicted 404) → box `expired`, button gone, **caption stays**;
  - close ONE of two boxes → the other remains;
  - `clear` → ALL boxes gone + pause.

---

## Change C — Docs + verification

1. `make check` green; `cd web && npx vitest run` (report delta vs 709); `npm run build` + `make ui-build`.
2. Real-browser re-demo on `voice-demo.pflow.md` (screenshot skill): fire the 6-step walkthrough as
   ONE shell sequence and confirm (a) clips no longer interrupt (pacing), (b) all six boxes persist
   and coexist, (c) each finished box shows Replay and it plays, (d) `clear-focus` clears all.
   Audible check + a genuinely-blocked autoplay stay user-only (headless allows autoplay).
3. Docs: `guide/features/ui.md` (captions now persist per-node + Replay; `--no-wait`);
   `docs/reference/cli/index.mdx` (`--no-wait` on focus/frame + the pacing sentence);
   `web/CLAUDE.md` + `web/src/components/CLAUDE.md` (say model: per-target Map, statuses, Replay);
   `src/pflow/cli/commands/CLAUDE.md` (pacing + `Narration`/`--no-wait`); `src/pflow/core/CLAUDE.md`
   (`wav_duration` on the tts.py row). Progress log entry.

## Do NOT build (locked out)
Server-side or client-side playback **queue** (option B from the pacing discussion — reconsider only
if fire-and-forget async narration becomes a real need); a native CLI `--batch` flag (the agent
sequences says in one shell call); a side-panel narration log (throws away the on-canvas spatial
anchoring that IS point-and-say); `_AUDIO_STORE_MAX` bump (the `expired` degrade covers eviction);
queue-depth reporting (only exists in a queue design — `duration_s` is the sync-model equivalent).

## Two decisions to ratify before coding (low stakes, both reversible)
1. **Pacing default = block, opt-out `--no-wait`** (vs default fire-and-forget + opt-in `--wait`).
   Recommend block-by-default (the sequence-just-works property is the whole point). Flag name
   `--no-wait` is the one bikeshed.
2. **`Narration` NamedTuple** (folds the 4-tuple + duplicated report dict) vs the minimal-diff
   option of just widening the tuple to 5. Recommend the NamedTuple — it's a fold, not a layer.
