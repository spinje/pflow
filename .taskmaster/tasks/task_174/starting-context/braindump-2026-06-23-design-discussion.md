# Braindump: Task 174 design discussion (the "point & say" voice feature)

> This is the tacit-knowledge complement to `task-174.md`. The task file has the *what/why/how*.
> This file has the *journey, the user's head, and the things I'd be furious not to have said.*
> Everything verifiable from files is deliberately omitted here.

## Where I Am

We finished a pure **design discussion** — no code written. The task spec (`task-174.md`) is
complete and, I believe, faithful. The user invoked `/braindump` immediately after I created the
spec and asked two follow-up questions I never got answers to (priority + roadmap placement). So:
**no implementation has started; two small loose ends are unresolved (below).**

## User's Mental Model — their exact words (the most valuable thing here)

The user drove this. They came in with the idea fully formed in spirit ("I want to discuss an idea
I have"). Capture their phrasing — it reveals priorities the spec flattens:

- The seed: *"let AI agents send a 'message' with a 'pointing event' that is expressed as a voice
  where the agent can explain things with text to speach."* → voice **attached to a point**, not
  standalone. That's why `--say` rides `focus`/`frame`.
- **The real motive (quote it):** *"I think this will be really useful when iterating on workflows
  and also I can create very interactive DEMOS that doubles as actual functionality to show off
  what pflow is capable of."* The phrase **"DEMOS that doubles as actual functionality"** is the
  load-bearing one. The demo is NOT a mockup — they want the *real* agent capability on display.
  This is why I steered away from "just pre-record everything": a faked demo undercuts their whole
  point. The deeper goal: **make pflow's agent-first nature visible and visceral** — a narrating,
  pointing agent *feels alive/present*, which is the wow.
- *"I will need this for a demo very soon."* → **real near-term deadline.** I asked how soon
  (days vs weeks) and whether it's scripted vs live-dynamic. **They never answered either.** They
  redirected to architecture questions every time. So the timeline and demo-format are genuinely
  UNKNOWN (see Open Threads — this matters a lot for sequencing the build).
- On the interface, with conviction: *"the thing the agent writes should still be very easy and
  intuitive, just --say 'bla bla' it should not be aware of any tts internals like urls, binaries
  or whatever."* This is a **core value**, not a nice-to-have. The minimal one-field interface is
  non-negotiable to them. Any implementation that leaks TTS internals into the agent's surface
  violates the spirit.
- They **push back and make you justify.** *"why shouldnt the ui server handle the fetching the
  audio from text?"* — they did not accept CLI-side synthesis on my say-so; they made me argue it
  properly. (I did, and they accepted: *"yes I guess you are right here."*) Expect a user who wants
  the *reasoning*, not the conclusion.
- They **catch unsourced claims.** *"are you sure this is how gemini works, how can agents use
  tags?"* — I had stated the audio-tags thing partly from a marketing blog. They were right to
  push; verification against Google's docs actually *changed* the recommendation. **Lesson for next
  agent: never hand this user (or yourself) an unverified LLM-provider claim.**
- They think about **reversibility / foreclosing options:** *"do we loose this capability if we use
  the cli as api caller instead of the ui server?"* (re: streaming). They worry about painting into
  corners. Frame future-proofing explicitly for them.
- They **contributed a design idea** that's now in the spec: *"if we ever add other tts providers
  pflow can internally translate the syntax so agent just learns one way of doing it."* This is
  *their* insight (the cross-provider tag-translation seam). It maps perfectly onto the project's
  "one notation, one source of truth" philosophy — they intuit that philosophy without naming it.
- On scope, they're decisive and minimalist: *"defer for now"* (standalone say verb), *"we can keep
  these around for now, maybe add a close button"* (captions). They cut quickly.

**Read of their working style:** architect-minded, hands-on, evidence-driven, minimalist on agent
surface, allergic to hand-waving. They gated the spec explicitly — *"before we commit to a task
spec I want to understand how to build the TTS"* — i.e. they want to *understand the mechanism*
before delegating, not be handed a black box.

## The Journey — how the design moved (and my reversals)

The spec reads as if these were obvious. They weren't. Three of my own recommendations got
overturned mid-conversation, all for good reasons:

1. **Web Speech API → killed.** My *first* recommendation was "build the dev-iteration core on the
   browser Web Speech API first (zero-dep), defer premium TTS." The user had **already tested Web
   Speech**: *"its not good at all, pretty much unusable."* This isn't a stepping stone — it's a
   different transport (text-on-wire vs audio-on-wire). Pivoted straight to synthesized audio.
   **Do not revisit Web Speech.**

2. **LiteLLM → direct httpx (a reversal driven by the codebase scan).** I initially leaned "reuse
   pflow's LiteLLM adapter / try LiteLLM first." Then the `pflow-codebase-searcher` scan surfaced
   that **litellm is pinned `==1.86.1`** (intentional, deterministic offline pricing map) and its
   Gemini-audio path is young/buggy. That flipped me to a **direct httpx call**. The reversal is in
   the spec, but the *meta-point* isn't: this was an evidence-driven update the user respects — they
   like when new info changes the call.

3. **Two-request split → dropped (I argued myself out of my own idea).** I *introduced* the
   point-then-audio decoupling as a "nice consequence." The user asked *"how will the splitting up
   into two requests work and is it worth it?"* — and on honest analysis (deletion test +
   solve-observed-not-theorized), it wasn't worth it. The single biggest reason it's safe to drop:
   **the latency it fixes only exists during live synthesis, and the polish-critical path (demos)
   uses pre-rendered/cached audio that's already instant.** Kept as a deferred additive optimization.

4. **Audio tags: "plain text only" → "support tags, strip brackets" (verification flipped it).**
   I first flagged tags as a caption-leak problem and leaned toward forbidding them in v1. Then I
   verified Gemini's actual mechanism: bracketed tags are **delivery metadata, consumed/not
   spoken**, so stripping `[...]` from the caption is *correct* (caption = spoken words), not a
   workaround. That made supporting them near-free → flipped the recommendation. **The verification
   changed the answer** — a concrete example of why the user's "are you sure" was right.

## Key Insights (non-obvious, not in the spec)

- **CLI-side synthesis is the closest call in the whole design, not a slam-dunk.** The strongest
  argument *against* it (for server-side) is **caching/dedup**: a demo that replays a fixed set of
  lines across windows would synthesize each line once if the server cached by `(text, voice)` hash.
  I ruled server-side out because it breaks three 169 properties, but **if the user's demo turns out
  to be "replay the same ~10 lines many times," reconsider server-side caching** (or add CLI-side
  on-disk caching, which gets most of the benefit without the coupling). This tension is real; I
  weighted the 169 invariants over caching, but it's a judgment call.

- **The caption isn't just a fallback — it's the architectural simplifier.** Making the caption the
  *always-on baseline* (voice = enhancement) is what removes ALL failure-branching (autoplay-blocked
  and synth-failed collapse to "caption showed, audio didn't"). If a future agent "optimizes" by
  making the caption conditional on audio, they reintroduce the branch. Keep caption unconditional.

- **The feature literalizes 169's own metaphor.** Read `task_169/implementation/progress-log.md`,
  the `2026-06-19` "sent vs shown" entry: *"the human is the acknowledgment... the agent points,
  says 'see it?'"* Voice makes "says 'see it?'" real. That entry also explains why there's **no ack
  channel** — and why we don't need one here either (the human hears it; for sequencing, the CLI
  knows the audio's duration so it can pace itself without a browser ack).

## Assumptions & Uncertainties

- **NEEDS VERIFICATION (highest priority before coding the synth path):** I got the Gemini request
  shape from `WebFetch` *summaries*, and they conflated **two different request formats** — an
  "Interactions API" style (`input` / `response_format:{type:"audio"}` / `generation_config.speech_config`)
  AND a `generateContent` style (`response_modalities:["AUDIO"]` / `speech_config` with a voice).
  **I am NOT confident which is canonical for `gemini-3.1-flash-tts-preview`.** The implementer MUST
  make one real live call and pin the actual request/response JSON before writing `synthesize()`.
  Don't trust my spec's pseudo-shapes as literal.
- **NEEDS VERIFICATION:** the default voice. Docs mentioned **"Kore"** as an example; I have not
  confirmed the prebuilt voice list or a good default. Pick after seeing the real list.
- **NEEDS VERIFICATION:** PCM details (16-bit / mono / **24 kHz**) — confident from docs but confirm
  from the live response before hard-coding the WAV header params.
- **ASSUMPTION:** `gemini-3.1-flash-tts-preview` is the right id and is reachable with a standard
  `GEMINI_API_KEY`/`GOOGLE_API_KEY`. It's a **preview** model — id may have changed by build time;
  that's *why* it's config-driven (`tts_model`), but the *default* baked into code needs a re-check.
- **ASSUMPTION (unconfirmed by user):** the demo is run with the browser tab **foregrounded** (so
  169's SSE works and #529's reconnect gap doesn't bite). Never confirmed.

## Unexplored Territory

- **UNEXPLORED — the demo's actual format.** Scripted/pre-rendered vs live-dynamic was the ONE fork
  I kept asking about and never got answered. It decides build order: pre-rendered is the safe,
  instant, zero-API-risk path for the imminent demo; live-dynamic is the "doubles as real
  functionality" showcase but carries latency + API-failure risk live. **Ask this first.** The spec
  supports both (same plumbing), but the user should consciously choose what the *first* demo runs.
- **UNEXPLORED — demo orchestration/sequencing.** A narrated walkthrough is a *sequence*
  ("look here…now here…"). We established the CLI can pace off known audio duration (no ack needed),
  but never designed *how the agent drives a multi-step demo* — is it a sequence of CLI calls? A
  pflow workflow that orchestrates the demo? This is probably the user's next real need after the
  primitive exists. MIGHT MATTER for "very soon."
- **MIGHT MATTER — #529 reconnect gap during a live demo.** If the presenter drives from the
  terminal with the browser tab backgrounded/asleep, the SSE can drop and `say` reports `0 windows`
  silently-ish. 169's model says "reload to recover," fine for iteration — **awkward mid-demo.**
  For a live demo, keep the tab foregrounded, or note #529 as a real demo-day risk.
- **CONSIDER — rate limits / pre-warming.** A chatty iterating agent, or a rapid demo, could hit
  Gemini rate limits → live synth fails → caption-only (graceful, but voiceless on stage). For a
  high-stakes demo, **pre-warm/cache the lines** beforehand. Cost is a non-issue (~cents); rate
  limits and transient API errors are the real live risk.
- **CONSIDER — audio output device / muted machine.** The obvious demo-day failure. Caption baseline
  covers comprehension, but do a sound-check. Not worth code; worth a mention in any demo runbook.
- **UNEXPLORED — multi-speaker / voice variety.** Gemini supports multi-speaker. Could a demo use a
  distinct "narrator" voice vs other contexts? Out of v1 scope, but the user might want it for
  production-value demos. Config has only one `tts_voice` today.
- **MIGHT MATTER — `--say` makes `focus` slower.** With single-request, the focus command now blocks
  ~1–2s on synthesis before returning. A bare `focus` is instant; `focus --say` is not. Probably
  fine (agents tolerate latency), but it changes the command's feel and serializes rapid `--say`s.

## What I'd Tell Myself

- Don't propose Web Speech. (Already burned that; saved only by the user's prior testing.)
- Verify Gemini specifics against **official Google docs**, live, before coding. My training is
  stale and the field moved (Gemini 3.x TTS postdates my cutoff). The user *will* catch a guess.
- The user's minimal-interface conviction is sacred. When in doubt about exposing a knob, **don't** —
  push it into config or behind the seam.
- When you catch yourself adding machinery (the two-request split, an ack channel), run the deletion
  test out loud. The user respects "I argued myself out of this."

## Open Threads (unresolved when the conversation ended)

1. **Priority unconfirmed.** I set `task-174.md` Priority = **high** (demo-driven) and asked the
   user to confirm or drop to medium relative to the 172/173 queue. **No answer.** Re-confirm.
2. **CLAUDE.md roadmap NOT updated.** I deliberately did not touch the ordered "Planned Features"
   list and asked where 174 should slot (fast-follow near 169? after 172/173?). **No answer.**
   Still needs adding.
3. **Demo timing + format** (see Unexplored). The two biggest unknowns; both gate sequencing.

## Relevant Files & References

- `task-174.md` (sibling) — the full spec; read it first.
- **Task 169** (`.taskmaster/tasks/task_169/`): `task-review.md` (the durable invariants —
  async-only hub, vocabulary-agnostic envelope, target resolver), `implementation/progress-log.md`
  (the `2026-06-19` "sent vs shown / human is the acknowledgment" entry — the philosophical root of
  this feature; and the `2026-06-22` grammar entry — the "no second notation" discipline `--say`
  inherits).
- **Issue #529** — SSE reconnect + viewer discovery. Related, NOT a dependency; the demo-day risk
  above lives here. Belongs to the 172/173 track.
- **Codebase scan result** is in this conversation only (not a file): the seam map
  (`_request`/`_Hub`/`create_app`/`settings`/`inject_settings_env_vars`/`llm_client` completion-only)
  is summarized in `task-174.md` → Implementation Notes → Code anchors. Trust those line numbers
  loosely (they were from a same-session scan; re-confirm if files moved).
- **Gemini TTS docs** (verify against these live): https://ai.google.dev/gemini-api/docs/speech-generation
  · https://cloud.google.com/blog/products/ai-machine-learning/gemini-3-1-flash-tts-on-google-cloud
  · https://livekit.com/blog/gemini-3.1-flash-tts-prompting-guide (tag usage).
- **LiteLLM avoidance:** pin `==1.86.1`; bug BerriAI/litellm#11118 (Gemini audio, pcm16-only,
  no streaming).

## For the Next Agent

- **Start by asking the user two things:** (1) when is the demo and (2) is it scripted/pre-rendered
  or live-dynamic. Everything about build-order hinges on these and they were never answered.
- **Then verify the Gemini request/response shape with one real call** before writing `synthesize()`.
  My spec's request shapes are from doc summaries that conflated two formats — treat them as hints,
  not gospel.
- **The user cares most about:** the dead-simple `--say` interface (no leaked internals) and that
  the demo shows *real* capability, not a mockup. Hold both.
- **Don't bother with:** Web Speech (rejected), an ack channel (the human + known audio duration
  suffice), the two-request split (deferred), or a second agent-facing tag syntax (the seam
  translates).
- **Quick wins for the demo even before full build:** the pre-rendered path (point at static audio
  files via the same plumbing) is the lowest-risk way to get a great-sounding demo fast — but flag
  to the user that it's the "safe" mode and the live path is the one that matches "doubles as actual
  functionality."

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
