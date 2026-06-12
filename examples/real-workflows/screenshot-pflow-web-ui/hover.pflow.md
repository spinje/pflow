# Hover a canvas row and capture the result

One-off verification harness: open a pflow-UI URL, settle, dispatch a real
`mouseover` on the first row whose text starts with `row_name` (React's
onMouseEnter delegates through native mouseover, so this drives the production
hover path), then COUNT the hover marks + edge halos and screenshot.

## Inputs

### url

Full pflow-UI URL to open.

- type: string
- required: true

### row_name

Text prefix of the row to hover (param name or io port name).

- type: string
- required: true

### out_path

Where to write the screenshot PNG.

- type: string
- required: false
- default: "/tmp/pflow-shots/hover-verify.png"

## Steps

### prepare

Open + settle (the shared core the skill workflows use).

- type: workflow
- workflow: ./shared/open-and-settle.pflow.md
- inputs:
    url: ${url}

### hover

Dispatch a real mouseover on the named row, then count marks/halos.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const name = "${row_name}";
      const rows = [...document.querySelectorAll(".io-row, .param-row")];
      const el = rows.find((r) => (r.textContent || "").startsWith(name));
      if (!el) return { ok: false, reason: "row not found", rows: rows.length };
      el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 400));
      return {
        ok: true,
        ringedNodes: document.querySelectorAll(".hover-mark").length,
        haloedEdges: document.querySelectorAll(".edge-halo").length,
      };
    }

### shot

Capture the hovered state.

- type: mcp-chrome-devtools-take_screenshot
- fullPage: true
- format: png
- filePath: ${out_path}

## Outputs

### facts

The hover dispatch result: ok + ringed-node and haloed-edge counts.

- source: ${hover.result}
- stdout: true
