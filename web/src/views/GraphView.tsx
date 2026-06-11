// The per-workflow canvas: pure presentation + interaction. All data/effect logic
// (fetch -> build -> ELK layout -> focus) lives in useWorkflowGraph; this component
// owns the view state (density/direction/collapse/focus/selection), the React Flow
// surface, and the toolbar/read panel.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  type Node,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { collapsibleGroupIds, initialCollapsed } from "../graph/collapse";
import type { Density, Direction, FlowEdge, FlowNode } from "../graph/flow";
import { useWorkflowGraph } from "../hooks/useWorkflowGraph";
import { nodeColor } from "../utils/format";
import { edgeClickAction, readViewParams, resolveNodeFlatId, writeViewParams } from "../utils/viewParams";
import type { RFEdge, RFNode } from "../types";
import { EdgePanel } from "../components/EdgePanel";
import { edgeTypes } from "../components/edges";
import { InteractionProvider } from "../components/interaction";
import { nodeTypes } from "../components/nodes";
import { ReadPanel } from "../components/ReadPanel";
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
  const nodeParam = initialView.node;
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // The root IO cards' title line: the workflow's display name (basename, no
  // extension — the toolbar keeps the full path).
  const workflowName = useMemo(() => workflow.split("/").pop()?.replace(/\.pflow\.md$/, "") ?? workflow, [workflow]);

  const { nodes, edges, onNodesChange, onEdgesChange, status, errors, graph } = useWorkflowGraph(workflow, {
    density,
    direction,
    collapsed,
    focus,
    workflowName,
  });

  const { fitView, getNodes } = useReactFlow();
  const nodesInitialized = useNodesInitialized();

  // Mirror a density/direction toggle into the URL (replaceState so flips don't spam
  // the back button), preserving every other param (workflow, node).
  const syncUrl = useCallback((patch: { direction?: Direction; density?: Density }) => {
    const url = new URL(window.location.href);
    url.search = writeViewParams(window.location.search, patch);
    window.history.replaceState({}, "", url);
  }, []);
  const changeDensity = useCallback((d: Density) => { setDensity(d); syncUrl({ density: d }); }, [syncUrl]);
  const changeDirection = useCallback((d: Direction) => { setDirection(d); syncUrl({ direction: d }); }, [syncUrl]);

  // Read the contract via a ref so the fit effect doesn't re-run (and cancel its rAF)
  // when focus restyles `nodes` — it must fire only on workflow/direction/node.
  const graphRef = useRef(graph);
  graphRef.current = graph;

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

  // Apply a focus= deep link once the graph is rendered — the exact state a click
  // produces (dim + reveal + beautiful expansion), resolved like node= (node_id
  // first, flat id fallback). Read-once: later clicks own the focus from there.
  const focusParam = initialView.focus;
  const focusParamApplied = useRef(false);
  useEffect(() => {
    // Wait for React Flow to have MEASURED nodes (same race as the fit effect):
    // at status "ready" the store can still be empty, which would resolve to null
    // and burn the one-shot flag.
    if (focusParamApplied.current || !focusParam || status !== "ready" || !nodesInitialized) return;
    focusParamApplied.current = true;
    const rendered = new Set(getNodes().map((n) => n.id));
    const flatId = resolveNodeFlatId(graphRef.current, rendered, focusParam);
    if (flatId) {
      setFocus(flatId);
      setSelectedId(flatId);
      return;
    }
    // Flat EDGE id fallback (the deterministic escape hatch, like node='s flat-id
    // arm): `focus=e12` selects that connection — the screenshot/inspect loop and
    // Task 169 agents can capture an edge-selection state without driving a
    // click. STABLE edge addressing (source→target:input) stays deferred.
    if (graphRef.current?.edges.some((e) => e.id === focusParam)) {
      setFocus(focusParam);
      setSelectedId(focusParam);
    }
  }, [status, focusParam, nodesInitialized, getNodes]);

  // Refit on a new workflow, a direction flip, or a node= deep link (layout shape
  // changes wholesale); keep the user's viewport for collapse/density tweaks. With a
  // resolvable node=, frame just that node (a close-up); else fit the whole graph.
  const fitKey = `${workflow}|${direction}|${nodeParam ?? ""}`;
  const lastFit = useRef<string>("");
  useEffect(() => {
    // Fit only once React Flow has MEASURED the laid-out nodes (real positions + sizes).
    // A raw rAF after "ready" races the layout→store sync, so a single-node fit lands on
    // a stale near-origin position (the whole-graph fit hid it; one node exposes it).
    // useNodesInitialized is RF's "all nodes measured" signal — it re-arms after a
    // re-layout (direction flip); the lastFit guard keeps it to one fit per view.
    if (status !== "ready" || !nodesInitialized) return;
    if (lastFit.current === fitKey) return;
    lastFit.current = fitKey;
    const rendered = new Set(getNodes().map((n) => n.id));
    const flatId = nodeParam ? resolveNodeFlatId(graphRef.current, rendered, nodeParam) : null;
    if (flatId) fitView({ nodes: [{ id: flatId }], padding: 0.5, maxZoom: 1.5, duration: 200 });
    else fitView({ padding: 0.2, duration: 200 });
  }, [status, fitKey, fitView, nodeParam, nodesInitialized, getNodes]);

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    if (node.type === "io") {
      // The root IO card TOGGLES (its focus-expansion IS its open state, so a
      // second click must close it — user-caught 2026-06-10).
      setFocus((prev) => (prev === node.id ? null : node.id));
      setSelectedId((prev) => (prev === node.id ? null : node.id));
      return;
    }
    // Leaves AND containers SELECT (design D, 2026-06-10): a container's body is a
    // node like any other — focus + read panel; expand/collapse moved to the
    // GroupNode corner button (via InteractionContext) and double-click.
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
  useEffect(() => {
    if (!focus || !graph || edges.length === 0) return;
    const isEdgeFocus = focus.startsWith("io-flow:") || graph.edges.some((e) => e.id === focus);
    if (isEdgeFocus && !edges.some((e) => e.id === focus)) {
      setFocus(null);
      setSelectedId((prev) => (prev === focus ? null : prev));
    }
  }, [focus, graph, edges]);

  const onPaneClick = useCallback(() => {
    setFocus(null);
    setSelectedId(null);
  }, []);

  // Clicking a single IO ROW (on a root IO card or a group's row area) focuses just
  // that port — its connections reveal, the row highlights. No read panel (a port
  // has no params).
  const interaction = useMemo(
    () => ({ focusPort: (portId: string) => setFocus(portId), toggleGroup }),
    [toggleGroup],
  );

  // A selected CONTAINER reads as its HOST node — purpose, params (bindings),
  // loop/batch spec, source all live there. Wrapper groups have no host → no
  // panel (the io-card panel stays a parked knob).
  const selectedNode: RFNode | null = useMemo(() => {
    if (!graph || !selectedId) return null;
    const direct = graph.nodes.find((n) => n.id === selectedId);
    if (direct) return direct;
    const host = graph.groups.find((g) => g.id === selectedId)?.host;
    return host ? (graph.nodes.find((n) => n.id === host) ?? null) : null;
  }, [graph, selectedId]);

  // A selected EDGE reads as its contract edge (flow edges keep contract ids;
  // synthesized io-flow:/loop: ids never match — by design they have no panel).
  // Mutually exclusive with selectedNode: the id namespaces are disjoint.
  const selectedEdge: RFEdge | null = useMemo(
    () => (graph && selectedId ? (graph.edges.find((e) => e.id === selectedId) ?? null) : null),
    [graph, selectedId],
  );

  // The currently-rendered flat ids — EdgePanel's chips resolve their contract
  // endpoints against this (a suppressed host → its representative group; an
  // endpoint hidden in a collapsed ancestor → a non-clickable chip).
  const renderedIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);

  // Chip navigation: focus always moves; the panel swaps only when the chip
  // names a selectable subject (an IO-port chip keeps this edge panel open).
  // The camera FOLLOWS (user-caught 2026-06-11): a chip can name a card anywhere
  // on the canvas — selecting it off-screen reads as a dead click. Generous
  // padding + a zoom cap make it "bring into view", not a hard close-up; in
  // beautiful the expansion re-layout that may follow anchors on the same id,
  // so the target stays near where the fit put it.
  const onNavigate = useCallback(
    (focusId: string, selected?: string | null) => {
      setFocus(focusId);
      if (selected !== undefined) setSelectedId(selected);
      if (getNodes().some((n) => n.id === focusId)) {
        fitView({ nodes: [{ id: focusId }], padding: 0.45, maxZoom: 1.2, duration: 300 });
      }
    },
    [fitView, getNodes],
  );

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

  const toolbar = (
    <Toolbar
      title={workflow}
      density={density}
      direction={direction}
      groupCount={collapsibleIds.length}
      openCount={collapsibleIds.length - collapsed.size}
      focused={focus !== null}
      onDensity={changeDensity}
      onDirection={changeDirection}
      onCollapseAll={onCollapseAll}
      onExpandAll={onExpandAll}
      onClearFocus={() => setFocus(null)}
      onBack={onBack}
    />
  );

  if (status === "error") {
    return (
      <div className="graph-view">
        {toolbar}
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
      <div className="graph-view">
        {toolbar}
        <div className="graph-body">
          <div className="canvas">
          {status === "loading" && <div className="canvas-overlay">Laying out…</div>}
          {status === "empty" && <div className="canvas-overlay">This workflow has no visible structure.</div>}
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
          {graph && selectedEdge && (
            <EdgePanel
              edge={selectedEdge}
              graph={graph}
              renderedIds={renderedIds}
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
                // What downstream actually READS from this node, full-depth:
                // the canvas rows land on the first path segment (D7); the
                // panel shows the whole dotted path (`result.a.b`).
                [
                  ...new Set(
                    (graph?.edges ?? [])
                      .filter((e) => e.source === selectedNode.id && e.kind === "data_flow" && e.output_field != null)
                      .map((e) => [e.output_field, ...e.output_path].join(".")),
                  ),
                ]
              }
              onClose={() => setSelectedId(null)}
            />
          )}
        </div>
      </div>
    </InteractionProvider>
  );
}
