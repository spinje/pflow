// Click-to-read for the workflow's INTERFACE (the root IO card): its public API
// written out. Per input — name, type, required/default, the full authored
// description, and consumer chips; per output — the same plus its producer
// (`← node` + the field it reads). Everything derives from the contract in hand
// (ports via wrapperPorts — the same single copy the canvas rows render from;
// consumers/producers from the data-flow edges, the EdgePanel precedent).
//
// No claim where the contract is silent: an input with no data-flow edges shows
// no "used by" row at all — refs outside params (loop conditions) form no edges,
// so an affirmative "unused" would be the quiet≠unconsumed trap.

import { useEffect, useRef, useState } from "react";
import { fetchRunNode } from "../api/client";
import { refKey, wrapperPorts } from "../graph/flow";
import { fullValue, IO_COLOR } from "../utils/format";
import { ioCardIcon } from "../utils/icons";
import { resolveEndpointFlatId } from "../utils/viewParams";
import { Chip } from "./Chip";
import { Markdown } from "./Markdown";
import { RunValue } from "./RunValue";
import { PanelHeader } from "./PanelHeader";
import { sourceLabel } from "./ReadPanel";
import type { RFGraph, RFGroup, RFNode, RFRef, SourceRef } from "../types";

export function IoPanel({
  group,
  graph,
  workflowName,
  workflow,
  runId,
  hasRunContext,
  completedRunId,
  renderedIds,
  markedPortId,
  onNavigate,
  onOpenSource,
  onClose,
}: {
  // The ROOT input_wrapper/output_wrapper group the IO card renders as.
  group: RFGroup;
  graph: RFGraph;
  workflowName: string;
  // Task 175 — run context for the per-port "this run" value: `workflow` is the resolvable key
  // fetchRunNode posts to, `runId` pins a past run (null = newest live), `hasRunContext` gates the
  // fetch so an interface viewed with no run in scope shows no (empty) run blocks.
  workflow: string;
  runId: string | null;
  hasRunContext: boolean;
  // The id of the run that just completed (null until run.complete). OUTPUT ports 404 until the trailer
  // writes json_output, so this changes on completion → PortRunValue refetches and the value appears
  // without reopening the panel (Codex P2).
  completedRunId: string | null;
  renderedIds: ReadonlySet<string>;
  // A focused row's port id — its entry gets the marked treatment (card click =
  // the whole interface, row click = the same panel scrolled to one port).
  markedPortId: string | null;
  onNavigate: (focus: string, selectedId?: string | null) => void;
  // Opens the source pane (if closed) scrolled to a port's authored file:line —
  // the ReadPanel source-link gesture, per port. Absent → plain text (standalone).
  onOpenSource?: (ref: SourceRef) => void;
  onClose: () => void;
}): JSX.Element {
  const kind = group.kind === "input_wrapper" ? "input" : "output";
  const ports = wrapperPorts(graph, group);
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

  const markedRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // optional-call: jsdom implements no scrollIntoView
    markedRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [markedPortId]);

  return (
    <aside className="read-panel">
      {/* The avatar is the io card itself; its name navigates back to the card
          on canvas (the card's flat id IS its group id — it is the rendered node). */}
      <PanelHeader
        icon={ioCardIcon(kind)}
        color={IO_COLOR}
        eyebrow={`workflow ${kind}s`}
        eyebrowColor={IO_COLOR}
        name={workflowName}
        onNavigate={() => onNavigate(group.id)}
        onClose={onClose}
      />

      <section className="read-panel-params">
        <h3>
          {ports.length} {kind}
          {ports.length === 1 ? "" : "s"}
        </h3>
        {ports.map((port) => {
          const portNode = nodeById.get(port.id);
          const src = portNode ? sourceLabel(portNode.source) : null;
          const marked = port.id === markedPortId;
          // Consumers (inputs): the far end of each data-flow line out of this
          // port, deduped. A consumer may itself be an IO port (a root input
          // bound into a sub-workflow's input) — Chip's port arm handles it.
          const consumers: RFNode[] = [];
          const seen = new Set<string>();
          // Producer edges (outputs): each carries the field the `source:`
          // expression reads; a multi-ref expression is several edges.
          const producerEdges =
            kind === "output" ? graph.edges.filter((e) => e.kind === "data_flow" && e.target === port.id) : [];
          if (kind === "input") {
            for (const e of graph.edges) {
              if (e.kind !== "data_flow" || e.source !== port.id || seen.has(e.target)) continue;
              seen.add(e.target);
              const n = nodeById.get(e.target);
              if (n) consumers.push(n);
            }
          }
          // Type display: port.dataType already carries the authored OR
          // producer-derived type (wrapperPorts — the single copy the canvas
          // rows show too); no filler — unknown shows nothing.
          const meta = [port.dataType, kind === "input" && port.required ? "required" : null]
            .filter(Boolean)
            .join(" · ");
          return (
            <div className={`io-port${marked ? " marked" : ""}`} key={port.id} ref={marked ? markedRef : undefined}>
              <div className="read-param-head">
                <span className="read-param-name">{port.name}</span>
                {meta && <span className="io-port-meta">{meta}</span>}
                {/* The port's authored home: same grey mono as everywhere, but a
                    LINK — the ReadPanel source-link gesture (open the pane,
                    scroll to this port's own line, not the node's). */}
                {src &&
                  (onOpenSource && portNode?.source?.file ? (
                    <button
                      className="read-param-source read-panel-source-btn"
                      title={portNode.source.file}
                      onClick={() => onOpenSource(portNode.source!)}
                    >
                      {src}
                    </button>
                  ) : (
                    <span className="read-param-source">{src}</span>
                  ))}
              </div>
              {/* a <div>: Markdown renders <p> children, and <p>-in-<p> trips
                  validateDOMNesting. The `default:` line below stays plain. */}
              {port.description && (
                <div className="io-port-desc">
                  <Markdown text={port.description} />
                </div>
              )}
              {kind === "input" && port.defaultValue != null && (
                <p className="io-port-desc">
                  default: <code>{fullValue(port.defaultValue)}</code>
                </p>
              )}
              {/* Chip rows speak the panel's label-word vocabulary ("feeds",
                  "consumed", …): a faint word names the relationship — clearer
                  than a bare arrow (user-caught 2026-06-11). */}
              {consumers.length > 0 && (
                <div className="edge-chips io-port-uses">
                  <span className="io-port-uses-label">used by</span>
                  {consumers.map((n) => (
                    <Chip key={n.id} node={n} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
                  ))}
                </div>
              )}
              {producerEdges.map((e) => {
                // Reads as one phrase: "from build-report.result" — the chip is
                // the node, the dot-prefixed code its field snug beside it. A
                // PORT producer whose field just repeats the port's name shows
                // no field (`from execute-plan.pr_url .pr_url` said it twice —
                // reading the port IS the field; user-caught 2026-06-11); a
                // deeper sub-path still shows.
                const producer = nodeById.get(e.source);
                const fieldPath = e.output_field ? [e.output_field, ...e.output_path].join(".") : null;
                const showField = fieldPath != null && !(producer?.io && fieldPath === producer.ref.node_id);
                // The field is a LINK to the producer's recorded output: the
                // SELECTION arm (focus + open its ReadPanel, whose "This run"
                // section holds the value) — deliberately more than the chip
                // beside it, which navigates without opening. Chip's
                // resolve-or-disable rule: unresolvable → plain text.
                const producerFlatId = producer ? resolveEndpointFlatId(graph, renderedIds, producer.id) : null;
                return (
                  <div className="edge-chips io-port-uses" key={e.id}>
                    <span className="io-port-uses-label">from</span>
                    <Chip node={producer} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
                    {showField &&
                      (producerFlatId ? (
                        <button
                          className="io-port-path io-port-path-btn"
                          title={`Open ${producer!.ref.node_id}'s output`}
                          onClick={() => onNavigate(producerFlatId, producerFlatId)}
                        >
                          .{fieldPath}
                        </button>
                      ) : (
                        <code className="io-port-path">.{fieldPath}</code>
                      ))}
                  </div>
                );
              })}
              {/* Task 175 — this port's value for the in-context run. Gated on a run being present
                  (else every port would show an empty block) and on the port carrying a structural ref
                  (the same identity /api/run-node joins on). Redaction is server-side. */}
              {hasRunContext && portNode && (
                <PortRunValue
                  workflow={workflow}
                  runId={runId}
                  completedRunId={completedRunId}
                  nodeRef={portNode.ref}
                  kind={kind}
                  portName={port.name}
                />
              )}
            </div>
          );
        })}
      </section>
    </aside>
  );
}

// One port's value for the in-context run, fetched on demand from /api/run-node (the SAME endpoint the
// node detail panel uses; IO refs project from meta.inputs / json_output.result server-side). Owns its
// own fetch + catch (DR-6): a miss / absent value shows "no recorded value", never throws or blanks the
// panel. The value renders via CodeBlock (text for strings, JSON otherwise) — scroll-capped for large
// outputs, the chosen "this run" block treatment.
function PortRunValue({
  workflow,
  runId,
  completedRunId,
  nodeRef,
  kind,
  portName,
}: {
  workflow: string;
  runId: string | null;
  // Refetch discriminator: an OUTPUT port 404s until the run's run.complete trailer writes json_output, so
  // a fetch during a live run lands on "absent". This changes when the run completes → the effect re-runs
  // and the output value appears without reopening the panel (Codex P2). Harmless for inputs (same value).
  completedRunId: string | null;
  nodeRef: RFRef;
  kind: "input" | "output";
  portName: string;
}): JSX.Element {
  const [state, setState] = useState<{ phase: "loading" | "value" | "absent"; value?: unknown }>({
    phase: "loading",
  });

  // Inputs are recorded at t=0 and never change during a run → they fetch ONCE. Only OUTPUTS (404 until
  // run.complete writes json_output) refetch when the run completes, so gate the completion epoch to
  // outputs — otherwise every input port would re-fetch (and briefly flash empty via the loading phase) on
  // completion for no gain.
  const outputRunEpoch = kind === "output" ? completedRunId : null;

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    fetchRunNode(workflow, runId, nodeRef)
      .then((detail) => {
        if (cancelled) return;
        // input → the value keyed by the port name; output → the resolved value directly (the synthesized
        // IO shape, run_node._io_shape). The server only 200s when the value exists, so a 200 means present.
        setState({ phase: "value", value: kind === "input" ? detail.input[portName] : detail.output });
      })
      .catch(() => {
        // 404 (no recorded value for this port this run — sub-workflow, absent input, text-mode output) or
        // a transient error: either way show the honest "no recorded value", never blank the panel.
        if (!cancelled) setState({ phase: "absent" });
      });
    return () => {
      cancelled = true;
    };
  }, [workflow, runId, outputRunEpoch, refKey(nodeRef), kind, portName]);

  // Loading is brief over loopback — render nothing rather than a placeholder that would flash on N ports.
  if (state.phase === "loading") return <></>;
  return (
    <div className="io-port-run">
      <span className="io-port-run-label">this run</span>
      {state.phase === "value" ? (
        <RunValue value={state.value} label={portName} />
      ) : (
        <span className="io-port-run-empty">no recorded value</span>
      )}
    </div>
  );
}
