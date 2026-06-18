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
import { bindingLabel, nodeColor } from "../utils/format";
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

/** Control SUCCESSOR map — the edges that continue execution (sequential/branch/
 *  error); data passes no control and `end` terminates, so neither can form a cycle. */
function controlSucc(graph: RFGraph): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (e.kind === "sequential" || e.kind === "branch" || e.kind === "error") {
      const list = m.get(e.source);
      if (list) list.push(e.target);
      else m.set(e.source, [e.target]);
    }
  }
  return m;
}

function reachable(start: string, succ: Map<string, string[]>): Set<string> {
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length) {
    const id = stack.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const next of succ.get(id) ?? []) if (!seen.has(next)) stack.push(next);
  }
  return seen;
}

/** The decision step(s) inside the loop a control edge belongs to, or null if its
 *  endpoints aren't in a cycle. An edge is "in a loop" when control can return from
 *  its TARGET back to its SOURCE — so the two sit in one cycle (validate-fix's
 *  run-validate→check-validate, drawn as the wrap U even though it reads forward as
 *  a step). We name where the loop is DECIDED (the is_decision steps in the cycle);
 *  their exit conditions are shown when that step is opened — nothing is inferred
 *  here (the fail-closed bar: a backward-edge loop has no single authored condition).
 *  An empty array = a cycle with no decision step (rare); null = not a loop. */
export function loopDeciders(graph: RFGraph, edge: RFEdge): RFNode[] | null {
  const succ = controlSucc(graph);
  const fwd = reachable(edge.target, succ);
  if (!fwd.has(edge.source)) return null; // target can't return to source → not a loop
  // Cycle members lie on a target→…→source control path = (reachable from target)
  // ∩ (can reach source). Build the reversed map once for the can-reach side.
  const pred = new Map<string, string[]>();
  for (const [s, targets] of succ) {
    for (const t of targets) {
      const list = pred.get(t);
      if (list) list.push(s);
      else pred.set(t, [s]);
    }
  }
  const bwd = reachable(edge.source, pred);
  return [...fwd]
    .filter((id) => bwd.has(id))
    .map((id) => graph.nodes.find((n) => n.id === id))
    .filter((n): n is RFNode => n != null && n.is_decision);
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
  // The reserved `prompt_cache` input_name: a `## Cache` chunk dependency. The
  // chunk's ref is FORBIDDEN in the consumer's prompt body, so this edge is the
  // only visibility the dependency has — present it as the cached prefix, never
  // as a param binding (no such param row exists).
  const isCache = edge.kind === "data_flow" && edge.input_name === "prompt_cache";

  // A sequential edge whose endpoints sit in a control cycle is part of a loop (the
  // validate-fix gate's wrap U). Name it + its decision step — never inferring a
  // condition (those live on the decision step, shown when it's opened).
  const loopDecidersList = edge.kind === "sequential" ? loopDeciders(graph, edge) : null;
  const isLoop = loopDecidersList != null;

  const kindLine =
    edge.kind === "data_flow"
      ? isCache
        ? "cached context"
        : "data flow"
      : edge.kind === "branch"
        ? "branch · outcome"
        : edge.kind === "error"
          ? "error route"
          : edge.kind === "end"
            ? isDecisionEnd
              ? "end · outcome"
              : "end"
            : isLoop
              ? "sequential · loop"
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
  const dataTitle = isCache
    ? `${left ?? "data"} → cached prompt prefix`
    : left && right
      ? `${left} → ${right}`
      : (left ?? right ?? "data connection");
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
      {isLoop && (
        <p className="read-panel-purpose">
          Part of a loop — control returns through these steps each round
          {loopDecidersList!.length > 0 ? ", repeating until its decision step stops it." : "."}
        </p>
      )}
      {isLoop && loopDecidersList!.length > 0 && (
        <section className="read-panel-params">
          <h3>Loop controlled by</h3>
          <div className="chip-stack">
            {loopDecidersList!.map((d) => (
              <Chip key={d.id} node={d} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
            ))}
          </div>
        </section>
      )}
      {edge.kind === "sequential" && !isLoop && edge.shadowed && (
        <p className="read-panel-purpose">This ordering is also implied by a data dependency between the two steps.</p>
      )}
      {isCache && (
        <p className="read-panel-purpose">
          Feeds this node's cached system prefix — declared in the workflow's <code>## Cache</code> block, consumed via{" "}
          <code>prompt_cache:</code>.
        </p>
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
          <h3>All outcomes of {sourceName}</h3>
          <OutcomeTable branches={outcomes} marked={edge.id} />
        </section>
      )}

      {edge.kind === "data_flow" && (refSiblings > 1 || bundle.length > 1) && (
        <dl className="facts">
          {refSiblings > 1 && (
            <div className="fact">
              <dt>interpolated</dt>
              <dd>
                one of {refSiblings} references into <code>{edge.input_name ? bindingLabel(edge.input_name) : edge.input_name}</code>
              </dd>
            </div>
          )}
          {bundle.length > 1 && (
            <div className="fact">
              <dt>bundle</dt>
              <dd>
                one of {bundle.length} bindings between these nodes:{" "}
                {bundle
                  .map(
                    (b) =>
                      `${b.output_field ? [b.output_field, ...b.output_path].join(".") : "?"} → ${b.input_name ? bindingLabel(b.input_name) : "?"}`,
                  )
                  .join(", ")}
              </dd>
            </div>
          )}
        </dl>
      )}

      {param && (
        <section className="read-panel-params">
          <h3>Receives</h3>
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
