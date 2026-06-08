// The data pipeline for one workflow, as a hook: fetch the contract -> buildFlow
// (structural React Flow nodes/edges) -> ELK layout (positions) -> applyFocus
// (cheap dim pass) -> React Flow store. Keeping this out of the view component
// leaves GraphView as pure presentation + interaction, and makes the pipeline
// independently testable.
//
// Re-layout triggers (density / direction / collapse) re-run ELK; focus and
// selection do not. Every failure mode resolves to a visible `status` — a fetch
// or layout rejection becomes "error" (never a permanent "loading" spinner).

import { useEffect, useMemo, useState } from "react";
import { type OnEdgesChange, type OnNodesChange, useEdgesState, useNodesState } from "@xyflow/react";

import { ApiError, fetchGraph } from "../api/client";
import { applyFocus, buildFlow, type BuildOptions, type FlowEdge, type FlowNode } from "../graph/flow";
import { layoutGraph } from "../graph/layout";
import type { ApiErrorEntry, RFGraph } from "../types";

export type GraphStatus = "loading" | "ready" | "empty" | "error";

export interface WorkflowGraphView extends BuildOptions {
  focus: string | null;
}

export interface WorkflowGraphResult {
  nodes: FlowNode[];
  edges: FlowEdge[];
  onNodesChange: OnNodesChange<FlowNode>;
  onEdgesChange: OnEdgesChange<FlowEdge>;
  status: GraphStatus;
  errors: ApiErrorEntry[] | null;
  graph: RFGraph | null;
}

export function useWorkflowGraph(workflow: string, view: WorkflowGraphView): WorkflowGraphResult {
  const { density, direction, collapsed, focus } = view;

  const [graph, setGraph] = useState<RFGraph | null>(null);
  const [errors, setErrors] = useState<ApiErrorEntry[] | null>(null);
  // Nodes + edges are laid out and stored as ONE paired snapshot from the same
  // build, so the focus pass never decorates new edges against stale node ids.
  const [laid, setLaid] = useState<{ nodes: FlowNode[]; edges: FlowEdge[] } | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);

  // 1. Fetch the contract whenever the workflow changes. Reset derived state.
  useEffect(() => {
    let cancelled = false;
    setGraph(null);
    setErrors(null);
    setLaid(null);
    fetchGraph(workflow)
      .then((g) => {
        if (!cancelled) setGraph(g);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setErrors(e instanceof ApiError ? e.errors : [{ message: String(e) }]);
      });
    return () => {
      cancelled = true;
    };
  }, [workflow]);

  // 2. Structural build (no positions). Re-runs only on layout-affecting state.
  const built = useMemo(
    () => (graph ? buildFlow(graph, { density, direction, collapsed }) : { nodes: [], edges: [] }),
    [graph, density, direction, collapsed],
  );

  // 3. Client-side ELK layout. Skip while there is no graph (pre-fetch / fetch
  //    error) so an empty layout never clears a fetch error. A layout rejection
  //    surfaces as an error banner instead of hanging on "Laying out…".
  useEffect(() => {
    if (graph === null) return;
    let cancelled = false;
    layoutGraph(built.nodes, built.edges, direction)
      .then((laidOut) => {
        if (cancelled) return;
        setErrors(null); // a successful re-layout clears any stale layout error
        setLaid({ nodes: laidOut, edges: built.edges });
      })
      .catch((e: unknown) => {
        if (!cancelled) setErrors([{ message: `Could not lay out this workflow: ${String(e)}` }]);
      });
    return () => {
      cancelled = true;
    };
  }, [graph, built, direction]);

  // 4. Focus decoration (cheap, no re-layout) -> React Flow store.
  useEffect(() => {
    if (laid === null) return;
    const decorated = applyFocus(laid.nodes, laid.edges, focus);
    setNodes(decorated.nodes);
    setEdges(decorated.edges);
  }, [laid, focus, setNodes, setEdges]);

  const status: GraphStatus = errors
    ? "error"
    : laid === null
      ? "loading"
      : laid.nodes.length === 0
        ? "empty"
        : "ready";

  return { nodes, edges, onNodesChange, onEdgesChange, status, errors, graph };
}
