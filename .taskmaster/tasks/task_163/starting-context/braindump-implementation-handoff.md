# Braindump: Task 163 implementation handoff (Phases 1–4 built)

This is the SECOND braindump. The first (`braindump-harness-design.md`) covers the *design
session*. This one covers the *implementation session* — and deliberately does NOT repeat the
progress log (which has the full as-built record), the task-163 As-Built Amendments (the
authoritative current design), or the design braindump. Read all three first. This file is only
what's still in my head and written nowhere else.

## Where I am

v1 is built, validated end-to-end on the OLD topology (run 6, $4.23, verified good), then rewired
to the review-once topology the user corrected to. The rewire is verified by a $0 skeleton test but
**has not had a paid live run.** Everything is uncommitted on `main`.

The harness genuinely works — it produced correct, well-tested code with real review/verify that
caught real edge bugs. I am confident in the *design*. My uncertainty is narrow and specific (below).

---

## THREE real gaps I noticed but we never fixed (my most valuable contribution)

These are not in any file. They are things I'd be furious at myself for not flagging. None blocked
v1, but all three are real and the next agent (or the next live run) will likely hit them.

### 1. The review-once rewrite may reintroduce the context problem segmentation exists to solve

This is the one I'm most uneasy about, and it's subtle. We segment *implementation* specifically
for context-window management — each segment is a fresh agent so context never grows on a large
plan. **But the rewire moved review to be WHOLE-CODEBASE, once, at the end.** So on a genuinely
large plan (the real use case — task_160 was 488 lines / 7 phases), the single `review-round` agent
must `git diff` the ENTIRE implementation and review it in one context. That is exactly the
big-context situation we segmented implementation to avoid — just relocated to the review stage.

We only tested on a tiny 2-phase plan, where the whole diff is small, so this never surfaced. On a
real plan it might: the review agent could blow context reading a huge diff, or review shallowly.
**NEEDS VERIFICATION on a real (large) plan.** If it bites, the resolution is probably the deferred
`review_after` mechanism OR a "review per segment-group but in fresh context" hybrid — i.e. the
per-segment review the user moved away from might have been partly right for *large* plans. The
user's reasoning (segmentation = context mgmt, review = once) is sound for small/medium plans;
whether it holds for large ones is genuinely untested. Don't assume it does.

### 2. `final-review` is labeled "read-only" but that is NOT actually enforced

We made final-review a "read-only gate" and removed `Edit`/`Write` from its `allowed_tools`,
leaving `Bash, Read, Glob, Grep, Task`. **But `Bash` can write files and `git commit`.** So an
agent that decides to "just fix this one thing" can still edit (via `sed`/`tee`/`>`) and commit.
The read-only property rests ENTIRELY on the prompt instruction, not on tool restriction. This
matters because the whole reason final-review runs *after* verify is the guarantee "nothing changes
code after verify." If final-review edits via Bash, that guarantee silently breaks — and it's the
exact class of soft-guarantee-vs-hard-guarantee the user dislikes (cf. the cap "soft instruction"
discussion). NEEDS VERIFICATION that final-review actually stays hands-off in a live run; if it
doesn't, you need a real enforcement mechanism (a `disallowed_tools` for `Bash(git commit:*)` /
write-ish bash, or a post-stage `git` check that nothing changed, or accept it can edit and move
verify back to last). I'd lean: add a check after final-review that the tree didn't change, hard-stop
if it did.

### 3. `verify` leaves scratch test files in the repo → they get committed → they pollute the PR

In runs 5 AND 6, the verify agent created adversarial scratch files in the repo root —
`break_test.py`, `break_test2.py`, `break_test3.py`, `final_adversarial_test.py`,
`verify_none_break.py`, `adversarial_test.py`, `final_adversarial.py` — and they ended up in the
repo (some committed to the work branch). These are throwaway probing scripts, NOT the regression
tests we want kept. **A real PR would include this junk.** The verify prompt says "add regression
tests" but doesn't distinguish "a clean regression test that belongs in the suite" from "scratch
files I used to poke at it." Fix: tell verify to either (a) put scratch probes in a tmpdir outside
the repo, or (b) clean them up and fold only genuine regression tests into the project's test
location, and NOT commit scratch files. Verify it against `git status` after the verify stage.

---

## User's mental model (this session's additions to the design braindump)

- **Cost is a live constraint, watched to the cent.** The user stopped mid-Phase-2 with *"im
  spending real money for no reason"* — which is what triggered the billing-leak discovery (#455).
  The lesson the user operates by: **prove everything possible for $0 first** (skeleton/code
  stand-ins), spend on agents only when the $0 path is exhausted. Always offer the cheap path. When
  I proposed "fold remaining leaves into one integrated run instead of 4 paid isolation runs," that
  framing (fewer paid runs) is what they want. Batch paid work; never burn a run casually.

- **The user's "why is X?" is almost never a question — it's a catch.** This session, every "why"
  was them spotting a real problem before I did: *"why is this agent outputting its findings?"*
  (→ the plan-review/fix merge), *"why are we running review-fix after each segment?"* (→ the
  whole review-once rewrite), *"how can it cost $0?"*, *"how can it still be running?"* (→ surfaced
  the output-buffer-lag + non-determinism). When the user asks "why," STOP and treat it as "I've
  found something wrong" — go verify, don't explain/defend. They were right every single time, again.

- **"task tool" means TodoWrite (the internal step list), NOT the Task subagent tool.** They
  clarified this explicitly. Their mental frame is always "how do *I* steer agents manually" — the
  harness is automating *their* hands-on technique. When they reference an agent capability, map it
  to the manual move they make, not the API name.

- **They distinguish "context management" from "review" as orthogonal axes.** The crux correction:
  *"segmentation is for context-window management during implementation; review happens once at the
  end."* I had conflated them (built per-segment review). Hold these separate — it's load-bearing to
  how they think about the whole harness.

- **Worktree-as-isolation is their instinct, and it's right.** When I proposed a "don't run on your
  own repo" guard, they immediately reframed: *"it can be the harness's own repo if I have it
  checked into pflow, create worktree then run it from there."* The correct guardrail is clean-tree,
  not own-repo. They think in terms of git worktrees as the natural isolation primitive (same as the
  swarm). Don't add guards that block legitimate worktree dogfooding.

---

## Hard-won operational knowledge (cost me real confusion; not in any file)

- **Background run output LAGS the real state — trust git, not the output file.** When I checked a
  running e2e, the buffered output still showed `review-round...` while `git log` already showed
  final-review had committed. I briefly thought it was hung; it wasn't. For any live run: check
  `git -C <repo> log` and the progress-log file for ground truth, NOT the captured stdout buffer,
  which flushes only periodically.

- **breakdown is non-deterministic → cost and shape vary run-to-run.** Run 5: breakdown chose 1
  segment ($3.87). Run 6, SAME plan: 2 segments ($4.23, ~2x the review work). This is expected LLM
  variance, not a bug. Don't be alarmed by a run costing more or running longer than the last.
  Rough scale: a small 2-phase plan ≈ $4 and ~15–22 min end-to-end. A real plan will be more.

- **"2 segments = 2x work" was MY imprecision, and the user caught it.** Accurate: more segments
  adds more *review-fix passes* (the priciest stage), not 2x of everything — final-review and verify
  run once regardless. (This was under the OLD per-segment-review topology; under the NEW review-once
  topology, segment count affects only implement cost, since review is now whole-codebase once.)

- **Run the harness under REAL HOME, with explicit `repo_dir`.** Two traps I hit:
  (a) `HOME=/private/tmp/pflow-test-home` (the pflow-sandbox-testing recipe) breaks subscription
  auth — the Keychain creds aren't reachable → "Not logged in." That sandbox HOME is for *pytest*
  only, never for running the harness. (b) Without explicit `repo_dir`, `resolve-repo` defaults to
  git-root-of-cwd; if you launch from the pflow dir, it targets pflow. Always pass
  `repo_dir=<target>`.

- **The auto-stage hook stages Writes.** It bit the precursor and will bit you — `git status` before
  any commit and unstage anything you didn't intend. NEVER commit unless the user explicitly asks
  (the ship agent autonomously committing pflow's own work, commit `7fe0c25d`, was a real incident
  this session — I had to `git reset --soft` to undo it).

---

## Assumptions & uncertainties

- **NEEDS VERIFICATION (the big one): one paid live run of the CURRENT (review-once) topology.**
  Run 6 was the OLD topology. The new flow is proven only by the $0 skeleton test + individually-
  proven leaves. ~85% confident it runs clean; the integration of the new whole-codebase review loop
  with real agents is the unproven part. Do this run against a throwaway GitHub repo so it ALSO
  tests real-remote `ship`/`gh pr create` (never tested through — run 6's local repo had no origin).

- **ASSUMPTION: the review-fix agent picks good lenses from the available set.** In the one isolation
  test it deployed sensible lenses and adjudicated well (dismissed false positives, removed a
  scope-violating function). But that was a tiny change. On a big diff, whether it picks the RIGHT
  ~4 of 7 lenses is unverified at scale.

- **ASSUMPTION: the repo's 8 `review-*.md` lenses all work as claude-code subagents.** Verified TWO
  (`review-silent-failures`, `review-test-fidelity`) work via the Task tool. The other 6 are assumed
  to work the same way (same file format). Probably fine; not all individually exercised.

- **UNCLEAR: whether `plan-review-fix` editing the plan IN the target repo is right.** It edits the
  plan file in place and (in run 6) the plan lived in the target repo so the edit got committed onto
  the work branch. If the plan lives in `~/.claude/plans/` (the user's stated case), plan-review-fix
  would edit a file OUTSIDE the repo — does that commit? does it matter? Untested with an
  out-of-repo plan. The plan-location-vs-repo independence (As-Built #5) is wired but only tested
  with the plan INSIDE the repo.

---

## Unexplored territory

- **UNEXPLORED: the swarm refactor (v1.1).** `execute-plan` was deliberately built
  invocation-agnostic so `parallel-planner-review` can call it per-issue. Never started. The #188
  batch-input-coercion caveat (per-item fields arrive as strings) lands at that tier — verify-flagged
  in the progress log.

- **UNEXPLORED: README regen-and-diff guard.** The README is generated by `pflow visualize` but
  nothing enforces regeneration — it can go stale (same open follow-on the precursor has). Generation
  caught a real drift THIS session (the find-repo text), proving the risk is live.

- **MIGHT MATTER: prompt caching for the review lenses.** All review-fix rounds re-send the same plan
  + diff context; never cached. We dropped caching early because reviews must be agents and caching is
  llm-only — but the whole-codebase review re-reads the full diff every round, which on a big plan is
  expensive and uncached. If cost on real plans is a problem, this is where it lives.

- **MIGHT MATTER: what happens when verify or review-fix genuinely CAN'T fix something.** We tested
  happy-ish paths. The "cap reached with unresolved real findings" case (the user's view: rare, agent
  converges in practice) is unobserved. The ship agent surfaces concerns into the PR — but only if the
  upstream agents wrote them to the progress log. Untested under genuine failure.

- **CONSIDER: `implement-chunk` is now a one-real-node sub-workflow** (implement + a code guard).
  It's borderline whether it still earns being its own sub-workflow vs being inlined into the segment
  loop. Kept separate for the v1.1 swarm reuse + isolation, but if it never grows, inlining is simpler.

---

## What I'd tell myself starting over

1. **Don't trust the body of `task-163.md` — trust the As-Built Amendments at its top.** The original
   design text has several decisions that changed (per-segment review, find-repo, breakdown-as-llm,
   verify-last). I left the body intact as the design record and put corrections on top. A skim of the
   body will mislead you. (This is itself a lesson: the spec drifted because I recorded decisions as
   we went, and the user corrected fundamentals LATE — review topology changed at the very end.)

2. **The leaves are all individually proven; the risk is integration of the rewired flow.** Don't
   re-test the leaves. Spend the next paid run on the whole new topology, once, end-to-end.

3. **Every Phase-3 run found a real bug a static check missed.** "Validates ≠ runnable" is not a
   slogan here — it's the literal pattern (6 runs, ~6 distinct integration bugs). Trace multi-segment,
   multi-round, with real-ish state. The skeleton test does this for $0 — extend it before trusting
   any structural change.

4. **The three gaps at the top of this file are real.** I'd fix #3 (verify scratch files) and #2
   (final-review not truly read-only) before the next live run — they're cheap and they affect the
   PR quality / a stated guarantee. #1 (review context on large plans) needs a real large-plan run to
   even observe.

---

## Relevant files & references (beyond what's already linked in the log/spec)

- The undo I did: erroneous ship commit `7fe0c25d` in pflow was removed via `git reset --soft HEAD~1`
  + unstage. If anything looks off in pflow's own history near `ac479cfd`, that's the context.
- Stale skeleton: `.taskmaster/tasks/task_163/implementation/skeleton/` is the OLD topology, marked
  `STALE-DELETE-ME.md`. The live $0 guard is `tests/test_integration/test_plan_to_code_harness.py`.
- The throwaway test repos I used: `/private/tmp/t163-e2e`, `/private/tmp/t163-run6` (run-6 artifacts,
  with the junk verify files visible — good evidence for gap #3). May still exist.
- Spike files: `/tmp/t163-spikes/` (S1–S4 + leaf isolation tests). Reference templates.

---

## For the next agent

- **Start by** reading `task-163.md` (As-Built Amendments FIRST), the full progress log, the design
  braindump, then this. Then read the actual harness files — don't reconstruct from memory.
- **The user cares most about:** faithfully automating THEIR process; not wasting money (prove $0
  first); honest/non-drifting artifacts; and being corrected when wrong (they will catch you).
- **The single next action:** ONE paid live e2e of the current review-once topology against a
  throwaway GitHub repo (real HOME, explicit `repo_dir`) — closing both the rewire-unverified gap and
  the real-remote-ship gap at once. But FIRST consider fixing gaps #2 and #3 (cheap, improve that
  run's value). Get the user's go-ahead before spending — they'll want to.
- **Don't** trust the spec body over the amendments; re-test proven leaves; run under the sandbox
  HOME; commit anything without being asked; build the deferred `review_after` flag / HITL / caching
  speculatively; or believe a green `--validate-only` means it runs.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points — especially the three unfixed gaps
> (whole-codebase review context on large plans; final-review not truly read-only; verify scratch
> files polluting the PR) and the working style (the user's "why" = a catch; prove $0 first; trust
> the As-Built Amendments not the spec body) — then state you're ready to proceed.
