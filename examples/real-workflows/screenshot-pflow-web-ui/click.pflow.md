# Click a UI element and capture the result

One-off verification harness: open a pflow-UI URL, settle, dispatch a real `click`
on the first element matching `selector` (optionally narrowed to the match whose
trimmed text equals `text`), wait for the click's consequences (re-layout, camera
follow), then report the open panel title + an optional canvas node's rect
before/after and screenshot. Deep links capture STATES; this captures what a click
DOES — camera follow, panel stays-vs-swaps, focus/expansion side effects — the
interaction layer `focus=`/`node=` cannot reach.

Each run reopens the page (fresh in-page state, layout cache cleared), so a
multi-click sequence needs its own steps inside ONE run — copy the `click` step.
Selectors are interpolated into single-quoted JS strings: use double quotes inside
(`.react-flow__node[data-id="n16"]`), never single quotes.

## Inputs

### url

Full pflow-UI URL to open.

- type: string
- required: true

### selector

CSS selector for the click target — e.g. `.chip-stack .edge-chip` (panel chips)
or `.react-flow__node[data-id="n16"]` (a canvas node).

- type: string
- required: true

### text

Exact trimmed textContent to pick among the selector's matches (e.g.
`create-songs`). Empty picks the first match.

- type: string
- required: false
- default: ""

### measure_id

Flat id of a canvas node to rect-report before/after the click (e.g. the
expected camera-follow target). Empty skips measurement.

- type: string
- required: false
- default: ""

### out_path

Where to write the screenshot PNG.

- type: string
- required: false
- default: "/tmp/pflow-shots/click-verify.png"

## Steps

### prepare

Open + settle (the shared core the skill workflows use).

- type: workflow
- workflow: ./shared/open-and-settle.pflow.md
- inputs:
    url: ${url}

### click

Dispatch a real click on the target, then report panel + rects.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const sel = '${selector}';
      const text = '${text}';
      const measureId = '${measure_id}';
      const nodeRect = (id) => {
        const el = document.querySelector('.react-flow__node[data-id="' + id + '"]');
        return el ? el.getBoundingClientRect().toJSON() : null;
      };
      const candidates = [...document.querySelectorAll(sel)];
      const target = text ? candidates.find((c) => (c.textContent || "").trim() === text) : candidates[0];
      if (!target) {
        return {
          ok: false,
          reason: "target not found",
          matches: candidates.map((c) => (c.textContent || "").trim()).slice(0, 20),
        };
      }
      const before = measureId ? nodeRect(measureId) : null;
      target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 2500));
      const after = measureId ? nodeRect(measureId) : null;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const visible = !!after && after.right > 0 && after.left < vw && after.bottom > 0 && after.top < vh;
      const panel = document.querySelector(".read-panel h2");
      const vp = document.querySelector(".react-flow__viewport");
      return {
        ok: true,
        before,
        after,
        visible: measureId ? visible : null,
        panel: panel ? panel.textContent : null,
        vw,
        vh,
        transform: vp ? vp.style.transform : null,
      };
    }

### shot

Capture the post-click state.

- type: mcp-chrome-devtools-take_screenshot
- fullPage: true
- format: png
- filePath: ${out_path}

## Outputs

### facts

The click result: ok + open panel title + measured node rect before/after +
visibility verdict + viewport transform.

- source: ${click.result}
- stdout: true
