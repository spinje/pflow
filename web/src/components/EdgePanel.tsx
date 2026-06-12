// Click-to-read for a CONNECTION (edge selection, 2026-06-10): what flows, where
// it's authored, why a branch fires. Five variants by edge kind — data / branch /
// error / end / sequential — all from the contract already in hand (zero fetch).
// Degradation is ADDITIVE (the contract's own rule): input_name/output_field/
// condition are frequently null on re-anchored or truncated edges — the panel
// shows what exists and falls back to neutral wording, never an empty heading.
//
// Endpoint CHIPS (components/Chip.tsx, the shared module) navigate: resolve to
// the RENDERED flat id or render non-clickable; hover marks the canvas node; an
// IO port chip uses port-focus semantics (focus the row, keep this panel).

import { bindingParam } from "../graph/flow";
import { nodeColor } from "../utils/format";
import { Chip } from "./Chip";
import { OutcomeTable, ParamBlock } from "./ReadPanel";
import type { RFEdge, RFGraph, RFNode } from "../types";

// The kind line's tint mirrors the edge's canvas paint (semantic colors from the
// same CSS vars the components use; literals only as fallbacks).
const KIND_TINT: Record<string, string> = {
  data_flow: "var(--data-edge)",
  error: "var(--danger)",
  end: "var(--text-faint)",
};

/** The node that AUTHORED a binding into an IO port. A line into a sub-workflow's
 *  input port carries its `${...}` text on the sub-workflow STEP (`inputs: {key:
 *  "${...}"}` in the parent file) — the port itself has no params. Resolve: the
 *  wrapper holding the port → its enclosing workflow/batch group → that group's
 *  HOST node, walking PAST hostless ancestors (a literal-batch ITEM container
 *  ships `host: null`; the binding is authored once on the batch host one level
 *  up — review-caught 2026-06-11). A ROOT wrapper has no parent group → null
 *  (the caller/CLI binds it; there is no authored text to show). */
export function portOwnerHost(graph: RFGraph, port: RFNode): RFNode | null {
  const wrapper = graph.groups.find(
    (g) => (g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.members.includes(port.id),
  );
  let parent = wrapper?.parent ? (graph.groups.find((g) => g.id === wrapper.parent) ?? null) : null;
  while (parent && !parent.host && parent.parent) {
    parent = graph.groups.find((g) => g.id === parent!.parent) ?? null;
  }
  return parent?.host ? (graph.nodes.find((n) => n.id === parent.host) ?? null) : null;
}

/** Whether an IO port belongs to a NESTED wrapper (a sub-workflow's interface) as
 *  opposed to the root workflow's own inputs/outputs — drives the io fact's
 *  wording, which must never call a sub-workflow item's input a "workflow input". */
export function portIsNested(graph: RFGraph, port: RFNode): boolean {
  return graph.groups.some(
    (g) => (g.kind === "input_wrapper" || g.kind === "output_wrapper") && g.members.includes(port.id) && g.parent != null,
  );
}

export function EdgePanel({
  edge,
  graph,
  renderedIds,
  onNavigate,
  onClose,
}: {
  edge: RFEdge;
  graph: RFGraph;
  renderedIds: ReadonlySet<string>;
  onNavigate: (focus: string, selectedId?: string | null) => void;
  onClose: () => void;
}): JSX.Element {
  const sourceNode = graph.nodes.find((n) => n.id === edge.source);
  const targetNode = graph.nodes.find((n) => n.id === edge.target);
  const sourceName = sourceNode?.ref.node_id ?? edge.source;
  const targetName = targetNode?.ref.node_id ?? edge.target;
  // A decision's end edge is its reserved "end" OUTCOME — discriminated by the
  // SOURCE's is_decision fact (never by condition presence: extraction is
  // fail-closed, so a real decision's end edge can ship condition-less).
  const isDecisionEnd = edge.kind === "end" && sourceNode?.is_decision === true;
  const isOutcome = edge.kind === "branch" || isDecisionEnd;

  const kindLine =
    edge.kind === "data_flow"
      ? "data flow"
      : edge.kind === "branch"
        ? "branch · outcome"
        : edge.kind === "error"
          ? "error route"
          : edge.kind === "end"
            ? isDecisionEnd
              ? "end · outcome"
              : "end"
            : "sequential";
  const tint = edge.kind === "branch" || edge.kind === "sequential" ? (sourceNode ? nodeColor(sourceNode) : undefined) : KIND_TINT[edge.kind];

  // Data title: "output_field[.sub.path] → input_name", each side falling back to
  // an IO port's name (an input's binding carries no output_field — the port IS
  // the source). `output_path` is part of the edge's MEANING (review-caught
  // 2026-06-11: two sub-key lines from one field gave byte-identical panels):
  // "result.ok → x" and "result.err → y" must read as the distinct connections
  // they are. Both roles null (re-anchored/deduped) → neutral wording.
  const fieldPath = edge.output_field ? [edge.output_field, ...edge.output_path].join(".") : null;
  const left = fieldPath ?? (sourceNode?.io ? sourceName : null);
  const right = edge.input_name ?? (targetNode?.io ? targetName : null);
  const dataTitle = left && right ? `${left} → ${right}` : (left ?? right ?? "data connection");
  const title =
    edge.kind === "data_flow"
      ? dataTitle
      : edge.kind === "branch"
        ? (edge.label ?? "outcome")
        : edge.kind === "error"
          ? `on failure → ${targetName}`
          : edge.kind === "end"
            ? `${sourceName} → end`
            : `${sourceName} → ${targetName}`;

  // The selected data edge's param block: the target param the line lands on,
  // with THIS edge's ${ref} segments highlighted (source name + optional field —
  // the most specific prefix, so a sibling ref from the same node doesn't light).
  // An INPUT-PORT target resolves through the port to the sub-workflow HOST step
  // that authored the binding (the port's own params are always empty —
  // user-caught 2026-06-10: "I can't see any highlight"); the binding key there
  // is the PORT's name. An output port's text lives in the outputs section, not
  // a param — the io fact below covers it.
  const targetHost = targetNode?.io && targetNode.kind === "input" ? portOwnerHost(graph, targetNode) : null;
  const param =
    edge.kind === "data_flow"
      ? targetNode?.io
        ? bindingParam(targetHost, targetNode.ref.node_id)
        : bindingParam(targetNode, edge.input_name)
      : null;
  // The most specific prefix the contract gives us — including the sub-key path,
  // so `${gen.result.ok}` and `${gen.result.err}` light ONLY their own line's ref.
  const highlightRef = sourceNode ? (fieldPath && !sourceNode.io ? `${sourceName}.${fieldPath}` : sourceName) : undefined;

  // "one of N references into `prompt`" — interpolated params draw one line per ref.
  const refSiblings =
    edge.kind === "data_flow" && edge.input_name
      ? graph.edges.filter((e) => e.kind === "data_flow" && e.target === edge.target && e.input_name === edge.input_name).length
      : 0;
  // "one of N bindings between these nodes" — parallel bindings can dedupe to one
  // rendered line at node level (the clicked line then represents them all).
  // Contract-pair count: covers leaf↔leaf multi-bindings; a port-fanout bundle
  // (distinct port targets) self-heals on click in beautiful (the expansion gives
  // every binding its own row line).
  const bundle =
    edge.kind === "data_flow"
      ? graph.edges.filter((e) => e.kind === "data_flow" && e.source === edge.source && e.target === edge.target)
      : [];

  // The source's full outcome table (branch edges + a decision's end arm), the
  // selected edge's row marked — a branch only makes sense as one arm of its fork.
  const outcomes = isOutcome
    ? graph.edges.filter((e) => e.source === edge.source && (e.kind === "branch" || (e.kind === "end" && sourceNode?.is_decision)))
    : [];

  return (
    <aside className="read-panel">
      <header className="read-panel-header">
        <div>
          <span className="read-panel-kind" style={tint ? { color: tint } : undefined}>
            {kindLine}
          </span>
          <h2>{title}</h2>
        </div>
        <button className="icon-button" onClick={onClose} title="Close">
          ✕
        </button>
      </header>

      <div className="edge-chips">
        <Chip node={sourceNode} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
        <span className="edge-chips-arrow">→</span>
        <Chip node={targetNode} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
      </div>

      {edge.kind === "error" && (
        <p className="read-panel-purpose">
          Taken when <code>{sourceName}</code> fails — after its retries are exhausted.
        </p>
      )}
      {edge.kind === "end" && !isDecisionEnd && <p className="read-panel-purpose">The workflow's final step.</p>}
      {edge.kind === "sequential" && edge.shadowed && (
        <p className="read-panel-purpose">This ordering is also implied by a data dependency between the two steps.</p>
      )}

      {isOutcome && (
        <dl className="facts">
          <div className="fact">
            <dt>condition</dt>
            <dd>{edge.condition ?? "—"}</dd>
          </div>
        </dl>
      )}
      {isOutcome && outcomes.length > 1 && (
        <section className="read-panel-params">
          <h3>all outcomes of {sourceName}</h3>
          <OutcomeTable branches={outcomes} marked={edge.id} />
        </section>
      )}

      {edge.kind === "data_flow" && (refSiblings > 1 || bundle.length > 1) && (
        <dl className="facts">
          {refSiblings > 1 && (
            <div className="fact">
              <dt>interpolated</dt>
              <dd>
                one of {refSiblings} references into <code>{edge.input_name}</code>
              </dd>
            </div>
          )}
          {bundle.length > 1 && (
            <div className="fact">
              <dt>bundle</dt>
              <dd>
                one of {bundle.length} bindings between these nodes:{" "}
                {bundle.map((b) => `${b.output_field ? [b.output_field, ...b.output_path].join(".") : "?"} → ${b.input_name ?? "?"}`).join(", ")}
              </dd>
            </div>
          )}
        </dl>
      )}

      {param && (
        <section className="read-panel-params">
          <h3>receives</h3>
          {/* kind = the param OWNER's kind: an IO-port target's param comes from
              the sub-workflow HOST (bindingParam above), so the port's own
              kind ("input") would pick the wrong language. */}
          <ParamBlock
            param={param}
            kind={targetNode?.io ? (targetHost?.kind ?? "") : (targetNode?.kind ?? "")}
            highlightRef={highlightRef}
          />
        </section>
      )}
      {edge.kind === "data_flow" && targetNode?.io && (
        <dl className="facts">
          <div className="fact">
            <dt>feeds</dt>
            <dd>
              {targetHost
                ? `sub-workflow input of ${targetHost.ref.node_id}: `
                : targetNode.kind === "input"
                  ? portIsNested(graph, targetNode)
                    ? "sub-workflow input "
                    : "workflow input "
                  : "workflow output "}
              <code>{targetName}</code>
              {targetNode.io.data_type ? ` (${targetNode.io.data_type})` : ""}
            </dd>
          </div>
        </dl>
      )}
    </aside>
  );
}
