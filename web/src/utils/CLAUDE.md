# Utils (`web/src/utils/`)

Pure presentation, URL, and source helpers; no React or graph state.

- Identity colors/labels → `format.ts:nodeColor`, `categoryLabel`. Card, tile, category and edge
  gradients share `nodeColor`; raw `kindColor` omits decision/transform treatment.
- Canvas/tooltip text → `format.ts:stripMarkdown`. Keep stripping conservative: under-stripping
  is better than corrupting code, snake_case, arithmetic or globs. Param highlighting language
  → `paramLanguage`; template text segments → `parseTemplate`.
- Syntax highlighting → `highlight.ts:highlight`, `markRefs`, `codeChildren`, consumed by
  CodeBlock and SourcePane. Rejected lazy loads reset their memo so a stale chunk URL does not
  disable highlighting for the session. Unsupported, oversized or failed highlighting returns
  plain text; grammars/limits live in this module.
- Selected-reference marks must survive a highlight upgrade: `CodeBlock` compares the exact
  mark count and keeps plain rendering on mismatch. Teal decoration is best effort and has no
  such completeness guarantee. Render Shiki's code children inside the consumer's container;
  nesting its pre would override wrapping.
- URL/view state → `viewParams.ts:readViewParams`, `writeViewParams`. Absent direction means
  auto. `resolveNodeFlatId`/`resolveEndpointFlatId` find rendered representatives, using
  `../graph/io.ts:shellBatchIds` rather than re-deriving shell suppression. `edgeClickAction`
  owns the three-way edge dispatch; its pure tests cover the jsdom edge-DOM gap.
- Source-to-canvas → `sourceMap.ts:nodeAtLine`; fence-aware extents → `nodeBlockRange`,
  `sectionBlockRange`. `breadcrumbFor` follows the selected node's structural ancestry;
  `fileChainFor` is the file-only/no-selection fallback. One file can be invoked by several
  hosts, so file identity cannot replace invocation ancestry for a selection.
- Pane sizing/persistence → `panelWidth.ts:clampPanelWidth`, `loadPanelWidth`, `savePanelWidth`,
  shared by both panes through `../hooks/usePanelPair`.
- Kind/provider SVG lookup → `icons.ts:iconFor`; container host icon → `groupIconFor`.
- Literal batch item display → `batchItems.ts:resolveBatchItems`, shared by ReadPanel/BatchItems.
  Dynamic batches have no static items to substitute.
