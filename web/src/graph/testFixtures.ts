// Shared fixture builders for the graph package's tests (non-.test name so
// vitest doesn't collect it). Every builder fills the full contract shape with
// neutral defaults; tests override only what they assert on.

import type { BuildOptions } from "./flow";
import type { EdgeKind, RFEdge, RFGroup, RFNode } from "../types";

export function node(id: string, over: Partial<RFNode> = {}): RFNode {
  return {
    id,
    ref: { node_id: id, ancestor_path: [], port: null },
    kind: "shell",
    purpose: "",
    params: [],
    io: null,
    loop: null,
    batch: null,
    parent: null,
    source: null,
    is_decision: false,
    is_terminal: false,
    is_transform: false,
    output_shape: null,
    cached_prefix: null,
    is_group_host: false,
    unexpanded: null,
    annotations: {},
    ...over,
  };
}

export function group(id: string, over: Partial<RFGroup> = {}): RFGroup {
  return {
    id,
    kind: "workflow",
    parent: null,
    host: null,
    members: [],
    nesting_depth: 0,
    annotations: {},
    ...over,
  };
}

export function edge(id: string, source: string, target: string, kind: EdgeKind, over: Partial<RFEdge> = {}): RFEdge {
  return { id, source, target, kind, label: null, output_field: null, input_name: null, shadowed: false, condition: null, output_path: [], ...over };
}

export const DETAILED: BuildOptions = { density: "detailed", direction: "LR", collapsed: new Set() };
export const COMPACT: BuildOptions = { density: "compact", direction: "LR", collapsed: new Set() };
export const TD: BuildOptions = { density: "compact", direction: "TD", collapsed: new Set() };
