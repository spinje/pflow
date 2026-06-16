import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchGraph, fetchSource, fetchVersion } from "./client";

function mockFetch(status: number, body: unknown): void {
  globalThis.fetch = vi.fn(async () => ({
    ok: status < 400,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => vi.restoreAllMocks());

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
