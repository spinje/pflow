# Screenshot pflow web UI

Capture the pflow web UI canvas (`web/` → `src/pflow/ui`) reliably, for verifying
frontend changes you can't see in tests. Drives the real-rendering chrome-devtools MCP
Chrome and POLLS until the React Flow layout (ELK + fitView) has settled before
capturing.

Takes a full pflow-UI **URL** — you pick the workflow + view params in the URL. The
param vocabulary (`workflow`, `direction=LR|TD`, `density=beautiful|advanced`,
`node=<node_id>`) lives in `web/src/utils/viewParams.ts`. Keeping the URL as the input
makes this a thin, stable "settle then screenshot a URL" tool that needs no change when
the UI gains new view params.

**Why a dedicated workflow (not the general `shoot`, nor Chrome's built-in capture):**
the UI renders **asynchronously** — React mounts, fetches `/api/graph`, runs ELK
layout, React Flow measures the nodes (ResizeObserver), `useNodesInitialized` flips,
then `fitView` frames the canvas. Two naive approaches both fail:

- A plain `open → screenshot` (the general `shoot`) fires *before* that chain
  finishes → a half-built / un-fit canvas.
- `chrome --headless --screenshot --virtual-time-budget` *suppresses* the
  ResizeObserver/paint pipeline → `fitView` never runs → a permanently un-fit shot.

This workflow uses the **chrome-devtools MCP** Chrome (real rendering, so the pipeline
runs) and a **poll step** that waits until the canvas has actually settled.

Prerequisites: the `pflow ui` server running (whatever host:port the URL targets), and
the chrome-devtools MCP server synced (`pflow mcp sync chrome-devtools`). After any
`web/` change, rebuild the bundle (`make ui-build`) — the server serves the built
`static/`, not the source.

## Inputs

### url

Full pflow-UI URL to screenshot, including the view params — e.g.
`http://127.0.0.1:8765/?workflow=examples/core/conditional-branching.pflow.md&direction=TD&density=beautiful&node=classify`.
Query params (source: `web/src/utils/viewParams.ts`): `workflow` (required),
`direction=LR|TD`, `density=beautiful|advanced`, `node=<node_id>` (close-up on one node).

- type: string
- required: true

### out_dir

Directory to write the screenshot into (created if missing).

- type: string
- required: false
- default: "/tmp/pflow-shots"

## Steps

### derive

Build a descriptive output PNG path from the URL's query (the workflow name + whatever
view params are present) and a timestamp. Param-set-agnostic — it slugs whatever is in
the query, so it needs no update when the UI adds params.

- type: code
- inputs:
    url: ${url}
    out_dir: ${out_dir}

```python code
url: str
out_dir: str

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

q = dict(parse_qsl(urlparse(url).query))
wf = q.pop("workflow", "ui").rsplit("/", 1)[-1]
if wf.endswith(".pflow.md"):
    wf = wf[: -len(".pflow.md")]
slug = re.sub(r"[^A-Za-z0-9.-]+", "-", "-".join([wf, *q.values()])).strip("-")[:80] or "ui"
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
folder = Path(out_dir).expanduser().resolve()
folder.mkdir(parents=True, exist_ok=True)

result: str = str(folder / f"{slug}-{timestamp}.png")
```

### open

Open the URL in a fresh tab in the MCP-managed Chrome. This is a REAL rendering Chrome
(unlike `chrome --headless --screenshot`), so ResizeObserver / fitView run.

- type: mcp-chrome-devtools-new_page
- url: ${url}

### settle

Poll the React Flow viewport transform until it is non-default AND stable across
consecutive reads (the `fitView` animation has finished) — or give up after 8s. This
is the load-bearing step: it waits out the async `fetch → ELK → measure → fit` chain so
the capture is deterministic instead of a race. Returns the final transform + how long
it waited (a non-default transform is proof the fit applied).

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const start = Date.now();
      const deadline = start + 8000;
      const DEFAULT = "translate(0px, 0px) scale(1)";
      const read = () => {
        const vp = document.querySelector(".react-flow__viewport");
        return vp ? vp.style.transform : "";
      };
      let prev = null, stable = 0, t = "";
      while (Date.now() < deadline) {
        t = read();
        if (t && t !== DEFAULT && t === prev) {
          stable++;
          if (stable >= 2) break;
        } else {
          stable = 0;
        }
        prev = t;
        await new Promise((r) => setTimeout(r, 100));
      }
      return { transform: t, waited_ms: Date.now() - start };
    }

### shot

Full-page PNG of the now-settled canvas, written to the path from `derive`.

- type: mcp-chrome-devtools-take_screenshot
- fullPage: true
- format: png
- filePath: ${derive.result}

## Outputs

### path

Absolute path of the saved screenshot.

- source: ${derive.result}
- stdout: true

### viewport

The settled viewport transform + wait time (non-default transform = fit applied;
default `translate(0px, 0px) scale(1)` = nothing fit — empty graph or node not found).

- source: ${settle.result}
