# Braindump: Unified Data-Flow Edges + Prompt-Cache Edges (handoff to implementer)

> For the agent implementing
> `.taskmaster/tasks/task_168/implementation/unified-data-flow-edges-plan.md`.
> The plan is APPROVED, review-hardened (one structural plan-review pass + one
> feature-interactions pass, findings folded in), and designed to be executable in
> isolation. This document carries what the plan deliberately does NOT: the journey,
> the user's mental model, the reasoning behind the locked decisions, and the
> watch-items I couldn't fully discharge. Read the plan FIRST; read this second.

## Where I Am

Planning is 100% done; zero implementation has happened. The working tree is clean on
`feat/workflow-visualization-static-viewer`. The plan went through: proposal →
Phase-0 corpus measurement (I prototyped BOTH variants as monkeypatches and measured
real edge counts) → 4 parallel codebase-searcher verification reports → 2 detail-pinning
searchers → review-plan agent (2 MAJOR, 6 minor — all folded) → review-feature-interactions
agent (found the THIRD landmine — folded). Every line citation in the plan was verified
against this branch on 2026-06-12/13. Line numbers WILL drift as you edit — anchor by
function names, which the plan always gives.

## User's Mental Model (their words matter — reuse them)

- The governing directive, verbatim: **"We should prioritize simplicity of the FINAL
  code, not how easy it is to get there. When in doubt we should ask ourselves whats
  the right solution that the top 10% of codebases similar to this one would implement,
  have we considered it yet?"** — immediately qualified: **"What this doesnt mean is
  overfitting … and overengineering, this is about more simple code that is optimized
  for AI agents to understand and add features to."** This directive is WHY the plan is
  the A2 consolidation (delete `_add_declared_input_edges`, one emitter) instead of the
  minimal add-a-second-call fix. If you face an unforeseen fork mid-implementation,
  apply that test — but see "What I'd Tell Myself" below for the counterweight.
- The user is NOT a casual reviewer of visual semantics. They twice stopped me to demand
  plain-language explanations ("im still not sure I understand, why are we showing two
  lines for the same relationship? why not 1? we are not using arrows?"). The resolution
  that satisfied them: control edge = the gradient spine THROUGH the icons; data edge =
  teal line landing on the exact param row; beautiful already shows only one line;
  advanced is the "show every fact" audit view. If you have to explain a visual choice
  to them, use concrete geometry like that, not abstractions.
- On prompt cache, the user initially believed "wont prompt cache always point to an
  edge (template var) allready existing in the prompt?" — the fact that flipped them:
  the chunk ref is FORBIDDEN in the consumer's prompt (`cache.prompt-body-duplicates-cache`
  is a hard validation error), so the cache edge is the ONLY visibility that dependency
  can ever have. They answered "yeah you are right." Keep that framing if cache questions resurface.
- They explicitly asked me to verify assumptions with subagents before starting and to
  ask "what would make this fail?" — they value pre-verification over speed. Honor the
  plan's phase gates literally; don't batch phases to save time.

## Key Insights (the non-obvious load-bearing stuff)

1. **The plan's three landmines are the distilled output of ~700K tokens of review. They
   are not decoration.** Each was found by a different mechanism: #1 by tracing Mermaid's
   `_has_direct_data_flow` against deep-research goldens; #2 by the truncation test's
   dedup-key interaction; #3 by the interactions reviewer noticing
   `_render_data_flow_batch_targets` has NO source filter while the model's `shadowed()`
   does. If your implementation makes a golden diff, the answer is in those three —
   do not rationalize a golden change as acceptable.
2. **My instinct to scope down was WRONG three times, and verification corrected it each
   time.** (a) I recommended "ship without list descent" — the grammar-parity agent showed
   the validator recurses lists, so skipping them breaks the one-sentence rule. (b) I said
   "the shadowing risk is moot" — agent B showed advanced mode would dim most of the spine.
   (c) I recommended "accept the expanded-batch items edge loss BY-DESIGN" — the
   interactions reviewer produced the opaque `inputs: ${item}` case where the loss is total.
   Lesson for you: when tempted to simplify away a plan step, assume the plan is right and
   your instinct is the un-verified one.
3. **`test_data_flow_edges_from_params` (test_mermaid.py, the exactly-once assertion) is
   the emission-shape canary.** It passes ONLY if your consolidated params-walk emits
   byte-identical input-edge shapes to `_add_child_input_data_flow` (same target formula,
   `output_field=None` for input roots, same `output_path` guard) so full-equality dedup
   absorbs the overlap. If it goes red: your edge SHAPE diverged — fix the shape, never
   the test. Most likely divergence points: the target formula, or accidentally emitting
   `output_field` for input-rooted refs.
4. **`_resolve_ref` checking inputs FIRST is what makes the whole consolidation one-line
   deep**: deleting the emitter's `elif root in level.inputs: continue` is the entire
   semantic change of A2. Everything else is plumbing removal.
5. **The shadow-dim removal (4.1) has a USER GATE.** The user accepted "stop dimming" only
   *pending a browser before/after*. You MUST produce both screenshots (stash-toggle) of
   `generate-changelog` in advanced and present them before considering 4.1 closed. The
   agreed fallback if they dislike full-strength: dim only when NO same-pair data edge
   exists (Mermaid's rule-1 analogue). Do not skip this because the tests pass.
6. **Mermaid is far less exposed than it looks.** Body→body data edges (sibling refs,
   sibling-rooted cache) are unrenderable there — Mermaid's 5 render sites are all
   filtered. The ONLY Mermaid-visible consequences are: input-edge duplicate lines (fixed
   by 3.1's dedup), input-rooted cache chunks (new truthful arrows, no goldens affected),
   and the three landmines.
7. **Cache-edge-counts-as-a-read is a decided semantic, not an accident.** New cache edges
   carrying `output_field` will un-quiet the producer's output row and appear in
   consumedReadPaths. Intended — the field genuinely is read through the cached prefix.
   Don't add a guard.

## Hard Numbers (so you can recognize "expected" vs "wrong")

- Corpus (64 buildable examples + lyrics-generator): 656 → ~830 data edges under A2.
  Per-workflow: harness `run-from-plan` 124→152 (+27 of those are input multiplicity,
  e.g. `repo_dir → fix-tests` via both `cwd` and `repo_dir` params); `generate-changelog`
  11→39 (all sibling `command:`/`stdin:` refs); `claude-code-git-workflow` 0→8;
  lyrics-generator 131→149. Cache edges add a handful more (not in these numbers).
- Build time: 0.148s on the harness, identical before/after. If you measure a regression,
  something is wrong with your walk (probably re-resolving inside a loop).
- The measurement scripts are preserved in `scratchpads/param-ref-data-flow-edges/`
  (`phase0_measure.py`, `phase0_a2.py`, `show_mult.py`) — `phase0_a2.py`'s monkeypatch is
  ~the consolidated semantics; re-running the corpus sweep post-implementation is
  verification step 5 (adapt: no monkeypatch needed, just count). Expect stderr noise
  "Template validation found 1 errors" during corpus runs — pre-existing, one example
  fails standalone validation; 14 examples skip standalone — that's the unchanged baseline.
- lyrics-generator lives OUTSIDE the repo:
  `~/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md` —
  the user's real 128-node workflow and their favorite test subject.

## Assumptions & Uncertainties

- **NEEDS VERIFICATION (cheap, do early):** the plan's 1.4 changes `_params_strings` to
  yield 3-tuples. I believe its only caller is the params walk in
  `_add_one_input_consumer_edges`, and react_flow has its own local copy
  (`_string_leaves`) — but grep callers before changing the signature.
- **ASSUMPTION:** `_add_ref_edges`'s target formula `target_inputs.get(input_name, node_id)`
  with `input_name=None` (batch items pass) hits the `if input_name is not None` ternary
  → `node_id`. True today (build.py:520); preserve while renaming.
- **UNCLEAR / judged acceptable, not proven:** advanced-density layout shifts on the
  harness from +28 ELK edges. The interactions report says no hard breakage (watchdog
  guards), but nobody has SEEN the new harness layout. The 4.4 browser pass is where this
  gets eyeballed — if the harness advanced view degrades badly, that's a "report to user"
  moment, not a silent fix.
- **ASSUMPTION (70%):** no test outside the files the searchers swept asserts on
  data-edge counts. The sweep covered test_graph_build / test_mermaid /
  test_graph_*_renderer / goldens / contract fixtures. A stray integration test counting
  edges would show up at the `make test` gate — treat any such failure as
  rewrite-deliberately territory only after confirming it pins the OLD pair-dedup truth.

## Unexplored Territory

- **UNEXPLORED:** real `pflow visualize` output (non-golden) before/after — nobody
  eyeballed actual Mermaid renders of e.g. changelog. CONSIDER one manual
  `uv run pflow visualize examples/real-workflows/generate-changelog-simple/workflow.pflow.md`
  before/after as a sanity glance during Phase 3.
- **MIGHT MATTER:** the hover system re-renders every edge/node component per hover
  transition (known watch-item, `visualization-requirements.md`). +28 edges on the
  harness nudges that cost. Untested; if the 4.4 pass feels janky on hover, note it for
  the user — the known fix direction is selector-subscription, NOT fewer edges.
- **CONSIDER:** parallel agents have worked `web/` files concurrently in this task's
  history (progress log mentions slice coexistence and one clobber scare). Check
  `git status` before starting and keep your web edits surgical.
- **MIGHT MATTER (future, not now):** Task 169 (stable edge addressing) would fix the
  `?focus=e<i>` renumbering fragility properly; the plan just accepts the breakage.

## What I'd Tell Myself

- The plan is intentionally over-specified — trust it over your instincts on the parts
  marked verified, BUT the simplicity directive still applies to anything the plan leaves
  open (naming, comment wording, test structure). The balance: plan = WHAT and the
  guards; you own only the residual HOW.
- Phase order is load-bearing: the contract-fixture test stays red from Phase 1 until the
  ONE regen in Phase 3 — that's deliberate (one reviewed diff, not three). Don't "fix" it early.
- Project rules that bit previous agents: NEVER git add/commit unless the user says so;
  `make ui-build` + hard browser refresh before trusting any visual check (stale-tab
  404'd chunks render as "nothing works"); jsdom renders zero React Flow edge DOM, so
  edge integrity is pure `flow.ts` tests only; never emit a raw NUL byte/escape via tool
  output in this repo (route through python if ever needed).
- The progress-log entry (Phase 5) should follow the established format in
  `.taskmaster/tasks/task_168/implementation/progress-log.md` — deviations with reasons,
  review outcomes, learnings. The user reads these.

## Open Threads

- The shadow-dim before/after screenshots → user decision (the one explicit human gate).
- After implementation, `visualization-requirements.md`'s "references (N)/referenced by (N)"
  bullet's caveat ("completes for free when scratchpads/param-ref-data-flow-edges lands")
  resolves — Phase 5 moves it; verify in the browser that the ReadPanel sections actually
  fill out on a cache producer (`extract` → `referenced by (3)`).
- I did NOT create a new task number for this work — it rides under task 168's umbrella
  (plan + this braindump live in its folders). If the user wants a separate task file,
  `/create-task` exists.

## Relevant Files & References

- THE PLAN: `.taskmaster/tasks/task_168/implementation/unified-data-flow-edges-plan.md`
- Origin proposal (problem evidence, Option A/B framing):
  `scratchpads/param-ref-data-flow-edges/proposal.md` (+ the preserved measurement scripts beside it)
- The code you'll live in: `src/pflow/core/workflow/graph/build.py` (emitters),
  `graph/scope.py`, `graph/renderers/react_flow.py` (`_string_leaves`, `_resolve_edges`),
  `graph/renderers/mermaid.py` (`_render_data_flow_edges`, `_render_data_flow_batch_targets`,
  `_edge_shadowed_for_render`), `web/src/graph/flow.ts`, `web/src/components/EdgePanel.tsx`.
- Contract + rendering rules: `src/pflow/ui/CLAUDE.md`; frontend invariants: `web/CLAUDE.md`;
  model invariants: `src/pflow/core/workflow/graph/CLAUDE.md`.
- Browser verification: `.claude/skills/screenshot-pflow-web-ui` (shot / inspect / hover /
  click harnesses — `click.pflow.md` for "what does a click DO").

## For the Next Agent

Start with Phase 1.1–1.3 in one sitting (they're one logical change), run the Phase 1
gate, and STOP if any golden diffs. The cheapest early win is writing the
`test_data_flow_edges_from_params`-protecting emission shape correctly the first time:
input roots through `_resolve_ref` → `(input_node, None)` → `output_field=None`. The user
cares most about: final-code simplicity, no silent behavior changes (everything either
verified-identical or documented BY-DESIGN), and being shown the shadow-dim
before/after rather than told about it.

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points, then state you're
> ready to proceed.
