# Narration paces as a closed loop (CLI waits its turn, browser beacons playback) — not a playback queue

**Status:** accepted (Task 174 follow-up; the shape was reached through four falsified iterations in
one live-demo day — see `task_174/implementation/progress-log.md` for the arc)

A sequence of `pflow ui focus … --say` commands is a narrated walkthrough. Getting it to *sound*
right required a closed loop across three processes: the CLI **synthesizes first, then waits for
its turn** (reading `narration_s_remaining` / `narration_blocked` off `GET /api/health`) **before
dispatching**, so synthesis overlaps the still-playing clip and steps play back-to-back; the server
holds a single global rendezvous (`narration_until`, estimated at broadcast + a start-lag pad); and
the browser reports ground truth via fire-and-forget **playback beacons** (`POST /api/narration`,
`started|blocked|ended`) — `started` re-anchors the estimate to real playback, `blocked` makes the
CLI **hold the walkthrough** until the user's ▶ click, `ended` frees the next step. Commands return
at dispatch; nothing sleeps after its own clip.

## Considered options

- **A browser- or server-side playback queue** (queue clips, play sequentially) — rejected twice
  (spec + follow-up plan). It earns its complexity only for fire-and-forget *async* narration,
  which remains unobserved; persistent per-target caption boxes with Replay already make any
  interruption recoverable. Expect this to be re-proposed; this is the record of why not.
- **CLI-side cross-process state (a `~/.pflow` rendezvous file)** — rejected: the server is the
  natural shared rendezvous (it already holds the audio), and a real-home file is invisible to the
  test-isolation fixtures (parallel-test pollution).
- **Open-loop estimates without beacons** — falsified live, three times: post-dispatch sleeping
  left ~5s dead air (the next clip's synthesis); broadcast-time end estimates clipped the last
  words (the browser starts ~0.3–1s after broadcast); and an autoplay-blocked fresh window let the
  CLI narrate a silent room while reporting "sent to 1 window". Anything crossing into the physical
  world needs a feedback channel from the far end, not a model of it.

## Consequences

- This exercises ADR-0007's deliberately deferred arm — "browser→server apply-acknowledgments:
  additive later, when a concrete consumer exists" — for **narration playback only**. Point
  commands remain ack-less; the human is still the acknowledgment for pointing.
- `/api/health` permanently carries the two narration fields; `/api/narration` joins the mutating
  loopback exposure class (worst cross-origin case: flipping two floats/bools — benign per the
  ADR-0007 posture).
- The rendezvous is global, not per-workflow: one machine has one speaker.
- Residual inter-step gap is `max(0, synthesis_time − prior clip length)` — usually ~0s; a long
  line after a short clip can exceed 1s. Closing that fully would mean pre-synthesizing ahead,
  which is the rejected queue.
