import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchGraph, fetchRunNode, fetchSource, fetchVersion, runWorkflow } from "./client";
import type { RunNodeDetail } from "../types";

function mockFetch(status: number, body: unknown): void {
  globalThis.fetch = vi.fn(async () => ({
    ok: status < 400,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => vi.restoreAllMocks());

const RUN_DETAIL: RunNodeDetail = {
  node_type: "shell",
  status: "success",
  duration_ms: 5,
  cost_usd: null,
  tokens: null,
  error: null,
  input: {},
  output: null,
};

describe("fetchRunNode", () => {
  function captureFetch(body: unknown, status = 200): string[] {
    const urls: string[] = [];
    globalThis.fetch = vi.fn(async (url: string) => {
      urls.push(String(url));
      return { ok: status < 400, status, json: async () => body };
    }) as unknown as typeof fetch;
    return urls;
  }

  it("encodes the structural ref as JSON in the query and adds &run= when pinned", async () => {
    const urls = captureFetch(RUN_DETAIL);
    const ref = { node_id: "child", ancestor_path: [{ node_id: "host", batch_index: null }], port: null };
    await fetchRunNode("/wf.pflow.md", "run-1", ref);
    const url = new URL(urls[0]!, "http://x");
    expect(url.pathname).toBe("/api/run-node");
    expect(url.searchParams.get("workflow")).toBe("/wf.pflow.md");
    expect(JSON.parse(url.searchParams.get("ref")!)).toEqual(ref); // the ONE wire encoding — not a flat id
    expect(url.searchParams.get("run")).toBe("run-1");
  });

  it("omits &run= when unpinned (runId null)", async () => {
    const urls = captureFetch(RUN_DETAIL);
    await fetchRunNode("/wf.pflow.md", null, { node_id: "a", ancestor_path: [], port: null });
    expect(new URL(urls[0]!, "http://x").searchParams.has("run")).toBe(false);
  });

  it("throws ApiError on a malformed 200 shape rather than handing the panel a lie", async () => {
    mockFetch(200, { node_type: "shell" }); // missing status/input/output
    await expect(fetchRunNode("/wf", null, { node_id: "a", ancestor_path: [], port: null })).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it("surfaces a 404 (no recorded detail) as ApiError for the section's own catch", async () => {
    mockFetch(404, { error: "No recorded detail for this node in the selected run." });
    await expect(fetchRunNode("/wf", null, { node_id: "a", ancestor_path: [], port: null })).rejects.toMatchObject({
      status: 404,
    });
  });
});

describe("runWorkflow", () => {
  it("POSTs {workflow, inputs} as application/json and resolves on a 200 spawn", async () => {
    const calls: Array<[string, RequestInit]> = [];
    globalThis.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push([String(url), init]);
      return { ok: true, status: 200, json: async () => ({ status: "spawned" }) };
    }) as unknown as typeof fetch;

    await expect(runWorkflow("/wf.pflow.md", { name: "World", count: "3" })).resolves.toBeUndefined();
    const [url, init] = calls[0]!;
    expect(url).toBe("/api/run");
    expect(init.method).toBe("POST");
    // The application/json header is load-bearing for the server's no-CORS posture.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ workflow: "/wf.pflow.md", inputs: { name: "World", count: "3" } });
  });

  it("throws ApiError with the pre-flight diagnostics on a 400 (so the form shows them inline)", async () => {
    mockFetch(400, { errors: [{ message: "Workflow requires input 'name': the greeting target" }] });
    await expect(runWorkflow("/wf", {})).rejects.toMatchObject({
      status: 400,
      errors: [{ message: "Workflow requires input 'name': the greeting target" }],
    });
  });

  it("throws ApiError on a 404 unknown workflow", async () => {
    mockFetch(404, { errors: [{ message: "Workflow 'nope' not found." }] });
    await expect(runWorkflow("nope", {})).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchGraph", () => {
  it("returns the contract on a well-formed 200", async () => {
    const graph = { nodes: [], edges: [], groups: [] };
    mockFetch(200, graph);
    await expect(fetchGraph("wf")).resolves.toEqual(graph);
  });

  it("throws ApiError on a malformed 200 instead of letting buildFlow crash the render (C2a)", async () => {
    mockFetch(200, { nodes: null }); // server bug — wrong shape
    await expect(fetchGraph("wf")).rejects.toBeInstanceOf(ApiError);
  });

  it("surfaces server diagnostics on a 422", async () => {
    mockFetch(422, { errors: [{ message: "unknown node type" }] });
    await expect(fetchGraph("wf")).rejects.toMatchObject({
      status: 422,
      errors: [{ message: "unknown node type" }],
    });
  });

  it("degrades a non-JSON error body to a generic entry, never throwing raw", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    })) as unknown as typeof fetch;
    await expect(fetchGraph("wf")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchSource", () => {
  it("returns source files on a well-formed 200 and URL-encodes the workflow value", async () => {
    const source = { root: "/wf.pflow.md", files: { "/wf.pflow.md": "# Workflow\n" } };
    mockFetch(200, source);

    await expect(fetchSource("folder/wf name.pflow.md")).resolves.toEqual(source);
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/source?workflow=folder%2Fwf%20name.pflow.md");
  });

  it("throws ApiError on a malformed 200 instead of letting the pane render a lie", async () => {
    mockFetch(200, { root: 42, files: [] });
    await expect(fetchSource("wf")).rejects.toBeInstanceOf(ApiError);
  });

  it("surfaces server diagnostics on a 422", async () => {
    mockFetch(422, { errors: [{ message: "invalid workflow" }] });
    await expect(fetchSource("wf")).rejects.toMatchObject({
      status: 422,
      errors: [{ message: "invalid workflow" }],
    });
  });

  it("degrades a non-JSON error body to a generic entry, never throwing raw", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    })) as unknown as typeof fetch;
    await expect(fetchSource("wf")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchVersion", () => {
  it("returns the fingerprint on a 200 and URL-encodes the workflow value", async () => {
    mockFetch(200, { fingerprint: "abc123" });
    await expect(fetchVersion("folder/wf name.pflow.md")).resolves.toBe("abc123");
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/version?workflow=folder%2Fwf%20name.pflow.md");
  });

  it("throws ApiError on a malformed 200 (so the poll loop swallows it, never trusts a non-string)", async () => {
    mockFetch(200, { fingerprint: 42 });
    await expect(fetchVersion("wf")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError on a transport failure (the poll loop catches and keeps polling)", async () => {
    mockFetch(503, {});
    await expect(fetchVersion("wf")).rejects.toBeInstanceOf(ApiError);
  });
});
