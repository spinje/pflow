# session-09 — 2026-09-29 → 2026-10-01

## [2026-09-29] main orchestrator — boot + reality diff

- Booted per the role prompt; only session-08 carries a braindump → boot fork (1b) skipped per its gate;
  no pflow predecessor session live. Reality vs CURRENT-STATE: no drift (main = the s08 close commit,
  state-only). Boot fold: one stale SHA line.
- User focus: *"lets continue where the last session left off, focusing on the highest value/leverage
  things to work on"*.

## [2026-09-29] [RULING] *"yes go ahead"* → Task 170 build + lanes #617 #618 #615; #615 option (a)

- #615's gate logic touches `runtime/engine/` (grep) → launched under a fail-closed engine STOP. No prep
  commit (nothing producer-facing moved). Opus task-orchestrator on 170 (planner window spent — design
  doubts come UP to me).

## [2026-09-29] Filed #650 (screenshot suite silent pass)

- Correction to the s08 framing, from my own read: zero LEAVES already fails; the silent pass is unmeasured
  handles (`dotsChecked: 0`) + click/hover `ok:false` invisible to the API-warning detector.

## [2026-09-29] #615 ESCALATED (3/5): one-time approval vs loop-restart cycle

- The one-time answer fixes the bug, but re-resuming a loop paused at iteration ≥2 restarts the loop and
  spends the answer on iteration 1 → repeated side effect + endless pause cycle. Root: loop approvals issue
  pause tokens resume can't honour (escalations already unpausable in loops, `_gate_pausable`).

## [2026-09-29] Task 94 freshness (31 true / 8 stale / 1 unverifiable) — folded

- Load-bearing: enumeration must group `model_cost` by `litellm_provider` — `models_by_provider` misses live
  additions (searcher EXECUTED). Q1/Q2 → user; Q3 (modes) 2/5 with a verify-at-start probe.

## [2026-09-29] #617 merged (PR #651) — residual

- `core/param_coercion.py:98` turns CLI `false` into `"False"` for every string input (shared; candidate,
  class unverified, NOT filed); `examples/advanced/file-migration.pflow.md:185-190` lacks `confirm_delete`.

## [2026-09-29] User: *"we are running many reviewers with deep review right, including the falsifier etc?"*

- MEASURED answer: not uniformly. #617 ran 3 lenses, no falsifier. The lane def said "proportionate" and
  never named the falsifier; my packets didn't state the skill's floors. Sent mid-flight to 170 + #618.

## [2026-09-29] #618 ESCALATED (3/5): user-started threads' prints

- Lane found two worse instances pre-fix (EXECUTED): parallel-batch `--output-format json` → 0 bytes;
  timeout → error JSON 0 bytes. Options A (ship + stdout-hygiene follow-up) / B (patch `Thread.start`) / C.
- Incident: a lane `git stash pop` applied the SHARED `stash@{0}` (Task 125 WIP) — stashes are repo-wide
  across worktrees. Repaired; stash intact.

## [2026-09-29] User principle, verbatim: *"We should prioritize simplicity of the FINAL code, not how easy it is to get there. When in doubt we should ask ourselves whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet? What this doesnt mean is overfitting to "top 10% of codebases" and overengineering, this is about more simple code that is optimized for AI agents to understand and add features to. Doe this change enything?"*

- It changed two of my recommendations: #615 1 → 2 (one pausability rule, `_gate_pausable` extended to
  approvals); Task 94 Q2 → no default special case (`settings llm show` already prints it). #618 A
  reinforced (B is a process-wide stdlib patch).

## [2026-09-29] [RULING] *"yes go ahead witht this, make sure to have this lens for everything we do"*

- #618 A; #615 option 2 in ONE PR with a scoped engine exception (`_gate_pausable` + minimal iteration
  read; fail-closed on a trace field) — checked disjoint from 170's `engine.py` sites by grepping its plan;
  Task 94 Q1 static hint, Q2 no; lane gate → the deep-review rubric's floors.
- "This lens for everything": the principle added VERBATIM to root `CLAUDE.md` Code Quality; quoted
  verbatim in every packet thereafter.
- Filed #652 (machine-output stdout not reserved). Task 94 SPEC battery launched (4 Opus lenses).

## [2026-09-29] Task 94 SPEC battery — convergent 4/4 + filed #654

- 4/4: the catalog→pflow provider join is undefined (non-routable ids, hidden families) → user decision;
  3/4: keyword semantics dead-end the "see all" rung → fold.
- NEW pre-existing bug, reproduced by me offline: `register_model` re-keys upstream entries onto bundled
  ones → bundled prices mutate, new models never land → #654.

## [2026-09-29] #615 merged (PR #655) — residuals seed Task 179

- Loop-gate pause output lacks `--auto-approve` guidance (no loop info on the pause record); looping gated
  sub-workflow step overwrites iteration 1's trace record (→ #659); UI "approve all iterations" = product call.

## [2026-09-30] [RULING] *"yes go ahead with your recommendations"* — Task 94 provider universe A; wave 1; #644 p2 research

- A = the curated table, each row declaring its catalog groups + routing prefix; round-trip test. Prep
  commit pushed (CLAUDE.md lens, lane gate, Task 94 spec). Lanes #606 #654 #652 + MCP SDK 2.x research.

## [2026-09-30] #606 ESCALATED (2/5 ×4) → resolved here

- Derive rows; frozen dataclass; move the table to `core/llm_providers.py`; status = "what the runtime would
  actually use".

## [2026-09-30] UI approve-all: user *"explain what this means simply…"* → *"yes lets do this"* → *"why are we not doing the "real fix" again?"* → *"yes go ahead"*

- OWNED: I had proposed the button as a cheap interim without costing the real fix or asking whether it's
  part of the final design — ease-of-getting-there reasoning, minutes after the user stated the lens.
  Real fix = durable loop position (Task 179, spec'd now, after 170); #656 folded and closed.
- #652 ESCALATED (3/5): fd-level reservation; subprocess + text-mode-piped instances found → ruled S2
  (every run/resume, any format). Filed #657 (subprocess stdin) and #658 (probe -v JSON).

## [2026-09-30] Task 178 spec (MCP SDK 2.x) — research read in full

- One-step migration feasible (wire matrix VERIFIED both eras/transports + real servers); 8 sites silently
  wrong on 2.2.0; SDK 2 diverts fd 0/1 natively → the migration DELETES pflow's stdio shims.

## [2026-09-30] Task 179 spec (durable loop position) + #659

- Overturns Task 164's documented restart-at-1 stance by user ruling; ADR-0010 amended, not reversed.

## [2026-09-30] User: *"what is the scope for this session? im letting you run this end to end but we need a clear boundary for the session"* → [GRANT] *"yes go ahead with this'"*

- Scope: drain #606/#654/#652; 170 through merge; Task 94 planner + build; wave-2 #643/#657/#658/#650
  (#650 only with a defensible settled answer); close. OUT: building 178/179, new discoveries (file only),
  releases/force-push/history rewrites. 4–5/5 or settled-ruling contradictions PARK. Commit authority for
  this session: (a) my spec/state prep commits; (b) the close commit.

## [2026-09-30] Escalations resolved in-grant (each 2/5, logged in the PRs)

- #606: repeated settings warnings (same as `pflow run` already does) → ship, filed #660.
- #652: `anyio` direct import → declare it; lock diff fail-closed to pflow's own entry.
- #650 fork ruled here (settle fails loudly; empty graph = explicit opt-in; presence floors). The lane
  deviated twice ON EVIDENCE (literal floor failed 209 healthy views; click/hover throw) — accepted.
- #657 ×3: MCP stdin twin shim now (measured Windows hang); accept EOF for terminal + `< file` (accidental
  behavior; filed #666); keep the hygiene ratchet with an honest docstring.
- Task 94 CP-1 (13 mocks, real catalog data) collapsed to my review under the grant; planner-implements
  accepted (~356k tokens used at offer).
- Task 170 R5 (a) — the s08 ledger ruling; both validator tightenings kept (strict grammar wins).

## [2026-09-30] Seams found by lanes (filed)

- #652's Windows CI proved #657 worse than filed (code-node subprocess under `mcp serve` hangs the whole
  node timeout). #643's lane found **data loss**: `save --force` deletes before bundling → #665 (NOT launched,
  out of scope). #657's falsifier: `mcp serve` ignores SIGTERM → #669. #650's falsifier: collapsed
  sub-workflow card dot 214px off → #672.

## [2026-09-30] Task 170 decision 1 PARKED for the user (locked-spec boundary of the grant)

- Prose-wrapped output `source:` — the spec said "recorded, not fixed"; the plan's own normalizer fixes it.

## [2026-10-01] User (after switching the orchestrator to Opus 5.5): *"can you give me a recap of current state, is session closed? can you explain simply what I need to decide on and why, with tradeoffs"* → [RULING] *"yes go ahead with your recommendations"*

- Option (1): prose-wrapped output source interpolates = Sanctioned delta 7.

## [2026-10-01] Task 170 SHIPPED (PR #673; closes #630, #262 — spec-intended)

- CONTEXT.md: **Dynamic index**, **Issue**. Filed the ten review follow-ups #674–#683 (#675 batch memo
  cache stale is the consequential one; #674 scanner skips nodes under a `pflow` dir surfaced as CI breakage).
- Task 179 roadmap `then` → `next` (user ruled "build after 170").

## Braindump

_Tacit residue only — rulings and ships live above, in CURRENT-STATE, and in the PR bodies._

**The user this session — their words, and what they did with them**

- The governing lens arrived mid-session as *"Doe this change enything?"* — a test of whether I'd re-run
  my open recommendations through it, not a request for agreement. Re-running flipped two of four. Read a
  restated principle as "re-audit what's on the table now".
- *"why are we not doing the "real fix" again?"* — asked ~an hour after the lens, about a UI button I had
  proposed as a cheap interim. The tell: I offered an interim without stating the real fix's cost or whether
  the interim survives into the final design. Before proposing any interim, write one sentence: "the final
  shape is X; this interim is/isn't part of it because Y". They caught it; I hadn't.
- *"explain what this means simply"* came twice (the approve-all question, the 170 decision). Plain-language
  options with good/bad/reversible landed immediately both times — the spec-text version of the same
  question would not have.
- *"we need a clear boundary for the session"* — they grant autonomy readily but want the scope NAMED,
  including what's out. The grant-shape that worked: numbered in/out lists + two explicit commit
  authorizations (a/b). They answered "yes go ahead with this'".
- *"we are running many reviewers with deep review right, including the falsifier etc?"* — they audit that
  gates RAN (s07/s08 pattern, third instance). Answer by measuring the PR body, not by recalling packets.
- They switched me Fable → Opus before the last ruling. No borderline call was taken after the swap; the
  one decision went to them in plain terms.

**Overturned or corrected, owned**

- The #656 button (above). Lesson shape: an interim proposed without its final-shape relationship is
  ease-of-getting-there reasoning wearing a "pragmatic" label.
- My #650 ruling's literal presence floor (`dotsChecked===0 && leaves>0`) would have failed healthy pages;
  the lane measured 209 views and keyed it on rendered io rows instead. A ruling handed to an executing lane
  should state the INTENT ("never pass on nothing") with the mechanism as a suggestion — it did, and the
  lane improved it correctly.
- I wrote the Task 170 spec's "prose-wrap: recorded, not fixed" line last session from a battery summary;
  the plan's own normalizer contradicted it. Freeze lines written before the plan exists are predictions.

**Mechanisms that worked — reuse them**

- **Fail-closed hand-back conditions with a measurement attached** (s08's mechanism) held in every lane:
  #615 (engine), #618/#652/#657 (≥2 shapes), #606 (output change). Every stop was a real fork.
- **Relaying CI evidence between lanes**: #652's Windows failure was exactly #657's class; sending it as a
  MEASURED fact with "evaluate the process-level seam" turned a per-spawn fix into the right shape.
- **"Delete, don't port" recorded in the migration spec at the moment a shim lands** — Task 178 now owns the
  removal of both stdio shims and the `anyio` declaration; each shim's comment names it.
- **Spec battery → user decision → one fold pass** worked again for Task 94 (4/4 convergence made the one
  real decision obvious and everything else foldable).
- Planner-implements on a well-bounded task (94): one Fable agent, ~490k total, plan → PR with no
  re-derivation. Worth offering again for small/medium tasks with no engine contact.

**Seams noticed, not yet forced**

- Task 179 will touch `_gate_pausable`, which #615 just extended — its iteration-1 clause is exactly what
  179 deletes. #659 must land first inside 179 (it corrupts the history 179 seeds from).
- #675 (memo cache stale) sits in `runtime/engine/instrumentation.py` — engine, so lane A or serialize with
  179; don't launch it as a parallel lane-B beside 179.
- #621/#550 (literal `${…}` in non-pflow contexts) now has its one-parse home in `core/templates`; the user
  ruling is the only blocker. Task 118 waits behind it.
- `core/param_coercion.py:98` (`false` → `"False"` for string inputs) — unverified class, not filed.

**Local-only artifacts**

- `scratchpads/session-09/`: `task-94-freshness.md`, `task-94-spec-battery.md` (ledger), issue-body drafts.
  The MCP research and loop investigation were copied into the task folders (tracked).
- Worktree lanes left gitignored scratch dirs that `rm` couldn't delete; all worktrees were torn down via
  `./scripts/worktree rm`, so nothing remains on disk under `../pflow-worktrees/` (verified `git worktree list`).

**Markers**

- UNCLEAR: whether the #657 falsifier's `pkill -x sleep -f` killed an unrelated user process (no report).
- ASSUMPTION: claude-code/Desktop/Codex clients work against a v2 pflow MCP server (inferred, Task 178).
- ASKED-NOT-ANSWERED: none.
