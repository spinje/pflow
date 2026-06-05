# Task 166 — Progress log

> The **how we got here** (kept out of the spec deliberately). Records the exploration, the
> reframings, the dead ends, and the *evidence* behind each decision — so a future agent
> understands *why* the loop syntax is what it is, and doesn't re-litigate settled questions.
> Several conclusions here are broader than the loop primitive (they shaped it); a couple spawned
> separate artifacts (noted inline).

## Guiding principles (emerged during the discussion; shaped every decision)

1. **Agent-first.** The author is an AI agent; human readability of `.pflow.md` is a *bonus*, not
   the goal — humans are better served by a rendered (ideally trace-derived) flow view. Optimize
   syntax for an AI agent authoring it *correctly on the first try*.
2. **Optimize for FINAL-code simplicity, not ease-of-getting-there.** Ask "what would the top 10%
   of comparable codebases do?" — but do **not** overfit or overengineer. For an AI agent, simple
   = fewer files, less text, fewer tool calls, fewer idiosyncratic rules.
3. **Fix the primitive; don't flee to code.** The framework should own hard, correctness-critical
   control flow so agents *can't* get it wrong. Offloading retry/loops/error-handling to
   agent-written `try/except` is fragile and defeats pflow's purpose.
4. **Inline by default; a separate sub-workflow file is the most expensive unit for an agent.**
   Cost ladder: inline param < inline code block < `${ref}` < separate file. Don't force a file
   where an inline node/value suffices.
5. **No expression language in `${...}`** (verified: none exists; `${x > 0}` is illegal). Logic
   lives in the body (Python); conditions are field references. A guard-expression micro-syntax
   would be agent-hostile (out of training distribution).
6. **Explicit, statically-checkable wiring beats implicit coupling** — the #1 silent-failure source.

## Phase 0 — Trigger

Began with: is `.pflow.md` hard for agents to author *complex* patterns (the "6 workflow patterns"
+ Anthropic "5 effective-agent patterns" tables)? Grounded in the repo's most complex real
workflow (`examples/agent-orchestration/plan-to-code/`), which exposed concrete pain: stateful
loops as 3-node backward-edge worker/checker triangles with the counter threaded across siblings;
4-way code routers; per-agent schema-soft-fail guard nodes.

## Phase 1 — Explored "go code", then set it aside

Considered a code-orchestration plane (imperative Python calling effects via `run()`, like the
Claude Code Workflow tool). Genuinely cleaner for loops, and it would fix error-handling for free
(retry/saga = `try/except`). Rejected as the *primary* answer:

- **Forfeits pflow's core bets** — static visualization, built-in/correct handling, constraint.
- **Offloads correctness** to agent-written code (violates principle 3).
- **Static visualization of code is degraded.** Key sub-finding: authoring / execution /
  presentation are *separable* concerns. Humans should get a **trace-derived** render (the trace
  is rich enough — verified). But *before* a run, a declarative workflow has a **full** static
  graph; code yields only an AST skeleton, degrading fast with dynamic dispatch. That pre-run
  completeness is declarative's durable advantage. (Aside: graphs can be extracted from code via
  variable use-def — the modern-orchestrator ecosystem does this — but it's moot once we stay
  declarative.)
- The user's framing held throughout: **fix the declarative primitive, don't flee to code.**

## Phase 2 — Reframe: the friction is an incomplete primitive library, not the paradigm

Reasoning steps that matter:

- **Why is this even hard? It's a solved problem — by domain restriction.** A stateful loop is
  irreducibly code (`acc = init; while cond(acc): acc = step(acc)`). The deep tension is
  *expressiveness vs. analyzability* — you cannot, in general, statically analyze arbitrary
  control flow (Rice/halting). It's "solved" only by closing the vocabulary: SQL, spreadsheets,
  build DAGs, and **statecharts/XState** all give up generality to regain analyzability +
  visualization. So a declarative loop will never be *as* terse as a `while` — and that's the
  correct trade given principle 1.
- **`loop:` today is not a real primitive.** It's sugar over backward edges (themselves sugar over
  `next` routing), its condition must be its own output, and it has **no accumulator**. In
  functional terms the genuine primitives are `map`/`filter`/`reduce`/`scan`/`unfold`; `loop:` is
  an amputated `unfold`/`scan`. And `next`/`end` is essentially `goto` (with goto's footguns).
- **The bounded pattern space makes a closed vocabulary viable.** The user rightly pushed back on
  the functional-language analogy: pflow is *much* more constrained than a general FP language.
  That makes special constructs *feasible* (you can enumerate the patterns) but doesn't mandate them.
- **"Modern orchestrators use code" is NOT evidence for pflow.** Airflow TaskFlow / Dagster /
  Prefect went to code because their authors are human engineers, their *work* is arbitrary code,
  their control flow is genuinely general, and their viz is secondary (monitoring). pflow is the
  **opposite on all four** (AI authors, typed-effect work, bounded patterns, comprehension-first
  viz). The *declarative* orchestrators (AWS Step Functions ASL, Argo) are the ones whose context
  is closest to pflow's. The industry trend doesn't transfer.
- **Net scope collapse:** pflow already chose "pattern-as-primitive" with `batch:`/`loop:`. Five
  of six control needs (sequence, references, map/`batch`, branch, compose) are already sound. The
  one genuinely-broken primitive is the **stateful loop** → make it the symmetric sibling of `batch:`.

## Phase 2b — Patterns, guides, and what the tables omitted

- **Named patterns (tournament, evaluator-optimizer, adversarial-verify) are library recipes +
  guide topics, NOT node types.** Decision rule: promote to a first-class primitive only if
  *common AND hard-to-compose AND* benefits from engine-level validation/optimization. General
  combinators qualify; specific patterns don't (0-file recipes; the trace of a loop-of-shrinking-
  maps already renders as a bracket, so bespoke rendering wants a renderer hint, not a node type).
- **Statecharts/XState = inspiration, not a template.** Borrow: context (= accumulator), guards,
  compound-state composition, the canonical diagram. Reject: the event model and a guard-expression
  language.
- **The user's tables are the *agent-reasoning* subset of what fits pflow.** As a general
  execution engine, pflow naturally hosts patterns the "effective agents" literature omits:
  **poll-until-ready, map-reduce with deterministic aggregation, retry-with-backoff, and the whole
  error-handling/saga family** (the biggest omission — the tables have *zero* failure patterns).
  Proposed guide shape: primitive guides (core, batch, loop, branching, sub-workflows) + ~5
  composition topics (evaluator-optimizer, adversarial-verification, orchestrator-workers,
  tournament, generate-and-filter) + the omitted error-handling family.
- **Composition risk resolved.** "Do combinators nest?" → yes, via typed sub-workflow bodies;
  verified that `batch:` already works on `workflow` nodes, so a `loop:` over a workflow body that
  `batch:`es composes today with no engine change.

## Phase 3 — Verified the codebase (overturned the core premise)

Ran a 7-way parallel code audit (see `research/codebase-findings.md`). Decisive finding: the
assumption the whole design rested on — "a node can't read its own previous output" — is
**FALSE**. The loop self-reference substrate already exists (`shared[node_id]` persists across
iterations; resolution context is `dict(shared)` with no self-exclusion; the validator already
blesses loop self-reference). So carrying state is *substrate that already exists*; the task is a
clean **surface** on top of it. Also corrected two earlier wrong assumptions: document-order
fallthrough is already rejected at parse time; node types are cheap (1 file) but control flow is
engine work.

A separate pattern-coverage stress test (fresh agent) rated 8/11 patterns CLEAN and 3 AWKWARD, and
corrected me: the **tournament is awkward** (a `batch` nested in a `loop` + manual pairing/byes),
not clean as I'd claimed; and the error-handling family is awkward *and* semantically wrong
(degraded-after-recovery).

## Phase 4 — Designing the loop surface (and killing the first attempts)

First sketch: magic `${acc}` + `init:`. A blind cold-read rated it **4/10** — the
`init`-must-mirror-the-body's-*output* coupling was a silent trap, `${acc}` "changed meaning per
line," the `inputs:`/`init:` overlap confused. A second sketch (bare-name `${satisfied}` +
auto-threading) was caught by the user as "too much magic" (invented scope + hidden data flow).
Cataloged **eight** distinct alternatives (A–H: self-ref+`??`, magic `${acc}`, named-state+`update`,
body-I/O name-match, explicit feedback, python-reducer-block, bare-name accumulator, no-accumulator)
for blind grading.

## Phase 5 — Blind grading + independent design → convergence

Four blind graders (fresh, no pflow context, no provenance, neutral prompts) **disagreed on the
winner** — treat as signal not truth (smaller model) — but converged on the *principle*:
**implicit / invisible output→input coupling is the #1 reliability risk**; explicit,
statically-checkable wiring is what makes loops reliable. The python-reducer-block (F) was broadly
rejected (heavy; violates the simple-poll-case). Implicit options (name-match, magic `acc`,
bare-name) were distrusted for silent failure.

Three independent designer agents (criteria only, no catalog, no conclusions) **converged on the
same shape**, and one's adversarial self-critique surfaced the highest-value finding of the whole
exercise: **`while:` polarity inversion is a silent killer** ("poll until done" → `while: done` →
runs once and exits; type-checks, runs, looks plausible; uncatchable statically) → fix with
**both `while:` and `until:` keywords (exactly one required)**.

## Phase 6 — Reconciling the blind designs with verified pflow

The fresh designers proposed `type: loop` (a dedicated type with a `body:` param) — an **artifact
of withholding pflow context**. Corrected to the **`- loop:` modifier** (batch-symmetric, on the
verified substrate, supports inline bodies, no new node type). Then settled references and seed:

- **References:** the existing `${loop-node-id.field}` model over a new `${body}` alias
  (consistency, zero new words, verified self-reference). **Rejected `${item}`** — it is batch's
  per-iteration *input* injected *into* the body; a loop needs the per-iteration *output*,
  referenced in the *parent* config. Opposite role. (`${body}` remains a low-stakes open alternative.)
- **Seed:** collapsed `seed:` into `inputs:` — `carry:` already declares carried-ness, so a carried
  input's `inputs:` value is its round-1 value. 2 of 3 designers independently did this. Accepted
  cost: the round-1-only nature is implicit (surface via a validation note).
- **Form:** `carry:` mirrors `inputs:` (destination : `${source}`) so direction is un-reversible;
  the bare `output -> input` arrow was self-rejected (parser-fragile, guessable).

Landed on the converged shape (now in the spec's **Target Syntax**).

## Cross-cutting outcomes (broader than this task)

- **Error/resilience model → GitHub issue spinje/pflow#471** (audit-first). The error-handling
  family is both the category the tables omitted *and* the most broken in the engine: `on-error`
  always DEGRADES (no "recovered-cleanly" status); retry is hardcoded per node type and not
  settable in `.pflow.md`; no exponential backoff. Independent of this task; retry-style loops
  benefit from both.
- **Guide structure** (Phase 2b) — not yet its own task; recorded here as the agreed shape.

## Epistemic / method notes (so a future agent calibrates trust correctly)

- **The design oscillated, and the user's pushbacks were load-bearing course-corrections.** I
  over-leaned toward "go code" more than once and was repeatedly pulled back to "fix declarative."
  Calibrated conclusion: **declarative was NOT a mistake** (~15–20% confidence it was) — it has a
  real ceiling only for dynamic/stateful loops, which this task fixes.
- **Disclosed bias:** I (Claude) run on an imperative code-orchestration tool (the Workflow tool),
  so I'm predisposed to favor the code shape — discount enthusiasm for it accordingly.
- **Method:** fresh, uninfluenced subagents were used for both *verification* (codebase facts) and
  *evaluation* (blind grading + independent design), specifically to avoid anchoring on my own
  proposals or on each other. Provenance and conclusions were withheld from graders/designers; the
  blind A/B comparison never revealed which form existed today vs. was proposed.
- **Confidence split:** the **convergence** (the shape) and the **polarity finding** are
  high-confidence; graders/designers ran on a smaller model, so exact keywords are implementation
  bikeshed, and the two flagged loose ends (inline-body path, `${node-id}` vs `${body}`) are
  genuinely open.

## Phase 7 — From design to implementation plan (start-work session)

> Outcome: a zero-ambiguity implementation plan at
> `.taskmaster/tasks/task_166/implementation/implementation-plan.md`. This phase did NOT write
> feature code — it run-proved the substrate, resolved the open questions, and hardened the plan
> against a 4-agent review. Read the plan for the *what*; this records the *evidence* and the
> decisions a future agent should not re-open.

### Step-0 spikes — the substrate is run-PROVEN, not just code-read

The braindump's highest-leverage instruction was "prove the self-reference substrate by RUNNING it
before writing a line." Done, on current `main`, with three throwaway `.pflow.md` files (now kept as
regression fixtures in `scratchpads/task-166-loop-carry/`):

- **Inline code-node carry** (`spike-self-reference.pflow.md`): a `code` node whose `inputs:`
  reference its own prior output (`${tick.result.acc ?? 0}`) accumulated `1→2→3→4` and stopped on
  the **condition** at 4 iterations (not the cap). Self-reference threads at runtime. ✓
- **Sub-workflow carry** (`spike-subworkflow-carry.pflow.md` + `child-inc.pflow.md`): a `type:
  workflow` loop feeding the child's `n_plus` output back into the child's `n` input accumulated
  `1→2→3`, condition stop. The primary v1 case works. ✓
- **Ref-as-coalesce-fallback** (`spike-coalesce-refseed.pflow.md`): `${self.x ?? some_input}` seeds
  round 1 from a *referenced* workflow input (not just a literal). ✓

**Consequence:** `carry:` is a thin, statically-checked *surface* over a proven mechanism — manual
carry via `${self.field ?? seed}` already works today. This collapsed the risk of the whole task.

### Two design decisions the spikes resolved (the spec had left open)

1. **Body-type scope → ALL node types, uniformly** (the spec hedged "sub-workflow only, inline is
   under-worked"). The spikes + a verification pass showed carry is just an override of the node's
   `inputs:` map, and `inputs:` resolution is **node-type-agnostic** (single code path). So the
   inline/sub-workflow split *dissolves* — simpler AND more capable than the spec's fallback. The one
   real nuance: for **llm/shell** bodies the resolved value reaches the body only via the
   prompt/command text (`inputs:` is a context-enrichment device there, not a value sink), so a
   carried key must be referenced in the prompt — captured as a validation WARNING + doc note.
2. **Runtime mechanism → explicit per-iteration override, NOT desugar-to-coalesce.** Coalesce
   (`${ref ?? seed}`) already works, but it silently re-seeds if the body omits the carried output a
   round — exactly the silent-coupling failure the task exists to kill. Explicit override always uses
   the carry ref from round 2+, so absent/typo is loud. Robustness > fewer lines.

The low-stakes micro-decisions were settled on the spec defaults (`${node-id.field}` not `${body}`;
`inputs:` not `initial:`; `max_iterations` optional) — to be A/B'd via the Phase-7 acceptance gate
only if fresh agents trip. **The Phase-6 "inline-body path" loose end is now RESOLVED** (uniform on
`inputs:`); `${node-id}` vs `${body}` settled on `${node-id}`.

### The 4-agent plan review — caught a CRITICAL bug in the first plan draft

Ran `/code-review` (plan mode) with 4 specialists (plan / validation-consistency /
feature-interactions / silent-failures) + 4 source verifications. The review **paid for itself**:

- **🔴 CRITICAL — the carry-override hook was dead code** (found independently by *two* agents,
  traced to a stale `engine/CLAUDE.md:160` claim I'd inherited). The first draft hooked
  `_execute_single_node`, which is the **batch-only** callback; since batch+loop are mutually
  exclusive, a loop node never reaches it → the override would have *silently never fired*, re-using
  the round-1 seed forever (the exact bug the task targets). **Fix:** rebind `config` at the top of
  `_execute_node` (the real chokepoint for both walk re-entry and `--only`) via `dataclasses.replace`
  before `plan_node()`, so resolution + config-hash + execution all see the override. The unit tests
  would have passed while the feature was inert — only a *content-asserting* integration test catches
  it (now mandated, non-negotiable).
- **🔴 Permissive-mode hole** (verified): the "absent → loud" guarantee is strict-mode-only; in
  `template_resolution_mode: permissive` an absent carry ref passes the literal `"${...}"` string
  through with only a DEGRADED warning. **Decision (user): strict on carry refs ALWAYS** — a
  per-iteration guard raises regardless of mode (carry is structural plumbing).
- **🟡 `until` + absent polarity bug** (reviewers split; I sided with correctness after re-deriving):
  my draft kept "absent → stop" for both polarities, which re-introduces the "runs once and exits"
  bug for a body that omits the field while not-yet-done. **Decision (user): `until` + absent →
  CONTINUE** (bounded by cap). `evaluate_loop_condition` restructured so absent becomes a falsy
  *value* and polarity applies uniformly; `while` behavior unchanged; malformed-template + string
  stay hard stops.

Hardening also folded in: a **shared `check_loop_polarity` helper** (one source of truth for
exactly-one-of across the two parity layers), `until` field-name parameterized in message text *and*
path, carry-typo check restricted to the namespaced key + ordered after the self-ref check, the
llm/shell unreferenced-carry WARNING, and tests for no-carry-loop / carry×on-error / permissive-strict.

**Verified clean (disputed or non-issues):** constant-input coercion across the static→template move
(scalars are no-ops both paths — no *new* divergence); nested `loop + storage_mode: shared` (recursive
validation catches it, and `mapped` child storage keeps inner `__iteration__` in a separate dict);
`--only`/`--dry-run`/memo interactions.

### Method note (trust calibration)

Every load-bearing claim was verified by a *fresh* `pflow-codebase-searcher` against current source
(line anchors drift — re-confirm). The review agents were treated as fallible: the critical dead-hook
finding was confirmed by a dedicated hook-location verification before accepting the fix, and the
`until`-polarity disagreement between reviewers was resolved by first-principles re-derivation, not by
vote. The plan marks every review correction with `[review-fix]` so they are not silently reverted.

### Documentation updated this session

- `context/CONTEXT.md` — added glossary terms **Carry**, **Seed**, the **Carry vs Seed**
  discriminator, and a polarity note on **Loop condition** (glossary-only; no implementation detail).
