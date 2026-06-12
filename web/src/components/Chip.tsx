// The node CHIP — the shared "name a node in a panel" component (extracted from
// EdgePanel 2026-06-11 when ReadPanel became its third consumer). A chip is a
// mini node avatar: the canvas tile in miniature (kind-color border +
// native-color icon) + the name — identity by recognition, not a category word
// (the word rides the tooltip; the read panel keeps the canvas→file mapping).
//
// Semantics every consumer inherits:
// - CLICK navigates (resolve-or-disable: an endpoint hidden inside a collapsed
//   ancestor renders a NON-CLICKABLE chip — visible honesty over a silent no-op).
//   An IO-port chip uses port-focus semantics (focus the row, keep the panel).
// - HOVER marks the chip's canvas node (Interaction.hoverNode) — a pure
//   highlight, no focus/expansion/camera change (user decision 2026-06-11).
//   Only chips that resolve to a rendered canvas box hover (io ports don't).

import { ioOwners } from "../graph/flow";
import { categoryLabel, nodeColor } from "../utils/format";
import { iconFor, ioCardIcon } from "../utils/icons";
import { resolveEndpointFlatId } from "../utils/viewParams";
import { useInteraction } from "./interaction";
import type { RFGraph, RFNode } from "../types";

/** The workflow STEP an io port belongs to (`create-songs` for its `concept`
 *  input) — the chip's scope prefix. A ROOT port returns null (the panel/header
 *  already names the workflow; a bare name is unambiguous there). */
function ioPortScope(graph: RFGraph, port: RFNode): string | null {
  const ownerId = ioOwners(graph).ports.get(port.id);
  const owner = ownerId != null ? graph.groups.find((g) => g.id === ownerId) : undefined;
  const host = owner?.host ? graph.nodes.find((n) => n.id === owner.host) : undefined;
  return host?.ref.node_id ?? null;
}

export function Chip({
  node,
  graph,
  renderedIds,
  onNavigate,
}: {
  node: RFNode | undefined;
  graph: RFGraph;
  renderedIds: ReadonlySet<string>;
  onNavigate: (focus: string, selectedId?: string | null) => void;
}): JSX.Element | null {
  const { hoverNode } = useInteraction();
  if (!node) return null;
  if (node.kind === "end") {
    return <span className="edge-chip edge-chip-static">end</span>;
  }
  const color = nodeColor(node);
  if (node.io) {
    // Port-focus semantics: focus the row (its lines reveal, the row highlights),
    // keep this panel open — a port has no panel of its own. A NESTED port is
    // scope-prefixed (`create-songs.concept` — a bare port name loses WHOSE
    // input it is; user-caught 2026-06-11). Hover marks the PORT id: the owner
    // box rings (GroupNode/IOCardNode match their port lists) and the row
    // lights when rendered (PortRows) — pure highlight, like every chip.
    const scope = ioPortScope(graph, node);
    return (
      <button
        className="edge-chip"
        style={{ "--chip-c": color } as React.CSSProperties}
        title={scope ? `${node.kind === "input" ? "input" : "output"} of ${scope}` : "io port"}
        onClick={() => onNavigate(node.id)}
        onMouseEnter={() => hoverNode(node.id)}
        onMouseLeave={() => hoverNode(null)}
      >
        <span className="edge-chip-tile">
          <img src={ioCardIcon(node.kind === "input" ? "input" : "output")} alt="" />
        </span>
        <span className="edge-chip-name">
          {scope && <span className="edge-chip-scope">{scope}.</span>}
          {node.ref.node_id}
        </span>
      </button>
    );
  }
  const resolved = resolveEndpointFlatId(graph, renderedIds, node.id);
  return (
    <button
      className="edge-chip"
      style={{ "--chip-c": color } as React.CSSProperties}
      disabled={resolved == null}
      title={resolved == null ? "hidden inside a collapsed container" : categoryLabel(node)}
      onClick={resolved != null ? () => onNavigate(resolved, resolved) : undefined}
      onMouseEnter={resolved != null ? () => hoverNode(resolved) : undefined}
      onMouseLeave={resolved != null ? () => hoverNode(null) : undefined}
    >
      <span className="edge-chip-tile">
        <img src={iconFor(node)} alt="" />
      </span>
      <span className="edge-chip-name">{node.ref.node_id}</span>
    </button>
  );
}

/** The data-flow neighbors of a node — the far end of each edge in the given
 *  direction, deduped, in edge order (the IoPanel consumer rule). Derived from
 *  contract edges ONLY: plain-param sibling refs form no edges today (the model
 *  gap in scratchpads/param-ref-data-flow-edges/proposal.md) — when that fix
 *  lands both directions complete with zero change here. */
function dataNeighbors(graph: RFGraph, nodeId: string, direction: "out" | "in"): RFNode[] {
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const out: RFNode[] = [];
  const seen = new Set<string>();
  for (const e of graph.edges) {
    if (e.kind !== "data_flow") continue;
    const far = direction === "out" ? (e.source === nodeId ? e.target : null) : e.target === nodeId ? e.source : null;
    if (far == null || seen.has(far)) continue;
    seen.add(far);
    const n = nodeById.get(far);
    if (n) out.push(n);
  }
  return out;
}

/** Who reads this node's output (downstream). */
export function consumersOf(graph: RFGraph, nodeId: string): RFNode[] {
  return dataNeighbors(graph, nodeId, "out");
}

/** Whose output this node reads (upstream). */
export function producersOf(graph: RFGraph, nodeId: string): RFNode[] {
  return dataNeighbors(graph, nodeId, "in");
}

function ChipStack({
  label,
  nodes,
  graph,
  renderedIds,
  onNavigate,
}: {
  label: string;
  nodes: RFNode[];
  graph: RFGraph;
  renderedIds: ReadonlySet<string>;
  onNavigate: (focus: string, selectedId?: string | null) => void;
}): JSX.Element | null {
  if (nodes.length === 0) return null;
  return (
    <section className="read-panel-params">
      <h3>
        {label} ({nodes.length})
      </h3>
      <div className="chip-stack">
        {nodes.map((n) => (
          <Chip key={n.id} node={n} graph={graph} renderedIds={renderedIds} onNavigate={onNavigate} />
        ))}
      </div>
    </section>
  );
}

/** The node's data-flow neighborhood as chip stacks — `references` (upstream,
 *  first: data flows in→out and the panel reads that way) then `referenced by`
 *  (downstream). An EMPTY direction renders NOTHING (the no-claims rule: refs
 *  that form no edges exist, so an affirmative "unreferenced" would be the
 *  quiet≠unconsumed trap). */
export function ConnectionSections({
  node,
  graph,
  renderedIds,
  onNavigate,
}: {
  node: RFNode;
  graph: RFGraph;
  renderedIds: ReadonlySet<string>;
  onNavigate: (focus: string, selectedId?: string | null) => void;
}): JSX.Element {
  const shared = { graph, renderedIds, onNavigate };
  return (
    <>
      <ChipStack label="references" nodes={producersOf(graph, node.id)} {...shared} />
      <ChipStack label="referenced by" nodes={consumersOf(graph, node.id)} {...shared} />
    </>
  );
}
