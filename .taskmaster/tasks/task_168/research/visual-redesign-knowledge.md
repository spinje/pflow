# Task 168 — Visual Redesign Knowledge Base (Phase A: n8n-style look-and-feel)

> **What this file is.** A single, self-contained brief for redesigning the `pflow ui` canvas
> to match the **n8n / Flowise-AgentFlow** look (gradient edges, color-tile icon nodes,
> clean branch fan-out). It was compiled by cloning **Flowise** (`FlowiseAI/Flowise`, `packages/ui`)
> and reading its actual AgentFlow-v2 source, plus authoritative `@xyflow/react` v12 / ELK /
> smart-edge docs. **Assume the reader has ONLY this file + the codebase** — every technique here
> is written to be implemented directly, with code for OUR stack.
>
> **Mission context.** Task 168 shipped a working static viewer (`render_react_flow` Python
> contract → Starlette `pflow ui` → Vite/React/`@xyflow/react`/ELK SPA). It works and is fully
> tested but looks utilitarian. Phase A is a **frontend-only restyle** (zero contract change) to
> the references the user supplied. Later phases: B = branch clarity, C = annotations, D = smart
> routing. See `../visualization-requirements.md` (the hard requirements that must not regress) and
> `../../task_168/implementation/progress-log.md` (the journey).

---

## 0. The single most important conclusion

**Flowise does NOT solve our hard problems.** It is `reactflow@^11.5.6` with **no dagre, no elkjs,
no auto-layout** — every node position is hand-dragged and persisted. Confirmed:
`packages/ui/package.json` has no layout lib; `grep -r "getLayoutedElements|dagre|elk.layout"` → nothing.

So Flowise is worth cloning for exactly **one thing: visual styling** (gradient edges, color-tile
nodes, the pastel palette, provider badges). For **auto-layout** (we derive graphs, we don't drag
them) and **node-avoidance routing**, Flowise offers nothing — that stays our problem (ELK + §9).

Everything below separates **[BORROW]** (take the technique) from **[SKIP]** (Flowise-specific or
editing-only, irrelevant to our read-only derived viewer).

---

## 1. Locked decisions (the brief — do not re-litigate)

1. **Tile treatment = Option B (n8n): neutral dark tile + icon in its native color.** NOT solid
   color tiles with white glyphs (that was Option A / the pure color-tile look). The **kind color** still drives:
   the category label text, the card's left accent, and the gradient edges. This lets the brand
   SVGs (python blue/yellow, claude orange) render as-is, no recoloring.
2. **"Beautiful" is the new DEFAULT density** (currently `detailed` is default — flip it in
   `GraphView.tsx`).
3. **One visual language for both densities.** Advanced = "the same card, bigger" — same header
   (tile + category + bold purpose), advanced just **adds the body** (param rows + output ports) and
   shows **all** data-flow edges; beautiful = header only + the control skeleton. Structurally:
   `DetailedNode`/`CompactNode` collapse to a **shared header** + an optional body.
4. **LR stays the default orientation** (LR/TD toggle kept). The references are vertical, but it's
   the *card + edge aesthetic* we want, not the orientation (n8n proves it reads horizontally).
5. **Icons:** vendor real SVGs (no lucide). The `llm` node icon is **resolved from the model
   field's provider prefix** (verified format: `provider/model`), default to a sparkle.
6. **Skip annotations** this round (logged future: render the workflow description + non-reserved
   `##` sections as on-canvas cards — Flowise's `StickyNote` is the reference pattern, see §8.5).
7. **Soften the harsh neon green** (`--data-edge`/`--ref` `#8be9c0`). Use a calmer green/teal;
   purple is taken (batch/llm) so avoid it for data-flow. Tune live (§5).
8. **No existing feature lost.** Preserve: collapse/expand, focus+context, LR/TD, read panel,
   consolidated dual-handle ports node, loop arcs, fork handles, the **handle-type invariant**, the
   **additive-edges** principle, no-information-loss. These are pure-style changes layered on top.

---

## 2. Our stack + the exact seams to touch

**Stack (from `web/package.json`):** `@xyflow/react@^12.3.5`, `elkjs@^0.9.3`, `react@^18.3.1`,
`vite@^5.4`, `vitest@^4.1`, `typescript@^5.6` (strict). Build → `src/pflow/ui/static/` (base `./`),
ships in the wheel via `pyproject.toml` `[tool.hatch.build.targets.wheel] artifacts` (don't remove).

**File map — where each Phase-A change lands:**

| Change | File / symbol |
|---|---|
| Edge gradient + dashed/solid styling | `web/src/graph/flow.ts` → `toFlowEdge()` (the styling factory); add `sourceColor`/`targetColor` to `EdgeData` (type in flow.ts) |
| New gradient custom edge | `web/src/components/edges/GradientEdge.tsx` + register in `web/src/components/edges/index.ts` (alongside existing `loop`) |
| Node card (shared header, tile, icon) | `web/src/components/nodes/DetailedNode.tsx` + `CompactNode.tsx` → extract a shared `NodeHeader`; `index.css` |
| Icon set + llm-provider resolver | `web/src/utils/format.ts` (replace `kindGlyph` emoji map with an icon map + `providerFromModel`); vendor SVGs → `web/src/assets/icons/` |
| Color palette (soften) | `web/src/utils/format.ts` → `KIND_COLORS`; `web/src/index.css` `:root` vars |
| Node sizing (header is taller now) | `web/src/graph/flow.ts` → size constants (`HEADER_HEIGHT`, `COMPACT_HEIGHT`) + `leafSize()` |
| Default density → beautiful | `web/src/views/GraphView.tsx` → `useState<Density>("compact")` |
| Spacing / (later) ELK routing | `web/src/graph/layout.ts` → `layeredOptions` |
| Favicon | copy `pflow-cloud/public/favicon.ico` → `web/public/favicon.ico`; ref in `web/index.html` |
| Branch labels (n8n look) | `web/src/components/nodes/BranchPorts.tsx` + `index.css` |

**Invariants you must not break** (from `web/CLAUDE.md` + `handles.ts`):
- **Handle-type invariant.** Every `sourceHandle` id must resolve to `"source"`, every
  `targetHandle` to `"target"` (`handles.ts::handleType`), or React Flow **silently drops the edge**.
  Gradient/dashed changes are pure *styling* — they touch `style`/`className`/edge `type`, NOT
  handles — so the invariant test (`flow.test.ts`) stays valid. Don't change handle ids.
- **Additive edges.** A hidden/re-anchored endpoint degrades to a node-level handle, never dropped
  (`renderAnchor` in flow.ts). Styling doesn't touch this.
- `graph/` is React-free (pure transform, node-env tests). Edge/node **components** live in
  `components/`. Keep the gradient *component* in `components/edges/`, the color *computation* in
  `graph/flow.ts`.

**Our current edge data shape** (`flow.ts` `EdgeData`): `{ kind, shadowed, from, to, loop? }`.
→ Phase A adds `sourceColor: string; targetColor: string`.

**Our current handle scheme** (`handles.ts`, unchanged): `NODE_IN="__in"`(t)/`NODE_OUT="__out"`(s);
prefixes `p:`(param,t) `o:`(output,s) `b:`(branch,s) `io:`(port source) `iot:`(port target).

---

## 3. Gradient edges — THE core technique

This is the headline of the whole redesign. ~40 lines. Two viable approaches; **we use
`userSpaceOnUse`** (Flowise uses the other; ours is strictly more correct for our re-anchored/backward
edges).

### 3.1 The two SVG gradient coordinate systems (the crux)

A `<linearGradient>` can position itself two ways:

- **`objectBoundingBox`** (SVG default): gradient spans 0%→100% of the *path's bounding box*,
  left-to-right. **Flowise uses this.** Problem: a perfectly horizontal or vertical edge has a
  **zero-area bounding box** → the gradient degenerates and **doesn't render** ("edge invisible until
  you drag a node" — this is xyflow issue **#4822**). Flowise works around it with a hack (§3.3).
  Also: it always blends left→right of the bbox, so a **backward edge** (target left of source) blends
  *reversed* vs. true source→target.
- **`userSpaceOnUse`**: gradient is positioned by explicit `x1,y1,x2,y2` **in the same coordinate
  space as the path**. Set them to the edge's actual `sourceX,sourceY → targetX,targetY` and the
  blend **follows true edge direction** in any orientation, and there is **no degenerate-bbox bug**.
  This is the right choice for us (we have backward/re-anchored edges; we want source→target to mean
  source→target). **Recommended.**

> Why `userSpaceOnUse` "just works" inside React Flow: RF renders every edge `<path>` inside one
> viewport-transformed `<g>`; the path `d` is in flow coordinates (pre-zoom). A `userSpaceOnUse`
> gradient with `x1..y1` in those same flow coordinates shares the path's coordinate system, so they
> align under pan/zoom automatically. Unique `id` per edge avoids cross-edge collisions.

### 3.2 OUR implementation (`@xyflow/react` v12 + TS) — copy this

`web/src/components/edges/GradientEdge.tsx`:

```tsx
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";
import type { FlowEdge } from "../../graph/flow";

// A smooth bezier edge whose stroke blends sourceColor -> targetColor along the TRUE
// edge direction (userSpaceOnUse). No straight-line hack needed (that bug is an
// objectBoundingBox-only artifact). Pure styling: handles/anchoring are untouched.
export function GradientEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  markerEnd, data, selected, label,
}: EdgeProps<FlowEdge>): JSX.Element {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });
  const gid = `grad-${id}`;
  const from = data?.sourceColor ?? "var(--accent)";
  const to = data?.targetColor ?? "var(--accent)";
  return (
    <>
      <defs>
        <linearGradient
          id={gid}
          gradientUnits="userSpaceOnUse"
          x1={sourceX} y1={sourceY} x2={targetX} y2={targetY}
        >
          <stop offset="0%" stopColor={from} />
          <stop offset="100%" stopColor={to} />
        </linearGradient>
      </defs>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        // interactionWidth (default 20) gives a wide invisible hit-path automatically
        // in v12 — no need for Flowise's manual transparent "selector" path.
        style={{ stroke: `url(#${gid})`, strokeWidth: selected ? 3 : 2 }}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="edge-label nodrag nopan"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
```

Register it (`web/src/components/edges/index.ts`):

```ts
import type { EdgeTypes } from "@xyflow/react";
import { LoopEdge } from "./LoopEdge";
import { GradientEdge } from "./GradientEdge";

export const edgeTypes: EdgeTypes = {
  loop: LoopEdge,
  gradient: GradientEdge, // sequential + branch (control flow) use this
};
```

Wire the colors in `flow.ts` `toFlowEdge()` — we already compute `sourceColor` there
(`kindColor(nodeById.get(e.source)?.kind)`). Add the target color and stop emitting inline
`style.stroke`; instead set `type:"gradient"` for control edges and pass both colors in `data`:

```ts
// inside toFlowEdge(...)
const targetColor = kindColor(nodeById.get(edge.target)?.kind ?? "");
// control-flow edges (sequential/branch) get the gradient custom edge:
const isControl = edge.kind === "sequential" || edge.kind === "branch";
return {
  id: edge.id, source, target, sourceHandle, targetHandle,
  type: isControl ? "gradient" : "default",           // data/error/end keep CSS-colored default
  label, className: classes.join(" "),
  data: { kind: edge.kind, shadowed: edge.shadowed, from: edge.source, to: edge.target,
          sourceColor, targetColor },                  // NEW fields on EdgeData
  markerEnd: isData ? undefined : { type: MarkerType.ArrowClosed, color: targetColor },
};
```

> **Marker color:** an SVG `marker` (arrowhead) **cannot** use the gradient `url(#…)` reliably
> across browsers — give the arrowhead a **solid** color. Use the **target** color (the edge arrives
> at the target, so its head matching the target node reads best). Flowise actually omits arrowheads
> on gradient edges entirely; arrowhead-with-target-color is our call — both are fine.

### 3.3 Flowise's version (reference — the `objectBoundingBox` + 0.0001 hack)

`packages/ui/src/views/agentflowsv2/AgentFlowEdge.jsx` (v11), trimmed to the essence:

```jsx
const xEqual = sourceX === targetX
const yEqual = sourceY === targetY
const [edgePath, edgeCenterX, edgeCenterY] = getBezierPath({
  // the hack: nudge a perfectly-straight line so its bbox isn't zero-area,
  // otherwise the objectBoundingBox gradient won't render (issue #4822)
  sourceX: xEqual ? sourceX + 0.0001 : sourceX,
  sourceY: yEqual ? sourceY + 0.0001 : sourceY,
  sourcePosition, targetX, targetY, targetPosition,
})
const gradientId = `edge-gradient-${id}`
return (
  <>
    <defs>
      <linearGradient id={gradientId}>   {/* default objectBoundingBox, 0%->100% L→R */}
        <stop offset="0%"   stopColor={data?.sourceColor || '#ae53ba'} />
        <stop offset="100%" stopColor={data?.targetColor || '#2a8af6'} />
      </linearGradient>
    </defs>
    {/* wide transparent path for hover/click hit area (v12 gives us interactionWidth instead) */}
    <path className="agent-flow-edge-selector"
          style={{ stroke:'transparent', strokeWidth:15, fill:'none', cursor:'pointer' }} d={edgePath}/>
    {/* the visible gradient path */}
    <path className="agent-flow-edge"
          style={{ strokeWidth: selected?3:2, stroke:`url(#${gradientId})`,
                   opacity: selected?1:0.75, fill:'none' }}
          d={edgePath} markerEnd={markerEnd}/>
  </>
)
```

Notes: their signature default gradient is **`#ae53ba` (purple) → `#2a8af6` (blue)**. They keep edges
at **opacity 0.75**, full on select. Hover is CSS-only via the sibling selector path:

```css
.agent-flow-edge-selector:hover + .agent-flow-edge { stroke-width: 3 !important; opacity: 1; }
```

**[BORROW]** the gradient idea + the opacity-0.75/full-on-select polish + CSS hover.
**[SKIP]** the 0.0001 hack (unnecessary with `userSpaceOnUse`), the manual selector path (v12's
`interactionWidth`), and the foreignObject delete-button (editing-only).

---

## 4. Node card redesign (Option B) — the shared header

### 4.1 Anatomy (what every node shows)

```
┌─────────────────────────────────────────┐
│ ┌──────┐  HTTP REQUEST   ← category (kind), small, in kindColor
│ │ icon │  Fetch the image ← purpose (bold) || node_id fallback   [badges]
│ └──────┘     ↑ neutral dark tile, icon in NATIVE color (Option B)
├─────────────────────────────────────────┤  ← body: ADVANCED density only
│  p:url     ${repo}/img.png               │  param rows (left target handle per row)
│  p:method  GET                           │
│              → stdout  ●                  │  output fields (right source handle)
└─────────────────────────────────────────┘
   ▌ left border accent = kindColor
```

- **Beautiful** = header only (+ branch rows if a decision, + loop arc). **Advanced** = header + body.
- **Left accent** (`border-left: 3px solid var(--kind)`) — already present, keep.
- **Category line** = `node.kind` (uppercased, in `kindColor`). The model/provider could later be
  shown as a sub-pill (§8.4) but Phase A just shows the kind.
- **Title** = `node.purpose || node.ref.node_id` (bold). Today the title is `node_id`; switch to
  `purpose` (n8n shows the human description). `node_id` still available in read panel + tooltip.

### 4.2 Shared header component (extract from Detailed/Compact)

```tsx
// web/src/components/nodes/NodeHeader.tsx
import type { CSSProperties } from "react";
import type { RFNode } from "../../types";
import { kindColor, categoryLabel } from "../../utils/format";
import { NodeIcon } from "./NodeIcon";
import { NodeBadges } from "./Badges";

export function NodeHeader({ node, maxBadges }: { node: RFNode; maxBadges?: number }): JSX.Element {
  const style = { "--kind": kindColor(node.kind) } as CSSProperties;
  return (
    <div className="node-header" style={style}>
      <div className="node-tile">           {/* neutral tile; icon native color */}
        <NodeIcon node={node} />
      </div>
      <div className="node-titles">
        <span className="node-category">{categoryLabel(node)}</span>
        <span className="node-name" title={node.ref.node_id}>
          {node.purpose || node.ref.node_id}
        </span>
      </div>
      <NodeBadges node={node} max={maxBadges} />
    </div>
  );
}
```

`DetailedNode` = `<NodeHeader/>` + the existing `.param-rows`/output/`BranchPorts` body.
`CompactNode` = `<NodeHeader maxBadges={1}/>` + `BranchPorts` (branches show in both densities).

### 4.3 CSS for the tile (Option B — neutral + native-color icon)

```css
.node-header { display:flex; align-items:center; gap:10px; padding:8px 10px; }
.node-tile {
  flex: 0 0 auto; width: 34px; height: 34px; border-radius: 9px;
  display: grid; place-items: center;
  background: var(--bg-node-header);                 /* neutral dark, NOT --kind */
  border: 1px solid color-mix(in srgb, var(--kind) 45%, transparent);
  box-shadow: 0 0 0 1px rgba(0,0,0,0.2) inset;
}
.node-tile .node-icon-img { width: 20px; height: 20px; object-fit: contain; }
.node-category {
  font-family: var(--mono); font-size: 10px; letter-spacing: .04em; text-transform: uppercase;
  color: var(--kind);                                /* category in the kind color */
}
.node-name { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.node-titles { display: flex; flex-direction: column; min-width: 0; gap: 1px; }
```

> **Why neutral tile, not solid (Flowise uses solid `data.color` for its monochrome tabler icons).**
> Our icons are brand SVGs in their own colors (python, claude, bash-white). A solid `--kind` tile
> would clash with a multicolor logo and force white-flattening. Neutral tile + native icon + a
> `--kind` *tinted border* keeps the type-color language without recoloring the art — this is exactly
> the n8n treatment in the user's #4/#5 references. (Flowise itself falls back to a *white circle +
> brand `<img>`* for integration nodes that lack a tabler icon — same instinct.)

### 4.4 Sizing impact (feeds ELK)

The header is taller/wider than today's compact card. Update size constants in `flow.ts` so ELK
boxes match the rendered DOM (mismatch → overlaps/gaps):
- `COMPACT_WIDTH` ~230, `COMPACT_HEIGHT` ~52 (header only).
- Advanced: `HEADER_HEIGHT` ~52; rows stay `ROW_HEIGHT` 26.
- Branch rows add `branchLabels.length * ROW_HEIGHT` in **both** densities (already handled in
  `leafSize`). Re-measure once after first render and tune.

---

## 5. Icons + the LLM-provider resolver

### 5.1 Assets (vendored from `pflow-cloud/public/`)

Copy into `web/src/assets/icons/` (Vite bundles `.svg` URL imports → wheel). Available + gaps:

| kind | source SVG | status |
|---|---|---|
| shell | `tools/Bash_dark.svg` | white monochrome ✓ |
| mcp | `logos/Model Context Protocol_dark.svg` | ✓ |
| python | `logos/icons/python.svg` | brand color ✓ |
| code | python.svg (placeholder, user's call) | ✓ reuse |
| claude-code | `logos/agents/claude-ai-icon.svg` | brand orange ✓ |
| workflow | `logos/icons/workflow/markdown-dark.svg` | placeholder (swappable) |
| **llm** | provider-resolved (see 5.2), default `logos/icons/ai-llm.svg` | sparkle ✓ |
| **http** | — | **generic placeholder** for now |
| **file** | — | **generic placeholder** for now |

`input`/`output` are the **ports table-node** (no tile); `end` is the small sink circle (no tile).
Favicon: `pflow-cloud/public/favicon.ico` → `web/public/favicon.ico`.

> Vite tip: `import bash from "../assets/icons/bash.svg";` yields a URL string by default → render
> `<img src={bash}/>` (preserves brand colors). Don't inline via svgr unless you need `currentColor`
> recoloring (we don't, for Option B).

### 5.2 LLM provider → icon (verified: model is `provider/model`)

Real example workflows write LiteLLM strings: `anthropic/claude-opus-4.5`, `gemini/gemini-2.5-flash`,
`openai/gpt-5.2`. So `model.split("/")[0]` is the provider — no fuzzy matching. The contract already
ships `node.params` inline, so this is free (no contract change). Mirrors what Flowise does (it shows
a per-model provider badge via `node-icon/${item.model}`) and its `llm` icon is literally `IconSparkles`.

```ts
// web/src/utils/format.ts
import sparkle from "../assets/icons/ai-llm.svg";
import anthropic from "../assets/icons/anthropic.svg";
import openai from "../assets/icons/openai.svg";
import gemini from "../assets/icons/gemini.svg";
import ollama from "../assets/icons/ollama.svg";
import bash from "../assets/icons/bash.svg";
import mcp from "../assets/icons/mcp.svg";
import python from "../assets/icons/python.svg";
import claude from "../assets/icons/claude.svg";
import workflow from "../assets/icons/markdown.svg";
import placeholder from "../assets/icons/placeholder.svg";
import type { RFNode } from "../types";

const PROVIDER_ICON: Record<string, string> = { anthropic, openai, gemini, ollama };
const KIND_ICON: Record<string, string> = {
  shell: bash, mcp, python, code: python, "claude-code": claude, workflow,
  http: placeholder, file: placeholder, // TODO real icons
};

export function iconFor(node: RFNode): string {
  if (node.kind === "llm") {
    const model = node.params.find((p) => p.name === "model")?.value;
    if (typeof model === "string") {
      const provider = model.split("/")[0]?.toLowerCase();
      if (provider && PROVIDER_ICON[provider]) return PROVIDER_ICON[provider];
    }
    return sparkle; // dynamic ${ref} model, missing, or unknown provider
  }
  return KIND_ICON[node.kind] ?? placeholder;
}

// category line text, e.g. "HTTP" / "LLM" / "SHELL". Tune to taste / Title Case.
export function categoryLabel(node: RFNode): string {
  return node.kind.replace("-", " ").toUpperCase();
}
```

```tsx
// web/src/components/nodes/NodeIcon.tsx
import { iconFor } from "../../utils/format";
import type { RFNode } from "../../types";
export function NodeIcon({ node }: { node: RFNode }): JSX.Element {
  return <img className="node-icon-img" src={iconFor(node)} alt={node.kind} />;
}
```

> **Edge cases for the llm resolver:** `model` may be (a) a `${ref}` → string contains `${`, split
> gives e.g. `"${cfg.model}"` → provider `"${cfg.model}"` not in map → sparkle ✓; (b) absent (uses
> a configured default) → sparkle ✓; (c) provider with no icon (`mistral/…`, `groq/…`) → sparkle ✓;
> (d) a bare model with no slash (`"gpt-4o"`) → provider = whole string, not in map → sparkle (we
> deliberately don't infer; add heuristics later if needed).

### 5.3 Future (logged, not Phase A): provider/tool badges

Flowise renders a little pill **inside the node** with the provider icon + model name (and tool
icons) — `AgentFlowNode.jsx` lines ~440–656. This is the natural "show the actual model/tool on the
node" enhancement. For an `mcp` node it'd show the specific server (slack/github/…). Needs the
contract to carry the resolved tool/provider; defer.

---

## 6. Color palette (soften — addresses the "harsh neon green")

Flowise's `AGENTFLOW_ICONS` palette is **soft/pastel**, which is the look the user wants and validates
the "neon green is too harsh" note. Reference (name → color → icon):

```
condition #FFB938 split   start #7EE787 play   llm #64B5F6 sparkles   agent #4DD0E1 robot
humanInput #6E6EFD user   loop #FFA07A repeat  directReply #4DDBBB    customFn #E4B7FF
tool #d4a373              retriever #b8bedd     conditionAgent #ff8fab stickyNote #fee440
http #FF7F7F world        iteration #9C89B8     executeFlow #a3b18a
```

Our current `KIND_COLORS` (`format.ts`) vs a **proposed softened** set (tune live with the user —
this is a low-stakes knob, don't over-commit):

| kind | current | proposed (softer) | note |
|---|---|---|---|
| shell | `#34d399` (harsh) | `#7EE787` | Flowise start-green; calmer |
| http | `#38bdf8` | `#7FB4F5` | softer sky (or `#FF7F7F` Flowise coral — user pick) |
| llm | `#a78bfa` | `#8FA6F0` / keep violet | keep distinct from http |
| claude-code | `#818cf8` | `#9C89B8` | soft indigo/purple |
| code/python | `#fbbf24` | `#FFD479` | softer amber |
| file | `#2dd4bf` | `#5EC8B0` | calmer teal |
| mcp | `#f472b6` | `#FF8FAB` | Flowise pink |
| workflow | `#60a5fa` | `#A3B18A` | sage (distinct from http) |
| input | `#94a3b8` | keep | ports header only |
| output | `#fb7185` | `#FF9EAA` | softer |
| end | `#6b7280` | keep | faint |

CSS vars to retune in `index.css :root`:
- `--data-edge` / `--ref`: `#8be9c0` → **`#6FBFA8`** (calmer teal-green) or **`#7FB3A3`** (muted sage).
  Keep distinct from `--batch #c79bf0` (purple) and llm violet. **Do NOT use purple for data-flow**
  (collides). Present 2–3 swatches to the user and pick on canvas.
- Consider lowering edge `opacity` to ~0.85 (Flowise uses 0.75) so the canvas reads calmer.

---

## 7. Edge semantics — solid / dashed / colored

Decided mapping (the reference tools dash conditionals; we keep data-flow dashed-green):

| edge kind | stroke | dash | hidden in beautiful? |
|---|---|---|---|
| `sequential` | **gradient** (source→target), width 2 | solid | no (control skeleton) |
| `branch` | **gradient** (or source color), width 2 | **dashed** (`6 4`) | no |
| `data_flow` | `--data-edge` (softened green) | dashed (`4 3`) | **yes**, revealed on focus |
| `error` | `--danger` red | solid | no |
| `end` | `--text-faint` | dashed (`2 3`) | no |
| `loop` | amber arc (`LoopEdge`, existing) | solid | no |

CSS (`index.css`):
```css
.react-flow__edge .react-flow__edge-path { stroke-width: 2; }
.react-flow__edge.edge-branch    .react-flow__edge-path { stroke-dasharray: 6 4; }
.react-flow__edge.edge-data_flow .react-flow__edge-path { stroke: var(--data-edge); stroke-dasharray: 4 3; }
.react-flow__edge.edge-error     .react-flow__edge-path { stroke: var(--danger); }
.react-flow__edge.edge-end       .react-flow__edge-path { stroke: var(--text-faint); stroke-dasharray: 2 3; }
.react-flow__edge.edge-shadowed  .react-flow__edge-path { opacity: .35; }   /* advanced only */
```
Gradient edges set `stroke` via the custom edge (`url(#grad-…)`), so don't also set it in CSS for
`edge-sequential`/`edge-branch` — CSS would override the gradient. Keep CSS strokes only for the
non-gradient kinds (data/error/end).

---

## 8. Flowise AgentFlowNode teardown (full reference)

`packages/ui/src/views/agentflowsv2/AgentFlowNode.jsx` (711 lines). What's worth knowing:

### 8.1 Card sizing & color
- `width: 'max-content'`, `height: 'auto'` — content-sized (they drag; we can't — ELK needs fixed
  sizes, so we **estimate** in `leafSize`). **[SKIP]** content-sizing.
- Card **background** = a faint tint of the node color: `darken(nodeColor, 0.8)` (dark mode) /
  `lighten(nodeColor, 0.9)` (light). **[BORROW lightly]** — a very subtle `--kind` tint on the card
  bg reads richer than flat `--bg-node`. Use `color-mix(in srgb, var(--kind) 8%, var(--bg-node))`.
- **Border** = state-driven opacity of the node color: `alpha(color, 0.5)` rest, `0.8` hover, full
  on select (`getStateColor`). **[BORROW]** maps cleanly to our dimmed/focused states.

### 8.2 The icon tile (the Option-A vs B fork, in their code)
```jsx
{data.color && !data.icon ? (
  // colored rounded-square tile + white tabler icon (Option A)
  <div style={{ borderRadius:'15px', backgroundColor:data.color, ... }}>{renderIcon(data)}</div>
) : (
  // white circle + brand <img> (their integration-node fallback ≈ our Option B spirit)
  <div style={{ borderRadius:'50%', backgroundColor:'white' }}>
    <img src={`${baseURL}/api/v1/node-icon/${data.name}`} .../>
  </div>
)}
```
`renderIcon` looks up `AGENTFLOW_ICONS` by name → `<Icon size={24} color="white"/>`.
**We do Option B for all kinds** (neutral tile, native icon) — simpler + uses brand SVGs as-is.

### 8.3 Handles
- **Input**: a thin vertical bar (5×20) colored `nodeColor` on the left (`left:-2`). Subtle, nice.
- **Output(s)**: `IconCircleChevronRightFilled` (chevron-in-circle) colored `nodeColor`, **multiple**
  stacked vertically via `getAnchorPosition(i) = clientHeight/(n+1)*(i+1)`, **revealed on hover**
  (`opacity: isHovered ? 1 : 0`). This is the **n8n labeled-output** pattern source. **[BORROW]** the
  chevron-circle look + vertical spacing for our `BranchPorts` (§ task Phase B). We already have
  labeled branch handles; this makes them prettier.
- They call `useUpdateNodeInternals(data.id)` after measuring handle positions (needed when handle
  count/position changes post-mount). **Relevant** if we dynamically position branch handles.

### 8.4 Provider/model + tool badges (the future §5.3)
Lines ~440–656: pills with `<img src={node-icon/${model}}/>` + model name; tool icons as small
circles. The "show the provider/tool on the node" pattern. **[Future]**

### 8.5 StickyNote (annotation node — for Phase C)
`StickyNote.jsx`: a node `type:"stickyNote"` that's just a `MainCard` wrapping an editable `Input`,
colored `#fee440` (yellow), same tint/border treatment. For us (read-only) it'd render the
workflow description / `##` section text. **[Future Phase C]** — register a `note` node type, derive
from the contract (would need the renderer to emit description/section text; small contract add).

### 8.6 Canvas wiring (how colors reach the edge)
`Canvas.jsx onConnect`: on edge creation it looks up `sourceColor`/`targetColor` from
`AGENTFLOW_ICONS` by the node name and stores them in `edge.data` (+ `edgeLabel` for condition /
humanInput, + `type:'agentFlow'`). `nodeTypes={{agentFlow, stickyNote, iteration}}`,
`edgeTypes={{agentFlow: AgentFlowEdge}}`, `<ReactFlow fitView minZoom={0.5}
connectionLineComponent={ConnectionLine}/>`. **We do the equivalent in `flow.ts toFlowEdge`** (colors
from `kindColor`), at build time, not on user-connect.

### 8.7 Branch/condition edge labels
`ConnectionLine.jsx` + `onConnect`: condition outputs are labeled by the handle suffix
(`sourceHandle.split('-').pop()` → index); humanInput → `'proceed'`/`'reject'`. Rendered via
`EdgeLabelRenderer`, tiny (0.5rem), bold, colored by source. We already carry branch labels on the
**handle** (`BranchPorts`), which is cleaner than mid-edge labels — keep ours.

---

## 9. Edge routing (Phase D — the hard one, deferred)

Our edges are straight-ish beziers; in dense graphs (the 82-node harness) skip/back edges can cross
nodes. Two real options (Flowise has **none** — it's drag-positioned):

### 9.1 Option D1 — ELK's own orthogonal routing (we already run ELK)
ELK can route edges and return bend points. Set on the layered graph:
```ts
"elk.edgeRouting": "ORTHOGONAL",   // or "SPLINES" | "POLYLINE"
```
After `elk.layout()`, each edge gains `sections: [{ startPoint, endPoint, bendPoints: [{x,y}, …] }]`.
Render a custom edge that builds an SVG path from those points instead of `getBezierPath`.

**Pros:** free-ish (already using ELK); ELK understands our **nested containers** (its strength);
one global routing pass. **Cons/edge-cases:**
- Bend-point coords are **relative to the edge's container node**, not global — you must offset by
  the container's absolute position (same nesting math we already do for node positions in
  `layout.ts`). Getting this wrong puts edges in the wrong place.
- React Flow computes `sourceX/Y`/`targetX/Y` from **handle DOM positions**; ELK's section endpoints
  come from **ELK ports**. They won't match exactly → either (a) snap ELK endpoints to RF handle
  coords (use ELK only for the middle bend points), or (b) drive everything from ELK and ignore RF's
  endpoint math. (a) is less jarring.
- `SPLINES`: bendPoints are **control points**, not corners — interpret as a piecewise cubic spline
  (different path builder). `ORTHOGONAL` bendPoints are literal corners (round them for the smooth
  look).
- Re-layout cost: ELK edge routing adds time; fine for our compute-once model.

### 9.2 Option D2 — `@jalez/react-flow-smart-edge` (A* node avoidance, drop-in)
Maintained v12 fork of `@tisoap/react-flow-smart-edge` (original archived). `npm i
@jalez/react-flow-smart-edge`. Exports `SmartBezierEdge`, `SmartStepEdge`, `SmartStraightEdge`;
register in `edgeTypes`, set `type:'smart'` on edges. Or compose with our gradient via `getSmartEdge`:
```ts
import { getSmartEdge } from "@jalez/react-flow-smart-edge";
const res = getSmartEdge({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, nodes });
if (res === null) return <BezierFallback/>;        // pathfinding failed → fall back
const { svgPathString, edgeCenterX, edgeCenterY } = res;   // stroke svgPathString with our gradient
```
Options: `nodePadding` (default 10), `gridRatio` (default 10; **larger = faster + coarser**).
Pathfinders: `pathfindingAStarDiagonal` (bezier), `pathfindingAStarNoDiagonal` (straight),
`pathfindingJumpPointNoDiagonal` (step).

**Pros:** true node-avoidance, drop-in, composes with gradient. **Cons/edge-cases:**
- **Per-edge A\* over a grid of ALL nodes** → cost scales with node count × edges × (1/gridRatio²).
  The harness (82 nodes, 153 edges) could be heavy; bump `gridRatio` and only apply `smart` to the
  **problem edges** (skip/backward), not every sequential edge.
- It pathfinds around **node bounding boxes** but is **not group-aware** — our collapsible
  containers/ports nodes may be treated as obstacles oddly. Test against a nested workflow.
- Uses `useNodes()` → recomputes on node change; fine for our static layout (compute once).

### 9.3 Recommendation
**Try D1 (ELK orthogonal) first** — we already run ELK and it's container-aware; the main work is the
bend-point→path renderer + coordinate offsetting. Keep **D2 as a targeted fallback** for specific
overlapping edges if D1's look isn't enough. **Defer both until after Phase A** ships — gradients +
softened palette + better spacing often make the overlap far less objectionable, possibly removing
the need.

---

## 10. Animated "flowing" edges (optional flair)

The "agentic" feel is partly **motion**. Three techniques, cheapest→nicest:

1. **React Flow built-in** `animated: true` on an edge → adds class `.animated`, which RF styles with
   marching-ants:
   ```css
   .react-flow__edge.animated path { stroke-dasharray: 5; animation: dashdraw .5s linear infinite; }
   @keyframes dashdraw { from { stroke-dashoffset: 10; } }
   ```
   Cheap, but **stroke-dasharray animation is CPU-heavy at scale** (per route06/Liam ERD: many
   animated SVG paths spike CPU). On a 150-edge harness, **don't animate all edges**.
2. **Animate the gradient** (the glow/flow look) via SMIL on the stops — shift `offset` or colors in
   a loop:
   ```svg
   <linearGradient id="g" gradientUnits="userSpaceOnUse" x1=… x2=…>
     <stop offset="0" stopColor={from}><animate attributeName="offset" values="0;1" dur="2s" repeatCount="indefinite"/></stop>
     <stop offset="1" stopColor={to}/>
   </linearGradient>
   ```
3. **`animateMotion`** — move a small dot/shape *along* the path (xyflow's "Animated SVG Edge"):
   ```tsx
   const [path] = getBezierPath({ ... });
   return (<>
     <BaseEdge id={id} path={path} />
     <circle r={3} fill={data.targetColor}>
       <animateMotion dur="2s" repeatCount="indefinite" path={path} />
     </circle>
   </>);
   ```
   `animateMotion` is **cheaper than dasharray** for many edges and reads as "data flowing."

**Recommendation:** ship Phase A **static** (no animation). If you want the agentic shimmer, add
`animateMotion` dots **only on focus/hover** (reveal the active path), never globally — keeps the
150-edge canvas calm and cheap.

---

## 11. `reactflow` v11 → `@xyflow/react` v12 deltas (porting Flowise snippets)

Flowise is v11; we're v12. When adapting their code:
- Package: `reactflow` → `@xyflow/react`; CSS `reactflow/dist/style.css` → `@xyflow/react/dist/style.css`.
- Node prop `parentNode` → **`parentId`** (we already use `parentId`).
- Same in both: `Handle`, `Position`, `getBezierPath/getSmoothStepPath/getStraightPath`
  (return `[path, labelX, labelY, offsetX, offsetY]`), `EdgeLabelRenderer`, `BaseEdge`,
  `useUpdateNodeInternals`, `MarkerType`, `useStore`, `useNodes`.
- v12 `BaseEdge` + edge `interactionWidth` (default 20) gives the wide invisible hit-path → **skip**
  Flowise's manual transparent "selector" path.
- v12 `EdgeProps` is generic: type ours `EdgeProps<FlowEdge>` (FlowEdge from `graph/flow.ts`).
- v12 typing: `EdgeTypes`/`NodeTypes` maps; keep `edgeTypes`/`nodeTypes` **module-level constants**
  (new object identity each render = React Flow warning + perf hit).

---

## 12. Gotchas & edge cases (consolidated — the expensive-to-rediscover list)

1. **Gradient invisible until node drag** = the `objectBoundingBox` zero-bbox bug (#4822) on
   straight edges. **Use `userSpaceOnUse`** → gone. (Or Flowise's `+0.0001` nudge if you ever use
   objectBoundingBox.)
2. **Arrowheads can't use `url(#gradient)`** reliably — give markers a **solid** color (use the
   target color).
3. **CSS `stroke` overrides the gradient.** For gradient edges, set stroke in the component
   (`url(#…)`), and **don't** also write `.edge-sequential { stroke: … }` in CSS. Keep CSS strokes for
   non-gradient kinds only.
4. **Handle-type invariant is sacred.** Styling never touches handles, so it stays valid — but if you
   add a new handle scheme for branch outputs, register its type in `handles.ts::handleType` or React
   Flow silently drops the edge (the bug that bit the build twice). `flow.test.ts` enforces it; jsdom
   CANNOT (renders no edge DOM).
5. **ELK box sizes must match rendered DOM.** The new taller header changes node heights — update
   `flow.ts` size constants or ELK lays out against stale sizes → overlaps/gaps.
6. **Self-loops are excluded from ELK** (`layout.ts` filters `source===target`) — `LoopEdge` owns the
   path. Any new synthesized self-edge must follow suit.
7. **Nested coordinates.** ELK child positions (and edge bend points, if you use D1) are **relative to
   the parent container**; absolute placement needs the parent offset. We already handle this for
   nodes; replicate for routed edges.
8. **`edgeTypes`/`nodeTypes` must be stable references** (module-level), not inline objects.
9. **`fitView` races async ELK.** A screenshot/measure before ELK + the one-shot `fitView` rAF shows
   an un-fit view — it's a timing artifact, not a bug (measure after settle). Already handled in
   `GraphView` via the `fitKey` rAF.
10. **Vendored SVGs ship via the wheel** only because of the `artifacts` glob in `pyproject.toml` —
    new asset folders under `web/src/assets` are fine (they're bundled by Vite into `static/assets`),
    but the **gitignored** `src/pflow/ui/static/` is force-included by that glob; don't remove it.
11. **Animated dasharray is CPU-heavy at scale** — never animate all 150 harness edges; focus/hover
    only, or `animateMotion`.
12. **Default density flip** (`detailed`→`compact`) changes which edges show by default (beautiful
    hides data-flow). Confirm focus-reveal still works and the toolbar label still reads
    "advanced/beautiful".

---

## 13. Phase A plan (proposed sequencing) + acceptance

1. **Palette + green** (`format.ts KIND_COLORS`, `index.css` vars) — soften, retune `--data-edge`.
   Cheapest visible win; align swatches with the user on canvas.
2. **Icons** — vendor SVGs to `web/src/assets/icons/`, `iconFor` + `providerFromModel`, `NodeIcon`,
   favicon. Replace `kindGlyph` emoji usage.
3. **Shared node header** — extract `NodeHeader` (tile + icon + category + bold purpose); rewire
   `DetailedNode` (header + body) and `CompactNode` (header + branches). Update `leafSize`/constants.
   Flip default density to `compact` in `GraphView`.
4. **Gradient edges** — `GradientEdge.tsx`, register `gradient` type, set `type` + `sourceColor`/
   `targetColor` in `toFlowEdge`, marker = target color. Add `sourceColor/targetColor` to `EdgeData`.
5. **Dashed semantics** — branch dashed, data-flow softened green, opacity ~0.85 (§7 CSS).
6. **Verify:** `npx vitest run` (esp. `flow.test.ts` handle-type invariant — must stay green; it
   asserts properties, not styles, so it should), `tsc --noEmit`, `npm run build`, then **real browser**
   on `conditional-branching` (forks) + the harness (density, gradients, no dropped edges). jsdom
   can't see edges — browser is the only visual proof.

**Acceptance:** matches the n8n references — neutral-tile native-color icons, gradient
control edges, dashed conditionals, softened palette, beautiful default — **with zero contract
change** and **no regression** to the §1 invariants (collapse/focus/LR-TD/read-panel/ports/loop/forks
all still work; `render_react_flow` + its tests untouched; Mermaid goldens irrelevant/untouched).

---

## 14. Sources

- Flowise (cloned, read directly): `FlowiseAI/Flowise` → `packages/ui/src/views/agentflowsv2/`
  (`AgentFlowEdge.jsx`, `AgentFlowNode.jsx`, `Canvas.jsx`, `ConnectionLine.jsx`, `StickyNote.jsx`,
  `index.css`), `store/constant.js` (`AGENTFLOW_ICONS`). License **Apache-2.0** (inspiration clean;
  we write our own).
- xyflow custom edges: https://reactflow.dev/learn/customization/custom-edges
- Gradient render bug: https://github.com/xyflow/xyflow/issues/4822
- Gradient how-to: https://raivaibhav.medium.com/change-react-flow-edge-color-to-gradient-bc303c6845b9
- Smart routing (maintained v12 fork): https://github.com/Jalez/react-flow-smart-edge ·
  original (archived) https://www.npmjs.com/package/@tisoap/react-flow-smart-edge
- ELK edge routing: https://eclipse.dev/elk/reference/options/org-eclipse-elk-edgeRouting.html ·
  layered https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html · elkjs
  https://github.com/kieler/elkjs
- React Flow layouting (ELK/dagre): https://reactflow.dev/learn/layouting/layouting
- Animated edges: https://reactflow.dev/examples/edges/animating-edges ·
  https://reactflow.dev/ui/components/animated-svg-edge · perf
  https://liambx.com/blog/tuning-edge-animations-reactflow-optimal-performance
- Our code (the seams): `web/src/graph/{flow,layout,handles}.ts`, `web/src/components/{nodes,edges}/`,
  `web/src/utils/format.ts`, `web/src/index.css`, `web/src/views/GraphView.tsx`, `web/CLAUDE.md`,
  `src/pflow/ui/CLAUDE.md`, `.taskmaster/tasks/task_168/visualization-requirements.md`.
```
