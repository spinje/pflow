// The single data-loading seam. Today it hits the static /api/* endpoints; a
// future live-run overlay (Task 168 deferred increment) adds an events
// subscription HERE — the components never learn where data comes from.

import type { ApiErrorBody, CatalogItem, RFGraph, RFRef, RunInfo, RunNodeDetail, SourceFiles } from "../types";

/** A structured /api failure (400 missing param / 422 validation). Carries the
 *  server's diagnostics so the UI can render them instead of a blank canvas. */
export class ApiError extends Error {
  readonly status: number;
  readonly errors: ApiErrorBody["errors"];

  constructor(status: number, errors: ApiErrorBody["errors"]) {
    const first = errors[0];
    super(first?.message ?? first?.title ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody["errors"]> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (Array.isArray(body?.errors) && body.errors.length > 0) {
      return body.errors;
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
 *  Resolves on a 200 spawn; throws ApiError on a 400 (malformed body OR a pre-flight
 *  failure carrying actionable diagnostics in `.errors`) / 404 (unknown workflow), so
 *  the form surfaces the diagnostics inline (DR-6) — never blanks the canvas. Uses
 *  this typed-error client (not the fire-and-forget events.ts POSTs); the
 *  application/json header is load-bearing for the server's no-CORS posture. */
export async function runWorkflow(workflow: string, inputs: Record<string, string>): Promise<void> {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow, inputs }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response));
  }
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
