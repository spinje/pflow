# TRANSFORM Level 2 — result shape + per-key edge landing (implementation plan)

> **Status:** approved by the user 2026-06-10; plan reviewed by `review-plan`
> 2026-06-10 (7 majors, all folded in — no criticals). Design locked against the mock
> in `.taskmaster/tasks/task_168/implementation/transform-l2-mock/` (index.html is
> the source; mock.png the approved render — open index.html in a browser to inspect).
> **Implementer:** a fresh agent. This document is self-contained: every integration
> point is verified with a symbol anchor, every step has a done-when. Line numbers
> are from 2026-06-10 and may drift (parallel work is active in `web/src/graph/`) —
> **anchor on symbols, re-grep before editing.**
>
> **Read first, in order:** (1) this file; (2) `src/pflow/ui/CLAUDE.md` (the contract
> consumption rules — H6 especially); (3) `src/pflow/core/workflow/graph/renderers/react_flow.py`
> (the contract + the existing `_is_transform_code` / `_branch_conditions` AST patterns
> you will mirror); (4) `web/CLAUDE.md` (frontend rules: handle-type invariant, row
> machinery, the TRANSFORM pseudo-kind bullet).

## WHY (one paragraph)

Task 168's viewer shows a code node's output as a single generic `→ result` port.
Real workflows read *into* that result (`${run-validate.result.ok}`), and transforms
*author* its shape (`result: dict = {"ok": ..., "rounds": ...}`) — but today the card
says nothing about what comes out, and every sub-key line leaves one ambiguous dot.
Level 2 fixes both: **Half A** ships the authored shape (keys + types, AST-extracted
fail-closed) so the card shows what a node produces; **Half B** keeps the ref's
sub-path on the edge so each line leaves its exact key row — the project's "edges
land on the exact handle" hard requirement, one level deeper. Half B also generalizes
beyond transforms: any node whose consumers read `result.ok` grows that row
(observed usage), which is the `run-validate → check-validate` case in the mock.

## Locked decisions (user, 2026-06-10 — implement exactly; do NOT re-litigate)

| # | Decision |
|---|---|
| D1 | Row format is **`name: type`** — name first, then a FAINT `: type` suffix (matches the file's own `result: dict` annotation syntax). See mock section 1. |
| D2 | **Wholesale-read case:** if anything reads `${node.result}` bare, the parent `→ result: dict` row renders and key rows nest under it as `· summary: str`. |
| D3 | **Wrapper-collapse case:** if NOTHING reads `result` bare AND keys are known, the parent row is dropped; keys render flat as `→ result.summary: str` — always the FULL dotted path (the text an author must write in `${...}`), never bare `summary`. |
| D4 | **Unread keys** render as quiet-dot rows (grey dot, faint text) with **no line**. They are shape documentation — the "produced but unconsumed" signal. |
| D5 | **Invariant: a connection exists only where some node actually reads.** True by construction (lines ⇐ edges ⇐ `${refs}`) — pin it with a test anyway (a synthetic graph with authored keys but no reading edges must produce zero data-flow edges/lines for them). |
| D6 | **Wholesale sends never decompose:** `prompt: ${combine.result}` is ONE line onto the parent row. No synthetic fan-out into keys. |
| D7 | **One level deep, max.** A ref `${x.result.a.b}` lands on the `a` key row (first sub-segment); deeper structure is read-panel-only. This matches where edges can form (the extractor is one-level by design — see F2). |
| D8 | **Types:** parent row type = the AUTHORED `result:` annotation. Key types are INFERRED fail-closed: `ast.Constant` → its Python type name; `ast.JoinedStr` → `str`; a bare `ast.Name` that matches an annotated input declaration → that annotation; `ast.Dict` → `dict`; `ast.List` → `list`; anything else → `None` (render no type). Never guess. |
| D9 | `result_shape` ships for **ALL code nodes**, not just `is_transform` ones (run-validate's annotation is just as true; display policy is the frontend's). |

## VERIFIED FACTS (all confirmed 2026-06-10 by direct probe/read — trust but re-grep)

| # | Fact | Where |
|---|---|---|
| F1 | `${run-validate.result.ok}` ships `output_field='result'`, `input_name='ok'` — the `.ok` SUB-PATH IS DROPPED. Each distinct ref still gets its own edge (probe: run-validate→check-validate is TWO edges with input_name `ok`/`round`). | live probe via `resolve_validate_build` on `examples/.../validate-fix.pflow.md` |
| F2 | The drop happens at EXTRACTION: `_REF_IN_BLOCK_RE` (`scope.py`, module top) captures root + exactly ONE `.field` segment; the remaining `.ok` tail does not even tokenize as a new root (the prefix class `(?:^|[\s?])` excludes `.`). | `src/pflow/core/workflow/graph/scope.py:12` |
| F3 | Data-flow edges are emitted at **THREE** sites in `build.py` (grep `EdgeKind.DATA_FLOW`): (1) the param-binding path `_add_one_param_input_edges` ~:532 (dedup `if edge not in self.edges` ~:539); (2) the output-`source:` path `_connect_source_expression` ~:630 (no dedup); (3) the workflow-INPUT→consumer path `_add_declared_input_edges` ~:620 — `input_name` only, NO `output_field`. **Only sites 1 and 2 switch to `refs_with_path_in`**; site 3 stays on `refs_in` (no output port → no sub-path), as do `_resolve_batch_source` (~:547) and any other `refs_in` consumer. | `build.py`; corrected per plan review 2026-06-10 |
| F4 | `_resolve_ref(root, field, level)` returns `(NodeId, output_field)` in FOUR cases: an INPUT ref → `(input_node, None)`; field matches a DECLARED output → `(output_node, field)`; **bare ref + exactly one declared output → `(output_node, that_output_name)` — here `output_field != first_segment` (first_segment is None)**; otherwise `(sibling_node, field)`. Step 2.3's equality rule handles all four (cases 1 and 3 keep `()` because `None != name`). | `build.py:632–646` |
| F5 | Edge dedup is full dataclass equality (`if edge not in self.edges`); `graph/CLAUDE.md` documents the multi-role `input_name` lossiness this implies. A new field that participates in `__eq__` would CHANGE dedup → could change Mermaid. | `build.py:~538`, `graph/CLAUDE.md` "best-effort" note |
| F6 | The frontend's output rows are ALREADY derived from edges: `outputFieldsByNode` is built from `e.kind === "data_flow" && e.output_field` in `buildFlow`'s edge scan. Half B slots into this exact mechanism. | `web/src/graph/flow.ts` (~:483–494, search `outputFieldsByNode`) |
| F7 | `outputHandle(field) = "o:" + field` accepts ARBITRARY strings and `handleType` already types the `o:` prefix as `"source"` — `outputHandle("result.ok")` needs ZERO handle-scheme changes. | `web/src/graph/handles.ts` |
| F8 | `rowAnchorsFor(n)` (LR ELK row ports — built by a parallel agent 2026-06-10) iterates leaf rows in RENDER ORDER: `node.params` → `outputFields` → loop rows → branch rows. It and `leafSize` consume the same lists `WorkflowNode` renders — if key rows flow through that one list, anchors/size/ports work UNCHANGED. | `web/src/graph/flow.ts:~291` (`export function rowAnchorsFor`) |
| F9 | All 6 corpus transforms with literal result dicts have EXACTLY ONE `result` assignment — the "exactly one literal-dict assignment" rule covers 6/6 with zero ambiguity. (Multi-arm dicts exist only on deciders, which are out of scope here.) | sweep, `scratchpads/transform-role/sweep.py` output |
| F10 | The code-node INPUT annotation convention is a top-level `ast.AnnAssign` with NO value (`ok: bool`); the result annotation is an AnnAssign WITH a value (`result: dict = {...}`). `impl: object` is such an annotation — never treat annotation Names as builtin references (this exact mistake cost two corpus transforms in Level 1; see progress log "TRANSFORM pseudo-kind shipped"). | `react_flow.py` `_is_transform_code` history |
| F11 | A running `pflow ui` server serves OLD Python after renderer/model edits — `make ui-build` is NOT enough; restart the server before browser verification. | progress log, twice |
| F12 | ruff SIM114 auto-merges adjacent `elif` branches with identical bodies, and a merged isinstance-union can break mypy narrowing — `make check` then never converges. If you hit it: make the branch bodies structurally different. Precedent + comment in `react_flow.py::_bound_names`. | progress log "Finalization" |

## ANTI-GOALS (do NOT do these)

- Do NOT change `refs_in` / `source_refs_in`'s return shape — three callers depend on
  `(root, field)` (build.py, react_flow `is_dynamic`, mermaid.py). Add a NEW function.
- Do NOT let the new `Edge` field participate in equality (`compare=False` is
  load-bearing — see Step 2.2). Mermaid must stay byte-identical.
- Do NOT gate `result_shape` on `is_transform` (D9).
- Do NOT decompose wholesale lines into per-key edges (D6) — edge COUNT must not change anywhere.
- Do NOT render bare key names in the collapsed case — full `result.x` paths (D3).
- Do NOT touch `model.py`/`build.py` with any render vocabulary — the purity guard
  (`tests/test_core/test_graph_model_purity.py`) scans those files for render tokens.
- Do NOT extend extraction to bracket refs (`${x[0].y}`) — existing behavior, fail-closed.
- Do NOT add arrowheads, colors, or any new edge styling — rows only; lines reuse the
  existing data-flow machinery untouched.

---

## PHASE 1 — contract: `RFNode.result_shape` (Python, renderer-only)

**Why first:** independently shippable (Half A alone improves cards), zero model/build
risk, and Phase 3 consumes its output.

### Step 1.1 — dataclasses + field
**Where:** `react_flow.py`, beside `RFNode` (top of file).
**What:** two frozen dataclasses + one additive field:
```python
@dataclass(frozen=True)
class RFResultKey:
    name: str
    data_type: str | None

@dataclass(frozen=True)
class RFResultShape:
    data_type: str | None              # the AUTHORED `result:` annotation, e.g. "dict"
    keys: list[RFResultKey] | None     # literal-dict keys, None when not statically known
```
`RFNode.result_shape: RFResultShape | None` — place it after `is_transform` (all RFNode
fields are constructed by keyword in `_node()`; the only construction site).
**Done when:** `json.dumps(asdict(rf), default=str)` round-trips (existing tests cover
the mechanism; the new field rides along).

### Step 1.2 — extraction
**Where:** `react_flow.py`, module level, beside `_is_transform_code` (mirror its
style; reuse nothing from it — both are small, independent walks).
**What:** `_result_shape(code: str) -> RFResultShape | None`:
1. `ast.parse`; on `SyntaxError` → `None`.
2. Collect input annotations: top-level `AnnAssign` with `value is None` and a `Name`
   target → `{target.id: ast.unparse(annotation)}` (F10).
3. Find ALL assignments to `result` (Assign/AnnAssign, any depth — reuse the
   tuple-target walk style of `_assigned_names`).
4. `data_type` = the annotation of a `result` AnnAssign when it is a simple
   `ast.Name` annotation (`dict`, `str`, `int`, …) — `ast.unparse(annotation)`;
   `None` for subscripted/exotic annotations (fail-closed).
5. `keys`: ONLY when there is **exactly one** `result` assignment AND its value is
   `ast.Dict` with every key an `ast.Constant` str (F9). Per-key `data_type` per D8
   (the annotated-input map from item 2 feeds the bare-`Name` case). Otherwise
   `keys=None` — never a partial list.
   **What counts as a "result assignment" (pin this — two readings diverge):** any
   `Assign`/`AnnAssign`/`AugAssign` whose TARGET WALK contains a `Name` `result` —
   this includes the subscript mutation `result["k"] = v` (its target is a
   `Subscript` whose `.value` is `Name result`). So `result = {...}` followed by
   `result["k"] = v` is TWO assignments → `keys=None` (a strict Name-target check
   would ship a keys list missing `k` — quiet rows that LIE). An **empty** literal
   dict (`result: dict = {}`) ships `keys=None` too — an empty literal is almost
   always a to-be-mutated accumulator.
   **Valueless `result:` AnnAssign corner:** an AnnAssign with NO value is an INPUT
   declaration by the code-node convention (F10) — it is neither a result assignment
   nor an annotation source. Only AnnAssigns WITH a value count for items 4 and 5.
6. Return `None` (not an empty shape) when there is no `result` assignment at all.
**Wire:** in `_node()`: `result_shape=self._result_shape(node)` with a small method
mirroring `_is_transform` (kind == "code" + str code param gate → else `None`).
**Done when (tests, in `tests/test_core/test_graph_react_flow_renderer.py`):**
- matrix: annotation only (`result: str = x.upper()` → `("str", None)`); single literal
  dict with typed keys (`{"ok": True, "n": count}` where `count: int` is an input →
  keys `[("ok","bool"),("n","int")]`); f-string value → `str`; unknown value expr →
  key with `data_type=None`; TWO result assignments → `keys=None` (annotation still
  shipped); `result = {...}` + `result["k"] = v` → `keys=None` (the subscript-mutation
  case); empty literal dict → `keys=None`; a VALUELESS `result:` AnnAssign (input
  declaration) is ignored entirely; no result → `None`; non-code node → `None`;
  syntax error → `None`.
- contract: a built graph ships the shape; round-trip passes.
- **types.ts mirror in this step**: add `RFResultKey`/`RFResultShape` interfaces +
  `result_shape: RFResultShape | null` to the `RFNode` interface in `web/src/types.ts`
  (with a fail-closed doc comment like `is_transform`'s), and update any test fixture
  factories that construct full `RFNode` objects (`flow.test.ts` `node()`,
  `collapse.test.ts`, `GraphView.test.tsx` — add `result_shape: null`). Run
  `npx tsc --noEmit` — the web tree must stay green after EVERY phase.
- REGRESSION GUARD: `impl: object` as an input annotation must not affect anything (F10).

### Phase 1 gate
`uv run pytest tests/test_core/test_graph_react_flow_renderer.py tests/test_core/test_graph_model_purity.py tests/test_core/test_mermaid_golden.py -q` — all green;
`make check` clean (beware F12).

---

## PHASE 2 — model + build: the edge sub-path

**Why:** the sub-path must survive from the ref text to the wire; it is dropped at the
regex today (F2). This is the only phase touching `model.py`/`build.py` — the
blast-radius phase; its nets are the goldens + a corpus diff.

### Step 2.1 — scope.py: a path-preserving extractor
**Where:** `src/pflow/core/workflow/graph/scope.py`.
**What:** extend the regex to capture the full dotted tail, keep old callers intact:
```python
_REF_IN_BLOCK_RE = re.compile(r"(?:^|[\s?])([a-zA-Z0-9_-]+)((?:\.[a-zA-Z0-9_-]+)*)")
```
- `refs_in` / `source_refs_in` MUST still return `(root, field)` where field is the
  FIRST segment or `None` (derive: `parts = tail.split(".")` etc.). Their behavior is
  pinned by existing tests — byte-identical output required. GOTCHA: the new group 2
  matches the EMPTY STRING (not None) on a bare ref — the derivation must map
  `"" → (root, None, ())`, not `(root, "", ())`.
- New `refs_with_path_in(value) -> list[tuple[str, str | None, tuple[str, ...]]]` —
  `(root, first_segment, remaining_segments)`. Implement ONE internal walk both
  functions share so they cannot drift.
**Done when:** existing scope/build/renderer tests green unchanged; new unit cases:
`"${a.b.c.d}"` → `("a","b",("c","d"))`; `"${a.b}"` → `("a","b",())`; `"${a}"` →
`("a",None,())`; coalesce `"${a.b.c ?? x.y}"` → two entries; literal operands skipped.

### Step 2.2 — model.py: `Edge.output_path`
**Where:** `model.py`, `Edge` dataclass.
**What:**
```python
output_path: tuple[str, ...] = dataclasses.field(default=(), compare=False)
```
**WHY `compare=False` (load-bearing, do not "fix"):** edge dedup is full equality (F5).
In identity, two same-`input_name` sub-key refs would become two edges → Mermaid edge
count changes → goldens break. Out of identity, dedup is byte-identical to today; the
accepted lossiness (first ref's path wins in that rare shape) is EXACTLY the
documented `input_name` multi-role precedent. Put this rationale in a comment on the
field.
**Done when:** full `tests/test_core/` green untouched; goldens byte-identical.

### Step 2.3 — build.py: carry the tail
**Where:** emission sites 1 and 2 ONLY (F3 — `_add_one_param_input_edges` and
`_connect_source_expression`; site 3 and the batch-source resolver stay on `refs_in`).
**What:** switch those two loops to `refs_with_path_in`. Set `output_path=tail`
**only when BOTH** hold:
1. **the ref did not resolve through the batch alias** — an EXPLICIT guard
   (`root == batch_alias` → always `()`). This is NOT implied by the equality rule:
   with `as: item`, `items: ${prep.rows}`, a binding `${item.rows.x}` has
   first_segment `"rows"` == the batch source's output_field `"rows"` — the
   comparison alone would attach a WRONG path `("x",)` to an edge whose source is
   `prep`. The guard must come first.
2. the resolved `output_field == first_segment` (covers F4's four cases: an INPUT
   ref resolves with `output_field=None`, and the bare-ref-single-output case
   resolves with `first_segment=None` — both keep `()` since `None != name`).
**Done when:** a new build test pins: `${gen.result.ok}` between two code nodes →
edge has `output_field="result"`, `output_path=("ok",)`; `${gen.result}` → `()`;
`${input_x.y}` (workflow input) → `()`; `${gen.result.a.b}` → `("a","b")`; **the
batch-alias counterexample** (`as`-alias key colliding with the batch source's
output_field name) → `()`.

### Step 2.4 — react_flow.py: ship it
**Where:** `RFEdge` + `_resolve_edges`.
**What:** `RFEdge.output_path: list[str] = field(default_factory=list)` (additive,
JSON-friendly list). In `_resolve_edges`, emit `list(edge.output_path)` — and CLEAR it
(`[]`) whenever `output_field` is cleared by truncation re-anchoring (same line, same
rule: a re-anchored endpoint no longer names a real port — H9/W1).
**Done when:** renderer test: the path rides the wire on a synthetic graph; a
truncation-re-anchored edge ships `[]`; round-trip green. In the SAME step: update
the `web/src/types.ts` `RFEdge` mirror (`output_path: string[]`) AND the
`flow.test.ts` `edge()` fixture factory's defaults (`output_path: []` — all edge
fixtures go through it, so it's one line), then run `npx tsc --noEmit`. The web
tree must be type-green at the end of Phase 2, not just Phase 3 — Phase 2 may be
shipped/handed off alone.

### Phase 2 gate
`make test` + `make check` green. **Corpus Mermaid diff** (the decisive net): render
all examples before/after with the pattern in `scratchpads/transform-role/mermaid_corpus.py`
→ `diff -rq` MUST be empty. Goldens byte-identical.

---

## PHASE 3 — frontend: rows + per-key landing

**Why this shape:** F8 — `WorkflowNode`, `leafSize`, and `rowAnchorsFor` all consume
the node's output-row list. Make that list THE single source of truth and everything
(render, height, LR ELK ports, handles) stays in lockstep by construction.

**⛔ PHASE 3 ENTRY GATE (hard, not advisory):** `git status web/src/` must be CLEAN
(or every dirty file's author identified and coordinated). A parallel agent was
actively editing `flow.ts`/`rowAnchorsFor`/`WorkflowNode.tsx`/`GroupNode.tsx`/`index.css`
on 2026-06-10 (LR row ports + other work). Phases 1–2 are Python-only and
conflict-free; do them first regardless. Re-read `rowAnchorsFor` before Step 3.2 —
its row iteration is the surface you extend.

### Step 3.1 — the row model
**Where:** `flow.ts`.
**What:** replace `LeafData.outputFields: string[]` with:
```ts
export type OutputRow = {
  field: string;          // the handle key: "result" | "result.summary" (full dotted path)
  label: string;          // what the row shows: "→ result" | "· summary" | "→ result.summary"
  dataType: string | null;
  quiet: boolean;         // authored-but-unread (D4): grey dot, faint text, NO line possible
  nested: boolean;        // renders indented under a parent row (D2 case)
};
// LeafData.outputRows: OutputRow[]
```
Derivation per node (pure function, unit-test it directly):
1. **observed** = from edges: group `output_field` + first `output_path` segment →
   read-set of `"result"` (bare reads exist) and/or `"result.ok"` … (sub-reads).
2. **authored** = `node.result_shape` (parent type + keys).
3. Compose per D2/D3/D4 — **the key set is always authored ∪ observed** (an observed
   sub-read of a key ABSENT from the authored shape — stale shape, post-literal
   mutation, permissive mode — still gets an ACTIVE row; otherwise its line falls to
   NODE_OUT and the feature fails for exactly the read it exists to show):
   - bare read exists (or keys unknown) → parent row (`label "→ result"`, type from
     shape) + one nested row per key in authored ∪ observed (`· key`), quiet when
     not in the read-set;
   - no bare read AND (authored ∪ observed) non-empty → flat rows `→ result.key`
     for every key in the union (read ones active, unread quiet), NO parent row;
   - non-`result` output fields (e.g. `stdout`) keep today's single-row behavior,
     EXCEPT they also gain sub-rows when sub-reads exist (the observed-usage
     generalization — same composition with `result_shape=None`).
4. Ordering: parent first; authored keys in AUTHORED order, then observed-only keys
   in first-read order.
**Done when:** the composition matrix is pinned: wholesale+keys / collapsed /
unread-quiet / keys-unknown / **observed-only key (not in authored shape) gets an
active row in both parent-row cases** / non-result sub-read / no-output node.

### Step 3.2 — size, anchors, render
**Where:** `leafSize` + `rowAnchorsFor` (`flow.ts`), `WorkflowNode.tsx`, `index.css`.
**What:** both functions iterate `outputRows` (one row each — `outputHandle(row.field)`,
side "right", same y-math; F8 makes this a list-swap, not new math). `WorkflowNode`
renders `row.label` + faint `: type` suffix (D1) + quiet styling (D4 — reuse the
faint-dot pattern; new classes documented at their construction site per the CSS
grep-comment convention). ReadPanel: add the full shape (incl. >1-level paths and all
keys) to the node facts.
**Done when:** web tests pin: row labels/types/quiet flags reach the DOM model
(`LeafData`), `rowAnchorsFor` emits one anchor per row with `o:`-prefixed handles, and
the ELK row-port test still passes.

### Step 3.3 — landing
**Where:** `sourceHandleFor` (`flow.ts`).
**What:** for a data-flow edge with `rowsVisible && isRealSource`:
```
edge.output_path[0] present AND a row with field `${output_field}.${output_path[0]}` renders
  → outputHandle that row             (the per-key landing; D7: first segment only)
else edge.output_field row renders → outputHandle(output_field)   (today's behavior)
else NODE_OUT                                                      (H6 ladder)
```
The "row renders" check MUST be against the actual `outputRows` list (the silent-drop
rule: never name a handle that does not render).
**Done when:** flow tests pin: `result.ok` ref → lands on the key row; bare ref →
parent row; 2-deep path → first-segment row; rows hidden (beautiful, unexpanded) →
NODE_OUT; the HANDLE-TYPE INVARIANT test extended with an `outputRows` fixture; the D5
invariant test (authored keys, zero reading edges → zero lines incident to those rows).

### Phase 3 gate
`npx vitest run` + `npx tsc --noEmit` + `npm run build` clean; no `outputFields`
references remain (grep — the rename must be total, or anchors/size/render drift).

---

## PHASE 4 — verification + docs (the implementer does ALL of these)

0. **Invoke the `/code-review` skill on the full diff** BEFORE browser verification —
   this is a 4-phase, contract-spanning change (regex → model → build → renderer →
   wire → row model → layout ports → landing); repo convention for this scope.
   Address findings before proceeding.
1. `make test`, `make check`, web gates — green.
2. Corpus Mermaid diff — still empty (Phase 2's net, re-run on the final tree).
3. **Real browser** (use `.claude/skills/screenshot-pflow-web-ui`; F11 — restart the
   server first): (a) execute-plan, advanced, framed on `group-tick` → three lines
   leave three key rows (mock section 2); (b) validate-fix framed on `run-validate` →
   observed `· ok`/`· round` rows on a plain CODE node (mock section 3); (c)
   deep-research framed on `combine` → wholesale case: parent row + nested keys,
   ONE line (mock section 1, middle card); (d) beautiful density unchanged at rest
   (rows follow showBody; lines follow hidden-until-focus — no new rules).
4. Docs sync: `ui/CLAUDE.md` (both contract fields + the compare=False note),
   `web/CLAUDE.md` (the outputRows single-source rule + landing ladder),
   `graph/CLAUDE.md` (Edge.output_path + WHY it is compare=False),
   `visualization-requirements.md` (Implemented entry), progress-log entry
   (deviations + surprises, per the log's convention).

## Honest residuals (state these in the review, do not fix)

- Bracket refs (`${x[0].y}`) form no sub-path (existing extractor behavior).
- Two sub-key refs sharing one `input_name` in one string: first path wins
  (compare=False dedup; documented precedent).
- Multi-arm same-key literal dicts ship `keys=None` (fail-closed; no corpus case).
- Key TYPES are best-effort (D8); a typeless key row is correct, not a bug.
- `dataFlowLabel` (flow.ts, the beautiful-mode `out → in` floating label) is
  deliberately UNTOUCHED: a revealed line for `${x.result.ok}` still labels
  `result → ok`. Acceptable — row-to-row landings drop the label anyway, and the
  node-level fallback's label remains truthful. Do not extend it in this increment.
- Phase 2's Mermaid corpus diff does not exercise `_resolve_edges`' dedup key
  directly; if paranoid, an optional RF-wire assertion (edge count/identity
  unchanged across all examples before/after) is cheap — the dedup key
  (react_flow.py `_resolve_edges`) is untouched by this plan, so this is optional.
