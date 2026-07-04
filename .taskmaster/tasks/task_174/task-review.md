# Task 174 Review: Agent Voice Narration — "Point & Say" (+ pacing/persistence follow-up)

## Metadata

- Implemented 2026-07-04 on `feat/agent-voice-narration`. v1 phases 1–5 committed (`66220404`,
  `c1063ef0`); the follow-up (pacing, persistent captions, playback beacons, blocked-hold, TTS
  setters, ADRs 0011/0012) is **uncommitted working tree on top** — review the full branch diff,
  not just the commits. Not merged. No users yet (per CLAUDE.md), but the feature is demo-critical.
- Final state verified live: Python 8495+ passed / web 719 passed / `make check` green, plus a real
  user-heard walkthrough (block → hold → ▶ click → resume → paced narration).
- Journey (4 falsified design iterations in one day, all measurements): `implementation/progress-log.md`.
- Untracked demo fixtures at repo root: `ticket-triage.pflow.md`, `voice-demo.pflow.md` (keep for demos).

## Read First — the load-bearing block

**What exists now:** `pflow ui focus|frame <wf> <target> --say "text"` synthesizes CLI-side
(Gemini TTS via direct httpx), uploads WAV to `/api/say`, which broadcasts point-then-caption over
the 169 SSE channel; the browser shows persistent per-target caption boxes with Replay and plays
one clip at a time. Sequential `--say` commands self-pace as a narrated walkthrough via a
closed loop: CLI waits-before-dispatch on the server's narration rendezvous, which the browser
corrects with playback beacons; a silent (autoplay-blocked) window **holds** the walkthrough until
the user's ▶ click.

**Read these first:**
- `src/pflow/core/tts.py` — `synthesize()` / `strip_delivery_tags()` / `wav_duration()` (totality seams)
- `src/pflow/cli/commands/ui.py` — `Narration`, `_resolve_narration`, `_send_point`, `_await_narration_turn` (the pacing/hold seam)
- `src/pflow/ui/server.py` — `say()`, `narration()`, `health()`, `_AudioStore`, `narration_until`/`narration_blocked`
- `web/src/views/GraphView.tsx` — `SayItem` Map, `startClip` (the single start-any-clip seam), `sayAnchorIdFor`
- `context/adr/0011-174-tts-direct-httpx.md` + `0012-174-narration-pacing-closed-loop.md` (the two decisions people will try to "fix")

**Invariants that must NOT break:**
- **No `await` between the two broadcasts in `say()`** — point→caption per-queue ordering exists
  only because the block is synchronous. An await lets a Viewer see the caption before the focus.
- **Every handler touching `narration_until`/`narration_blocked`/`_AudioStore` stays `async def`**
  — they are lock-free ONLY by event-loop affinity (the 169 hub invariant, extended). A sync
  handler runs threadpooled and races silently.
- **`synthesize()` and `wav_duration()` are TOTAL** (after the key check / unconditionally). The
  CLI sleeps on `wav_duration`'s value and `_synthesize_say` never raises — a leaked exception
  either crashes the point or stalls pacing. Same for the server's duration computation.
- **`startClip`'s sweep excludes its own key and sets the key's status itself** — reordering
  reproduces two plan-stage bugs (a playing box showing Replay; an interrupted box stuck
  `"playing"` forever). Both are mutation-pinned in `GraphView.test.tsx`.
- **Currency guards (`audioRef.current === clip`) on BOTH `onended` and the play `.catch`** —
  `pause()` rejects the prior clip's pending `play()` with AbortError *after* the new clip starts;
  an unguarded catch flips the NEW box's state. Fires exactly on rapid says (the demo flow).
- **Say-box anchors are structural refs (`refKey(anchorRef)`), never flat ids** — flat `n*/g*` ids
  are positional and renumber on any live-reload rebuild; anchors re-resolve per render.
- **Notes print to stderr before the payload** — in JSON mode stdout must stay one pure JSON
  document; the hold notes print BEFORE dispatch, so `err=True` unconditionally.

## What Was Built (actual vs. planned)

v1 (phases 1–5) landed essentially per plan. The follow-up's approved design was then **replaced
same-day by user-driven iteration** — the durable deviations:

- **Pacing v2 supersedes the approved "sleep after dispatch."** The CLI now synthesizes, waits its
  turn (server `narration_s_remaining` via the existing `/api/health` probe), dispatches, returns
  at clip START. Dead air went from ~5s to ~0 (measured; residual = `max(0, synth − prior clip)`).
  A `~/.pflow` file rendezvous was rejected (invisible to test isolation → xdist pollution); the
  server owns the state because it already holds the audio.
- **`_NARRATION_START_LAG_S = 0.75` pad** — broadcast-time ≠ playback-time (browser starts 0.3–1s
  later; the un-padded estimate audibly clipped last words).
- **Playback beacons (`POST /api/narration`, `web/src/api/events.ts::reportNarration`)** — not in
  any plan. Born when the CLI narrated a silent autoplay-blocked window while reporting "sent to 1
  window". `started` re-anchors the rendezvous to real playback, `blocked` flags health, `ended`
  clears. This *is* ADR-0007's deferred "browser acks, additive later" arm, for narration only.
- **Blocked-hold** — `_await_narration_turn` polls (0.5s × 240 cap) while `narration_blocked`,
  printing `note: … holding the walkthrough; click the caption's ▶ button …` / `resuming`. The
  user explicitly rejected "march on with a note".
- **`startClip` fold** — the plan's separate `playNarration`/`replay` sketches contained two state
  bugs (see invariants); merged into one function with a `failStatus` param (`"blocked"` initial /
  `"expired"` replay — a gesture replay can't be autoplay-blocked, so its rejection means evicted).
- **`pflow settings llm set-tts-model|set-tts-voice` + `unset` arms** — v1 displayed the TTS fields
  with no way to change them except hand-editing settings.json. `unset` restores BUILT-IN defaults
  (fields are non-Optional `str`), unlike the model trio's revert-to-None; no LiteLLM prefix
  normalization (TTS ids aren't LiteLLM-routed).
- **Health contract extension** — `narration_s_remaining` + `narration_blocked` ride every
  `/api/health` body. Three 169-era exact-body test pins were deliberately amended (recorded, not
  snuck in).

## Patterns & Anti-Patterns

**Patterns to propagate:**
- **Close the loop with the physical world.** Anything whose correctness is "did the human
  see/hear it" needs telemetry from the far endpoint, not an open-loop model. Three estimates were
  falsified live before the beacons ended the class. Build observability FIRST next time — once
  beacons existed, each remaining bug diagnosed itself in one run.
- **Total functions at degrade seams.** `synthesize()`/`wav_duration()`/`_synthesize_say()` never
  leak exceptions; "caption always, voice when it can" holds because every failure has a value.
- **One seam per behavior.** `_send_point` (say-vs-point routing), `startClip` (start any clip),
  `_await_narration_turn` (all waiting), `sayAnchorIdFor` (anchor resolution). Each demo-day fix
  stayed 20–60 lines because these existed.
- **Fresh-agent doc audits.** `pflow guide ui` was re-read as rendered output after three
  incremental patches — the accretion seams were only visible that way. Quote real CLI output in
  guides (agents pattern-match strings, not descriptions).

**Anti-patterns (tried/rejected — don't resurrect):**
- Browser/server **playback queue** — rejected twice; earns complexity only for fire-and-forget
  async narration (unobserved). Boxes+Replay make interruption recoverable. See ADR-0012.
- **Cross-process CLI state on disk** for coordination — test-isolation-invisible.
- Routing TTS through `llm_client`/LiteLLM — see ADR-0011 (pin + broken audio path); the
  "inconsistency" is deliberate.
- Pinning autoplay/audio behavior with headless-browser tests — headless Chrome ALLOWS autoplay;
  the entire blocked class is invisible there. jsdom has no audio at all. Real-user-browser only.

## Gotchas & Non-Obvious Coupling

- **Chrome's autoplay policy is the dominant failure mode for fresh `--open` windows** and it's
  machine/profile-dependent (MEI). Symptoms without beacons looked like random bugs ("only the
  last clip played"). Any future audio path must route through `startClip` so the beacons keep
  reporting truth.
- **Agent-latency coupling:** thinking time between separate `--say` tool calls is absorbed only
  up to the playing clip's length; the guide now says "one chained shell command". A narrating
  agent's tool call blocks for the whole sequence + up to 2 min of hold — budget timeouts or
  background the chain (pacing lives inside each command; backgrounding is safe).
- **`clear` is entangled with narration on BOTH sides:** server resets `narration_until`; frontend
  `dismissAllSays` pauses + clears the Map. Touch one, check the other.
- **The hold clears only via a `started` beacon** — i.e. the ▶ click that plays the blocked box. A
  bare canvas click grants the browser gesture but fires no beacon, so the hold continues. Known;
  the note directs to ▶ specifically. (A page-level pointerdown unlock is the noted future fix.)
- **`test_ui.py` pops `pflow.ui.server` from `sys.modules`** — patching server module constants by
  string silently no-ops in full-suite order; use `patch.dict(create_app.__globals__, …)`
  (tests/CLAUDE.md pitfall #21; bit us once for real).
- **jsdom can't mount `NodeCallout` naturally** (no-op ResizeObserver → RF never measures) — the
  `getInternalNode` measured-backfill in `GraphView.test.tsx`'s `useReactFlow` partial mock is what
  makes ALL callout DOM tests possible. `FakeAudio.play()` must mint a FRESH promise per call, and
  `pause()` must NOT fire `onended` (real HTMLMediaElement contracts; violating either makes
  replay/interrupt tests silently wrong).
- **A stale pre-feature server on :8765 answers 405 on new endpoints** (static-mount fallthrough)
  — looks exactly like "the feature doesn't exist". Kill + restart from the worktree before any
  browser verification; rebuild the bundle (`make ui-build`) after web changes and cache-bust with
  a throwaway `&v=` param.
- Gemini responses: the pinned `generateContent` shape is live-verified; a safety-filtered 200 has
  `candidates: []`; near-cap (1500-char) inputs can exceed 120s synthesis (measured) — the 30s
  timeout is a deliberate bound, not a bug.

## Integration Points

- **`GET /api/health`** now carries `narration_s_remaining`/`narration_blocked` on EVERY body —
  consumed by `_await_narration_turn`; the discovery/reuse probes ignore the extra keys but three
  exact-body tests pin the full shape.
- **`POST /api/narration`** (mutating, loopback-guarded, in both guard-inventory tests) ←
  `reportNarration` fire-and-forget from `startClip`/`closeSay`.
- **`POST /api/say` / `GET /api/audio/{id}`** — unchanged wire contract from v1; `say()` now also
  writes the rendezvous (delivered + playable audio only).
- **Settings:** `llm.tts_model`/`llm.tts_voice` (concrete defaults `gemini-3.1-flash-tts-preview`/
  `Kore`); key rides the existing `inject_settings_env_vars()` path — no new credential plumbing.
- **Docs that transcribe output** (will drift silently): `docs/reference/cli/settings.mdx` (literal
  `llm show` output incl. the To-configure block), `docs/reference/configuration.mdx` (llm.* table),
  `docs/reference/cli/index.mdx` (ui verbs + pacing paragraph), `src/pflow/guide/features/ui.md`
  (quotes the two CLI notes VERBATIM — changing a note string means updating the guide).
- **Engine/runtime: zero contact.** The whole feature lives in cli/ui/web; batch/loop/cache/nodes
  untouched by design.

## Tests That Matter

- `web/src/views/GraphView.test.tsx` "agent say callout" describe — **mutation-verified**: the
  plan's original sketch fails 5 tests; removing the interrupt sweep fails 2. Also pins the
  currency guard (rapid two-say AbortError), unmount-pauses, beacon truthfulness (incl.
  expired-replay ≠ blocked). Run on ANY GraphView/audio change.
- `tests/test_cli/test_ui_commands.py::TestSayPacing` — the pacing seam: hold-until-unblocked with
  ORDERED events (sleeps then post), poll-cap give-up, bare-focus-never-probes, `--open --say`
  distinguishing the two sleep sources by VALUE (the braindump's named trap).
- `tests/test_cli/test_ui_interaction_server.py::TestNarrationPacingRendezvous` — rendezvous
  set/reset semantics incl. zero-window/caption-only/garbage-bytes never-busy, started re-anchors
  exactly, clear resets. `TestSayEndpoint::test_say_point_is_replayed_…` — **mutation-verified**
  reconnect-replays-point-never-caption (the most-debated design call).
- `tests/test_core/test_tts.py` — totality table (safety-filtered 200 ≠ IndexError, etc.);
  `wav_duration` exactness.
- `tests/test_cli/test_settings_cli.py::test_llm_show_names_the_tts_setters` — meta-pin: `show`
  must name a setter for every field it displays (the gap class that stranded agents).
- Guard inventories (content-type 415 + evil-Host 403 lists) — every new endpoint MUST be added or
  the DNS-rebinding posture silently erodes.

## Extension points for the next task

- **Page-level autoplay unlock** (any pointerdown plays the most recent blocked box) — makes
  "click anywhere" true and the hold friendlier; touches global listeners, deferred.
- **Cross-provider TTS**: lands entirely inside `synthesize()` incl. bracket-tag translation
  (spec forward-note; the agent-facing `[bracket]` syntax must remain the ONLY syntax).
- **Caption latch/replay to reconnecting windows** — recorded as a clean additive follow-up if a
  demo shows the gap; deliberately NOT built.
- Clip caching by `(text, voice)` hash — makes repeated demo lines instant; natural CLI-side
  `~/.pflow/` cache; not needed yet.

---
*Distilled from the implementation context of Task 174 (v1 + follow-up + live-demo session). The
chronological journey — four falsified pacing designs, the live measurements, and every deviation
as it happened — lives in `implementation/progress-log.md`; this review is the durable
forward-reference.*
