// Camera ownership for the canvas: the fit-on-view-change effect, the one-shot
// focus= deep link, and chip navigation (onNavigate) with its paint-deferred
// camera follow. It calls useReactFlow/useNodesInitialized itself, so it must
// render inside a ReactFlowProvider (GraphView does).

import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef } from "react";
import { useNodesInitialized, useReactFlow } from "@xyflow/react";

import type { Direction } from "../graph/flow";
import type { GraphStatus } from "./useWorkflowGraph";
import { resolveEndpointFlatId, resolveNodeFlatId, type ViewParams } from "../utils/viewParams";
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
  /** A `?run=` deep-link opens the run callout, which frames the initial camera on its anchor (Task 175).
   *  Skip the ONE initial whole-graph fit so the two don't fight (later view-change fits are unaffected). */
  suppressInitialFit: boolean;
}

export interface CameraNavigation {
  onNavigate: (focusId: string, selected?: string | null) => void;
  frameTargets: (ids: readonly string[], deferUntilPaint?: boolean) => void;
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
  suppressInitialFit,
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
  // One-shot: the ?run= deep-link skips ONLY the first whole-graph fit (the run callout frames it instead).
  const suppressedInitialFit = useRef(false);
  useEffect(() => {
    // Fit only once React Flow has MEASURED the laid-out nodes (real positions + sizes).
    // A raw rAF after "ready" races the layout→store sync, so a single-node fit lands on
    // a stale near-origin position (the whole-graph fit hid it; one node exposes it).
    // useNodesInitialized is RF's "all nodes measured" signal — it re-arms after a
    // re-layout (direction flip); the lastFit guard keeps it to one fit per view.
    if (status !== "ready" || !nodesInitialized) return;
    if (lastFit.current === fitKey) return;
    lastFit.current = fitKey;
    // A `?run=` deep-link: the run callout frames the initial camera on its anchor, so SKIP this one
    // whole-graph fit (they'd fight and the whole-graph fit — the parent effect — would win, shrinking the
    // box). One-shot via the ref: a later direction flip (new fitKey) re-fits normally. An explicit `?node=`
    // still wins (it asked to frame a node). NOT suppressed without an anchor (then the graph fit is right).
    if (suppressInitialFit && !suppressedInitialFit.current && !nodeParam) {
      suppressedInitialFit.current = true;
      return;
    }
    const rendered = new Set(getNodes().map((n) => n.id));
    const flatId = nodeParam ? resolveNodeFlatId(graphRef.current, rendered, nodeParam) : null;
    if (flatId) fitView({ nodes: [{ id: flatId }], padding: 0.5, maxZoom: 1.5, duration: 200 });
    else fitView({ padding: 0.2, duration: 200 });
  }, [status, fitKey, fitView, nodeParam, nodesInitialized, getNodes, suppressInitialFit]);

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
  const pendingFrameRef = useRef<readonly string[] | null>(null);
  useEffect(() => {
    const id = pendingFollowRef.current;
    if (id != null) {
      pendingFollowRef.current = null;
    }
    const rendered = new Set(getNodes().map((node) => node.id));
    if (id != null && rendered.has(id)) {
      fitView({ nodes: [{ id }], padding: 0.45, maxZoom: 1.2, duration: 300 });
    }
    const frameIds = pendingFrameRef.current;
    if (frameIds != null && frameIds.every((target) => rendered.has(target))) {
      pendingFrameRef.current = null;
      fitView({ nodes: frameIds.map((target) => ({ id: target })), padding: 0.45, maxZoom: 1.2, duration: 300 });
    }
  }, [paintEpoch, fitView, getNodes]);

  // Hidden-tab camera re-frame. A focus that lands while the tab is hidden applies
  // its STATE (panel, dim/reveal) but never moves the camera: fitView is rAF-driven
  // and rAF is throttled/paused in a hidden tab, so the transition never runs and is
  // not re-issued on return — the focused node ends up off-screen (user-confirmed
  // 2026-06-23). Capture a focus that CHANGES while hidden and re-fit when the tab
  // is shown again, so an agent Point made while the user was away is actually framed.
  // Only a change-while-hidden re-frames — an ordinary tab return where focus didn't
  // move leaves the user's viewport alone. (Connection recovery must NOT key on
  // visibilitychange — see api/events.ts — but CAMERA re-framing legitimately does.)
  const pendingReframeRef = useRef<string | null>(null);
  const prevFocusRef = useRef(focus);
  useEffect(() => {
    if (focus === prevFocusRef.current) return;
    prevFocusRef.current = focus;
    // Arm a re-frame only for a focus that moves WHILE HIDDEN; a focus change while
    // visible (including Clear Focus → null) clears any pending one, so a stale
    // pending can't jerk the camera to a since-dismissed target on the next paint.
    pendingReframeRef.current = document.visibilityState === "hidden" ? focus : null;
  }, [focus]);
  useEffect(() => {
    const reframeOnShow = (): void => {
      if (document.visibilityState !== "visible") return;
      const id = pendingReframeRef.current;
      if (id == null) return;
      const graph = graphRef.current;
      const rendered = new Set(getNodes().map((node) => node.id));
      // Resolve to the SAME on-canvas representative the live Point path uses: a node
      // (or group HOST → its rendered group / io-wrapper) via resolveEndpointFlatId; an
      // io-PORT → its owner card; an EDGE focus → its rendered endpoints. A target not
      // painted yet (an agent Point that revealed a collapsed node while hidden) resolves
      // to null — DON'T clear; the paintEpoch dep re-runs this once the reveal paints.
      const resolve = (flatId: string): string | null => {
        const port = ioPorts?.get(flatId);
        if (port != null) return rendered.has(port) ? port : null;
        if (graph) return resolveEndpointFlatId(graph, rendered, flatId);
        return rendered.has(flatId) ? flatId : null;
      };
      const edge = graph?.edges.find((e) => e.id === id);
      const fitIds = (edge ? [edge.source, edge.target] : [id])
        .map(resolve)
        .filter((fitId): fitId is string => fitId !== null);
      if (fitIds.length === 0) return; // nothing rendered yet — keep pending, retry on the next paint
      pendingReframeRef.current = null;
      fitView({ nodes: fitIds.map((fitId) => ({ id: fitId })), padding: 0.45, maxZoom: 1.2, duration: 300 });
    };
    // Re-fit when the tab returns to visible, AND on each paint while a re-frame is
    // pending (so a focus whose node hadn't painted when the tab was shown still lands).
    reframeOnShow();
    document.addEventListener("visibilitychange", reframeOnShow);
    return () => document.removeEventListener("visibilitychange", reframeOnShow);
  }, [paintEpoch, fitView, getNodes, ioPorts]);
  const onNavigate = useCallback(
    (focusId: string, selected?: string | null) => {
      // The clicked chip may unmount with the panel swap — its mouseleave never
      // fires, so the hover mark would stick. Clear it here.
      clearHover();
      // A newer user/chip navigation supersedes any agent frame that was
      // waiting for a reveal paint.
      pendingFrameRef.current = null;
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

  // Agent frame command: reveal is owned by GraphView; this camera-only arm
  // waits for the resulting paint when a target is currently collapsed, and
  // never mutates focus or selection.
  const frameTargets = useCallback(
    (ids: readonly string[], deferUntilPaint = false) => {
      clearHover();
      // Latest command wins. Without this, a pending frame for A can run on
      // the paint caused by a later immediate frame for B.
      pendingFrameRef.current = null;
      const targets = [...new Set(ids.map((id) => ioPorts?.get(id) ?? id))];
      if (targets.length === 0) return;
      const rendered = new Set(getNodes().map((node) => node.id));
      if (!deferUntilPaint && targets.every((id) => rendered.has(id))) {
        fitView({ nodes: targets.map((id) => ({ id })), padding: 0.45, maxZoom: 1.2, duration: 300 });
      } else {
        pendingFrameRef.current = targets;
      }
    },
    [clearHover, fitView, getNodes, ioPorts],
  );

  return { onNavigate, frameTargets };
}
