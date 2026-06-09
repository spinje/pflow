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
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { Density, Direction, FlowEdge, FlowNode } from "../graph/flow";
import { useWorkflowGraph } from "../hooks/useWorkflowGraph";
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
  const [density, setDensity] = useState<Density>("compact"); // beautiful by default
  const [direction, setDirection] = useState<Direction>("LR");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { nodes, edges, onNodesChange, onEdgesChange, status, errors, graph } = useWorkflowGraph(workflow, {
    density,
    direction,
    collapsed,
    focus,
  });

  const { fitView } = useReactFlow();

  // Refit the viewport on a new workflow or a direction flip (layout shape changes
  // wholesale); keep the user's viewport for collapse/density tweaks.
  const fitKey = `${workflow}|${direction}`;
  const lastFit = useRef<string>("");
  useEffect(() => {
    if (status !== "ready") return;
    if (lastFit.current === fitKey) return;
    lastFit.current = fitKey;
    // rAF so React Flow has the new nodes measured before fitting.
    const handle = requestAnimationFrame(() => fitView({ padding: 0.2, duration: 200 }));
    return () => cancelAnimationFrame(handle);
  }, [status, fitKey, fitView]);

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
      onDensity={setDensity}
      onDirection={setDirection}
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
