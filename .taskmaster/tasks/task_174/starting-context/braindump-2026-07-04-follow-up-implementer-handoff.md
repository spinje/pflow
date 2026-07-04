# Braindump: Task 174 follow-up (pacing + persistent captions) → implementer handoff

Written 2026-07-04 by the agent that (a) shipped Task 174 phases 1–5, (b) demoed it live with the
user, and (c) wrote the follow-up plan you're about to execute. Everything procedural is in
`implementation/follow-up-plan-narration-pacing-and-persistence.md` — read it first. This file is
ONLY what's in my head and nowhere else. No repetition of the plan/spec/progress-log.

## Where I am / what's settled

Both "decisions to ratify" at the bottom of the plan are **CONFIRMED by the user** (verbatim:
*"confirmed on both 1 and 2"*): pacing blocks by default with `--no-wait` opt-out, and the
`Narration` NamedTuple fold is in. Treat them as locked, not open. Zero code written for this
follow-up.

## How this follow-up was born — and why that matters for HOW you build it

This plan did not come from theorizing. **We ran the real feature live** — I created
`voice-demo.pflow.md` (repo root, untracked), opened it in the user's actual browser, and narrated
a 6-node walkthrough with a sequence of `pflow ui focus … --say` commands. The user watched it and
immediately said the audio *"was constantly being interrupted and moving to the next item before it
was finished."* **That felt experience is the entire origin of Change A.** So: when you finish,
don't just green the tests — *re-run the demo and feel it*. The user validates by USE, not by test
counts. If the walkthrough still feels wrong after your change, it's not done, regardless of CI.

## The user's mental model (their words, their bar)

- They pasted the **simplicity mantra twice**, unprompted: *"prioritize simplicity of the FINAL
  code… what's the right solution that the top 10% of codebases similar to this one would implement…
  NOT overfitting / overengineering… more simple code that is optimized for AI agents to understand
  and add features to."* This is a standing instruction, not a one-off. The plan's Change B is
  deliberately a *fold* (the Map REPLACES `sayCallout` + `narrationBlocked`, net simpler) — hold
  that. If you catch yourself ADDING a layer (a queue, a manager class, a second state store),
  stop; you've drifted from what they want.
- When I gave options + a clear recommendation, they **decided instantly**. They don't want a survey;
  they want a recommendation with reasoning they can veto. Give them that shape if anything reopens.
- They think in **whole interactions**, not features: they went from "interruption" → "maybe a
  queue" → "report queue depth" → "batch the command" → "persistent boxes + replay" across three
  messages. The through-line they care about is *"a narrated walkthrough should just work."* Keep
  that lens; individual asks (queue-depth, batch API) they raised and then we jointly dropped — see
  the plan's Do-NOT-build list for why, but the tacit point is: **they float ideas to test them, not
  as commitments.** Don't over-index on any single phrasing.

## The one thing NOT in the plan that will bite: the inter-step SILENCE GAP

Change A blocks for clip N's duration, then returns. Command N+1 then spends ~4–6s **synthesizing
before it dispatches** — during which nothing plays. So a paced walkthrough has a *silence gap
between steps* ≈ the next clip's synthesis time. In the live demo, my ~80–120-char captions
synthesized in ~4–6s (clips ~5–7s). So expect ~4–6s of dead air between narration steps after the
fix. **I judged this acceptable** (a natural beat between "look here" and "now here"), and the
alternatives all lead into the locked-out queue territory (pre-synthesizing N+1 while N plays =
pipelining = the client/server queue we explicitly rejected). But the USER HASN'T FELT THE GAP YET
— it only appears once pacing is in. When you re-demo, watch their reaction to the gap specifically.
If they dislike it, the honest options are: (a) accept it, (b) shorten captions, (c) reopen the
queue decision. Do NOT silently build a queue to close the gap — that's a decision for them.

## Test-scaffolding landmines — you WILL re-hit these in Change B

The session-2 progress-log entry lists three (jsdom NodeCallout `getInternalNode` measured-backfill;
the `?run=` URL leak across tests; `FakeAudio.play()` must return a FRESH promise per call). **Read
that entry — all three apply directly to your Change B test rewrite**, I'm not repeating them. Two
ADDITIONS specific to your work:

- **`FakeAudio` needs an `ended` trigger** (plan B7 says add `fireEnded()`). Subtlety: `pause()` does
  NOT fire `onended` in real browsers — so your "interrupted clip becomes done" path (playNarration
  flipping other playing boxes to `done`) is driven by CODE, not by an `ended` event. Test the two
  paths separately: natural finish via `fireEnded()`, interruption via a second `say()`.
- **The `--open --say` pacing test is the tricky one.** `focus_cmd`'s `--open` poll loop *already*
  calls `time.sleep` (the interval poll at ui.py:691). Your pacing sleep is ALSO `time.sleep`. So a
  test that patches `time.sleep` sees BOTH the poll-interval sleeps AND the one pace-sleep. Assert on
  the sleep call carrying the *clip duration* value (or the LAST call), not "sleep called once."
  This is the single most likely place to write a passing-but-wrong test.

## NEEDS VERIFICATION before you assume block-by-default is free

The plan's A4 claims existing CLI say tests stay instant because their mocked bytes give
`wav_duration ≈ 0`. I'm ~85% sure but did NOT exhaustively check. **Grep the CLI say tests for what
`synthesize` is patched to return** — if any returns a real multi-second WAV, block-by-default will
add real wall-clock to the suite; patch `time.sleep` there. The server tests DO use a "real tiny
WAV" b64 but those don't hit the CLI sleep path (different process). Confirm, don't assume.

## Don't weaken the currency guard when you refactor `playNarration`

`playNarration` gains a `key` param and per-item status transitions. The `if (audioRef.current ===
clip)` guard inside the `.catch` was a **deep-review CRITICAL** in the original 174 (a stale
`AbortError` from a paused prior clip must not flip the NEW clip's box to `blocked`). It's easy to
drop or mis-thread when you add the key. The plan keeps it in the B2 sketch — keep it, and keep the
test that pins it (rapid two-say → no false unlock/blocked). This is the fix most likely to silently
regress under refactor.

## A small correctness point the plan implies but doesn't spell out

A **caption-only** say (no `audioUrl`) should render a persistent box with NO Replay/unlock button
(the render gates both buttons on `item.audioUrl`). In `playNarration` I set such a box straight to
`status: "done"`. That's correct — a caption-only box is just a persistent caption + close button.
Don't "fix" it by adding a dead Replay button, and don't let `status: "done"` + null audioUrl render
one.

## The scratchpad verification workflows are DYING WITH MY SESSION

For Change C's re-demo you need to drive the real browser via pflow (I confirmed this session:
**you have NO direct chrome-devtools MCP access — it's wired into pflow as `mcp-chrome-devtools-*`
nodes**, so a workflow is mandatory, not a choice). I built two throwaway workflows in my scratchpad
(gone when my context ends):
- `say-verify.pflow.md` — single-shot: open → settle → run ONE `--say` → assert `.say-caption` text
  → screenshot. (Also the skill's `open-and-settle` poll pattern re-inlined.)
- `say-sequence.pflow.md` — the multi-command one: open → settle → say A → assert → say B → assert
  replaced (one callout) → screenshot → clear-focus → assert caption gone → screenshot.

Rebuilding either is ~5 min BUT I hit four pflow-authoring landmines you'll re-hit (none documented
anywhere):
1. **Every output entity needs a description paragraph** (parse error otherwise).
2. **Only ONE output may have `stdout: true`** (validation error otherwise).
3. **An output `source:` must be a single `${…}` template string** — you can't put a JSON object
   literal there. To combine several results, add a `code` node that assembles a dict and output
   THAT.
4. **A `code` node needs `result: <type> = …`** AND **every `- inputs:` var needs a type annotation
   in the code body** (`notes: str`). The MCP `evaluate_script` result arrives as a **string**
   (annotate the input `str`, not `dict`) — it's the tool's stdout wrapper, JSON inside.

Also: the demo workflow at repo root needed `- next: end` on BOTH branch targets to validate (the
validator rejects fall-through branch targets — a good catch to narrate, incidentally). And a
**stale pre-174 `pflow ui` server answers 405 on `/api/say`** — if the endpoint looks missing, kill
and restart the server from this worktree.

## UNEXPLORED / MIGHT MATTER

- **UNEXPLORED — box overlap on adjacent anchors.** With multiple persistent boxes, two anchored to
  visually-close nodes will overlap on the canvas (NodeCallout uses a fixed perpendicular offset from
  its anchor). Accepted (each has a close button), but I never saw it in a real browser — my demo
  interrupted each box before the next, so only one showed at a time. **Your re-demo with pacing is
  the FIRST time multiple boxes coexist visually.** Eyeball it; if a 6-node walkthrough is a mess of
  overlapping boxes, that's the user's next feedback loop (maybe a "close all" button, deferred in
  the plan).
- **MIGHT MATTER — block-by-default changes the feel of a SINGLE live `--say`.** An agent that points
  once and continues now blocks ~5s. The user consciously accepted this (the walkthrough win is
  worth it), but if a live-reasoning agent feels sluggish, `--no-wait` is the escape. Not a bug; a
  known tradeoff.
- **CONSIDER — the `--no-wait` flag NAME.** User confirmed default-block but never blessed the name
  `--no-wait`. It's a bikeshed; rename freely (`--async`, `--no-block`) if a better one fits. Not
  load-bearing.
- **UNEXPLORED — replay after LRU eviction in a REAL browser.** The `expired` path (replay a clip
  evicted from the 16-slot store → 404 → button gone) is only unit-testable in jsdom. To see it live
  you'd fire 17+ says then replay the first. Low priority; the graceful-404 is simple.

## Process / repo state you must know

- **Task 174 itself is NOT committed** — it lives as uncommitted working-tree changes (phases 1–5)
  plus this session's frontend fixes. You are building on an uncommitted base. The progress log
  records a near-miss where `git checkout <file>` wiped uncommitted work — **never `git checkout` a
  file with uncommitted changes; use Edit to revert.**
- Untracked artifacts on the branch: `voice-demo.pflow.md` (repo root — the demo fixture, keep it),
  and the plan/this-braindump under `.taskmaster/tasks/task_174/`.
- **NEVER git add/commit/push unless the user explicitly says so** (strict project rule; they are
  particular about it).
- This is a **follow-up** — the user said *"another agent will implement this plan."* The plan
  reopens two 174 v1 decisions; that's sanctioned, but keep it as a distinct unit of work (its own
  progress-log section at minimum), don't blur it into the 174 phase-1–5 record.

## For the next agent

- **Start by** reading the plan in full, then this. Change A and Change B are independent — do A
  first (it's ~25 lines, self-contained, and lets you re-demo pacing immediately to feel the gap).
- **The user cares most about**: the walkthrough *feeling* right (re-demo, don't just test) and the
  FINAL code being simpler, not layered (the Map replaces two pieces of state — that's the whole
  point; don't add a third).
- **Don't bother with**: a playback queue, queue-depth reporting, a CLI batch flag, an LRU bump, a
  side-panel log — all in the plan's Do-NOT-build with reasons; the tacit reason is the user raised
  each, we reasoned through it together, and jointly dropped it. Don't resurrect them.
- **The riskiest code**: the `--open --say` pacing test (two sleep sources) and the currency guard
  under the `playNarration(key)` refactor. Get those right and the rest is mechanical.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
