import { describe, expect, it } from "vitest";

import { DEFAULT_VIEW, readViewParams, resolveNodeFlatId, writeViewParams } from "./viewParams";
import type { RFGraph } from "../types";

describe("readViewParams", () => {
  it("defaults to LR + beautiful + no node on an empty query", () => {
    expect(readViewParams("")).toEqual(DEFAULT_VIEW);
  });

  it("parses all view params, mapping user-facing density words inward", () => {
    expect(readViewParams("?direction=TD&density=advanced&node=fetch-data&focus=classify&collapse=all")).toEqual({
      direction: "TD",
      density: "detailed",
      node: "fetch-data",
      focus: "classify",
      collapse: "all",
    });
  });

  it("collapse= accepts only all/none; anything else means AUTO (null)", () => {
    expect(readViewParams("?collapse=none").collapse).toBe("none");
    expect(readViewParams("?collapse=maybe").collapse).toBeNull();
    expect(readViewParams("").collapse).toBeNull();
  });

  it("treats a blank focus as null", () => {
    expect(readViewParams("?focus=").focus).toBeNull();
    expect(readViewParams("").focus).toBeNull();
  });

  it("maps density=beautiful -> compact", () => {
    expect(readViewParams("?density=beautiful").density).toBe("compact");
  });

  it("falls back to defaults on invalid values (no throw)", () => {
    expect(readViewParams("?direction=sideways").direction).toBe("LR");
    expect(readViewParams("?density=fancy").density).toBe("compact");
  });

  it("treats a blank node as null", () => {
    expect(readViewParams("?node=").node).toBeNull();
    expect(readViewParams("?node=%20%20").node).toBeNull();
  });

  it("ignores unrelated params (e.g. the App-owned workflow)", () => {
    expect(readViewParams("?workflow=demo&direction=TD").direction).toBe("TD");
  });
});

describe("writeViewParams", () => {
  it("writes density as its user-facing word and preserves every other param", () => {
    const out = writeViewParams("?workflow=demo&node=x", { density: "detailed" });
    const p = new URLSearchParams(out);
    expect(p.get("density")).toBe("advanced");
    expect(p.get("workflow")).toBe("demo");
    expect(p.get("node")).toBe("x");
  });

  it("writes direction verbatim", () => {
    expect(new URLSearchParams(writeViewParams("", { direction: "TD" })).get("direction")).toBe("TD");
  });

  it("never writes the node param (it is read-only)", () => {
    expect(new URLSearchParams(writeViewParams("?node=keep", { direction: "LR" })).get("node")).toBe("keep");
  });
});

describe("resolveNodeFlatId", () => {
  const graph = {
    nodes: [
      { id: "n3", ref: { node_id: "fetch-data", ancestor_path: [], port: null } },
      { id: "n7", ref: { node_id: "summary", ancestor_path: [], port: null } },
    ],
    edges: [],
    groups: [],
  } as unknown as RFGraph;

  it("resolves a node_id to its flat id when rendered", () => {
    expect(resolveNodeFlatId(graph, new Set(["n3", "n7"]), "fetch-data")).toBe("n3");
  });

  it("falls back to treating the value as a flat id", () => {
    expect(resolveNodeFlatId(graph, new Set(["n3"]), "n3")).toBe("n3");
  });

  it("returns null when the matched node is not rendered (collapsed / suppressed)", () => {
    expect(resolveNodeFlatId(graph, new Set(), "fetch-data")).toBeNull();
  });

  it("returns null for an unknown value", () => {
    expect(resolveNodeFlatId(graph, new Set(["n3"]), "nope")).toBeNull();
  });

  it("returns null when there is no graph yet", () => {
    expect(resolveNodeFlatId(null, new Set(["n3"]), "fetch-data")).toBeNull();
  });

  // A group HOST's node is never rendered — its name must resolve to the
  // representative GROUP so focus=/node= can target containers by name.
  const hostGraph = {
    nodes: [{ id: "n5", ref: { node_id: "execute-plan", ancestor_path: [], port: null } }],
    edges: [],
    groups: [
      { id: "gshell", kind: "batch", host: "n5", members: [] }, // memberless shell — never rendered
      { id: "gwf", kind: "workflow", host: "n5", members: ["n9"] },
    ],
  } as unknown as RFGraph;

  it("resolves a group host's node_id to its representative group (skipping batch shells)", () => {
    expect(resolveNodeFlatId(hostGraph, new Set(["gwf"]), "execute-plan")).toBe("gwf");
  });

  it("prefers the rendered node itself over its group when both could match", () => {
    expect(resolveNodeFlatId(hostGraph, new Set(["n5", "gwf"]), "execute-plan")).toBe("n5");
  });

  it("returns null when neither the host nor its group is rendered", () => {
    expect(resolveNodeFlatId(hostGraph, new Set(["other"]), "execute-plan")).toBeNull();
  });
});
