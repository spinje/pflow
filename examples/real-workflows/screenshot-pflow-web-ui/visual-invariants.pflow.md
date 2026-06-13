# Assert visual invariants on a settled canvas

Open a pflow-UI URL, settle, then assert the geometry invariants that no vitest
suite can observe (jsdom renders no React Flow edge DOM and fictional rects —
only a real browser computes the cascade and the layout):

* **io dots sit ON their owner border** — every visible `.port-handle` that the
  CSS offsets onto a card/region border (the `--io-inset` rules) has its center
  within 2 CSS px of that border. Catches the offset-drift class (a stylesheet
  translate composing under an authored offset pushed every dot ~4px outside,
  user-caught 2026-06-12).
* **no contract edge is silently missing** — every edge id in `/api/graph`
  appears as a rendered `.react-flow__edge`, and every extra DOM edge is a known
  synthesized kind (`loop:` / `io-flow:`). Catches the silent-edge-drop class
  (a handle id of the wrong type drops the edge with no error). Only meaningful
  with `density=advanced` and `collapse=none` (otherwise edges hide/re-anchor by
  design) — the check self-skips and says so when the view doesn't qualify.
* **no two leaf boxes overlap** — expanded regions contain their children by
  design and are excluded; any other pair of node rects intersecting by more
  than 1 CSS px means ELK laid out on a lie (a size function disagreeing with
  the DOM).

Returns a JSON verdict (`passed` plus per-invariant counts and violations) and a
screenshot. Run with `-p -o verdict` to get just the JSON.

## Inputs

### url

Full pflow-UI URL. For the edge-coverage invariant pass
`density=advanced&collapse=none`; the other two invariants run on any view.

* type: string
* required: true

### out_path

Where to write the screenshot PNG.

* type: string
* required: false
* default: "/tmp/pflow-shots/visual-invariants.png"

## Steps

### prepare

Open + settle (the shared core the skill workflows use).

- type: workflow
- workflow: ./shared/open-and-settle.pflow.md
- inputs:
    url: ${url}

### check

Measure the settled DOM and return the verdict. The dot check mirrors the
index.css `--io-inset` selectors exactly (the four groups that put a dot on a
border) rather than re-deriving which side a row connects on; the edge check
compares DOM edge ids against the live `/api/graph` contract by identity, never
by re-derived counts.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const vpEl = document.querySelector(".react-flow__viewport");
      const m = vpEl && vpEl.style.transform.match(/scale\(([\d.]+)\)/);
      const scale = m ? Number(m[1]) : 1;
      const violations = { dots: [], edges: [], overlaps: [] };

      // ---- invariant 1: bordered io dots ----
      // Mirror of the index.css --io-inset rules (the dots DESIGNED to sit on a
      // border). Region rows' inner-scope dots stay at their row edge by design
      // and are deliberately not matched here.
      const ON_LEFT = ".io-col-input .react-flow__handle-left, .io-card .io-col-output .react-flow__handle-left";
      const ON_RIGHT = ".io-col-output .react-flow__handle-right, .io-card .io-col-input .react-flow__handle-right";
      const TOL = 2 * scale; // 2 CSS px in screen px
      let dotsChecked = 0;
      const checkDots = (sel, side) => {
        for (const h of document.querySelectorAll(sel)) {
          if (!h.classList.contains("port-handle")) continue;
          if (Number(getComputedStyle(h).opacity) === 0) continue; // quiet side
          const owner = h.closest(".node, .group"); // card OR expanded region
          const hb = h.getBoundingClientRect();
          if (!owner || hb.width === 0) continue;
          dotsChecked++;
          const ob = owner.getBoundingClientRect();
          const cx = (hb.left + hb.right) / 2;
          const off = Math.abs(cx - (side === "left" ? ob.left : ob.right));
          if (off > TOL) {
            const wrap = h.closest(".react-flow__node");
            violations.dots.push({
              node: wrap ? wrap.getAttribute("data-id") : null,
              row: (h.parentElement.textContent || "").trim().slice(0, 30),
              side: side,
              offCssPx: +(off / scale).toFixed(1),
            });
          }
        }
      };
      checkDots(ON_LEFT, "left");
      checkDots(ON_RIGHT, "right");

      // ---- invariant 2: contract edge coverage ----
      const params = new URLSearchParams(location.search);
      const density = params.get("density") || "beautiful";
      const collapsedCards = document.querySelectorAll(".group-card").length;
      let edges;
      if (density !== "advanced") {
        edges = { skipped: "density!=advanced — data edges hidden by design" };
      } else if (collapsedCards > 0) {
        edges = { skipped: "collapsed containers present (edges re-anchor + dedupe by design) — pass collapse=none" };
      } else {
        const res = await fetch("/api/graph?workflow=" + encodeURIComponent(params.get("workflow") || ""));
        if (!res.ok) return { passed: false, reason: "api graph fetch returned http " + res.status };
        const contract = await res.json();
        const domIds = new Set(
          [...document.querySelectorAll(".react-flow__edge")].map((e) => e.getAttribute("data-id")),
        );
        const known = new Set(contract.edges.map((e) => e.id));
        const missing = contract.edges.map((e) => e.id).filter((id) => !domIds.has(id));
        const badExtras = [...domIds].filter(
          (id) => !known.has(id) && !id.startsWith("loop:") && !id.startsWith("io-flow:"),
        );
        edges = { contract: contract.edges.length, dom: domIds.size, missing: missing.slice(0, 20), badExtras: badExtras.slice(0, 20) };
        if (missing.length || badExtras.length) violations.edges.push(edges);
      }

      // ---- invariant 3: no two leaf boxes overlap ----
      const leaves = [];
      for (const wrap of document.querySelectorAll(".react-flow__node")) {
        const inner = wrap.firstElementChild;
        if (inner && inner.classList.contains("group")) continue; // region contains children by design
        leaves.push({ id: wrap.getAttribute("data-id"), b: wrap.getBoundingClientRect() });
      }
      if (leaves.length === 0) return { passed: false, reason: "no nodes rendered — wrong URL or unsettled page" };
      const EPS = 1 * scale; // 1 CSS px
      for (let i = 0; i < leaves.length; i++) {
        for (let j = i + 1; j < leaves.length; j++) {
          const a = leaves[i].b;
          const c = leaves[j].b;
          const ox = Math.min(a.right, c.right) - Math.max(a.left, c.left);
          const oy = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top);
          if (ox > EPS && oy > EPS && violations.overlaps.length < 20) {
            violations.overlaps.push({
              a: leaves[i].id,
              b: leaves[j].id,
              ox: +(ox / scale).toFixed(1),
              oy: +(oy / scale).toFixed(1),
            });
          }
        }
      }

      const passed =
        violations.dots.length === 0 && violations.edges.length === 0 && violations.overlaps.length === 0;
      violations.dots = violations.dots.slice(0, 20);
      return { passed, scale: +scale.toFixed(3), dotsChecked, leaves: leaves.length, edges, violations };
    }

### shot

Capture the checked state (context for any violation).

- type: mcp-chrome-devtools-take_screenshot
- fullPage: true
- format: png
- filePath: ${out_path}

### clean

Strip the chrome-devtools "Script ran on page and returned" wrapper off the check
result and re-emit pure JSON, so the `verdict` output pipes straight to `jq`.

- type: code
- inputs:
    raw: ${check.result}

```python code
raw: str

import json

start = raw.find("{")
end = raw.rfind("}")
result: str = json.dumps(json.loads(raw[start : end + 1])) if start != -1 else "{}"
```

## Outputs

### verdict

The invariant verdict: `passed` + `dotsChecked`/`leaves` counts, the edge-coverage
report (or its skip reason), and up to 20 violations per invariant.

- source: ${clean.result}
- stdout: true
