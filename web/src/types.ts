// Hand-mirrored TypeScript view of the Python wire contract
// (src/pflow/core/workflow/graph/renderers/react_flow.py). This is the single
// shape both ends agree on; codegen from a JSON Schema is a deferred nicety
// (task-168.md). Keep field names byte-identical with the dataclasses.

export interface SourceRef {
  file: string | null;
  line: number | null;
}

export interface AncestorStepRef {
  node_id: string;
  batch_index: number | null;
}

export interface RFRef {
  node_id: string;
  ancestor_path: AncestorStepRef[];
  port: "in" | "out" | null;
}

export interface RFParam {
  name: string;
  // JSON-able authored value: string (incl. full prompt/code), number, bool,
  // list, dict, or null. `is_dynamic` says whether it carries a ${ref}.
  value: unknown;
  is_dynamic: boolean;
  source: SourceRef | null;
}

export interface LoopSpec {
  polarity: "while" | "until";
  condition: string;
  cap: number | string | null;
  carry: Record<string, string>;
}

export interface BatchSpec {
  parallel: boolean;
  dynamic: boolean;
  as_name: string;
  source_ref: string | null;
  count: number | null;
  items: unknown[] | null;
}

export interface IOPort {
  data_type: string | null;
  required: boolean;
}

export type UnexpandedReason = "depth_limit" | "unresolved" | "dynamic_path" | "cycle";

export interface RFNode {
  id: string;
  ref: RFRef;
  kind: string;
  purpose: string;
  params: RFParam[];
  io: IOPort | null;
  loop: LoopSpec | null;
  batch: BatchSpec | null;
  parent: string | null;
  source: SourceRef | null;
  is_decision: boolean;
  is_terminal: boolean;
  is_group_host: boolean;
  // A pure data TRANSFORM: a code node whose AST provably only reshapes inputs
  // into `result` (no effects, no routing). Classified FAIL-CLOSED in Python
  // (react_flow.py _is_transform_code) — the frontend cannot derive this one.
  is_transform: boolean;
  unexpanded: UnexpandedReason | null;
  annotations: Record<string, unknown>;
}

export type EdgeKind = "sequential" | "branch" | "error" | "data_flow" | "end";

export interface RFEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  label: string | null;
  output_field: string | null;
  input_name: string | null;
  shadowed: boolean;
  // Source condition selecting this branch outcome ("if len(items) > 5" / "else"),
  // extracted fail-closed in Python (react_flow.py). null on non-branch edges and
  // whenever extraction couldn't be done safely.
  condition: string | null;
}

export type ContainerKind = "workflow" | "batch" | "input_wrapper" | "output_wrapper";

export interface RFGroup {
  id: string;
  kind: ContainerKind;
  parent: string | null;
  host: string | null;
  members: string[];
  nesting_depth: number;
  annotations: Record<string, unknown>;
}

export interface RFGraph {
  nodes: RFNode[];
  edges: RFEdge[];
  groups: RFGroup[];
}

export interface CatalogItem {
  name: string;
  description: string;
  path: string;
}

// The /api error envelope (400/422). Each entry is a Diagnostic.to_dict() on 422,
// or a single {message} on 400 (see src/pflow/ui/server.py).
export interface ApiErrorEntry {
  message?: string;
  title?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface ApiErrorBody {
  errors: ApiErrorEntry[];
}
