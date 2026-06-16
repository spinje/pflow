// The per-workflow canvas: pure presentation + interaction. All data/effect logic
// (fetch -> build -> ELK layout -> focus) lives in useWorkflowGraph; the camera
// (view fits, deep links, chip-navigation follow) in useCameraNavigation; the two
// side panes' widths in usePanelPair. This component owns the view state
// (density/direction/collapse/focus/selection), the React Flow surface, and the
// toolbar/read panel.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  type Node,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { collapsibleGroupIds, initialCollapsed } from "../graph/collapse";
import { consumedReadPaths, ioOwners, rowTouches, type Density, type Direction, type FlowEdge, type FlowNode } from "../graph/flow";
import { remapCollapsed, remapSelection } from "../graph/remap";
import { useCameraNavigation } from "../hooks/useCameraNavigation";
import { usePanelPair } from "../hooks/usePanelPair";
import { useSourceWatch } from "../hooks/useSourceWatch";
import { useWorkflowGraph } from "../hooks/useWorkflowGraph";
import { ApiError, fetchSource } from "../api/client";
import { nodeColor } from "../utils/format";
import { edgeClickAction, readViewParams, writeViewParams } from "../utils/viewParams";
import type { RFEdge, RFGraph, RFNode, SourceFiles } from "../types";
import { EdgePanel } from "../components/EdgePanel";
import { edgeTypes } from "../components/edges";
import { HoverMarksProvider, InteractionProvider, NO_HOVER } from "../components/interaction";
import { IoPanel } from "../components/IoPanel";
import { nodeTypes } from "../components/nodes";
import { PanelResizer } from "../components/PanelResizer";
import { ReadPanel } from "../components/ReadPanel";
import { SourcePane } from "../components/SourcePane";
import { Toolbar } from "../components/Toolbar";

interface GraphViewProps {
  workflow: string;
  onBack: () => void;
}

// MiniMap node fills — REAL color strings, not CSS vars: React Flow paints minimap
// nodes as SVG fill attributes, where var() does not resolve. Leaves take their
// identity color through the nodeColor seam (CONDITION-aware — never raw kindColor);
// groups stay a faint wash so containers read as regions without drowning the leaf
// dots; the root IO cards take a quiet wash of their teal; end stays neutral. The
// dark container/mask styling lives in index.css (.react-flow__minimap*).
function minimapNodeColor(n: FlowNode): string {
  switch (n.type) {
    case "node":
      return nodeColor(n.data.node);
    case "group":
      return "rgba(255, 255, 255, 0.05)";
    case "io":
      return "rgba(111, 191, 168, 0.45)"; // IO_COLOR at minimap strength
    default:
      return "rgba(255, 255, 255, 0.12)"; // end sink
  }
}

export function GraphView(props: GraphViewProps): JSX.Element {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  );
}

function GraphCanvas({ workflow, onBack }: GraphViewProps): JSX.Element {
  // The view (LR/TD, beautiful/advanced, and an optional node to frame) is seeded from
  // the URL so a deep link renders the exact state — and an agent can screenshot it
  // without driving the UI. Toggles write back to the URL (replaceState); `node` is a
  // load-time camera instruction (read once, never written).
  const initialView = useMemo(() => readViewParams(window.location.search), []);
  const [density, setDensity] = useState<Density>(initialView.density);
  const [direction, setDirection] = useState<Direction>(initialView.direction);
  const [sourceOpen, setSourceOpen] = useState<boolean>(initialView.source);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Hover marks a SET of canvas subjects — a panel chip marks its one resolved
  // node, a canvas row marks its edges + their far ends. Pure highlight, no
  // focus / expansion / camera change (user decision 2026-06-11). Own context
  // so only node/edge components re-render on hover.
  const [hovered, setHovered] = useState<ReadonlySet<string>>(NO_HOVER);
  // Marks never outlive an interaction: a click can unmount the hovered source
  // (panel swap, focus-expansion re-layout, collapse) so its mouseleave never
  // fires and the marks would stick. Any focus/selection/structure change wipes
  // them; the next real mouseenter re-marks.
  useEffect(() => setHovered(NO_HOVER), [focus, selectedId, collapsed, density, direction]);

  // The root IO cards' title line: the workflow's display name (basename, no
  // extension — the toolbar keeps the full path).
  const workflowName = useMemo(() => workflow.split("/").pop()?.replace(/\.pflow\.md$/, "") ?? workflow, [workflow]);

  // Live source watch: poll /api/version and bump `reload` when the .pflow.md
  // changes on disk, so the graph re-fetches and rebuilds IN PLACE (no page
  // reload — view state is preserved). On unless `pflow ui --no-watch` opened
  // with watch=0. Detection only; the in-place reaction lives in the hook.
  const [reload, setReload] = useState(0);
  const onSourceChanged = useCallback(() => setReload((n) => n + 1), []);
  useSourceWatch(workflow, initialView.watch, onSourceChanged);

  const { nodes, edges, builtEdgeIds, paintEpoch, onNodesChange, onEdgesChange, status, errors, reloadError, graph } = useWorkflowGraph(
    workflow,
    {
      density,
      direction,
      collapsed,
      focus,
      selected: selectedId,
      workflowName,
    },
    reload,
  );

  // Live reload swaps `graph` for the SAME workflow (App keys GraphView on
  // workflow, so a workflow change remounts). Flat ids are POSITIONAL, so a
  // structural edit re-numbers them — remap the preserved selection/focus/collapse
  // through the stable structural ref BEFORE paint (useLayoutEffect → no one-frame
  // flicker of a wrong selection or an un-collapsed container). An append doesn't
  // renumber, so the remaps are no-ops and React bails out (no extra render).
  const prevGraphRef = useRef<RFGraph | null>(null);
  useLayoutEffect(() => {
    const prev = prevGraphRef.current;
    prevGraphRef.current = graph;
    if (!prev || !graph || prev === graph) return;
    setFocus((f) => remapSelection(prev, graph, f));
    setSelectedId((s) => remapSelection(prev, graph, s));
    setCollapsed((c) => remapCollapsed(prev, graph, c));
  }, [graph]);

  const [sourceFiles, setSourceFiles] = useState<SourceFiles | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  // Re-fetch the source pane on a live reload too (NOT just on workflow change),
  // or the pane shows stale text and its line→node mapping silently resolves
  // against the old file. Mirror the in-place regime: on a reload keep the
  // last-good source on screen (don't blank → no flash; a failed reload keeps it,
  // the canvas's reload banner already signals the invalid edit).
  const sourcePrevWorkflowRef = useRef<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const isReload = sourcePrevWorkflowRef.current === workflow;
    sourcePrevWorkflowRef.current = workflow;
    if (!isReload) {
      setSourceFiles(null);
      setSourceError(null);
    }
    fetchSource(workflow)
      .then((source) => {
        if (cancelled) return;
        setSourceError(null);
        setSourceFiles(source);
      })
      .catch((e: unknown) => {
        if (cancelled || isReload) return; // a failed reload keeps the last-good source
        const message =
          e instanceof ApiError
            ? (e.errors[0]?.message ?? e.errors[0]?.title ?? `Source request failed (${e.status}).`)
            : String(e);
        setSourceError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [workflow, reload]);

  // Mirror a density/direction toggle into the URL (replaceState so flips don't spam
  // the back button), preserving every other param (workflow, node).
  const syncUrl = useCallback((patch: { direction?: Direction; density?: Density; source?: boolean }) => {
    const url = new URL(window.location.href);
    url.search = writeViewParams(window.location.search, patch);
    window.history.replaceState({}, "", url);
  }, []);
  const changeDensity = useCallback((d: Density) => { setDensity(d); syncUrl({ density: d }); }, [syncUrl]);
  const changeDirection = useCallback((d: Direction) => { setDirection(d); syncUrl({ direction: d }); }, [syncUrl]);
  const changeSourceOpen = useCallback((open: boolean) => { setSourceOpen(open); syncUrl({ source: open }); }, [syncUrl]);

  // Read the contract/edges via refs so the interaction callbacks (focusPort,
  // hoverRow) stay stable while focus restyles `nodes`/`edges`.
  const graphRef = useRef(graph);
  graphRef.current = graph;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;

  // Initial collapse state, applied ONCE per workflow when its contract arrives: big
  // workflows open as an overview (everything collapsed), small ones fully expanded;
  // an explicit `collapse=` param overrides, and a node=/focus= deep-link target's
  // ancestor chain stays expanded so the link always shows it (graph/collapse.ts).
  const autoCollapsedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!graph || autoCollapsedFor.current === workflow) return;
    autoCollapsedFor.current = workflow;
    const initial = initialCollapsed(graph, initialView.collapse, [initialView.node, initialView.focus]);
    if (initial.size > 0) setCollapsed(initial);
  }, [graph, workflow, initialView]);

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    // EVERYTHING selects (design D, 2026-06-10; io cards joined 2026-06-11 when
    // they got a panel — the toggle was the canvas's only toggle, and "second
    // click closes" died the same way it did for containers): focus + panel;
    // closing = pane click / panel ✕, like every other node. An io card's
    // beautiful-mode rows still open via focus (expansion IS its focus state).
    setFocus(node.id);
    setSelectedId(node.id);
  }, []);

  const onNodeDoubleClick = useCallback(
    (_: unknown, node: Node) => {
      if (node.type === "group") toggleGroup(node.id);
    },
    [toggleGroup],
  );

  // Edges SELECT on click, like everything else on the canvas (2026-06-10). The
  // three-way dispatch (loop: redirect / io-flow: restyle-only / contract edge →
  // full selection) is pure and tested in viewParams.test.ts — jsdom renders no
  // edge DOM, so it cannot be exercised through clicks here.
  const onEdgeClick = useCallback((_: unknown, edge: FlowEdge) => {
    const action = edgeClickAction(edge);
    setFocus(action.focus);
    setSelectedId(action.selectedId);
  }, []);

  // A selected EDGE id has no `from`/`to` escape hatch through rebuilds: a
  // single-group collapse can re-anchor + dedupe the focused edge's id out of the
  // flow — the focus styling would then match nothing (all-dim canvas) while the
  // panel keeps describing an invisible line. Clear both when that happens.
  // Consult the CURRENT build (builtEdgeIds — synchronous with the focus-derived
  // expansion), never the painted edges: a deep-linked node-level-deduped edge
  // resurfaces in the very build its own focus triggers, while the painted
  // snapshot lags one async layout behind — checking the painted set cancelled
  // the deep link before it could render (review-caught 2026-06-11).
  useEffect(() => {
    if (!focus || !graph || builtEdgeIds.size === 0) return;
    const isEdgeFocus = focus.startsWith("io-flow:") || graph.edges.some((e) => e.id === focus);
    if (isEdgeFocus && !builtEdgeIds.has(focus)) {
      setFocus(null);
      setSelectedId((prev) => (prev === focus ? null : prev));
    }
  }, [focus, graph, builtEdgeIds]);

  const onPaneClick = useCallback(() => {
    setFocus(null);
    setSelectedId(null);
  }, []);

  // Clicking a single IO ROW focuses just that port — its connections reveal, the
  // row highlights. On a ROOT IO card the row ALSO opens the interface panel with
  // its entry marked (card = the whole interface, row = one port, same panel both
  // ways). Nested rows (on group cards) stay focus-only: their owner's panel is
  // the host ReadPanel, and auto-opening it on a row click is a different gesture.
  const ioOwnership = useMemo(() => (graph ? ioOwners(graph) : null), [graph]);
  const interaction = useMemo(
    () => ({
      focusPort: (portId: string) => {
        const owner = ioOwnership?.ports.get(portId);
        const ownerGroup = owner != null ? graphRef.current?.groups.find((g) => g.id === owner) : undefined;
        const isRootWrapper =
          ownerGroup != null &&
          ownerGroup.parent == null &&
          (ownerGroup.kind === "input_wrapper" || ownerGroup.kind === "output_wrapper");
        // A NESTED port with no line in the current view: focusing would dim the
        // whole canvas and reveal nothing — the into-nowhere click (user-caught
        // 2026-06-12; e.g. an output no caller reads, its inner producer edge
        // self-loop-dropped on the collapsed card). Root rows always click — the
        // interface panel is the payoff regardless of lines.
        if (!isRootWrapper) {
          const touched = edgesRef.current.some(
            (e) => e.source === portId || e.target === portId || e.data?.from === portId || e.data?.to === portId,
          );
          if (!touched) return;
        }
        setFocus(portId);
        if (isRootWrapper) setSelectedId(owner!);
      },
      toggleGroup,
      hoverNode: (flatId: string | null) => setHovered(flatId != null ? new Set([flatId]) : NO_HOVER),
      // A hovered row marks its touch set — derived from the FLOW edges (the
      // resolved row landings), read via a ref so the callbacks stay stable.
      hoverRow: (row: { nodeId: string; handles: readonly string[] } | null) =>
        setHovered(row != null ? rowTouches(edgesRef.current, row.nodeId, row.handles) : NO_HOVER),
    }),
    [ioOwnership, toggleGroup],
  );

  // A selected CONTAINER reads as its HOST node — purpose, params (bindings),
  // loop/batch spec, source all live there. Root wrapper groups have no host;
  // they resolve through selectedIoGroup below (the interface panel) instead.
  const selectedNode: RFNode | null = useMemo(() => {
    if (!graph || !selectedId) return null;
    const direct = graph.nodes.find((n) => n.id === selectedId);
    if (direct) return direct;
    const host = graph.groups.find((g) => g.id === selectedId)?.host;
    return host ? (graph.nodes.find((n) => n.id === host) ?? null) : null;
  }, [graph, selectedId]);

  // A selected ROOT IO CARD (its id IS its wrapper group's) reads as the
  // workflow's interface. Third resolution arm, disjoint from the other two by
  // id namespace: wrapper groups never match a node or a contract edge.
  const selectedIoGroup = useMemo(() => {
    if (!graph || !selectedId) return null;
    const g = graph.groups.find((grp) => grp.id === selectedId);
    return g && g.parent == null && (g.kind === "input_wrapper" || g.kind === "output_wrapper") ? g : null;
  }, [graph, selectedId]);

  // A selected EDGE reads as its contract edge (flow edges keep contract ids;
  // synthesized io-flow:/loop: ids never match — by design they have no panel).
  // Mutually exclusive with selectedNode: the id namespaces are disjoint.
  const selectedEdge: RFEdge | null = useMemo(
    () => (graph && selectedId ? (graph.edges.find((e) => e.id === selectedId) ?? null) : null),
    [graph, selectedId],
  );

  const rightPanelOpen = Boolean((graph && (selectedEdge || selectedIoGroup)) || selectedNode);
  // The two panes' widths + drag/reset/persistence/symmetric re-clamp live in
  // the hook (usePanelPair); the pure clamp math stays in utils/panelWidth.ts.
  const { panelWidth, sourceWidth, onPanelResize, onPanelReset, onSourceResize, onSourceReset } =
    usePanelPair(sourceOpen);

  // The currently-rendered flat ids — EdgePanel's chips resolve their contract
  // endpoints against this (a suppressed host → its representative group; an
  // endpoint hidden in a collapsed ancestor → a non-clickable chip).
  const renderedIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);

  // The read panel's "consumed" fact — the SAME computation the canvas rows use
  // (contract edges + the param-text scan), so panel and canvas can never state
  // contradictory facts about a binding (review-caught 2026-06-11).
  const readPaths = useMemo(() => (graph ? consumedReadPaths(graph) : null), [graph]);

  // Camera ownership (fit-on-view-change, the node=/focus= deep links, chip
  // navigation + the paint-deferred follow) lives in useCameraNavigation.
  const clearHover = useCallback(() => setHovered(NO_HOVER), []);
  const { onNavigate } = useCameraNavigation({
    status,
    paintEpoch,
    graph,
    workflow,
    direction,
    initialView,
    ioPorts: ioOwnership?.ports ?? null,
    focus,
    setFocus,
    setSelectedId,
    clearHover,
  });

  // Collapse-all folds every collapsible container and clears focus (the focused
  // node is about to disappear into a box — a ring on a hidden node is meaningless).
  // Expand-all only opens; focus survives.
  const collapsibleIds = useMemo(() => (graph ? collapsibleGroupIds(graph) : []), [graph]);
  const onCollapseAll = useCallback(() => {
    setCollapsed(new Set(collapsibleIds));
    setFocus(null);
    setSelectedId(null);
  }, [collapsibleIds]);
  const onExpandAll = useCallback(() => setCollapsed(new Set()), []);

  const toolbar = (showSourceToggle: boolean): JSX.Element => (
    <Toolbar
      title={workflow}
      density={density}
      direction={direction}
      sourceOpen={sourceOpen}
      showSourceToggle={showSourceToggle}
      groupCount={collapsibleIds.length}
      openCount={collapsibleIds.length - collapsed.size}
      focused={focus !== null}
      onDensity={changeDensity}
      onDirection={changeDirection}
      onSourceOpen={changeSourceOpen}
      onCollapseAll={onCollapseAll}
      onExpandAll={onExpandAll}
      onClearFocus={() => setFocus(null)}
      onBack={onBack}
    />
  );

  if (status === "error") {
    return (
      <div className="graph-view">
        {toolbar(false)}
        <div className="banner error">
          <strong>This workflow could not be rendered.</strong>
          <ul>
            {(errors ?? []).map((entry, i) => (
              <li key={i}>{entry.message ?? entry.title ?? JSON.stringify(entry)}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <InteractionProvider value={interaction}>
      <HoverMarksProvider value={hovered}>
      <div className="graph-view">
        {toolbar(true)}
        <div className="graph-body" style={{ "--panel-w": `${panelWidth}px`, "--source-w": `${sourceWidth}px` } as React.CSSProperties}>
          {sourceOpen && (
            <>
              <SourcePane
                source={sourceFiles}
                sourceError={sourceError}
                graph={graph}
                selectedNode={selectedNode}
                selectedIoKind={selectedIoGroup ? (selectedIoGroup.kind === "input_wrapper" ? "input" : "output") : null}
                renderedIds={renderedIds}
                workflowName={workflowName}
                onNavigate={onNavigate}
              />
              <PanelResizer side="left" onResize={onSourceResize} onReset={onSourceReset} />
            </>
          )}
          <div className="canvas">
          {status === "loading" && <div className="canvas-overlay">Laying out…</div>}
          {status === "empty" && <div className="canvas-overlay">This workflow has no visible structure.</div>}
          {reloadError && (
            // The source changed on disk but the new version is invalid. Keep the
            // last-good canvas interactive; surface the error as a non-blocking
            // strip that clears on the next valid save.
            <div className="reload-banner" role="alert">
              <strong>Source has errors</strong> — showing the last valid version.
              {reloadError[0]?.message ? ` ${reloadError[0].message}` : ""}
            </div>
          )}
          <ReactFlow<FlowNode, FlowEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            zoomOnDoubleClick={false}
            onPaneClick={onPaneClick}
            onEdgeClick={onEdgeClick}
            // RF native selection stays inert: applyFocus-written data.selected is
            // the single styling truth, and Backspace must never delete a selected
            // element from the store (useEdgesState applies remove changes).
            deleteKeyCode={null}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            minZoom={0.1}
            proOptions={{ hideAttribution: false }}
          >
            <Background bgColor="#0D0D0D" color="#272727" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor={minimapNodeColor} nodeStrokeColor="transparent" nodeBorderRadius={3} />
          </ReactFlow>
          </div>
          {rightPanelOpen && (
            <PanelResizer onResize={onPanelResize} onReset={onPanelReset} />
          )}
          {graph && selectedEdge && (
            <EdgePanel
              edge={selectedEdge}
              graph={graph}
              renderedIds={renderedIds}
              onNavigate={onNavigate}
              onClose={() => setSelectedId(null)}
            />
          )}
          {graph && selectedIoGroup && (
            <IoPanel
              group={selectedIoGroup}
              graph={graph}
              workflowName={workflowName}
              renderedIds={renderedIds}
              markedPortId={focus != null && selectedIoGroup.members.includes(focus) ? focus : null}
              onNavigate={onNavigate}
              onClose={() => setSelectedId(null)}
            />
          )}
          {selectedNode && (
            <ReadPanel
              node={selectedNode}
              branches={
                // The outcome table: branch edges, plus a decision's END edge
                // (its "end" stop arm — carries the extracted condition too).
                graph?.edges.filter(
                  (e) =>
                    e.source === selectedNode.id &&
                    (e.kind === "branch" || (e.kind === "end" && selectedNode.is_decision)),
                ) ?? []
              }
              reads={
                // What downstream actually READS from this node, full-depth —
                // edges AND plain-param refs, via the same scan the canvas rows
                // consume (consumedReadPaths). The canvas lands on the first
                // path segment (D7); the panel shows the whole dotted path.
                readPaths?.get(selectedNode.id) ?? []
              }
              graph={graph}
              renderedIds={renderedIds}
              onNavigate={onNavigate}
              onClose={() => setSelectedId(null)}
            />
          )}
        </div>
      </div>
      </HoverMarksProvider>
    </InteractionProvider>
  );
}
