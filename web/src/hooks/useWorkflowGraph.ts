// The data pipeline for one workflow, as a hook: fetch the contract -> buildFlow
// (structural React Flow nodes/edges) -> ELK layout (positions) -> applyFocus
// (cheap dim pass) -> React Flow store. Keeping this out of the view component
// leaves GraphView as pure presentation + interaction, and makes the pipeline
// independently testable.
//
// Re-layout triggers (density / direction / collapse) re-run ELK; focus dim/reveal
// does not. EXCEPTION (decided 2026-06-09): in beautiful, focusing a node EXPANDS it
// (and its data-flow endpoints) to the advanced body — that changes node sizes, so it
// re-layouts. To keep the click from feeling like a jump, the viewport is panned so
// the focused node stays exactly where it was on screen (camera anchoring).
// Every failure mode resolves to a visible `status` — a fetch or layout rejection
// becomes "error" (never a permanent "loading" spinner).

import { useEffect, useMemo, useRef, useState } from "react";
import { type OnEdgesChange, type OnNodesChange, useEdgesState, useNodesState, useReactFlow } from "@xyflow/react";

import { ApiError, fetchGraph } from "../api/client";
import { applyFocus, buildFlow, type BuildOptions, expandTargets, type FlowEdge, type FlowNode } from "../graph/flow";
import { layoutGraph } from "../graph/layout";
import type { ApiErrorEntry, RFGraph } from "../types";

export type GraphStatus = "loading" | "ready" | "empty" | "error";

export interface WorkflowGraphView extends Omit<BuildOptions, "expanded"> {
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

// Stable identity: the build memo keys on the expansion set, so the no-expansion
// case (advanced mode, no focus) must not mint a fresh Set per render — that would
// re-run build + ELK on every advanced-mode click.
const EMPTY_EXPANSION: ReadonlySet<string> = new Set();

// A laid-out node's position is relative to its parent (React Flow's parentId
// convention) — walk the chain for the absolute canvas position.
function absolutePosition(nodes: FlowNode[], id: string): { x: number; y: number } | null {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const node = byId.get(id);
  if (!node) return null;
  let { x, y } = node.position;
  let parent = node.parentId;
  while (parent) {
    const p = byId.get(parent);
    if (!p) break;
    x += p.position.x;
    y += p.position.y;
    parent = p.parentId;
  }
  return { x, y };
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
  const { getViewport, setViewport } = useReactFlow();

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

  // Focus-expansion (beautiful only): the focused leaf + its data-flow endpoints
  // render their advanced body, so the revealed lines land on rows. In advanced
  // every body is already visible — the set stays empty so focus stays layout-free.
  const expanded = useMemo(
    () => (graph && density === "compact" ? expandTargets(graph, focus) : EMPTY_EXPANSION),
    [graph, density, focus],
  );

  // 2. Structural build (no positions). Re-runs only on layout-affecting state
  //    (which, in beautiful, includes the focus-derived expansion set).
  const built = useMemo(
    () => (graph ? buildFlow(graph, { density, direction, collapsed, expanded }) : { nodes: [], edges: [] }),
    [graph, density, direction, collapsed, expanded],
  );

  // The last focused node — the anchor for expansion re-layouts. Kept after focus
  // clears so collapsing back is anchored on the same node the user was looking at.
  const anchorRef = useRef<string | null>(null);
  useEffect(() => {
    if (focus) anchorRef.current = focus;
  }, [focus]);
  // The previous layout + the view it was computed for. Anchoring applies only when
  // the SAME view re-laid out because of an expansion change — a workflow/direction/
  // density/collapse change has its own viewport semantics (GraphView's fit effect).
  const lastLayoutRef = useRef<{
    graph: RFGraph;
    density: string;
    direction: string;
    collapsed: ReadonlySet<string>;
    nodes: FlowNode[];
  } | null>(null);
  // A pan computed from the layout delta, applied in the SAME effect that pushes the
  // re-laid nodes to React Flow — so the nodes move and the camera compensates in one
  // paint, and the anchored node never visibly jumps.
  const pendingPanRef = useRef<{ dx: number; dy: number } | null>(null);

  // 3. Client-side ELK layout. Skip while there is no graph (pre-fetch / fetch
  //    error) so an empty layout never clears a fetch error. A layout rejection
  //    surfaces as an error banner instead of hanging on "Laying out…".
  useEffect(() => {
    if (graph === null) return;
    let cancelled = false;
    layoutGraph(built.nodes, built.edges, direction)
      .then((laidOut) => {
        if (cancelled) return;
        const prev = lastLayoutRef.current;
        const anchor = anchorRef.current;
        if (
          prev &&
          anchor &&
          prev.graph === graph &&
          prev.density === density &&
          prev.direction === direction &&
          prev.collapsed === collapsed
        ) {
          const before = absolutePosition(prev.nodes, anchor);
          const after = absolutePosition(laidOut, anchor);
          if (before && after && (before.x !== after.x || before.y !== after.y)) {
            pendingPanRef.current = { dx: after.x - before.x, dy: after.y - before.y };
          }
        }
        lastLayoutRef.current = { graph, density, direction, collapsed, nodes: laidOut };
        setErrors(null); // a successful re-layout clears any stale layout error
        setLaid({ nodes: laidOut, edges: built.edges });
      })
      .catch((e: unknown) => {
        if (!cancelled) setErrors([{ message: `Could not lay out this workflow: ${String(e)}` }]);
      });
    return () => {
      cancelled = true;
    };
  }, [graph, built, direction, density, collapsed]);

  // 4. Focus decoration (cheap, no re-layout) -> React Flow store. Applies any
  //    pending camera-anchoring pan alongside the new node positions.
  useEffect(() => {
    if (laid === null) return;
    const decorated = applyFocus(laid.nodes, laid.edges, focus);
    setNodes(decorated.nodes);
    setEdges(decorated.edges);
    const pan = pendingPanRef.current;
    if (pan) {
      pendingPanRef.current = null;
      const vp = getViewport();
      setViewport({ zoom: vp.zoom, x: vp.x - pan.dx * vp.zoom, y: vp.y - pan.dy * vp.zoom });
    }
  }, [laid, focus, setNodes, setEdges, getViewport, setViewport]);

  const status: GraphStatus = errors
    ? "error"
    : laid === null
      ? "loading"
      : laid.nodes.length === 0
        ? "empty"
        : "ready";

  return { nodes, edges, onNodesChange, onEdgesChange, status, errors, graph };
}
