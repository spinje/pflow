# Braindump: Task 155 — verified facts, the build mechanics, and what the implementation plan still needs (2026-06-06)

## Scope of THIS file (read first — strict non-overlap)

The other three files in this folder + the ADRs already cover their ground; **do not re-derive any of it here:**
- `task-155.md` — the *what/requirements* (model fields, Non-Goals, Verification, packaging). It was rewritten this session to current truth.
- `braindump-static-substrate-for-visual-ui.md` — 155's role/lead-promotion, the two-substrates frame, the Task 163 driver, why click-to-read matters, working style (now patched to current decisions).
- `braindump-loop-rendering-and-155-implications.md` — the loop fix (#483, merged), the three loop shapes, loop-on-subgraph = clean multinode, the loop field shape, the react-flow direction, and the **loop-specific** verified file:lines (parser/schema/engine/LoopConfig).
- `context/adr/0003-155-graphmodel-node-identity.md` and `0004-155-graphmodel-primitive-only.md` — the two load-bearing decisions + rationale. `context/CONTEXT.md` — the terms (Graph model, IR, Container).

**This file is ONLY the four things that exist nowhere else:** (1) the four pre-implementation verification passes with `file:line` (the evidence under the spec/ADRs — the searcher *reports* die with my context; this summary is the only durable record), (2) the architecture-lens reasoning that *shaped* the spec, (3) the concrete `build_graph` mechanics, (4) what the implementation-plan artifact must contain (the build-guide I deliberately stripped out of the spec).

---

## 1. The four verification passes (file:line — the durable record)

Run this session as four parallel `pflow-codebase-searcher` agents to put the spec/ADRs on verified ground. Trust boundary: **"Verified by searcher, line numbers as reported"** — the package is actively changing (loop fix just landed), so re-confirm a line if it looks off. One concrete proof it drifts: the mermaid `CLAUDE.md` documents the `outgoing_routes`/`has_expanded_outputs` write sites at `_io.py:348-349` + `_render.py:272-275`, but they are actually at **`_io.py:398-399` + `_render.py:291-294`** (the invariant holds; the line numbers are stale). **Do not trust `CLAUDE.md` line numbers when implementing — re-anchor against current code.**

### A — Routing-map separability (the gating risk → cleared)

Verdict: **a clean two-phase `build_graph` is possible.** All 5 `MermaidContext` routing maps (`outgoing_routes`, `has_expanded_outputs`, `fork_join_map`, `incoming_map`, `data_flow_targets`) and the `_render_workflow` upward return value are **structural facts** — deterministic functions of the IR subtree + resolved child IRs. **None** reads `ctx.lines` or any rendered-string state.

**THE implementation gotcha (this is the #1 thing for the build):** there is one *intra-build ordering* constraint (not a render-order one). In `_render_workflow` the node loop (`_render.py:115-116`) populates the node-keyed maps in document order, and `_generate_data_flow_edges` runs **inside that same loop** (`_render.py:197`), calling `Scope.resolve` which reads `outgoing_routes` **live** (it documents this at `_scope.py:11-14` — non-snapshot reads "because populated incrementally"). So a ref to a *later* sibling resolves wrong if you don't complete population first. Today `_connect_top_level_inputs` (`_render.py:118-120`) and structural edges (`_render_end_nodes_and_edges`, `_render.py:129`) are already deferred to after the loop; **only data-flow generation is fused in.** → `build_graph` must do **two sub-passes: (a) walk all nodes (recursively) populating every node-keyed map first; (b) then resolve all data-flow / input / structural edges against the complete maps.** This is *strictly cleaner* than today (removes the partial-read fragility) and is the one place the new build "improves correctness" rather than just preserving — which means **it may legitimately shift a golden** (fine under the tripwire policy; flag it when it happens).

Two freebies: `has_expanded_outputs == set(outgoing_routes.keys())` (the spec's "collapse to one field" — confirmed derivable). The upward `_render_workflow` return composes as a **post-order tree fold** (parent reads `child_submodel.outgoing_routes`), no interleaving, no cycle.

### B — ID alignment (the evidence under ADR-0003)

ADR-0003 records the *decision*; here's the *evidence* (not in the ADR). Visualizer flattens hierarchy into strings; runtime/trace keeps IDs bare + structural. They **diverge** for everything nested:

| | Visualizer ID | Runtime / trace identity |
|---|---|---|
| top-level node | `fetch-data` | `event.node_id == "fetch-data"` — **match** |
| nested sub-wf child | `process__classify` (prefix accumulates `ctx.child(prefix+node_id+"__")`, `_render.py:411`) | bare `classify`, nested under parent's `sub_workflow_events` (`workflow_trace.py:540-563`); child runs in an isolated store namespaced by bare id (`engine.py:1013`, `compiler.py:308`) |
| batch item | `fanout__alpha` — keyed by **label** (`_get_item_label`, `_context.py:233-248`) | `batch_items[i] = {index, item, …}` — keyed by **integer index** (`batch_executor.py:859-918`); `workflow_trace.py:353-354` explicitly ignores batch items "carry index, not node_id" |
| dynamic batch (`items:${x}`) | **one** `procs` node, zero per-item IDs (`_render.py:213-218`) | N entries by index |
| IO wrappers `__in_`/`__out_` | visualizer-only synthetic nodes | **no runtime node/event at all** |

Consequences for the build: store structural identity `(node_id, ancestor_path, batch_index?)`; the mermaid renderer derives the flat string. **IO-wrapper nodes have no runtime counterpart** → the future live overlay can't animate them off node-execution events (animate via edge dataflow instead) — worth a note in the model so the overlay knows. There is **no existing mermaid↔trace mapping layer** to reuse (searched — none).

### C — IR inventory, synthetic reachability, annotation seam

**Per-node IR fields `build_graph` can read** (schema `ir_schema.py:237-296`; parser `_build_node_dict` `markdown_parser.py:1559-1629`): `id`, `type`, **`purpose`** (the human description — the prose under the `###` heading, `:1612-1614`), **`params`** (catch-all, `additionalProperties:True` `:249`), `batch`, `loop`, `retry`, `cache`, `prompt_cache`, `prewarm`, **`_source_line`** (heading line, always set `:1627`), **`_source_lines`** (`{param: content-line}`, code-block params), **`_source_files`** (`{param: origin-file}`, injected by `file_resolver.py`). Routing (`next`/`on-error`) is NOT on the node — it's lifted into `ir["edges"]` (`{from,to,action}`; `on-error`→`action="error"`); **walk `ir["edges"]` separately.** Prompt content = `node["params"]["prompt"]`; its origin file = `node["_source_files"]["prompt"]`; its content line = `node["_source_lines"]["prompt"]`. → **click-to-read needs no new plumbing.**

**Synthetic-node reachability = YES.** `resolve_child` returns `SubWorkflowResult(ir, path, warnings)` where `.ir` is **file-resolved** (prompts already inlined; `sub_workflow_resolver.py:104-125,163`) and `.path` is preserved; `child_base = child_result.path.parent` is threaded into the child ctx (`_render.py:410-411`). Batch items reachable via `_try_expand_batch_item` (`_render.py:335-363`). **Caveat:** `_try_resolve_child` swallows resolution errors → `None` (`_render.py:490-503`) for `${template}`-dynamic workflow refs / unresolvable paths → those render **opaque** (inherent static limit, not a bug).

**Annotation seam (the nuance behind ADR-0004's `annotations` slot):** a custom node key (`pattern: tournament`) does **not** survive end-to-end today. The parser only hoists a fixed allowlist to top-level (`markdown_parser.py:1600`), so a custom key lands in **`params`**. The schema permits it (`params.additionalProperties:True`) but the node object is `additionalProperties:False` (`ir_schema.py:296`) AND the validator's **Step-8 unknown-param check rejects it** (against the registry interface). So the model's `annotations` slot is free, but *author-declared* annotations need a future carve-out: **Option A** — reserved namespace in `params` exempted from Step-8 (no parser/schema change, smallest); **Option B** — first-class top-level `annotations` field (hoist in parser + schema + Step-8 exemption, mirrors how batch/loop/cache were added). Not 155's job; recorded so it's not "discovered" as a blocker.

### D — One container concept, rename blast radius, CLI wrapping

**There is NO shared container abstraction today** — 7 ad-hoc `subgraph…end` emit sites: sub-workflow expansion (`_render_subgraph` `_render.py:408`), batch fork/join (`_render_batch_inline` `:258`), **batch-item-subworkflow** (`_try_expand_batch_item` `:352` — a 7th site not in the old spec's list), top-level inputs (`_io.py:30`), top-level outputs (`_io.py:154`), external inputs (`_io.py:323`), external outputs (`_io.py:370`). **Bimodal style** (the one thing the Container `kind` must drive): expansion/batch use `_subgraph_style(depth)` (opacity ramp `_SUBGRAPH_OPACITIES=[0.07,0.14,0.21,0.28]`); the 4 IO wrappers use a **hardcoded dashed string**. One `Container(id,label,kind,nesting_depth,parent,member_node_ids,loop?)` covers all 7 + future cycle — but it must add explicit **`parent` + `member_node_ids`** (today implicit in ID-prefix strings + `fork_join_map`). Loop-on-subgraph is a **label decoration**, not a container kind.

**Rename blast radius = tiny: exactly 3 external imports** — `cli/commands/visualize.py:52`, `tests/test_core/test_mermaid.py:6-14` (the full helper surface), `tests/test_core/test_mermaid_golden.py:16` — plus intra-package imports + 2 `logging.getLogger("...mermaid")` strings + doc mentions. `core/workflow/__init__.py` does **not** re-export mermaid (no second surface). `tests/test_cli/test_visualize.py` goes through the CLI command, insulated. **A compat shim re-exporting `generate_mermaid` (+ the 6 test helpers) from the old path → zero external edits.**

**CLI wrapping** (`cli/commands/visualize.py`, all self-contained — only coupling is the one `generate_mermaid(...)` call at `:94`): resolve → `WorkflowRunner().validate(...)` → `base_path = parent of file` → `generate_mermaid(ir, resolve_child=resolve_sub_workflow, base_path, max_depth=depth, direction, descriptions)` → if `-o *.md` wrap as ``# {title}\n{desc}\n```mermaid\n{mermaid}```\n`` (title = `resolved.title` or filename stem); `-o *.mmd`/other = raw; no `-o` = stdout; confirmation to stderr. Gotcha: CLI `--depth` default **5**, `generate_mermaid`'s own default **1** (CLI always passes explicit).

---

## 2. The architecture lens (why the spec is shaped the way it is)

The user had me read `.claude/skills/improve-codebase-architecture/` (LANGUAGE.md = architecture vocab: Module/Interface/Depth/Seam/Adapter/Leverage/Locality; DEEPENING.md; INTERFACE-DESIGN.md). **We did NOT run the skill** — its process *finds* deepening candidates; we already had ours. We applied its lens. The reasoning that shaped the spec but isn't written as such:

- **155 is a deepening**: the IR-walk is today shallow + scattered across `_render/_edges/_io/_scope/_context`; `build_graph → GraphModel` makes it a deep module (small interface, large behavior, N consumers). That's the real frame, beyond "text-in-text-out debt."
- **Deletion test** validated 155 *and* guarded the YAGNI calls: deleting `build_graph` concentrates complexity (earns its keep); an analysis layer with no consumer today is a shallow pass-through (→ ADR-0004, don't build).
- **"Interface is the test surface"** → the spec's testing-strategy shift: structural assertions move to the GraphModel; goldens demote to the *mermaid adapter's* regression. (Now in the spec's Verification, but the *why* is here.)
- **"One adapter = hypothetical seam, two = real"** is *why 155 isn't overengineering*: mermaid + the committed react-flow = two real adapters → the seam is earned. Corollary the spec encodes: **no more seams than have two adapters** — `annotations` stays a field (not a port), the analysis layer stays unbuilt.
- **Dependency category** = in-process / local-substitutable: `build_graph` is a pure fn of `(IR, resolve_child)`; `resolve_child` is the one injected port with existing test adapters → **no mocks**. That's the testability contract in the spec.
- **CONSIDER (unused this session): INTERFACE-DESIGN.md's "design it twice"** — parallel sub-agents each producing a radically different interface. We didn't need it (the GraphModel shape is largely dictated by the IR walk). But if the *exact dataclass interface* feels non-obvious during implementation, that pattern is the user-blessed way to explore it.

---

## 3. What the implementation-plan artifact still must contain

The user enforced a hard principle (see §4) that the spec is *what/requirements only* — so I **deliberately removed** the build-guide from `task-155.md`. It now has to live in the implementation plan (the next artifact). Specifically, rebuild there:

- **Phasing**: (1) `model.py` dataclasses → (2) `build.py` `build_graph` as the **two-sub-pass** walk (§1.A) → (3) `renderers/mermaid.py` over the model, byte-stable output → (4) rewire `generate_mermaid` + compat shim → (5) the **`graph/` rename as a separate mechanical commit** (don't tangle the structural extraction and the move) → (6) throwaway react-flow completeness sketch (six patterns + 163 harness, no info loss), discard.
- **A feature→layer mapping with *current* file:line anchors** — the old spec had this table but with stale lines. Rebuild it from D's function inventory + the mermaid `CLAUDE.md` function-to-file map, **re-verifying every line** (CLAUDE.md lines are stale, §1).
- **The testing-strategy migration** (what moves to GraphModel-level assertions, what stays as the mermaid golden).
- **Per-phase verification** tied to the spec's four Verification buckets.

CONSIDER: this plan is itself a good `/improve-codebase-architecture`-adjacent or `plan-breakdown` candidate, but it's small enough that one careful pass likely suffices.

---

## 4. User's working style — ONLY the net-new from this session

(The general style — properties-not-categories, "why is X" is a catch, verify-before-asserting, simplicity-of-final-code, never-commit-without-instruction — is already in both existing braindumps. Don't re-read it here. These are the *new* signals from this session:)

- **Spec hygiene is load-bearing to them.** Exact words: *"this is the what and how, we should avoid implementation details in this document unless its a specification of a requirement."* They made me strip the spec's Implementation-Notes (mapping table, enum sketch, order-of-work, code-to-read). **Keep build-mechanics OUT of the spec, IN the plan.**
- **They hate cross-doc duplication.** Exact words: *"make ABSOLUTELY sure you are not writing things that currently already exist in the other files."* Every doc must be net-new. (This braindump obeys it; the next agent should too.)
- **ADRs are a tool to stop future re-litigation.** They liked that ADR-0004 stops a future `/improve-codebase-architecture` run from re-suggesting the analysis layer. They prune ADRs they deem insignificant (they deleted `0002-455` mid-session). Next ADR number is **0005**.
- **They've adopted the architecture vocabulary** — they edited `CLAUDE.md` mid-session to "Verify at seams first" / "favor depth over feature surface." Speak Module/Seam/Depth/Adapter with them.
- They drive decisions fast once grounded ("yes A and lets use graph/", "yes go ahead, think hard before writing") — but they *first* want the options + verification. Earn the "go ahead" with grounded analysis, then move.

---

## 5. Assumptions, uncertainties, unexplored

- **NEEDS VERIFICATION (searcher A's own flag):** the two-sub-phase build is "more correct," so a golden *may* shift — characterize *which* workflows differ when implementing, and confirm each shift is the correct-er output, not a regression. Don't assume zero golden churn.
- **ASSUMPTION:** the model field set in the spec is sufficient. The react-flow completeness sketch (six patterns + 163 harness) is how you *prove* it — treat it as a real design check, not a formality. If the sketch can't draw something the IR knows, the model dropped a field.
- **UNCLEAR:** exact `kind`/`shape` enum values — left illustrative in the spec on purpose; finalize as the renderer mapping reveals what's needed (the old spec's enum sketch was explicitly "not a spec").
- **MIGHT MATTER:** the `outgoing_routes`/`has_expanded_outputs` "collapse to one field" — searcher A confirmed they're equal *today*, but the mermaid `CLAUDE.md` "Known Limitation" notes the split was *designed* to let batch-output-fan be fixed later (exclude batch from `outgoing_routes` while keeping `has_expanded_outputs`). If you collapse to one field, you foreclose that specific future fix. Probably fine (batch-fan fix is not in scope and may never happen), but **decide consciously** — don't collapse by accident.
- **UNEXPLORED:** how the eventual `pflow ui`/`--serve` reads the model (likely `dataclasses.asdict` → JSON → local React). The spec only requires the model be `asdict`-able; the serving command is the *web-UI task*, still unfiled (needs GraphModel + the Substrate-2 event log).

---

## 6. Files written this session (state — likely staged by the auto-stage hook, NOT committed)

- `.taskmaster/tasks/task_155/task-155.md` — full rewrite (what/requirements; build-guide removed).
- `context/CONTEXT.md` — +3 terms (Graph model, IR, Container) + "Graph model vs IR" ambiguity.
- `context/adr/0003-155-graphmodel-node-identity.md`, `0004-155-graphmodel-primitive-only.md` — new.
- The two sibling braindumps — surgically patched to current decisions (parity→tripwire, click-to-read resolved, structural identity, mockup discarded).
- This file.
- **Reference renders made this session** (scratch, useful baselines for the completeness check): `scratchpads/handoff-see-control-storage/harness-view-now.md` (the 163 harness as mermaid today — note the review loop is now a `loop:` badge, the group loop a back-edge), `loop-render.md` (tournament loop), `pattern-fanout.md` (batch fan-out as `parallel x|plan|`).
- `git status` before committing (auto-stage hook stages writes; user commits, never the agent).

---

## For the next agent (likely the implementation-plan writer, then the implementer)

- **Start by** reading, in order: this file → `task-155.md` (the spec) → the two sibling braindumps → ADR-0003 + ADR-0004 → `context/CONTEXT.md`. The session master narrative is `scratchpads/handoff-see-control-storage/session-progress-log.md` (older, broader — the see/control vision 155 sits inside).
- **The single most important build fact** is §1.A's two-sub-pass requirement — get that right and the extraction is straightforward; miss it and data-flow edges resolve against half-built maps.
- **Don't trust mermaid `CLAUDE.md` line numbers** — re-anchor against current code (proven stale this session).
- **The next artifact is the implementation plan** (§3) — and it's where build-mechanics belong, NOT the spec (§4).
- **Don't** re-run the four searchers (their facts are in §1), re-open A/B/graph-name decisions (locked: structural identity, `graph/`, Container), or put implementation detail in the spec.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points — especially the two-sub-pass `build_graph` requirement (§1.A), the structural-identity evidence (§1.B), and the spec-purity principle (§4) — then state you're ready to proceed.
