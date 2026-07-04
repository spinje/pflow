# Task 174: Agent Voice Narration — "Point & Say" (Spoken TTS for the Workflow Viewer)

## Description

Extends Task 169's agent↔browser channel so the agent can attach a **spoken message** to a
point: `pflow ui focus <wf> <target> --say "..."` focuses the node in the user's open Viewer
**and** narrates an explanation aloud (text-to-speech) with an on-canvas caption. It turns the
canvas from "the agent can point" into "the agent can point *and explain*" — the literal version
of the conversation metaphor Task 169 was designed around ("the agent points, says 'see it?'").

## Status

in progress

> All phases (1–5) implemented + tested on 2026-07-04: core TTS, server, CLI, frontend, docs,
> real-browser verification (caption/edge-anchor/degrade verified live; audible + autoplay-unlock
> checks left to the user), and the code-mode deep-review (4 agents, 2 confirmed findings, both
> fixed). `make check` green; Python suite 8471 passed (0 regressions), web suite 709 passed
> (+15). Awaiting human review; not committed. See `implementation/progress-log.md`.

## Priority

high — demo-driven (a near-term demo needs it) and a clean fast-follow on 169. Independent of the
172/173 overlay track, so it can land without waiting on the trace/overlay work.

## Problem

After Task 169 the agent can Point at a node in the user's browser and Watch their clicks, but the
agent's *explanation* still lives only as prose in the terminal — a separate surface from the
canvas the user is looking at. Two concrete needs surfaced:

- **Dev iteration:** while building/explaining a workflow, the agent wants to narrate "*this* is
  where the LLM call happens" with the canvas focused there — voice keeps the user's attention on
  the graph instead of split between graph and terminal.
- **Interactive demos that double as real functionality:** a compelling way to show off pflow is
  the agent dynamically narrating + pointing as it reasons about a workflow. The narration *is* the
  product capability, not a mockup.

The browser's built-in Web Speech API was evaluated and rejected: **quality is unusable**. So this
needs real synthesized TTS audio, not browser-side speech synthesis.

## Solution

A new `--say "text"` option on the existing `focus`/`frame` verbs. The CLI synthesizes the text to
audio (default: Gemini 3.1 Flash TTS via a direct API call), uploads the audio to the running UI
server, and the server broadcasts a `say` message over Task 169's existing SSE channel. Each open
Viewer focuses the target (unchanged Task 169 path), shows the text as a persistent on-canvas
caption, and plays the audio.

The agent's entire surface is the **sentence**. It never sees a URL, audio bytes, a voice name, a
model id, or an audio format. All TTS machinery is folded behind the CLI verb — a deep module with
a one-field interface.

High-level flow (single request — see Design Decisions for why not two):
1. `pflow ui focus wf node --say "[excited] this is the LLM call"`
2. CLI synthesizes the text → PCM16 audio → wraps to WAV (stdlib `wave`).
3. CLI uploads the WAV (base64-in-JSON) to a new server endpoint.
4. Server stores the audio in an ephemeral in-memory store, broadcasts
   `{type: "say", target, caption_text, audio_url?}` to every subscribed window for that workflow.
5. Browser focuses the target, shows the caption, and plays the clip.

## Design Decisions

- **CLI-side synthesis, NOT server-side.** The CLI (the agent's hands) calls the TTS provider; the
  server only stores + relays the bytes. This preserves three properties Task 169 deliberately
  holds: (1) the **viewer stays local + keyless** — you can still run `pflow ui` with no LLM/TTS
  key and just look at a graph; only the narrating agent needs a key, and it already has LLM
  creds; (2) the **security backstop stays benign** — the server makes no outbound calls, so the
  worst-case cross-origin write against the loopback server is still "store/play some bytes,"
  never "spend money / exfiltrate text to a third party"; (3) the **hub stays minimal** — no slow,
  failing outbound IO added to the loop-affine, lock-free `_Hub`. (Server-side synthesis was
  considered and would win on cross-invocation caching/dedup and a thinner CLI — revisit only if a
  demo replays a small fixed set of lines across many windows.)

- **Default provider: Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) via a DIRECT httpx
  call, NOT via LiteLLM.** Reasons: pflow's LiteLLM is pinned to exactly `==1.86.1` (intentional,
  deterministic offline pricing map; bumping has side effects) and LiteLLM's Gemini-audio path is
  young/buggy (pcm16-only, no streaming, open bug BerriAI/litellm#11118). A direct httpx call uses
  the already-present `httpx` dep, sidesteps the version-pin risk, and is simpler than LiteLLM's
  chat-completions-with-`modalities:["audio"]` shape. The `google-genai` SDK is NOT added (would be
  a new dep). Price/quality is strong: ~$1.80/hr of audio (~½¢ per 10s line, ~20¢ for a 50-line
  demo).

- **`synthesize(text, cfg) -> bytes` seam.** Provider/voice/model live behind this one function.
  Swapping to OpenAI or ElevenLabs is a config change with **zero agent-command change**. The seam
  is also the documented home for the future cross-provider tag-translation layer (see below).

- **Single-request flow, NOT a two-request point-then-audio split.** A split (fire the point+caption
  instantly, send audio when synthesis finishes ~1–2s later) was designed and **dropped**: its only
  benefit is an instant *visual* during *live* synthesis, but demos that care about polish use
  pre-rendered/cached audio (already instant), and dev iteration tolerates ~1–2s fine (terminal
  text already gives instant feedback). It fails the deletion test (adds a correlation id +
  supersession state machine + a second POST for a narrow, theorized win) and the
  solve-observed-not-theorized rule. It remains a **purely additive optimization** the envelope
  already permits — add it only if live-synth latency is observed to actually bite.

- **Caption = always-on baseline channel; voice = enhancement.** The caption *always* renders from
  the `--say` text; audio plays *when it can*. This removes the failure-branching: a blocked
  autoplay or a failed synthesis both land on "caption showed, audio didn't" with no special path.
  On synth failure the CLI still sends the `say` message **without** `audio_url` (caption shows;
  reason goes in the result report, never an error the agent must catch).

- **Captions persist with a close button.** No auto-fade. A new point may replace the prior caption
  on the same target; otherwise the user dismisses it via an explicit close/X affordance.

- **Inline Gemini bracketed tags supported; brackets stripped from the caption.** Gemini takes
  delivery direction inline in the same text string, two ways: bracketed tags (`[excited]`,
  `[whispers]`, `[slow]`, `[short pause]`, … — 200+, open-ended, combinable, consumed/not spoken)
  and natural-language style prefixes (`Say cheerfully: …`). v1 supports **bracketed tags**: the
  agent just writes them inline in `--say`; the caption text has `[...]` stripped (regex) at the
  source before broadcast. This is *correct*, not a hack — tags are delivery metadata, not words,
  so stripping makes the caption equal the spoken **words** while the tags shape only *how* they
  sound (preserves "spoken words == shown words"). **Natural-language prefixes are NOT cleanly
  strippable** (free-form prose) → they would leak into the caption; guide the agent toward
  brackets. Agent-facing rule: *delivery goes in `[brackets]`; everything outside is spoken AND
  shown.*

- **Cross-provider tag translation is the seam's future intent (forward-note, NOT v1 work).** When
  other TTS providers are added later, `synthesize()` is where the canonical inline-tag syntax gets
  **translated** into each provider's native mechanism — Gemini = passthrough; OpenAI
  `gpt-4o-mini-tts` = extract the bracketed tags into its separate `instructions` field and send
  the clean words as spoken content; ElevenLabs = its own tag/SSML vocabulary — so the agent only
  ever learns **one** syntax. v1 ships Gemini pass-through only (the canonical syntax simply *is*
  the bracket syntax for now). The future provider task owns the translation layer, including
  graceful handling of tags that don't map (drop or nearest-match). **Do not invent a second
  agent-facing syntax.**

- **Config via existing settings + env injection.** Two new settings fields (`tts_model`,
  `tts_voice`) in the `llm` settings section. API keys ride the **existing**
  `inject_settings_env_vars()` → `os.environ` path — Gemini's `GEMINI_API_KEY`/`GOOGLE_API_KEY`
  already flow through the provider registry, so there's **no new credential plumbing**. Sensible
  defaults are baked in (model = `gemini-3.1-flash-tts-preview` + a default voice) so `--say` works
  with just a key set, no required config.

- **No streaming in v1.** The use case is sentence-length point-and-say, not paragraph narration,
  so progressive playback buys little. (Gemini 3.1 *does* support native streaming — available
  behind the direct call if long-form narration ever becomes a real need; that would be the case to
  reconsider server-side synthesis to drop a hop.)

- **Standalone point-less `pflow ui say` verb: deferred** (build when a consumer exists, e.g. a
  narrated demo intro with no target). v1: `--say` rides `focus`/`frame` only.

## Dependencies

- **Task 169 (Agent↔Browser Interaction Channel) — DONE (PR #527).** Reuses the SSE channel, the
  `_Hub`, the vocabulary-agnostic envelope (`say` is an additive message type), the server-side
  target resolver, the `focus`/`frame` CLI verbs and `_request()` thin client, and the frontend
  `applyPoint` focus path. This task is a fast-follow on it.
- **NOT dependent on Task 172/173 (streamable trace / live overlay).** Independent track; can land
  before or alongside them. Issue #529 (SSE reconnect robustness) is related but belongs to the
  173 track — not required here (169's human-in-the-loop model makes a dropped connection an honest
  "0 windows," recoverable by reload).

## Requirements

### Interface (agent-facing)
- `pflow ui focus <wf> <target> --say "text"` and `pflow ui frame <wf> <target> --say "text"`
  point as before AND narrate + caption the text.
- The agent never supplies or sees a URL, audio bytes, voice, model id, or audio format. `--say`
  takes only the sentence.
- Inline bracketed delivery tags in the text (e.g. `[excited]`) are passed to synthesis and removed
  from the caption.
- A soft length cap on `--say` rejects/warns on absurdly long input (a typo must not synthesize a
  10-minute clip).

### Synthesis (CLI-side)
- A `synthesize(text, cfg) -> bytes` function performs a direct httpx call to Gemini TTS and returns
  WAV bytes (PCM16 from the API wrapped via stdlib `wave`).
- Provider/voice/model come from config (`tts_model`, `tts_voice` + key via env injection), never
  from CLI flags. Defaults make `--say` work with only a key configured.
- Synthesis failure (no key, network, rate limit, API error) does NOT abort the point: the `say`
  message is still sent without `audio_url`, and the failure reason appears in the result report.

### Server & channel
- A new mutating endpoint accepts the uploaded audio + the `say` parameters; a read-only
  `GET /api/audio/<id>` serves the stored bytes.
- Audio lives in an ephemeral in-memory store with bounded eviction (TTL or small LRU); memory
  stays flat under repeated use.
- The `say` broadcast mirrors `/api/command`: validate → resolve `workflow_key` → `hub.broadcast`.
  Every hub-touching handler is `async def` (Task 169 hub invariant — no sync handlers reading
  `app.state.hub`).
- New routes are registered **before** the static `Mount("/")` catch-all.
- All existing Task 169 endpoints and behavior are unchanged.

### Security
- The new endpoints honor + extend the existing no-CORS/loopback tripwire comment in `server.py`.
  Because synthesis is CLI-side, the server's worst-case cross-origin write stays benign
  (store/play bytes; no outbound call, no file/system effect). `GET /api/audio/<id>` is read-only.

### Frontend
- `web/src/api/events.ts` recognizes the `say` envelope type (envelope stays vocabulary-agnostic;
  no run-event schema — Task 133/173 boundary).
- On a `say` message: focus the target (existing `applyPoint` path), render the caption text near
  the target, play the audio. The caption persists and has a close/dismiss control.
  **Reuse `NodeCallout` for the caption (verified 2026-07-04) — do NOT build node-relative
  positioning fresh.** `web/src/components/NodeCallout.tsx` is a content-agnostic node-anchored box
  primitive built by Task 175 with THIS task named as a co-target in its header ("Task 174's agent
  'say' bubble reuses the same shell"). It owns anchoring/framing/chrome; pass the bracket-stripped
  text as `children` + a `title`/`onClose`. Sole current usage wraps `RunProgress`
  (`GraphView.tsx:956-983`). Wiring trap: a `say` callout and the run callout can coexist and both
  fire the one-shot `setCenter` — reconcile the camera framing at the GraphView level (not by
  editing `NodeCallout`).
- A one-time **autoplay unlock** affordance handles the browser autoplay policy (audio is blocked
  before a user gesture) so the first clip in a freshly opened window isn't silently dropped.
- Caption shows the bracket-stripped text (stripping may be done at the source before broadcast;
  the frontend must not display raw `[tags]`).

### Packaging
- No new runtime dependency: `httpx` and stdlib `wave` are already present. `google-genai`/provider
  SDKs are NOT added.

## Implementation Notes

- **CLI upload reuses `_request()` via base64-WAV-in-JSON** (`_request` is JSON-only — hardwired
  `json=`/JSON-decode). A ~10s clip ≈ 480 KB WAV → ~640 KB base64; chunky but localhost-fine.
  Alternatively add a small `httpx.request(content=bytes)` helper if base64 bloat matters. The
  CLI's own Gemini synthesis call (~1–2s) is a *separate* httpx call with its own timeout — it does
  NOT run inside the 5s `_REQUEST_TIMEOUT_S` localhost-upload budget.
- **Gemini audio is base64 PCM16, mono, 24 kHz** — not a playable file. Wrap in a WAV header
  (stdlib `wave`, ~5 lines) before upload; browsers play WAV natively. MP3 would shrink payloads
  but needs an encoder dep — skip for v1.
- **The audio store is the only piece with no existing analog.** The `_Hub` holds *connections*,
  not blobs; the audio bytes need their own short-lived keyed store (same ephemeral spirit), served
  by the GET route.
- **Overlapping audio:** a new point interrupts the prior clip (sane default for human-paced
  narration).
- **Caching (optional, additive):** caching synthesized clips by a `(text, voice)` hash makes a
  repeated line instant on reuse (behaves like pre-rendered). Not required for v1; natural CLI-side
  on-disk cache in `~/.pflow/` if added.
- **Pre-rendered path for demo safety:** the same plumbing serves a static `audio_url` instead of a
  live synth — point at hand-picked clips for a deterministic, zero-API-risk demo. No extra code;
  it's just "don't synthesize, point at an existing file." Worth keeping in mind for the imminent
  demo.

### Code anchors (from codebase scan)
- `src/pflow/cli/commands/ui.py` — `_request()` (~`:86`), `UiGroup`, `focus`/`frame` verbs (add
  `--say`; CLI synth + upload).
- `src/pflow/ui/server.py` — `_Hub` (~`:93`), `/api/command` (~`:407`), `create_app()` route
  registration (~`:556`), the static `Mount("/")` catch-all, the security tripwire comment. Add the
  `say` endpoint, the audio store, and `GET /api/audio/<id>`.
- `src/pflow/core/settings.py` — `SettingsManager` (add `tts_model`/`tts_voice` to the `llm`
  section).
- `src/pflow/core/llm_config.py` — `inject_settings_env_vars()` (~`:172`); keys reach env here.
- `src/pflow/core/llm_providers.py` — `PROVIDERS` + Gemini env-var aliasing.
- `src/pflow/core/llm_client.py` — completion-only today (no TTS). Add a new `synthesize()` here or
  in a sibling module; do NOT try to reuse `complete()`.
- `web/src/api/events.ts` — learns the `say` envelope type.
- `web/src/components/NodeCallout.tsx` — the reusable node-anchored box the caption rides (built
  Task 175, co-targeted at 174). `web/src/components/RunProgress.tsx` — the execution-specific
  child that models what the `say` text-body replaces.
- `web/src/views/GraphView.tsx` — `applyPoint` gains a `say`-callout state pair + WAV playback +
  autoplay unlock (render a second `NodeCallout` with a text body; caption positioning is reused,
  not rebuilt — see Frontend note re: the coexisting-callout camera-framing trap).

## Verification

Mirror Task 169's discipline (the visual/audio layer is not unit-testable in jsdom):

- **Unit:** `synthesize()` with the Gemini call mocked (text in → WAV bytes out; PCM→WAV wrap;
  bracket handling); the audio store (store/serve/evict, bounded memory); the `say` broadcast via a
  **raw-ASGI** harness (register/broadcast — not `TestClient` theater, per 169's SSE-cleanup
  lesson); synth-failure → message sent without `audio_url`.
- **jsdom (state, not sound):** the `say` message produces the focus + caption state transition;
  caption renders bracket-stripped text; close button clears it; autoplay-unlock state machine.
- **Real browser (the screenshot-pflow-web-ui skill):** with a workflow open, `pflow ui focus wf
  node --say "..."` actually plays audio and shows the caption; the autoplay unlock works (first
  clip not silently dropped); a `[excited]`-tagged line speaks expressively while the caption shows
  clean text.
- **Acceptance scenarios:** point+say focuses and narrates in an open window; zero-window reports
  honestly (169 behavior); no key configured → points + captions, "narration unavailable" in the
  report; all Task 169 server/CLI tests still pass unchanged.

## References

- **Task 169** (`.taskmaster/tasks/task_169/`): `task-169.md`, `task-review.md` (the `_Hub` /
  envelope / async-only invariant / target resolver this builds on), `implementation/progress-log.md`
  (the "human is the acknowledgment / it's a conversation" framing this makes literal).
- **Issue #529** — SSE reconnect robustness + viewer discovery (related, belongs to the 172/173
  overlay track; NOT a dependency here).
- **ADR-0007** (`context/adr/0007-169-ui-stateful-sse-channel.md`) — the stateful SSE hub + the
  vocabulary-agnostic envelope seam the `say` type rides.
- **Gemini TTS docs:** https://ai.google.dev/gemini-api/docs/speech-generation (request shape,
  `response_modalities:["AUDIO"]`, PCM16/24 kHz output, inline tags, streaming);
  https://cloud.google.com/blog/products/ai-machine-learning/gemini-3-1-flash-tts-on-google-cloud
  (model + audio tags); https://livekit.com/blog/gemini-3.1-flash-tts-prompting-guide (tag usage).
- **LiteLLM** (why NOT used for synthesis): pinned `==1.86.1`; Gemini-audio bug
  BerriAI/litellm#11118 (pcm16-only, no streaming).
