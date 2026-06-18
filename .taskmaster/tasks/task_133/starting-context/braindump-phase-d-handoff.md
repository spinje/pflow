# Braindump: Task 133 — post-A–C handoff (tacit knowledge only)

This is the stuff that is **NOT** in the four canonical docs. Read those for content; read this for *how the
work actually went, how to work with the user, and where the bodies are buried.*
- `task-133.md` = why/what + D1/D2/D3 · `context/adr/0007-…` = the decision · `implementation/implementation-plan.md`
  = the how + spike resolutions + Phase D contract + file:line · `implementation/progress-log.md` = the journey,
  deviations, reviews, and **6 critical gotchas** (read those gotchas — I won't repeat them here).

## Flag this first: the branch name is a lie
The worktree/branch is `feat/unified-node-storage` — that name reflects the **original, REJECTED** premise
(merge trace + cache into one content-addressed store). The work did the **opposite**: keep them separate, ship
a JSONL *transport* for the trace. The docs say the merge is rejected, but a future agent skimming the branch
name will be misled. Don't let it frame your thinking.

## How to work with this user (the highest-value thing here)
- **Trust-but-verify, hard.** They say "go ahead" but then drop checkpoints: *"Are you FULLY happy?"*, *"Any
  loose ends?"*, *"have you documented…"*. These are not rhetorical — when asked, **actually go hunt for your
  own holes.** Every single time I did, I found real gaps (a fragile discriminator, a dropped field, missed
  tests, an under-specified seam). They reward honest self-audit and will not accept reflexive "all good."
- **They expect you to have read EVERYTHING before forming a view.** I formed an initial position ("the task is
  deferred, nothing to build") and they corrected me with *"Did you read scratchpads/task-133/handoff.md?"* —
  which flipped the whole framing (the real plan was "build A–C in parallel with Task 168"). Do the full
  homework first; they test whether you did.
- **Reviews before AND after coding, and they pick the count: "3 best suited subagents."** They want you to
  *choose the right specialists*, not run the full 8-agent battery. For this subsystem the proven trio is
  **review-silent-failures + review-impact-completeness + review-test-fidelity** (+ **review-plan** at the plan
  stage). The reviews caught a real defect every round — **run the same discipline for Phase D.** Don't skip it.
- **Manual verification they can SEE and reproduce**, not "tests pass." Give copy-paste commands + real output.
- They gate docs/handoff on *genuine* confidence (*"update progress log when you are FULLY happy"*) and they
  care about the next agent — hence this braindump.
- **Their deepest priority (their words, repeated):** *"simplicity of the FINAL code, not how easy it is to get
  there"* + *"optimized for AI agents to understand and add features to"* + searchability is *"non-negotiable"*
  (greppable plaintext — they killed gzip earlier for exactly this). They'll accept a harder path (40 test
  edits, the D-stable trailer-now over a simpler header approach) for a cleaner/forward-compatible end-state.
  **Optimize the end-state, not the path.**
- They reason *with* you and reject premature building — **but they are not dogmatic about "defer everything."**
  Once the reasoning was solid they explicitly chose to *build* A–C now, accepting "foundation with no consumer
  yet," because Task 168 made the liveness direction concrete. Don't mistake their caution for "never build ahead."

## Process meta-learnings (my own errors, so you skip them)
- **Read the real engine code before trusting the plan's phase boundaries.** My plan put the *collector
  unification* in Phase B; only reading `engine.run`'s save/restore + the `record_trace`→`sub_workflow_events`
  embed chain revealed it belongs in **Phase D**. The phase lines were wrong until I read the code. For Phase D,
  read the actual collector lifecycle yourself before trusting any plan text.
- **Distrust your first instinct on format detection.** I confidently proposed `json.loads(whole_file)`
  parse-inference and called it "robust"; it was fragile, and the review forced the positive-marker design.
- The "use `pytest -m trace_files` to find every affected test" gotcha is in the progress log — the *meta* point
  is: I trusted my own hand-picked file list over the marker-based ground truth, and it cost a full review round.

## Environment / tooling friction (cost me real time)
- **Background bash stalls/contends** when several run at once, and `export HOME=…` was (correctly) denied — it
  would repoint the whole session. For manual e2e: use **`env HOME=$(mktemp -d) uv run pflow …`** scoped
  per-process, ONE at a time, and prefer a **single `uv run python` script** over chained `uv run pflow`
  subprocesses (those stalled mid-script for me).
- **System `python3` lacks pflow deps** (e.g. `jsonschema`). Use **`uv run python`** for anything importing pflow.

## Coordination with Task 168 (critical for Phase D / the overlay)
- Task 168 (the static React Flow UI) is being built **in parallel** in worktree
  `feat-workflow-visualization-static-viewer`. It is **static-only — it does NOT consume the runtime stream.**
  The **live overlay** (Phase D's actual consumer) is a *separate* increment that comes *after* 168.
- The shared, **READ-ONLY** seam is `NodeId = (node_id, ancestor_path)` (the "Runtime Overlay Join Contract" in
  `src/pflow/core/workflow/graph/CLAUDE.md`). 168 emits it; Phase D's events must *join onto* it. **Neither side
  may change it unilaterally** — if Phase D needs to alter the identity scheme, that's the one thing to sync with
  whoever owns 168.

## Git / commit state — sort before committing
- **Nothing is committed.** Staged vs unstaged is mixed (some Phase B was staged early; Phase C edits are
  unstaged). Reconcile before committing the Task 133 set.
- **A stray dirty file is NOT mine:** `.taskmaster/tasks/task_18/documentation/template-system-practical-example.py`
  shows modified in `git status` and I never touched it (pre-existing worktree state or auto-touched). `git
  checkout` / exclude it from the Task 133 commit.

## Unexplored / suspicions
- **MIGHT MATTER:** `default=str` in `save_to_file` is pre-existing lossy behavior (Path/datetime/set → str,
  one-way). **Nobody has audited which non-JSON-native leaves actually appear in production traces.** If Phase
  D's overlay ever needs faithful round-trip of such data, this bites — and the round-trip "identity" only holds
  for JSON-native data because of it.
- **CONSIDER:** the MCP server also writes traces via the same `save_to_file`, but I only verified it *surfaces
  the path*, not content. The MCP execution path writing/reading JSONL was **not** e2e-tested through the MCP
  server specifically (low risk — same writer — but unexercised).
- **CONSIDER:** `verify.sh` (Task 159 baseline) is pre-drifted; I deliberately skipped it (the suite + real-CLI
  e2e were stronger). Don't expect a clean baseline if you reach for it.

## For the next agent (Phase D)
- Start: read `handoff.md`, the progress-log's 6 gotchas, plan §3 ("Deferred to Phase D") + §6, ADR-0007 — then
  read the actual collector code before touching anything.
- **The hard, untouched crux is the collector unification:** per-sub-workflow collectors → one run-scoped
  collector, threading a single `run_id`/`parent_id`/`seq` across the `engine.run` save/restore + the
  `WorkflowExecutor` boundary, with `seq` assigned at *emit* time under the batch `ThreadPoolExecutor`. A–C
  deliberately avoided all of this (it derives correlation at *save* time from the already-built tree). Budget
  for it — it's the invasive piece, and spike #2's no-lock design becomes load-bearing *here*, not in A–C.
- **Do not re-pin the D1 span taxonomy** (batch-item promotion, retry-as-attempt, loop-as-span) until the
  overlay is real enough to validate it (spike #4). The on-disk format A–C established does **not** change in
  Phase D — only *when* correlation is assigned and *how* events are collected.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and
> understood by summarizing the key points, then state you're ready to proceed.
