# Every `${ref}` Is an Edge — Unified Data-Flow Emission + Prompt-Cache Edges

## Context

**Problem.** The GraphModel under-reports data dependencies that pflow's own validator enforces.
Three gaps, one disease:

1. **Plain-param sibling refs form no DATA_FLOW edge.** `prompt: "Summarize: ${gen.response}"`
   draws nothing; `inputs: {text: "${gen.response}"}` draws a line. The validator treats both as
   real ordering dependencies (`pflow --validate-only` rejects forward refs in plain params).
   Measured: `generate-changelog` renders 11 of 39 real connections; `claude-code-git-workflow`
   renders 0 of 8.
2. **Input edges are pair-deduped.** A node reading `${repo_dir}` in two params gets ONE edge
   labeled with whichever param came first — the other param row shows a live dot with no line
   landing on it (the documented "multi-role lossiness").
3. **Prompt-cache dependencies are invisible.** A node with `prompt_cache: [extract.response]`
   depends on `extract` *exclusively* through the cached system prefix (an inline body ref to the
   same path is a validation ERROR — `cache.prompt-body-duplicates-cache`), and `build_graph`
   never reads `ir["cache"]` at all.

**Outcome.** One rule an agent can hold in one sentence: *every `${ref}` the language enforces as
a dependency is one DATA_FLOW edge.* One general-purpose emitter in `build.py` (the second is
deleted), the `is_dynamic ⟺ edge` invariant becomes true on the wire, and the UI's canvas lines +
`references / referenced by` panel sections complete from contract edges alone.

**Origin.** `.taskmaster/tasks/task_168/implementation/sub-plans/proposal.md` (Option A, user-approved),
extended by user decisions: (a) consolidate to a single emitter — one-edge-per-distinct-ref,
inputs included; (b) include the prompt-cache arm; (c) dedup Mermaid's duplicate rendered lines;
(d) stop dimming shadowed control edges in advanced density (browser before/after as the
acceptance gate). Corpus impact measured: 656 → ~830 data edges across 64 buildable example
workflows + lyrics-generator; build time unchanged (0.148s on the plan-to-code harness).
Plan reviewed by a structural plan-review pass and a feature-interactions pass (2026-06-12/13);
all findings folded in below.

**Decided — do not re-litigate** (rationale: the proposal + the task conversation):
- One emitter, full-equality dedup, one-edge-per-distinct-ref (inputs included).
- Loop `while`/`until`/`carry` refs stay edge-less (recorded Task 155 decision). The templated
  `max_iterations` cap keeps its edge — unchanged.
- Cache edges ship `input_name="prompt_cache"`; no new contract field. A cache edge COUNTS AS A
  READ of the producer's field (un-quiets its output row, lists in the panel's consumed paths) —
  intended: the field genuinely is read through the cached prefix.
- Mermaid dedups identical rendered arrow lines (per-renderer presentation; the model keeps all
  edges).
- `_params_strings` deepens to lists + nested dicts (validator parity); react_flow's
  `_string_leaves` changes in lockstep (H5 preserved — both sides move together).
- Web `scanParamReads`/`paramTextReads`/`consumedReadPaths` are KEPT: build-time edge dedup still
  collapses two same-param sub-key refs (`Edge.output_path` is `compare=False` — load-bearing, do
  NOT change it), so the text scan recovers reads the edges lose.
- `_connect_source_expression` (build.py:636–652, output `source:` expressions) is INTENTIONALLY
  UNTOUCHED. Its no-dedup is load-bearing: two sub-key refs in one output `source:` must keep both
  edges (react_flow.py:308–312 comment). Do NOT "consolidate" it into the emitter.

## Verified facts — do not re-derive
(4 codebase-searcher reports + 2 corpus measurements + 2 plan reviews, 2026-06-12/13.)

- `_resolve_ref` (build.py:654–668) already resolves inputs-first-then-siblings, returns
  `(NodeId, output_field|None)`, maps sub-workflow output ports, and returns None for
  `item`/`__iteration__` roots. It becomes the single resolution authority.
- The dual-resolution pattern already exists at `_add_loop_cap_edges` (build.py:596–608); the
  consolidation makes every site a single call. The consolidated loop-cap edge shape is
  byte-identical to today's (verified trace).
- Full-equality dedup (`if edge not in self.edges`, build.py:553) absorbs duplicates when the
  params walk and `_add_child_input_data_flow` both emit for `inputs:` dict entries — both walks
  produce byte-identical shapes (verified trace: same `input_name`, same `target_inputs` map, same
  alias semantics, same `output_path` guard). `_add_child_input_data_flow` runs first
  (build.py:138), so its field values win under dedup.
- `_LevelResult` (build.py:58–65): `inputs`, `outputs`, `nodes`, `produces`, `incoming` (expanded
  workflow/dynamic-batch hosts only), `batch_item_incoming` (literal-batch hosts only — never
  `incoming`).
- Cache chunks: exactly ONE ref per chunk by construction; `name == var` enforced
  (markdown_parser.py:1786–1794). Chunk roots may be workflow inputs (validator
  data_flow.py:1147–1151); alias-rooted chunk vars are validator-rejected. `## Cache` is strictly
  per-file (DD#12); child IR carries its own `cache` key through sub-workflow resolution.
  `prompt_cache: list[str]` is a node TOP-level field (ir_schema.py:268–275), LLM-only
  (validator), so a cache consumer never has child-input maps.
- Grammar parity: scope.py / validator / TemplateResolver / flow.ts agree on coalesce (both
  operands), literals (skipped), deep paths, hyphens. Bracket refs (`${data[0].x}`) keep their
  edge (root survives) but lose `output_field`/`output_path` — role-lossy, not absent. The
  validator's grammar gate is `re.fullmatch` of `TemplateResolver._VAR_NAME_PATTERN`
  (template_resolver.py:28; `_PFLOW_VAR_RE` in data_flow.py:33) — the pattern INCLUDES bracket
  segments, so gating on it preserves bracket-ref edges.
- Mermaid renders data edges ONLY at 5 filtered sites (mermaid.py:117/172/224/330/337:
  input-consumers / child-inputs / batch-items / outputs ×2) — body→body sibling and cache edges
  are invisible there. Input-ROOTED edges (including input-rooted cache chunks) DO render at the
  input site. `_edge_shadowed_for_render` rule 1 (mermaid.py:424–426) KEEPS a structural arrow
  when a same-pair data edge exists. All 9 goldens verified byte-identical IF the three landmine
  guards below hold (no golden has multi-param same-input reads, cache blocks, input-rooted batch
  `items:`, or input-only-bound small literal batches).
- Baked facts drift legitimately: `is_terminal` counts DATA_FLOW out-edges (model.py:172–179) and
  `shadowed()` counts same-source data coverage — new edges can flip both for individual nodes/
  edges. Frontend consequences are cosmetic-by-construction: the io-flow Outputs-card skeleton
  derives from CONTROL edges only (flow.ts:871–879, deliberately not `is_terminal`); Mermaid's end
  sink dedupes (mermaid.py:412–422). A flipped fact in the fixture-regen diff must be explainable
  by a new edge — then it's correct.
- RFEdge ids are positional (`e{len(resolved)}`, react_flow.py:317) — new edges renumber ids ⇒
  committed contract fixtures drift (regen below) AND saved `?focus=<edge id>` deep links break.
  Accepted: no users; the screenshot skill regenerates links per run.
- Renderer edge-dedup key (react_flow.py:312) includes `input_name` + `output_path` — parallel
  same-pair edges survive with distinct ids.
- Frontend degrades gracefully on every new edge shape: unmatched `input_name` → node-level
  attachment, never dropped (`targetHandleFor` flow.ts:1509–1528 → `NODE_IN`); parallel edges get
  distinct handles/lanes in advanced and collapse node-level in beautiful (intentional,
  self-healing on focus); `expandTargets`' edge arm handles row-less endpoints; `shellBatchIds`,
  io-flow, `wrapperPorts`, and SourcePane are edge-volume-agnostic (each verified). No web test
  pins edge counts.
- No module outside `graph/` imports `EdgeKind.DATA_FLOW` or reads `GraphModel.edges`
  (consumers see edges only through the two renderers' baked facts — see drift note above).
- Refs inside literal `batch.items` VALUES are not validated as dependencies by the validator —
  their continued edge-lessness is consistent with the rule, not a violation.
- Build cost: zero (measured).

### The three golden/output-breaking landmines — guards that MUST hold

1. **The leaf-only guard on SIBLING-rooted batch `items:`** (build.py:593 — `if node_id not in
   level.incoming and node_id not in level.batch_item_incoming`) survives VERBATIM for sibling
   resolution. Without it an expanded dynamic batch (deep-research's `analyze-sources`) gains a
   direct host-level sibling edge that flips `_has_direct_data_flow` (mermaid.py:424–426) and
   un-suppresses a structural arrow → BOTH deep-research goldens break. (Input-rooted items refs
   are handled separately — see 1.2; input edges cannot flip either suppression rule: model
   `shadowed()` is same-source-filtered and `_has_direct_data_flow` needs same source+target.)
2. **The params walk skips nodes present in `level.batch_item_incoming`** (literal-batch hosts
   with expanded items), mirroring `_add_child_input_data_flow`'s arm (build.py:475–477).
   Otherwise a host-level duplicate appears beside per-item edges and
   `test_truncation_preserves_cross_boundary_dependency_via_host`
   (test_graph_react_flow_renderer.py:604) fails.
3. **Mermaid's literal-batch fork-coverage suppression must exclude input-kind sources**
   (`_render_data_flow_batch_targets`, mermaid.py:445–456 — today it counts ANY data edge into a
   batch-item descendant as coverage, with no source filter, unlike the model's same-source
   `shadowed()` clause at model.py:194–205). The re-landing of input-rooted bindings to per-item
   child inputs (1.2) would otherwise newly suppress the structural arrow INTO a ≤4-item literal
   batch whose bindings are exclusively input-rooted — deleting the predecessor's ordering arrow
   from `pflow visualize` with no visual replacement, invisible to every golden. Fix in 1.5; the
   React Flow `shadowed` fact does not flip for this shape, so without the fix the two renderers
   would silently disagree.

If a Mermaid golden diffs during Phases 1–2: either a guard above broke, or the literal-batch
re-landing interacted with fork coverage (landmine 3's family) — stop and re-read this section.
Goldens are EXPECTED byte-identical until Phase 3.

### Behavior deltas BY DESIGN (document, don't "fix"; all verified unpinned by any test)

- `test_top_level_input_connects_to_each_distinct_consumer_once` (test_graph_build.py:673) — THE
  pair-dedup pin. Rewrite: TWO edges (one per param, distinct `input_name`s `topic`/`again`).
- Input-rooted bindings on literal-batch hosts re-land from host-level to per-item child inputs
  (via `_add_literal_batch_item_input_edges` post-consolidation). Truer landing.
- Input-rooted `items:` on a LEAF batch lands on the host (was: arbitrary first-child-input
  fallback). Truer landing.
- The exotic `target_inputs.get(root, …)` fallback arm of `_add_declared_input_edges` is dropped —
  fires only for a workflow step whose non-`inputs` param refs a parent input colliding with a
  child input name (essentially unreachable: workflow steps only carry `workflow:`/`inputs:`).
- A workflow input literally named `item` or `__iteration__` no longer draws plain-param/binding
  edges (`_resolve_ref` reserves those roots; previously the inputs-only path matched them on
  non-batched nodes). Pathological naming; consistent with alias shadowing everywhere else.
- Saved `?focus=e<i>` deep links renumber (positional ids).

---

## Phase 1 — Builder consolidation (Python)

**Files:** `src/pflow/core/workflow/graph/build.py`, `graph/scope.py`,
`graph/renderers/react_flow.py` (lockstep walk), `graph/renderers/mermaid.py` (landmine-3 filter),
`tests/test_core/test_graph_build.py`, `tests/test_core/test_mermaid.py`.

### 1.1 Make the full-fidelity emitter THE emitter

In `_add_one_param_input_edges` (build.py:510–554): delete the `elif root in level.inputs:
continue` branch (:529–530) — input roots fall through to `_resolve_ref`, which resolves them
first → `(input_node, None)`. Everything else (batch-alias precedence, `source == target` skip,
`output_path` guards, full-equality dedup) stays byte-identical. Rename to `_add_ref_edges` and
update ALL call sites: `_add_child_input_data_flow` (:479), `_add_literal_batch_item_input_edges`
(:503), the leaf-batch items call (:594), `_add_loop_cap_edges` (:608), plus the new plain-param
and cache calls below. Docstring: "every resolvable `${ref}` in authored text is one DATA_FLOW
edge; full-equality dedup. (`_connect_source_expression` stays separate — its no-dedup is
load-bearing for sub-key output edges.)"

### 1.2 Re-route the three `_add_declared_input_edges` call sites

- **Plain params** (`_add_one_input_consumer_edges`, build.py:567–582): add `if node_id in
  level.batch_item_incoming: return` after the node lookup (landmine 2; comment-cite the
  literal-batch arm it mirrors). Replace the `_add_declared_input_edges(...)` call with
  `self._add_ref_edges(param_name, ref_value, shallow_targets, node_id, level,
  batch_source=None, batch_alias=alias_or_item)` where:
  - `alias_or_item` = the node's batch alias when batched else `"item"` (alias refs resolve to
    None and skip — same effect as today's `skip_root`; `batch_source=None` deliberately: the
    items-source edge is drawn elsewhere, a plain param's `${alias.x}` must not duplicate it).
  - `shallow_targets` = `level.incoming.get(node_id, {})` for SHALLOW yields, `{}` for deep ones
    (see 1.4's `shallow` flag) — a depth-2 dict ref must never target a child input port that
    happens to share its key's name (reviewer-caught misattribution; `{}` forces the host-level
    fallback).
- **Batch items** (build.py:584–594): delete the `_add_declared_input_edges(items, None, {},
  fallback_target, ...)` call. Two passes replace it:
  1. The existing leaf-only `_add_ref_edges(None, items, {}, node_id, level)` call behind the
     build.py:593 guard (landmine 1 — KEEP VERBATIM): full resolution (inputs + siblings) for
     leaf batches.
  2. NEW unconditional inputs-only pass: for each `(root, _field, _path)` in
     `refs_with_path_in(items)`, if `root in level.inputs`, emit
     `Edge(source=level.inputs[root], target=node_id, kind=DATA_FLOW)` (with the standard
     `if edge not in self.edges` dedup — on leaf batches it duplicates pass 1's input edges and
     dedup absorbs them). Rationale comment: an expanded dynamic batch over `${docs}` with OPAQUE
     bindings (`inputs: ${item}`) has no other emitter for the input→batch dependency
     (reviewer-caught deletion); sibling-rooted items stay leaf-only (landmine 1). Input edges
     cannot flip Mermaid suppression (same-source rules) — safe for expanded hosts.
- **Loop cap** (`_add_loop_cap_edges`, build.py:596–608): delete the `_add_declared_input_edges`
  call; body becomes guard + the one `_add_ref_edges` call.

### 1.3 Delete the dead machinery

Delete `_add_declared_input_edges` (build.py:610–634) and the `connected` set + threading
(`_add_input_consumer_edges` :505–508, `_add_one_input_consumer_edges` :571, `_add_loop_cap_edges`
:601). Post-condition: `grep -n connected src/pflow/core/workflow/graph/build.py` → zero hits.

### 1.4 Deepen `_params_strings` to validator parity

Rewrite `_params_strings` (build.py:796–807) as a recursive walk yielding
`(name, string_leaf, shallow)`:
- top-level string → `(param_name, value, shallow=True)` (unchanged behavior)
- depth-1 dict string value → `(dict_key, value, shallow=True)` (unchanged behavior)
- deeper dicts → recurse; a string value yields its own key, `shallow=False`
- lists (any depth) → recurse into items; items INHERIT the current name; `shallow` = whatever the
  current level was BEFORE entering the list is irrelevant — anything inside a list is
  `shallow=False` EXCEPT items of a top-level list param, which keep `(param_name, …,
  shallow=True)` (their name IS the binding-level name; the web's `bindingParam` joins them to
  the param row)
- other leaf types → skip

`shallow` means "this name is a binding-level key that may legitimately target a child-input
port"; the plain-params call site (1.2) passes child-input `target_inputs` only for shallow
yields. Matches the validator's `_check_param_value` (recurses dicts AND lists) and the
frontend's `stringLeaves` (flow.ts:469–474). Attribution rule to document: a ref is never
DROPPED; deep refs attach node-level (web: `bindingParam` returns null → `NODE_IN`) — except a
deep ref whose key collides with a real param name joins that row in the web UI (acceptable,
pre-existing one-level behavior extended; do not call it "never-misattribute").

**Lockstep (H5):** update `_string_leaves` in react_flow.py:446–451 (the `is_dynamic` walk whose
docstring names itself the `_params_strings` mirror) to recurse identically (it yields leaves
only — no names — so the recursion is simpler). Invariant unchanged ("is_dynamic=True ⟺ a
DATA_FLOW edge exists for this param's refs"); update both docstrings. Do NOT import build.py
from react_flow.py (purity guard).

### 1.5 scope.py grammar gate + Mermaid coverage source-filter

- **scope.py:** add the `(?<!\$)` lookbehind to `_BRACE_BLOCK_RE` (:12). Then add a GRAMMAR GATE
  in the shared walk: after the existing `is_literal_operand` skip (:48), skip any operand that
  does not `re.fullmatch(TemplateResolver._VAR_NAME_PATTERN, operand)`. Do NOT strip non-coalesce
  operands (stripping would defeat the gate — `" a.x "` must FAIL it, matching the runtime, which
  never resolves `${ a.x }`; coalesce operands arrive pre-stripped from
  `split_coalesce_operands`). The pattern includes bracket segments, so `${data[0].x}` passes and
  keeps its root-only edge. scope.py already imports from `runtime.template_resolver` — reuse
  `_VAR_NAME_PATTERN` from there, don't copy it.
- **mermaid.py (landmine 3):** in `_render_data_flow_batch_targets` (mermaid.py:445–456), exclude
  edges whose SOURCE node kind is `input` from fork-coverage counting (mirror the input-source
  exclusion the model's `shadowed()` achieves via same-source filtering). Comment: input fan-in
  must never suppress an execution-order arrow — the data fan comes from the Inputs wrapper, not
  the predecessor.

### 1.6 Tests (Phase 1)

In `tests/test_core/test_graph_build.py` (property-assertion style, inline IR dicts like the
file's existing fixtures):
- REWRITE `test_top_level_input_connects_to_each_distinct_consumer_once` → two edges, distinct
  `input_name`s, same (source, target). Rename to match the new truth.
- NEW: plain-param sibling ref (`prompt: "Summarize: ${gen.response}"`) → one edge
  `gen → consumer (output_field="response", input_name="prompt")`.
- NEW: interpolated multi-ref (`"${a.x} and ${b.y}"` in one param) → two edges onto that param.
- NEW: top-level list param (`["echo ${a.stdout}"]`) → edge with `input_name=<param name>`.
- NEW: depth-2 dict ref on a node WITHOUT child inputs → edge named by inner key, target = node;
  and on a workflow step WITH a child input named like the inner key → target = the HOST, not the
  child port (the `shallow` guard).
- NEW: dynamic batch over `${docs}` (declared input) with OPAQUE `inputs: ${item}` → the
  input→host edge exists (1.2 pass 2).
- NEW: batch-alias ref in a plain param of a batched node → no edge.
- NEW: literal operands (`${5}`, `${"x"}`, `${true}`) → no edge; `${a.x ?? b.y}` → two edges.
- NEW: `$${escaped}` and `${ spaced }` → no ref/edge (extend
  `test_refs_with_path_in_extracts_full_dotted_tail`, test_graph_build.py:955–965).
- NEW (in test_mermaid.py, landmine 3): structural arrow into a 2-item literal batch whose item
  bindings are exclusively input-rooted SURVIVES (is rendered, not suppressed).
- MUST STAY GREEN UNTOUCHED: `test_data_flow_edges_from_params` (test_mermaid.py:941 — its
  exactly-once assertion at :982 passes only if the params walk and `_add_child_input_data_flow`
  emit byte-identical input-edge shapes; if it fails, fix the emission shape, never the test),
  `test_truncation_preserves_cross_boundary_dependency_via_host`,
  `test_loop_max_iterations_template_creates_dependency_edges`,
  `test_batch_item_input_edges_honor_custom_alias_for_dynamic_batches`,
  `test_batch_alias_takes_precedence_over_same_named_top_level_input`,
  `test_literal_batch_item_alias_refs_do_not_resolve_as_sibling_nodes`.

**Gate:** `uv run pytest tests/test_core/test_graph_build.py tests/test_core/test_mermaid.py
tests/test_core/test_mermaid_golden.py tests/test_core/test_graph_react_flow_renderer.py
tests/test_core/test_graph_mermaid_renderer.py tests/test_core/test_graph_model_purity.py -x`
— all green, all 9 goldens byte-identical. (`test_react_flow_contract_fixtures.py` is EXPECTED
red until Phase 3 — one regen for all Python phases.)

## Phase 2 — Prompt-cache edges (Python)

**Files:** `build.py`, `tests/test_core/test_graph_build.py`.

### 2.1 `_add_cache_edges(ir, raw_nodes, level)`

New method called from `build_level` after `self._add_input_consumer_edges(nodes, result)`
(build.py:139 — `ir`, `nodes`, and the populated `result` are all in scope):

- Read `ir.get("cache")` defensively (mirror `_extract_declared_chunks`,
  prompt_cache_analysis/stages/row_builder.py:932–939: dict guard, `items` list guard, per-item
  dict + str-field guards). Build `{name: var}`. Empty/malformed → return (build_graph assumes
  pre-validated IR; the validator owns `cache.*` errors — same posture as `_node_params`).
- For each raw node whose `prompt_cache` is a list: for each str entry found in the chunk map,
  call `self._add_ref_edges("prompt_cache", "${" + var + "}", {}, node_id, level)` — the wrap is
  the established pattern (prompt_cache.py:169); resolution, `output_field`/`output_path`, the
  `source == target` skip (a producer listing its own chunk draws nothing), and dedup come free.
  `{}` for target_inputs: cache consumers are LLM nodes, never workflow hosts. Undeclared names:
  skip silently.
- Scoping is automatic: the arm reads only this level's `ir` (DD#12) and resolves against this
  level's `_LevelResult`.

### 2.2 Tests

Shapes: `test_cache_block_parser.py`'s `_wrap()` / `test_ir_schema_cache.py`'s
`_minimal_workflow()`; real subject `examples/core/prompt-caching-multi-chunk.pflow.md` (three
sibling shell producers, two LLM consumers listing all three chunks).
- Producer chunk consumed by two nodes → two edges, each
  `(output_field=<field>, input_name="prompt_cache")`.
- Input-rooted chunk (`${article}`) → edge from the input node.
- Sub-path chunk var (`${gen.result.ok}`) → edge with `output_path=("ok",)`.
- Subset consumption → edges only for listed chunks; unconsumed chunk → no edge.
- Sub-workflow with its own `## Cache` → edges resolve level-locally.
- Malformed (`prompt_cache: "x"`, `cache: []`, item missing `var`) → no crash, no edge.

**Gate:** Phase 1 suite still green; goldens still byte-identical. (No golden has a cache block.
Note: sibling-rooted cache edges are body→body and Mermaid-invisible; INPUT-rooted cache chunks DO
render at Mermaid's input site — correct and desirable, just not golden-covered. Phase 3.1's line
dedup absorbs the duplicate when the same input also feeds a param.)

## Phase 3 — Mermaid line dedup + regen + invariants

**Files:** `renderers/mermaid.py`, `renderers/react_flow.py` (docstring),
`tests/fixtures/react_flow_contracts/_generate.py`, regenerated fixtures.

### 3.1 Mermaid rendered-line dedup

`_MermaidRenderer` gains `self.emitted_data_flow: set[str]`, reset beside `self.lines` in
`render()` (mermaid.py:91). In `_render_data_flow_edges`'s append (mermaid.py:373): skip a line
string already in the set. Per-diagram scope by construction (renderer instance per render).
Rationale comment: the model keeps one edge per ref; Mermaid boxes have no param rows, so
same-pair refs are indistinguishable here — presentation dedup only. Test: a node reading one
input in two params renders exactly one `input_x --> node` line (beside
`test_data_flow_edges_from_params`).

### 3.2 Contract docstring + fixture regen

- react_flow.py:282–283 docstring: drop "multi-role-dedup" (only output-source / batch-items /
  truncation-re-anchor produce `input_name=None` now); document `prompt_cache` as a reserved
  `input_name`.
- Add `prompt-caching-multi-chunk` to the contract fixture set
  (`tests/fixtures/react_flow_contracts/_generate.py:36–40` WORKFLOWS dict) — pins cache edges in
  the Python drift guard AND enrolls them in the frontend `lossless.test.ts` real-contract sweep.
- Regen: `uv run python -m tests.fixtures.react_flow_contracts._generate`. READ the diff. Expect:
  added `data_flow` edges; renumbered positional `e{i}` ids; possible `is_terminal`/`shadowed`
  fact flips — each flip must be explainable by a new edge (a node gaining a data out-edge stops
  being terminal; a structural edge gaining same-source data coverage becomes shadowed). Zero
  node-set/group changes. Anything else → investigate before committing.
- **Gate:** `uv run pytest tests/test_core/` full green; `cd web && npx vitest run` green
  (lossless asserts survival, never counts; `sourceMap.test.ts` reads deep-research nodes only).

## Phase 4 — Frontend

**Files:** `web/src/graph/flow.ts`, `web/src/index.css`, `web/src/components/EdgePanel.tsx`,
`web/src/utils/format.ts` (label helper home), `web/CLAUDE.md`, tests beside each.

### 4.1 Advanced shadow-dim removal

- Delete the add site `if (edge.shadowed && detailed) classes.push("edge-shadowed")`
  (flow.ts:1587 + comment :1585–1586), the `SHADOWED_EDGE_CLASS` constant (:1646) and the
  applyFocus strip arm (`.filter(...)`, :1791–1799 — dead after this), the CSS rule
  (index.css:1070–1072) and its mention in the grep-helper comment (index.css:1053).
- KEEP `data: { shadowed: edge.shadowed }` (flow.ts:1625) — the contract fact's EdgeData mirror
  (avoids churn across the 10+ test fixtures that set it).
- KEEP EdgePanel's sequential-variant fact (EdgePanel.tsx:178–180; pinned by
  EdgePanel.test.tsx:276–284) — untouched.
- DELETE the test `"a selected shadowed edge sheds edge-shadowed..."` (flow.test.ts:2141–2151)
  whole — it pins the removed machinery.
- **Acceptance gate (user decision):** screenshot `generate-changelog` advanced density
  with/without the dim (screenshot-pflow-web-ui skill; toggle by stashing) and present both.
  Fallback if the user wants a middle option: dim only when NO same-pair data edge exists
  (computed over flow edges in `toFlowEdge` — Mermaid's rule-1 analogue).

### 4.2 `prompt_cache` presentation — ONE label helper, two consumers

- New helper in `web/src/utils/format.ts`: `bindingLabel(inputName)` → `"cached prefix"` for
  `"prompt_cache"`, else the name verbatim. Consumers:
  1. **`dataFlowLabel`** (flow.ts:1556–1559) — the canvas label on a revealed beautiful-density
     line; a cache edge can never land row-to-row (no such param row), so without this the raw
     sentinel `response → prompt_cache` always shows (reviewer-caught).
  2. **EdgePanel** data variant: branch on `edge.kind === "data_flow" && edge.input_name ===
     "prompt_cache"` — kind line (:77–88) → `"cached context"`; title (:100) →
     `` `${fieldPath} → cached prompt prefix` ``; purpose paragraph beside the error/end/sequential
     arms (:172–180): "Feeds this node's cached system prefix — declared in the workflow's
     `## Cache` block, consumed via `prompt_cache:`." Bundle entry labels (:207–215) route through
     `bindingLabel` (don't exclude cache edges from bundles — they're real connections).
     `bindingParam` already returns null → "receives" section correctly absent; `refSiblings`
     counts only among cache edges → fine.
- Tests: one cache-edge EdgePanel case beside the data-variant describe (EdgePanel.test.tsx
  :69–211) asserting kind line, title wording, no "receives" heading; one `dataFlowLabel` case in
  flow.test.ts.

### 4.3 Scan retention + ref-grammar mirror + doc fixes

- KEEP `scanParamReads`/`paramTextReads`/`consumedReadPaths` (verified pure set-unions, idempotent
  beside the new edges — zero changes). ADD a comment at `paramTextReads` (flow.ts:483) stating
  the post-fix reason-to-exist: build dedup collapses same-param multi-sub-key refs
  (`output_path` `compare=False`); the scan recovers those reads.
- Mirror 1.5 in flow.ts: `(?<!\$)` lookbehind on `REF_BLOCK_RE` (:455) AND the operand grammar
  gate (fullmatch of the var-name pattern, ported beside `isLiteralOperand` :462–468 — note the
  scan currently trims operands at :496, which would defeat the gate exactly as in Python; gate
  the UNtrimmed single operand). Tests: `$${x}` and `${ a.x }` yield no read.
- Fix the stale `web/CLAUDE.md` claim (lines 144–145, "hidden ones are also excluded from ELK so
  the layout stays tight") → hidden data edges DO go to ELK; only self-loops are excluded
  (layout.ts:303–312). Note: more model edges shift layouts in both densities — expected.
- No change for list-valued dynamic params (verified: teal row + badge are value-type-agnostic;
  canvas preview shows `[N items]` without ref chips — acceptable; ReadPanel shows full JSON).

### 4.4 Real-browser verification pass

Via the screenshot-pflow-web-ui skill (deep links; `inspect` for geometry, crops for paint):
- `examples/real-workflows/generate-changelog-simple/workflow.pflow.md`, `density=detailed`: the
  ~28 new lines land on their param rows (spot-check `get-latest-tag.stdout` →
  `get-commits.command`); control trunk full-strength (4.1).
- `examples/core/prompt-caching.pflow.md`, advanced: three `extract → consumer` cache lines; click
  one → EdgePanel cache wording; `extract`'s ReadPanel shows `referenced by (3)`.
- Beautiful density on the same workflow: skeleton unchanged; clicking a cache consumer reveals
  its cache line labeled `response → cached prefix`.
- lyrics-generator + plan-to-code harness: layout sane, zero console warns about dropped anchors,
  focus/click flows intact.

**Gate:** `cd web && npx vitest run && npm run build` clean; `make check && make test` clean.

## Phase 5 — Docs

- `src/pflow/core/workflow/graph/CLAUDE.md`: replace the pair-dedup/"multi-role lossiness"
  paragraph → the single-emitter rule; residual lossiness is ONLY the same-param sub-key collapse
  (`output_path` out of identity); add cache edges (per-file scoping, `input_name="prompt_cache"`,
  one-ref-per-chunk, counts-as-a-read); bracket-ref role-lossiness; the literal-batch relanding;
  the `item`-named-input delta; the `is_terminal`/`shadowed` legitimate-drift note;
  `_connect_source_expression` stays a separate emitter (why).
- `src/pflow/ui/CLAUDE.md`: H5/is_dynamic bullet (full-depth walk), the `input_name=None is
  COMMON` bullet (drop multi-role; add reserved `prompt_cache` + cache-edge semantics), advanced
  no longer dims shadowed.
- `web/CLAUDE.md`: ELK stale claim, shadow policy, scan reason-to-exist, `bindingLabel` helper +
  EdgePanel cache arm.
- `.taskmaster/tasks/task_168/visualization-requirements.md`: references-sections completeness →
  Implemented; add cache-edge + one-edge-per-ref bullets.
- `.taskmaster/tasks/task_168/implementation/sub-plans/proposal.md`: prepend "Status: IMPLEMENTED" noting the
  A2 consolidation extension + the cache arm.
- Progress log entry (`.taskmaster/tasks/task_168/implementation/progress-log.md`): deviations,
  review outcomes, learnings, per the established format.

## Verification (end-to-end)

1. `make test` + `make check` green.
2. All 9 Mermaid goldens byte-identical through Phase 2 (a diff = a landmine broke — stop);
   Phase 3 adds only the dedup unit test, no golden changes.
3. Contract fixtures regenerated once (Phase 3) with a READ diff per 3.2's expectations.
4. The Phase 4 browser pass, including the user-facing shadow-dim before/after screenshots.
5. Corpus sanity: build every `examples/**/*.pflow.md` +
   `~/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md` via
   `pflow.execution.graph_service.resolve_validate_build(path, max_depth=5)` — zero NEW build
   failures (14 examples already skip standalone — unchanged baseline); corpus data-edge total
   lands ~830 (was 656).

## Effort

Phases 1–3 (Python): ~a day. Phase 4 (frontend): ~half a day. Phase 5 (docs): ~1h.
Implement phases in order; each gate must pass before the next phase starts.
