# Braindump — main orchestrator (rolling tacit layer)

_Tacit residue ONLY: what exists in no other file. Process = `ORCHESTRATION.md`; settled
decisions = `DECISIONS.md`; state = `CURRENT-STATE.md`; journey = `sessions/`. The test for every
line here: **"could the next agent find this by reading files?"** If yes, it gets cut._

_**Read these as LEADS, not as verified truth** — verify before propagating. Organized by theme,
not by session. `(sNN)` tags mark which session a line came from, for recency and supersession.
**When you add to this file, merge into the section that owns the theme — do not append a dated
one.** Refreshed in place at each session close (`/close-orchestrator-session`, step 3 — the
doctrine lives there). Sessions: seeded 2026-07-12; refreshed through session-07-continued
(2026-08-15)._

Predecessor tacit layer: the **Genesis** section at the bottom of this file (2026-07-02) —
HISTORICAL; its process claims are superseded by ORCHESTRATION.md, its working-style observations
were absorbed into the command's "Working with the user".

## 1. The user — their words, their moves

- **The web UI is first-class product, not a dev tool.** I framed it as "a dev tool" to skip
  the sibling programme's UI ruling and the user hard-stopped it ("pflows web ui is not a web tool, and all
  ui should be done by fable… and verify everything"). Lesson shape: never infer a surface's
  importance from its architecture (local server ≠ low stakes) — the ruling is DECISIONS #8;
  the sensitivity behind it (UI quality matters to them, everywhere) is the tacit part.
- **User correction — visibility is not deletion.** When they said they did not want compatibility
  edits committed because they wanted to see them, I wrongly erased the commit and working diff.
  Their correction: *"I asked what you did, I just wanted to see it."* Leave reviewable changes
  visible; explain them; do not infer discard.
- **User correction — protect the orchestration boundary.** *"I meant for the agent implementing
  this to do that, you are an orchestrator."* Main relays review work to the same implementer;
  it verifies PR/CI/merge seams, not implementation comments.
- **User challenge pattern — "step back / are we solving the right thing" (s04, twice).**
  They caught me pattern-matching both times: proposing a file-perm "consistency fix" (traces/cache
  aren't credential stores — locking them is arguably wrong) and asserting "#516's premise is wrong"
  (plaintext at 0600 is the accepted CLI standard; OS-keychain is the non-urgent *upgrade*). Lesson:
  **verify the OBSERVED leak before designing the fix** — the whole secret-masking design arc was
  scoped against a leak that does NOT happen on the main path (a settings key never reaches the
  trace/output). Their probing IS the audit; hold the gate, concede plainly when overturned.
- **User applies the top-10% test to CI/infra, not just product code** (s06). On a Chocolatey
  `499` blocking the Windows gate I proposed "add a retry"; they pushed back — "are you sure? what
  would a top-10% repo do?" — and the honest answer was *remove the flaky external feed from the
  critical path* (band-aid vs. root cause). Same governing-principle challenge as on product design.
  Sub-lesson: diagnose CI-infra failures at the seam (read the failing step's log) before assuming
  flake OR regression; an external-feed outage → wait it out, don't thrash reruns.
- **Failure mode — dismissing a REAL problem because its ORIGINAL framing went stale** (s06,
  Task 94). I leaned "park it, the crash problem is mostly handled" — the user reframed to the live
  need (agents can't help *choose* a model). Guard both directions: the observed-problems rule stops
  over-building theorized problems, but a stale spec can also make a real need *look* theoretical.
  Re-derive the problem from today, not from the spec's old problem statement.
- **They run this system's own gate prompts on YOU (s07 — pflow-earned; sibling standing).**
  *"So you are FULLY happy? Any loose ends right now?"* and *"have you read all current reviews
  on the pr?"* — answer by GOING LOOKING (that pass found five real loose ends, including the
  #14 auto-reviewer gate I had skipped while declaring the PR ready). They audit whether a gate
  RAN, not just what shipped.
- **User pressure-tests a new CLI surface hard and iteratively — and demands consistency be VERIFIED,
  not asserted** (s06, `pflow settings llm models` design). They serially caught surface
  incoherences (a status label that read as an imperative, a flag combo that made no sense,
  positional-vs-flag ambiguity) and asked "is this consistent across the CLI?" The move that
  satisfied it: grep the existing command conventions FIRST (positional-keyword filtering, no
  `--filter` anywhere, `--output-format` vs the legacy `--json`, the `mcp sync --all` XOR pattern)
  and design the new surface to match — don't invent a shape in isolation. Show-before-code with
  concrete mock output per iteration is how the design converged.

_Lines tagged `(sibling, s07)` were imported from the sibling programme's tacit layer in the
re-audit (DECISIONS #22) — same user, empirically earned THERE; imported-not-earned here (#19)._

- **(sibling, s07) The user stages changes themselves to read incremental diffs** — a staged
  tree is their normal working state: never reset/unstage to "clean up"; staged ≠ about to
  commit; `git commit <pathspec>` is the safe shape; fresh `git status` at every commit and
  launch, never from memory.
- **(sibling, s07) A model-swap mid-session is a REVIEW move, not capacity** — expect it on a
  design fork you already analysed; re-derive from evidence, don't defend the framing. On
  "anything to think through before I switch you?", write pending decisions + their settled
  handling into the session file BEFORE the swap. A downgraded orchestrator degrades its
  decision authority too: park borderline 2–3/5 calls, close conservatively.
- **(sibling, s07) They prune your pending-actions list and the pruning is a ruling** — carrying
  someone else's to-do list is not diligence; surface once, then ask whether it's still yours.
- **(sibling, s07) Cost the zero-build option before designing** — their first move on a scope
  gap is the existing surface that already covers it, and they're usually right. Twin: "why is
  there a max in the first place?" — state what a constraint is FOR before working around it.
- **(sibling, s07) Delegation triggers: YOUR uncertainty (not task size), and SHELF LIFE** —
  one-shot verification reading that won't be needed again never enters this window; hand it to
  a searcher/fork.
- **(sibling, s07) At every major ruling, produce the claims-risk inventory unasked** — rank the
  load-bearing claims by damage × evidence-thinness, delegate the probes as ONE battery,
  per-claim VERIFIED/REFUTED/PARTIAL.
- **(sibling, s07) Bad-history posture: a module with an n≥3 fix-is-the-risky-artifact record
  reverses the cost calculus** — offer the heavier shape (planner / full task) unprompted.
  **Probe-spend posture:** a bounded probe that settles a load-bearing premise beats an
  inference — cap stated at launch, counted, reported; and research scoped to "make it work" is
  not research scoped to "map what it can do" — a task needing both must be asked for both.
  (Both recorded as posture; promote to a row on the first real pflow instance.)

## 2. Claims and their tells — verify before relaying

- **Own overturn (s07): "ready to merge" is a CHECKLIST claim, never a feeling** — CI green on
  the FINAL head + #14 auto-reviewer dispositions + state docs true. I declared readiness with
  the reviews unread. Sub-trap, same session: a CI watcher parsing `gh pr checks` tabular output
  with `awk $2` reads green through noise (check names contain spaces) — parse `--json` with
  python/jq, and re-measure any watcher verdict before acting on it.
- **Trap — a PR review authored by `spinje` is the AGENT under the repo git identity, not the human
  user** (s06). I nearly treated an inline review comment as a human review gate. The git
  user IS `spinje`; children post disposition comments under it. Read the body/author-association
  before assuming the human weighed in.
- **Trap — a child agent's "watching in the background" is a lie; the orchestrator owns the wait**
  (s06, hit ~3× on one PR). A lane-B/task agent that hands back "CI watch running in the
  background, I'll merge when green" has actually STOPPED — its watch cannot outlive it. Don't take
  the claim at face value: run your OWN background CI poll (`gh pr checks` until no `pending`) and
  resume the agent only for the terminal action (merge). Resuming just to re-watch dies again on the
  wait.
- **(sibling, s07) A subordinate's VERIFICATION REPORT is still a claim** — "I independently
  re-read all six and confirmed" has been wrong for two of six; corrections come from agents
  that EXECUTED, not read. Same family: a harness failure-notification's excerpt is not the
  agent's final state — ground-truth `git log` in the worktree before ordering a relaunch (an
  agent reported as "produced essentially nothing" had committed the complete phase).
- **(sibling, s07) "It contradicts a settled ruling" is the one sentence that stops work without
  anyone re-reading the ruling** — source it to the ruling's TEXT before it travels (which
  decision, and does the fix negate its rationale?).
- **(sibling, s07) Re-rate a producer's own 1–2/5 severity riders when they touch the surface its
  fix changes** — a producer is least neutral exactly where it decided not to build.
- **(sibling, s07) A note classifying an anomaly as HARMLESS is the least-tested inherited
  claim** ("harmless" removes the prompt to look further) — spend the one probe that checks the
  SYSTEM it's attached to, not the artifact. Cousins: an external-party gate is the least-tested
  blocker (name what the answer could invalidate; if nothing, it's not a gate); an inherited
  sequencing/timing claim is re-derived at proposal time and labeled hard-dependency vs
  someone's priority call.
- **(sibling, s07) A number travels WITH its basis (n, what the sample is, bias direction) or it
  does not travel**; a count states its member definition; a probe + an impression are not a
  measurement — run the grouped query.
- **(sibling, s07) Fold hygiene, before writing any durable rule:** does it already EXIST
  (un-applied ≠ missing — a restatement taxes every reader)? am I naming the MECHANISM or a
  CARRIER (a rule feels sharp precisely because the carrier is concrete)? does it state its
  BOUNDARY (a constraint without one reads as a general prohibition)? and when two independent
  agents' observations INVERT, delete the ranking rather than pick a side. Readership/timing
  test for placement: who reads this file, can they act on it, have they already decided by the
  time they read it — skill bodies are read at the moment of use, so upstream-shaping content
  there is structurally too late.

## 3. Running the machine — recovery, runner seams

- **Transient API death ≠ tier exhaustion → resume the SAME agent, don't replace** (s06). The
  limit-recovery rule (never resume an exhausted tier — it re-dies) does NOT apply to a "connection
  closed mid-response" drop. Check the worktree is clean/uncommitted, then SendMessage the same
  agent — context intact, cheap. Replacing it re-derives everything.
- **Codex approval seam** (s03): relayed user approval may be rejected in child transcripts for
  external writes. The working mechanism is the child hands back the exact
  files/message/head/action; root performs only that directly authorized
  commit/push/PR-comment/merge action, then resumes the same child for ownership and monitoring.

- **(sibling, s07) Merge-boundary recovery**: a session dying between `gh pr merge` and recording
  the result leaves merged-vs-not ambiguous — ground-truth `gh pr view --json
  state,mergeCommit,mergedAt` + `origin/main` BEFORE resuming anything, and treat the post-merge
  half as unverified (it's exactly what an interrupted merger silently skips).
- **(sibling, s07) Polling doctrine**: read existing check states ONCE before any appearance
  wait — never poll toward a verdict that already exists; NO record of ANY status after a short
  bounded wait means the trigger never fired — stop polling and diagnose.
- **(sibling, s07) The permission classifier is NONDETERMINISTIC across identical shapes and
  sessions** — an acceptance is a sample, never a predicate; never fold "this shape works" from
  one acceptance or a ban from one denial. A classifier error that calls itself transient earns
  exactly one identical retry; a plain denial earns a simpler shape, not a retry. Subagents
  inherit the COMMITTED settings file, not the local one.
- **(sibling, s07) Shell/git traps that transfer verbatim**: `git commit --amend` chained behind
  a commit pre-commit ABORTED rewrites the previous, already-pushed commit (pflow runs the same
  asset-mirror hook — recovery is `reset --soft` + fresh commit, never force-push); `git add a b
  c` with one bad path stages NOTHING and is silent under `2>/dev/null` — read `git diff
  --cached --name-only` before multi-path commits; the harness gitStatus block can be STALE —
  cross-check live `git log`; zsh reserves `status`/`path`; a heredoc body starting `**` dies on
  zsh globbing — use `--body-file`.

## 4. Mechanisms that worked

- **Cross-file coherence audit:** grep `DECISIONS #` across ORCHESTRATION + all agent defs, then
  check each def's standing rules against the lane rules. Caught a real contradiction (lane B's
  merge-it-itself vs the def's flat "never merge") that both writing passes missed. Run it after
  any multi-file process edit.
- **When porting an artifact from another repo, port its WIRING too** — grep the source repo for
  references to the artifact before declaring the port done. I wrote the close skill without
  checking how the source repo's command invoked it; the user had to point ("see how its
  mentioned in the [sibling repo] docs"). One `grep -rn <name>` would have caught it.
  - **And check the SUBSTRATE, not just the wiring** (s07): an imported rule can depend on a
    mechanism the source repo has and yours lacks — the review-labour ownership move (#17)
    required a Bash-drivable lens dispatch that didn't exist here yet (implementers hold no
    Agent tool). Caught at import time, encoded as an explicit interim, dissolved the same day
    when the fan-out shipped. Before porting an ownership/authority rule, ask what MECHANISM the
    target role uses to exercise it.
- **Adversarial DESIGN review via Codex** (s04, user-invoked). For a hard design
  call, get an independent critique of the *proposed design* (not a diff). Working zsh invocation:
  `codex exec --sandbox workspace-write -c 'approvals_reviewer="auto_review"' "$(cat prompt.md)"`.
  Traps: the user's PowerShell form uses backtick line-continuations (write it single-line for zsh);
  `--ask-for-approval` is NOT valid for `codex exec` (drop it — exec is non-interactive); output
  streams ~MB (redirect to a file, read the tail). It surfaced real flaws my own review missed
  (durable-provenance gap, three-seams-not-N). Local-only: that review + the session's searcher
  outputs live in `scratchpad/` (gitignored) — gone once this machine's temp clears.

## 5. Local-only artifacts (a successor cannot discover these)

- `scratchpads/cross-repo-knowledge-transfer/` (gitignored): `plan.md` (the fold's plan),
  `re-audit-report.md` (four buckets + P0–P8 dispositions + the addendum), and
  `phase-a-transfer-list.md` (the blind-pass list — holds the UN-imported residue for any future
  pass). If missing: DECISIONS #19/#22 summarize what landed; the residue is reconstructable
  only from the sibling corpus.

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
`<sibling repo>/.taskmaster/tasks-orchestration/orchestrator-handoff-2026-06-30.md`.
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
- CONSIDER: back-porting the kickoff/log split to the sibling repo once it proves itself here.

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
