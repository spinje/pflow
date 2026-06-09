---
name: screenshot-pflow-web-ui
description: Screenshot the running pflow web UI (the React Flow canvas; web/ → src/pflow/ui) to verify frontend changes. Frames the whole graph or one node for a close-up. Use after changing web/ UI code and needing to SEE the rendered canvas.
---

# screenshot-pflow-web-ui

Take a settled screenshot of a pflow web UI URL — optionally framed on a single node.
The workflow lives at `examples/real-workflows/screenshot-pflow-web-ui/workflow.pflow.md`
(how and why it settles before capturing is in its description + node descriptions).

## The URL

You pass a full UI URL. Base: `http://127.0.0.1:<port>/` (default port **8765**). Query
params — source of truth: `web/src/utils/viewParams.ts`:

| param | values | default | meaning |
|---|---|---|---|
| `workflow` | a saved name, or a `.pflow.md` path relative to where the server runs | — (required) | which workflow to render |
| `direction` | `LR` \| `TD` | `LR` | layout direction (left-right / top-down) |
| `density` | `beautiful` \| `advanced` | `beautiful` | node density (compact / detailed cards) |
| `node` | a `node_id` (or flat id) | — (fit whole graph) | frame the camera on one node — a close-up, essential for small geometry (a connector, a handle) |

Example:
```
http://127.0.0.1:8765/?workflow=examples/core/conditional-branching.pflow.md&direction=TD&density=beautiful&node=classify
```

## Before running

1. **Ensure a server** on the URL's port (default 8765) — reuse one if it's already up,
   else start it and wait until ready (so the first screenshot doesn't race a cold start):
   ```bash
   curl -sf http://127.0.0.1:8765/api/catalog >/dev/null 2>&1 \
     || { uv run pflow ui --no-open --port 8765 & \
          for i in $(seq 1 20); do curl -sf http://127.0.0.1:8765/api/catalog >/dev/null 2>&1 && break; sleep 0.3; done; }
   ```
   The `||` is the check: the probe runs first, and the server starts **only if** it
   fails — so this is safe to re-run and never double-starts.
2. **Rebuild after ANY `web/` change** (the server serves the built bundle, not source):
   ```bash
   make ui-build
   ```

## Run

```bash
uv run pflow examples/real-workflows/screenshot-pflow-web-ui/workflow.pflow.md \
  url='http://127.0.0.1:8765/?workflow=<name|path>&direction=TD&density=beautiful&node=<node_id>' \
  [out_dir=/tmp/pflow-shots]
```

Stdout = the saved PNG path → then `Read` it. (Single-quote the URL so the shell doesn't
split on `&`.)

## Don't use for

- General URLs (a static site, docs) → use the `shoot` skill instead.
- States that need clicks first (collapse a group, focus a node) → drive the
  chrome-devtools MCP tools (`click`, `evaluate_script`) directly.

## Troubleshooting

- **"MCP tool not registered"** (or any `mcp-chrome-devtools-*` node error) → the
  chrome-devtools MCP isn't synced: `pflow mcp sync chrome-devtools`.
- **`viewport` output is the default `translate(0px, 0px) scale(1)`** → nothing fit:
  the graph is empty, or `node=` named a node that isn't rendered (check the id).
- **Stale UI in the shot** → you didn't rebuild after a `web/` change: `make ui-build`.
