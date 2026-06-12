// Click-to-read: the full detail of one node, straight from the inline /api/graph
// payload (all param values — including full prompts/code — already ride the
// contract, so there is no on-demand fetch). Surfaces what the canvas can't: full
// param values, source file:line, loop/batch/io config.

import { fullValue, paramLanguage } from "../utils/format";
import { ConnectionSections } from "./Chip";
import { CodeBlock } from "./CodeBlock";
import { Markdown } from "./Markdown";
import type { RFEdge, RFGraph, RFNode, SourceRef } from "../types";

export function sourceLabel(source: SourceRef | null): string | null {
  if (!source?.file) return null;
  const name = source.file.split("/").pop() ?? source.file;
  return source.line != null ? `${name}:${source.line}` : name;
}

/** The outcome → condition table of a decision (branch edges + the reserved "end"
 *  arm). Shared by ReadPanel (a condition node's panel) and EdgePanel (a selected
 *  branch/end edge marks ITS row). */
export function OutcomeTable({ branches, marked }: { branches: RFEdge[]; marked?: string }): JSX.Element | null {
  if (branches.length === 0) return null;
  return (
    // `outcomes` overrides the facts table's fixed 76px label column: outcome
    // names are long ("process-large") and wrapped mid-word, orphaning the arrow.
    <dl className="facts outcomes">
      {branches.map((edge) => (
        <div className={`fact${edge.id === marked ? " fact-marked" : ""}`} key={edge.id}>
          {/* an END edge has no label — it is the reserved "end" outcome */}
          <dt title={edge.label ?? "end"}>→ {edge.label ?? "end"}</dt>
          <dd>{edge.condition ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** One param's full detail (name + dynamic badge + source file:line + value).
 *  Shared by ReadPanel (every param) and EdgePanel (the one param a selected data
 *  edge lands on). `kind` is the param OWNER's node kind — it picks the syntax
 *  highlighting via paramLanguage (fail-closed: unknown stays plain text).
 *  `highlightRef` marks the `${ref}` segments belonging to a selected edge's
 *  SOURCE, so a multi-ref prompt shows WHICH reference the clicked line is
 *  (matches `ref` exactly or `ref.<path>` — never a different node's refs). */
export function ParamBlock({
  param,
  kind,
  highlightRef,
}: {
  param: RFNode["params"][number];
  kind: string;
  highlightRef?: string;
}): JSX.Element {
  const src = sourceLabel(param.source);
  return (
    <div className="read-param">
      <div className="read-param-head">
        <span className="read-param-name">{param.name}</span>
        {param.is_dynamic && <span className="badge badge-dynamic">dynamic</span>}
        {src && <span className="read-param-source">{src}</span>}
      </div>
      <CodeBlock code={fullValue(param.value)} lang={paramLanguage(kind, param.name, param.value)} highlightRef={highlightRef} />
    </div>
  );
}

function StructuralFacts({ node }: { node: RFNode }): JSX.Element | null {
  const rows: Array<[string, string]> = [];
  // "—" = no authored type (the in-file convention) — never the filler "any",
  // which reads as an authored claim (user-caught 2026-06-11).
  if (node.io) rows.push(["io", `${node.io.data_type ?? "—"}${node.io.required ? " (required)" : ""}`]);
  if (node.loop) {
    rows.push(["loop", `${node.loop.polarity} ${node.loop.condition}`]);
    if (node.loop.cap != null) rows.push(["loop cap", String(node.loop.cap)]);
  }
  if (node.batch) {
    const over = node.batch.dynamic ? node.batch.source_ref ?? "dynamic source" : `${node.batch.count ?? "?"} literal items`;
    rows.push(["batch", `${node.batch.parallel ? "parallel, " : ""}over ${over} as \`${node.batch.as_name}\``]);
  }
  if (node.unexpanded) rows.push(["unexpanded", node.unexpanded]);
  // The authored output shape, in full — the canvas's output rows show one
  // level (D7); the panel carries every key + type, labeled by the shape's own
  // port (`result` / `response`). "—" = unknown, the same convention as the
  // branch-condition table below.
  if (node.output_shape) {
    rows.push([node.output_shape.field, node.output_shape.data_type ?? "—"]);
    for (const key of node.output_shape.keys ?? []) {
      rows.push([`${node.output_shape.field}.${key.name}`, key.data_type ?? "—"]);
    }
  }
  if (rows.length === 0) return null;
  return (
    <dl className="facts">
      {rows.map(([k, v]) => (
        <div className="fact" key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ReadPanel({
  node,
  branches = [],
  reads = [],
  graph,
  renderedIds,
  onNavigate,
  onClose,
}: {
  node: RFNode;
  // The node's outgoing branch edges (GraphView filters the contract) — the
  // untruncated home of the outcome → condition table on a condition node.
  branches?: RFEdge[];
  // Full observed read paths OUT of this node (`output_field[.path…]` joined,
  // from its data-flow edges, deduped by GraphView). The canvas rows land on
  // the FIRST path segment (D7); the panel is the untruncated home — a
  // `${gen.result.a.b}` read shows here as `result.a.b`.
  reads?: string[];
  // The references / referenced-by chip sections need the contract + chip
  // semantics — optional so the panel stays renderable on its own (the
  // sections simply don't appear without them).
  graph?: RFGraph | null;
  renderedIds?: ReadonlySet<string>;
  onNavigate?: (focus: string, selectedId?: string | null) => void;
  onClose: () => void;
}): JSX.Element {
  const src = sourceLabel(node.source);
  return (
    <aside className="read-panel">
      <header className="read-panel-header">
        <div>
          {/* The authored truth: the canvas presents a decision code node as
              CONDITION, so the panel is where `type: code` stays mappable. */}
          <span className="read-panel-kind">
            {/* the canvas shows the ROLE (CONDITION/TRANSFORM); this line keeps it
                mappable back to the file's `type: code` */}
            {node.is_decision ? `${node.kind} · condition` : node.is_transform ? `${node.kind} · transform` : node.kind}
          </span>
          <h2>{node.ref.node_id}</h2>
        </div>
        <button className="icon-button" onClick={onClose} title="Close">
          ✕
        </button>
      </header>

      {/* Authored prose renders as markdown. The markdown CSS hangs off `.md` —
          NOT off .read-panel-purpose, which EdgePanel shares for app-written
          plain strings (do not restyle that class). */}
      {node.purpose && (
        <div className="read-panel-purpose md-host">
          <Markdown text={node.purpose} />
        </div>
      )}
      {src && <p className="read-panel-source" title={node.source?.file ?? ""}>{src}</p>}

      <StructuralFacts node={node} />

      {reads.length > 0 && (
        <dl className="facts">
          <div className="fact">
            <dt>consumed</dt>
            <dd>{reads.join(", ")}</dd>
          </div>
        </dl>
      )}

      <OutcomeTable branches={branches} />

      {node.params.length > 0 && (
        <section className="read-panel-params">
          <h3>params</h3>
          {node.params.map((param) => (
            <ParamBlock param={param} kind={node.kind} key={param.name} />
          ))}
        </section>
      )}

      {graph && renderedIds && onNavigate && (
        <ConnectionSections node={node} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
      )}
    </aside>
  );
}
