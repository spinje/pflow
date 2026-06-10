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
import { assignDataRails, assignFacingSides, assignLoopRails } from "../graph/portSides";
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

// Animated expansion transitions: positions glide over ANIMATE_MS instead of
// snapping — but ONLY on graphs small enough that the per-frame store updates (and
// the edge-path recomputes they trigger) are cheap. Above the cap, snap as before.
const ANIMATE_MAX_NODES = 60;
const ANIMATE_MS = 200;
const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
  // `key` is the layout-state the snapshot was computed for — the decoration effect
  // paints ONLY a matching snapshot (see the stale-paint note there).
  const [laid, setLaid] = useState<{ nodes: FlowNode[]; edges: FlowEdge[]; key: string } | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);
  const { getViewport, setViewport } = useReactFlow();

  // Layout cache: ELK costs ~150ms on a 100+-node workflow (measured), and HALF of
  // all expansion re-layouts recompute a state we already laid out — un-focusing
  // returns to the base layout, re-clicking a node repeats its layout. Keyed by the
  // full layout-affecting state (focus itself is NOT layout-affecting — only the
  // expansion set derived from it is, so two focuses with one expansion set share an
  // entry). Insertion-order eviction caps memory; cleared per workflow fetch.
  const layoutCacheRef = useRef(new Map<string, FlowNode[]>());
  const LAYOUT_CACHE_MAX = 24;

  // 1. Fetch the contract whenever the workflow changes. Reset derived state.
  useEffect(() => {
    let cancelled = false;
    setGraph(null);
    setErrors(null);
    setLaid(null);
    layoutCacheRef.current.clear();
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

  // The current layout-affecting state as a string — the layout cache key AND the
  // staleness guard the decoration effect compares laid snapshots against.
  const layoutKey = useMemo(
    () => `${density}|${direction}|${[...collapsed].sort().join(",")}|${[...expanded].sort().join(",")}`,
    [density, direction, collapsed, expanded],
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
  // The PREVIOUS layout's nodes, captured under the same condition as the pan: an
  // expansion-only re-layout of the same view. They are the start positions for the
  // animated transition (small graphs glide to the new layout instead of snapping).
  const pendingFromRef = useRef<FlowNode[] | null>(null);

  // 3. Client-side ELK layout. Skip while there is no graph (pre-fetch / fetch
  //    error) so an empty layout never clears a fetch error. A layout rejection
  //    surfaces as an error banner instead of hanging on "Laying out…".
  useEffect(() => {
    if (graph === null) return;
    let cancelled = false;
    const apply = (laidOut: FlowNode[]): void => {
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
        pendingFromRef.current = prev.nodes;
      }
      lastLayoutRef.current = { graph, density, direction, collapsed, nodes: laidOut };
      setErrors(null); // a successful re-layout clears any stale layout error
      // Now that positions exist, point each ports-row edge at the side facing
      // its peer, center wrap rails, number fork outcomes by spatial order, and
      // give each loop-back U its wrap rail (graph/portSides.ts) — buildFlow
      // could only assign defaults.
      const decorated = assignLoopRails(
        laidOut,
        assignDataRails(laidOut, assignFacingSides(laidOut, built.edges)),
        direction,
      );
      setLaid({ nodes: laidOut, edges: decorated, key: layoutKey });
    };
    const cached = layoutCacheRef.current.get(layoutKey);
    if (cached) {
      // Synchronous: an already-seen state (un-focus, re-click) lands in one paint —
      // no ELK, no async gap. Camera anchoring still applies (the pan is a delta
      // between layouts, cached or not).
      apply(cached);
      return;
    }
    layoutGraph(built.nodes, built.edges, direction)
      .then((laidOut) => {
        if (cancelled) return;
        const cache = layoutCacheRef.current;
        cache.set(layoutKey, laidOut);
        if (cache.size > LAYOUT_CACHE_MAX) {
          cache.delete(cache.keys().next().value as string);
        }
        apply(laidOut);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErrors([{ message: `Could not lay out this workflow: ${String(e)}` }]);
      });
    return () => {
      cancelled = true;
    };
  }, [graph, built, direction, density, collapsed, layoutKey]);

  // 4. Focus decoration (cheap, no re-layout) -> React Flow store. Applies any
  //    pending camera-anchoring pan alongside the new node positions.
  //    STALE-PAINT GUARD: when a click changes the layout state (expansion), this
  //    effect fires in the same commit as the layout effect — BEFORE the new laid
  //    snapshot exists — so it would decorate the OLD layout with the NEW focus for
  //    one frame, then the real layout lands: a visible "shake" on cached clicks
  //    (and the two-phase look on uncached ones). Painting only a snapshot that
  //    MATCHES the current layout state makes every click exactly one visible
  //    change. Focus-only changes (advanced mode, same expansion) keep the same key,
  //    so pure restyles still apply instantly.
  const animRef = useRef<number | null>(null);
  // The laid snapshot currently painted — animation triggers only when a NEW snapshot
  // lands, never on a focus-only re-decoration of the same one.
  const paintedRef = useRef<{ nodes: FlowNode[]; edges: FlowEdge[]; key: string } | null>(null);
  useEffect(() => {
    if (laid === null || laid.key !== layoutKey) return;
    if (animRef.current !== null) {
      cancelAnimationFrame(animRef.current);
      animRef.current = null;
    }
    const decorated = applyFocus(laid.nodes, laid.edges, focus);
    const isNewLayout = paintedRef.current !== laid;
    paintedRef.current = laid;
    const from = isNewLayout ? pendingFromRef.current : null;
    const pan = isNewLayout ? pendingPanRef.current : null;
    pendingFromRef.current = null;
    pendingPanRef.current = null;

    // Animated transition (expansion re-layouts only — `from` is set under the same
    // condition as the pan): interpolate positions THROUGH the store so the edges
    // follow the nodes (a CSS transform transition would glide the nodes while the
    // edge paths — computed from store positions — snap: detached lines). Per frame,
    // only MOVED nodes get new object identity, so memo'd unmoved nodes skip
    // re-render. Gated to small graphs (per-frame edge recompute is the real cost)
    // and off under prefers-reduced-motion.
    const fromPos = new Map((from ?? []).map((n) => [n.id, n.position]));
    const moved = from
      ? new Set(
          decorated.nodes
            .filter((n) => {
              const p = fromPos.get(n.id);
              return p !== undefined && (p.x !== n.position.x || p.y !== n.position.y);
            })
            .map((n) => n.id),
        )
      : new Set<string>();
    const animate = moved.size > 0 && decorated.nodes.length <= ANIMATE_MAX_NODES && !prefersReducedMotion();

    if (!animate) {
      setNodes(decorated.nodes);
      setEdges(decorated.edges);
      if (pan) {
        const vp = getViewport();
        setViewport({ zoom: vp.zoom, x: vp.x - pan.dx * vp.zoom, y: vp.y - pan.dy * vp.zoom });
      }
      return;
    }

    setEdges(decorated.edges);
    const vp0 = getViewport();
    const t0 = performance.now();
    const ease = (t: number): number => 1 - (1 - t) ** 3; // easeOutCubic
    const step = (now: number): void => {
      const t = Math.min(1, (now - t0) / ANIMATE_MS);
      const e = ease(t);
      setNodes(
        t === 1
          ? decorated.nodes // land EXACTLY on the final snapshot (identities settle for memo)
          : decorated.nodes.map((n) => {
              if (!moved.has(n.id)) return n;
              const p = fromPos.get(n.id)!;
              return { ...n, position: { x: p.x + (n.position.x - p.x) * e, y: p.y + (n.position.y - p.y) * e } };
            }),
      );
      // The camera pan eases WITH the positions, so the anchored node stays
      // stationary throughout the glide, not just at the endpoints.
      if (pan) {
        setViewport({ zoom: vp0.zoom, x: vp0.x - pan.dx * vp0.zoom * e, y: vp0.y - pan.dy * vp0.zoom * e });
      }
      animRef.current = t < 1 ? requestAnimationFrame(step) : null;
    };
    animRef.current = requestAnimationFrame(step);
    return () => {
      if (animRef.current !== null) {
        cancelAnimationFrame(animRef.current);
        animRef.current = null;
        // Interrupted mid-glide (view change / unmount): land on the final state so
        // nothing is left stranded at an interpolated position.
        setNodes(decorated.nodes);
        if (pan) setViewport({ zoom: vp0.zoom, x: vp0.x - pan.dx * vp0.zoom, y: vp0.y - pan.dy * vp0.zoom });
      }
    };
  }, [laid, layoutKey, focus, setNodes, setEdges, getViewport, setViewport]);

  const status: GraphStatus = errors
    ? "error"
    : laid === null
      ? "loading"
      : laid.nodes.length === 0
        ? "empty"
        : "ready";

  return { nodes, edges, onNodesChange, onEdgesChange, status, errors, graph };
}
