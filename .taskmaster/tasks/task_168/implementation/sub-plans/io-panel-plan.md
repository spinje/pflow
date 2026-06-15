# IO Card Panel — clicking INPUTS/OUTPUTS opens the workflow's interface

> **Status:** ✅ IMPLEMENTED (2026-06-11, same day) — deviations + verification in the
> progress log's "IO interface panel" entry. One deviation: input `source` stays None
> (parser injects `_source_line` only for outputs; the inputs schema forbids extra keys).
>
> Trigger: user screenshot — clicking the OUTPUTS card does
> nothing in advanced density (the click is a focus toggle whose only visible effect is the
> beautiful-mode row expansion; the panel resolution dead-ends on `host: null` — the comment in
> GraphView.tsx:239-241 literally calls it "a parked knob"). This plan unparks it.
>
> **UX frame (settled in conversation):** the IO card is the workflow's public API — the most
> click-worthy object on the canvas — and it is the ONLY node-shaped object that answers a click
> with silence. Fix = make it behave like everything else (click = select + panel) and make the
> panel the workflow's signature written out: per input — name, type, required/default, full
> description, consumer chips; per output — name, description, `← producer.field` source chip.

## Locked design decisions

**D1 — Click = SELECT, the toggle dies.** The io arm in `onNodeClick` (GraphView.tsx:176-183)
is today the only toggle on the canvas. It becomes the same unconditional
`setFocus(id); setSelectedId(id)` as leaves and containers — one fewer special case, and the
"focus IS its open state" mechanic keeps working untouched (selection sets focus → expandTargets
expands the card in beautiful; pane-click clears focus → card closes). Closing = pane click /
panel ✕ / clicking another node — identical to every other node. *Muscle-memory note: "second
click closes" is gone; that matches what containers already did when select replaced open.*

**D2 — The panel is a SIBLING component (`IoPanel.tsx`), not a ReadPanel mode.** ReadPanel's
contract is "one RFNode"; the io card is a hostless wrapper *group*. Widening ReadPanel means
graph/group plumbing it never otherwise needs. EdgePanel already set the sibling precedent:
same `<aside className="read-panel">` shell, same `.facts`/`.fact` CSS, cross-imports of the
shared primitives (`ParamBlock`/`OutcomeTable`/`sourceLabel` are exported from ReadPanel today).
`Chip` gets **exported from EdgePanel** (it's module-local at EdgePanel.tsx:28) — same
precedent, no new file of "shared panel parts" (deletion test: extraction would move complexity,
not concentrate it).

**D3 — GraphView grows a THIRD resolution arm, disjoint by id namespace.**
`selectedIoGroup` memo: `selectedId` → a root (`parent == null`) `input_wrapper`/`output_wrapper`
group. Renders `<IoPanel group graph renderedIds markedPortId onNavigate onClose>` exactly like
the EdgePanel site (GraphView.tsx:365-373). `selectedNode`/`selectedEdge` resolution is
untouched — wrapper groups still produce no `selectedNode` (host is null), so the three arms
stay mutually exclusive by construction.

**D4 — Row click opens the panel too (ROOT wrappers only), with that port marked.**
`focusPort` (GraphView.tsx:234-237) today sets focus only ("a port has no params" — true, but
the port's OWNER now has a panel). New rule: resolve the port's owner via the existing
`ioOwners(graph)` single-copy helper; if the owner is a root wrapper id, also
`setSelectedId(owner)`. Nested wrapper rows (rows on workflow group cards) keep focus-only —
their owner's panel is the host ReadPanel and auto-opening it on a row click is a behavior
change nobody asked for. The panel receives `markedPortId` (= focus when focus is one of the
group's member port ids) and gives that entry the `.fact-marked` treatment — card click = whole
interface, row click = same panel scrolled to one port. Canvas row-level focus (reveal that
port's lines) is unchanged; this is additive.

**D5 — Python contract additions: inputs get the interface data outputs already have.**
The wire today (verified, see Facts): input ports ship NO description (IR has it — build drops
it), NO default (IR has it), NO source ref, and a `required` whose default polarity is **wrong**
(`build.py:181` defaults `False`; validator/executor/formatter/context all default `True`).
Changes, all in `_add_inputs` (build.py:152-186) + `IOPort` (model.py:61-64):
- `purpose = str(config.get("description", ""))` — exactly symmetric with `_add_outputs`.
- `required = bool(config.get("required", True))` — **a correctness fix**, aligning the wire
  with every runtime reader. (Verify the non-dict-config arm during implementation and match
  whatever the validator treats it as.)
- `IOPort.default: Any = None` — the IR value verbatim when authored, `None` when absent.
  (An authored `default: null` is indistinguishable from "no default" — accepted; it's
  pathological and the panel only shows the fact when non-None.)
- `source=_source_ref(config, source_file)` — free if the parser injects `_source_line` for
  inputs (it does for outputs); stays None otherwise. Verify, don't assume.
**Out of scope:** `stdin`/`stdout` markers (deferred — not in the panel mock); the verbatim
output `source:` expression text (reconstructable per-edge as `${producer.field.path}`, which
is what the panel shows — same rule EdgePanel.tsx:140 already uses).

**D6 — Consumers/producers derive from contract edges INLINE in the panel.** No new helper:
`graph.edges.filter(e => e.kind === "data_flow" && e.source === portId)` → consumers (inputs);
`… e.target === portId` → producer edge(s) (outputs). This is the established panel precedent
(EdgePanel's refSiblings walk, EdgePanel.tsx:176-187). Chips resolve through
`resolveEndpointFlatId` + disable-when-hidden, navigate via the existing `onNavigate`
(camera-follow included, GraphView.tsx:275-284).

**D7 — Run-hint line: OPTIONAL, last, default-skip pending the user's call.** A final
`pflow <name> input=…` line on the inputs panel is agent-friendly garnish; everything above
stands without it.

## Verified facts (file:line — from three codebase-searcher passes, 2026-06-11)

- io click toggle arm: `GraphView.tsx:176-183`; pane-clear: `:226-229`; "parked knob" comment:
  `:239-241`; panel render sites: `:365-395`; onNavigate+fitView: `:275-284`;
  `renderedIds`: `:261`.
- `selectedNode` falls through for wrapper groups: root wrappers ship `host: null`
  (fixture-confirmed: deep-research.json g0).
- io card build: `flow.ts:997-1036` (`type:"io"`, id = wrapper group id,
  `rowsVisible = detailed || expandedSet.has(wrapper.id)` at :1008). `IOCardData`:
  `flow.ts:96-112`. `Port` row type `{id, name, dataType, required, description}`:
  `flow.ts:81-89`, built by `wrapperPorts` `flow.ts:841-852` (module-local — export it; the
  panel must not re-derive port rows).
- `ioOwners` (wrapper/port → owner, shell-aware): `flow.ts:563-588`. Edge `data.from/to`:
  `flow.ts:1476-1477`. `expandTargets` wrapper arm (focus=wrapper → all ports + far ends):
  `flow.ts:601-661`.
- `focusPort` context: `components/interaction.ts:8-13`; PortRows row click + stopPropagation:
  `PortRows.tsx:59-67`; IOCardNode: `components/nodes/IOCardNode.tsx` (renders PortRows when
  `rowsVisible`).
- Panel primitives: ReadPanel exports `ParamBlock`/`OutcomeTable`/`sourceLabel`
  (ReadPanel.tsx:9,18,40); EdgePanel `Chip` (NOT exported, EdgePanel.tsx:28-67), exported
  `portOwnerHost`/`portIsNested` (:77-95). Panel CSS block: `index.css:1048-1246`.
- Python: input construction drops description/default/source — `build.py:152-186` (the
  `required=False` default at :181); output construction (the symmetry template) —
  `build.py:188-226`; `IOPort` — `model.py:61-64`; RFNode serialization `io=asdict(node.io)` —
  `react_flow.py:220`. Required-default-True readers: `validator.py:1663`,
  `workflow_executor.py:646`, `ir_preparation.py:60,83`, `path_validation.py:497`,
  `workflow_describe_formatter.py:117`, `context.py:144`. IR fields exist:
  `ir_schema.py:343-366` (description :349, required :350 documents default True, default :356).
- Contract fixtures drift guard: `tests/test_core/test_react_flow_contract_fixtures.py` +
  `tests/fixtures/react_flow_contracts/_generate.py` (regen command in the failure message);
  frontend copies `web/src/test/fixtures/contracts/*.json`.

## Steps

### Phase 1 — Python: complete the input port's wire data

1. `model.py`: `IOPort` gains `default: Any = None`. (Frozen dataclass; additive, positional-safe
   — audit `IOPort(...)` call sites anyway: build.py is the only constructor.)
2. `build.py _add_inputs`: populate `purpose` (description), `required` default → `True`,
   `default`, `source=_source_ref(...)`. Keep the existing non-dict guard shape; verify what a
   non-dict input config means before picking its `required` arm.
3. Tests (`test_graph_build.py` + renderer test): an input with
   description/default/required-omitted ships `purpose`, `io.default`, `io.required == True`,
   `source` (if parser provides the line — assert whichever is true and comment it); an input
   with `required: false` ships `False`; output behavior unchanged.
4. **Gate: Mermaid goldens byte-identical** (`test_mermaid_golden.py`). Input `purpose` was
   always `""` before — if any golden renders io descriptions this WILL surface; inspect before
   accepting any golden change (expected: none — verify, don't assume).
5. Regen contract fixtures (`_generate.py`) → both the Python drift guard and the web fixture
   copies update. The `required` polarity flip will change fixture JSON — that's the fix
   working, not drift.

### Phase 2 — Frontend data plumbing

6. `types.ts`: `IOPort` mirror gains `default: unknown | null`. `flow.ts`: `Port` gains
   `defaultValue: unknown | null` (and inputs now get `description` for free via `m.purpose` —
   delete the stale "inputs have none" comment at `wrapperPorts`); export `wrapperPorts`.
7. Confirm web tests still green (the polarity flip may move tooltip pins in PortRows tests).

### Phase 3 — IoPanel + GraphView wiring

8. Export `Chip` from EdgePanel.tsx (rename nothing; one keyword).
9. New `web/src/components/IoPanel.tsx`:
   props `{ group: RFGroup; graph: RFGraph; renderedIds; markedPortId: string | null;
   onNavigate; onClose }`. Renders the `.read-panel` shell: kind line `INPUTS`/`OUTPUTS`,
   `h2` = workflow name (root wrapper → graph root name; same source IOCardNode uses), count
   line, then one entry per `wrapperPorts(...)` port — name + type + `required`/`default: …`
   facts, full description paragraph, `source` file:line via `sourceLabel`, and chips:
   inputs → "used by" consumer chips (D6), outputs → `← producer.field[.path]` + producer chip.
   `markedPortId` entry gets `.fact-marked`. Reuse existing CSS classes; add at most a couple
   of `.io-panel-*` rules — no new styling system.
10. GraphView: delete the io toggle arm (D1); add `selectedIoGroup` memo + the third render arm
    (D3); `focusPort` becomes owner-aware (D4, via `ioOwners`); update the stale comments
    (:230-233, :239-241).

### Phase 4 — Tests, browser, docs

11. `IoPanel.test.tsx` (jsdom, EdgePanel fixture pattern — **production-style divergent ids**):
    inputs variant (required/default/description facts, consumer chips resolve + disabled-when-
    hidden), outputs variant (producer `← field.path`, description), markedPortId highlight,
    empty-description port renders without a gap.
12. GraphView pins: io card click opens IoPanel (replaces nothing — the toggle had no jsdom pin,
    a known gap); second click keeps it open; pane click closes panel + collapses card;
    root row click opens panel with the port marked; NESTED row click does NOT open a panel.
13. Real-browser loop (headless, `screenshot-pflow-web-ui`): lyrics-generator — click OUTPUTS
    (the motivating screenshot) → panel with `report ← summary-report.result` + description;
    click INPUTS in beautiful → card expands + panel + lines reveal; row click → marked entry;
    chip click → camera follows. **Restart the server after the Python change** (the
    serves-old-Python gotcha).
14. Docs sync: `web/CLAUDE.md` (panel trio + io click semantics), `ui/CLAUDE.md` (IOPort.default
    on the contract), `visualization-requirements.md` (Implemented + the superseded toggle),
    progress log entry. Full gates: `make test` + `make check` + web vitest/tsc/build.

## Anti-goals

- Do NOT widen ReadPanel to take groups (D2). Do NOT extract a shared panel-parts module.
- Do NOT add registry-declared interface rows (rejected 2026-06-10 — rows/facts come from
  authored data or actual reads only).
- Do NOT change nested-wrapper row click behavior or canvas row rendering (tooltips may
  truthfully change via the polarity fix; that's all).
- Do NOT ship the verbatim `source:` expression on the wire — per-edge reconstruction is the
  established rule.
- Do NOT touch Mermaid (`mermaid.py`), `applyFocus`, or `expandTargets` — the focus mechanics
  already do everything the panel needs.
