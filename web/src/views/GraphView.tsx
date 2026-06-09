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

import type { Density, Direction, FlowEdge, FlowNode } from "../graph/flow";
import { useWorkflowGraph } from "../hooks/useWorkflowGraph";
import { readViewParams, resolveNodeFlatId, writeViewParams } from "../utils/viewParams";
import type { RFNode } from "../types";
import { edgeTypes } from "../components/edges";
import { InteractionProvider } from "../components/interaction";
import { nodeTypes } from "../components/nodes";
import { ReadPanel } from "../components/ReadPanel";
import { Toolbar } from "../components/Toolbar";

interface GraphViewProps {
  workflow: string;
  onBack: () => void;
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

  const { nodes, edges, onNodesChange, onEdgesChange, status, errors, graph } = useWorkflowGraph(workflow, {
    density,
    direction,
    collapsed,
    focus,
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

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    if (node.type === "group") {
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(node.id)) next.delete(node.id);
        else next.add(node.id);
        return next;
      });
      return;
    }
    setFocus(node.id);
    setSelectedId(node.id);
  }, []);

  const onPaneClick = useCallback(() => {
    setFocus(null);
    setSelectedId(null);
  }, []);

  // Clicking a single port ROW (inside a ports node) focuses just that port — its
  // connections reveal, the row highlights. No read panel (a port has no params).
  const interaction = useMemo(
    () => ({ focusPort: (portId: string) => setFocus(portId) }),
    [],
  );

  const selectedNode: RFNode | null = useMemo(
    () => graph?.nodes.find((n) => n.id === selectedId) ?? null,
    [graph, selectedId],
  );

  const toolbar = (
    <Toolbar
      title={workflow}
      density={density}
      direction={direction}
      hasCollapsed={collapsed.size > 0}
      focused={focus !== null}
      onDensity={changeDensity}
      onDirection={changeDirection}
      onExpandAll={() => setCollapsed(new Set())}
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
            onPaneClick={onPaneClick}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            minZoom={0.1}
            proOptions={{ hideAttribution: false }}
          >
            <Background bgColor="#0D0D0D" color="#272727" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable />
          </ReactFlow>
          </div>
          {selectedNode && <ReadPanel node={selectedNode} onClose={() => setSelectedId(null)} />}
        </div>
      </div>
    </InteractionProvider>
  );
}
