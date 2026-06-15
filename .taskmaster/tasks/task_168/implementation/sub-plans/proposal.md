# Plain-param sibling refs form no DATA_FLOW edges — analysis + fix proposal

**Status: IMPLEMENTED (2026-06-13)** — as Option A, extended to the A2
consolidation (one general-purpose emitter `_add_ref_edges`; the inputs-only
`_add_declared_input_edges` + pair-dedup deleted) plus the prompt-cache arm
(`input_name="prompt_cache"` edges from `## Cache` chunks). Plan + guards:
`.taskmaster/tasks/task_168/implementation/sub-plans/unified-data-flow-edges-plan.md`;
journey: the task-168 progress log (2026-06-13 entry).

**Original status:** proposal, not implemented. **Date:** 2026-06-11.
**Trigger:** designing a "Referenced by" panel section (who consumes this node's
output) revealed that consumer lists derived from contract edges under-report —
which led to the underlying model gap this doc is about.

## TL;DR

A `${gen.response}` reference to a **sibling node** inside a regular param
(an llm `prompt:`, a shell `command:`, …) produces **no DATA_FLOW edge** in the
GraphModel — even though pflow's validator and runtime treat it as a real data
dependency, and the Task 168 spec promised a line per `${ref}`. Only refs in
specific authoring positions form sibling edges today. Proposal: extend the edge
builder so sibling refs in any param form edges (Option A), with a verification
phase first because the blast radius (Mermaid goldens, shadowing, fixtures) is
real but not yet measured.

## Verified facts (each reproduced on this branch, 2026-06-11)

### 1. The repro

```markdown
### gen
- type: llm
- prompt: "write a poem"

### consume-prompt
- type: llm
- prompt: "Summarize this: ${gen.response}"     ← ref in a plain param

### consume-inputs
- type: code
- inputs: {"text": "${gen.response}"}           ← ref in an inputs: binding
```

`build_graph` emits exactly **one** DATA_FLOW edge:
`gen -> consume-inputs (field=response, input=text)`. The identical read in
`consume-prompt`'s prompt produces no edge. `render_mermaid` on the same graph
shows only the sequential chain.

### 2. Where the asymmetry lives (`core/workflow/graph/build.py`)

Sibling-resolving DATA_FLOW edges are emitted from exactly these positions:

- `_add_child_input_data_flow` (~`build.py:465`) — the `inputs:` **binding
  dict** (code nodes' `inputs` param, sub-workflow step bindings). Resolves
  sibling roots via `_resolve_ref` → full edges with
  `output_field`/`input_name`/`output_path`.
- `_connect_source_expression` (~`build.py:636`) — workflow output `source:`
  expressions.
- batch `items:` (`_resolve_batch_source` + the leaf-batch arm in
  `_add_one_input_consumer_edges`) and loop `max_iterations` when templated
  (`_add_loop_cap_edges`).

For **all other params**, `_add_one_input_consumer_edges` (~`build.py:567`)
walks every param string but routes through `_add_declared_input_edges`
(~`build.py:610`), which resolves roots **only against `level.inputs`**
(declared workflow inputs — `build.py:626`: `source = level.inputs.get(root)`;
unresolved roots are skipped). Sibling node roots fall through silently.

### 3. pflow's own semantics disagree with the model

`pflow <file> --validate-only` on a workflow where a *prompt* references a
later node errors with: *"Node 'consume-prompt' references 'gen' in parameter
'prompt', but 'gen' comes after this node in execution order."* So the
validator (`core/workflow/data_flow.py`) treats a plain-param sibling ref as a
real ordering dependency. The graph model is the only layer that doesn't.

### 4. The wire contradicts a documented invariant

`render_react_flow` on the repro ships `consume-prompt.prompt` with
`is_dynamic=True` and **zero** data-flow edges touching `consume-prompt`.
Task 168's review/spec state the invariant "`is_dynamic=True` ⟺ a DATA_FLOW
edge exists" — that invariant is **already false on the wire today** for
sibling refs in plain params. (It holds for workflow-input refs and `inputs:`
bindings, which is presumably what it was written against.)

### 5. The spec promised these lines

`task-168.md` Solution: "**Template connections** (`${ref}`) drawn as lines
between nodes (the GraphModel's `DATA_FLOW` edges — one per `${ref}`)."
Verification: "a param like `"${a.x} and ${b.y}"` renders as **two** connecting
lines (one per ref) landing on that param." Plain-param sibling refs don't
deliver this today.

### 6. The frontend already half-compensates

`web/src/graph/flow.ts` `scanParamReads`/`paramTextReads` scan sibling param
*text* so a node's output rows don't falsely read "quiet / no reader" when a
sibling's prompt consumes them. The scan deliberately draws **no lines** and
creates **no rows** (D5: lines come only from contract edges). It is scope-aware
and batch-alias-skipping, and splits `??` coalesce operands / skips literal
operands (mirrors `TemplateResolver`). Its documented residual: refs outside
params (loop conditions) are unscanned.

### 7. In the lyrics-generator corpus dump, every data edge's target was a code node

Consistent with the rule (code nodes consume via `inputs:`); llm steps that
read siblings via `prompt:` get no incoming data edge. (One workflow's dump —
indicative, not a corpus-wide measurement.)

## Inferred — believed but NOT fully verified

- **The scope is inherited from the legacy Mermaid generator, not a decided
  position.** Evidence: the Task 155 review records that the first build cut
  "only generated data-flow for expanded child inputs, *mirroring old Mermaid*"
  and a test forced ONE broadening (sub-workflow outputs threading to sibling
  consumers). No task-155/168 doc records a decision *against* plain-param
  sibling edges. Contrast: loop `while`/`until`/`carry` refs producing no edges
  IS an explicit recorded decision (task-155 review: "deliberately produce no
  data-flow edges (stay metadata); only `max_iterations: ${ref}` creates a
  dependency edge") — that decision is NOT in question here.
- **Why the legacy Mermaid scope was what it was** — unknown. Possibly clutter
  control, possibly just incremental growth. Don't assume either.

## Why fix it

1. **The UI's mission is "reveal the wiring the text implies."** The most
   natural authoring shape — an llm prompt reading a sibling's output — is
   exactly the connection a reader wants to see, and it's invisible.
2. **One source of truth.** Today the "who reads X" fact lives in three places
   that can disagree: contract edges, the frontend param-text scan, and the
   validator's dependency analysis. Emitting the edges folds the first two
   together (the scan mostly retires) and aligns the model with the validator.
3. **Downstream features need it**: the planned "Referenced by" panel section
   under-reports from edges alone; same for any future overlay/impact analysis
   keyed on data edges.
4. It makes the documented `is_dynamic ⟺ edge` invariant actually true.

## Proposal — Option A (recommended): emit the edges in Python

Extend `_add_one_input_consumer_edges` so sibling roots in plain params resolve
via `_resolve_ref` (the same resolution `inputs:` bindings use), emitting
DATA_FLOW edges with `output_field`, `input_name` (= the param name), and
`output_path` — subject to the existing guards (batch-alias skip, literal
operands, `item`/`__iteration__` exclusion, `(source, target)` dedup semantics —
see open questions).

### Phase 0 — measure before committing (cheap, do first)

- **Corpus edge-count diff**: build old-vs-new edge sets for the committed
  fixture workflows + the Task 163 harness + lyrics-generator; count new edges
  and eyeball where they land. (The harness has ~124 data edges today; growth
  magnitude is unknown.)
- **Mermaid golden diff**: regenerate goldens, read the actual diff. New dashed
  data arrows will appear; `shadowed()` may newly suppress some sequential
  arrows in `render_mermaid`'s narrower `_edge_shadowed_for_render` — the
  visual outcome is unknown until rendered.
- **The beautiful-density shadowing interaction** (the one identified risk that
  could *remove* visible structure): `shadowed()` is "structural edge covered by
  a data-flow edge from the same source." New data edges ⇒ more sequential
  edges ship `shadowed=true`. The frontend's policy for shadowed structural
  edges (dim in advanced / hide or 35%-opacity in beautiful — exact current
  behavior needs checking in `flow.ts`/`applyFocus`/CSS before relying on this
  sentence) could thin the control skeleton beautiful is built on. Verify and,
  if needed, adjust the *frontend policy* (predicates-as-facts: Python ships the
  fact, TS picks the treatment — the established split).

### Phase 1 — the builder change

- `build.py`: in the plain-param walk, attempt sibling resolution for roots not
  found in `level.inputs`. Reuse `refs_with_path_in` so `output_path` ships.
  Keep loop `while`/`until`/`carry` exactly as-is (decided no-edge).
- Tests: extend `test_graph_build.py` with the repro shapes (prompt ref →
  edge with `input_name="prompt"`; interpolated multi-ref param → one edge per
  ref; batch-alias param ref → still no false edge; literal operand → none).

### Phase 2 — regen + invariants

- Mermaid goldens (reviewed diff, not blind regen), React Flow contract
  fixtures (`tests/fixtures/react_flow_contracts/_generate.py` — the drift
  guard names the command), Python no-info-loss test, frontend
  `lossless.test.ts` over the regenerated real contracts.

### Phase 3 — frontend consumes the truth

- Param rows: new edges land on their param rows via the existing
  `input_name` machinery — expected to need no new code (verify).
- `scanParamReads`: shrink or retire. Careful: it currently *also* covers
  shapes that stay edge-less (loop conditions are the documented residual —
  those remain). Decide retire-vs-keep against what Phase 0 shows.
- "Referenced by" panel section then derives from edges alone.

### Effort guess

A day-ish of careful work end-to-end (Phase 0 ~1-2h). Touches the shared model,
so the review bar is the Mermaid-parity + losslessness suites, not just new
unit tests.

## Option B (stopgap): frontend union only

Keep the model as-is; the "Referenced by" section unions edge-consumers with
`paramTextReads` readers (the no-claims gate carries over). Cheap (~hours),
honest in the panel — but the canvas keeps silently omitting real connections,
and the multi-source-of-truth split stays. A would absorb B later; B does not
advance A.

## Open questions (decide during Phase 0/1, not silently)

1. **Dedup semantics for the new edges.** `_add_declared_input_edges` dedups
   per `(source, target)` via the `connected` set (one edge per node pair);
   `_add_one_param_input_edges` dedups by full edge equality (one edge per
   distinct ref). Which do plain-param sibling edges get? Full-equality matches
   the "one line per `${ref}`" spec promise; pair-dedup matches the current
   input-edge behavior. Affects edge counts everywhere.
2. **Does Mermaid want these edges drawn?** `render_mermaid` consumes the same
   model. Options if the goldens get noisy: accept (truth), or narrow Mermaid's
   render policy (its prerogative — render policy is per-renderer by design).
3. **`Edge.output_path` `compare=False` interaction** — two same-`input_name`
   sub-key refs collapse at dedup today (documented lossiness). The new edges
   inherit this; fine, but state it in the contract docs.
4. **Performance**: `_params_strings` already walks every param; resolution
   adds dict lookups. Expected negligible — but the harness build time is the
   thing to spot-check.

## References

- `src/pflow/core/workflow/graph/build.py` — `_add_one_input_consumer_edges`
  (~567), `_add_declared_input_edges` (~610, the inputs-only resolution at
  ~626), `_add_child_input_data_flow` (~465), `_connect_source_expression`
  (~636), `_resolve_ref` (~654).
- `src/pflow/core/workflow/graph/CLAUDE.md` — model invariants, `output_path`
  `compare=False` note, loop-refs-no-edge decision.
- `.taskmaster/tasks/task_155/task-review.md` — "mirroring old Mermaid" (the
  inheritance evidence), shadowed() asymmetry note.
- `.taskmaster/tasks/task_168/task-168.md` — the template-connections spec
  promise + the `is_dynamic` derivation requirement.
- `.taskmaster/tasks/task_168/task-review.md` — Unexpected Discovery #4 (the
  first written observation of this gap).
- `web/src/graph/flow.ts` — `scanParamReads`/`paramTextReads` (the frontend
  compensation that Phase 3 revisits); `web/CLAUDE.md` output-rows bullet (D5).
- Repro workflows: recreate from the TL;DR snippet (originals were in `/tmp`).
