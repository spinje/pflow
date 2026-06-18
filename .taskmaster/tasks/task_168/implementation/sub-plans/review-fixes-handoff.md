# Review fixes — handoff for an isolated agent

> **STATUS (2026-06-11): ALL 9 ISSUES FIXED** — see the progress log's
> "Review-fixes batch" entry for deviations (Issue 1's scope was wider than
> stated below: the literal-batch-of-SUB-WORKFLOW shape was equally broken and
> is fixed too). The deferred section at the bottom remains deferred.

> **Provenance:** a 4-lens deep review (feature-interactions / silent-failures /
> simplicity / test-fidelity) over the committed range `d8e4a3a9..HEAD`, which merged two
> parallel workstreams: **A** (edge click-selection + EdgePanel) and **B** (output rows /
> `output_shape`+`output_path` contract / `scanParamReads` / chip rail). Findings were
> verified against the real renderer before landing here — every issue below includes a
> confirmed repro.
>
> **Scope of THIS document:** the items in workstream-B territory (Python contract, its
> tests, B's frontend functions) plus standalone component cleanups. Workstream-A's items
> (EdgePanel `output_path` blindness, the deep-link invalidation race, `portOwnerHost`
> hostless-container walk, EdgePanel fixture ids, the `bindingParam` consolidation) are
> being fixed by the agent that wrote them — **not in this doc**. If you find them
> already fixed in the tree, that is expected.
>
> **Coordination:** another agent edits `web/src/graph/flow.ts`, `EdgePanel.tsx`,
> `GraphView.tsx` around the same time. Re-read any shared file immediately before
> editing; keep edits additive/localized. This is the working norm on this branch.

## Context you need before touching anything

- Read `web/CLAUDE.md` (frontend conventions — the purity rule for `graph/`, the
  handle-silent-drop bug class, the "components own stroke" rule) and
  `src/pflow/ui/CLAUDE.md` (server/contract). The contract is defined in
  `src/pflow/core/workflow/graph/renderers/react_flow.py` and hand-mirrored in
  `web/src/types.ts` — they must not drift.
- **Gates** (all must pass for every item):
  - Python: `uv run pytest tests/test_core/ -q` and `make check` from repo root.
  - Web: `cd web && npx vitest run && npx tsc --noEmit && npm run build`.
  - **Mermaid goldens stay byte-identical** (`tests/test_core/test_mermaid_golden.py`) —
    several fields exist precisely to protect this (see item 3).
- **Visual verification loop:** `.claude/skills/screenshot-pflow-web-ui/SKILL.md`. The
  server (`uv run pflow ui --no-open --port 8765`) serves the BUILT bundle — run
  `npm run build` in `web/` after frontend changes, and **restart the server after any
  Python change** (it serves old Python otherwise — documented gotcha).
- Useful background: `.taskmaster/tasks/task_168/implementation/progress-log.md` (the
  journey), `implementation/sub-plans/transform-l2-plan.md` and `implementation/sub-plans/batch-chip-rail-plan.md`
  (workstream B's plans), `implementation/sub-plans/edge-selection-plan.md` (workstream A's).

---

## Issue 1 — CRITICAL: a literal-`items:` batch step is INVISIBLE and its spine edges are dropped

**Files:** `src/pflow/core/workflow/graph/renderers/react_flow.py` (the `_is_group_host`
rule, ~line 341–354); consumers that make the damage visible:
`web/src/graph/flow.ts:584-590` (shellBatch skip), `:830` (`is_group_host` leaf skip),
`:937-942` (renderAnchor), `:969` (the warn-drop). Tests:
`tests/test_core/test_graph_react_flow_renderer.py`, `web/src/graph/flow.test.ts`.

**The issue.** The RF contract marks the host node of a **literal** batch
(`batch: items: [a, b, c]`) as `is_group_host: True`, while its batch container ships
`members: []` (the contract NEVER puts item copies in `Container.members` — verified:
`build.py` only appends body nodes to their level's parent container). The frontend's
rules then compose into a hole: an `is_group_host` leaf is never rendered (its group is
supposed to represent it), but a memberless batch group is a "decorator shell" that is
also never rendered and is excluded from `groupsByHost` — so the node has **no
representative at all**. Every edge touching it re-anchors to `null` and is dropped with
only a `console.warn`.

**How it manifests (confirmed repro).** Save this as `/tmp/literal-batch-test.pflow.md`:

```markdown
# Literal batch test

Test literal-items batch rendering.

## Steps

### prep

Make a value.

- type: shell
- command: echo hi

### fan

Greet each name.

- type: shell
- command: echo "hello ${item}"
- batch:
    items: ["alice", "bob", "carol"]
    as: item

### done

Finish.

- type: shell
- command: echo done
```

Render it (`pflow ui`, `?workflow=/tmp/literal-batch-test.pflow.md`): the canvas shows
`prep` and `done` as two disconnected islands. `fan` is gone; both sequential edges are
gone. No error banner. Contract dump (`/api/graph`): `n1 fan is_group_host=True`,
`g0 batch host=n1 members=[]`, edges `e0 n0→n1`, `e1 n1→n2` (present in the contract,
dropped by the frontend). Dynamic batches (`batch: ${ref}`) are NOT affected — their
hosts ship `is_group_host: False` and render as a leaf with the deck + `×N` chip.

**Root cause.** `_is_group_host`'s rule ("literal batch OR workflow-host-with-expanded-
body") dates from when Mermaid-style item copies were expected to populate the batch
container. The contract does not emit item copies for literal batches, and the frontend's
2026-06-10 "batch is a MODIFIER, not a box" redesign made memberless batch groups
unrenderable. The two decisions contradict for exactly the literal-leaf-batch shape.

**Fix direction (preferred: Python).** A literal-batched LEAF should ship
`is_group_host: False` — it is presentationally a leaf with a deck + `⧉ ×{count}` chip,
exactly like a dynamic-batched leaf. `is_group_host` is an RF-contract-only field (added
for the React Flow renderer; Mermaid does not read it), so the change cannot affect
Mermaid goldens — but verify that claim by grepping `mermaid.py` for `is_group_host`
before relying on it. Check what a literal batch **of a sub-workflow** ships (its
workflow item containers DO have members) and keep that path working. Revisit the two
tests that pin the current rule (search `test_graph_react_flow_renderer.py` for
`is_group_host` — e.g. the `unexpanded_dynamic_batch_host_is_not_a_group` family) — they
pin the DYNAMIC arm and should keep passing; the LITERAL-leaf arm changes deliberately.

**Definition of done:**
1. The repro renders: `prep → fan → done` connected, `fan` visible as a SHELL leaf with
   the stacked deck and the ChipRail literal `⧉ ×3` capsule (which is currently
   unreachable dead code — your fix brings it to life; verify it displays `×3`, not `×N`).
2. A Python test pins: literal-batched leaf → `is_group_host is False`; its batch group
   may stay memberless (the frontend never renders shells).
3. A web `flow.test.ts` fixture mirrors the repro contract shape (host=False leaf +
   memberless batch group) and asserts: the leaf node IS emitted, both sequential edges
   survive with correct endpoints. Also FIX the stale comment in `flow.ts` (~line 584:
   "Literal batches (real item-copy members) keep their container" — describes a contract
   shape that never occurs for leaves).
4. Literal batch of a SUB-WORKFLOW still renders (its item workflow groups with members).
5. All gates green; Mermaid goldens byte-identical; screenshot of the repro attached to
   your progress-log entry (`implementation/progress-log.md` — append, never rewrite).

---

## Issue 2 — WARNING: `_result_shape_from_code` / `_is_transform_code` accept a `result` assignment inside a nested `def`

**Files:** `src/pflow/core/workflow/graph/renderers/react_flow.py:826-844`
(`_result_assignments` walks the WHOLE tree via `ast.walk`), `:958-970`, `:789-803`
(`assigns_result`). Tests: `tests/test_core/test_graph_react_flow_renderer.py:812-977`
(the extraction matrix — extend it).

**The issue.** Both extractors treat ANY `result = ...` assignment anywhere in the AST as
the node's output — including one inside a nested `def helper():`. A code node whose
helper uses a local named `result` (but whose module level never writes `result`) ships
`output_shape(field="result", keys=[...])`, and can be classified TRANSFORM.

**How it manifests.** The frontend renders a quiet "produced" `result`/`result.<key>` row
for a port the node never writes — a row that LIES, which is exactly the failure the
fail-closed design documents as worse than no row (see the D4 rules in `web/CLAUDE.md`).
A pure-decider-with-helper could also wrongly present as TRANSFORM.

**Fix direction.** Scope both walks to MODULE-LEVEL statements (iterate `tree.body`, not
`ast.walk(tree)`) — assignment targets, annotated assigns, and aug-assigns at top level
only. Mind the existing fail-closed contract: when in doubt ship `None`, never a partial.

**Definition of done:** a matrix case `def helper(): result = {"a": 1}` (module level
binds something else) → `output_shape is None` AND `is_transform is False`; the existing
matrix stays green; module-level `result` in an `if/else` at top level — decide and pin
(current behavior for top-level branches should be preserved, only NESTED scopes are
excluded). Gates green; goldens byte-identical.

---

## Issue 3 — WARNING: the load-bearing `compare=False` on `Edge.output_path` has no failing test

**Files:** `src/pflow/core/workflow/graph/model.py:117` (the field + its "LOAD-BEARING,
do not 'fix'" comment), `tests/test_core/test_graph_build.py` (~line 944 area — the
output_path tests).

**The issue.** `Edge.output_path` is declared `compare=False` because edge dedup uses
full dataclass equality: putting the path into identity changes the model's edge count,
which changes Mermaid's output (goldens break) and shadowing semantics. The comment
documents this; **no test fails if someone removes `compare=False`** — the existing
output_path tests use one ref per binding, so dedup never fires across differing paths.

**How it manifests.** A future "cleanup" PR makes the field compare, all current tests
stay green, and Mermaid edge counts silently change on workflows with multi-sub-key
bindings.

**Fix direction + definition of done.** Add to `test_graph_build.py`: ONE binding
carrying two sub-key refs of the same field (e.g. a node param
`inputs: {ok: "${gen.result.ok} ${gen.result.no}"}` where `gen`'s code assigns a literal
`result` dict with keys `ok`/`no`) → assert exactly ONE `DATA_FLOW` edge into that input,
with `output_path == ("ok",)` (the first ref's path — the documented dedup-survivor
semantics). Verify the test FAILS when `compare=False` is removed (state this check in
the test's docstring). Gates green.

---

## Issue 4 — WARNING: `scanParamReads` doesn't skip coalesce literal operands; its in-code claim is provably wrong

**Files:** `web/src/graph/flow.ts` (~lines 365–420 — `scanParamReads` and the comment
"Literal operands can't false-positive: a quote/digit boundary never satisfies the root
prefix class"). The Python reference behavior: `src/pflow/core/workflow/graph/scope.py:47-49`
(splits operands via `TemplateResolver.split_coalesce_operands`, skips
`is_literal_operand`). Tests: `web/src/graph/flow.test.ts` (the scanParamReads describe).

**The issue.** The JS mirror of the Python param-text scan does not split `${a ?? "..."}`
coalesce expressions into operands, and the comment's safety argument only holds at a
literal's FIRST token: a space INSIDE a quoted literal satisfies the `(?:^|[\s?])` root
prefix class. Two review lenses found this independently.

**How it manifests.** Param `note: ${cfg.text ?? "ask gen.result owner"}` where `gen` is
a same-parent sibling code node with `output_shape.field === "result"`: the scan matches
root `gen` + tail `.result` inside the LITERAL → `gen`'s `result` row renders as READ
(active) with zero real readers — the inverse of the lie the quiet rows exist to prevent
— and can flip row composition D3→D2 (a parent row appears). Python's build/edges are
immune; only the frontend scan diverges.

**Fix direction.** Mirror scope.py: split each `${...}` segment's text on the coalesce
operator into operands, skip operands that are quoted/numeric literals, scan only
non-literal operands. **At minimum** correct the comment (it currently teaches the next
agent a false invariant) — but the operand split is small and the right fix. Keep the
documented residuals true (bracket refs skipped, no new rows ever created — the D5 rule).

**Definition of done:** a `flow.test.ts` case with the exact manifest shape above
asserts the row stays `quiet: true`; a positive control (`${gen.result.ok ?? "x"}` — ref
in the NON-literal operand) asserts the read IS counted; the misleading comment is gone.
Gates green.

---

## Issue 5 — MINOR: `toFlowEdge` discriminates a decision's END edge by condition presence, not `is_decision`

**Files:** `web/src/graph/flow.ts:1350-1355` (toFlowEdge — "the condition's presence is
the decision test here") vs `:999` (`decisionIds`, the correct fact) and the same rule
correctly applied in `EdgePanel.tsx` (which documents condition-presence as WRONG because
extraction is fail-closed).

**The issue.** A decision whose end-route condition the fail-closed extractor could not
parse ships `condition=None` — `toFlowEdge` then treats its END edge as a static end (no
`outcome` carried), while `buildFlow`'s branchLabels machinery (via `decisionIds`) and
the panel treat it as an outcome. Harmless today only because `outcome` is consumed
together with `condition`; it is the precise inconsistency this same diff documents
elsewhere as a bug pattern.

**Fix + definition of done:** pass the `decisionIds` set (already computed in
`buildFlow`) into `toFlowEdge` and gate on it; one `flow.test.ts` case: a decision END
edge with `condition: null` still carries `outcome: "end"` (and renders the faint LR
"end" row via branchLabels — assert branchLabels includes "end"). Gates green.

---

## Issue 6 — MINOR: the node panel's "consumed" list and the canvas rows disagree about param-text reads

**Files:** `web/src/views/GraphView.tsx:376-386` (the `reads` prop — built from contract
edges only), `web/src/graph/flow.ts:702` (the canvas merges `scanParamReads` into the
observed set). **Coordination: another agent is actively editing both files** — re-read
first, keep the change additive.

**The issue.** Workstream B taught the CANVAS that plain-param refs (`prompt:
${gen.result.ok}` — which form no contract edge) count as reads; the node panel's
"consumed" list was never updated to match.

**How it manifests.** `prompt: ${gen.result.ok}` as the only consumer: the canvas shows
gen's `ok` row as read/active; click `gen` → the ReadPanel shows NO "consumed" fact.
Panel and canvas state contradictory facts about the same binding.

**Fix direction:** export the merged observed-read computation (or reuse
`scanParamReads`' result) so the `reads` prop GraphView passes is the same set the canvas
rows consume. Definition of done: with the manifest shape above, the node panel lists the
read; a contract-edge-only read still lists; web gates green.

---

## Issue 7 — CLEANUP: `Badges.tsx` is hollow scaffolding; ChipRail crumbs

**Files:** `web/src/components/nodes/Badges.tsx:14-46`, its sole call site
`WorkflowNode.tsx:250`, `web/src/index.css` (`.badge-more`, ~line 913),
`web/src/components/nodes/ChipRail.tsx:32`.

**The issue.** After the chip rail took loop/batch/decision, `badgesFor` can return at
most ONE badge (`unexpanded`) — the `Badge[]` list machinery, `max` prop, slice, and `+N`
overflow pill can never fire; `max={detailed ? undefined : 1}` at the call site is dead
logic. Also: `ModifierChips` is exported from ChipRail.tsx with no external consumer, and
ChipRail double-guards a loop/batch check it already performed.

**Fix + definition of done:** collapse Badges to a single conditional unexpanded badge
(GroupNode.tsx renders its unexpanded badge inline — copy that shape), delete
`.badge-more`, unexport/inline `ModifierChips`, drop the double guard. No visual change
(screenshot an unexpanded node before/after — `?workflow=` any workflow with an
unresolved sub-workflow, or trust the existing unexpanded-badge test). Web gates green.

---

## Issue 8 — CLEANUP (take care): two port-ownership rules inside `flow.ts`

**Files:** `web/src/graph/flow.ts:511-517` (`expandTargets`'s `ioOwner`:
`g.parent ?? g.id`, no member filtering) vs `:714-724` (`buildFlow`'s `ioNodeToOwner`:
`effectiveParent(wrapper.parent) ?? wrapper.id`, members filtered `io != null`, wrappers
filtered non-empty). **Coordination: this file is under active edit by another agent.**

**The issue.** Same concept ("the flow node carrying this port's row") under two
different rules 200 lines apart, one per workstream. The divergence is unreachable today
ONLY because wrappers' `parent` is never a shell batch (verified in `build.py` — wrapper
parents are always the workflow container), so `effectiveParent` is a no-op on them. The
next reader must re-derive that proof.

**Fix + definition of done:** one exported helper (e.g.
`ioPortOwners(graph): Map<portId, ownerId>`) used by BOTH sites, encoding the stricter
(`buildFlow`) rule; all existing `flow.test.ts` and `EdgePanel.test.tsx` pins stay green
unchanged (they are the behavioral spec — if any fails, your helper changed semantics:
stop and reconcile). NOTE: `portOwnerHost` in EdgePanel.tsx answers a DIFFERENT question
("which host node authored the binding") and stays separate.

---

## Issue 9 — TEST: regression pin for chip-click camera follow

**Files:** `web/src/views/GraphView.tsx` (`onNavigate` — the `fitView` call, comment
"user-caught 2026-06-11"), `web/src/views/GraphView.test.tsx`, `web/src/test/rf-jsdom.ts`.
**Coordination:** GraphView.test.tsx is shared — re-read before editing.

**The issue.** Deleting the `fitView` call in `onNavigate` reproduces a user-caught bug
(EdgePanel chip naming an off-screen card selects it invisibly — reads as a dead click)
and zero tests fail.

**Fix + definition of done:** a jsdom test that partially mocks `@xyflow/react`
(`importActual` + spy on `useReactFlow().fitView` — check how `test/rf-jsdom.ts`
installs its mocks first), loads GraphView with `?focus=<edge id>` (the deep-link edge
arm at GraphView.tsx ~line 140 — currently also untested; this test covers both), waits
for the EdgePanel, clicks an endpoint chip, asserts `fitView` was called with the
resolved node id in `nodes`. Do NOT pin `padding`/`maxZoom`/`duration` values — they are
tunable. Web gates green.

## Deferred (do not do in this pass — recorded so they aren't lost)

- `web/src/graph/flow.ts` is 1,568 lines; the rows concern (`OutputRow`/`outputRowsFor`/
  `scanParamReads`) and the focus concern (`expandTargets`/`applyFocus`) would lift out
  as sibling `graph/` modules. Pure decomposition — coordinate with all active agents
  before attempting.
- `toFlowEdge`'s 12 positional params → options object for the trailing booleans.
- The selected-edge shade/halo shoot-lab (`--data-edge-selected`, halo multipliers in
  DataEdge/GradientEdge) is pending a USER pick — do not tune these values.
