# Braindump: Task 125 — escalation use case + the shared resume substrate (2026-06-02)

This is the SECOND braindump for Task 125. The first
(`braindump-openclaw-discussion.md`) covers the original action-approval framing and the
OpenClaw strategic context — **read it for strategy, but treat its technical assumptions as
superseded**: its "wrapper chain" and "shared store is JSON-serializable" assumptions are now
resolved/corrected in the `task-125.md` Reuse + Implementation Notes sections (verified this
session). This braindump captures what is NOT in any file — the conversation journey, the
user's words, the design landmines I flagged but didn't resolve, and the bigger picture this
work is one piece of.

**Don't re-derive what's now in the files.** `task-125.md` was substantially rewritten this
session (Two Use Cases, Architecture, Reuse, Known Hard Problems, Phasing, corrected
wrapper→inline integration, updated Dependencies). `task-164.md` (Resume Workflow From a
Failed Node) was created as the sibling. Every code claim in both carries a verified
`file:line`. Read both fully first. This file is the tacit layer around them.

---

## Where this came from (the journey — NOT in the files)

The user did NOT start by asking to improve Task 125. They opened a strategic discussion:
**"Task 125 vs Task 155, leading into a visual UI"** — because, while building the Task 163
plan-to-code harness, they hit a wall: *"It's very hard for me as a human user to understand
how this agentic workflow actually works and I NEED to have full control."*

The escalation use case and Task 164 are **downstream of that** — they emerged mid-discussion.
The Task 125 edits we made are ONE branch of a much larger tree. **If you only read
task-125.md, you'll miss that 125 is a leaf of a "see + control the agentic harness"
vision.** That vision is the user's real priority; HITL is a means to it.

The decomposition I built with the user (this is the load-bearing mental frame, and it's
NOT written in 125's file — it spans 125, 155, and an unfiled UI task):

> "Understand + full control" is FOUR distinct needs, not one:
> - **A. Static structure** — "what's wired to what, click to read prompts" → Task 155 (GraphModel) → web UI
> - **B1. Replay observability** — "what did this run do" → traces (mostly exists)
> - **B2. Real-time observability** — "watch it run live" → a transport upgrade on B1
> - **C. Intervention** — pause/approve/escalate → Task 125

And the **meta-insight that ties it all together** (say this to the user; they liked it):
there are really only **two substrates**, and 125/164/the-UI are thin layers over them:
1. **GraphModel + an event stream** (Task 155 work) → feeds static render, replay overlay,
   live overlay, AND the visual approval/escalation gate.
2. **checkpoint → restore → continue** (≈60% exists via `--only`) → feeds durable-125 AND
   Task 164.

This recurring shape — *one substrate, many triggers/renderers* — is how the user and I came
to think about the whole space. It's why escalation, approval, failure-resume, and the visual
gate keep turning out to be the same machinery wearing different hats.

---

## The user's mental model (their exact words — use them)

- On escalation (the new use case, verbatim): **"The agents need to surface genuine HARD
  decisions that will have a lasting impact on the product and architecture and that has
  surfaced during implementation or was missed during specification / planning. This is the
  usecase and without this the agent workflow cant probably ship."** — This is the heart of
  why 125 matters to them. NOT "approve before sending a Slack message" (that's the old
  framing). It's "the agent hit a fork above its pay grade; a human must decide."

- On its importance, hedged: **"you are right that this is a separate problem and arguably
  less important but I'm not sure about this."** — I resolved their uncertainty by splitting
  125 into **blocking** (ship-gating, cheap) and **durable** (deferrable). The escalation
  *blocking* slice is what "can't ship without"; durable resume is the deferrable part. Make
  sure they keep that distinction — it's what makes the importance question answerable.

- They breached an opacity wall I'd wrongly called impassable: **"claude code is writing
  .jsonl in .claude folder today so I could teoretically read that data from there to
  populate the ui if I want to."** — I had claimed claude-code nodes are black boxes
  ("blocking subprocess, nothing in between"). WRONG. The transcript is on disk, tailable.
  This matters for 125 because **the same .jsonl tail is a plausible live escalation-detection
  channel** AND for the UI (intra-agent observability). I conceded; you should too.

- On grounding: **"do you need to verify any assumptions or ambiguity using parallel pflow
  searcher subagents before we write to ground your insights in verified claims?"** — This
  user wants claims VERIFIED before they're written into specs. They explicitly invited the
  searcher verification. They will catch hand-waving. Every code claim in the two task files
  came from a searcher pass with `file:line`. **Do not add unverified claims to these specs.**

- Working style (consistent with the 163 braindumps, reconfirmed here): reasons from
  PROPERTIES not categories; "why is X?" is usually a catch (go verify, don't defend); prove
  the cheap/$0 path first; wants options + a recommendation, then decides; dislikes bloat and
  speculative features.

---

## Key insights you won't find in the files

### 1. The escalation SIGNAL mechanism is the first real design landmine — and the obvious approach is known-broken

task-125.md says "an agent-returned escalation marker." That glosses a real problem I flagged
but did NOT solve: **claude-code `output_schema` SOFT-FAILS** (Task 163's hard-won lesson —
agentic, subagent-spawning nodes tend to end on prose and fail a requested schema; the result
comes back as a raw string). So you **cannot reliably signal an escalation via `output_schema`.**

The likely-correct mechanism (mirrors 163's own patterns, NOT designed yet): the agent
**writes an escalation artifact to a file** (like the progress log) and a downstream `code`
node checks for it (the `isinstance(result, dict)` / file-exists guard pattern 163 uses
everywhere). This also fits 163's **artifact-replay fork model**: the agent escalates by
writing + returning, pflow halts, human decides, a fresh fork re-reads the artifact + the
decision. **This connects to Task 99 (Expose pflow Tools to Claude Code Node)** — the clean
version is a pflow-provided `escalate_to_human(...)` tool, but under the hood it's
write-artifact-then-return regardless. Resolve this before implementing escalation.

### 2. The decision FEEDBACK loop is undesigned

How does the human's choice re-enter the agent's work? I gestured "written back to the
plan/progress log, then continue/re-fork" but we never designed it. In 163's model the natural
answer is: **write the decision into the plan (it's a plan-gap resolution — amend the source
of truth) and/or the progress log, then re-fork the agent with a delta.** Writing it back into
the plan is the honest move (a re-run wouldn't re-ask). This is a 163-fork-model design task,
not a generic one. Untouched.

### 3. "Blocking needs no substrate" is verified — but ONLY in a TTY

Searcher A verified the engine is synchronous/single-threaded on the main thread, no output
redirection around the run, stdin free → it CAN pause in-place for `click.prompt()` and re-run
a node (via the existing `loop:` re-entry, `MAX_NODE_VISITS=100` cap) with no disk
serialization. **This is what makes blocking-125 independent of Task 164 and buildable first.**
BUT: non-TTY contexts (MCP server, piped stdin, CI, agent-invoked-as-subprocess) have nowhere
to prompt → a blocking prompt hangs. So non-TTY = auto-decide/fail OR fall back to durable
resume (= Task 164's substrate). Two placement gotchas Searcher A flagged: don't put a gate
inside a parallel-batch item (worker-thread TTY race), and a reject-and-re-ask loop must stay
under the 100-visit cap.

### 4. The implementation order, and WHY (the reasoning, not just the order)

**blocking-125 → 164 (builds the substrate) → durable-125.** 125 is NOT monolithic — it splits,
and 164 goes *between* the halves. The reasoning: the expensive foundational piece is the
checkpoint→restore→continue substrate; it's needed by durable-125 AND 164 but NOT by
blocking-125. Build it once in 164 (the general, HITL-free case) and durable-125 falls out as a
thin trigger ("stop at a gate" vs "stop at a failure"). **Idempotency (re-running a
partially-run node) is 164's burden ALONE** — no 125 path hits it (approval stops before the
node; escalation re-forks by design). Caveat I told the user: if they ever need durable/non-TTY
resume *first*, 164 moves to the very front and both 125 slices follow it.

---

## Assumptions & uncertainties

- **NEEDS VERIFICATION: the escalation signal via file-write + code-check actually works
  end-to-end with a claude-code agent.** It's the 163 pattern, so ~85% confident, but unproven
  for an escalation specifically. The output_schema path is verified-broken for agents (163).
- **NEEDS VERIFICATION (Searcher B flagged): conditional-branch divergence on resume.** A
  resumed run may take a different branch than the snapshot; branch-dependent state must
  resolve correctly. This is 164's verification target but also relevant to durable-125.
- **NEEDS VERIFICATION (Searcher A flagged): MCP server path truly has no TTY.** "Highly
  likely" from docs, not exhaustively traced. Design the non-TTY fallback against it.
- **NEEDS VERIFICATION: backward-edge routing for an `on-reject` re-ask.** Searcher A confirmed
  `loop:` re-runs the SAME node in-process, but if a gate uses a backward edge to re-run an
  UPSTREAM node, the parser's branch-target validation (`markdown_parser.py`) wasn't traced —
  verify the parser accepts the backward action edge.
- **ASSUMPTION: `restored_nodes` semantic tweak ("seeded AND not visited this run") is the
  only display-contract touchpoint for resume.** From Searcher B; the executing resume path
  doesn't exist yet, so this is "verified by analogy to the planner, not run."
- **UNCLEAR: does escalation belong only to the agentic-harness use case, or to generic
  workflows too?** We discussed it ONLY in the Task 163 context. A generic `llm`/`shell`
  workflow escalating is plausible but unconsidered. The current framing is harness-shaped.

---

## Unexplored territory

- **UNEXPLORED: the decision PAYLOAD format.** What exactly does the agent surface — options,
  tradeoffs, its recommendation, the "why I can't decide"? task-125.md says "structured data,
  not a printed string" (so it renders in CLI + UI), but the schema is undesigned.
- **UNEXPLORED: escalation CALIBRATION.** Flagged as the make-or-break (too eager defeats
  autonomy; too reluctant = the silent-bad-decision nightmare). It's a prompt-design problem
  with the shape of 163's review adjudication ("a finding is a claim to verify, not obey").
  Nobody has drafted the calibration prompt.
- **CLI surface collision (flagged, unresolved):** `pflow resume` is wanted by BOTH 125
  (resume a paused gate) and 164 (resume a failed run). Decide jointly whether one command
  serves both, or `--resume`/`--from-failed` flags. In both task files.
- **MIGHT MATTER: nested escalation.** Task 163 is a TREE of sub-workflows. An escalation
  raised *inside* a child workflow — does the parent pause correctly? Resuming *into* a child
  is explicitly OUT of scope for 164 v1 (dotted `--only` is rejected; child plumbing dormant,
  #443). Same limitation will bite nested escalation. Not addressed.
- **MIGHT MATTER: durable escalation token security** — the openclaw braindump raised this
  (signed/encrypted tokens). Still unaddressed; deferrable with the durable phase.

---

## The BIGGER open thread (don't lose this — it's the user's actual priority)

The whole conversation was about **seeing and controlling the Task 163 harness**, and there's
a **deferred sequencing decision the user never made**:

> **155 (extract GraphModel — UNBLOCKED, Option X landed, verified) → static web UI (unfiled
> task: React Flow, local server, click-to-read-prompts, run on demand) → live event overlay
> (a JSONL event sink + `pflow watch`; the progress callback already emits
> node_start/complete/cached/batch_progress but only to stderr; the trace is end-only,
> `workflow_trace.py:850`) → blocking escalation gate (visual).**

vs. alternatives (control-first; UI-only; stopgap). I offered to re-pose this as a clean
decision and the user kept going down the 125/164 path instead. **It is still open.** The user
explicitly wants a visual UI ("run in a react server locally on demand using something like
react flow", "clicking to read prompts, descriptions"). Task 125's "decision surface for CLI
and UI" bullet only makes sense in light of this. Bring this decision back up.

Also note: **a $0 stopgap exists today** — `pflow visualize <wf> --depth 5 --descriptions -o
out.md` renders the whole expanded harness tree as Mermaid (paste into mermaid.live). The UI is
the interactive/live version of exactly that. I mentioned it; unclear if the user tried it.

---

## What I'd tell myself starting over

1. **Lead with the two-substrates frame.** It took the whole conversation to crystallize
   "GraphModel+events" and "checkpoint→restore→continue" as the two things everything else
   layers onto. If you hold that from the start, 125/155/164/UI stop looking like four
   features and start looking like two substrates + thin layers.
2. **Verify before asserting — this user will catch you.** I was wrong about the .jsonl
   opacity wall and glib about "policy flip — tiny" / "~60%" / "process-died case" until the
   searchers forced precision. Six searcher passes grounded the final claims. The user
   *explicitly* asked me to verify before writing. Honor that reflex.
3. **The escalation signal mechanism is where this gets real.** output_schema is broken for
   agents (163). Solve the file-write-+-code-check (or Task-99-tool) signal first; everything
   else in escalation depends on a reliable "I need a decision" channel.

## Open threads (next steps not taken)

- Re-pose the deferred sequencing decision (155 → UI → live overlay → blocking gate).
- Design the escalation signal mechanism (landmine #1) and decision-feedback loop.
- CLAUDE.md roadmap does NOT list Task 164 yet (I deliberately didn't touch CLAUDE.md — it has
  its own update conventions; roadmap placement is the user's call).
- Nothing was committed. The user commits, never the agent (a hard rule in this repo).

## Relevant files & references

- `task-125.md` — rewritten this session (the authoritative spec; read it, don't re-derive).
- `task-164.md` — the sibling I created (full failure-resume spec).
- `braindump-openclaw-discussion.md` — strategy/OpenClaw context; technical assumptions STALE.
- `.taskmaster/tasks/task_163/` — the harness whose build surfaced all of this. The two 163
  braindumps + progress log are essential context for the escalation use case and fork model.
- `.taskmaster/tasks/task_73/` — DEPRECATED prior art for checkpoint/idempotency (read for 164).
- Task 155 (`task-155.md`) — GraphModel extraction; UNBLOCKED (Option X / `_scope.py` landed,
  `b3bad44a`). The pre-step to the visual UI.
- Verified source touchpoints (from the searcher passes, all in the task files with line refs):
  `runtime/engine/engine.py` (synchronous walk, `_run_only_snapshot`, `loop:` re-entry,
  `find_node_by_id`), `runtime/workflow_trace.py` (`seed_snapshot_into_shared:347`,
  `load_full_run_events:179` rejects failed traces, `save:850` end-only `default=str`),
  `execution/plan.py:_resolve_walk_start` (the seed+walk-from-K composition proof),
  `cli/commands/run.py:294-298` (trace saved in `finally`, graceful-failure only),
  `core/output_controller.py:348` (the existing progress event stream).

---

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points — especially (1) that
> Task 125 is one leaf of a larger "see + control the harness" vision built on two substrates;
> (2) the escalation use case is the user's real driver and its signal mechanism is an
> unsolved landmine (output_schema is broken for agents); (3) the build order
> blocking-125 → 164 → durable-125 and why; (4) the deferred 155→UI→live→gate sequencing
> decision is still open — then state you're ready to proceed.
