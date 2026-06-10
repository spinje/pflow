---
name: screenshot-pflow-web-ui
description: Screenshot or measure the running pflow web UI (the React Flow canvas; web/ → src/pflow/ui) to verify frontend changes. Use after changing web/ UI code.
---

# pflow web UI: screenshot + inspect

Two workflows. Both drive the chrome-devtools MCP Chrome and **wait until the React Flow
canvas has settled** (ELK + fitView) before acting. Pass a full UI URL.

- **`screenshot.pflow.md`** → a settled full-page PNG. Eyeball the rendered canvas.
- **`inspect.pflow.md`** → JSON geometry: every node's box/tile/connector/handle rect +
  every edge's path rect + the viewport `scale`. Measure exact pixels (e.g. does an edge
  endpoint land on its target handle? is a connector flush with the tile?).

## URL params

Base `http://127.0.0.1:<port>/` (default port 8765). Source: `web/src/utils/viewParams.ts`.

| param | values | default | meaning |
|---|---|---|---|
| `workflow` | saved name, or `.pflow.md` path relative to the server's cwd | required | which workflow |
| `direction` | `LR` \| `TD` | `LR` | layout direction |
| `density` | `beautiful` \| `advanced` | `beautiful` | node density |
| `node` | a `node_id` (or flat id) | whole graph | frame the camera on one node — needed for small geometry (a connector/handle) |
| `focus` | a `node_id` (or flat id) | none | apply the click-focus state on load: dim non-incident, reveal data lines, (beautiful) expand the card + its data-flow endpoints to rows — the only way to capture the focused/expanded state without driving the UI |

## Before running

1. Server on the URL's port (reuse if up, else start and wait — safe to re-run):
   ```bash
   curl -sf http://127.0.0.1:8765/api/catalog >/dev/null 2>&1 \
     || { uv run pflow ui --no-open --port 8765 & \
          for i in $(seq 1 20); do curl -sf http://127.0.0.1:8765/api/catalog >/dev/null 2>&1 && break; sleep 0.3; done; }
   ```
2. Rebuild after ANY `web/` change (the server serves the built bundle, not source):
   ```bash
   make ui-build
   ```

## Run

Single-quote the URL so the shell doesn't split on `&`.

Screenshot — `-p` makes stdout JUST the PNG path (no progress/header — saves tokens; errors
still print + exit 1); then `Read` it:
```bash
uv run pflow examples/real-workflows/screenshot-pflow-web-ui/screenshot.pflow.md \
  url='http://127.0.0.1:8765/?workflow=<name|path>&direction=TD&density=beautiful&node=<node_id>' \
  [out_dir=/tmp/pflow-shots] -p
```

Inspect — stdout is the geometry JSON; pipe to `jq`:
`-p -o geometry` prints just the JSON (no progress, no header) → pipe straight to `jq`:
```bash
uv run pflow examples/real-workflows/screenshot-pflow-web-ui/inspect.pflow.md \
  url='http://127.0.0.1:8765/?workflow=<name|path>&direction=TD&density=beautiful&node=<node_id>' \
  -p -o geometry | jq '<filter>'
```

Both reuse `shared/open-and-settle.pflow.md` (open + poll-until-settled).

## inspect output

~1K tokens for a small graph, ~11K for a big one in advanced — so **filter with `jq`
in-shell**, never read it whole. Every `rect` is `{top,bottom,left,right,w,h}` in screen
px (= CSS px × `scale`); `null` when the element is absent:

```
{ scale,
  nodes: [{ dataId, nodeId, kind, offsetHeight,
            nodeRect, tile, connTop, connBottom,           // rects (connTop/Bottom: the TD connector stubs)
            handles: [{ type: "source"|"target", rect }] }],
  edges: [{ id, pathRect }] }                              // pathRect = where the edge actually draws
```

```bash
… -p -o geometry | jq '.nodes[] | select(.nodeId=="classify")'   # one node
… -p -o geometry | jq '[.nodes[] | select(.nodeRect.left < 0)]'  # assert: any node off-canvas?
```

`nodeId` isn't unique across sub-workflows (the same step invoked twice → two nodes with
the same `nodeId`) — disambiguate with the flat `dataId` (`n6` vs `n9`); the URL `node=`
also accepts a flat id.

A connector gap = the edge's `pathRect` end vs the node's `connTop`/`connBottom` tip vs
its `tile` edge. **Before/after a fix:** save each run (`… -p -o geometry > /tmp/before.json`),
then `diff` (or `jq`) the rects to prove the gap closed.

## Headless by default (user decision 2026-06-10)

The MCP Chrome runs with `--headless=true` (`~/.pflow/mcp-servers.json`, `chrome-devtools`
entry): no window appears, nothing steals the user's focus, and the occluded-window
interference class (suspected in the 2026-06-10 ELK-worker hang) is gone. **Verified
identical to headed** for both tools: `screenshot` paints the full canvas (gradient edges,
flares, condition icon, minimap), and `inspect` returns the same CSS-px geometry (compact
leaf 230×68, tile 56×56, all edges carry pathRects). Treat headless output as authoritative.

**Opt-in headed mode** — ONLY if the user explicitly asks to watch the browser: remove
`"--headless=true"` from the `chrome-devtools` args and kill the running headless instance
(`pkill -f "chrome-devtools-mcp/chrome-profile"`) so the next run relaunches with a window.
Re-add the flag when done — headless is the standing default; do not leave headed on.

## Troubleshooting

- `mcp-chrome-devtools-*` node error ("MCP tool not registered") → `pflow mcp sync chrome-devtools`.
- `viewport` = the default `translate(0px, 0px) scale(1)` → nothing fit: empty graph, or `node=` named a node that isn't rendered.
- Stale output → you didn't rebuild after a `web/` change: `make ui-build`.
- Stale output DESPITE a rebuild (old layout/styles, even mixed old+new) → the MCP Chrome's
  **HTTP cache** heuristically reused old `assets/*` (index.html itself now sends
  `Cache-Control: no-cache`). Add a throwaway query param to bust it: `&v=<anything-new>`
  (unknown params are ignored by the app).
