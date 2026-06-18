# Inspect pflow web UI geometry

Read the **real rendered geometry** of the pflow web UI canvas — every node's box, icon
tile, connector stubs, and handles, plus every edge's path rect — as structured JSON.
The companion to the screenshot tool: a screenshot is for *eyeballing*, this is for
*measuring* and *asserting* (does an edge endpoint land inside its target handle? is the
connector flush with the tile? do two nodes overlap?). It answers geometry questions in
exact pixels that jsdom provably cannot (React Flow renders no edge DOM under jsdom).

Shares the load-bearing `open + settle` core with the screenshot tool via the
`shared/open-and-settle.pflow.md` sub-workflow, then runs a single `evaluate_script` that
dumps the canvas geometry from the settled DOM.

All rects are **screen-space** `getBoundingClientRect` (so the viewport zoom is baked in
— divide by the viewport scale for CSS px). That keeps connector-vs-edge-vs-tile gaps
directly comparable in the same coordinate space.

Prerequisites: the `pflow ui` server running on the URL's port, and the chrome-devtools
MCP server synced (`pflow mcp sync chrome-devtools`). After any `web/` change, rebuild
the bundle (`make ui-build`) — the server serves the built `static/`, not the source.

## Inputs

### url

Full pflow-UI URL to inspect, including the view params (same vocabulary as the
screenshot tool: `workflow` required, `direction=LR|TD`, `density=beautiful|advanced`,
`node=<node_id>`). Frame on a node (`node=`) for a tight geometry read of one node.

- type: string
- required: true

## Outputs

### geometry

Pure-JSON canvas geometry — run with `-p -o geometry` to print just this (no progress, no
header) and pipe to `jq`. Shape: `{ scale, nodes: [...], edges: [...] }` — see the field
reference in the skill.

- source: ${clean.result}
- stdout: true

### viewport

The settled viewport transform (proof the fit applied), from the shared sub-workflow.

- source: ${prepare.transform}

## Steps

### prepare

Open the URL and poll until the canvas has settled — the shared `open + settle` core
(`shared/open-and-settle.pflow.md`), reused by the screenshot tool too. It leaves the MCP
Chrome on the opened, settled page; `measure` below reads that same page (the page
persists across the sub-workflow boundary in the shared MCP browser).

- type: workflow
- workflow: ./shared/open-and-settle.pflow.md
- inputs:
    url: ${url}

### measure

Read screen-space rects for every node's box, tile, connector stubs, and handles, and
every edge's path — so connector↔edge and connector↔tile gaps are exact numbers, not
guesses. Also reports the viewport `scale` so rendered px can be converted to CSS px.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const r = (el) => {
        if (!el) return null;
        const b = el.getBoundingClientRect();
        return {
          top: Math.round(b.top), bottom: Math.round(b.bottom),
          left: Math.round(b.left), right: Math.round(b.right),
          w: Math.round(b.width), h: Math.round(b.height),
        };
      };
      const vp = document.querySelector(".react-flow__viewport");
      const m = vp && vp.style.transform.match(/scale\(([\d.]+)\)/);
      const scale = m ? Number(m[1]) : 1;
      const out = { scale, nodes: [], edges: [] };
      for (const nodeEl of document.querySelectorAll(".react-flow__node")) {
        const inner = nodeEl.querySelector(".node");
        const kindClass = inner ? [...inner.classList].find((c) => c.startsWith("kind-")) || "" : "";
        const nameEl = nodeEl.querySelector(".node-name");
        const handles = [...nodeEl.querySelectorAll(".react-flow__handle")].map((h) => ({
          type: h.classList.contains("source") ? "source" : h.classList.contains("target") ? "target" : "?",
          rect: r(h),
        }));
        out.nodes.push({
          dataId: nodeEl.getAttribute("data-id"),
          nodeId: nameEl ? nameEl.getAttribute("title") : null,
          kind: kindClass,
          offsetHeight: inner ? inner.offsetHeight : null,
          nodeRect: r(inner || nodeEl),
          tile: r(nodeEl.querySelector(".node-tile")),
          connTop: r(nodeEl.querySelector(".node-connector-top")),
          connBottom: r(nodeEl.querySelector(".node-connector-bottom")),
          handles,
        });
      }
      for (const edgeEl of document.querySelectorAll(".react-flow__edge")) {
        const path = edgeEl.querySelector("path.react-flow__edge-path") || edgeEl.querySelector("path");
        out.edges.push({ id: edgeEl.getAttribute("data-id"), pathRect: r(path) });
      }
      return out;
    }

### clean

Strip the chrome-devtools "Script ran on page and returned" wrapper off the measure
result and re-emit pure JSON (the JSON is the only brace-delimited span in the wrapper),
so the `geometry` output pipes straight to `jq` with no escaping.

- type: code
- inputs:
    raw: ${measure.result}

```python code
raw: str

import json

start = raw.find("{")
end = raw.rfind("}")
result: str = json.dumps(json.loads(raw[start : end + 1])) if start != -1 else "{}"
```
