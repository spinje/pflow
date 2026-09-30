# Open and settle pflow UI

Open a pflow-UI URL in the chrome-devtools MCP Chrome and poll until the React Flow
canvas has **settled** (the async `fetch → ELK → measure → fitView` chain has finished).
This is the reusable core both pflow-web-UI tools share — the screenshot tool and the
inspect (geometry) tool each need the page opened and settled before their own verb
(capture a PNG / read the DOM). Returns the settle report (a non-default transform is
proof the fit applied).

**It never hands back a page it could not settle.** A timeout fails the run, because every
caller would otherwise examine a canvas that isn't there and report success on nothing.
Capturing a page with no framed canvas on purpose (the full-screen error page) is the
caller's explicit `allow_empty` opt-in.

Why it must poll rather than open-then-act: the UI renders asynchronously (React mounts,
fetches `/api/graph`, runs ELK, React Flow measures nodes via ResizeObserver,
`useNodesInitialized` flips, then `fitView` frames the canvas). Acting before that chain
finishes captures/measures a half-built, un-fit canvas.

Callers depend on this sub-workflow leaving the opened, settled page in the MCP Chrome
(the page persists in the MCP server across the workflow-call boundary) AND on its
`page_id` output: chrome-devtools-mcp ≥ 1.8 requires `pageId` on every page-scoped tool
(`evaluate_script`, `take_screenshot`, …) instead of acting on an implicitly selected
page, so every caller step that touches the page passes `pageId: ${prepare.page_id}`.

## Inputs

### url

Full pflow-UI URL to open, including the view params — e.g.
`http://127.0.0.1:8765/?workflow=examples/core/conditional-branching.pflow.md&direction=TD&density=beautiful&node=classify`.

- type: string
- required: true

### allow_empty

Accept a page whose canvas never frames — the full-screen error page — instead of
failing. `settle` then waits out its full 8 s and reports `settled: false`.

- type: boolean
- required: false
- default: false

## Outputs

### page_id

The opened tab's chrome-devtools page id — pass it as `pageId` to every later
page-scoped call so it acts on this page, not whichever one the server has selected.

- source: ${page.result}

### report

The settle report: `{settled, transform, nodes, waited_ms}` — the viewport transform,
the rendered node count, and how long the poll waited. `settled` is always `true` unless
the caller passed `allow_empty`.

- source: ${settled.result}

## Steps

### open

Open the URL in a fresh tab in the MCP-managed Chrome. This is a REAL rendering Chrome
(unlike `chrome --headless --screenshot`), so ResizeObserver / fitView run.

- type: mcp-chrome-devtools-new_page
- url: ${url}

### page

Read the new tab's page id from `new_page`'s result — a prose page list
(`## Pages` / `1: about:blank` / `2: <title> (<url>) [selected]`) in which the page just
opened is the `[selected]` one. The marker must END the line (a page title may contain the
text `[selected]`; the ` (<url>)` after it keeps such a title off the line end), and exactly
one line may carry it — anything else fails loudly rather than letting a later step act on
the wrong tab.

- type: code
- inputs:
    pages: ${open.result}

```python code
pages: str

import re

selected = re.findall(r"^(\d+): .* \[selected\]$", pages, re.MULTILINE)
if len(selected) != 1:
    raise ValueError(f"expected exactly one [selected] page in the new_page result: {pages!r}")

result: int = int(selected[0])
```

### settle

Poll the React Flow viewport transform until it is non-default AND stable across
consecutive reads (the `fitView` animation has finished) with at least one node rendered
— or give up after 8s. The load-bearing step: it waits out the async chain so the
downstream verb is deterministic instead of a race. It only measures; `settled` below
judges.

- type: mcp-chrome-devtools-evaluate_script
- pageId: ${page.result}
- result_format: json_block
- function: |
    async () => {
      const start = Date.now();
      const deadline = start + 8000;
      const DEFAULT = "translate(0px, 0px) scale(1)";
      const read = () => {
        const vp = document.querySelector(".react-flow__viewport");
        return vp ? vp.style.transform : "";
      };
      const nodes = () => document.querySelectorAll(".react-flow__node").length;
      let prev = null, stable = 0, t = "";
      while (Date.now() < deadline) {
        t = read();
        if (t && t !== DEFAULT && t === prev && nodes() > 0) {
          stable++;
          if (stable >= 2) break;
        } else {
          stable = 0;
        }
        prev = t;
        await new Promise((r) => setTimeout(r, 100));
      }
      return { settled: stable >= 2, transform: t, nodes: nodes(), waited_ms: Date.now() - start };
    }

### settled

Fail the run when `settle` timed out, unless the caller opted into an unframed page.
The message names what the page showed, so the caller can tell a broken URL from a slow
layout.

- type: code
- inputs:
    report: ${settle.result}
    allow_empty: ${allow_empty}

```python code
report: dict
allow_empty: bool

if not report["settled"] and not allow_empty:
    if not report["transform"]:
        seen = "no canvas on the page (the full-screen error page, or a wrong URL)"
    else:
        seen = f"{report['nodes']} nodes rendered, viewport transform {report['transform']!r}"
    raise ValueError(
        f"canvas did not settle within {report['waited_ms']} ms: {seen}. Nothing was examined. "
        "Check that the workflow= path renders in the UI, and retry if the host is loaded. "
        "To capture a page with no framed canvas on purpose, pass allow_empty=true (screenshot, inspect)."
    )

result: dict = report
```
