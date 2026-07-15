# Braindump — main orchestrator (rolling tacit layer)

_Refreshed in place at each session close (`/close-orchestrator-session`, step 3 — the doctrine
lives there). Sessions: seeded 2026-07-12; refreshed at the 2026-07-12, 2026-07-13, session-04
(2026-07-13), session-05 (2026-07-15), and session-06 (2026-07-15) handoffs._

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
  writes. The working mechanism is the child hands back the exact files/message/head/action; root
  performs only that directly authorized commit/push/PR-comment/merge action, then resumes the
  same child for ownership and monitoring.
- **User challenge pattern — "step back / are we solving the right thing" (session-04, twice).**
  They caught me pattern-matching both times: proposing a file-perm "consistency fix" (traces/cache
  aren't credential stores — locking them is arguably wrong) and asserting "#516's premise is wrong"
  (plaintext at 0600 is the accepted CLI standard; OS-keychain is the non-urgent *upgrade*). Lesson:
  **verify the OBSERVED leak before designing the fix** — the whole secret-masking design arc was
  scoped against a leak that does NOT happen on the main path (a settings key never reaches the
  trace/output). Their probing IS the audit; hold the gate, concede plainly when overturned.
- **Mechanism — adversarial DESIGN review via Codex** (session-04, user-invoked). For a hard design
  call, get an independent critique of the *proposed design* (not a diff). Working zsh invocation:
  `codex exec --sandbox workspace-write -c 'approvals_reviewer="auto_review"' "$(cat prompt.md)"`.
  Traps: the user's PowerShell form uses backtick line-continuations (write it single-line for zsh);
  `--ask-for-approval` is NOT valid for `codex exec` (drop it — exec is non-interactive); output
  streams ~MB (redirect to a file, read the tail). It surfaced real flaws my own review missed
  (durable-provenance gap, three-seams-not-N). Local-only: that review + the session's searcher
  outputs live in `scratchpad/` (gitignored) — gone once this machine's temp clears.
- **Trap — a child agent's "watching in the background" is a lie; the orchestrator owns the wait**
  (session-06, hit ~3× on one PR). A lane-B/task agent that hands back "CI watch running in the
  background, I'll merge when green" has actually STOPPED — its watch cannot outlive it. Don't take
  the claim at face value: run your OWN background CI poll (`gh pr checks` until no `pending`) and
  resume the agent only for the terminal action (merge). Resuming just to re-watch dies again on the
  wait.
- **Transient API death ≠ tier exhaustion → resume the SAME agent, don't replace** (session-06). The
  limit-recovery rule (never resume an exhausted tier — it re-dies) does NOT apply to a "connection
  closed mid-response" drop. Check the worktree is clean/uncommitted, then SendMessage the same
  agent — context intact, cheap. Replacing it re-derives everything.
- **Trap — a PR review authored by `spinje` is the AGENT under the repo git identity, not the human
  user** (session-06). I nearly treated an inline review comment as a human review gate. The git
  user IS `spinje`; children post disposition comments under it. Read the body/author-association
  before assuming the human weighed in.
- **User applies the top-10% test to CI/infra, not just product code** (session-06). On a Chocolatey
  `499` blocking the Windows gate I proposed "add a retry"; they pushed back — "are you sure? what
  would a top-10% repo do?" — and the honest answer was *remove the flaky external feed from the
  critical path* (band-aid vs. root cause). Same governing-principle challenge as on product design.
  Sub-lesson: diagnose CI-infra failures at the seam (read the failing step's log) before assuming
  flake OR regression; an external-feed outage → wait it out, don't thrash reruns.
- **Failure mode — dismissing a REAL problem because its ORIGINAL framing went stale** (session-06,
  Task 94). I leaned "park it, the crash problem is mostly handled" — the user reframed to the live
  need (agents can't help *choose* a model). Guard both directions: the observed-problems rule stops
  over-building theorized problems, but a stale spec can also make a real need *look* theoretical.
  Re-derive the problem from today, not from the spec's old problem statement.
- **User pressure-tests a new CLI surface hard and iteratively — and demands consistency be VERIFIED,
  not asserted** (session-06, `pflow settings llm models` design). They serially caught surface
  incoherences (a status label that read as an imperative, a flag combo that made no sense,
  positional-vs-flag ambiguity) and asked "is this consistent across the CLI?" The move that
  satisfied it: grep the existing command conventions FIRST (positional-keyword filtering, no
  `--filter` anywhere, `--output-format` vs the legacy `--json`, the `mcp sync --all` XOR pattern)
  and design the new surface to match — don't invent a shape in isolation. Show-before-code with
  concrete mock output per iteration is how the design converged.
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
