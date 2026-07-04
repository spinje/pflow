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

### What to verify manually (when resuming / reviewing)
- The wire contract is exercised only within-process (TestClient + CliRunner + mocked Gemini/httpx).
  A **real** `pflow ui <wf>` + `pflow ui focus <wf> <node> --say "[excited] …"` against a live
  browser is still needed (Phase 5.3) to confirm audible playback, the caption anchor, edge-target
  anchoring, and the autoplay-unlock flow — a screenshot can't hear audio; ask the user.
- The default `tts_model` (`gemini-3.1-flash-tts-preview`) is the plan's pinned preview id; confirm
  it still resolves at demo time (config-driven, so a drift is a one-line settings change).
