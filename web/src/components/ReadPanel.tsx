// Click-to-read: the full detail of one node, straight from the inline /api/graph
// payload (all param values — including full prompts/code — already ride the
// contract, so there is no on-demand fetch). Surfaces what the canvas can't: full
// param values, source file:line, loop/batch/io config.

import { fullValue } from "../utils/format";
import type { RFEdge, RFNode, SourceRef } from "../types";

function sourceLabel(source: SourceRef | null): string | null {
  if (!source?.file) return null;
  const name = source.file.split("/").pop() ?? source.file;
  return source.line != null ? `${name}:${source.line}` : name;
}

function StructuralFacts({ node }: { node: RFNode }): JSX.Element | null {
  const rows: Array<[string, string]> = [];
  if (node.io) rows.push(["io", `${node.io.data_type ?? "any"}${node.io.required ? " (required)" : ""}`]);
  if (node.loop) {
    rows.push(["loop", `${node.loop.polarity} ${node.loop.condition}`]);
    if (node.loop.cap != null) rows.push(["loop cap", String(node.loop.cap)]);
  }
  if (node.batch) {
    const over = node.batch.dynamic ? node.batch.source_ref ?? "dynamic source" : `${node.batch.count ?? "?"} literal items`;
    rows.push(["batch", `${node.batch.parallel ? "parallel, " : ""}over ${over} as \`${node.batch.as_name}\``]);
  }
  if (node.unexpanded) rows.push(["unexpanded", node.unexpanded]);
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
  onClose,
}: {
  node: RFNode;
  // The node's outgoing branch edges (GraphView filters the contract) — the
  // untruncated home of the outcome → condition table on a condition node.
  branches?: RFEdge[];
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

      {node.purpose && <p className="read-panel-purpose">{node.purpose}</p>}
      {src && <p className="read-panel-source" title={node.source?.file ?? ""}>{src}</p>}

      <StructuralFacts node={node} />

      {branches.length > 0 && (
        <dl className="facts">
          {branches.map((edge) => (
            <div className="fact" key={edge.id}>
              {/* an END edge has no label — it is the reserved "end" outcome */}
              <dt>→ {edge.label ?? "end"}</dt>
              <dd>{edge.condition ?? "—"}</dd>
            </div>
          ))}
        </dl>
      )}

      {node.params.length > 0 && (
        <section className="read-panel-params">
          <h3>params</h3>
          {node.params.map((param) => (
            <div className="read-param" key={param.name}>
              <div className="read-param-head">
                <span className="read-param-name">{param.name}</span>
                {param.is_dynamic && <span className="badge badge-dynamic">dynamic</span>}
                {sourceLabel(param.source) && <span className="read-param-source">{sourceLabel(param.source)}</span>}
              </div>
              <pre className="read-param-value">{fullValue(param.value)}</pre>
            </div>
          ))}
        </section>
      )}
    </aside>
  );
}
