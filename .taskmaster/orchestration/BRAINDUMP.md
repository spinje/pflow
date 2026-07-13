# Braindump — main orchestrator (rolling tacit layer)

_Refreshed in place at each session close (`/close-orchestrator-session`, step 3 — the doctrine
lives there). Sessions: seeded 2026-07-12; closes 2026-07-12 and 2026-07-13._

Predecessor tacit layer: the **Genesis** section at the bottom of this file (2026-07-02) —
HISTORICAL; its process claims are superseded by ORCHESTRATION.md, its working-style observations
were absorbed into the command's "Working with the user".

- **The web UI is first-class product, not a dev tool.** I framed it as "a dev tool" to skip
  loudkult's UI ruling and the user hard-stopped it ("pflows web ui is not a web tool, and all
  ui should be done by fable… and verify everything"). Lesson shape: never infer a surface's
  importance from its architecture (local server ≠ low stakes) — the ruling is DECISIONS #8;
  the sensitivity behind it (UI quality matters to them, everywhere) is the tacit part.
- **When porting an artifact from another repo, port its WIRING too** — grep the source repo for
  references to the artifact before declaring the port done. I wrote the close skill without
  checking how loudkult's command invoked it; the user had to point ("see how its mentioned in
  the loudkult docs"). One `grep -rn <name>` would have caught it.
- **Mechanism that worked — cross-file coherence audit:** grep `DECISIONS #` across
  ORCHESTRATION + all agent defs, then check each def's standing rules against the lane rules.
  Caught a real contradiction (lane B's merge-it-itself vs the def's flat "never merge") that
  both writing passes missed. Run it after any multi-file process edit.
- **User correction — visibility is not deletion.** When they said they did not want compatibility
  edits committed because they wanted to see them, I wrongly erased the commit and working diff.
  Their correction: *"I asked what you did, I just wanted to see it."* Leave reviewable changes
  visible; explain them; do not infer discard.
- **User correction — protect the orchestration boundary.** *"I meant for the agent implementing
  this to do that, you are an orchestrator."* Main relays review work to the same implementer;
  it verifies PR/CI/merge seams, not implementation comments.
- **Codex approval seam:** relayed user approval may be rejected in child transcripts for external
  writes. The working mechanism is root performs only the exact directly authorized push/PR/
  rerun/merge action, then resumes the same child for ownership and monitoring.
- **RESOLVED 2026-07-13:** the pre-existing `.claude/agents/task-planner.md` `model: opus` edit —
  previously flagged local-only and contradicting the Fable planner policy — was committed by the
  user (`647d86f9` "dont use fable as default for subagents"). Planners now route Opus; scope is
  planners only (DECISIONS #3 amended; #8 UI→Fable and #9 lane-B opt-in stand). No longer
  local-only.
Note to next agent: read this file fully, summarize it to yourself, then proceed.

---

# Braindump: the orchestration system's genesis (2026-07-02)

> Companion to the `/start-orchestration` command (the "kickoff" this doc refers to throughout;
> promoted from `orchestrator-kickoff.md` on 2026-07-08) + `orchestrator-progress-log.md`, written
> by the session that created them. Zero overlap intended: the kickoff = the role, the log = the state, the
> task-125 braindump = that task's tacit layer. This file = **why the system is shaped this way,
> what's untested, and the homeless facts** — the context a future session needs to *maintain or
> evolve* the system rather than operate it.

## Genesis — the user's framing (verbatim)

*"You have been essentially working as an orchestrator for the pflow repo"* — the role was
recognized **post-hoc**, after ~3 weeks of it emerging organically, and the ask was to make it
reproducible: *"Make the 'kickoff prompt' for starting this process as general as possible, the
context of exactly what tasks exists, what is done exactly lives in a separate
orchestrator-progress-log.md."* Generality of the kickoff was THE requirement.

The reference (and anti-pattern) is the sibling file in their other repo:
`/Users/andfal/projects/loudkult/loudkult/.taskmaster/tasks-orchestration/orchestrator-handoff-2026-06-30.md`.
It's good on the tacit layer but **mixes evergreen role with a dated state snapshot** (hence its
dated filename) — the pflow split exists specifically to fix that. Same user, same working style
across both repos; cross-pollination is intended.

## Design calls and their approval status

Of the four design questions I posed, the user explicitly ruled only on **location**
(`.taskmaster/orchestration/`). The other three — the log's `Now`-edited-in-place + append-only
shape, the kickoff being *fully* general (no task numbers at all), and the session-end
self-maintenance duty — were **my calls accepted implicitly** via "think hard then write."
ASSUMPTION: they're right; but they're revisable without ceremony if the shape chafes in use.

## The system is UNTESTED

- The kickoff has **never booted a fresh session**. Its first real use is its first test — expect
  gaps, and use the built-in mechanism (propose kickoff edits when the *process* changes) to fix
  them rather than working around silently.
- RESOLVED 2026-07-08: the **invocation mechanism** is the `/start-orchestration` slash-command
  (promoted from the kickoff file). Originally left open — whether to stay a pointed-at file or
  become a command.
- CONSIDER: back-porting the kickoff/log split to loudkult once it proves itself here.

## Homeless facts (nowhere else)

- NEEDS VERIFICATION: commit `47f4fb21` ("chore: use fable for certain subagents") — the user
  enforced the fable rule somewhere in repo config; never inspected. Agent-model defaults may
  already be fable, making the kickoff's rule belt-and-braces.
- The user's stated alternatives were *"sonnet 5 or fable"* — sonnet-5 doesn't exist in the Agent
  tool's enum today, so fable is the practical rule; if a sonnet-5 alias appears, it's
  pre-sanctioned.
- The three orchestration files (kickoff, log, this) are **uncommitted** as of writing; everything
  else from the session is in `c02a4bde`.

## How the role's norms actually crystallized (they look timeless in the kickoff; they're not)

The kickoff presents its rules as settled; each was minted mid-session from a real event: the
worktree-fleet pattern emerged from the first parallel-issues question; the delegation norm from
an explicit correction; the fable rule arrived as an interrupt (a live sonnet agent was killed
mid-run); the spec-refresh ritual was invented when 164/171 proved stale under their substrate;
the step-back audit became standard after the user asked it twice. **Implication: more norms will
emerge. The session-end duty (fold process changes back into the kickoff) is how the system
learns — treat it as load-bearing, not paperwork.**

## Maintenance advice from the author

- The log's `## Now` will bloat. Prune each session with the test used at birth: *"would a fresh
  orchestrator be hurt without this line?"* The user notices and values concision ("great job at
  keeping it concise") — and separately audits for omissions ("make sure you haven't missed
  anything important"). Expect both pressures; they're the spec.
- The kickoff's **failure-modes section is its highest-value part** — keep it earned: only
  mistakes that actually happened, never hypotheticals.
- The user reviews these artifacts personally. Write for them first, the next agent second.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
