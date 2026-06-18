# Utils (`web/src/utils/`)

Pure presentation / URL / source helpers — no React, no graph state, node-env testable.
Most are small; the non-obvious behavior is below. Consumed by `components/` (render),
`hooks/` (URL + state), and a couple by `graph/` — noted per module.

> Cross-cutting invariants (the handle/edge contract, geometry-single-sourced, etc.) live in
> `web/CLAUDE.md`; not restated here.

- **`format.ts` — color + text presentation.** `nodeColor(node)` is the SINGLE identity seam:
  a node's card / tile / category AND its edge gradients all route through it (CONDITION
  orange / TRANSFORM cyan aware) — callers must NEVER use raw `kindColor(kind)` for a node's
  identity. `kindColor` is the per-kind palette; `categoryLabel` / `isCondition` / `isTransform`
  the label + pseudo-kind logic. `stripMarkdown` hides markers on canvas lines + `title=`
  tooltips (where formatting can't render) — deliberately MORE conservative than CommonMark:
  no intraword `*`/`_` pairing, so `2*3` / `snake_case` / `*.tmp` globs survive (under-strip
  beats corruption). `paramLanguage` picks a highlight language VALUE-type-first (object →
  json), then kind/name. `parseTemplate` splits `${ref}` segments; `bindingLabel` maps the
  reserved `prompt_cache` input → "cached prefix".
- **`highlight.ts` — THE shiki seam.** Lazy promise-memoized chunk (like ELK), EXCEPT a
  REJECTED load RESETS the memo (a transient 404'd chunk ≠ session-dead highlighting). 5
  grammars (python/bash/json/yaml/markdown); fail-closed to `null` → plain text for unknown
  languages, >50k chars, or any failure. `markRefs(root, highlightRef?, {tealRest})` teals
  every `${ref}` (and bright-marks one selected ref, gated on an exact mark-count match — a
  tokenizer-split ref falls back to plain). Shiki's `<pre>` never renders — its `<code>`
  children go inside the consumer's container so `pre-wrap` keeps governing. Consumed by
  `components/CodeBlock` + `components/SourcePane`.
- **`viewParams.ts` — URL ↔ view state (pure, deep-linkable).** `direction` is NULLABLE
  (absent = AUTO); plus density / `node=` / `focus=` / `collapse=` / `source=` / `watch=`.
  `resolveNodeFlatId` / `resolveEndpointFlatId` resolve a deep-link id to its on-canvas
  representative (a group host → its rendered group, skipping decorator shells via `graph/io`'s
  `shellBatchIds`). `edgeClickAction` is the pure edge-click dispatch (jsdom renders no edge
  DOM, so the dispatch is unit-tested here, not via render). Consumed by `views/GraphView` +
  `hooks/`.
- **`sourceMap.ts` — source ↔ canvas mapping.** `nodeAtLine` = the greatest authored
  `source.line` ≤ the clicked line (ignoring null lines); `breadcrumbFor` / `fileChainFor` walk
  the node's OWN `ancestor_path`, NOT the file's first invocation (a child file invoked from
  two host steps would otherwise crumb to the wrong one); `nodeBlockRange` / `sectionBlockRange`
  give a fence-aware block extent. Consumed by `components/SourcePane`.
- **`panelWidth.ts`** — `clampPanelWidth` / `loadPanelWidth` / `savePanelWidth`: the symmetric
  reserved-budget clamp + localStorage persistence shared by both side panes. Consumed by
  `hooks/usePanelPair`.
- **`icons.ts`** — `iconFor` (node kind / LLM provider → a vendored SVG URL from
  `assets/icons/`, incl. `condition.svg` / `transform.svg`); `groupIconFor` (a container's host
  KIND). Add a node-kind icon here.
- **`batchItems.ts`** — `resolveBatchItems`: substitute `${item.x}` against LITERAL batch items
  for panel display (literal only — a dynamic batch has no static items). Consumed by
  `components/ReadPanel` + `components/BatchItems`.
