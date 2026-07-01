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
import { Chip } from "./Chip";
import { Markdown } from "./Markdown";
import { RunValue } from "./RunValue";
import { PanelHeader } from "./PanelHeader";
import { sourceLabel } from "./ReadPanel";
import type { RFGraph, RFGroup, RFNode, RFRef } from "../types";

export function IoPanel({
  group,
  graph,
  workflowName,
  workflow,
  runId,
  hasRunContext,
  renderedIds,
  markedPortId,
  onNavigate,
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
  renderedIds: ReadonlySet<string>;
  // A focused row's port id — its entry gets the marked treatment (card click =
  // the whole interface, row click = the same panel scrolled to one port).
  markedPortId: string | null;
  onNavigate: (focus: string, selectedId?: string | null) => void;
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
                {src && <span className="read-param-source">{src}</span>}
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
                return (
                  <div className="edge-chips io-port-uses" key={e.id}>
                    <span className="io-port-uses-label">from</span>
                    <Chip node={producer} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
                    {showField && <code className="io-port-path">.{fieldPath}</code>}
                  </div>
                );
              })}
              {/* Task 175 — this port's value for the in-context run. Gated on a run being present
                  (else every port would show an empty block) and on the port carrying a structural ref
                  (the same identity /api/run-node joins on). Redaction is server-side. */}
              {hasRunContext && portNode && (
                <PortRunValue workflow={workflow} runId={runId} nodeRef={portNode.ref} kind={kind} portName={port.name} />
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
  nodeRef,
  kind,
  portName,
}: {
  workflow: string;
  runId: string | null;
  nodeRef: RFRef;
  kind: "input" | "output";
  portName: string;
}): JSX.Element {
  const [state, setState] = useState<{ phase: "loading" | "value" | "absent"; value?: unknown }>({
    phase: "loading",
  });

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
  }, [workflow, runId, refKey(nodeRef), kind, portName]);

  // Loading is brief over loopback — render nothing rather than a placeholder that would flash on N ports.
  if (state.phase === "loading") return <></>;
  return (
    <div className="io-port-run">
      <span className="io-port-run-label">this run</span>
      {state.phase === "value" ? (
        <RunValue value={state.value} />
      ) : (
        <span className="io-port-run-empty">no recorded value</span>
      )}
    </div>
  );
}
