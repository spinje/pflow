import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchGate, fetchGraph, fetchRunInputs, fetchRunNode, fetchSource, fetchVersion, resumeRun, runWorkflow } from "./client";
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
  it("POSTs {workflow, inputs} as application/json and resolves with the spawned run id", async () => {
    const calls: Array<[string, RequestInit]> = [];
    globalThis.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push([String(url), init]);
      return { ok: true, status: 200, json: async () => ({ status: "spawned", run_id: "run-abc" }) };
    }) as unknown as typeof fetch;

    // Returns the run id (Task 175) so the caller can PIN the overlay to the exact run it spawned.
    await expect(runWorkflow("/wf.pflow.md", { name: "World", count: "3" })).resolves.toBe("run-abc");
    const [url, init] = calls[0]!;
    expect(url).toBe("/api/run");
    expect(init.method).toBe("POST");
    // The application/json header is load-bearing for the server's no-CORS posture.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ workflow: "/wf.pflow.md", inputs: { name: "World", count: "3" } });
  });

  it("throws ApiError when a 200 omits the run id (the pin needs it — don't silently resolve)", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ status: "spawned" }),
    })) as unknown as typeof fetch;
    await expect(runWorkflow("/wf", {})).rejects.toBeInstanceOf(ApiError);
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

describe("fetchRunInputs", () => {
  it("GETs /api/run-inputs with workflow + run, and resolves the token-string map", async () => {
    let calledUrl = "";
    globalThis.fetch = vi.fn(async (url: string) => {
      calledUrl = url;
      return { ok: true, status: 200, json: async () => ({ name: "World", count: "3" }) };
    }) as unknown as typeof fetch;
    await expect(fetchRunInputs("/wf.pflow.md", "run-1")).resolves.toEqual({ name: "World", count: "3" });
    expect(calledUrl).toContain("/api/run-inputs?");
    expect(calledUrl).toContain("workflow=");
    expect(calledUrl).toContain("run=run-1");
  });

  it("throws ApiError on a 404 (unknown workflow/run) for the panel's own catch", async () => {
    mockFetch(404, { error: "No recorded inputs for the selected run." });
    await expect(fetchRunInputs("/wf", "ghost")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError on a non-object 200 rather than feeding the form a bad shape", async () => {
    mockFetch(200, ["not", "an", "object"]);
    await expect(fetchRunInputs("/wf", "run-1")).rejects.toBeInstanceOf(ApiError);
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

describe("fetchGate (Task 176)", () => {
  const GATE = {
    paused_node_id: "deploy",
    gate_kind: "action_approval",
    gate_request: {
      node_id: "deploy",
      node_type: "shell",
      kind: "action_approval",
      preview: { command: "./deploy.sh" },
      question: null,
      options: [],
      recommendation: null,
    },
  };

  it("GETs /api/gate?run= (URL-encoded) and resolves the gate payload", async () => {
    mockFetch(200, GATE);
    await expect(fetchGate("run 1")).resolves.toEqual(GATE);
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/gate?run=run%201");
  });

  it("throws ApiError on a malformed 200 shape rather than handing the panel a lie", async () => {
    mockFetch(200, { paused_node_id: "deploy", gate_kind: "action_approval" }); // no gate_request
    await expect(fetchGate("r1")).rejects.toBeInstanceOf(ApiError);
  });

  it("surfaces a 404's singular {error} body — the REAL /api/gate wire shape — as a readable diagnostic", async () => {
    // The gate 404s use the house singular shape (server.py `_json({"error": ...})`), NOT the
    // plural errors array; parseErrorBody must surface the text (review-caught: it used to
    // collapse to the generic "Server returned HTTP 404." and the panel lost the reason).
    mockFetch(404, { error: "Run 'r1' is not paused at a gate." });
    await expect(fetchGate("r1")).rejects.toMatchObject({
      status: 404,
      errors: [{ message: "Run 'r1' is not paused at a gate." }],
    });
  });
});

describe("resumeRun (Task 176)", () => {
  function captureCalls(status: number, body: unknown): Array<[string, RequestInit]> {
    const calls: Array<[string, RequestInit]> = [];
    globalThis.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push([String(url), init]);
      return { ok: status < 400, status, json: async () => body };
    }) as unknown as typeof fetch;
    return calls;
  }

  it("POSTs the answer as application/json and resolves with the new attempt's run id (the pin)", async () => {
    const calls = captureCalls(200, { status: "spawned", run_id: "attempt-2" });
    await expect(resumeRun({ run: "r1", approve: "yes" })).resolves.toBe("attempt-2");
    const [url, init] = calls[0]!;
    expect(url).toBe("/api/resume");
    expect(init.method).toBe("POST");
    // The application/json header is load-bearing for the server's no-CORS posture.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    // approve rides verbatim; force is ABSENT unless the caller acked a dialog (the server never adds it).
    expect(JSON.parse(init.body as string)).toEqual({ run: "r1", approve: "yes" });
  });

  it("passes choose and force through verbatim", async () => {
    const calls = captureCalls(200, { status: "spawned", run_id: "attempt-3" });
    await resumeRun({ run: "r1", choose: "Ship it", force: true });
    expect(JSON.parse(calls[0]![1].body as string)).toEqual({ run: "r1", choose: "Ship it", force: true });
  });

  it("throws ApiError carrying the refusal discriminator on `.body` — read from ONE parse (a re-read throws)", async () => {
    // Pins the single-read rule: a real Response body can be consumed once. The mock throws on a
    // second json() call, so an implementation that parses errors and then re-reads for `.body`
    // fails here (collapsing every refusal to the generic arm — the bug this guards against).
    let reads = 0;
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => {
        if (++reads > 1) throw new TypeError("Body is already consumed.");
        return { errors: [{ message: "already resumed" }], refusal: "superseded", newer_execution_id: "run-9" };
      },
    })) as unknown as typeof fetch;
    await expect(resumeRun({ run: "r1", approve: "yes" })).rejects.toMatchObject({
      status: 409,
      errors: [{ message: "already resumed" }],
      body: expect.objectContaining({ refusal: "superseded", newer_execution_id: "run-9" }),
    });
  });

  it("surfaces a shape-400's singular {error} body (the house shape) instead of the generic line", async () => {
    mockFetch(400, { error: "Fields 'approve' and 'choose' are mutually exclusive — one flag per gate kind." });
    await expect(resumeRun({ run: "r1" })).rejects.toMatchObject({
      status: 400,
      errors: [{ message: "Fields 'approve' and 'choose' are mutually exclusive — one flag per gate kind." }],
    });
  });

  it("falls back to a generic entry (body undefined) on a non-JSON refusal", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => {
        throw new SyntaxError("not JSON");
      },
    })) as unknown as typeof fetch;
    await expect(resumeRun({ run: "r1" })).rejects.toMatchObject({
      status: 500,
      errors: [{ message: "Server returned HTTP 500." }],
      body: undefined,
    });
  });

  it("throws ApiError when a 200 omits the run id (the pin needs it — don't silently resolve)", async () => {
    mockFetch(200, { status: "spawned" });
    await expect(resumeRun({ run: "r1" })).rejects.toBeInstanceOf(ApiError);
  });
});
