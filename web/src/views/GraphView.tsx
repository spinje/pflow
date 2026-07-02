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
  type Node,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { reportInteraction, subscribe, type PointHandlers } from "../api/events";
import { collapsibleGroupIds, initialCollapsed, revealNodes } from "../graph/collapse";
import { autoDirection } from "../graph/direction";
import { consumedReadPaths, ioOwners, refKey, rowTouches, runSteps, topLevelSteps, type Density, type Direction, type FlowEdge, type FlowNode } from "../graph/flow";
import {
  edgeIdForTarget,
  edgeTargetForId,
  flatIdForRef,
  refForFlatId,
  remapCollapsed,
  remapSelection,
} from "../graph/remap";
import { useCameraNavigation } from "../hooks/useCameraNavigation";
import { usePanelPair } from "../hooks/usePanelPair";
import { useSourceWatch } from "../hooks/useSourceWatch";
import { useWorkflowGraph } from "../hooks/useWorkflowGraph";
import { ApiError, fetchSource } from "../api/client";
import {
  DENSITY_TO_PARAM,
  edgeClickAction,
  nodeRepresentativeId,
  readViewParams,
  writeViewParams,
} from "../utils/viewParams";
import type { InteractionTarget, NodeRunState, PointTarget, RFEdge, RFGraph, RFNode, RunComplete, RunEvent, SourceFiles } from "../types";
import { EdgePanel } from "../components/EdgePanel";
import { edgeTypes } from "../components/edges";
import { HoverMarksProvider, InteractionProvider, NO_HOVER } from "../components/interaction";
import { IoPanel } from "../components/IoPanel";
import { NodeCallout } from "../components/NodeCallout";
import { nodeTypes } from "../components/nodes";
import { PanelResizer } from "../components/PanelResizer";
import { RunProgress } from "../components/RunProgress";
import { Rail } from "../components/Rail";
import { ReadPanel } from "../components/ReadPanel";
import { RunPanel } from "../components/RunPanel";
import { RunSelector } from "../components/RunSelector";
import { SourcePane } from "../components/SourcePane";
import { Toolbar } from "../components/Toolbar";

interface GraphViewProps {
  workflow: string;
  onBack: () => void;
}

// A run-event → the overlay's per-node state: status + the cheap hover metrics (already on the wire). Status
// drives the badge; duration/cost ride its hover detail.
const eventState = (e: RunEvent): NodeRunState => ({ status: e.status, durationMs: e.duration_ms, costUsd: e.cost_usd, id: e.id });

// The detail panel's "This run" section opens ONLY for a node with a recorded COMPLETION in the current run.
// `running` (the badge/chip cover it), `stopped` (only a node.start on disk — nothing to project), and
// `unrecorded` (absent from a stale-version replay) are excluded; `pending` is the absence of any status. A
// status-driven CONDITIONAL render (not CSS-hide), so a loop's next iteration remounts → refetches the latest.
const TERMINAL_RUN_STATUSES = new Set<string>(["success", "cached", "failed"]);

// The pflow ">>" chevrons before the run callout's "RUN" title (its leading mark).
const RUN_CHEVRONS = (
  <svg width={17} height={11} viewBox="0 0 17 11" fill="none" aria-hidden>
    <path d="M2 2l3.5 3.5L2 9" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    <path d="M9 2l3.5 3.5L9 9" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

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
  // Provisional LR until the contract arrives; when the URL carried no explicit
  // `direction=`, the auto-direction effect below flips a dense pipeline to TD before
  // the first layout settles (graph/direction.ts).
  const [direction, setDirection] = useState<Direction>(initialView.direction ?? "LR");
  const [sourceOpen, setSourceOpen] = useState<boolean>(initialView.source);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Live execution overlay (Task 173): node status keyed by stable structural ref-key, plus the run
  // banner. Driven by the SSE run-* messages; an empty map = no run = no overlay styling.
  const [runStatus, setRunStatus] = useState<ReadonlyMap<string, NodeRunState>>(() => new Map());
  const [runBanner, setRunBanner] = useState<RunComplete | null>(null);
  // Task 173 DR-1: an optional `?run=<run_id>` pins this Viewer to one specific run (replay a finished
  // run, or watch one of N concurrent runs) instead of the unpinned "follow newest live" overlay. Read
  // once at mount (changing it reloads the page in v1); `runMissing` shows when the pinned id resolves
  // to no trace (stale bookmark / rotated file).
  const [runId, setRunId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("run") || null,
  );
  const [runMissing, setRunMissing] = useState(false);
  // Task 173 (flock death-detection): the run's process exited before finishing (crash/kill). Flip dangling
  // `running` nodes to `stopped` + show a banner, rather than leave them pulsing blue forever.
  const [runStopped, setRunStopped] = useState(false);
  // Task 173 (replay version-detection): the pinned run was recorded against a DIFFERENT version of this
  // workflow than the file on disk now (a node renamed/removed/re-nested). Nodes whose id is unchanged still
  // light correctly; show an honest banner that the rest may not match. Latched server-side; pinned-only.
  const [runStale, setRunStale] = useState(false);
  // Task 175: the Run panel's open/close — a boolean OUTSIDE the `selectedId`
  // selection model (like the RunSelector popover), so opening the launch form
  // never races the three selection panels.
  const [runPanelOpen, setRunPanelOpen] = useState(false);
  // Task 175: after launch the form hands off to a canvas CALLOUT anchored at the
  // Inputs card, streaming live per-node progress (reuses the overlay's runStatus).
  // Opens on launch, on an interactive RunSelector pin, AND on load for a `?run=`
  // deep-link (parity — the pinned run's box should appear when you open its URL).
  const [runCalloutOpen, setRunCalloutOpen] = useState<boolean>(
    () => Boolean(new URLSearchParams(window.location.search).get("run")),
  );
  // Whether THIS page load was a `?run=` deep-link (immutable). The run callout then frames the initial
  // camera on its anchor, so the camera hook skips the competing one-shot whole-graph fit.
  const runDeepLinkRef = useRef(Boolean(new URLSearchParams(window.location.search).get("run")));
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
  // reload — view state is preserved). On unless `pflow ui --no-auto-update` opened
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
      runStatus,
      // Task 173 replay: a STALE (different-version) + COMPLETED (runBanner present → no more events) replay
      // → mark current nodes the run has no state for as "unrecorded" instead of leaving them blank. Gated on
      // completed so a still-running pinned-stale run never mis-marks a node that's merely pending.
      markUnmatched: runStale && runBanner !== null,
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

  // Auto layout direction, decided ONCE per workflow when the contract arrives and ONLY
  // when the URL carried no explicit `direction=` (initialView.direction === null): a
  // dense pipeline opens TD so its ${ref} data dependencies don't thread horizontally
  // through the cards (graph/direction.ts — measured 55%→8% edges-through-boxes on the
  // harness). useLayoutEffect (pre-paint) so the flip lands before the first layout
  // settles, not after a visible LR pass. The ref freezes the choice per workflow — a
  // live-reload edit never re-rotates the canvas, and a user toggle (changeDirection,
  // which sets a concrete value) is never overridden.
  const autoDirectionFor = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!graph || initialView.direction !== null) return;
    if (autoDirectionFor.current === workflow) return;
    autoDirectionFor.current = workflow;
    const auto = autoDirection(graph);
    if (auto !== "LR") setDirection(auto); // LR is the seed — only a flip needs a setState
  }, [graph, workflow, initialView.direction]);

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
  const syncUrl = useCallback(
    (patch: { direction?: Direction; density?: Density; source?: boolean; run?: string | null }) => {
      const url = new URL(window.location.href);
      url.search = writeViewParams(window.location.search, patch);
      window.history.replaceState({}, "", url);
    },
    [],
  );
  // Task 173 D6: pick a run to view — a run_id PINS it (replay, or watch one of N live runs via &run=);
  // null = follow the newest live run (unpinned). In-place: only the overlay status swaps — the graph,
  // camera, focus, and collapse all stay (no ELK re-layout). `?run=` is written to the URL (shareable +
  // survives reload). Clear prior run-state synchronously so the switch never flashes the old run's status;
  // the re-subscribe (the SSE effect depends on runId) repopulates from the new run's snapshot/deltas.
  const selectRun = useCallback(
    (next: string | null) => {
      // Re-picking the CURRENT selection is a no-op. Clearing run-state here relies on the SSE effect
      // (deps include runId) to repopulate from the new run's snapshot — but an UNCHANGED runId never
      // re-fires it, so we'd wipe the overlay markers with nothing to refill them. Only a genuine switch
      // tears down + rebuilds. (The menu still closes: RunSelector.pick owns that, independent of onSelect.)
      if (next === runId) return;
      setRunId(next);
      syncUrl({ run: next });
      setRunStatus(new Map());
      setRunBanner(null);
      setRunMissing(false);
      setRunStopped(false);
      setRunStale(false);
      // Pinning a SPECIFIC past run (from the RunSelector) opens its run callout — the same box a launch
      // hands off to, now showing that run's replayed per-node states (the re-subscribe repopulates
      // runStatus from the pinned run's snapshot). "Live — follow newest" (null) has no specific run to
      // show → close it; a launch re-opens it explicitly in onRunLaunched (which runs after this).
      setRunCalloutOpen(next !== null);
    },
    [runId, syncUrl],
  );
  // Task 175: the ▶ toggles the Run FORM; toggling it always clears any prior run
  // callout (a fresh launch starts clean).
  const toggleRunPanel = useCallback(() => {
    setRunCalloutOpen(false);
    setRunPanelOpen((open) => !open);
  }, []);
  // A successful spawn: PIN the overlay to the EXACT run just spawned (Task 175 — the server mints +
  // returns its id). Pinning, not follow-newest, is load-bearing: follow-newest reverts to an older
  // still-live run when this (often shorter) run finishes. `selectRun(runId)` is always a genuine switch
  // here (a fresh unique id), so it tears down + clears + opens the callout (setRunCalloutOpen(true)) on
  // its own — no manual state-clear needed (that was the old follow-newest no-op workaround). The pinned
  // tailer waits out the run's ~1-2s startup (run_tailer grace) then streams it.
  const onRunLaunched = useCallback(
    (runId: string) => {
      selectRun(runId);
      setRunPanelOpen(false);
    },
    [selectRun],
  );
  // The node the run-progress callout anchors to: the top-level Inputs card (its RF node id IS the
  // top-level input_wrapper group's flat id), falling back to the first top-level executable node for a
  // no-input workflow. null → nothing to anchor to (no graph) → no callout.
  const runAnchorId = useMemo(() => {
    if (!graph) return null;
    const inputCard = graph.groups.find((g) => g.kind === "input_wrapper" && !g.parent && g.members.length > 0);
    if (inputCard) return inputCard.id;
    return topLevelSteps(graph)[0]?.id ?? null; // else the first executable step (same predicate as runSteps)
  }, [graph]);
  const changeSourceOpen = useCallback((open: boolean) => { setSourceOpen(open); syncUrl({ source: open }); }, [syncUrl]);
  // The read panel's source-link click: open the pane (if closed) and bump a
  // counter so SourcePane re-scrolls to the selected node's line even when it's
  // already open (the "jump to source" gesture).
  const [sourceJump, setSourceJump] = useState(0);
  const openSourceAt = useCallback(() => { changeSourceOpen(true); setSourceJump((n) => n + 1); }, [changeSourceOpen]);

  // Read the contract/edges via refs so the interaction callbacks (focusPort,
  // hoverRow) stay stable while focus restyles `nodes`/`edges`.
  const graphRef = useRef(graph);
  graphRef.current = graph;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;
  const ioOwnership = useMemo(() => (graph ? ioOwners(graph) : null), [graph]);

  const interactionTargetForNode = useCallback(
    (flatId: string): InteractionTarget | undefined => {
      if (!graph) return undefined;
      const ref = refForFlatId(graph, flatId);
      return ref ? { kind: "node", flat_id: flatId, ref } : undefined;
    },
    [graph],
  );
  const interactionTargetForEdge = useCallback(
    (flatId: string): InteractionTarget | undefined => {
      if (!graph) return undefined;
      const target = edgeTargetForId(graph, flatId);
      return target ? { ...target, flat_id: flatId } : undefined;
    },
    [graph],
  );
  const reportUser = useCallback(
    (
      type: string,
      target?: InteractionTarget,
      nextFocus: string | null = focus,
      nextDensity: Density = density,
      nextDirection: Direction = direction,
    ): void => {
      const focusRef = graph && nextFocus ? refForFlatId(graph, nextFocus) : null;
      reportInteraction(workflow, {
        type,
        ...(target ? { target } : {}),
        view_state: {
          density: DENSITY_TO_PARAM[nextDensity],
          direction: nextDirection,
          focus: focusRef?.node_id ?? null,
        },
      });
    },
    [density, direction, focus, graph, workflow],
  );

  const changeDensity = useCallback(
    (next: Density) => {
      setDensity(next);
      syncUrl({ density: next });
      reportUser("density_change", undefined, focus, next, direction);
    },
    [direction, focus, reportUser, syncUrl],
  );
  const changeDirection = useCallback(
    (next: Direction) => {
      setDirection(next);
      syncUrl({ direction: next });
      reportUser("direction_change", undefined, focus, density, next);
    },
    [density, focus, reportUser, syncUrl],
  );

  const reportedOpen = useRef(false);
  useEffect(() => {
    if (!graph || reportedOpen.current) return;
    reportedOpen.current = true;
    reportUser("workflow_open");
  }, [graph, reportUser]);

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
    reportUser("node_click", interactionTargetForNode(node.id), node.id);
  }, [interactionTargetForNode, reportUser]);

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
    reportUser("edge_click", interactionTargetForEdge(edge.id), action.focus);
  }, [interactionTargetForEdge, reportUser]);

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
    reportUser("focus_clear", undefined, null);
  }, [reportUser]);
  const onClearFocus = useCallback(() => {
    setFocus(null);
    reportUser("focus_clear", undefined, null);
  }, [reportUser]);

  // Clicking a single IO ROW focuses just that port — its connections reveal, the
  // row highlights. On a ROOT IO card the row ALSO opens the interface panel with
  // its entry marked (card = the whole interface, row = one port, same panel both
  // ways). Nested rows (on group cards) stay focus-only: their owner's panel is
  // the host ReadPanel, and auto-opening it on a row click is a different gesture.
  const selectPort = useCallback(
    (portId: string, force: boolean, report: boolean): void => {
      const owner = ioOwnership?.ports.get(portId);
      const ownerGroup = owner != null ? graphRef.current?.groups.find((g) => g.id === owner) : undefined;
      const isRootWrapper =
        ownerGroup != null &&
        ownerGroup.parent == null &&
        (ownerGroup.kind === "input_wrapper" || ownerGroup.kind === "output_wrapper");
      // A user-clicked nested port with no line would reveal nothing. Agent Point
      // is total-apply, so it bypasses this guard and still reveals the named row.
      if (!force && !isRootWrapper) {
        const touched = edgesRef.current.some(
          (edge) =>
            edge.source === portId ||
            edge.target === portId ||
            edge.data?.from === portId ||
            edge.data?.to === portId,
        );
        if (!touched) return;
      }
      setFocus(portId);
      if (isRootWrapper) setSelectedId(owner!);
      if (report) reportUser("port_click", interactionTargetForNode(portId), portId);
    },
    [interactionTargetForNode, ioOwnership, reportUser],
  );

  const interaction = useMemo(
    () => ({
      focusPort: (portId: string) => selectPort(portId, false, true),
      toggleGroup,
      hoverNode: (flatId: string | null) => setHovered(flatId != null ? new Set([flatId]) : NO_HOVER),
      // A hovered row marks its touch set — derived from the FLOW edges (the
      // resolved row landings), read via a ref so the callbacks stay stable.
      hoverRow: (row: { nodeId: string; handles: readonly string[] } | null) =>
        setHovered(row != null ? rowTouches(edgesRef.current, row.nodeId, row.handles) : NO_HOVER),
    }),
    [selectPort, toggleGroup],
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

  // The selected node's live run state — looked up ONCE: `status` drives `showRunDetail`, and the event
  // `id` is the "This run" panel's refetch discriminator (a loop re-completing the same node → new id →
  // refetch, even though the ref/status are unchanged; PR #543).
  const selectedRunState = selectedNode ? runStatus.get(refKey(selectedNode.ref)) : undefined;

  // Task 175: is a run in scope for the IoPanel's per-port "this run" values? A run is pinned (runId), or
  // the overlay has observed one this session (runStatus populated). Gates the IO value fetch so an
  // interface viewed cold shows no empty run blocks. (IO nodes route to IoPanel, never ReadPanel — root IO
  // selection sets selectedId to the wrapper GROUP, which has no host, so selectedNode stays null.)
  const hasRunContext = runId !== null || runStatus.size > 0;

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
  const { onNavigate: navigate, frameTargets } = useCameraNavigation({
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
    suppressInitialFit: runDeepLinkRef.current && Boolean(runAnchorId),
  });
  const onNavigate = useCallback(
    (focusId: string, selected?: string | null): void => {
      navigate(focusId, selected);
      reportUser("focus_change", interactionTargetForNode(focusId), focusId);
    },
    [interactionTargetForNode, navigate, reportUser],
  );

  // Collapse-all folds every collapsible container and clears focus (the focused
  // node is about to disappear into a box — a ring on a hidden node is meaningless).
  // Expand-all only opens; focus survives.
  const collapsibleIds = useMemo(() => (graph ? collapsibleGroupIds(graph) : []), [graph]);
  const onCollapseAll = useCallback(() => {
    setCollapsed(new Set(collapsibleIds));
    setFocus(null);
    setSelectedId(null);
    reportUser("focus_clear", undefined, null);
  }, [collapsibleIds, reportUser]);
  const onExpandAll = useCallback(() => setCollapsed(new Set()), []);

  // The rail's search: the searchable subjects are the workflow's STEPS + container
  // hosts — not IO ports (found via the IO card) and not the synthetic end sink.
  const searchNodes = useMemo(
    () => (graph ? graph.nodes.filter((n) => n.kind !== "input" && n.kind !== "output" && n.kind !== "end") : []),
    [graph],
  );
  const reveal = useCallback(
    (nodeIds: readonly string[]): void => {
      if (!graph) return;
      setCollapsed((current) => revealNodes(graph, current, nodeIds));
    },
    [graph],
  );
  const representativeFor = useCallback(
    (node: RFNode): string => {
      if (node.ref.port !== null) return ioOwnership?.ports.get(node.id) ?? node.id;
      return graph ? nodeRepresentativeId(graph, node) : node.id;
    },
    [graph, ioOwnership],
  );
  // Search-select behaves like CLICKING the node: REVEAL it (expand the collapsed
  // ancestor chain so a buried target becomes visible), then focus + SELECT +
  // camera its representative (a host → its group; a leaf → itself). Passing the
  // rep as the SELECTION (not just the focus) is what opens the read panel and
  // syncs the source pane (selectedNode → activeLine → scroll, SourcePane) — a bare
  // focus would do neither. The follow is paint-deferred, landing after the reveal
  // re-layout — the same ordering the node=/focus= deep link relies on.
  const selectNode = useCallback(
    (node: RFNode, report: boolean) => {
      if (!graph) return;
      reveal([node.id]);
      const repId = representativeFor(node);
      navigate(repId, repId);
      if (report) reportUser("node_click", interactionTargetForNode(repId), repId);
    },
    [graph, interactionTargetForNode, navigate, reportUser, representativeFor, reveal],
  );
  const onSelectNode = useCallback((node: RFNode) => selectNode(node, true), [selectNode]);

  const applyPoint = useCallback(
    (command: "focus" | "frame", target: PointTarget): void => {
      if (!graph) return;
      if (target.kind === "node") {
        const flatId = flatIdForRef(graph, target.ref);
        const node = flatId ? graph.nodes.find((candidate) => candidate.id === flatId) : undefined;
        if (!node) return; // stale Viewer; Auto-update + a human re-point self-heals
        reveal([node.id]);
        const representative = representativeFor(node);
        if (command === "frame") {
          frameTargets([representative], !nodes.some((rendered) => rendered.id === representative));
        } else if (node.ref.port !== null) {
          selectPort(node.id, true, false);
          frameTargets(
            [representative],
            focus !== node.id || !nodes.some((rendered) => rendered.id === representative),
          );
        } else {
          selectNode(node, false);
          // onNavigate cannot see a currently-collapsed representative until
          // the reveal paints; arm the camera explicitly in that one case.
          if (!nodes.some((rendered) => rendered.id === representative)) frameTargets([representative], true);
        }
        return;
      }

      const edgeId = edgeIdForTarget(graph, target);
      const sourceId = flatIdForRef(graph, target.source);
      const targetId = flatIdForRef(graph, target.target);
      if (!edgeId || !sourceId || !targetId) return;
      reveal([sourceId, targetId]);
      const endpointRepresentatives = [sourceId, targetId]
        .map((id) => graph.nodes.find((node) => node.id === id))
        .filter((node): node is RFNode => node !== undefined)
        .map(representativeFor);
      const endpointsNeedPaint = endpointRepresentatives.some(
        (representative) => !nodes.some((rendered) => rendered.id === representative),
      );
      if (command === "frame") {
        frameTargets(endpointRepresentatives, endpointsNeedPaint);
      } else {
        setFocus(edgeId);
        setSelectedId(edgeId);
        frameTargets(endpointRepresentatives, focus !== edgeId || endpointsNeedPaint);
      }
    },
    [focus, frameTargets, graph, nodes, representativeFor, reveal, selectNode, selectPort],
  );

  // Subscribe only after the graph is present. This prevents the open-if-absent
  // retry from observing a live Viewer before it can resolve/apply a command.
  const pointHandlers = useRef<PointHandlers | null>(null);
  pointHandlers.current = {
    focus: (target) => applyPoint("focus", target),
    frame: (target) => applyPoint("frame", target),
    clear: () => {
      setFocus(null);
      setSelectedId(null);
    },
    // Task 175: the agent's select-run verb switches this open Viewer to a run — reuses the SAME selectRun
    // the RunSelector pin / launch use (its `if (next === runId) return` guard makes a re-pick a no-op; a
    // stale id surfaces the run-not-found path). Routed through the ref like focus/frame/clear.
    selectRun: (runId) => selectRun(runId),
  };
  const graphReady = graph !== null;
  useEffect(() => {
    if (!graphReady) return;
    // A (re)subscribe starts clean: clear any prior run's status so switching WORKFLOW (or run) never
    // briefly paints the previous run's state onto this graph before the new snapshot arrives. The new
    // subscription repopulates via its snapshot/deltas. (selectRun also clears synchronously for no flash.)
    setRunStatus(new Map());
    setRunBanner(null);
    setRunMissing(false);
    setRunStopped(false);
    setRunStale(false);
    return subscribe(workflow, {
      focus: (target) => pointHandlers.current?.focus(target),
      frame: (target) => pointHandlers.current?.frame(target),
      clear: () => pointHandlers.current?.clear(),
      selectRun: (runId) => pointHandlers.current?.selectRun(runId),
      // Task 173 live overlay. setState identities are stable + refKey is pure, so these never
      // re-subscribe. The status map is keyed by structural ref-key (survives a flat-id renumber).
      runSnapshot: (events, run, stopped, stale) => {
        setRunMissing(false);
        setRunStopped(stopped);
        // `stale` carries on the snapshot for a LATE subscriber (the present subscriber learns it via the
        // run-stale broadcast below, whose snapshot predates the server-side latch).
        setRunStale(stale);
        // A late subscriber to an already-stopped run gets the dangling nodes still reading `running` —
        // flip them to `stopped` here so it doesn't blue-blink forever (silent-failures review).
        setRunStatus(
          new Map(
            events.map((e) => [
              refKey(e.ref),
              stopped && e.status === "running" ? { status: "stopped" } : eventState(e),
            ]),
          ),
        );
        setRunBanner(run);
      },
      runEvents: (events) =>
        setRunStatus((prev) => {
          const next = new Map(prev);
          for (const e of events) next.set(refKey(e.ref), eventState(e));
          return next;
        }),
      // A completed run is not stopped — clear any stale stopped state (defensive against the clean-finish
      // race the tailer now also guards; concurrency review).
      runComplete: (run) => {
        setRunStopped(false);
        setRunBanner(run);
      },
      runReset: () => {
        setRunMissing(false);
        setRunStopped(false);
        setRunStale(false);
        setRunStatus(new Map());
        setRunBanner(null);
      },
      runNotFound: () => {
        setRunStatus(new Map());
        setRunBanner(null);
        setRunStale(false);
        setRunMissing(true);
      },
      // Task 173 flock death-detection: the run's process exited mid-flight. Flip the nodes still showing
      // `running` to `stopped` (they'll never complete) and surface the banner.
      runStopped: () => {
        setRunStopped(true);
        setRunStatus((prev) => {
          const next = new Map(prev);
          for (const [key, st] of next) {
            if (st.status === "running") next.set(key, { ...st, status: "stopped" });
          }
          return next;
        });
      },
      // Task 173 replay version-detection: the pinned run was recorded against a different workflow version.
      // Reaches the subscriber present when the server latched it (its snapshot predates the latch); late
      // subscribers get it via the snapshot's stale flag instead. Non-blocking — nodes still light.
      runStale: () => setRunStale(true),
    }, runId);
  }, [graphReady, workflow, runId]);

  // Dev-only join-miss detector (Task 173, deep-review R1). A run-event whose structural ref matches no
  // graph node lights nothing and raises nothing — the overlay's signature silent failure (producer
  // emit-time ancestor_path drifting from the renderer's RFRef). Surface it loudly in dev so it's caught
  // during the mandatory browser verification, especially at the sub-workflow / batch checkpoints where
  // non-empty ancestor_path joins first get exercised. Keyed on the FULL graph (not rendered nodes), so a
  // collapsed-group child is not a false positive.
  useEffect(() => {
    if (!import.meta.env.DEV || !graph || runStatus.size === 0) return;
    const joinable = new Set(graph.nodes.map((n) => refKey(n.ref)));
    const unjoined = [...runStatus.keys()].filter((key) => !joinable.has(key));
    if (unjoined.length > 0) {
      console.warn(
        `pflow overlay: ${unjoined.length} run-event(s) join to no graph node ` +
          `(producer ancestor_path vs renderer RFRef drift?):`,
        unjoined,
      );
    }
  }, [runStatus, graph]);

  const toolbar = (): JSX.Element => (
    <Toolbar
      title={workflowName}
      path={workflow}
      density={density}
      direction={direction}
      onDensity={changeDensity}
      onDirection={changeDirection}
      onBack={onBack}
    />
  );

  // The rail is a floating capsule anchored to the LEFT EDGE OF THE CANVAS (it
  // rides right of the source pane when open, far-left when closed). showSource is
  // false in the error state, where there's no canvas; the rail returns null when
  // it has nothing to show (the back nav lives in the toolbar).
  const rail = (showSourceToggle: boolean): JSX.Element => (
    <Rail
      runControl={<RunSelector workflow={workflow} runId={runId} onSelect={selectRun} />}
      sourceOpen={sourceOpen}
      showSourceToggle={showSourceToggle}
      groupCount={collapsibleIds.length}
      openCount={collapsibleIds.length - collapsed.size}
      focused={focus !== null}
      searchNodes={showSourceToggle ? searchNodes : undefined}
      // The ▶ needs the schema to build the form — gate it on a loaded graph.
      onRun={graph ? toggleRunPanel : undefined}
      runPanelOpen={runPanelOpen}
      onSourceOpen={changeSourceOpen}
      onCollapseAll={onCollapseAll}
      onExpandAll={onExpandAll}
      onClearFocus={onClearFocus}
      onSelectNode={onSelectNode}
    />
  );

  if (status === "error") {
    return (
      <div className="graph-view">
        {toolbar()}
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
        {toolbar()}
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
                jump={sourceJump}
                onNavigate={onNavigate}
              />
              <PanelResizer side="left" onResize={onSourceResize} onReset={onSourceReset} />
            </>
          )}
          <div className="canvas">
          {rail(true)}
          {/* Run banners stack top-right (a stale REPLAY shows the version banner AND the outcome banner; a
              crashed run the stopped banner too) — a flex column so they never overlap. */}
          <div className="run-banners">
          {runMissing && (
            // Task 173 DR-1: a pinned `?run=` id resolved to no trace. TWO causes collapse here — the
            // trace was cleared/rotated, OR the run id is wrong (typo / hand-built / from another machine).
            // Name both + echo the id + the recovery, rather than assert one cause or leave an all-pending
            // canvas implying the run never started (the silent failure this banner exists to prevent).
            <div className="run-banner run-failed" role="status">
              Run <code>{runId}</code> not found — its trace may have been cleared from{" "}
              <code>~/.pflow/debug</code>, or the run id is incorrect. Remove <code>?run=</code> to follow
              the newest run.
            </div>
          )}
          {runStale && (
            // Task 173 replay version-detection: this run was recorded against a different version of the
            // workflow than the file on disk now. Factual + non-blocking — unchanged-id nodes still light;
            // the "● Live — follow newest" un-pin in the RunSelector is the way out.
            <div className="run-banner run-stale" role="status">
              This run was recorded against a different version of this workflow — node states may not match
              the current graph.
            </div>
          )}
          {runStopped && (
            // Task 173 flock death-detection: the run's process exited before finishing. Say so (amber)
            // instead of leaving nodes pulsing `running`; the ones that were running now read `stopped`.
            <div className="run-banner run-stopped" role="status">
              Run stopped — the process exited before finishing.
            </div>
          )}
          {runBanner && (
            // Task 173: the run outcome banner (final_status: success | degraded | failed | denied). The live
            // per-node state shows on the nodes themselves; this is the run-level summary.
            <div className={`run-banner run-${runBanner.final_status ?? "running"}`} role="status">
              Run {runBanner.final_status ?? "running"}
              {typeof runBanner.nodes_executed === "number" ? ` · ${runBanner.nodes_executed} nodes` : ""}
              {runBanner.nodes_failed ? ` · ${runBanner.nodes_failed} failed` : ""}
            </div>
          )}
          </div>
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
            {/* Task 175: live run progress, anchored on the canvas at the Inputs card (ViewportPortal →
                flow-space, so it pans/zooms like a node). Reuses the overlay's runStatus — no new
                observation. The reusable NodeCallout shell is Task 174's "say" bubble target too. */}
            {runCalloutOpen && graph && runAnchorId && (
              <NodeCallout
                anchorId={runAnchorId}
                direction={direction}
                icon={RUN_CHEVRONS}
                title="Run"
                // The run id: the pinned id (RunSelector / ?run=), else the completed run's id from the banner
                // (a live run surfaces its id on completion). Shortened, full on hover.
                subtitle={
                  (runId ?? runBanner?.execution_id) ? (
                    <span title={runId ?? runBanner?.execution_id}>{(runId ?? runBanner?.execution_id)!.slice(0, 8)}</span>
                  ) : undefined
                }
                onClose={() => setRunCalloutOpen(false)}
              >
                <RunProgress
                  steps={runSteps(graph, runStatus)}
                  banner={runBanner}
                  // A run that ended with NO banner: not-found (stale ?run=) / stopped (killed). Without
                  // this the callout span "Running…" forever while the canvas banner said otherwise.
                  outcome={runMissing ? "not-found" : runStopped ? "stopped" : null}
                  onSelectStep={(id) => onNavigate(id, id)}
                />
              </NodeCallout>
            )}
          </ReactFlow>
          </div>
          {(rightPanelOpen || (runPanelOpen && graph)) && (
            <PanelResizer onResize={onPanelResize} onReset={onPanelReset} />
          )}
          {/* At most ONE right-side panel: the Run panel REPLACES the selection panel
              while open (selectedId is preserved underneath, so closing ▶ returns to it).
              Two no-shrink .read-panels + the source pane would exceed usePanelPair's
              source-vs-one-right-panel budget and crush the canvas — the run panel is
              outside the selectedId model in STATE, but shares the one right slot. */}
          {runPanelOpen && graph ? (
            <RunPanel
              workflow={workflow}
              workflowName={workflowName}
              graph={graph}
              onLaunched={onRunLaunched}
              onClose={() => setRunPanelOpen(false)}
            />
          ) : (
            <>
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
              workflow={workflow}
              runId={runId}
              hasRunContext={hasRunContext}
              completedRunId={runBanner?.execution_id ?? null}
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
              onOpenSource={openSourceAt}
              onClose={() => setSelectedId(null)}
              workflow={workflow}
              runId={runId}
              showRunDetail={TERMINAL_RUN_STATUSES.has(selectedRunState?.status ?? "")}
              runEventId={selectedRunState?.id ?? null}
            />
          )}
            </>
          )}
        </div>
      </div>
      </HoverMarksProvider>
    </InteractionProvider>
  );
}
