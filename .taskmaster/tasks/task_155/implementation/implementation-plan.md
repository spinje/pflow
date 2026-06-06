# Task 155 — Workflow Graph Model for Multi-Renderer Support: Implementation Plan

> **For the implementing agent.** Self-contained. Read `.taskmaster/tasks/task_155/task-155.md` and
> `context/adr/0001/0003/0004` once for background; **this plan is the build guide** and supersedes the
> spec sketch where they differ (§6). Hardened by two rounds of multi-agent plan review (review-plan,
> review-simplicity, review-feature-interactions, review-impact-completeness, review-silent-failures); all
> confirmed findings are integrated. Re-anchor every line number before editing — they drift.

---

## 1. Context — why this change

`pflow visualize` renders a workflow IR to a Mermaid string via `src/pflow/core/workflow/mermaid/`
(6 files / ~1673 lines), which is **text-in / text-out**: every function appends Mermaid syntax to a shared
`ctx.lines`. There is no data layer between IR and text, so the committed endgame — a **React Flow** web UI
to *see* and click-to-read the Task 163 agentic harness — would have to re-walk the IR and re-derive every
structural decision.

This task extracts a **renderer-agnostic Graph model**: one IR walk → a pure-data `GraphModel`; Mermaid
becomes the first renderer; React Flow / JSON slot in later with no re-walk. The model is the static "see"
substrate, carrying **zero runtime data** (a future event log animates it; they converge only at the UI).

```
   IR  →  build_graph()  →  GraphModel  ─┬─→  render_mermaid()    →  str
                                         ├─→  render_react_flow() →  {nodes, edges, groups}  (future)
                                         └─→  dataclasses.asdict  →  JSON API payload         (future)
```

**Guiding priority:** optimize the *final code's* simplicity. Mermaid parity is a **verification tripwire**,
not a contract — where a current Mermaid behavior is a limitation, the model encodes the structural truth
and Mermaid renders best-effort. Shape the model for the endgame renderer + clean, AI-navigable code.

---

## 2. Verified findings (6 searcher passes + 2 review rounds)

| # | Finding | Consequence |
|---|---------|-------------|
| F1 | IR edges `{from,to,action?}`; `action` ∈ {absent=sequential, `"default"`, `"error"`, target-id=branch}; `- next: end` emits **no edge** AND is **discarded entirely** (routing dict is parser-local, never on the IR); parser emits a redundant default+named edge for the first multi-target (`markdown_parser.py:1257-1309, 1604-1609`). | One `Edge` + `kind` enum; collapse the parser duplicate at build. `→ end` is NOT recoverable from the IR — capture it via a new parser field (D2 / §3a). |
| F2 | `_deduplicate_edges`/`_detect_decision_nodes` (distinct named-action **set** ≥2)/`_find_terminal_nodes` (no non-error out) are pure over the edge list (`_edges.py:17-73`). | Derived helpers on `GraphModel`; `is_decision` = distinct BRANCH labels over post-collapse edges (provably equal to today). |
| F3 | Routing maps (`outgoing_routes`, `has_expanded_outputs`, `fork_join_map`, `incoming_map`, `data_flow_targets`) are mermaid-ID-keyed **build scratch** (`_context.py:97-101`, `_edges.py:104-140`). | None in the model. Local build state only. |
| F4 | Cycle detection is a recursion-stack (`seen.add` `_render.py:348/397`, `discard` `_render.py:362/421`, check `:500`); diamond expands twice, cycle collapses. **Gap:** keys on `str(path)`, so `path is None` children skip detection. | Port; key on `synthesize_inline_workflow_id(ir)` (`workflow_id.py:49-51`, `ir-hash:<md5>`) when `path is None`. |
| F5 | `resolve_child: Callable[[dict, Optional[Path]], Optional[SubWorkflowResult]]` (positional); `SubWorkflowResult(ir, path, warnings)` frozen; `.ir` file-resolved; `.path` optional (a `Path`); plain-closure test adapters (**no mocks**). | Keep a bare callable; don't re-resolve files; tests assert on the `GraphModel`. |
| F6 | 4 "can't expand" reasons collapse to one opaque node, error swallowed (`_render.py:170,490-503`). | Node carries an `unexpanded` reason discriminator. |
| F7 | Data-flow edges from `${ref}` in `params["inputs"]` + output `source:`; producing pair is `(node_id, output_name)`, flattened today (`_edges.py:183-229`, `_io.py:184-239`, `_scope.py:54-90`). | `Edge` carries `output_field`/`input_name`. |
| F8 | `_scope.py` regex captures only the first dotted segment — **correct granularity** for edge routing. | Do not "fix"; reuse `Scope.refs_in`/`source_refs_in`; only resolution changes (flat str → structural). |
| F9 | Vocab: 7 colour classes + computed `decision`/`mcp`; 8 shape geometries; loop `while`/`until`/`carry`(dict)/`max_iterations`(int OR `${}`); batch top-level `items`(list/str)+`parallel`+`as` (`_context.py:17-46,147-323`, `ir_schema.py:98-196`). | `kind = raw IR type str`; decision derived; shape derived at render; `LoopSpec`/`BatchSpec` store raw. |
| F10 | IO groupings: 4 dashed wrappers → `input_wrapper`/`output_wrapper`; content subgraphs (depth-opacity) → `workflow`/`batch`; 2 bare sub-workflow IO funcs emit members into the enclosing container (`_io.py`, `_render.py:309/359/415`). | One `Container`, `kind ∈ {workflow,batch,input_wrapper,output_wrapper}` (`cycle` reserved). |
| F11 | Compat surface: `visualize.py` imports only `generate_mermaid`; `test_mermaid.py` imports all 7; `test_mermaid_golden.py` only `generate_mermaid`. The 6 helpers have no non-test consumer; `generate_mermaid` re-exported nowhere. | Shim re-exports **only `generate_mermaid`**; the 6 helpers are test-only → tests adapt. |
| F12 | Parity blast radius: 8 byte-exact goldens; ~184 asserts in `test_mermaid.py`; 3 rendered doc blocks (named in §9); loose CLI tests. | Regenerate shifted goldens with recorded rationale; migrate structural asserts to model-level tests. |
| F13 | Today's "nearest-consumer for top-level inputs" is actually **pair-dedup** — `_connect_input_from_params` (`_io.py:99-109`) draws an edge to **each distinct consumer**, deduped only on the `(source,target)` pair; `_generate_data_flow_edges` skips depth-0 input refs (`_edges.py:222`) to avoid double-emission. | Model carries input→all-distinct-consumers; render dedups per `(source,target)` pair. The "nearest-only" spec wording is a **misnomer** — match the code. |
| F14 | Runtime termination on `next: end`: edge-absence at the graph level; a code node returning `"end"` is handled by `is_clean_termination` (`engine.py:377-393`). A top-level node field is **inert** to engine + validator (Step-8 reads `params`; data_flow reads `edges`; engine routes on `edges`). | The `routes_to_end` field (§3a) is parser-metadata only — zero runtime/validation effect. |

---

## 3. The GraphModel (`graph/model.py`) — pure data, no Mermaid syntax

`dataclasses.asdict`-able, `json.dumps`-able. **No field value contains Mermaid syntax.** Node-to-node
cross-refs use structural `NodeId` (ADR-0003); container refs use synthetic string ids. **All path-like
fields are `str`, never `Path`** (`json.dumps` raises on `Path`).

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional

# ── Structural identity (ADR-0003) ──────────────────────────────────────────
@dataclass(frozen=True)
class AncestorStep:
    node_id: str                       # the sub-workflow / batch host node id at this level
    batch_index: Optional[int] = None  # which LITERAL batch item we entered; None = plain sub-wf OR dynamic batch

@dataclass(frozen=True)
class NodeId:
    """Runtime-aligned identity (ADR-0003). No leaf batch_index — leaf batch items are BatchSpec.items data (§4f)."""
    node_id: str
    ancestor_path: tuple[AncestorStep, ...] = ()

# ── Per-node facets ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LoopSpec:                         # ADR-0001: a node property, never an edge
    polarity: Literal["while", "until"] # build constructs a LoopSpec ONLY when exactly one key is present
    condition: str                      # RAW ${...} ref
    cap: int | str | None               # max_iterations: literal int OR ${...} OR absent
    carry: dict[str, str]               # {body_input_name: ${prior_output_ref}}

@dataclass(frozen=True)
class BatchSpec:
    parallel: bool
    dynamic: bool                       # items is ${...} (True) vs a literal list (False)
    as_name: str = "item"               # IR `as`, default "item"
    source_ref: Optional[str] = None    # dynamic only: raw ${...}
    count: Optional[int] = None         # literal only: len(items); None when dynamic
    items: Optional[list[Any]] = None   # literal only: RAW items, JSON-able (renderer labels via _get_item_label)

@dataclass(frozen=True)
class IOPort:                           # only on kind in {input, output}
    data_type: Optional[str]
    required: bool = False

@dataclass(frozen=True)
class SourceRef:                        # click-to-read back-ref (pointer); file is str() of the resolver Path
    file: Optional[str]
    line: Optional[int]

UnexpandedReason = Literal["depth_limit", "unresolved", "dynamic_path", "cycle"]
NodeKind = str   # raw IR type ("llm"/"shell"/"mcp-...") OR synthetic "input"/"output"/"end"

# ── Nodes ───────────────────────────────────────────────────────────────────
@dataclass
class Node:
    id: NodeId
    kind: NodeKind
    purpose: str = ""                   # RAW IR purpose; renderer truncates via _first_sentence
    parent: Optional[str] = None        # containing Container id (string)
    loop: Optional[LoopSpec] = None     # single-node OR sub-workflow host (§4g)
    batch: Optional[BatchSpec] = None   # the batch host node's config
    io: Optional[IOPort] = None         # kind in {input, output}
    source: Optional[SourceRef] = None  # None for synthetic IO nodes
    unexpanded: Optional[UnexpandedReason] = None
    annotations: dict[str, Any] = field(default_factory=dict)  # open seam (ADR-0004); JSON-able values ONLY
    # NOTE: `- next: end` is NOT a node flag — it is an EdgeKind.END edge to a synthetic END node (§4e).

# ── Edges (ONE type, kind-discriminated) ────────────────────────────────────
class EdgeKind(str, Enum):
    SEQUENTIAL = "sequential"  # action absent or "default"
    BRANCH     = "branch"      # named action (action == target id)
    ERROR      = "error"       # - on-error:
    DATA_FLOW  = "data_flow"   # inferred from ${ref}
    END        = "end"         # - next: end → edge to the synthetic per-level END node (NOT branch; excluded from is_decision)

@dataclass(frozen=True)
class Edge:
    source: NodeId
    target: NodeId
    kind: EdgeKind
    label: Optional[str] = None         # BRANCH: the action label
    output_field: Optional[str] = None  # DATA_FLOW: producing output name (None = whole/single output)
    input_name: Optional[str] = None    # DATA_FLOW: consuming input name on target

# ── Containers (ONE record for every grouping — ADR-0004) ────────────────────
ContainerKind = Literal["workflow", "batch", "input_wrapper", "output_wrapper"]  # "cycle" reserved

@dataclass
class Container:
    id: str
    kind: ContainerKind
    nesting_depth: int                  # 0 = top level; drives the renderer's opacity ramp
    host: Optional[NodeId] = None       # the node this expands (workflow/batch); None for IO wrappers & per-item batch sub-containers
    parent: Optional[str] = None        # parent Container id
    members: list[NodeId] = field(default_factory=list)  # DIRECT member nodes (child containers via .parent)
    annotations: dict[str, Any] = field(default_factory=dict)

@dataclass
class GraphModel:
    nodes: list[Node]
    edges: list[Edge]
    containers: list[Container]
    def is_decision(self, n: NodeId) -> bool: ...   # ≥2 distinct BRANCH labels out of n (post-collapse)
    def is_terminal(self, n: NodeId) -> bool: ...   # no non-ERROR, non-END outgoing edge
    def shadowed(self, e: Edge) -> bool: ...        # see §4e for the exact 3-clause predicate
    def node(self, n: NodeId) -> Optional[Node]: ... # O(1) lookup (cache dict[NodeId, Node])
```

**Derived, not stored** (F2): `is_decision`, `is_terminal`, `shadowed`, shape. **Bidirectional**
`Node.parent` ↔ `Container.members` (React Flow wants `node.parentNode`; Mermaid walks members) — keep both,
assert consistency at build, document in `graph/CLAUDE.md`. Build also asserts **edge-endpoint referential
integrity** — every `Edge.source`/`Edge.target` (and `Container.host`/`members`) resolves to a Node in
`graph.nodes` (catches a dangling END or data-flow target).

**Container labels are render-derived** (no `label` field): `workflow`/`batch` label = `host.node_id`;
a **per-item batch sub-container** (kind `workflow`, `host=None`, parent = the batch Container) is labelled
`_get_item_label(parentBatch.host.batch.items[i], i)` where **`i` = the `batch_index` of the *last*
`AncestorStep` of any direct member** (literal batches only — see §4f for the literal-vs-dynamic split; a
per-item container always has ≥1 member because it is an expanded sub-workflow).

---

## 3a. Parser change — persist `routes_to_end` (D2, the one IR-contract change)

`- next: end` and code-node `next = "end"` are discarded at parse time (F1), so `build_graph` cannot see
them. To let the endgame UI show abort branches, persist the fact as a **node field** (verified small +
low-risk + inert to engine/validator, F14). **Reject** a sentinel `to:"end"` edge (breaks schema integrity,
compiler wiring, ~dozens of edge-shape tests).

- **Write sites** (both): bullet path — set `node["_routes_to_end"] = True` where `_build_edges` drops the
  `end`-only branch (`markdown_parser.py:1285-1286`, or in `_build_node_dict:1604-1609` by checking
  `"end" in _parse_next_targets(routing["next"])`); code path — thread a `has_end` flag out of
  `_extract_next_targets_from_code` (`:1247-1254`, which currently drops `"end"`) into the node dict.
- **Schema**: add the optional `_routes_to_end` property to the node object in `ir_schema.py` (it is
  `additionalProperties:False` at `:296`; mirror the `_source_line` whitelist convention `:285-293`). ~6 lines.
  **Mandatory** — without it, committed examples using `next: end` (`examples/core/conditional-branching.pflow.md`,
  `error-handling.pflow.md`, …) fail schema validation.
- **Inert downstream** (F14): Step-8 reads `params` (not top-level fields); data_flow + engine route on
  `edges`. No validator/engine/compiler change. `is_terminal`/`is_decision` are **unaffected** (it's a flag,
  not an edge) — `handle-error` stays terminal, `check-validate` stays a non-decision.
- **The IR field is a `bool` named `_routes_to_end`** — the `_`-prefix matches the parser-injected
  `_source_*` convention (keeps it out of agent-facing surfaces). **Use this exact name at BOTH parser
  write-sites AND the schema whitelist** — a name mismatch would silently fail validation of committed
  `next: end` examples. `build_graph` **consumes** it to create the model's synthetic END node +
  `EdgeKind.END` edge (§4e) — the field is *not* carried onto the model Node. (Prose elsewhere in this plan
  says "routes_to_end" for the concept; `_routes_to_end` is the canonical code name.) A `bool` suffices
  today; widen to a list of end-routing actions only if branch-granular abort viz is later wanted.

---

## 4. `build_graph` (`graph/build.py`) — the one IR walk

`def build_graph(ir, *, resolve_child=None, base_path=None, max_depth=1) -> GraphModel:` — no
`direction`/`descriptions` (render concerns). Pure function of `(ir, resolve_child)`; zero render syntax.

### 4a. Two-sub-pass per level
**Pass A** walk every node (create `Node` + grouping `Container`s; recurse), building a **local**
`produces: dict[NodeId, dict[str, NodeId]]`. **Pass B** resolve all edges against the complete node set.
Recursion = post-order fold: a parent reads each child's `produces`/declared outputs — this must thread a
**grandchild's** declared output up to a 1-deep sibling consumer (cf. `_io.py:386-394` `_child_out` cascade;
the §8 test asserts the *endpoint* `score.score → compile`, `output_field` set, not just "an edge exists").

### 4b. Sub-workflow expansion + cycle detection (F4)
Recursion-stack: add on enter, **discard on exit**, check before recursing. Key on `str(path)`, else on
`synthesize_inline_workflow_id(ir)` when `path is None`. (Note its `json.dumps(default=str)` keying admits a
vanishingly-rare hash collision → a false cycle; acceptable, comment it.) A **hand-wired backward-edge cycle
within one level** (e.g. `validate-fix`'s `run-validate → check-validate → fix-tests → run-validate`) is NOT
a sub-workflow re-entry — it stays faithful edges (ADR-0004) and never touches the recursion stack. `.ir` is
file-resolved (don't re-resolve). `max_depth`: expand while `current_depth < max_depth`.

### 4c. The `unexpanded` discriminator (F6) + empty-IR guard
Explicit reason at each site: `depth_limit`, `cycle`, `dynamic_path` (`workflow` param is `${...}`),
`unresolved` (resolver `None`/raised). **Also** mark `unexpanded="unresolved"` when the resolved child IR is
empty/degenerate (no `nodes`) — otherwise an empty Container looks like a successful expansion. Store any
`SubWorkflowResult.warnings` as **strings** in `annotations` (Diagnostic objects break `json.dumps`).

### 4d. Node identity (worked examples)
ancestor_path is a chain of `AncestorStep`. Container `id` = deterministic string from the path (e.g.
`"/".join(f"{s.node_id}#{s.batch_index}" if s.batch_index is not None else s.node_id for s in path)` + host
id) — unique/deterministic, **not** the Mermaid flat id.

| Node | `NodeId` |
|------|----------|
| top-level `prepare` | `NodeId("prepare")` |
| `extract` in `analyze-sources` | `NodeId("extract", (AncestorStep("analyze-sources"),))` |
| `evaluate` in `score` in `analyze-sources` (3-deep) | `NodeId("evaluate", (AncestorStep("analyze-sources"), AncestorStep("score")))` |
| `critique` in batch `reviews` item 0 / item 1 | `NodeId("critique", (AncestorStep("reviews", 0),))` / `(... ,1)` |
| top-level input `sources` | `NodeId("sources")`, `kind="input"` |
| `analyze-sources` output `analysis` (IR output id is `analysis`; the `out_` prefix is render-only) | `NodeId("analysis", (AncestorStep("analyze-sources"),))`, `kind="output"` |
| same child via `seg-gate` vs `final-gate` | distinct ancestor paths; both expand (diamond, not cycle) |

### 4e. Edge construction (F1, F7, F8, F13)
- **Structural** (`ir["edges"]`): run the `_deduplicate_edges` collapse **first** (drops the parser's
  duplicate default+named), then map `action` → `EdgeKind` (absent/`"default"`→`SEQUENTIAL`,
  `"error"`→`ERROR`, target-id→`BRANCH` with `label=action`). **For `→ end`** (from the Phase 0
  `routes_to_end` IR flag, §3a): create the per-level synthetic END node `NodeId("__end__", <level
  ancestry>)` (`kind="end"`) **once** (multiple terminating nodes share it), and emit `Edge(source=node,
  target=__end__, kind=END)`. The distinct `END` kind means `is_decision` (BRANCH-only) is unaffected and
  `is_terminal` (excludes END) is preserved — `check-validate` stays a non-decision, `handle-error` stays
  terminal-equivalent.
- **Data-flow**: reuse `Scope.refs_in`/`source_refs_in` (F8) over `params["inputs"]` values **and** output
  `source:` — **NOT** over `loop:` blocks (so `${review-round.result.continue}`/`${max_review_rounds}` stay
  loop metadata) and not for magic refs (`${__iteration__}`, `${item}` outside batch → resolve to nothing,
  dropped). Resolve `root`→sibling `Node`/declared input, `field`→producing `output_name` via `produces`.
  `${a ?? b}` → N edges sharing a target (the output-source path `_connect_sources_to_output` is one of the
  4 migration paths — don't miss its coalesce; literal operands like `"none"` are filtered by
  `source_refs_in`).
- **Top-level inputs (F13, was "nearest-consumer")**: emit an edge from the input Node to **each distinct
  consumer**, deduped on the `(source, target)` pair (NOT "one consumer per input"). The old depth-0
  double-emission de-dup dissolves under the single build path; preserve the `(source,target)` dedup key.
  Port the consumer-input-wrapper routing (`in_dict.get(child_param, ...)`, `_io.py:104`).
- **Suppression is NOT applied here** — `GraphModel.shadowed` is a derived view; build keeps both edges.

  **`shadowed(e)` exact predicate** (mirror `_render_edge:155-162`, all 3 clauses): a structural edge
  `A→B` is shadowed iff **(1)** A does NOT have expanded outputs (i.e. A has no output Nodes / is not an
  expanded grouping with outputs — else output→input name-matching handles routing, don't suppress),
  **AND** **(2)** a DATA_FLOW edge targets B directly, **OR (3)** B is a batch grouping and **ALL** its
  expanded item members are themselves data-flow targets. Omitting clause 1 silently drops real edges;
  omitting "ALL" in clause 3 silently drops edges to uncovered items.

### 4f. Batch representation (D1 + simplicity)
- **Literal batch, sub-workflow items**: carry **ALL** items. Each item i → a workflow Container
  (`host=None`, parent = the batch Container) whose member nodes carry `AncestorStep(host, i)`. Truncation
  (first-2 + ellipsis) is a **Mermaid render decision** — **no `__dots` Node in the model**.
- **Literal batch, leaf (non-workflow) items**: NOT model nodes — they are `host.batch.items` data; the
  renderer draws item boxes (and ellipsis) from `BatchSpec.items`. Edges connect to the host.
- **Dynamic batch over a sub-workflow** (`items:${x}`, workflow type): **one** expansion in the batch
  Container (members carry `AncestorStep(host, None)`), NOT a per-item fan. `BatchSpec.items=None`,
  `dynamic=True`. The per-item label rule (§3) does **not** apply (no `items[i]`).
- The batch host is a `Node` carrying `BatchSpec`, plus a `Container(kind="batch", host=that node)`.

### 4g. Scope (`graph/scope.py`) + phase note
Move `_scope.py` here. **Keep** `refs_in`/`source_refs_in` verbatim (static, pure). `Scope.resolve`,
`Scope.for_level`, and the mermaid-ID-coupled instance fields (`ctx`/`input_ids`/`batch_source`) are
**reimplemented structurally in `build.py`** (return `NodeId` + optional `output_field`; `ctx.prefix` →
structured `ancestor_path`), **not moved**. This reimplementation is folded into the build phase (§7) since
build is the only consumer.

---

## 5. Mermaid renderer (`graph/renderers/mermaid.py`)

`def render_mermaid(graph, *, direction="LR", descriptions=False) -> str:` — reads **only the `GraphModel`**
(grep-checkable, §9.2).
- **Flat-id derivation** from `NodeId` in one helper (ADR-0003): walk `ancestor_path` (`node_id` + `__` +
  the **batch-item label** for an indexed `AncestorStep` — re-derive via `_get_item_label(host.batch.items[i], i)`,
  looking up the host Node in the model) + leaf `node_id`; IO → `in_/out_`. *Worked example:* `critique` in
  `reviews` item 0 → `reviews__accuracy__critique` (label "accuracy" from `items[0]`). The ellipsis `__dots`
  is a render artifact.
- **Truncated-tail collapse** (the W6 case): for a literal batch's hidden items (index ≥ 2), synthesize the
  render-only `__dots` node, **drop their per-item DATA_FLOW edges**, and **redirect their structural edge
  endpoints onto `__dots`** (so today's `combine → reviews__dots → final-report` survives). Reconstruct the
  per-output structural fan from the target Container's output Nodes (the routing maps are gone, F3).
- **Shape** from `kind` + `graph.is_decision()` + `node.batch` (precedence `decision > mcp-prefix >
  _SHAPE_MAP[kind] > rect`, + `procs` for batch); **colour** from `kind` (reuse `_CLASSDEF_STYLES`, default
  `code`). Tables move here from `_context.py`.
- **Labels composed here**; the label builders `_loop_label`/`_dynamic_batch_label`/`_get_item_label`/
  `_format_label` are **rewritten to read `LoopSpec`/`BatchSpec`/`Node`** (NOT moved verbatim).
- **Loop**: `LoopSpec` on a single-node → badge + dotted self-edge; on a sub-workflow host → badge on the
  Container title (read via `Container.host`).
- **Containers**: `workflow`/`batch` depth-opacity ramp; `input_wrapper`/`output_wrapper` dashed.
- **End-sink (parity)**: synthesize `pflow_end` exactly as today — gated by `is_decision present && no
  declared outputs && not suppress_io`, connecting **`is_terminal` nodes only**. Mermaid **ignores the
  model's `EdgeKind.END` edges** (it derives its sink from `is_terminal`, as today) — drawing an END edge
  from a *non-terminal* decision (e.g. `check-groups`) would need a sink even when outputs exist, a behavior
  change Mermaid can't place cleanly. So Mermaid output is unchanged by D2; the END node + END edges are
  consumed by **React Flow** for abort-path viz. The renderer **MUST call `graph.is_terminal()`** (the
  END-excluding model helper) — it must NOT re-derive terminality by a raw edge walk / verbatim
  `_find_terminal_nodes` port (which excludes only `error`, not END), or `handle-error` (now carrying an END
  edge) reads as non-terminal and its `--> pflow_end` silently vanishes (a parity regression).
- **Top-level input edges**: dedup per `(source,target)` pair (F13).
- **Suppression**: drop a structural edge where `graph.shadowed(edge)`.

---

## 6. Deliberate deviations from the spec sketch

| Spec sketch | This plan | Why |
|---|---|---|
| `descriptions` on `build_graph` | on `render_mermaid` | render decision; model always carries raw `purpose`. |
| Node carries `shape` | derived at render | pure fn of kind/role/batch. |
| Edge `suppression` flag | `GraphModel.shadowed()` derived (3-clause, §4e) | render decision; opaque-sub-wf renderer wants the edge kept. |
| "one routing field" | routing maps carried nowhere | build scratch (F3). |
| decision/`end`/terminal as kinds | `decision`/`terminal` derived; `→ end` modeled as an **edge (`EdgeKind.END`) to a synthetic per-level END node**, sourced via the Phase 0 `routes_to_end` parser flag; Mermaid keeps its render-only `is_terminal` sink and ignores END edges | F1 (not in IR → parser flag) + a *distinct* edge kind avoids the BRANCH decision-detection break + uniform "connections are edges" for the React Flow endgame (build synthesizes the END sink once; renderers just consume edges). |
| `kind` enum | raw IR type string (+ `input`/`output`) | registry-extensible types. |
| one identity field | `NodeId` + `AncestorStep(batch_index)`; **no leaf `NodeId.batch_index`** | ADR-0003 + uniqueness; leaf batch items are `BatchSpec.items` data. |
| back-ref "carries content" | `(file, line)` pointer, `file` is `str()` | lighter, JSON-safe. |
| Container loop/batch + `Edge.via_coalesce` | loop/batch read via `Container.host`; `via_coalesce` dropped | no duplication; no consumer for coalesce (and uncomputable from flat `refs_in`). |
| "nearest-consumer-only" | **pair-dedup, all distinct consumers** (F13) | the spec wording is a misnomer; match the code. |

**Not done (correctly):** "fixing" the lossy `_scope` field (F8); custom-batch-var (`as:`) data-flow edges
(Scope hardcodes `"item"` — parity limitation, but `as_name` carried losslessly); analysis/SCC layer
(ADR-0004); a real React Flow renderer (throwaway sketch only); branch-granular abort viz (a `bool` flag
now; widen later if needed).

---

## 6a. Forward-compat: the runtime-overlay join (Substrate 2 / JSONL trace)

Verified: the GraphModel's structural identity already **is** the runtime's, so a future live overlay joins
losslessly. **No model change required; the pins are documentation.**

- **Lossless today (by tree walk):** top-level + sub-workflow children = **bare `node_id`** under
  `sub_workflow_events`; batch items = **integer `index`** (never `node_id`) = the `batch_index` slot;
  ancestry is *positional* (no `parent_id`/`ancestor_path` field on events yet).
- **The JSONL rework strengthens it.** Task 133 (the trace/cache storage ADR — *designed, not built*, gated
  to land **after** Task 155) converts positional nesting → explicit `parent_id` chaining, batch→child
  spans, loop visits→spans with `seq`. Same identity, made explicit. 155 establishes the static half of the
  join contract Task 133 D1 (`event_id`/`parent_id`/`run_id`/`seq`) will cite.
- **N:1 for loops.** `__iteration__` is a runtime *template* variable, not in trace events; loop visits
  append with the same `node_id`. The static model collapses a looped node to one identity — *consistent*
  with today's trace. The overlay expects N spans : 1 node (Task 133 `seq` is the future discriminator).
- **No-runtime-event nodes**: IO-wrapper nodes (`kind` input/output) and the synthetic END node (`kind`
  end) have no execution events — the overlay animates them via edges, not node events.
- **Dynamic batch**: model = 1 representative (`AncestorStep(host, None)`) + `dynamic=True`; the overlay fans
  it onto the N runtime items by index.

**Pins for 155:** (1) identity mirrors the runtime exactly (frozen by §8 build tests). (2) `graph/CLAUDE.md`
+ `NodeId` docstring document the correspondence, the N:1 loop rule, and the **3 trace keying facts** so a
future trace change is caught: sub-wf children = bare `node_id` under `sub_workflow_events`
(`instrumentation.py:582-596`); batch items = integer `index`, never `node_id` (`batch_executor.py:877-882`);
batch-item sub-wf children nest under `events`, not `sub_workflow_events` (`batch_executor.py:913-916`).
Cite ADR-0003 + Task 133 D1. (3) **No coupling** — 155 does NOT import trace code; the live join test belongs
to the future overlay task against the post-133 JSONL trace.

---

## 7. Packaging, phasing & commits

```
src/pflow/core/workflow/graph/
├── __init__.py            # public: build_graph, render_mermaid, GraphModel + dataclasses/enums
├── model.py               # §3
├── build.py               # §4 (incl. the Scope.resolve→structural reimplementation)
├── scope.py               # refs_in/source_refs_in moved verbatim
└── renderers/{__init__.py, mermaid.py}   # §5
```

**Phases** (each ends green: `make check` + relevant tests):
0. **Parser/schema — `routes_to_end`** (§3a). `markdown_parser.py` (both write sites) + `ir_schema.py`
   (whitelist) + ~3-4 parser/schema tests + confirm committed `next: end` examples still validate. Small,
   self-contained, LOW risk; lands first (build depends on the field). Separate commit.
1. **`model.py`** — dataclasses + derived helpers + helper unit tests; assert the `Node.parent`↔
   `Container.members` consistency.
2. **`scope.py`** — move `refs_in`/`source_refs_in` verbatim. (`resolve`/`for_level` are NOT here — §4g.)
3. **`build.py`** — `build_graph`: two-sub-pass; expansion+cycle (incl. `path is None` + empty-IR guard);
   the 4-path structural+data-flow resolution (the `Scope.resolve`/`for_level` structural reimplementation);
   batch carry-all/leaf-as-data/dynamic-one-expansion; `unexpanded`; `routes_to_end` propagation;
   `shadowed`/`is_decision`/`is_terminal`. **Main structural test surface** (`test_graph_build.py`, §8).
4. **`renderers/mermaid.py`** — `render_mermaid`; move pure utils; rewrite label builders; flat-id +
   truncated-tail collapse + batch-fan + end-sink(parity) + pair-dedup + suppression at render.
5. **Compat shim** — `mermaid/__init__.py` re-exports **only `generate_mermaid`**. `visualize.py` +
   `test_mermaid_golden.py` unchanged. `test_mermaid.py` helper imports adapt (structural-helper tests →
   `test_graph_build.py`; render-util tests → new homes).
6. **Remove old internals** — delete `_context/_edges/_io/_render/_scope.py`; keep the shim; update
   `mermaid/CLAUDE.md` → point at `graph/`; add `graph/CLAUDE.md` (file map; build-scratch-vs-model rule;
   derived-helpers rule; NodeId-vs-string-id + parent/members invariants; the §6a join contract).
7. **Throwaway react-flow completeness sketch** — `render_react_flow(graph)` over the 6 patterns + the 163
   harness; confirm no info loss (incl. `routes_to_end` abort indicators); **discard**. If it can't draw a
   fact, fix the model/build (phase 1/3), not the renderer.

**Agent handoff (§12a):** N=3 — agent 1: phases 0–3 (parser + structural layer); agent 2: phase 4
(renderer); agent 3: phases 5–7 (cutover + completeness). Firebreak at 3→4 (the two-layer split, locked by
the frozen `GraphModel` + the build suite).

---

## 8. Testing strategy migration

- **New `tests/test_core/test_graph_build.py`** — structural assertions on `build_graph`'s `GraphModel`
  (plain-closure `resolve_child`, no mocks). On the named acceptance subjects:
  - nesting (2- and 3-deep `analyze-sources → score → evaluate`); cross-boundary data-flow asserting the
    **endpoint** (`score.score → compile`: `output_field` set, target = the output Node) — not just "exists".
  - batch: literal sub-wf (`reviews`, **all 5** items present, **no `__dots` node**); literal leaf
    (`[correctness,sources,logic]` → `BatchSpec.items`, no item Nodes); dynamic-over-workflow
    (`analyze-sources`, one expansion, `items=None`).
  - decision/terminal + END (exercise BOTH parser write-sites): `check-groups` (`- next: …, end`) IS a
    decision (3 distinct BRANCH labels), `is_terminal=False`, **and has exactly ONE `EdgeKind.END` edge** to
    the level's END node (it carries `end` in *both* bullet and code — dedup per node, not per source).
    `check-validate` is NOT a decision (1 branch) and has an END edge sourced from the **code-node
    `next = "end"` path** — use the `validate-fix` fixture; this is the only test that exercises the
    code-path `has_end` plumbing, so it must source from a code-routing fixture, not a bullet one.
    `handle-error` (`- next: end`, **bullet path**) stays `is_terminal=True` and has an END edge. A plain
    mid-workflow node has no END edge. Assert: the per-level END node is created **once** (terminating nodes
    share it); **`graph.node(end_edge.target)` resolves to the synthetic END Node** (kind `"end"`, not None —
    guards the dangling-target case); `is_decision` (BRANCH-only) and `is_terminal` (excludes END) are
    unaffected by END edges; and a node with **both an ERROR edge and an END edge** is still `is_terminal=True`.
  - loop: single-node (`review-round`, `LoopSpec` on Node); **sub-workflow loop via the
    `examples/core/stateful-loop-tournament.pflow.md` `run-rounds` fixture** (badge via `Container.host`) —
    NOT in the two acceptance subjects, so include this fixture; confirm `loop:`/`${__iteration__}` refs
    produce NO data-flow edges and `${max_review_rounds}` is not double-drawn.
  - coalesce on output source: `summary` edge **count == 2**, `pr_url` **count == 1** (literal filtered).
  - the 4 `unexpanded` reasons; the empty-IR-child guard; `path is None` cycle (inline child) caught.
  - same child twice (`validate-fix` via `seg-gate`/`final-gate`) → distinct paths, both expand; intra-level
    back-edge cycle stays a faithful edge (not a recursion-stack hit).
  - top-level input consumed by **≥2 distinct nodes** → both edges present (F13 pair-dedup), no duplicate.
  - `shadowed()` 3-clause: an edge whose source has expanded outputs is NOT shadowed; a fork/join target is
    shadowed only when ALL items are covered.
  - `dataclasses.asdict` + `json.dumps` round-trips — include an **adversarial** case (a batch item with a
    nested/non-string value; a `SourceRef` from a `Path`) to prove serialization, not just the clean subjects.
- **`test_mermaid.py`** — stays the renderer's test (via `generate_mermaid`); migrate structural asserts to
  `test_graph_build.py`; rewrite the 3 edge-helper tests as `GraphModel`-method tests; adapt render asserts.
- **`test_mermaid_golden.py`** — unchanged mechanism; **add a golden** exercising a batch-of-expanded-items-
  with-**multiple-outputs** → downstream node (to pin the W6 over-fan cardinality, which no current golden
  covers); regenerate shifted goldens with recorded rationale.
- **`test_visualize.py`** — should pass unchanged.

---

## 9. Verification (spec's 4 buckets)

1. **Functional parity (tripwire).** Run the mermaid/visualize suite. Investigate every golden diff:
   accidental → fix; justified (two-sub-pass reorder, F1 collapse, F13 pair-dedup move, `path is None` fix,
   empty-IR guard) → regenerate + record why. **D2 adds no Mermaid edges** (§5). **Pin the D2 parity
   tripwire:** after the model gains the `handle-error → __end__` END edge, the regenerated
   `conditional-branching.mmd` MUST still contain `handle-error --> pflow_end` — the single most important D2
   regression guard (it catches a renderer that re-walks edges instead of calling `graph.is_terminal()`).
   Manually re-render the 163 harness + deep-research in `mermaid.live`. Hand-regenerate the
   3 rendered doc blocks: `docs/reference/cli/index.mdx:520` (**gated by `tests/test_docs/test_mdx_fences.py`**
   — clean ```` ```mermaid ```` fence, no `${...}`), `examples/agent-orchestration/plan-to-code/README.md:19`,
   `examples/agent-orchestration/parallel-planner-review/README.md:29`.
2. **Model purity (grep).** `grep -nE 'classDef|@\{|:::|fill:|stroke:|<br/>' graph/model.py graph/build.py`
   → zero. `build.py` is the only IR reader; `render_mermaid` reads no IR field. asdict+json round-trip
   (incl. the adversarial case, §8).
3. **Sufficiency.** The throwaway `render_react_flow` reconstructs — no info loss — every node (incl. the
   synthetic END node), edge kind (incl. `EdgeKind.END` abort edges), container (incl. loops), and a
   reachable source back-ref per node, for the 6 patterns + the 163 harness.
4. **Testability.** `build_graph` tested through its interface; `resolve_child` via plain closures; no mocks.

`make check` clean throughout.

---

## 10. Edge cases & risks

- **#1 risk — the 4-path Scope migration** (exhaustive, no 5th): `_generate_data_flow_edges` (`_edges.py:183`)
  + 3 hand-rolled — `_connect_sources_to_output` (`_io.py:184`, incl. coalesce + output-field),
  `_generate_batch_item_data_flow` (`_edges.py:232`), `_connect_input_from_params`/`_connect_input_from_batch`
  (`_io.py:72/112`, incl. the pair-dedup wrapper-routing). All reimplemented in `build.py`. The bulk of the work.
- **Batch-output-fan** (W6): the renderer rebuilds the fan from Containers + output Nodes; no current golden
  pins the over-fan → **add one** (§8) or a too-few/empty fan passes silently.
- **3-deep nested output threading** (W3): the post-order fold must thread a grandchild output up; assert the
  endpoint, not existence.
- **`shadowed()`** must encode all 3 clauses (§4e) — omitting any silently keeps/drops edges.
- **`asdict` safety** — `NodeId`/string cross-refs only; `annotations` + `BatchSpec.items` JSON-able;
  `SourceRef.file` is `str()`. Verified by the adversarial round-trip test.
- **`routes_to_end`** (Phase 0 IR flag) is parser-metadata only — inert to engine/validator (F14). `build`
  consumes it to create the synthetic END node + `EdgeKind.END` edge; Mermaid ignores END edges (parity); the
  react-flow sketch consumes them. The parser AST-path plumbing is the only place a careless edit could
  corrupt the return-tuple contract — keep it narrow.
- **Loop placement** — `LoopSpec` only when exactly one of `while`/`until` present; batch+loop mutually
  exclusive (assert).
- **Don't store derived facts** — `shape`/`is_decision`/`is_terminal`/`shadowed`.
- **Empty/zero/None** — 0-edge/0-node workflow, 0-item batch, dynamic batch (`items=None`): derived helpers
  and the per-item label rule must no-op (never `IndexError`/`NoneType`-subscript on `items[i]`); test these.

---

## 11. Function → new-home migration map (re-anchor lines before editing)

| Current | New home | Notes |
|---|---|---|
| `markdown_parser._build_edges`/`_build_node_dict`/`_extract_next_targets_from_code` | edit in place (§3a) | persist `routes_to_end`; do not move |
| `ir_schema.py` node schema | edit in place (§3a) | whitelist `routes_to_end` |
| `_render.py: generate_mermaid` | shim in `mermaid/__init__.py` | only this symbol re-exported |
| `_render.py: _render_workflow/_render_node/_render_subgraph/_try_expand_batch_item` | `build.py` (structure) + `renderers/mermaid.py` (syntax) | split walk vs draw |
| `_render.py: _try_resolve_child` (cycle stack) | `build.py` | port F4; fix `path is None` |
| `_render.py: _render_batch_inline` | `build.py` (BatchSpec + members, all items) + `mermaid.py` (truncate/procs/dots) | dots render-only |
| `_render.py: _render_end_nodes_and_edges` | `mermaid.py` (end-sink, parity, ignores END edges) + `build.py` (synthetic END node + `EdgeKind.END` edges from the `routes_to_end` flag; `is_terminal`) | `→end` is a distinct-kind edge |
| `_render.py: _render_loop_self_edge` | `renderers/mermaid.py` | from `LoopSpec` |
| `_edges.py: _deduplicate_edges` | `build.py` (run before action→kind) **and** `GraphModel` derived view | test migrates |
| `_edges.py: _detect_decision_nodes/_find_terminal_nodes` | `model.py` derived helpers | distinct-label, post-collapse |
| `_edges.py: _resolve_edge_endpoints/_render_edge` | `renderers/mermaid.py` | F3 routing recomputed at render |
| `_edges.py: _generate_data_flow_edges/_generate_batch_item_data_flow/_extract_batch_source` | `build.py` | structural data-flow edges |
| `_io.py: 4 wrappers + 2 bare IO + _connect_sources_to_output + _connect_*_inputs` | `build.py` (IO nodes/Containers/edges, pair-dedup) + `mermaid.py` (wrapper styles) | F10/F13 |
| `_scope.py: refs_in/source_refs_in` | `graph/scope.py` (phase 2, verbatim) | static helpers |
| `_scope.py: Scope.resolve / Scope.for_level / instance fields` | `graph/build.py` (phase 3) | **reimplemented** structural; not moved |
| `_context.py: MermaidConfig/MermaidContext + routing maps` | gone | local build state |
| **Pure-move →** `renderers/mermaid.py` | `_to_mermaid_id`, `_escape_label`, `_subgraph_style`, `_classdef_to_style`, `_format_node_type`, `_first_sentence`, `_render_classdefs`, `_strip_template`, `_SHAPE_MAP`, `_CLASSDEF_STYLES`, `_SUBGRAPH_OPACITIES`, `_WORKFLOW_TYPES` | signatures unchanged |
| **Adapt-to-dataclass →** `renderers/mermaid.py` | `_loop_label`(→`LoopSpec`), `_dynamic_batch_label`(→`BatchSpec`), `_get_item_label`(→`BatchSpec.items[i]`), `_format_label`(→`Node`) | rewrite, NOT verbatim |

---

## 12a. Phase breakdown for agent handoffs

| Phase | ~Prod LOC | Tests | Cognitive | Risk |
|---|---|---|---|---|
| 0. parser/schema `routes_to_end` | ~20 | ~3-4 | LOW | LOW |
| 1. `model.py` | ~220 | helper units | HIGH (identity) | MED |
| 2. `scope.py` (verbatim move) | ~10 | (existing) | LOW | LOW |
| 3. `build.py` | ~500–650 | **large suite** | **VERY HIGH** | **VERY HIGH** |
| 4. `renderers/mermaid.py` | ~450–550 | golden regen + adapt | HIGH | MED* |
| 5. shim + test migration | ~40 | rewrite 3 helper tests | LOW | LOW–MED |
| 6. remove old internals | delete ~1500 | (gated) | LOW | LOW |
| 7. react-flow sketch | ~20 (discarded) | n/a | MED | LOW |

\*parity is only a tripwire.

```
[0 parser] ─○─ [1 model] ─○─ [2 scope] ─●─ [3 build] ═║═ [4 render] ─○─ [5 shim] ═║═ [6 remove] ─○─ [7 sketch]
            LOOSE        LOOSE        TIGHT        FIREBREAK       LOOSE      FIREBREAK      LOOSE
```
- Phase 0 is an independent IR enrichment (LOOSE to everything; build just reads the field).
- **2→3 TIGHT** — `Scope.resolve`/`for_level` reimplemented in build; scope+build share the 4-path tacit knowledge.
- **3→4 FIREBREAK (the main split)** — locked by the frozen `GraphModel` + the build suite.

**Highest-risk phase: Phase 3 `build.py`** — stays with one agent; phases 0–3 = one agent (identity designed
in model, constructed in build; the migration spans scope; phase 0 is its tiny prerequisite).

**Recommendation: N=3** — [0–3 structural | 4 renderer | 5–7 cutover+sketch].

**Irreducible tacit knowledge → mitigation:** why `AncestorStep.batch_index` keys identity → `graph/CLAUDE.md`
worked example + the item-0≠item-1 test; which goldens shift + why → recorded in the PR; the 4-path
completeness → one build test per path; what the sketch couldn't draw → a model/build fix (escalate to agent 1).

---

## 12. Post-approval doc reconciliation (not code)

Reconcile docs to the verified model (uneditable in plan mode): `task-155.md` (the §6 deviations + D2 as a
`routes_to_end` parser field + dropped `via_coalesce`/leaf-batch/`NodeId.batch_index`); `context/CONTEXT.md`
(confirm Graph model / Container entries hold); `mermaid/CLAUDE.md` → repoint at `graph/`; add `graph/CLAUDE.md`.
No new ADR warranted (reversible refinements). If desired, a one-line note in Task 133 that `routes_to_end`
and the §6a join contract are the static half it should cite.
