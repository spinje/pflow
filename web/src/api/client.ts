// The single data-loading seam. Today it hits the static /api/* endpoints; a
// future live-run overlay (Task 168 deferred increment) adds an events
// subscription HERE — the components never learn where data comes from.

import type { ApiErrorBody, CatalogItem, GateInfo, RFGraph, RFRef, RunInfo, RunNodeDetail, SourceFiles } from "../types";

/** A structured /api failure (400 missing param / 422 validation). Carries the
 *  server's diagnostics so the UI can render them instead of a blank canvas. */
export class ApiError extends Error {
  readonly status: number;
  readonly errors: ApiErrorBody["errors"];
  // The RAW parsed refusal body (Task 176): /api/resume 4xxs carry a machine-readable
  // `refusal` discriminator + kind-specific extras (`newer_execution_id`, `node_id`/
  // `node_type`, `hash_known`) BESIDE `errors` — reachable here so the panels never
  // string-parse a diagnostic. Undefined for endpoints that only send `errors`.
  readonly body?: Record<string, unknown>;

  constructor(status: number, errors: ApiErrorBody["errors"], body?: Record<string, unknown>) {
    const first = errors[0];
    super(first?.message ?? first?.title ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
    this.body = body;
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody["errors"]> {
  try {
    const body = (await response.json()) as ApiErrorBody & { error?: unknown };
    if (Array.isArray(body?.errors) && body.errors.length > 0) {
      return body.errors;
    }
    // The server's OTHER error shape: shape-validation 4xxs send a singular {"error": "<text>"}
    // (house convention across /api/gate 404s, /api/command, the JSON-POST preflight …). Surface
    // the text instead of collapsing it to the generic HTTP line — the panels render these inline
    // (Task 176 review finding: /api/gate's "not paused" message was being dropped).
    if (typeof body?.error === "string" && body.error) {
      return [{ message: body.error }];
    }
  } catch {
    // Non-JSON body (e.g. a 500 HTML page) — fall through to a generic entry.
  }
  return [{ message: `Server returned HTTP ${response.status}.` }];
}

export async function fetchCatalog(): Promise<CatalogItem[]> {
  const response = await fetch("/api/catalog");
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  return (await response.json()) as CatalogItem[];
}

function isRFGraph(value: unknown): value is RFGraph {
  if (!value || typeof value !== "object") return false;
  const g = value as Record<string, unknown>;
  return Array.isArray(g.nodes) && Array.isArray(g.edges) && Array.isArray(g.groups);
}

function isSourceFiles(value: unknown): value is SourceFiles {
  if (!value || typeof value !== "object") return false;
  const body = value as Record<string, unknown>;
  if (body.root !== null && typeof body.root !== "string") return false;
  if (!body.files || typeof body.files !== "object" || Array.isArray(body.files)) return false;
  return Object.values(body.files).every((text) => typeof text === "string");
}

export async function fetchGraph(workflow: string): Promise<RFGraph> {
  const response = await fetch(`/api/graph?workflow=${encodeURIComponent(workflow)}`);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  // A 200 should always be the contract shape; validate rather than cast a lie, so
  // a server bug surfaces as a banner here (the caught path) instead of throwing
  // deep inside buildFlow's render and white-screening the app.
  const body = (await response.json()) as unknown;
  if (!isRFGraph(body)) {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected graph shape." }]);
  }
  return body;
}

/** A cheap change-fingerprint over the workflow's source files. The frontend
 *  polls this; when it changes, the graph is re-fetched in place (no reload).
 *  The server never errors this for an invalid workflow (it falls back to the
 *  entry file), so a non-200 here is a genuine transport failure — the caller
 *  (the poll loop) swallows it and keeps polling. */
export async function fetchVersion(workflow: string): Promise<string> {
  const response = await fetch(`/api/version?workflow=${encodeURIComponent(workflow)}`);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as { fingerprint?: unknown };
  if (typeof body.fingerprint !== "string") {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected version shape." }]);
  }
  return body.fingerprint;
}

export async function fetchSource(workflow: string): Promise<SourceFiles> {
  const response = await fetch(`/api/source?workflow=${encodeURIComponent(workflow)}`);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as unknown;
  if (!isSourceFiles(body)) {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected source shape." }]);
  }
  return body;
}

/** Runs from the trace dir (Task 173 D6). No arg → every run; `workflow` → that workflow's history.
 *  Each consumer (catalog badge, run selector, dashboard) owns its own catch (DR-6) so a runs-fetch
 *  failure degrades that one surface, never blanks the page. */
export async function fetchRuns(workflow?: string): Promise<RunInfo[]> {
  const url = workflow ? `/api/runs?workflow=${encodeURIComponent(workflow)}` : "/api/runs";
  const response = await fetch(url);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as unknown;
  if (!Array.isArray(body)) {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected runs shape." }]);
  }
  return body as RunInfo[];
}

/** Spawn a detached `pflow run` for `workflow` with `inputs` (Task 175). `inputs`
 *  values are TOKEN STRINGS — they become the CLI's `name=value` argv verbatim
 *  (channel A: the spawned run's infer_type + declared-type coercion re-type them).
 *  Resolves with the spawned run's `run_id` (Task 175 — the server mints it so the
 *  caller can PIN the overlay to the exact run, not follow-newest); throws ApiError on
 *  a 400 (malformed body OR a pre-flight failure carrying actionable diagnostics in
 *  `.errors`) / 404 (unknown workflow), so the form surfaces the diagnostics inline
 *  (DR-6) — never blanks the canvas. Uses this typed-error client (not the
 *  fire-and-forget events.ts POSTs); the application/json header is load-bearing for
 *  the server's no-CORS posture. */
export async function runWorkflow(workflow: string, inputs: Record<string, string>): Promise<string> {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow, inputs }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as { run_id?: unknown };
  if (typeof body.run_id !== "string") {
    throw new ApiError(response.status, [{ message: "The server did not return a run id for the launch." }]);
  }
  return body.run_id;
}

function isGateInfo(value: unknown): value is GateInfo {
  if (!value || typeof value !== "object") return false;
  const g = value as Record<string, unknown>;
  if (typeof g.paused_node_id !== "string") return false;
  if (g.gate_kind !== "action_approval" && g.gate_kind !== "decision_escalation") return false;
  const req = g.gate_request as Record<string, unknown> | null | undefined;
  // The essentials only — escalation fields are optional by contract (render leniently).
  return !!req && typeof req === "object" && typeof req.node_id === "string" && typeof req.kind === "string";
}

/** A paused run's gate payload (Task 176): GET /api/gate, on demand when the gate panel
 *  opens — the bulky `gate_request` deliberately never rides the SSE wire or /api/runs
 *  (only the small `paused_node_id` does). The `preview` arrives secret-masked server-side.
 *  Throws ApiError on 400 (missing param) / 404 (unknown run, or not paused at a gate —
 *  e.g. answered elsewhere between the banner and this fetch); the caller renders the
 *  diagnostics inline (DR-6), never blanks the canvas. */
export async function fetchGate(run: string): Promise<GateInfo> {
  const response = await fetch(`/api/gate?run=${encodeURIComponent(run)}`);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as unknown;
  if (!isGateInfo(body)) {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected gate shape." }]);
  }
  return body;
}

/** Answer a paused gate — or resume a failed/interrupted run — by spawning a detached
 *  `pflow resume` (Task 176): POST /api/resume, ONE endpoint mirroring the CLI verb.
 *  `approve`/`choose` are mutually exclusive; `force` is sent ONLY after an explicit ack
 *  dialog (stale-workflow / side-effect confirmation — the server never adds it itself).
 *  Resolves with the spawned attempt's run_id (server-minted, like runWorkflow) so the
 *  caller PINS the overlay to the exact new attempt. A refusal throws ApiError with the
 *  machine-readable `refusal` discriminator + extras on `.body` — the response body is
 *  read ONCE (a second .json() on a consumed body throws, silently collapsing every
 *  refusal to the generic inline-errors arm). The application/json header is load-bearing
 *  for the server's no-CORS posture. */
export async function resumeRun(req: {
  run: string;
  approve?: "yes" | "no";
  choose?: string;
  force?: boolean;
}): Promise<string> {
  const response = await fetch("/api/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    // SINGLE READ: derive both `errors` and the raw `body` from one parse. Shape-validation
    // 400s use the singular {"error": ...} house shape — surface it like parseErrorBody does.
    const parsed = (await response.json().catch(() => null)) as Record<string, unknown> | null;
    const errors =
      parsed && Array.isArray(parsed.errors) && parsed.errors.length > 0
        ? (parsed.errors as ApiErrorBody["errors"])
        : parsed && typeof parsed.error === "string" && parsed.error
          ? [{ message: parsed.error }]
          : [{ message: `Server returned HTTP ${response.status}.` }];
    throw new ApiError(response.status, errors, parsed ?? undefined);
  }
  const body = (await response.json()) as { run_id?: unknown };
  if (typeof body.run_id !== "string") {
    throw new ApiError(response.status, [{ message: "The server did not return a run id for the resume." }]);
  }
  return body.run_id;
}

function isRunNodeDetail(value: unknown): value is RunNodeDetail {
  if (!value || typeof value !== "object") return false;
  const d = value as Record<string, unknown>;
  return typeof d.node_type === "string" && typeof d.status === "string" && "input" in d && "output" in d;
}

/** ONE node's runtime record for the detail panel's "This run" section (Task 173). `ref` is the structural
 *  RFRef — the SAME identity the overlay joins on (sameRef) — JSON-encoded in the query, never a positional
 *  flat id (which renumbers). `runId` set → the pinned run; null → the newest live trace. The caller
 *  (ThisRunSection) owns its own catch (DR-6) so a failure degrades that one section, never the panel. */
export async function fetchRunNode(workflow: string, runId: string | null, ref: RFRef): Promise<RunNodeDetail> {
  const params = new URLSearchParams({ workflow, ref: JSON.stringify(ref) });
  if (runId) params.set("run", runId);
  const response = await fetch(`/api/run-node?${params.toString()}`);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as unknown;
  if (!isRunNodeDetail(body)) {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected run-node shape." }]);
  }
  return body;
}

/** A past run's recorded inputs as form-ready TOKEN STRINGS, for the Run panel's re-run prefill (Task 175).
 *  `{ "<name>": "<token>" }` — the run's `meta.inputs` with sensitive-named keys OMITTED server-side (a past
 *  run's resolved secret never reaches the browser) and each value rendered back to its CLI token. The
 *  caller (RunPanel) owns its catch (DR-6): a failed prefill leaves the current values, never blanks the
 *  form. `404` (unknown workflow/run) throws ApiError; an older trace with no recorded inputs resolves `{}`. */
export async function fetchRunInputs(workflow: string, runId: string): Promise<Record<string, string>> {
  const response = await fetch(`/api/run-inputs?${new URLSearchParams({ workflow, run: runId }).toString()}`);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
  const body = (await response.json()) as unknown;
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new ApiError(response.status, [{ message: "The server returned an unexpected run-inputs shape." }]);
  }
  return body as Record<string, string>;
}
