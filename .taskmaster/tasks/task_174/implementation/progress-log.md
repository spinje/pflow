# Task 174 — Progress Log: Agent Voice Narration ("Point & Say")

> Implementation log. Newest entries at the bottom of each dated section.
> Plan: `implementation-plan.md` (canonical). Spec: `../task-174.md`.

---

## 2026-07-04 — Kickoff + plan re-verification (phases 1–3)

**Scope for this session:** Implement **phases 1–3 only** (Core TTS, Server, CLI), then stop for
human review. Phase 4 (frontend) and Phase 5 (verification/docs) are OUT of scope this session,
except that `make check` must be green.

### Plan anchors re-verified against current code (code is truth)

HEAD = `845a9943` ("prepeare for imp") on top of `add42ffc` — the exact commit the plan verified
against on 2026-07-04. Task 164 (`_run_entry`, `/api/runs`, `scan_traces`) has ALREADY landed on
this branch, but it did **not** shift the plan's anchors because the plan was verified at this same
state. Every cite below was checked directly:

| Plan cite | Actual | Status |
|---|---|---|
| `settings.py` `LLMSettings` fields :93-105 | `default_model` :93, `discovery_model` :98, `filtering_model` :102 | ✅ add after :105 |
| `llm_config.py` `PROVIDER_ENV_VARS` :28 | :28, gemini = `("GEMINI_API_KEY","GOOGLE_API_KEY")` canonical-first | ✅ |
| `exceptions.py` `MissingApiKeyError` | class :365; `to_diagnostics` uses `set-env` (hyphenated) :406 | ✅ `set-env` confirmed |
| `exceptions.py` `PflowError` :45 | :45 | ✅ |
| `server.py` `_ACTIVITY_MAX` neighbourhood | `_MAX_DEPTH` :90, `_ACTIVITY_MAX` :91 | ✅ constants block |
| `server.py` `command()` :662-725 | :662, `response.update` :724 | ✅ |
| `server.py` `_dispatch_report` :556 / `_string_field` :551 / `_json_body` :535 / `_json` :294 | all match | ✅ |
| `server.py` `set_point` :201 / `broadcast` :246 / `point_for` :228 | all match | ✅ |
| `server.py` routes list :1069-1084, catch-all :1085, security :1089-1103, `app.state.hub` :1106 | all match | ✅ |
| `server.py` `import base64` | ABSENT — must add | ✅ confirmed absent |
| `ui.py` `_REQUEST_TIMEOUT_S` :28 / `_point_request` :362 / `focus_cmd` :524 / `frame_cmd` :601 / `_dispatch_failed` :243 | all match | ✅ |
| `ui.py` focus re-send site :576, `timed_out` :577 | match | ✅ |
| `ui.py` `import base64` | ABSENT — must add | ✅ confirmed absent |
| `llm_config.py` `inject_settings_env_vars` :171 | :171 | ✅ |
| `test_ui_interaction_server.py` `_client()` helper, `base_url="http://127.0.0.1"` :23-30 | :23-30 | ✅ |

### Deltas from the plan text (recorded, none block implementation)

1. **`command()` accepts 4 types now, not 2.** Plan §2b quotes the error message as if the type set
   were `{"focus","frame"}` and cites `command()`'s `:670-673` message for the "names valid types
   inline" pattern. Actual `command()` handles `{"focus","frame","clear","select-run"}` (Task 175
   added `select-run`). This does not change `/api/say` — `/api/say` only accepts `{"focus","frame"}`
   per the wire contract. I mirror the *style* of the inline-valid-types message, not its verbatim text.
2. `_request`'s `json_body` param is typed `dict[str, str] | None`. `_say_request` passes only str
   values (`workflow`/`type`/`target`/`caption`/`audio_b64`), so the existing type holds — no widening.

### Settings default model note (design call to honor)

Plan §1a pins `tts_model` default = `"gemini-3.1-flash-tts-preview"` and `tts_voice` = `"Kore"`.
The 2026-06-23 braindump flagged the model id is a *preview* that may drift; the plan's own header
says the Gemini API was live-verified 2026-07-04. I follow the plan's pinned defaults verbatim
(config-driven, so a drift is a one-line settings change, not a code change).

### Baseline
`uv run pytest -q` @ `845a9943` = **8427 passed, 9 skipped** in ~82s. This is HIGHER than the plan's
cited 8384 (Task 164's tests landed on this branch before this session). 8427 is MY baseline to diff
against; the +43 vs the plan is pre-existing and not attributable to my change.

### Phase 1 — Core TTS (in progress)
- **1a settings**: added `tts_model="gemini-3.1-flash-tts-preview"` + `tts_voice="Kore"` to
  `LLMSettings` after `filtering_model`. No validator (open-ended values).
- **1b exception**: added `class TTSSynthesisError(PflowError)` after the LLM-cluster (`_derive_env
  vars_for_model` helper, before `SchemaValidationError`). `pass` body + docstring; no
  `to_diagnostics` override (CLI reads `str(exc)`).
- **1c `core/tts.py`**: `strip_delivery_tags` + `synthesize` + private helpers. Followed the pinned
  Gemini `generateContent` shapes verbatim. Totality: key check raises `MissingApiKeyError`; a single
  `try/except` after it re-raises `TTSSynthesisError` and wraps everything else. `_extract_audio`
  raises `TTSSynthesisError` (not IndexError) on empty candidates. `_parse_pcm_params` defends the
  rate/channels defaults. Imports `PROVIDER_ENV_VARS` from `llm_config` (cheap — llm_config's
  module-level imports don't pull litellm, which is lazy inside `complete()`).
- **1d tests**: `tests/test_core/test_tts.py` (happy path WAV round-trip, prefix strip, defensive
  rate parse, mime-without-rate default, non-200, ConnectError, missing inlineData, empty-candidates
  ≠ IndexError, non-JSON 200, bad base64, no-key → MissingApiKeyError with `settings set-env`,
  strip-tags table) + `TestLLMDefaults` in `test_settings.py`. **17 passed**; ruff + mypy clean.

**Phase 1 COMPLETE.**

### Phase 2 — Server (COMPLETE)
- **2a**: `import base64` + `OrderedDict` added to server imports. Constants `_AUDIO_STORE_MAX=16`,
  `_AUDIO_MAX_BYTES=10_000_000` beside `_ACTIVITY_MAX`. `class _AudioStore` (loop-only, lock-free,
  insertion-order LRU, no read-touch) after `_Hub`. Registered `app.state.audio = _AudioStore()` in
  `create_app`.
- **2b `POST /api/say`**: mirrors `command()`'s validate→resolve→broadcast; two broadcasts with the
  no-`await`-between invariant written as a comment. Point via `set_point` (stamped+latched); say
  transient (no epoch). Audio stored only after a unique resolve.
- **2c `GET /api/audio/{audio_id}`**: `async def` with the STORE-AFFINITY reason in the docstring
  (not "no blocking IO"). 404 on miss; `audio/wav` on hit.
- **2d**: routes inserted before the catch-all; security comment extended.
- **DEVIATION (justified): extracted `_decode_say_audio` helper.** The inline audio-decode/validate
  block pushed `say`'s cyclomatic complexity to 12 (ruff C901 limit is 10). Rather than suppress the
  lint, I extracted the decode+bound-check into a cohesive private helper returning
  `(bytes|None, Response|None)`. This is the *simpler final code* the directive asks for — the audio
  validation is one concern, testable in isolation, and `say` reads linearly. Not a shortcut.
- **2e tests**: added `TestSayEndpoint` (11 cases: point-then-caption ordering + audio round-trip,
  caption-only omits audio_url, point-latched/caption-not, frame verb, missing caption 400, bad
  base64 400, non-point verb 400, unknown workflow 404, oversize 400 stating limit, failed-resolve
  neither broadcasts nor stores, unknown audio id 404) + `TestAudioStore` (round-trip, eviction).
  Extended the 3 guard-list regression pins per plan §2e (`/api/say` → the two mutating lists,
  `/api/audio/<id>` → the read-endpoint host-guard list). These are inventory lists meant to cover
  EVERY endpoint — extending them is the plan's explicit instruction, not a rewrite of 169 behavior.
  **File: 54 passed** (was 43). ruff clean; mypy checks `src` only (test file untyped `monkeypatch`
  param is out of `make check` scope).

**Phase 2 COMPLETE.**

### Phase 3 — CLI (COMPLETE)
- **3a**: `import base64` + `_SAY_MAX_CHARS=1500`. Helpers `_prepare_say` (BadParameter on
  over-length / tags-only, lazy `strip_delivery_tags` import), `_synthesize_say` (never-raises seam:
  `MissingApiKeyError`→`missing_key`, `except Exception`→`synthesis_failed`; all imports lazy;
  `inject_settings_env_vars()` called), `_say_request` (POSTs `/api/say`, omits `audio_b64` when None).
- **DEVIATION (justified): two extra helpers `_resolve_narration` + `_send_point`.** The plan wrote
  the say-vs-point routing inline at 3 call sites (focus initial, focus `--open` re-send, frame) and
  the caption/synth block inline in both commands. Inlining forced a mypy narrowing problem
  (`caption: str | None` passed to `_say_request(caption: str)` inside an `if say is not None` branch
  mypy can't narrow) AND duplicated the routing 3x. `_send_point` branches on `caption is not None`
  (which mypy DOES narrow) and concentrates the routing in ONE place — the deeper, simpler final code
  the directive asks for, and it makes "the `--open` re-send reuses the same audio, never
  re-synthesizes" a structural guarantee (one synth call at the top). `_resolve_narration` folds the
  prepare+synthesize block. Net: each command body stays linear. This IS the plan's behavior, folded.
- **3b**: shared `_say_option` decorator applied to both `focus_cmd`/`frame_cmd` (identical help text,
  DRY). Narration field merged into payload before `_emit_payload` (JSON consumers see it); the
  `narration unavailable: …` note is a top-level statement after (`err=output_json`), never gated by
  the timed_out/text block — emits even when `--open` timed out AND synthesis failed. `_dispatch_failed`
  untouched (synthesis failure alone never exits 1).
- **3c tests**: `TestSayNarration` (12 cases: stripped caption + audio POST, frame verb, synth-failure
  caption-only text-mode, JSON-mode stdout/stderr split, missing-key reason_kind, bare-RuntimeError
  backstop, over-length rejected pre-request, tags-only rejected, bare focus/frame regression to
  `/api/command`, `--open --say` re-sends to `/api/say` + synthesizes ONCE, inject called on say path
  only). **42 passed** in the file.
- **Fixed a real test-ordering bug (pitfall #21):** `test_ui.py:1133` pops `pflow.ui.server` from
  sys.modules + re-imports, so `monkeypatch("pflow.ui.server._AUDIO_MAX_BYTES", 4)` targeted a fresh
  module while the handler ran the original. Switched the oversize test to
  `patch.dict(create_app.__globals__, {"_AUDIO_MAX_BYTES": 4})` — the namespace the running closure
  reads. Verified green in both file orderings (166 / 108 passed).

**Phase 3 COMPLETE.**

---

## 2026-07-04 — Phases 1–3 done; STOP for human review

### Result
- `make check`: **GREEN** (pre-commit incl. ruff/ruff-format, mypy 244 files, deptry — no issues).
- `make test` / full `uv run pytest`: **8469 passed, 9 skipped** vs baseline **8427 passed, 9 skipped**
  = **+42 new tests, 0 regressions, 0 new skips**. (+42 = 16 tts + 1 settings + 13 server + 12 CLI.)
- Collision guard (Phase 5.4): `git diff` touches NONE of `server.py::_run_entry`, `/api/runs`,
  `RunSelector.tsx`, or any `resumed_from` — verified by grep. `web/` untouched.
- Real-process smoke (no mocks): `--say` appears on `focus` + `frame --help`; `strip_delivery_tags`
  and the no-key → `MissingApiKeyError("…settings set-env…")` path both behave; settings defaults
  load as `gemini-3.1-flash-tts-preview` / `Kore`.

### What was built (phases 1–3)
- **Core** (`core/tts.py`, `settings.py`, `exceptions.py`): `synthesize()` (direct httpx Gemini
  generateContent → PCM16 → WAV), `strip_delivery_tags()`, `TTSSynthesisError`, `tts_model`/
  `tts_voice` settings. Totality after the key check is enforced.
- **Server** (`ui/server.py`): `_AudioStore` (loop-only LRU), `POST /api/say` (point+caption two
  broadcasts, no-await-between invariant), `GET /api/audio/{id}`, routes + security comment.
- **CLI** (`cli/commands/ui.py`): `--say` on `focus`/`frame`; CLI-side synth via the never-raises
  `_synthesize_say`; `/api/say` upload; narration report field + `narration unavailable:` note.

### Key learnings / insights
- The plan's line anchors were accurate to the letter (verified at the exact commit it targeted);
  Task 164 had already landed but did not disturb them. No plan-vs-code deltas blocked work — only
  the two recorded above (`command()` now has 4 verb types; `_request.json_body` already str-typed).
- **The one real bug found was in a test, not the code:** `test_ui.py:1133` pops `pflow.ui.server`
  from `sys.modules` and re-imports, so the naive `monkeypatch("pflow.ui.server._AUDIO_MAX_BYTES")`
  hit a fresh module object while the handler ran the original (tests/CLAUDE.md pitfall #21). Fixed
  with `patch.dict(create_app.__globals__, …)`. This only surfaced because pflow runs tests in a
  fixed multi-file order — worth remembering for any future module-constant patch in the ui tests.

### Deviations from the plan (with reasons — none defer scope)
1. **Extracted `_decode_say_audio` (server).** Inlining the audio decode/validate pushed `say` over
   ruff's C901 complexity limit (12>10). Extraction is the simpler final code, not a lint dodge.
2. **Added `_send_point` + `_resolve_narration` (CLI).** The plan inlined the say-vs-point routing at
   3 sites; inlining also created a real mypy narrowing gap (`caption: str|None` into a `str` param).
   `_send_point` branches on `caption is not None` (mypy narrows it) and makes "one synth, re-send
   reuses audio" structural. Same behavior, folded behind a smaller interface — the directive's ask.
Both are pure structural folds of the plan's own behavior; nothing was skipped or deferred.

### NOT done this session (out of scope — for human review / next session)
- **Phase 4 (frontend `web/`)** — events.ts `say` branch, NodeCallout `frameOnMount`, GraphView
  say-callout + audio playback + autoplay unlock, frontend tests, `make ui-build`. Untouched.
- **Phase 5 (docs + real-browser + deep-review)** — CLAUDE.md updates, `docs/reference/cli`,
  `guide/features/ui.md`, `settings llm show` line, CHANGELOG, the real-browser audible check, and
  the code-mode `/deep-review`. Not started.

### Live Gemini verification (2026-07-04, user-authorized spend, ~$0.003 total)
Ran a real 2-call probe through the SHIPPED `synthesize()` (not a separate probe) via the CLI's
`inject_settings_env_vars()` → settings-key path. **Core is now verified against reality, not just mocks:**
- `gemini-3.1-flash-tts-preview` resolves → **HTTP 200** (the pinned preview id is still valid).
- Response shape is **EXACT** to the plan: `candidates[0].content.parts[0].inlineData.data` +
  `inlineData.mimeType == "audio/l16; rate=24000; channels=1"`; top-level keys
  `['candidates','modelVersion','responseId','usageMetadata']`.
- `synthesize()` produced a valid WAV: `RIFF` header, **channels=1, sampwidth=2 (PCM16), rate=24000**,
  64320 frames (~2.7s for a ~30-char line). PCM byte count = frames×2 = header-stripped WAV size ✓.
This closes the "core never touched the real API" residual risk. (Two calls returned slightly
different frame counts — expected TTS non-determinism, each WAV internally consistent.)

### 2026-07-04 — Loose-ends pass (post-review, user-authorized live spend)

**Resolved the braindump's NEEDS-VERIFICATION on the 30s timeout with real measurements** (2 more
live probes, still well under budget):

| input | gen wall-time | audio | ratio |
|---|---|---|---|
| 35 chars (typical point-and-say) | 3.0s | 3.2s | 0.94x |
| 121 chars | 6.2s | 7.7s | 0.80x |
| 253 chars (short paragraph) | 10.6s | 15.4s | 0.69x |
| ~1480 chars (near the 1500 cap) | **>120s (timed out)** | — | — |

**Decision — KEEP the 30s default + 1500 cap (deviates from the braindump's "bump the timeout"
advice, with cause).** The braindump assumed generation is faster-than-realtime at ALL sizes and so
advised bumping the timeout rather than shrinking the cap. The data disproves the premise: realistic
`--say` (one sentence to a short paragraph, ≤~250 chars) synthesizes in 3–11s — 30s gives 3–10x
margin — but a near-cap 1480-char input exceeds even 120s. Bumping the default to *cover* 1500 chars
would block the agent's point for 1–2+ minutes on the critical path (single-request design), which is
strictly worse than degrading. So: 30s bounds the wait and covers the real use case; a pathological
runaway input degrades to caption-only (NOT silently — the CLI prints "narration unavailable"). This
is a reversible, low-stakes call the braindump explicitly delegated to the implementer; flagged for
the reviewer to override if they disagree. (The `_SAY_MAX_CHARS=1500` cap stays a runaway-typo guard,
not a target length — per the locked spec.)

**Fixes applied this pass:**
1. **Actionable timeout message (`tts.py`).** Added an explicit `except httpx.TimeoutException` arm
   before the generic catch, producing `"TTS synthesis timed out after 30s — the text may be too long
   to narrate."` instead of the raw `"...The read operation timed out"`. A timeout has a distinct
   remedy (shorten the text) vs a network error, so an agent gets an actionable note. +1 test.
2. **Empty-caption message (`ui.py`).** `_prepare_say` now says `"--say has no speakable text — it is
   empty or only [delivery] tags…"` — accurate for BOTH `--say ""` (empty variable) and tags-only,
   where the old "contains only [delivery] tags" would send an agent hunting for absent tags. +1 test
   (empty `--say ""` rejected pre-request); the tags-only test's assertion still holds (substring).
3. **Defensive `PROVIDER_ENV_VARS.get("gemini", [])`** in `_gemini_api_key()` (runs before the
   totality wrapper; mirrors `llm_config._has_provider_key`). No behavior change today (gemini is
   always registered) — removes a theoretical raw-KeyError path.

**Considered and deliberately NOT changed** (avoiding busywork / respecting locked decisions):
- `narration.audio: true` on a failed resolve — correct per the plan's field contract (`audio` =
  "synthesis succeeded"; delivery is reported by `resolved`/`sent_to`). Two orthogonal axes; keeping
  them separate preserves information. No change.
- Shared `_say_option` decorator — confirmed safe: `click.option(...)` creates a fresh `Option`
  per application (inside its returned decorator), so focus/frame don't share Option state. No change.
- Edge-target `--say` server test — redundant: the `say` handler relays `resolution.descriptor`
  opaquely (identical path for node/edge), and edge resolution is already covered by
  `test_ui_targets.py`. Testing it here would test the framework, not my code. No change.
- Single-request synthesis blocking `focus` for a few seconds — a locked spec tradeoff, not a bug.

### 2026-07-04 — Test-depth review ("passing the right thing")

Stepped back and audited every new test for depth (not coverage). Conclusion: the suite is deep — it
pins the real invariants (totality/never-drop-the-point, the raw-synth/stripped-caption contract,
caption-still-sent-on-failure, no-orphan-audio-on-bad-target, reuse-audio-once on `--open`,
stdout-parseable JSON, the reason_kind discriminator). Found **one test whose name over-claimed its
assertion** and deepened it; found no shallow/misleading tests to remove.

**Deepened `test_say_latches_the_point_but_not_the_caption` → `test_say_point_is_replayed_to_a_
reconnecting_window_but_the_caption_is_not`.** The old test only asserted `hub.point_for(key) ==
focus` (the latch). The plan's most-debated deep-review decision is "the caption is NOT
latched/replayed to reconnecting/late windows" — so the RIGHT test drives the real `events()` replay
(reusing the existing `test_events_replays_the_latched_point_to_a_new_connection` technique) and
proves a reconnecting window receives `connected → run-snapshot → focus(point)` and NEVER the say /
caption / audio_url. This is the demo-critical scenario (presenter's tab backgrounded during a say,
reopens). **Mutation-verified (pitfall #19):** temporarily latching the say (`hub.broadcast(k,
hub.set_point(k, say_message))`) makes the test FAIL (the replayed frame becomes the caption) —
proving it's not vacuous. Reverted the mutation.

**Considered and declined (with reasons, not laziness):**
- A concurrency test for the "no `await` between the two broadcasts" invariant — would need two
  overlapping `say()` coroutines and is inherently FLAKY (the interleave only manifests if the loop
  context-switches at the exact await, which it may not deterministically). A flaky test gives false
  confidence; the invariant stays protected by the load-bearing comment + code review. The
  single-say ordering IS tested (queue yields point-then-say).
- A full CLI→server→GET WAV round-trip integration test — each seam is already proven (tts unit +
  live probe for synth→WAV; server unit for b64→store→GET→bytes), they compose over opaque bytes,
  and a subprocess test would be heavy for no new failure mode.
- A 2-viewer fan-out test — inherited from `hub.broadcast` (already tested for `command()`); the say
  uses the same broadcast, so it'd re-test the framework.

**⚠️ Process near-miss (recorded for honesty):** while mutation-testing I used `git checkout
src/pflow/ui/server.py` to revert the mutation — which ALSO wiped my *uncommitted* Phase 2 server
work. Caught it immediately (a system reminder showed the constants missing), restored every piece
from history, and re-verified: `grep` counts match, ruff+mypy clean, 54 server tests pass, full
`make check` green, full suite **8471 passed / 9 skipped**. **Lesson: never `git checkout <file>` to
undo an edit on a file with uncommitted changes — use Edit to revert the specific mutation instead.**

Net test delta this pass: 0 (one test replaced by a strictly-stronger one). Suite: **8471 passed**.

---

## 2026-07-04 — Session 2 kickoff: phases 4–5 (frontend + verification/docs)

**Scope:** Phase 4 (frontend `web/`) + Phase 5 (verification, docs, deep-review), then STOP for
human review. No commits.

### Plan anchors re-verified for Phase 4 (code is truth; all read directly)

| Plan cite | Actual | Status |
|---|---|---|
| `events.ts` `PointHandlers` :6-14 / `isTarget` :46-58 / focus-frame branch :175-176 | all match | ✅ |
| `NodeCallout.tsx` props :22-42 / one-shot frame effect :70 | match | ✅ |
| `GraphView.tsx` `direction` :99 / run-callout state :131 / `runAnchorId` :305-310 / `pointHandlers.current` :693-705 / clear :697-700 / subscribe handlers :717-721 / run-callout render :959-983 | all match | ✅ |
| `index.css` CANVAS-token grant :66-69 (`.node-callout` in list) / `.node-callout*` block :2238-2303 | match | ✅ |
| `events.test.ts` FakeEventSource :8-37, handler literal :54 | match | ✅ |
| `GraphView.test.tsx` `live.handlers` mock :22-32, Point tests :776-845 | match | ✅ |

### Deltas from plan text (recorded; none block)

1. **`runEvents.test.ts` lives at `web/src/api/`, not `web/src/views/`** (plan cites
   "runEvents.test.ts:39-51,217"). The literals are at :38-51 (handler factory) and :217 (inline
   Point-only literal). Substance unchanged: `say?` optional keeps them compiling untouched.
2. **`sayAnchorId` placement:** the plan sketches it "near the run-callout state (:131)", but it
   depends on `representativeFor`, defined at :616. The state lives with the other state; the memo +
   audio callbacks sit after `representativeFor` (still before `applyPoint`). Ordering constraint,
   not a design change.
3. **Plan-internal tension resolved:** §4a says optional `say?` "leaves every pre-existing
   PointHandlers test literal (`events.test.ts`, …) untouched", while §4d says "add `say: vi.fn()`
   to the handler literals (:54 and siblings)". Read: §4a is the compile-time guarantee; §4d's
   intent is that the NEW say tests have a say mock. I add a new describe block with its own
   handlers factory (including `say`) and leave all pre-existing literals untouched — satisfies
   both clauses.

### Baseline for this session
Suite at session start = **8471 passed / 9 skipped** (end of session 1). `web/` baseline (fresh
`npm ci` — node_modules was absent in this worktree): **694 passed / 51 files**.

### Phase 4 — Frontend (COMPLETE)
- **4a `events.ts`**: `say?` optional member on `PointHandlers` (additive, run-handlers pattern);
  `say` branch after focus/frame — validated by the existing `isTarget` (covers node AND edge
  descriptors), NO `admitEpoch` gate (transient, never latched), `audio_url` non-string → `null`.
- **4b `NodeCallout.tsx`**: `frameOnMount?: boolean` (default `true`) gating the one-shot frame
  effect; header comment updated. Run callout behavior unchanged (prop unset).
- **4c `GraphView.tsx`**: `sayCallout` state stores the STRUCTURAL `RFRef` (never a flat id);
  `sayAnchorId` re-resolved from `graph` every render (placed after `representativeFor` — its
  dependency; the plan sketched it "near :131" but that's above the definition, ordering only);
  `playNarration` with the currency-guarded `.catch` (`audioRef.current === clip`);
  `narrationBlocked` + "▶ Play narration" unlock/replay button (trailing catch); say handler in
  `pointHandlers.current` (edge → target-side endpoint, stale ref drops silently); `clear` extended
  to dismiss + pause; `say` wired into `subscribe(...)` as a delegating arrow (deps untouched);
  render sibling of the run callout with `frameOnMount={false}`, `title="Agent"`, plain `<p>`.
- **DEVIATION (justified): folded the dismiss into ONE `dismissSay` callback.** The plan writes
  `audioRef.current?.pause(); setSayCallout(null);` inline at BOTH the clear handler and the
  callout `onClose`. Two identical multi-statement sites = drift risk; one named callback states
  the locked semantics ("dismiss = stop talking") once. Same behavior, folded.
- **CSS**: `.say-caption` + `.say-unlock` beside the `.node-callout*` block; they live inside
  `.node-callout`, which is already in the CANVAS-layer token-grant list (:66-69) → tokens inherit.
- **4d tests**: `events.test.ts` +6 (dispatch with url / null-url coercion / malformed drops /
  transient-not-epoch-gated + no baseline bump / edge-target / handler-absent back-compat — all in
  a NEW describe with its own say-mock factory; pre-existing literals untouched per §4a).
  `GraphView.test.tsx` +8 (caption+clip start, caption-only no clip, edge-target anchor, close
  dismisses+pauses, blocked→unlock→replay clears, second-say replaces + pauses prior + **currency
  guard pinned** (stale AbortError after two rapid says → unlock stays absent), clear dismisses /
  bare focus does NOT, stale ref drops). FakeAudio stub returns a FRESH promise per `play()` call
  (the real HTMLMediaElement contract — a shared per-instance deferred made the replay test
  wrongly see the old rejection).

**Discoveries while testing (real deltas, recorded):**
1. **`NodeCallout` could never render in jsdom** — the no-op ResizeObserver means RF never sets
   `measured` on any node, so the callout returns null forever (this is why NO existing GraphView
   test asserts run-callout DOM). Fixed in scaffolding, not production: extended the file's existing
   `useReactFlow` partial mock to backfill nominal `measured` dims in `getInternalNode`. This made
   the run callout render in pre-existing tests too (see 2/3).
2. **Pre-existing test edit (query-tightening only):** "re-picking the already-pinned run" clicked
   `findByTitle("r1")` — now ambiguous because the `?run=` deep-link's run callout ALSO renders
   (its subtitle carries `title="r1"`). Filtered to the `role="menuitem"` match. Assertions
   unchanged; forced by the scaffolding improvement, not by production changes.
3. **URL leak between tests:** launch tests leak `?run=<id>` into the URL via the component's own
   `syncUrl` (a known file quirk, commented at the density test) — with (1), that opened the RUN
   callout inside my say tests. My describe's beforeEach resets the URL to "/".

**Verification:** `npx tsc --noEmit` clean; `npx vitest run` = **708 passed / 51 files** (baseline
694, **+14, 0 regressions**); `npm run build` green (strict tsc + vite; chunk-size warning
pre-existing); `make ui-build` → bundle regenerated into `src/pflow/ui/static/`.

### Phase 5 — Verification, docs (COMPLETE except deep-review at time of this entry)

- **5.1** `pytest test_ui_interaction_server.py test_ui_commands.py test_ui.py test_ui_targets.py`
  = **167 passed**, zero pre-existing Task 169 tests edited.
- **5.2** Full `uv run pytest -q` = **8471 passed / 9 skipped** — byte-identical to the phase-3
  baseline (Phase 4 is web-only; its +14 tests are vitest). `make check` fully green after every
  edit (ruff, ruff-format, mypy 244 files, deptry, MDX checks).
- **5.3 Real browser (screenshot-pflow-web-ui MCP Chrome + a purpose-built scratchpad workflow
  `say-verify.pflow.md`: open → settle → run the REAL CLI --say → assert DOM → screenshot):**
  - Node target: `focus classify --say "[excited] this is where..."` → caption shows the CLEAN
    stripped text, callout title "Agent", anchored above the node (LR), point focus + ReadPanel
    ride the preceding focus message. `passed: true`.
  - **Audio played end-to-end**: headless Chrome permits autoplay; `play()` resolved (no unlock
    button), which requires the real synthesized WAV served from `/api/audio/<id>` — the full
    CLI-synth → upload → store → fetch → play chain ran against the live Gemini API.
  - Edge target: `frame "fetch-data.stdout -> classify.data" --say ...` → caption anchors at the
    TARGET-side endpoint (classify), both endpoints framed. (First attempt with the unqualified
    address exercised the did-you-mean resolver — worked.)
  - Synthesis failure: invalid `GEMINI_API_KEY` → point + caption still land, exit 0,
    `narration unavailable: Gemini TTS returned HTTP 400: ... API key not valid ...` in the report.
  - A stale pre-174 server on :8765 answered 405 on `/api/say` (static-mount fallthrough) —
    killed + restarted from this worktree. Worth remembering: a lingering old server makes the
    feature look absent.
  - **NOT verifiable here:** the autoplay-BLOCKED → unlock flow (headless Chrome allows autoplay;
    the braindump predicted this) — pinned by jsdom tests instead; and the audible check (a
    screenshot can't hear) — both handed to the user.
- **5.4 Collision guard**: `git diff 845a9943` (full task diff) touches NONE of
  `server.py::_run_entry`, `/api/runs`, `RunSelector.tsx`, `resumed_from`. Verified by grep.
- **5.5 Docs**: `docs/reference/cli/index.mdx` (both verb lines gain `[--say TEXT]` + a --say
  paragraph), `src/pflow/guide/features/ui.md` (verb lines + the agent-facing contract verbatim:
  delivery in `[brackets]`, everything outside is spoken AND shown), `settings.py::llm_show`
  (+2 lines, pinned in `test_settings_cli.py`), `src/pflow/core/CLAUDE.md` (tts.py module row +
  section, `TTSSynthesisError` in tree + usage table), `src/pflow/cli/commands/CLAUDE.md` (ui.py
  row), `src/pflow/ui/CLAUDE.md` (say/audio endpoints + store + security note),
  `web/CLAUDE.md` (SSE verb list + say semantics), `web/src/components/CLAUDE.md` (NodeCallout —
  which Task 175 never documented there — + `frameOnMount`).
- **DEVIATION (justified): no CHANGELOG edit.** The plan lists "CHANGELOG entry", but this repo's
  CHANGELOG is machine-generated at release time by the release skill ("prepended with the new
  version section"; git history shows CHANGELOG.md only ever changes in version-bump commits —
  there is no Unreleased section). A hand-added section now would be clobbered/duplicated by the
  next release run. The release process will pick this task up from its task files/PR.

### Phase 5.6 — Code-mode deep-review (4 agents) + fixes

Deployed `review-silent-failures`, `review-feature-interactions`, `review-impact-completeness`,
`review-concurrency-safety` over the full branch diff (`git diff 845a9943`), each pointed at the
plan's locked-decisions section (no re-litigation occurred). `review-test-fidelity` was passed
over because session 1 already ran a dedicated test-depth audit; the risk mass sat in the four
chosen lenses.

**Findings: 2 confirmed (both fixed), 0 critical, 0 disputed.**
1. **CONFIRMED + FIXED — no unmount cleanup for the playing clip** (found independently by
   concurrency-safety AND silent-failures). `new Audio()` is a detached object, not DOM — React
   unmount doesn't stop it, so Back-to-catalog / workflow-switch mid-narration left the voice
   playing, unstoppable (the demo path!). Fix: `useEffect(() => () => audioRef.current?.pause(), [])`
   in GraphView + a jsdom test ("unmounting the view pauses a playing clip"). Web suite → **709**.
2. **CONFIRMED + FIXED — two stale settings-doc consumers** (impact-completeness). My `llm_show`
   change added two output lines, but `docs/reference/cli/settings.mdx` transcribes that command's
   LITERAL output, and `docs/reference/configuration.mdx` tables the `llm.*` fields — both missed
   by the plan's Phase 5.5 doc list. Added `tts_model`/`tts_voice` to both.

**Suggestions declined (with cause):**
- "Partial bracket-stripping is silent" — that IS the locked semantics ("everything outside
  brackets is spoken AND shown"), now taught verbatim in the guide. No change.
- "Synthesize before checking server reachability wastes a call when the server is down" — real
  but tiny (one ~$0.003 call + ~3s), and a pre-flight health probe adds a request to every
  successful say to optimize the failure case. Not plan-sanctioned; declined for v1.

**Verified clean by the battery** (each agent's no-finding dimensions recorded): _AudioStore loop
affinity holds (the sole `put` runs post-`to_thread`-resume ON the loop); no `await` between the
two broadcasts, ordering holds even under concurrent says (pairs interleave, never split); no
stale-closure in the say handler; currency guard correct; say×{latch/replay, epoch/boot_id fence,
#539 hidden tab, 173 run-callout camera, 175 select-run, live-reload renumber, --open re-send,
edge anchors, loopback+content-type guards, multi-window} all handled AND named-tested; every
PointHandlers/guard-inventory/doc consumer updated; no MCP parity gap (point verbs are CLI-only
by 169 design); engine/batch/loop/caching untouched by design.

**Post-fix verification:** `npx vitest run` = **709 passed** (+1), `npm run build` + `make ui-build`
green (bundle regenerated), full `make check` green.

### 2026-07-04 — Session 2 addendum: closed the cheap real-browser gaps

After the wrap-up the reviewer asked whether the frontend browser verification was complete
(it was thinner than the backend). First established the load-bearing fact I'd assumed: **this
session has NO direct chrome-devtools MCP access** (only WebFetch + the Google MCP servers) —
the chrome-devtools server is wired into pflow as `mcp-chrome-devtools-*` nodes, so browser
driving MUST go through a pflow workflow (a driver-script/interactive-MCP alternative was
eliminated, not just skipped). Within that constraint the simplest tool was ONE self-contained,
hardcoded scratchpad workflow (`say-sequence.pflow.md`) — no inputs and no `${...}` in the
assertion JS (avoids the pflow-template↔JS-template-literal collision that a parameterized
generic would hit), linear named steps, poll-with-deadline asserts.

Three previously jsdom-only behaviors now confirmed against the REAL browser + real CLI pushes:
- **Say REPLACEMENT** — `focus classify --say "…"` then `focus done --say "…"` on one persistent
  page: caption became the second text, moved to the `done` node, `callout_count == 1` and
  `caption_count == 1` (replaced, NOT stacked). Screenshot `say-seq-replaced.png`.
- **clear-dismiss** — `clear-focus` after a say: `.say-caption` gone from the DOM, focus ring
  cleared. Screenshot `say-seq-dismissed.png`. Confirms the locked "clear dismisses the caption".
- **Collapsed/nested target** — `focus extract --say "…"` on deep-research with `collapse=all`:
  caption rendered (DOM-authoritative — `NodeCallout` returns null on an unresolved/unmeasured
  anchor, so `.say-caption` existing proves `sayAnchorId`→`representativeFor` resolved the buried
  node) and the ReadPanel showed the nested `extract` (`analyze-source.pflow.md:22`), proving the
  point revealed the collapsed sub-workflow. Caveat: the auto-framed screenshot didn't CENTER the
  caption — a Task-169 point-camera nuance for deep collapsed→revealed targets (frameOnMount=false
  means the point owns the camera), NOT a 174 defect; resolution is what 174 adds and it works.

**Still user-only (unchanged):** the audible check (a screenshot can't hear) and the
autoplay-BLOCKED→unlock flow (headless Chrome allows autoplay, so the block never triggers;
jsdom pins that logic). No code changed this addendum — verification only.

### What to verify manually (when resuming / reviewing)
- ~~The wire contract is exercised only within-process~~ **RESOLVED 2026-07-04 session 2:** the
  full chain ran against a live browser + live Gemini (Phase 5.3 above). Still user-only:
  **the audible check** (a screenshot can't hear — the WAV round-tripped and `play()` resolved,
  but a human confirming sound is the last mile) and **the autoplay-unlock flow in a fresh
  non-headless window** (headless Chrome allows autoplay; jsdom pins the logic).
- The default `tts_model` (`gemini-3.1-flash-tts-preview`) is the plan's pinned preview id; confirm
  it still resolves at demo time (config-driven, so a drift is a one-line settings change).
  (Re-confirmed live 2026-07-04 session 2 — HTTP 200 through the shipped path.)

---

## 2026-07-04 — Session 2 wrap-up: phases 4–5 DONE; STOP for human review

**Result:** Task 174 fully implemented. Python **8471 passed / 9 skipped** (identical to the
phase-3 baseline — phase 4 is web-only), web **709 passed** (baseline 694; +15), strict tsc +
`npm run build` + `make ui-build` + full `make check` all green. Deep-review ran (4 agents),
2 confirmed findings, both fixed same-session. NOT committed (project rule).

**Key learnings / insights (session 2):**
- **jsdom can't mount `NodeCallout` naturally** — RF never measures nodes under a no-op
  ResizeObserver, so the callout returns null forever; this is WHY no prior test asserted
  run-callout DOM. The `getInternalNode` measured-backfill in the existing `useReactFlow` partial
  mock unlocks callout testing for all future work (run callout included).
- **The component leaks `?run=` into the URL across tests** via its own `syncUrl` (a known quirk
  commented in the test file) — combined with the backfill, that opened the RUN callout inside
  unrelated tests. URL hygiene in a describe's beforeEach is the cure.
- **`HTMLMediaElement.play()` mints a NEW promise per call** — a per-instance shared deferred in
  the Audio stub silently makes replay tests assert against the old rejection. Stub per-call.
- **A lingering pre-feature `pflow ui` server answers 405 on new endpoints** (static-mount
  fallthrough) — looks exactly like "the feature isn't there". Kill + restart before browser
  verification.
- The deep-review earned its cost: two agents independently found the ONE real runtime gap
  (unmount doesn't stop a detached `Audio` object — invisible to every existing test dimension),
  and the impact lens caught doc surfaces the plan's own checklist missed.

**Deviations from plan (session 2, all recorded in-place above):** `dismissSay` fold (two
identical inline sites → one named callback); no CHANGELOG edit (machine-generated at release —
a hand-added section would be clobbered); test-scaffolding additions (measured backfill, one
query-tightening in a pre-existing test forced by it); `review-test-fidelity` swapped for
`review-concurrency-safety` in the battery (test-depth audit already done in session 1).

**For the reviewer / next session:** the audible check + fresh-window autoplay-unlock are the
only unverified behaviors (user's ears + a non-headless window needed). Phase 5.7's offer stands:
an ADR for "TTS bypasses LiteLLM via direct httpx" — the decision survived implementation
unchanged (LiteLLM pin `==1.86.1` + BerriAI/litellm#11118), so it qualifies; ask the user.

---

# FOLLOW-UP: Narration Pacing + Persistent Replayable Captions

> Distinct unit of work (plan: `follow-up-plan-narration-pacing-and-persistence.md`; handoff:
> `../starting-context/braindump-2026-07-04-follow-up-implementer-handoff.md`). Base: the
> committed 174 v1 (`c1063ef0`). Both plan decisions pre-ratified by the user; the plan's two
> v1 reopenings (interrupt model, single caption) are sanctioned and recorded there.

## 2026-07-04 — Follow-up session: Changes A + B + C (COMPLETE)

**Baseline** (verified at session start, on committed v1): Python **8471 passed / 9 skipped**;
web **709 passed**. Braindump's NEEDS-VERIFICATION resolved before coding: the CLI say tests
mock `synthesize` with `b"WAV"`-style bytes → `wav_duration` (total) returns `0.0` → the sleep
gate is falsy → **block-by-default adds zero wall-clock to the suite** (confirmed by grep, then
by the green run).

### Plan amendment (raised with the user pre-implementation; approved)

Stress-testing the plan's Change-B sketches found **two state-transition defects**:
1. `playNarration`'s playing→done sweep flips its OWN just-set box to `done` (both functional
   updaters compose in order), so a playing box would show a Replay button.
2. `replay` had no sweep at all, so replaying box B while box A plays left A stuck `"playing"`
   forever (no Replay button — contradicting "interrupted = replayable, not lost").

**Fix — one fold:** `playNarration` + `replay` merged into a single `startClip(key, url,
failStatus)` (they were ~90% identical); the sweep excludes `key`, the function owns the key's
own status, and `failStatus` carries the one legitimate difference (`"blocked"` for the initial
autoplay-policy rejection vs `"expired"` for a replay rejection — a user-gesture replay can't be
policy-blocked, so its rejection means LRU-evicted). Both defects are structurally impossible in
the folded form. **Mutation-verified (pitfall #19):** re-introducing the plan's original sketch
order fails 5 tests; removing the sweep fails 2 (the two new pins below). Reverted.

### Change A — CLI pacing (Python)
- `core/tts.py`: `wav_duration(wav) -> float`, TOTAL (0.0 on any unparseable input).
- `cli/commands/ui.py`: `Narration` NamedTuple (folds the 4-tuple + the narration-report dict
  duplicated in both commands; `duration_s` added to the report, `null` without audio);
  `--no-wait` (`wait` flag, default block) on `focus`/`frame`; `_pace_narration(payload, n,
  wait=)` sleeps `duration_s` as the LAST statement of each command (after all reporting and the
  `_dispatch_failed` exit check), gated on audio present + point delivered + `--no-wait` absent.
  **DEVIATION (structural only):** the plan inlined the sleep in both commands; `_pace_narration`
  is the same 2-line gate in one place (the `_send_point` precedent).
- Tests: +3 `wav_duration` (real 1s WAV == 1.0 exactly; garbage/empty → 0.0); +6 pacing
  (`TestSayPacing`: sleeps exactly the clip duration + `duration_s` in JSON; frame paces too;
  `--no-wait` skips; synth-failure skips; 0-window skips (exit 1 unchanged); `--open --say`
  paces ONCE, as the last event AFTER both `/api/say` posts — event-list ordering, distinguishing
  the poll-interval sleeps per the braindump's two-sleep-sources warning). One pre-existing
  assertion updated for the new `duration_s` report field (this branch's own test, not a 169 one).

### Change B — persistent replayable captions (web)
- `GraphView.tsx`: `sayCallout` + `narrationBlocked` replaced by `Map<refKey, SayItem>`
  (`status: playing|blocked|done|expired`); module-level `sayAnchorIdFor` (per-box re-resolve
  every render — flat ids renumber); `startClip` (above) + `replaySay` + `closeSay(key)` +
  `dismissAllSays` (the `clear` verb — close-all, locked); render maps one `NodeCallout` per box
  (`frameOnMount={false}`, unlock button on `blocked`, ↻ Replay on `done`, nothing on
  `expired`/caption-only); unmount cleanup kept; currency guards kept on BOTH `onended` and the
  play `.catch`. `index.css`: `.say-replay` shares the `.say-unlock` selector.
- Tests (say describe rewritten to the Map model): FakeAudio gains `onended`/`fireEnded()`
  (pause does NOT fire onended — interruption is code-driven, finish is event-driven, per the
  braindump). 14 say tests (was 10): kept/adapted all v1 pins (incl. the rapid-two-say
  AbortError currency guard, unmount-pause, stale-ref, clear-vs-bare-focus); new: different-target
  coexistence + close-one-leaves-other; interruption flips playing→done (mutation pin);
  replay-while-other-plays finishes the other (mutation pin); natural-finish → Replay → replays
  via a FRESH Audio; evicted replay → expired, button gone, caption stays; no Replay while
  playing (defect-1 pin); no dead button on caption-only.

### Change C — verification, docs
- **Suites:** Python **8480 passed / 9 skipped** (+9, 0 regressions); web **714 passed** (+5 net,
  0 regressions); strict tsc + `npm run build` + `make ui-build` + full `make check` all green.
- **Real browser (live Gemini + real CLI + headless MCP Chrome,** scratchpad workflow
  `say-followup-verify.pflow.md`, all assertions DOM-polled, screenshot
  `/tmp/pflow-shots/say-followup-persist.png`): **every check passed.**
  - **Pacing measured:** say1 elapsed **7s** for a **3.64s** clip; say2 elapsed **8s** for a
    **4.6s** clip (≈ synth + clip each — the CLI demonstrably blocked for the full clip);
    `duration_s` present in the JSON report.
  - **Persistence:** after two says to different nodes, BOTH captions coexist and BOTH show
    ↻ Replay (each clip finished naturally while its command blocked — the playing→done→Replay
    transition ran live, end-to-end through the real audio store).
  - **Replay:** clicking box 1's ↻ Replay flipped it back to playing (button count 2→1) — a live
    re-fetch + re-play of the stored WAV.
  - **clear-focus** removed ALL boxes.
  - Workflow-authoring notes: shell JSON stdout auto-parses to dict at a code node, while MCP
    `evaluate_script` results arrive as a PROSE wrapper with a ```json fence inside — a verdict
    node must brace-slice before `json.loads` (first run failed only on this; all browser checks
    had already passed — read the trace's `node_output` before re-spending on synthesis).
- **Docs:** `guide/features/ui.md` (verb lines + the pacing/persistence contract),
  `docs/reference/cli/index.mdx` (`--no-wait` + pacing paragraph), `web/CLAUDE.md` (say model:
  per-target Map, statuses, startClip), `web/src/components/CLAUDE.md` (say bubbles),
  `src/pflow/cli/commands/CLAUDE.md` (pacing + Narration), `src/pflow/core/CLAUDE.md`
  (`wav_duration`).

### Still user-only (hand-off to the human)
- **The felt walkthrough** — the whole origin of Change A: run the 5-step voice-demo sequence
  and feel the pacing + the ~4-6s inter-step SILENCE GAP (synthesis of clip N+1 happens after
  clip N ends; the braindump predicts it and names the options if it grates — accept / shorten
  captions / consciously reopen the queue decision; nothing was built for it).
- The audible check and a genuinely-blocked autoplay (headless allows autoplay; jsdom pins the
  unlock logic).
- **Box overlap on adjacent anchors** — two boxes coexisted live (DOM-verified) but the framed
  screenshot showed one at a time; a full multi-node walkthrough is the first real eyeball of
  crowding (braindump UNEXPLORED item).
- The v1 ADR offer ("TTS bypasses LiteLLM via direct httpx") remains open.

## 2026-07-04 — Live end-to-end demo session: pacing v2 (wait-before-dispatch) + playback beacons + blocked-hold

Driven entirely by the user narrating `ticket-triage.pflow.md` (new demo fixture, repo root) in
their REAL browser and reacting. Three user-reported defects, each fixed and re-demoed live:

**1. "~5s dead air between steps; max 1 second" → pacing v2 (reopens the follow-up's own
"block after dispatch" call, sanctioned by the user's explicit requirement).** The post-dispatch
sleep became a PRE-dispatch wait: synthesis already runs first in the command, so it overlaps the
still-playing previous clip; the CLI then waits out the remainder and dispatches. The rendezvous
lives on the SERVER (which already holds the audio): `app.state.narration_until` set on a
delivered audio say (`wav_duration(decoded)`), reset by `clear`, reported as
`narration_s_remaining` on `/api/health` (the probe the CLI already used). No filesystem state
(a `~/.pflow` file was rejected: real-home test pollution under xdist). Measured live: gaps
dropped from ~5s to **0 / 0.8 / 0.6 / 1.8s** (the 1.8 = a long line after a short clip; bound is
max(0, synth − prior clip)). Commands now return at dispatch — the LAST clip plays after the
sequence exits.

**2. "the first message was interrupted by the second" → start-lag pad.** The rendezvous was
recorded at BROADCAST time but the browser starts playing ~0.3–1s later (SSE + audio fetch +
play()), so the next say arrived exactly at the recorded end and clipped the last words.
`_NARRATION_START_LAG_S = 0.75` added to the estimate (err past the true end).

**3. "boxes showed without narration, only the last played (no clicks)" → playback beacons +
blocked-hold.** Root cause (proven live by the beacons, not guessed): the fresh `--open` window's
**autoplay policy** blocked the clips — and nothing could see it: the CLI reported "sent to 1
window" and paced a silent walkthrough. Fix: the Viewer now beacons what the audio element
ACTUALLY did — `POST /api/narration {audio_id, event: started|blocked|ended}`
(`reportNarration` in events.ts, fire-and-forget like reportInteraction; wired into startClip's
then/catch/onended + closeSay). `started` re-anchors `narration_until` to REAL playback (replaces
the lag guess); `ended` clears it; `blocked` sets `narration_blocked` (health-surfaced).
Then the user's follow-up ("it still marches on while blocked") locked the final behavior:
`_await_narration_turn` **HOLDS the walkthrough while blocked** — polls health every 0.5s (cap
240 = ~2 min), stderr notes `holding the walkthrough… click ▶` / `resuming` / gave-up — so a
silent window pauses the sequence until the user's ▶ click plays the blocked line (started
beacon clears the flag) and narration resumes. Verified in the live demo: block → hold note →
user clicked ▶ → "resuming" → clips flowed back-to-back.

**Contract deltas:** `/api/health` gains `narration_s_remaining` + `narration_blocked` (3
exact-body 169-era health pins updated — deliberate extension); new mutating `POST
/api/narration` (added to both guard inventories); the `--say`/`--no-wait` help + guide + CLI
reference rewritten to the wait-before-dispatch + hold semantics. All notes stderr-only (stdout
stays a pure JSON payload — they print BEFORE it).

**Tests:** CLI TestSayPacing rewritten to the new seam (10 cases incl. hold-until-unblocked with
ordered events, poll-cap give-up, bare-focus-never-probes, unreachable-server skip,
synth-failure-still-waits); server TestNarrationPacingRendezvous (12 cases: rendezvous set/reset,
caption-only/zero-window/garbage-bytes never busy, started re-anchors exactly, blocked flags,
ended clears, evicted-id harmless, body validation); web +5 (beacon truthfulness incl.
expired-replay ≠ blocked, close-beacons-ended; events.test reportNarration unit). Notable churn:
the follow-up's own post-sleep pacing tests were REPLACED same-day by the v2 seam's tests —
expected cost of iterating a live demo, not test instability.

**Not built (noted for later):** auto-resume on ANY canvas click (currently only the ▶ click
clears the hold — a page-level pointerdown unlock would be smoother but touches global listeners);
per-workflow narration state (global is right for one speaker); `--no-wait` leaves a stale
rendezvous if its clip outlives the sequence (bounded by one clip length).

**ADRs recorded (closes the standing v1 offer):** `context/adr/0011-174-tts-direct-httpx.md`
(TTS bypasses the LiteLLM single-seam rule — deliberate, don't "fix") and
`0012-174-narration-pacing-closed-loop.md` (wait-before-dispatch + rendezvous + playback beacons;
the queue rejection on record), plus a pointer in ADR-0007's rejected apply-acks bullet (its
"additive later" arm arrived for narration playback only).

## 2026-07-04 — Shipped: PR #560

Task 174 marked **done** (`task-174.md`); the distilled forward-reference is `task-review.md`.
The full branch shipped as **PR #560** (https://github.com/spinje/pflow/pull/560) in five commits:
v1 phases 1–3 (`66220404`) and 4–5 (`c1063ef0`), then the demo-day arc as three logical commits —
`8120a324` (pacing closed loop + persistent replayable captions + beacons + blocked-hold),
`9fc866ee` (settings `set-tts-model`/`set-tts-voice` + unset arms), `c2d1dbf6` (ADRs 0011/0012,
guide rewrite, task review, demo fixture). Final verification on the shipped tree: Python 8495
passed / 9 skipped, web 719 passed, `make check` green, plus the live user-heard walkthrough
(block → hold → ▶ → resume). Untracked demo fixtures `ticket-triage.pflow.md` /
`voice-demo.pflow.md` are committed on the branch.

## 2026-07-04 — Post-ship stress test: live whisper-TTS bug found + stripped-tags retry

A user-driven stress-test session (narrating a throwaway `silly-story-robot.pflow.md` in a real
browser, quirky/giggly voice, deliberately re-pointing the same nodes) surfaced a **real live
Gemini failure** the mocks never could — and produced a shipped fix to `core/tts.py`.

**Symptom.** One point in a 7-step giggly walkthrough came back
`narration unavailable: no audio in response (missing inlineData): {...finishReason: OTHER...}`.
The point + caption still landed and the walkthrough never stumbled — i.e. the totality seam
degraded to caption-only exactly as designed, against a **genuine** API misbehavior, not a mock.

**Root cause (empirically isolated, ~35 live probe calls, ~$0.10).** `gemini-3.1-flash-tts-preview`
returns a 200 with `finishReason=OTHER`, empty content (`parts=0`), `safety=None`, ~240 generated
tokens, and **zero audio** for **whispered delivery on certain content**:
- Deterministic per input (BASE line failed 5/5); a lone earlier success was a rare stochastic fluke.
- **Whisper is the necessary ingredient** — every failure carried `[whispers]`/`[whispering
  playfully]`; NO energetic tag (`[giggly]`, `[excited]`, even the freeform multi-word
  `[in a silly sing-song voice]`) failed on any content, including the exact content that fails
  0/4 under whisper.
- **Content-dependent under whisper** — `[whispers]` + calm ("penguin drifted off to sleep") →
  4/4 audio; `[whispers]` + "story zooms along the wire to the next room" → 0/4.
- **Ruled out:** safety filter (no `blockReason`/ratings), the `?`, "Wheee!", freeform-vs-canonical
  tags. It is a **Gemini preview-model bug, not a pflow bug.**

**Fix — one-shot stripped-tags retry inside the `synthesize()` seam (silent recovery).** New
private `_NoAudioError(TTSSynthesisError)` raised by `_extract_audio` on the empty-candidates /
missing-inlineData cases (a non-200/network error stays plain `TTSSynthesisError`, NOT retried —
stripping tags can't fix those). On `_NoAudioError`, if `strip_delivery_tags(text)` differs and is
non-empty, `synthesize()` retries ONCE with the tags stripped: the plain words synthesize where the
styled version won't, recovering **voice in default delivery** instead of degrading to caption-only
("caption always, voice when it can, **styled when it can**"). Recovery is silent by design (user
decision) — the caption already equals the stripped words, so voice and caption still match; the
agent's surface stays the sentence. Function remains **total** (only `MissingApiKeyError`/
`TTSSynthesisError` escape). Also: `_extract_audio`'s no-audio message is now **actionable** for
agents (`_no_audio_message` names `finishReason` + the whisper trigger + "try rephrasing or a
different delivery tag") instead of dumping truncated raw JSON.

**Verification.** `tests/test_core/test_tts.py` **25 passed (+5)** — new `TestStrippedTagsRetry`
pins: recover-by-stripping (asserts the 2nd call sent tag-free text), no-tags-not-retried (1 call),
network-error-not-retried (1 call), stripped-retry-also-fails → actionable message (2 calls),
finishReason surfaced. Updated the empty-candidates test's match string (message changed, intent —
"not an IndexError" — preserved). **Live 3/3 recovery** of the exact fragile input through the
shipped `synthesize()`. Full `make check` + `make test` green: **8460 passed / 0 failed**, mypy 244
files clean, all hooks pass. Re-running the original failing CLI command now prints **no**
"narration unavailable" note (synthesis succeeds; the only nonzero exit was an honest
`sent to 0 windows` after the tab was closed).

**Separately clarified (no code change): the "failed point's caption box wasn't shown" observation
is OCCLUSION, not a rendering gap.** `GraphView.tsx:1148` renders the caption `<p>`
unconditionally (only the Replay button gates on `&& url`), so a caption-only say DOES draw. The
walkthrough's edge point (`… -> add-a-lesson.prompt`) anchors at `add-a-lesson` (target-side
endpoint), and the *next* point (`focus add-a-lesson`) anchored the same visible node with a
DIFFERENT `refKey` (`add-a-lesson|in|` vs `add-a-lesson|null|`) → two separate boxes stacking at
one node, the later on top. That is the plan's own accepted-for-v1 "boxes at the same node stack in
DOM order" limitation, now biting two say-boxes. Candidate future work if crowding matters:
dedupe/offset boxes that resolve to the same anchor node.

**Not committed** (project rule). Files touched: `src/pflow/core/tts.py`,
`tests/test_core/test_tts.py`.

## 2026-07-04 — Post-ship stress test (cont.): say-box "now speaking" polish

Same session, two user-requested visual refinements to the say caption box (frontend only).

**1. Shimmer border while a clip plays.** `NodeCallout` gained an optional additive `className`
prop (the run callout doesn't pass it, so unaffected); `GraphView` passes `say-playing` only while
`item.status === "playing"`. CSS `.node-callout.say-playing` keeps the base drop-shadow and pulses
a soft white ring (`@keyframes pflow-say-shimmer`, 1.6s); `prefers-reduced-motion` → static ring.
So the currently-narrating box stands out among coexisting captions.

**2. Fixed-height affordance slot (no resize on play/stop).** User caught that an audio box changed
HEIGHT on every play/stop — `playing` had no button, `done` grew a ↻ Replay row, Replay shrank it
back — a vertical jitter made worse by the new shimmer. Fix: reserve ONE affordance row for the
whole life of an audio box (a caption-only box has no `url` → still no slot, so it never jumped) and
swap only its CONTENTS by status:
- `playing` → animated equalizer bars (`.say-eq`, 4 bars bouncing in `var(--accent)`,
  non-interactive) + "playing" label — the classic audio-playing signifier, chosen over a
  spinner (reads as "loading") after showing the user ASCII mockups.
- `blocked` → ▶ Play narration · `done` → ↻ Replay · `expired` → muted "clip expired".
- New `.say-affordance` base fixes EVERY height-affecting property (margin, padding, border WIDTH,
  font, line-height); variants only recolor + toggle `cursor`/interactivity — never the box model.
  So the box height is constant across ▶ → bars → Replay. `prefers-reduced-motion` → static bars.

**Verification.** tsc clean; **web suite 721 passed** (+2 — the say-callout playing-state test now
also pins `.say-eq` present while playing / gone + Replay when ended, i.e. the slot SWAP, not an
appear/disappear); `npm run build` + `make ui-build` green (bundle regenerated into
`src/pflow/ui/static/`). Verified live against the real browser + real CLI: box shows ▶ (fresh
`--open` window re-locks autoplay) → click → **equalizer bars + shimmer while speaking** → **↻
Replay in the same slot** on finish, no vertical jump. User confirmed "works great" (twice — shimmer,
then the eq/slot).

**Not committed** (project rule). Files touched: `web/src/components/NodeCallout.tsx`,
`web/src/views/GraphView.tsx`, `web/src/index.css`, `web/src/views/GraphView.test.tsx`
(+ regenerated `src/pflow/ui/static/` bundle).

## 2026-07-04 — Post-merge review response: PR #560 code-review triage + beacon-completeness fixes

Ran `/evaluate-review` on the two PR #560 reviews — a substantive human review
(`#issuecomment-4881677393`) and Codex's automated review (`#pullrequestreview-4629375486`, 6 inline
P2s). Verified every finding against CURRENT code (the branch had advanced past the reviewed commit
`c2d1dbf6` to `6e322e28` — the whisper fix + say-box polish — so line anchors needed re-checking; 3
parallel `pflow-codebase-searcher` agents gathered the evidence, then I read the load-bearing spots
myself). Triage: **8 real, 2 no-action-by-design, and the reviews were still relevant** — none of the
post-review commits had touched the pacing/beacon state machine.

**Key insight that shaped the fix (the reviewers' framing hid a coupling).** Findings A2/B1 (clear
doesn't reset `narration_blocked`), A3 (interrupt doesn't beacon `ended`), B2 (close-blocked doesn't
beacon), B3 (stale `ended` clears unconditionally), B4 (unmount doesn't beacon) are ONE family: the
server's pacing state (`narration_until`/`narration_blocked`) is a closed loop fed by playback
beacons, but several stop paths don't beacon. The obvious "sprinkle an `ended` at each stop path" is
**incorrect for the interrupt case**: a new say already set `narration_until` server-side *before*
broadcasting, so a naive interrupt-beacon (`ended` for the OLD clip) races in *after* and — because
`narration()` zeroed `narration_until` UNCONDITIONALLY — wiped the NEW clip's pacing. So B3
(clip-scoping) is **load-bearing** for A3/B4 to be safe, and doing them right meant folding in the
finding I'd initially deferred. Raised the coupling with the user; they approved folding B3/[7] in.

### What was fixed (family, folded into one symmetric design)

- **Server (`ui/server.py`) — clip-scoped pacing (B3) + clear-reset (A2/B1).** Added
  `app.state.narration_audio_id`. `say()` records it alongside `narration_until` (captured the stored
  `audio_id`, previously inlined into the f-string). `narration()` now: `started`/`ended` clear the
  blocked flag for ANY clip (evidence sound works), but only move `narration_until` when
  `audio_id == narration_audio_id` (the current clip) — a beacon for a superseded clip is inert. This
  makes the frontend safe to beacon `ended` from every stop path. `clear` command resets the WHOLE
  rendezvous (`narration_until` + `narration_blocked` + `narration_audio_id`), window-independently
  (releases a stuck blocked flag even when every tab is gone — a frontend `ended` only fires if a tab
  is open).
- **Frontend (`GraphView.tsx`) — the missing symmetric seam (A3/B2/B4).** Replaced `audioRef` with
  `currentClipRef` (the clip + the box `key` it belongs to). Added `stopCurrentClip()` — the mirror of
  `startClip` ("the single start-any-clip seam"): pause + beacon `ended` + null the ref. EVERY stop
  path now funnels through it — `startClip`'s interrupt (A3), `closeSay` when the box owns the live
  clip incl. a `blocked` one (B2), `dismissAllSays` (clear), and the unmount cleanup (B4).
  `closeSay` lost its `status === "playing"` special-case (now: stop iff `currentClipRef.key === key`,
  so closing a stale box never kills what's playing); `onended` nulls the ref to avoid a double-beacon;
  currency guards moved to `currentClipRef.current?.audio === clip` (the rapid-two-say AbortError pin
  still holds).
- **[8] pace-on-say (Codex B6).** `say()` was keying pacing AND the dispatch report on the POINT
  broadcast's `conns`, ignoring the say broadcast's return. If a Viewer's bounded queue has room for
  the point but overflows on the say, it's evicted having received the focus but NO audio — yet pacing
  was still set. Now captures `say_conns` and paces on it; the dispatch report stays on the point's
  `conns` (the honest "did the focus land" count — a dropped point implies a dropped say, point-first).
  **No dedicated test** (deliberate): forcing the case needs a queue artificially filled to 63 to
  trigger the hub's eviction — that tests the framework's backpressure, not this logic (tests/CLAUDE.md
  pitfall #1/#19); the comment carries the intent.

### Declined / no-action (recorded so they aren't re-litigated)

- **[6] synth-before-validate (Codex B5) — DECLINED (2nd time).** `--say` synthesizes (paid ~½¢/~3s
  Gemini call) before contacting the server / resolving the target, so a typo target or dead server
  wastes the call. Real but efficiency-only. The fix that catches typos needs a server round-trip +
  a SECOND recursive graph build on every SUCCESS (`/api/say` already builds), taxing the ~99% path
  and the low-dead-air pacing budget to save the rare miss; the cheap reachability-only variant
  catches only the dead-server case (which fails on the first say and stops) and overlaps a probe the
  CLI already makes. Deep-review declined it in v1; declined again. **Documented for a future agent in
  a TEMP scratchpad doc** (`scratchpads/task-174-voice-narration/ISSUE-say-synthesizes-before-validation.md`
  — a throwaway working note, NOT a durable task artifact) with repro steps, the four constraints, the
  priced fix options, and the reconsider-triggers (observed spend / price rise / a future clip cache).
  *[Update 2026-07-04, later session: the scratchpad doc was retired. The durable record is now
  ADR-0012's rejected-options bullet ("validate-before-synthesize") + the DELIBERATE ORDERING note on
  `_resolve_narration` in `ui.py`; the sanctioned remedy (clip cache) is designed in GH issue #561.]*
- **A4** (`ended` zeroes global pacing while another window plays) — the documented "one machine, one
  speaker" model; reviewer flagged it only to keep it conscious. **A5** (`TTSSynthesisError` bare
  `pass`) — intentional and documented. No change to either.

### [5] Stray demo file (human review warning)

`ticket-triage.pflow.md` was already gone; only `voice-demo.pflow.md` remained at the repo root (zero
example-validation coverage — the glob is `examples/**`). Confirmed it validates (`✓ Workflow is
valid`), `git mv`'d it to `examples/narration/voice-demo.pflow.md` (+ a short README) — now covered by
`test_docs/test_example_validation.py`.

### Verification (0 regressions)

- Python `make test`: **8463 passed** (baseline 8460 → **+3** server tests: stale-`ended` ignored,
  stale-`started` ignored, `clear` resets blocked; `test_ended_beacon_clears_the_window` updated to use
  the real audio_id). `make check` fully green (ruff/ruff-format, mypy 244 files, deptry, MDX).
- Web `npx vitest run`: **723 passed** (baseline 721 → **+2**: close-blocked-beacons,
  stale-box-close-leaves-live-clip; strengthened the interrupt + unmount tests to assert the beacon).
  Strict `tsc` + `npm run build` + `make ui-build` green (bundle regenerated).

### Deviation / design note

- Folded the reviewers' 4–5 sprinkled patches into **one symmetric design** (a stop seam mirroring the
  start seam + clip-scoped server pacing) rather than N call-site edits. Rationale: the naive sprinkle
  is subtly *incorrect* (the interrupt/stale-beacon coupling above), and the symmetric version is the
  simpler FINAL code — one start seam, one stop seam, symmetric `started`/`ended` guards — with no
  deferred landmine. User explicitly asked to optimize for final-code simplicity and confirmed folding
  [7] in.

### Docs updated

`src/pflow/ui/CLAUDE.md` (`/api/narration` scoping + `clear` resets the whole rendezvous),
`web/CLAUDE.md` (the `currentClipRef` + `stopCurrentClip` stop seam, id-scoped beacon safety).

**Not committed** (project rule). Files touched: `src/pflow/ui/server.py`,
`tests/test_cli/test_ui_interaction_server.py`, `web/src/views/GraphView.tsx`,
`web/src/views/GraphView.test.tsx`, `src/pflow/ui/CLAUDE.md`, `web/CLAUDE.md`,
`voice-demo.pflow.md` → `examples/narration/voice-demo.pflow.md` (+ new `examples/narration/README.md`),
(+ regenerated `src/pflow/ui/static/` bundle). Temp working note (not a task artifact):
`scratchpads/task-174-voice-narration/ISSUE-say-synthesizes-before-validation.md` *(retired in a
later session — see the [6] update above: ADR-0012 + the `_resolve_narration` docstring are the
durable record; clip cache designed in GH issue #561)*.
