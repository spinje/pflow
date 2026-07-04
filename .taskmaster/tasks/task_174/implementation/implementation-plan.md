# Task 174 — Implementation Plan: Agent Voice Narration ("Point & Say")

Status: **ready for implementation** (all assumptions verified against code 2026-07-04; Gemini API
pinned by live call). Spec: `.taskmaster/tasks/task_174/task-174.md` (canonical — read its Design
Decisions first; they are locked). Brief: `scratchpads/task-174-voice-narration/BRIEF.md`.

**Baseline** (captured on `feat/agent-voice-narration` @ add42ffc = current main, 2026-07-04):
`make test` = **8384 passed, 0 failed**. Any delta after implementation must be explained.

This plan is written so an agent can implement it in isolation. Every "mirror X" instruction names
the exact function and line; every design call is made (no open decisions). Line numbers verified
2026-07-04 — re-check with grep if a file was touched since.

---

## 0. What you are building (one paragraph)

`pflow ui focus <wf> <target> --say "text"` (and the same on `frame`): the CLI strips `[delivery]`
tags to get the caption, synthesizes the *raw* text to WAV via a direct httpx call to Gemini TTS,
and sends ONE POST to a new `/api/say` endpoint (caption + target + base64 WAV; audio optional).
The server resolves the target exactly like `/api/command`, stores the WAV in a small in-memory
LRU, then emits TWO broadcasts on the existing SSE pipe, in order: (1) the ordinary stamped+latched
`focus`/`frame` point message — byte-identical to Task 169 semantics, so latch/replay still work —
and (2) a transient un-stamped `{"type":"say", "target", "caption", "audio_url"?}`. The frontend
`say` branch is purely additive: it anchors a persistent caption (`NodeCallout` reuse) and plays
the clip; camera/selection ride the point message that precedes it on the same ordered queue.
Synthesis failure never blocks the point: the say message goes out without `audio_url` and the
reason lands in the CLI report ("caption always, voice when it can").

### Wire contracts (locked)

- **POST `/api/say`** request: `{"workflow": str, "type": "focus"|"frame", "target": str,
  "caption": str, "audio_b64": str?}` (`audio_b64` absent ⇒ caption-only say).
- **`/api/say`** response: identical shape to `/api/command` — `{"resolved": <resolution.report()>,
  "sent_to": int, "windows": [{"visibility": str}], "workflow_key": str}` — so all existing CLI
  rendering (`_render_dispatch`, `_dispatch_failed`) works unchanged.
- **SSE say envelope**: `{"type": "say", "target": <TargetDescriptor>, "caption": str,
  "audio_url": "/api/audio/<id>"?}` — no `epoch` (transient, never latched); `audio_url` key
  omitted entirely when there is no audio. `target` is `resolution.descriptor` (the structural
  TypedDict — plain JSON-native dict, serializes as-is; never a flat `n*` id).
- **GET `/api/audio/{audio_id}`** → `200 audio/wav` bytes or `404`.
- CLI JSON output: the server payload plus a CLI-merged `"narration": {"audio": bool,
  "reason": str|null, "reason_kind": "missing_key"|"synthesis_failed"|null}` field
  (`reason_kind` lets a programmatic consumer branch without substring-matching prose —
  the discriminator pattern `exceptions.py` prescribes).

### Design calls (all made — do not re-open; rationale in one line each)

| Call | Choice |
|---|---|
| Gemini surface | `generateContent` (spec's choice, live-verified 200; Interactions API also verified 200 as documented fallback — swap lives entirely inside `synthesize()`) |
| One POST, two broadcasts | Point semantics stay byte-identical to 169 (stamp+latch+replay); `say` stays purely additive; no audio auto-replay for reconnecting windows; one target resolve |
| Dispatch report source | The **point** broadcast's conns feed `_dispatch_report` (mirrors `/api/command` exactly) |
| Audio store | Loop-only (async handlers only) `OrderedDict` LRU, `_AUDIO_STORE_MAX = 16` clips, no lock, no TTL — mirrors the hub's loop-affine lock-free spirit |
| Upload bound | `_AUDIO_MAX_BYTES = 10_000_000` decoded; oversize → 400 (server.py has NO body-size guard today — verified; this keeps the loopback worst-case benign per ADR-0007) |
| Exception | New `TTSSynthesisError(PflowError)` in `core/exceptions.py`; missing key raises existing `MissingApiKeyError` |
| `--say` length cap | `_SAY_MAX_CHARS = 1500`; over → `click.BadParameter` (no callback validators exist in the CLI — verified; use the mcp.py:98-114 in-body `BadParameter` idiom) |
| Empty-after-strip | `--say "[excited]"` (tags only) → `click.BadParameter` ("nothing would be shown or spoken") |
| Model normalization | `tts_model.removeprefix("gemini/")` before URL interpolation (settings convention uses LiteLLM-style `gemini/` prefixes — user's `default_model` is `gemini/gemini-2.5-flash-lite`) |
| Default voice | `Kore` (live-verified; docs' canonical example) |
| Envelope field | `caption` (not `caption_text`) |
| Edge targets | Caption anchors to the **target-side endpoint** node (`flatIdForRef(graph, target.target)` → `representativeFor`); focus/selection of the edge itself rides the point message |
| Stale ref in browser | Drop the caption silently (mirrors `applyPoint`'s silent return on stale refs) |
| Caption state | ONE active say-callout globally (new say replaces prior, any target); matches "new point interrupts prior clip" |
| Caption lifecycle | A bare `focus`/`frame` (no `--say`) does NOT dismiss the caption (spec-locked: "captions persist… the user dismisses"); `clear` DOES dismiss it + pauses audio (clearing the agent's marks clears its annotation); `select-run` leaves it |
| Caption anchor | `sayCallout` stores the **structural ref** (`RFRef`), never the resolved flat id — flat ids are positional and renumber on auto-update rebuild; the anchor id is re-resolved from `graph` every render (the `runAnchorId` pattern); an unresolvable ref hides the callout |
| `PointHandlers.say` | **Optional** (`say?:`), dispatched as `handlers.say?.(...)` — mirrors the additive `Partial<RunHandlers>` pattern and leaves every pre-existing `PointHandlers` test literal (`events.test.ts`, `runEvents.test.ts:39-51,217`) untouched under strict tsc |
| Never-raises seam | Enforced at BOTH ends: `synthesize()` is total (its whole post-key body wrapped — any non-`MissingApiKeyError` becomes `TTSSynthesisError`), AND `_synthesize_say` catches `except Exception` as backstop |
| Callout chrome | `title="Agent"`, no `icon`, no `subtitle`, plain-text body (`<p>` — captions are spoken words, not markdown) |
| Camera | New `frameOnMount?: boolean` prop on `NodeCallout` (default `true`; run callout unchanged); say callout passes `frameOnMount={false}` — the point message owns the camera |
| Close button | Also pauses the playing clip (dismiss = "stop talking") |
| Autoplay unlock | `audio.play()` rejection → show "▶ Play narration" button in the callout body; click plays + sets a session `unlocked` flag; doubles as replay affordance |
| Exit code | `--say` with failed synthesis still exits 0 if the point delivered (`_dispatch_failed` unchanged) |
| Narration reason | text mode: `click.echo(f"narration unavailable: {reason}", err=output_json)` — the exact `timed_out` precedent (ui.py:589-596: stderr only in JSON mode so stdout stays parseable) |

### Verified externals — Gemini TTS (pinned by LIVE call, 2026-07-04, both surfaces returned 200)

**Chosen surface — `generateContent`:**
```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
header: x-goog-api-key: <key>
body: {"contents": [{"parts": [{"text": <raw text, tags included>}]}],
       "generationConfig": {"responseModalities": ["AUDIO"],
         "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": <voice>}}}}}
response audio: candidates[0].content.parts[0].inlineData.data   (base64 PCM)
response mime:  candidates[0].content.parts[0].inlineData.mimeType == "audio/l16; rate=24000; channels=1"
```
PCM16 confirmed (sample width 2). Parse `rate=(\d+)` / `channels=(\d+)` from mimeType with
defaults 24000/1 — guards a silent pitch-shift if Google changes the rate. Fallback surface
(do NOT implement; documented for the future): `POST /v1beta/interactions` with
`{"model", "input", "response_format":{"type":"audio"}, "generation_config":{"speech_config":[{"voice"}]}}`,
audio at `steps[0].content[0].data`.

---

## Phase 1 — Core TTS (`src/pflow/core/`)

### 1a. Settings — `settings.py`
Add to `LLMSettings` (fields at :93-105), mirroring the non-null-default pattern of
`RegistrySettings.output_mode` (:32-36):
```python
tts_model: str = Field(default="gemini-3.1-flash-tts-preview", description="TTS model for `pflow ui --say` narration.")
tts_voice: str = Field(default="Kore", description="TTS voice name for `pflow ui --say` narration.")
```
No validator (open-ended values). Accessor at runtime: `SettingsManager().load().llm.tts_model`
(pattern: `llm_config.py:241`).

### 1b. Exception — `exceptions.py`
`class TTSSynthesisError(PflowError)` with a short docstring ("TTS synthesis call failed
(network, API error, or unparseable response)."). No `to_diagnostics` override needed — the CLI
catches it and reports the message; it never reaches the engine.

### 1c. New module — `src/pflow/core/tts.py`
Sibling of `llm_client.py`, NOT inside it (different dep surface — raw httpx vs LiteLLM; different
interface; keeps each module's seam small). Contents (~70 lines):

```python
def strip_delivery_tags(text: str) -> str:
    # re.sub(r"\[[^\]]*\]", "", text) then collapse runs of whitespace and strip.

def synthesize(text: str, *, model: str, voice: str, timeout: float = 30.0) -> bytes:
    # 1. Key: first non-empty os.environ.get() over PROVIDER_ENV_VARS["gemini"]
    #    (llm_config.py:28; canonical-first GEMINI_API_KEY then GOOGLE_API_KEY).
    #    None -> raise MissingApiKeyError. Message must cite the REAL command:
    #    "pflow settings set-env GEMINI_API_KEY <value>" (hyphenated `set-env` —
    #    settings.py:313; match the wording MissingApiKeyError.to_diagnostics()
    #    at exceptions.py:401-412 already uses). NOT `settings set env`.
    # 2. model = model.removeprefix("gemini/")
    # 3-7 run inside ONE try/except that converts ANY exception except
    #    MissingApiKeyError/TTSSynthesisError into TTSSynthesisError —
    #    synthesize() is TOTAL after the key check. This is load-bearing:
    #    a 200 with candidates: [] (safety filter), malformed base64,
    #    a reshaped body (KeyError/IndexError/TypeError/binascii.Error),
    #    or degenerate audio params (wave.Error) must all surface as
    #    TTSSynthesisError, never a raw traceback.
    # 3. httpx.post(<generateContent URL above>, json=<body above>,
    #    headers={"x-goog-api-key": key}, timeout=timeout).
    # 4. Non-200 / httpx.RequestError -> TTSSynthesisError with status + first ~200 chars of body.
    # 5. Extract candidates[0].content.parts[0].inlineData.data; empty candidates or
    #    missing keys -> TTSSynthesisError("no audio in response (...)"). base64.b64decode.
    # 6. Parse rate/channels from mimeType (defaults 24000/1); wrap with stdlib wave into
    #    io.BytesIO: setnchannels(channels), setsampwidth(2), setframerate(rate), writeframes(pcm).
    # 7. Return WAV bytes.
```
The Gemini request/response dict shapes are the pinned ones above — copy them exactly.

### 1d. Tests
- `tests/test_core/test_tts.py` (new): mock `httpx.post` —
  - happy path: canned generateContent JSON (build base64 from a few PCM16 frames) → returns bytes
    starting with `RIFF`, and `wave.open` reads back nchannels=1, sampwidth=2, framerate=24000;
  - mimeType `rate=48000` → framerate 48000 (the defensive parse);
  - non-200 → `TTSSynthesisError`; `httpx.ConnectError` → `TTSSynthesisError`; response missing
    `inlineData` → `TTSSynthesisError`; **`candidates: []` (safety-filtered 200) →
    `TTSSynthesisError`, NOT IndexError**; non-JSON 200 body → `TTSSynthesisError` (totality);
    no env key (patch `os.environ` clean) → `MissingApiKeyError` whose message contains
    `settings set-env`;
  - `strip_delivery_tags` table: `"[excited] hi"→"hi"`, `"a [x] b [y] c"→"a b c"`, `"no tags"`
    unchanged, `"[only]"→""`, nested-ish `"[a][b] hi"→"hi"`.
- `tests/test_core/test_settings.py`: `PflowSettings().llm.tts_model == "gemini-3.1-flash-tts-preview"`,
  `.tts_voice == "Kore"`.

---

## Phase 2 — Server (`src/pflow/ui/server.py`)

### 2a. Audio store
Constants beside `_ACTIVITY_MAX` (:90-96): `_AUDIO_STORE_MAX = 16`, `_AUDIO_MAX_BYTES = 10_000_000`.
```python
class _AudioStore:
    """Ephemeral clips for `say` narration. Loop-only like the hub (async handlers only) — lock-free."""
    def __init__(self) -> None: self._clips: OrderedDict[str, bytes] = OrderedDict()
    def put(self, data: bytes) -> str:      # uuid.uuid4().hex; evict oldest while len > _AUDIO_STORE_MAX
    def get(self, audio_id: str) -> bytes | None:   # plain read; no LRU-touch needed (clips are short-lived)
```
`uuid` is already imported (:44-84 block). Register in `create_app()` right after
`app.state.hub = _Hub()` (:1106): `app.state.audio = _AudioStore()`.

### 2b. `POST /api/say` — `async def say(request)`
Mirror `command()` (:662-725) exactly, with these deltas. Sequence:
1. `_json_body` guard (same `isinstance(body, Response)` return).
2. `workflow = _string_field(body, "workflow")`; `command_type = _string_field(body, "type")` must
   be in `{"focus", "frame"}`; `target = _string_field(body, "target")`; `caption =
   _string_field(body, "caption")`. Any missing → 400 `{"error": ...}` via `_json`, one message
   that **names the valid types inline** like `command()` does (:670-673): `"Fields 'workflow',
   'target', 'caption' and type ('focus' or 'frame') are required."`.
3. `audio_b64 = body.get("audio_b64")`; if present it must be a str that base64-decodes
   (`base64.b64decode(audio_b64, validate=True)` in try/except → 400 `{"error": "audio_b64 must be
   valid base64."}`); decoded size > `_AUDIO_MAX_BYTES` → 400 **stating both the limit and the
   actual size** (`f"Audio is {len(decoded)} bytes (max {_AUDIO_MAX_BYTES})."`). **Add `import
   base64` to the module imports (currently absent — verified).**
4. `workflow_key = _workflow_key(workflow)`; `None` → `_workflow_not_found(workflow)`.
5. `model = await asyncio.to_thread(resolve_validate_build, workflow, max_depth=_MAX_DEPTH)` with
   the same `WorkflowGraphValidationError` → 422 handler as :706-707.
6. `resolution = resolve_target(render_react_flow(model), target)`; build
   `response = {"resolved": resolution.report(), **_dispatch_report(workflow_key, [])}`; if
   `resolution.matched != 1 or resolution.descriptor is None` → return `_json(response)` (audio is
   NOT stored on a failed resolve).
7. Store audio (if any): `audio_url = f"/api/audio/{request.app.state.audio.put(decoded)}"`.
8. Two broadcasts, in this order (order is load-bearing — the browser applies the point before the
   caption):
   ```python
   conns = hub.broadcast(workflow_key, hub.set_point(workflow_key, {"type": command_type, "target": resolution.descriptor}))
   say_message: dict[str, object] = {"type": "say", "target": resolution.descriptor, "caption": caption}
   if audio_url is not None: say_message["audio_url"] = audio_url
   hub.broadcast(workflow_key, say_message)
   ```
   (`set_point` stamps the epoch internally and latches — :201-211; the say message is deliberately
   NOT stamped/latched: reconnecting windows replay the point, never stale audio.)
   **Invariant — write it as a comment beside these two calls:** the point→say per-queue ordering
   holds only because there is NO `await` between the two broadcasts (the loop can't preempt a
   synchronous block). Never insert an await between them.
9. `response.update(_dispatch_report(workflow_key, conns))`; return `_json(response)`.

### 2c. `GET /api/audio/{audio_id}` — `async def audio(request)`
```python
data = request.app.state.audio.get(request.path_params["audio_id"])
if data is None: return _json({"error": "Unknown or expired audio id."}, status_code=404)
return Response(data, media_type="audio/wav")
```
**Must be `async def`, and the comment on it must give the real reason: store affinity.** The
`_AudioStore` is lock-free ONLY because every accessor runs on the event loop (the `_Hub`
invariant, :115-120). A sync handler runs in the threadpool and would race `put`'s eviction —
do NOT justify the async with "no blocking IO" (that phrasing invites a future sync "optimization"
that introduces the race; contrast `_GIT_ROOT_CACHE` + lock at :894-895, needed precisely because
`runs` is sync). No hub access.

### 2d. Routes + security comment
Insert into the `routes` list (:1069-1084), before the `if (_STATIC_DIR / "index.html").exists():`
catch-all append (:1085):
```python
Route("/api/say", say, methods=["POST"]),
Route("/api/audio/{audio_id}", audio),
```
Extend the SECURITY comment block (:1089-1103) with two sentences: `/api/say` is mutating but its
worst cross-origin case is storing/playing benign local bytes (synthesis is CLI-side; the server
makes NO outbound call), bounded by `_AUDIO_MAX_BYTES`×`_AUDIO_STORE_MAX`; `/api/audio/<id>` joins
the `/api/source` read-exposure class. Both sit behind `_LoopbackOnly` middleware automatically.

### 2e. Tests — `tests/test_cli/test_ui_interaction_server.py`
Follow the file's existing idioms (helper `_client(app)` at :23-30 — `TestClient(app,
base_url="http://127.0.0.1")` REQUIRED or `_LoopbackOnly` 403s; direct
`app.state.hub.register(key, "visible")` + `conn.queue.get_nowait()` for envelope asserts):
- say happy path: register conn → POST `/api/say` (real tiny WAV b64) → response has
  `resolved.matched==1`, `sent_to==1`; queue yields TWO messages in order: first
  `{"type":"focus","target":...,"epoch":<int>}` (stamped), then `{"type":"say",...}` with caption +
  `audio_url` and NO `epoch` key; GET the `audio_url` → 200, `audio/wav`, bytes round-trip.
- caption-only: no `audio_b64` → say message has NO `audio_url` key.
- point latch: after a say, `hub.point_for(workflow_key)` is the focus envelope (a NEW subscriber
  replays focus but not say — assert via the events-generator pattern at :681-719 if cheap, else
  assert the latch directly).
- validation: missing caption → 400; bad base64 → 400; decoded > `_AUDIO_MAX_BYTES` (monkeypatch
  the constant small) → 400; `type: "clear"` → 400; unknown workflow → 404; ambiguous/unknown
  target → `matched != 1`, zero broadcasts, audio NOT stored.
- store: put 17 clips (patch `_AUDIO_STORE_MAX=16` or insert directly) → oldest evicted, GET old id
  → 404.
- guard regression pins: add `/api/say` to the mutating-endpoint lists in
  `test_mutating_endpoints_require_json_content_type` (:343) and
  `test_guard_also_rejects_the_existing_mutating_posts` (:544), and `/api/audio/<id>` to the
  read-endpoint host-guard list (:566).
- Do NOT use TestClient for SSE-stream behavior (169 lesson); the queue/generator patterns above
  suffice. Keepalive/existing tests must remain untouched.

---

## Phase 3 — CLI (`src/pflow/cli/commands/ui.py`)

### 3a. Constants + helpers
`_SAY_MAX_CHARS = 1500` near `_REQUEST_TIMEOUT_S` (:28). Three additions (place near
`_point_request` :362):

```python
def _prepare_say(say: str) -> str:
    """Validate --say and return the caption (tags stripped). Raises click.BadParameter."""
    # lazy: from pflow.core.tts import strip_delivery_tags
    # len(say) > _SAY_MAX_CHARS -> BadParameter(f"--say is {len(say)} chars (max {_SAY_MAX_CHARS}).", param_hint="'--say'")
    # caption = strip_delivery_tags(say); empty -> BadParameter("--say contains only [delivery] tags — nothing would be shown or spoken.", param_hint="'--say'")

def _synthesize_say(say: str) -> tuple[str | None, str | None, str | None]:
    """(audio_b64, failure_reason, reason_kind). Success: (b64, None, None). NEVER raises —
    this seam enforces the locked 'synthesis failure is a report note, never an error' decision,
    so the catch is `except Exception` (belt to synthesize()'s totality braces)."""
    # ALL imports lazy (ui.py convention + the lazy-import boundary test):
    #   from pflow.core.llm_config import inject_settings_env_vars
    #   from pflow.core.settings import SettingsManager
    #   from pflow.core.tts import synthesize
    #   from pflow.core.exceptions import MissingApiKeyError
    # inject_settings_env_vars()   # ui.py does NOT call this anywhere today — required for settings-stored keys
    # llm = SettingsManager().load().llm
    # try: return base64.b64encode(synthesize(say, model=llm.tts_model, voice=llm.tts_voice)).decode("ascii"), None, None
    # except MissingApiKeyError as exc: return None, str(exc), "missing_key"
    # except Exception as exc: return None, str(exc), "synthesis_failed"
    #   (TTSSynthesisError lands in the Exception arm; the wide catch is deliberate — a stray
    #    IndexError/wave.Error must degrade to caption-only, never crash the point.)

def _say_request(ctx, port, workflow, command_type, target, caption, audio_b64, *, output_json) -> dict[str, object]:
    # mirror _point_request (:362-379) but path="/api/say" and
    # json_body={"workflow", "type", "target", "caption"} + {"audio_b64": ...} only when not None
```
`import base64` at module level (ui.py imports are at :9-24; base64 is stdlib-light, fine).

### 3b. Wire into `focus_cmd` (:524-598) and `frame_cmd` (:601-624)
Add to BOTH: `@click.option("--say", "say", default=None, help="Narrate this text aloud in the
Viewer with an on-canvas caption. Delivery direction goes in [brackets] (e.g. \"[excited] this
node...\"); bracketed tags shape the voice and are stripped from the caption.")`.

In each command body, before the first request:
```python
caption = audio_b64 = narration_reason = narration_kind = None
if say is not None:
    caption = _prepare_say(say)                      # BadParameter propagates (usage error)
    audio_b64, narration_reason, narration_kind = _synthesize_say(say)
```
Then every `_point_request(ctx, port, workflow, <verb>, target, output_json=...)` call becomes
conditional: `_say_request(..., caption, audio_b64, ...)` when `say is not None`, else the existing
call. In `focus_cmd` that is BOTH call sites — :554 and the post-`--open`-poll re-send at :577
(re-send reuses the SAME `audio_b64`; do NOT re-synthesize). The `--open` poll flow itself
(:557-576) is untouched.

After `payload = ...` and before `_emit_payload` (:579): if `say is not None`, merge
`payload["narration"] = {"audio": audio_b64 is not None, "reason": narration_reason,
"reason_kind": narration_kind}` so JSON consumers see it. The narration note is a **top-level
statement, NOT nested inside the `if not output_json and not timed_out:` block** that guards
`_render_dispatch` (:580-588) — it must emit even when `--open` timed out AND synthesis failed:
```python
if narration_reason is not None:
    click.echo(f"narration unavailable: {narration_reason}", err=output_json)
```
(the exact `timed_out` routing precedent, :589-596: stderr only in JSON mode so stdout stays
parseable). `_dispatch_failed` (:243-247) is unchanged — synthesis failure alone never exits 1.

### 3c. Tests — `tests/test_cli/test_ui_commands.py`
Mirror `_response`/`_dispatch_payload` (:14-26) and `test_focus_dispatches_as_subcommand` (:38-50).
Patch `httpx.request` AND `pflow.core.tts.synthesize` (patch where used:
`patch("pflow.core.tts.synthesize", ...)` works since the lazy import resolves at call time).
Cases:
- `focus demo greet --say "[excited] hi"` → POST to `/api/say`; body has `caption == "hi"`,
  `audio_b64` set, `type == "focus"`; exit 0.
- synthesize raises `TTSSynthesisError("boom")` → still POSTs (no `audio_b64` key), exit 0, text
  output contains `narration unavailable: boom`; JSON mode: payload has
  `narration == {"audio": false, "reason": "boom", "reason_kind": "synthesis_failed"}` on stdout
  and the note on stderr.
- `MissingApiKeyError` path same shape with `reason_kind == "missing_key"`.
- **never-raises backstop**: synthesize raises a bare `RuntimeError` → command still POSTs and
  exits 0 with the reason in the note (the point is never dropped by a synthesis crash).
- `--say` over 1500 chars → exit ≠ 0, BadParameter message; `--say "[only-tags]"` → BadParameter.
- `frame ... --say` hits `/api/say` with `type == "frame"`.
- bare `focus`/`frame` (no `--say`) still POST `/api/command` with the unchanged body (regression).
- `--open --say`: patch `ui_module._probe_health` and `time.sleep` (tests/CLAUDE.md pitfall #21 —
  the monotonic deadline ignores a patched sleep); assert the re-send also went to `/api/say` and
  `synthesize` was called exactly ONCE.
- `inject_settings_env_vars` called on the say path (patch and assert), NOT on bare focus.
- Check the lazy-import boundary test (in `tests/test_cli/test_ui.py`) still passes — the new core
  imports are function-local.

---

## Phase 4 — Frontend (`web/`)

### 4a. `web/src/api/events.ts`
- `PointHandlers` (:6-14) gains an **OPTIONAL** member: `say?: (target: PointTarget, caption:
  string, audioUrl: string | null) => void;` — optional is load-bearing: `runEvents.test.ts`
  builds `PointHandlers` literals at :39-51 and :217 that strict `tsc` (run by `npm run build` →
  `make ui-build`) would reject if `say` were required, forcing edits to pre-existing tests.
  Optional mirrors the additive `Partial<RunHandlers>` pattern and leaves them all untouched.
- New branch in the `onmessage` chain, after the focus/frame branch (:175-176):
  ```ts
  } else if (message.type === "say" && isTarget(message.target) && typeof message.caption === "string") {
    handlers.say?.(message.target, message.caption, typeof message.audio_url === "string" ? message.audio_url : null);
  }
  ```
  No `admitEpoch` gate — say is transient and never latched/replayed (the point message that
  precedes it carries the epoch). `isTarget` (:46-58) already validates both node AND edge
  descriptors — reuse as-is.

### 4b. `web/src/components/NodeCallout.tsx`
Add `frameOnMount?: boolean` (default `true`) to the props (:22-42). Gate the one-shot effect at
:70: `if (!frameOnMount || framedRef.current || !rect) return;`. Nothing else changes; the run
callout keeps its behavior (prop unset → true). Update the header comment's Task-174 sentence to
note the say bubble passes `frameOnMount={false}`.

### 4c. `web/src/views/GraphView.tsx`
- State — **store the structural ref, never the resolved flat id** (flat ids `n{i}`/`g{j}` are
  POSITIONAL and renumber on any auto-update rebuild; `remapSelection`/`remapCollapsed` exist for
  exactly this reason, and `runAnchorId` re-derives reactively at :305-310):
  ```ts
  const [sayCallout, setSayCallout] = useState<{anchorRef: RFRef; caption: string; audioUrl: string | null} | null>(null);
  ```
  near the run-callout state (:131). Resolve the anchor id EVERY render (survives rebuilds; a
  vanished node hides the callout):
  ```ts
  const sayAnchorId = useMemo(() => {
    if (!sayCallout || !graph) return null;
    const flatId = flatIdForRef(graph, sayCallout.anchorRef);
    const node = flatId ? graph.nodes.find((n) => n.id === flatId) : undefined;
    return node ? representativeFor(node) : null;
  }, [sayCallout, graph, representativeFor]);
  ```
- Audio (one ref + two small callbacks, near the state). **The rejection handler MUST be
  currency-guarded**: `pause()` on an in-flight `play()` rejects that promise with `AbortError`
  as a microtask AFTER the new clip started — an unguarded catch flips `narrationBlocked` true
  while the new clip is audibly playing (fires exactly on rapid successive says, the headline
  demo flow):
  ```ts
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [narrationBlocked, setNarrationBlocked] = useState(false);
  const playNarration = (url: string | null) => {
    audioRef.current?.pause();
    audioRef.current = null;
    setNarrationBlocked(false);
    if (!url) return;
    const clip = new Audio(url);
    audioRef.current = clip;
    clip.play().catch(() => { if (audioRef.current === clip) setNarrationBlocked(true); });
  };
  ```
  Unlock/replay: a button rendered in the callout body when `narrationBlocked && sayCallout?.audioUrl`,
  onClick `audioRef.current?.play().then(() => setNarrationBlocked(false)).catch(() => {})` —
  the trailing catch prevents an unhandled rejection if the clip was evicted (404) or the gesture
  still doesn't satisfy the policy. The gesture unlocks the page for subsequent clips; no
  persistent flag needed beyond clearing `narrationBlocked`.
- Handler in `pointHandlers.current` (:693-705):
  ```ts
  say: (target, caption, audioUrl) => {
    if (!graph) return;
    const anchorRef = target.kind === "node" ? target.ref : target.target;  // edge: target-side endpoint
    if (!flatIdForRef(graph, anchorRef)) return;         // stale ref: drop silently (applyPoint behavior)
    setSayCallout({ anchorRef, caption, audioUrl });
    playNarration(audioUrl);
  },
  ```
  (The focus/frame message arrives first on the same SSE queue and does reveal/camera/selection —
  the say handler does neither.) **Caption lifecycle (locked)**: extend the existing `clear`
  handler (:697-700) to also dismiss — `audioRef.current?.pause(); setSayCallout(null);` — so
  `pflow ui clear-focus` clears the agent's annotation along with its point. A bare `focus`/
  `frame` deliberately does NOT dismiss the caption (spec: "captions persist… the user dismisses");
  `selectRun` leaves it too. Wire `say` into the `subscribe(...)` handler object (:717-721)
  exactly like `focus` — one delegating arrow through `pointHandlers.current`; do NOT add anything
  to the subscribe effect's deps (web/CLAUDE.md invariant).
- Render, sibling of the run callout (:959-983), inside `<ReactFlow>`:
  ```tsx
  {sayCallout && sayAnchorId && (
    <NodeCallout anchorId={sayAnchorId} direction={direction} title="Agent"
                 frameOnMount={false}
                 onClose={() => { audioRef.current?.pause(); setSayCallout(null); }}>
      <p className="say-caption">{sayCallout.caption}</p>
      {narrationBlocked && sayCallout.audioUrl && (
        <button className="say-unlock" onClick={...}>▶ Play narration</button>
      )}
    </NodeCallout>
  )}
  ```
  `direction` is the existing GraphView state (:99). Both callouts coexisting is fine — neither
  new mount frames (say: `frameOnMount={false}`; run: only frames on ITS mount). If both anchor
  the same node they stack in DOM order (say renders after run, so say sits on top) — accepted
  for v1; both have close buttons.
- CSS: `.say-caption` (margin 0, `color: var(--text)`) and `.say-unlock` in `web/src/index.css`
  beside `.node-callout*` (:2238-2303), reusing the existing tokens (`--text`, `--text-muted`,
  `--border`). Check the CANVAS-layer token grant block at index.css:66-69 covers the new classes
  (they live inside `.node-callout`, so they inherit — verify visually).

### 4d. Frontend tests
- `events.test.ts`: FakeEventSource pattern (:8-37). Emit `{type:"say", target:<valid node
  target>, caption:"hi", audio_url:"/api/audio/x"}` → `say` handler called with `(target, "hi",
  "/api/audio/x")`; emit without `audio_url` → third arg `null`; emit with bad target → not called.
  Add `say: vi.fn()` to the handler literals (:54 and siblings).
- `GraphView.test.tsx`: jsdom + `installReactFlowJsdomMocks()`; **`vi.stubGlobal("Audio", ...)`
  is REQUIRED** — jsdom has no `Audio`/`play()` (verified: no existing stub anywhere; rf-jsdom.ts
  mocks only ResizeObserver/DOMMatrix/matchMedia/getBoundingClientRect). Stub shape: a class with
  `play: vi.fn(() => Promise.resolve())` and `pause: vi.fn()`. Tests: invoke
  `live.handlers.say(...)` → callout DOM shows caption text; close button clears it and calls
  `pause`; `play` rejection (`Promise.reject(new Error("NotAllowed"))`) → unlock button appears;
  second say replaces the first caption and pauses the prior clip — AND with autoplay allowed,
  after two rapid says the unlock button is ABSENT (pins the currency guard against the stale
  `AbortError` rejection); `clear` handler dismisses the caption and pauses; stale target ref →
  no callout.
- After all web edits: `cd web && npx vitest run && npm run build` locally, then `make ui-build`
  (bundle → `src/pflow/ui/static/`; `npm run build` runs strict `tsc --noEmit` first).

---

## Phase 5 — Verification & wrap-up

1. `uv run pytest tests/test_cli/test_ui_interaction_server.py tests/test_cli/test_ui_commands.py
   tests/test_cli/test_ui.py tests/test_cli/test_ui_targets.py` — every pre-existing Task 169 test
   passes UNCHANGED (do not edit them).
2. `make test` + `make check` — compare to the 8384-passed baseline; report the exact delta
   (new tests added, 0 regressions).
3. **Real browser** (use the `screenshot-pflow-web-ui` skill): with a workflow open,
   `uv run pflow ui focus <wf> <node> --say "[excited] this is the LLM call"` → caption shows
   `this is the LLM call` (clean, no brackets) anchored at the node; audio plays (needs the user
   to confirm audibly — a screenshot can't); fresh window → unlock button appears and works;
   `--say` on an edge target anchors at the edge's target endpoint; synthesis with the key
   temporarily unset → point + caption still work, `narration unavailable: ...` in the report.
4. Collision guard (Task 164 runs in parallel): `git diff --stat` must NOT touch
   `server.py::_run_entry`, `/api/runs`, or `web/src/components/RunSelector.tsx`, and no
   `resumed_from`/attempt-chain UI anywhere.
5. Docs: update `src/pflow/cli/commands/CLAUDE.md`, `src/pflow/core/CLAUDE.md` (tts.py + exception
   row), `src/pflow/ui/CLAUDE.md` (say endpoint, audio store, security note),
   `web/src/components/CLAUDE.md` (frameOnMount), `web/CLAUDE.md` if it lists SSE verbs;
   **`docs/reference/cli/index.mdx:505-506`** (the `pflow ui focus/frame` reference lines gain
   `[--say TEXT]` — docs/CLAUDE.md policy: "new CLI flag → update the CLI reference page");
   **`src/pflow/guide/features/ui.md:41-44` — REQUIRED, not conditional** (it documents both
   verbs), and it must teach the agent-facing contract verbatim: *delivery direction goes in
   `[brackets]` (shapes the voice, stripped from the caption); everything outside brackets is
   spoken AND shown*; one line in `settings.py::llm_show` (:437-448) so `pflow settings llm show`
   surfaces `tts_model`/`tts_voice` (they already appear in the generic `settings show`);
   CHANGELOG entry.
6. Run `/deep-review` (code mode, full branch) after implementation — this change crosses four
   surfaces (~12+ files); the plan-stage review found real issues, expect the code-stage one to
   as well.
7. Offer an ADR at ship time for "TTS bypasses LiteLLM via direct httpx" (LiteLLM `==1.86.1` pin +
   BerriAI/litellm#11118) — only if the decision survived implementation.

## Recorded decisions from the plan-stage deep-review (do not re-litigate silently)
- **Caption is NOT latched/replayed** to reconnecting or late-opened windows (only the point is).
  The reviewer noted this sits in tension with the spec's "caption = always-on baseline" phrasing;
  the call: that phrasing governs the synthesis-failure branch, not reconnect replay, and 169's
  model treats a dropped connection as an honest zero. Latching caption text (without audio) is a
  clean ADDITIVE follow-up if a demo shows the gap — do not build it in v1.
- **`--open --say` stores one orphaned clip** (the zero-window first POST): benign, LRU-bounded,
  never fetched — not load-bearing, no fix needed.
- **Multiple Viewers all narrate simultaneously** — intended; one store entry, shared `audio_url`,
  consistent with how `focus` broadcasts.

## Do NOT build (locked out of v1 — spec Design Decisions)
Two-request point/audio split; streaming; standalone `pflow ui say` verb; clip caching;
cross-provider tag translation; server-side synthesis; Web Speech API; a second agent-facing tag
syntax; any `resumed_from` run-list UI (Task 164/173 territory); `NodeToolbar` or any new
positioning primitive (NodeCallout owns it).

## Known seams for the reviewer
- The say endpoint duplicates ~15 lines of `command()`'s validate/resolve scaffolding rather than
  extracting a shared helper — deliberate: two call sites with different field sets; extract only
  if a third verb-with-payload appears (one adapter = hypothetical seam, two = real).
- `_AudioStore.get` does not LRU-touch on read — clips are played once within seconds of storage;
  insertion-order eviction is sufficient. Say so in its docstring.
