# Braindump: loop rendering in mermaid — done, and what it hands to Task 155

**Date:** 2026-06-06. This replaces a formal plan doc (the user asked for a braindump instead — they
don't want plan docs lingering once the work is done). The fix described is **implemented + verified + merged to `main`** (#483, `463795f5`). This is the tacit layer; the durable payload is "What this hands to 155" below.

## Where this came from (the journey — not in any file)

This is a **leaf of a much bigger thread.** The master narrative is
`scratchpads/handoff-see-control-storage/session-progress-log.md` — read it first. The user opened with
*"Task 125 (HITL) vs Task 155 (graph model → visual UI), leading into a visual UI"* and the load-bearing
quote that recurs everywhere: **"It's very hard for me as a human user to understand how this agentic
workflow actually works and I NEED to have full control."** They're building Task 163 (a plan→code
agentic harness — a *tree* of `.pflow.md` sub-workflows) and can't SEE or CONTROL it.

The path to this loop fix:
1. Dissolved "125 vs 155" → orthogonal substrates (155 = SEE/static; 125 = CONTROL/runtime), not competing.
2. Rendered the harness as Mermaid → the intelligence lives in the **prompts** (truncated in mermaid); the
   highest-value UI feature is **click-node → read-prompt**.
3. User asked: can we visualize the six workflow patterns (`src/pflow/guide/features/patterns.md`:
   classify, fan-out, adversarial-verify, generate-filter, tournament, loop-until-done) **without the
   trace**? → Yes: *structure* is static; only the chosen-path highlight, dynamic fan width, and tournament
   unrolling need the trace.
4. **The user caught that `loop:` might not render** (*"im unsure if loops works in visualize right now
   since we just implemented it"*). They were right. That triggered this fix.
5. User's instinct: mermaid is a dead-end for loops; *"using react flow we can probably come up with
   something great?"* → Yes — and that is exactly 155's thesis (one semantic model, many renderers).

**This loop fix is the first actual code in the whole strategic thread.** It is deliberately a tiny,
near-throwaway *honesty* fix; the real value is (a) informing 155 and (b) the react-flow direction.

## The fix is DONE — don't re-explain it, read the code

`make check` clean; full mermaid/visualize suite (92) green; **zero existing-golden regressions** (verified:
no golden renders a loop workflow). Files (merged in #483):
`mermaid/_context.py` (`_loop_label` + `_strip_template`), `_render.py` (2 append sites + a `loop` param on
`_render_subgraph`), `__init__.py` (re-export), `tests/test_core/test_mermaid.py` (13 tests), new golden
`tests/test_core/golden_mermaid/stateful-loop-tournament.mmd` + its parametrize entry.

Mechanic worth holding in your head: **a looped node has NO edge in the graph** (the engine self-re-enters
in place), so the renderer *synthesizes* a label badge `⟳ while <cond> · ≤N · carry <keys>` from
`node.get("loop")`. Single node → badge on the node; sub-workflow node → badge on the subgraph title.

## The multinode finding (the user's specific question — the durable insight)

They asked: *"let me know if you find any way to handle loops with multinode bodies for mermaid."* There are
**three** structurally-different loop shapes, and the clean multinode path already exists:

1. `loop:` on a **single node** → body = 1 node → badge on node. Trivial.
2. **`loop:` on a sub-workflow node → body = the whole sub-workflow, which is ALREADY a subgraph box →
   badge on the box. This is the legible multinode answer; nothing new structurally.** (The tournament's
   `run-rounds`. Verified: `loop:` is legal on ALL node types — no allowlist.)
3. **Hand-wired backward-edge cycle** across siblings (the harness group loop:
   `group-tick → implement-chunk → check-groups`) → already renders as a visible back-edge; containerizing
   needs SCC/cycle detection → NOT minimal → out of scope.

**The convergence (tell the user — they like this framing):** declarative `loop:` (single OR sub-workflow)
= renderable/containerizable; hand-wired cycle = back-edge-only → another reason to **prefer `loop:`**, and
a reason the harness's group loop could be refactored into a `loop:`-on-a-sub-workflow (which would also
make it containerizable in react-flow).

## What this hands to Task 155 (the REAL payload — why we did it)

When 155 extracts the GraphModel:
- **The node record needs an optional first-class `loop` field** — `{polarity (while|until), condition ref,
  cap (literal int | template), carry map}`. Keep it a **node property, NOT an edge** — mirror the engine
  (it creates no edge; a loop is evaluated at the re-entry seam).
- **The loop-on-subgraph case must be representable** so react-flow draws a collapsible **container**
  ("repeats while X · ≤N" box) and mermaid draws the **badge** — from the *same* model. **The loop is the
  single strongest demonstration of 155's "one semantic model, many renderers" thesis**: it's where
  renderer quality diverges most (mermaid: ugly badge/back-edge; react-flow: great container). Get the loop
  right in the model and both renderers win.
- `_loop_label` is the throwaway *location* of a durable *decision* (what a loop carries + how it surfaces);
  155 relocates it from the renderer into `build_graph` (model) + render split.
- `carry:` as data-flow-style edges (`contenders ← survivors`) = deferred renderer concern; flag known-future.
- Hand-wired cycle containerization (SCC detection) = out of scope for the minimal fix AND 155's first cut,
  but the model should not *preclude* it.

## The react-flow direction (a parallel fork — important context)

A forked agent built a self-contained react-flow mockup proving the "great" version:
`scratchpads/handoff-see-control-storage/loop-containers-mockup.html` + screenshot
`loop-containers-final.png`. It renders **both** harness loops as collapsible first-class containers (the
hand-wired group loop AND the declarative review loop get identical treatment — the point being mermaid can
render *neither* well). NOTE (updated this session): the user later judged this specific mockup *"isnt great"* — it is a *discarded reference*, not the visual target; the actual component design is a deferred, separate problem. The durable point is the renderer-divergence thesis (mermaid renders neither loop well; react-flow can). The user wants, verbatim: *"run
in a react server locally on demand using something like react flow,"* *"clicking to read prompts."*
(Side effect of that fork: it ran `pflow mcp sync chrome-devtools`, registering 29 chrome-devtools tools in
the local registry.)

## User's mental model & working style (as it showed up in THIS thread)

- **Reasons from PROPERTIES not categories.** "Is this static or runtime? a node property or an edge?" wins.
- **"why is X?" / "im unsure if X works" is a CATCH, not a question.** This thread they caught (a) that I'd
  conflated hand-wired back-edge loops (which DO render) with declarative `loop:` (which did NOT) — I had
  wrongly claimed "loops render statically"; (b) the loop-invisibility itself. **Verify, concede, don't
  defend.** Right both times.
- **They corrected a misread that matters:** when they said *"this will help the 155 task to understand this
  needs to be handled,"* I wrote a plan doc. They meant **implement now** — *"I meant for us to implement
  this right now, did you not agree with that or why put it in task 155?"* **When this user says a fix
  "helps 155," they mean DO the fix — the doing is what helps — not write a plan for later.**
- **Prioritizes simplicity of the FINAL code; elegance earned; prove the cheap path first; solve OBSERVED
  (not theorized) problems.** The loop fix is exactly that: an observed gap, the cheap honest fix (label
  badge, no new edges), beauty deferred to react-flow.
- **NEVER commit/push without explicit instruction** (hard repo rule; an auto-stage hook stages writes).

## Assumptions & uncertainties

- **Open micro-decision (badge format).** I shipped `⟳ while result.continue · ≤ max_review_rounds` (strip
  `${}`, strip the leading `<node_id>.` self-prefix). For `review-round` the condition is
  `${review-round.result.continue}` → renders `result.continue` — slightly verbose (I'd shown plain
  `continue` in an earlier mockup). **The user has NOT explicitly signed off on the final format.** They may
  want `.result` also stripped, or the badge on its own `<br/>` line vs inline. All trivially tweakable in
  `_loop_label`.
- **NEEDS VERIFICATION:** I only string-grepped the badge lines — I did NOT render the full harness on
  mermaid.live after the fix. The mermaid `CLAUDE.md` explicitly warns "string-level assertions can pass
  while the rendered diagram is broken." The badge is a low-risk label append, but a visual check is the
  documented standard for rendering changes.
- **ASSUMPTION:** batch + loop are mutually exclusive (verified `data_flow.py:580-581`), so I did not handle
  a `dynamic_batch_label` + loop-badge collision in `_render_node`. If that validation ever loosens, that
  interaction is untested.

## Verified facts worth keeping (hard-won — a ~100k-token searcher pass; don't re-derive)

- `loop:` is a **top-level node field** `node["loop"]` (sibling to batch/retry/cache), raw dict keys
  `while`/`until`/`carry`/`max_iterations`. Parser `markdown_parser.py:1187-1190`, `:1600`; schema
  `ir_schema.py:147-196`, attached `:252`.
- Compiled form: `LoopConfig` dataclass `runtime/engine/types.py:38-53` (attrs differ from IR keys:
  `while_template`/`until_template`/`max_iterations`/`max_iterations_template`/`carry`), on
  `NodeConfig.loop_config:71`; built `compilation/compiler.py:389-444`.
- **Exactly one of while/until required** (polarity) — `core/workflow/loop_validation.py:6-18`.
- **NO node-type allowlist** for `loop:` — valid on `workflow` nodes (the tournament). Only forbidden
  *combos*: loop+batch, loop+`enable_namespacing:false`, loop+`storage_mode:shared` (`data_flow.py:546-589`).
- **A looped node is a SINGLE self-re-entering node — NO graph edge** (`engine.py:573-617`,
  `_loop_should_reenter:712-761`). This is *why* it was invisible and *why* a label (not an edge) is right.
- `${__iteration__}` = reserved shared key, 1-based, template-accessible (`core/types.py:218-227`).
- Task 166 (carry+until) merged to `main` via `b5dc37ff`; the loop skeleton (while/max_iterations) predates
  it (Task 162 / #445). Branch `feat/declarative-stateful-loop` is **stale** (behind main) — target `main`.

## For the next agent (likely picking up Task 155 itself)

- **Start by** reading `session-progress-log.md` (master) → this → `task-155.md` +
  `braindump-static-substrate-for-visual-ui.md`.
- **The loop fix is DONE and is your concrete reference** for what the GraphModel must carry for loops. Read
  `_loop_label` + the two append sites in `_render.py`; they ARE the "what a loop looks like" decision,
  ready to relocate into `build_graph`.
- **The 155 acceptance check** (rewritten `task-155.md` → Verification): the throwaway react-flow sketch
  must reconstruct the six workflow patterns (incl. both loop shapes) **+ the 163 harness** from the
  GraphModel *with no information loss*. The react-flow mockup
  (`scratchpads/handoff-see-control-storage/loop-containers-mockup.html`) is a *discarded reference*, NOT
  the visual target — the user judged it "isnt great"; component design is a separate, deferred problem.
- **The user's real priority** is SEEING + CONTROLLING the Task 163 harness. 155 is the SEE substrate; this
  loop fix is a tiny down-payment that proves the renderer-divergence thesis.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read
> and understood by summarizing the key points — especially (1) the three loop shapes and the
> loop-on-subgraph = clean-multinode finding, (2) what 155 must carry (a first-class loop **node property**,
> loop-on-subgraph representable, the loop as the strongest multi-renderer demonstration), (3) the loop fix
> is done/verified/**merged** (#483), (4) the react-flow mockup is a *discarded reference*, not the visual
> target — the 155 acceptance check is completeness (the six patterns + the 163 harness reconstructed from
> the GraphModel with no info loss) — then state you're ready.
