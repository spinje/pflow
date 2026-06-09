# Open and settle pflow UI

Open a pflow-UI URL in the chrome-devtools MCP Chrome and poll until the React Flow
canvas has **settled** (the async `fetch → ELK → measure → fitView` chain has finished).
This is the reusable core both pflow-web-UI tools share — the screenshot tool and the
inspect (geometry) tool each need the page opened and settled before their own verb
(capture a PNG / read the DOM). Returns the settled viewport transform (a non-default
transform is proof the fit applied).

Why it must poll rather than open-then-act: the UI renders asynchronously (React mounts,
fetches `/api/graph`, runs ELK, React Flow measures nodes via ResizeObserver,
`useNodesInitialized` flips, then `fitView` frames the canvas). Acting before that chain
finishes captures/measures a half-built, un-fit canvas.

Both tools depend on this sub-workflow leaving the MCP Chrome on the opened, settled page
(the page persists in the MCP server across the workflow-call boundary — that shared
browser state IS the contract here, not just the returned transform).

## Inputs

### url

Full pflow-UI URL to open, including the view params — e.g.
`http://127.0.0.1:8765/?workflow=examples/core/conditional-branching.pflow.md&direction=TD&density=beautiful&node=classify`.

- type: string
- required: true

## Outputs

### transform

The settled viewport transform + how long the poll waited (non-default transform = fit
applied; default `translate(0px, 0px) scale(1)` = nothing fit — empty graph or a `node=`
that isn't rendered).

- source: ${settle.result}

## Steps

### open

Open the URL in a fresh tab in the MCP-managed Chrome. This is a REAL rendering Chrome
(unlike `chrome --headless --screenshot`), so ResizeObserver / fitView run.

- type: mcp-chrome-devtools-new_page
- url: ${url}

### settle

Poll the React Flow viewport transform until it is non-default AND stable across
consecutive reads (the `fitView` animation has finished) — or give up after 8s. The
load-bearing step: it waits out the async chain so the downstream verb is deterministic
instead of a race.

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
