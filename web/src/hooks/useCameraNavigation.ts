// Camera ownership for the canvas: the fit-on-view-change effect, the one-shot
// focus= deep link, and chip navigation (onNavigate) with its paint-deferred
// camera follow. It calls useReactFlow/useNodesInitialized itself, so it must
// render inside a ReactFlowProvider (GraphView does).

import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef } from "react";
import { useNodesInitialized, useReactFlow } from "@xyflow/react";

import type { Direction } from "../graph/flow";
import type { GraphStatus } from "./useWorkflowGraph";
import { resolveNodeFlatId, type ViewParams } from "../utils/viewParams";
import type { RFGraph } from "../types";

interface CameraNavigationArgs {
  status: GraphStatus;
  /** Bumped by useWorkflowGraph after every COMPLETED paint — the deferred follow's cue. */
  paintEpoch: number;
  graph: RFGraph | null;
  workflow: string;
  direction: Direction;
  /** The URL-seeded view: `node` frames a node on load, `focus` replays a click. Read-once. */
  initialView: ViewParams;
  /** ioOwners(graph).ports — resolves an io-PORT id to the card carrying its row. */
  ioPorts: ReadonlyMap<string, string> | null;
  focus: string | null;
  setFocus: Dispatch<SetStateAction<string | null>>;
  setSelectedId: Dispatch<SetStateAction<string | null>>;
  /** Wipes the hover marks — a navigation can unmount the hovered source. */
  clearHover: () => void;
}

export interface CameraNavigation {
  onNavigate: (focusId: string, selected?: string | null) => void;
}

export function useCameraNavigation({
  status,
  paintEpoch,
  graph,
  workflow,
  direction,
  initialView,
  ioPorts,
  focus,
  setFocus,
  setSelectedId,
  clearHover,
}: CameraNavigationArgs): CameraNavigation {
  const { fitView, getNodes } = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const nodeParam = initialView.node;
  const focusParam = initialView.focus;

  // Read the contract via a ref so the fit effect doesn't re-run (and cancel its rAF)
  // when focus restyles `nodes` — it must fire only on workflow/direction/node.
  const graphRef = useRef(graph);
  graphRef.current = graph;

  // Apply a focus= deep link once the graph is rendered — the exact state a click
  // produces (dim + reveal + beautiful expansion), resolved like node= (node_id
  // first, flat id fallback). Read-once: later clicks own the focus from there.
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
  }, [status, focusParam, nodesInitialized, getNodes, setFocus, setSelectedId]);

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

  // Chip navigation: focus always moves; the panel swaps only when the chip
  // names a selectable subject (an IO-port chip keeps this edge panel open).
  // The camera FOLLOWS (user-caught 2026-06-11): a chip can name a card anywhere
  // on the canvas — selecting it off-screen reads as a dead click. Generous
  // padding + a zoom cap make it "bring into view", not a hard close-up.
  //
  // The follow is DEFERRED to the paint the click produces (user-caught
  // 2026-06-12): in beautiful a focus change re-layouts (expansion), and a fit
  // started at click time glides toward the target's PRE-layout position —
  // first click landed wrong, the second (cached layout, no repaint) landed
  // right. paintEpoch bumps on every completed paint — the advanced restyle
  // path follows just as promptly. A SAME-focus navigate repaints nothing, so
  // it fits immediately (positions are already settled — the old behavior).
  const pendingFollowRef = useRef<string | null>(null);
  useEffect(() => {
    const id = pendingFollowRef.current;
    if (id == null) return;
    pendingFollowRef.current = null;
    if (getNodes().some((n) => n.id === id)) {
      fitView({ nodes: [{ id }], padding: 0.45, maxZoom: 1.2, duration: 300 });
    }
  }, [paintEpoch, fitView, getNodes]);
  const onNavigate = useCallback(
    (focusId: string, selected?: string | null) => {
      // The clicked chip may unmount with the panel swap — its mouseleave never
      // fires, so the hover mark would stick. Clear it here.
      clearHover();
      setFocus(focusId);
      if (selected !== undefined) setSelectedId(selected);
      // An io-PORT chip names a row, not a node — the camera follows the OWNER
      // card carrying that row (a port id is never a rendered node, so without
      // this arm the follow silently skipped and the focus jump read as "nowhere").
      const rendered = new Set(getNodes().map((n) => n.id));
      const owner = ioPorts?.get(focusId);
      const fitId = rendered.has(focusId) ? focusId : owner != null && rendered.has(owner) ? owner : null;
      if (fitId == null) return;
      if (focusId === focus) {
        fitView({ nodes: [{ id: fitId }], padding: 0.45, maxZoom: 1.2, duration: 300 });
      } else {
        pendingFollowRef.current = fitId;
      }
    },
    [fitView, getNodes, ioPorts, focus, setFocus, setSelectedId, clearHover],
  );

  return { onNavigate };
}
