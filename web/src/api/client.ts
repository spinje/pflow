// The single data-loading seam. Today it hits the static /api/* endpoints; a
// future live-run overlay (Task 168 deferred increment) adds an events
// subscription HERE — the components never learn where data comes from.

import type { ApiErrorBody, CatalogItem, RFGraph, SourceFiles } from "../types";

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
