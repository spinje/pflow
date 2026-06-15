# Task 168 — Phase A Implementation Plan (Tines/n8n visual redesign)

> **Scope.** Frontend-only restyle of the `pflow ui` canvas to the Tines/n8n look:
> neutral-tile native-color icon nodes, one visual language across both densities,
> gradient control edges, dashed branches, softened palette, beautiful-by-default.
> **Zero contract change.** Companion to `../../research/visual-redesign-knowledge.md`
> (the KB — gradient technique, Flowise teardown, gotchas). This doc records the
> *concrete file-by-file plan + the simplicity decisions where I diverge from the KB*.
> The §1 invariants in the KB (collapse/focus/LR-TD/read-panel/ports/loop/forks,
> handle-type invariant, additive edges, no-info-loss) must not regress.

## Guiding principle (from the user)

Optimize the **FINAL code** for simplicity — what the top 10% of comparable
CLI/tool codebases would ship — *without* over-abstracting. Fewer files, obvious
data flow, easy for the next agent to extend. The deletion test governs every new
abstraction: keep it only if removing it would *concentrate* complexity, not move it.

## Key design decisions (3 diverge from the KB — recorded with rationale)

1. **ONE `WorkflowNode` component, not two (Detailed/Compact) + a shared `NodeHeader`.**
   The KB sketched keeping both node components and extracting a `NodeHeader`. But the
   two densities now differ *only* by "show the body or not" — so the simplest final
   shape is a **single** component that always renders the header and renders the body
   when `density === "detailed"`. One file replaces three (no `NodeHeader.tsx`,
   no `CompactNode.tsx`). The React Flow node `type` collapses from `"detailed"|"compact"`
   to a single `"node"`; density rides in `data` (where it already lives). Deletion
   test: extracting `NodeHeader` for a single consumer only *moves* complexity → don't.
   - **Cost:** 2 incidental assertions in `flow.test.ts` (`type === "detailed"`) update to
     `"node"`; the `FlowNode` union loses one arm. The *behavioral* assertions
     (branchLabels, handle-type invariant, density-governs-edges) are untouched.

2. **Icon registry in a dedicated `utils/icons.ts`, not inlined into `format.ts`.**
   The icon map pulls ~11 `.svg` imports + the provider resolver. Keeping it out of the
   heavily-depended-on `format.ts` (a) gives a single obvious home for "add a node icon",
   and (b) isolates asset imports from `format.ts`'s wide dependency tree. `format.ts`
   keeps the pure text/color helpers; `categoryLabel` lives there (it's text, no assets).

3. **`GradientEdge` omits label rendering; marker = solid target color.** Control edges
   (sequential/branch) carry **no** label by construction (`toFlowEdge` nulls branch
   labels — they ride the border handle via `BranchPorts`; sequential edges have none).
   So the component is just the gradient path + arrowhead — no `EdgeLabelRenderer`.
   Data-flow edges keep `type:"default"` so React Flow renders *their* "stdout → data"
   labels natively (the existing beautiful-mode behavior the tests pin).

## File-by-file changes

### New files
- `web/src/assets/icons/*.svg` — vendored from `pflow-cloud/public/` (see icon table) +
  a hand-written `placeholder.svg` (generic box, for http/file until real ones land).
- `web/public/favicon.ico` — copied from `pflow-cloud/public/favicon.ico`.
- `web/src/utils/icons.ts` — `iconFor(node)` + `PROVIDER_ICON`/`KIND_ICON` maps + the
  `model.split("/")[0]` provider resolver. The single place to wire a node-kind icon.
- `web/src/components/nodes/WorkflowNode.tsx` — the unified node (header always; param
  rows + output ports when detailed; `BranchPorts` in both). Replaces Detailed+Compact.
- `web/src/components/edges/GradientEdge.tsx` — the `userSpaceOnUse` gradient bezier (KB §3.2).

### Deleted files
- `web/src/components/nodes/DetailedNode.tsx`, `web/src/components/nodes/CompactNode.tsx`.

### Edited files
- `web/src/utils/format.ts` — remove `KIND_GLYPHS`/`kindGlyph` (only the deleted nodes
  used it); soften `KIND_COLORS`; add `categoryLabel(node)`. Keep parseTemplate/preview/etc.
- `web/src/components/nodes/index.ts` — `nodeTypes = { node: WorkflowNode, ports, group, end }`.
- `web/src/components/edges/index.ts` — register `gradient: GradientEdge` alongside `loop`.
- `web/src/graph/flow.ts` —
  - `FlowNode` union: `Node<LeafData,"detailed">|"compact"` → `Node<LeafData,"node">`.
  - leaf emit: `type: view.density` → `type: "node"` (density stays in `data`).
  - `EdgeData`: add optional `sourceColor?`/`targetColor?`.
  - `toFlowEdge`: control edges (seq/branch) → `type:"gradient"` + both colors in `data`,
    drop the inline `style.stroke`; data/error/end stay `type:"default"` (CSS strokes);
    marker = target color for control, semantic literals for error/end, none for data.
  - size constants: header is taller/wider → bump `DETAILED_WIDTH`/`COMPACT_WIDTH`/
    `COMPACT_HEIGHT`/`HEADER_HEIGHT`; re-tune live after first render.
- `web/src/views/GraphView.tsx` — default density `useState<Density>("compact")`.
- `web/src/index.css` — new `.node-header`/`.node-tile`/`.node-category`/`.node-name`;
  gradient/dashed edge rules (keep CSS strokes ONLY for non-gradient kinds); softened
  `:root` palette vars (`--data-edge`/`--ref` off the neon green).
- `web/index.html` — favicon link.

### Test updates (behavior-preserving)
- `web/src/graph/flow.test.ts` — the 2 `type === "detailed"` assertions → `"node"`.
- `web/src/views/GraphView.test.tsx` — beautiful default now shows the **purpose**
  ("say hi") not node_id; the `${ref}` chip is an advanced-body detail → the mount test
  asserts the purpose/fallback titles, then clicks "advanced" and asserts the chip
  (keeps real chip-render coverage).
- `web/src/utils/format.test.ts` — unaffected (tests parseTemplate/previewValue only).

### Docs
- `web/CLAUDE.md` — node-component section: one `WorkflowNode` (density in data),
  `utils/icons.ts` registry, gradient edge + the "CSS stroke only for non-gradient kinds"
  rule. Keep the handle-type-invariant / additive-edges notes.

## Icon vendoring map (`pflow-cloud/public/` → `web/src/assets/icons/`)

| dest | source |
|---|---|
| bash.svg | `tools/Bash_dark.svg` |
| mcp.svg | `logos/Model Context Protocol_dark.svg` |
| python.svg | `logos/icons/python.svg` |
| claude.svg | `logos/agents/claude-ai-icon.svg` |
| markdown.svg | `logos/icons/workflow/markdown-dark.svg` |
| ai-llm.svg | `logos/icons/ai-llm.svg` |
| anthropic.svg | `logos/agents/Anthropic_dark.svg` |
| openai.svg | `logos/agents/OpenAI_dark.svg` |
| gemini.svg | `logos/llms/gemini.svg` |
| ollama.svg | `logos/llms/Ollama_dark.svg` |
| placeholder.svg | hand-written generic box |

Kind→icon: shell=bash, mcp=mcp, python=python, code=python (placeholder), claude-code=claude,
workflow=markdown, http=placeholder, file=placeholder, llm=provider-resolved(default ai-llm).
Provider→icon: anthropic, openai, gemini, ollama. `input`/`output`=ports node (no tile);
`end`=sink circle (no tile).

## Verification

1. `cd web && npx vitest run` — **all green**, especially `flow.test.ts` HANDLE-TYPE
   INVARIANT (styling never touches handles, so it holds) and density-governs-edges.
   First risk to clear: `.svg` URL imports must resolve under Vitest (isolated to
   `utils/icons.ts`) — if not, the whole tree fails fast and obviously.
2. `npx tsc --noEmit` strict clean.
3. `npm run build` → bundle into `src/pflow/ui/static/`.
4. **Real browser** (`uv run pflow ui`): `conditional-branching` (forks + dashed branches +
   gradient), then the 82-node harness (beautiful default, gradient control skeleton,
   focus reveals data lines, density toggle, LR/TD, collapse, read panel, loop arc).
   jsdom can't see edges — the browser is the only proof of the visual layer.

## Acceptance

Matches the Tines/n8n references — neutral-tile native-color icons, gradient control
edges, dashed conditionals, softened palette, beautiful default, LLM provider icons —
with **zero contract change** and **no regression** to the §1 invariants. `render_react_flow`
and its Python tests are untouched.
