// Click-to-read: the full detail of one node, straight from the inline /api/graph
// payload (all param values — including full prompts/code — already ride the
// contract, so there is no on-demand fetch). Surfaces what the canvas can't: full
// param values, source file:line, loop/batch/io config.

import { useState } from "react";

import { cacheInsertIndex } from "../graph/flow";
import { resolveBatchItems } from "../utils/batchItems";
import { fullValue, nodeColor, paramLanguage } from "../utils/format";
import { iconFor } from "../utils/icons";
import { resolveEndpointFlatId } from "../utils/viewParams";
import { BatchItemsBlock } from "./BatchItems";
import { ConnectionSections } from "./Chip";
import { CodeBlock } from "./CodeBlock";
import { Markdown } from "./Markdown";
import { PanelHeader } from "./PanelHeader";
import { ThisRunSection } from "./ThisRunSection";
import type { BatchSpec, RFEdge, RFGraph, RFNode, SourceRef } from "../types";

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
  batch,
}: {
  param: RFNode["params"][number];
  kind: string;
  highlightRef?: string;
  // The owner node's batch, when it has one. A param whose value reads the batch
  // alias (`${item.prompt}`) expands to its per-item resolved values — already
  // inline on the contract. Only LITERAL batches expand (a dynamic batch has no
  // static items). EdgePanel omits this (batch-alias refs draw no edge anyway).
  batch?: BatchSpec | null;
}): JSX.Element {
  const src = sourceLabel(param.source);
  const items = batch && !batch.dynamic ? resolveBatchItems(param.value, batch.as_name, batch.items) : null;
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="read-param">
      <div className="read-param-head">
        <span className="read-param-name">{param.name}</span>
        {param.is_dynamic && <span className="badge badge-dynamic">dynamic</span>}
        {src && <span className="read-param-source">{src}</span>}
        {items && (
          <button
            className="batch-expand"
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
            title={`Resolve \`${batch!.as_name}\` against the ${items.length} batch items`}
          >
            {expanded ? "▾" : "▸"} {items.length} items
          </button>
        )}
      </div>
      <CodeBlock code={fullValue(param.value)} lang={paramLanguage(kind, param.name, param.value)} highlightRef={highlightRef} />
      {items && expanded && (
        // Each item's resolved value, headed by its discriminating field. The
        // body colors with the SAME language as the raw param (a resolved prompt
        // is markdown source, like the param itself).
        <div className="batch-items">
          {items.map((item, i) => (
            <div className="batch-item" key={i}>
              <div className="batch-item-head">{item.label}</div>
              <CodeBlock code={item.value} lang={paramLanguage(kind, param.name, item.value)} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** The node's cached system prefix as the prompt will carry it: the `## Cache`
 *  block's authored template (prose + ${var} per consumed chunk, prefix order),
 *  assembled in Python with the runtime's own rule (RFNode.cached_prefix).
 *  Rendered like a prompt param — colored markdown SOURCE, never rendered
 *  prose — and placed before `prompt` so the panel reads in request order. */
function CachedPrefixBlock({ text }: { text: string }): JSX.Element {
  return (
    <div className="read-param">
      <div className="read-param-head">
        <span className="read-param-name">cached prefix</span>
        <span className="badge badge-dynamic">cached</span>
      </div>
      <CodeBlock code={text} lang="markdown" />
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
  onOpenSource,
  onClose,
  workflow,
  runId,
  showRunDetail,
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
  // Opens the source pane (if closed) and scrolls it to this node's file:line.
  // Absent → the source line renders as plain text (standalone render).
  onOpenSource?: () => void;
  onClose: () => void;
  // Task 173 detail panel: when the selected node has a recorded COMPLETION in the current run, GraphView
  // sets `showRunDetail` and passes the run context — the "This run" section then fetches that node's record
  // from /api/run-node. Optional → ReadPanel stays standalone-renderable (no run in context → no section).
  workflow?: string;
  runId?: string | null;
  showRunDetail?: boolean;
}): JSX.Element {
  const src = sourceLabel(node.source);
  // The avatar name navigates to this node on the canvas (re-centers the camera),
  // resolving a container HOST to its rendered group representative — exactly the
  // Chip's resolve-or-disable rule. Absent graph/onNavigate → a non-clickable name.
  const navId = graph && renderedIds ? resolveEndpointFlatId(graph, renderedIds, node.id) : null;
  // The canvas shows the ROLE (CONDITION/TRANSFORM); this eyebrow keeps it mappable
  // back to the file's `type: code`.
  const eyebrow = node.is_decision ? `${node.kind} · condition` : node.is_transform ? `${node.kind} · transform` : node.kind;
  return (
    <aside className="read-panel">
      <PanelHeader
        icon={iconFor(node)}
        color={nodeColor(node)}
        eyebrow={eyebrow}
        name={node.ref.node_id}
        onNavigate={navId != null && onNavigate ? () => onNavigate(navId) : undefined}
        onClose={onClose}
      />

      {/* Authored prose renders as markdown, inside a collapsible "Description"
          disclosure (open by default). The markdown CSS hangs off `.md` — NOT off
          .read-panel-purpose, which EdgePanel shares for app-written plain strings
          (do not restyle that class). */}
      {node.purpose && (
        <details className="panel-section" open>
          <summary>Description</summary>
          <div className="read-panel-purpose md-host">
            <Markdown text={node.purpose} />
          </div>
        </details>
      )}
      {src &&
        (onOpenSource ? (
          <button className="read-panel-source read-panel-source-btn" title={node.source?.file ?? ""} onClick={onOpenSource}>
            {src}
          </button>
        ) : (
          <p className="read-panel-source" title={node.source?.file ?? ""}>
            {src}
          </p>
        ))}

      <StructuralFacts node={node} />

      {/* The raw literal batch config — every item, every field. Collapsed; the
          `${item.x}` ParamBlock expansion above is the per-param view, this is
          the whole-config view (surfaces item fields no param reads). */}
      {node.batch && <BatchItemsBlock batch={node.batch} kind={node.kind} />}

      {reads.length > 0 && (
        <dl className="facts">
          <div className="fact">
            <dt>consumed</dt>
            <dd>{reads.join(", ")}</dd>
          </div>
        </dl>
      )}

      <OutcomeTable branches={branches} />

      {(node.params.length > 0 || node.cached_prefix != null) && (
        <section className="read-panel-params">
          <h3>Params</h3>
          {node.params.slice(0, cacheInsertIndex(node.params)).map((param) => (
            <ParamBlock param={param} kind={node.kind} batch={node.batch} key={param.name} />
          ))}
          {node.cached_prefix != null && <CachedPrefixBlock text={node.cached_prefix} />}
          {node.params.slice(cacheInsertIndex(node.params)).map((param) => (
            <ParamBlock param={param} kind={node.kind} batch={node.batch} key={param.name} />
          ))}
        </section>
      )}

      {graph && renderedIds && onNavigate && (
        <ConnectionSections node={node} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
      )}

      {showRunDetail && workflow && <ThisRunSection workflow={workflow} runId={runId ?? null} nodeRef={node.ref} />}
    </aside>
  );
}
