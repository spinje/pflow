# Hover a canvas row and capture the result

One-off verification harness: open a pflow-UI URL, settle, dispatch a synthetic
`mouseover` on the first row whose text starts with `row_name` (React's
onMouseEnter delegates through native mouseover, so this drives the production
hover path), then COUNT the hover marks + edge halos and screenshot.

The mouseover is a synthetic in-page event (`dispatchEvent`, `isTrusted: false`).
For real input (modifier keys, drag, typing, focus) or request interception, use a
host-side automation tool instead (`pflow guide mcp` → Choosing Tools for Deterministic Steps).

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

Dispatch a synthetic mouseover on the named row, then count marks/halos.

- type: mcp-chrome-devtools-evaluate_script
- pageId: ${prepare.page_id}
- result_format: json_block
- function: |
    async () => {
      const name = "${row_name}";
      const rows = [...document.querySelectorAll(".io-row, .param-row")];
      const el = rows.find((r) => (r.textContent || "").startsWith(name));
      if (!el) {
        throw new Error("hover row not found: none of " + rows.length + " .io-row/.param-row rows starts with " + JSON.stringify(name));
      }
      el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 400));
      return {
        ringedNodes: document.querySelectorAll(".hover-mark").length,
        haloedEdges: document.querySelectorAll(".edge-halo").length,
      };
    }

### shot

Capture the hovered state.

- type: mcp-chrome-devtools-take_screenshot
- pageId: ${prepare.page_id}
- fullPage: true
- format: png
- filePath: ${out_path}

## Outputs

### facts

The hover dispatch result: ringed-node and haloed-edge counts.

- source: ${hover.result}
- stdout: true
