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

// --- Live execution overlay (Task 173) ---------------------------------------------------------
// A node's display state. `pending` (not started) is the ABSENCE of a status — only these four
// arrive on the wire (the producer's per-node status enum + the live `node.start` → `running`).
// "stopped" is consumer-derived (Task 173 flock): a node still `running` when the run's process exited
// without finishing (crash/kill) — the server's `run-stopped` flips it (the producer never emits it).
// "unrecorded" is also consumer-derived (Task 173 replay): in a STALE, completed replay, a current-graph
// node the pinned run has NO state for (renamed/new since, or an untaken branch in that version) — "no
// recorded state for this version", distinct from pending. Neither rides the wire.
export type NodeStatus = "running" | "success" | "cached" | "failed" | "stopped" | "unrecorded";

// The cheap run metrics carried alongside a node's status (already on the wire — RunEvent below) for the
// badge's hover detail. `null`/absent when not applicable (a running node has no duration yet; a non-LLM
// node has no cost). Kept separate from `status` so the badge glyph/color stay status-only.
export interface RunDetail {
  durationMs?: number | null;
  costUsd?: number | null;
}

// A node's overlay run state: the status (drives the badge) + its hover metrics + the source event id. The
// overlay's status map is keyed by structural ref-key → this; `applyStatus` splits status/metrics onto
// `data.status` + `data.runDetail`. `id` is the source RunEvent id — a per-completion discriminator the
// detail panel keys its refetch on, so a loop re-completing the SAME node (same ref + status) still refreshes
// (PR #543); absent on synthesized states (a snapshot's dangling→stopped) and on idle/test fixtures.
export interface NodeRunState extends RunDetail {
  status: NodeStatus;
  id?: number | null;
}

// One run-event the overlay joins onto a graph node by its structural `ref` (node_id + ancestor_path
// + port=null), via sameRef/refKey. Carries only the join key + status (+ cheap cost/duration) — never
// node_output (may be large/blob) and never the raw node_type (a Python class name).
export interface RunEvent {
  id: number | null;
  ref: RFRef;
  status: NodeStatus;
  duration_ms?: number | null;
  cost_usd?: number | null;
}

// The run.complete trailer, surfaced as the run banner. `final_status` is the run outcome
// (`success` | `degraded` | `failed`) — distinct from any single node's status.
export interface RunComplete {
  final_status?: string;
  // The run.complete wire is a 4-field allowlist (run_tailer._RUN_COMPLETE_FIELDS); duration_ms / json_output
  // / warnings are deliberately NOT carried on the live SSE wire or the snapshot. Add a field here only after
  // adding it to that allowlist, or it is silently dropped at the projection.
  nodes_executed?: number;
  nodes_failed?: number;
  failed_node_ids?: string[];
}

// One run from GET /api/runs (Task 173 D6) — the catalog running-indicator + the run selector read this.
// RAW facts (the UI composes the badge): `complete` has a run.complete trailer; `final_status` is that
// trailer's outcome or null while not complete; `live` = not complete AND the writer still holds the trace's
// advisory lock (EXACT flock liveness, not the old mtime heuristic); `only_node` labels an --only run.
// `workflow_path` is `ir-hash:<md5>` for inline/stdin/MCP runs (a content fingerprint, NOT a file) — `null`
// only for a malformed/legacy trace lacking the field.
export interface RunInfo {
  run_id: string;
  workflow_name: string;
  workflow_path: string | null;
  start_time: string;
  complete: boolean;
  final_status: string | null;
  live: boolean;
  only_node: string | null;
  trace_file: string;
  // The git-repo root this run's file lives under (server-side detection, cached) — the catalog buckets
  // ad-hoc runs by repo. `null` for an inline (`ir-hash:`) / pathless run or a file under no repo ("Other").
  git_root: string | null;
}

// The detail panel's "This run" section reads this from GET /api/run-node (Task 173 D6) — ONE node's
// runtime record off its trace, the interactive single-node counterpart of `pflow report`. WIRE field
// names (snake_case), matching RunEvent above — NOT NodeRunState's camelCase (a derived in-app type).
// `node_type` is the tagged kind (NEVER the raw Python class); `input`/`output` are the realized
// (post-`${...}`) payloads with secrets redacted; `cost_usd` is the node's OWN paid cost (the shared
// event_cost — a cached node → 0). `tokens` / `cost_usd` / `error` are null when not applicable.
export interface RunNodeDetail {
  node_type: string;
  status: string;
  duration_ms: number;
  cost_usd: number | null;
  tokens: { input: number; output: number; cache_read: number } | null;
  error: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown> | string | null;
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
  // The authored `default:` value verbatim; null when absent.
  default: unknown;
}

export type UnexpandedReason = "depth_limit" | "unresolved" | "dynamic_path" | "cycle";

export interface RFResultKey {
  name: string;
  data_type: string | null;
}

// The authored shape of a node's structured output, extracted FAIL-CLOSED in
// Python (react_flow.py): `field` names the output port the shape describes —
// where the node actually WRITES ("result" for code/claude-code, "response"
// for structured llm). `data_type` is the authored annotation / schema type;
// `keys` are authored keys with best-effort types — null whenever not
// statically certain, never a partial list. A non-null shape with data_type
// AND keys null is valid: it asserts only "provably assigns `result`".
export interface RFOutputShape {
  field: string;
  data_type: string | null;
  keys: RFResultKey[] | null;
}

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
  // Ships for ALL code nodes (not just transforms); null on non-code nodes and
  // whenever nothing is provable.
  output_shape: RFOutputShape | null;
  // The cached system prefix as authored TEMPLATE text: per consumed `## Cache`
  // chunk (declaration order), prose_before + ${var} — the runtime's assembly
  // rule, so the panel can show the prompt as the model receives it. Null when
  // the node consumes no chunks.
  cached_prefix: string | null;
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
  // The ref's sub-path below output_field: `${gen.result.ok}` ships ["ok"].
  // Empty whenever output_field is absent or cleared by truncation re-anchoring.
  output_path: string[];
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
  // kind -> output field -> declared type (the registry's parsed docstring
  // interfaces), for kinds present in this graph. The LAST type fallback on
  // output rows that already exist — never creates a row; authored shapes win.
  kind_output_types?: Record<string, Record<string, string>>;
}

// Live Point command descriptors. These mirror src/pflow/ui/targets.py and
// deliberately contain structural refs only — positional flat ids are local to
// one render and must never cross the SSE channel.
export interface PointNodeTarget {
  kind: "node";
  ref: RFRef;
}

export interface PointEdgeTarget {
  kind: "edge";
  source: RFRef;
  source_field: string | null;
  source_path: string[];
  target: RFRef;
  input_name: string | null;
}

export type PointTarget = PointNodeTarget | PointEdgeTarget;

export interface InteractionViewState {
  density: "advanced" | "beautiful";
  direction: "LR" | "TD";
  focus: string | null;
}

export type InteractionTarget =
  | (PointNodeTarget & { flat_id: string })
  | (PointEdgeTarget & { flat_id: string });

export interface InteractionReport {
  type: string;
  target?: InteractionTarget;
  view_state: InteractionViewState;
}

export interface SourceFiles {
  root: string | null;
  files: Record<string, string>;
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
