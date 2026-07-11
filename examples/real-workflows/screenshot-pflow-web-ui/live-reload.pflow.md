# Live-reload check for the pflow web UI

Verify that `pflow ui` updates the canvas **IN PLACE (no page reload)** when the
`.pflow.md` source changes on disk — the one thing the other skill workflows can't
test, because they reopen the page each run. This one keeps the SAME page open and
edits the source under it, asserting four behaviors in a single session:

1. **in-place + viewport** — append a node → the canvas grows without a reload and
   the viewport transform is byte-identical (no camera jump);
2. **selection remap** — insert a node BEFORE a focused one (which renumbers the
   focused node's positional flat id) → focus FOLLOWS the node, never jumps to the
   inserted one (the structural-ref remap, `web/src/graph/remap.ts`);
3. **source pane refresh** — the left source pane shows the edited text, not stale;
4. **invalid held** — corrupt the source → the last valid canvas stays up under a
   non-blocking banner, NOT the full-screen error.

It manages its own throwaway workflow: it WRITES a valid seed to `wf_file`, drives
the edits, and deletes it. The caller only provides a temp path + a URL pointing at
it. Re-run this before merging any change to the live-reload path
(`useSourceWatch` / the `reload` arm of `useWorkflowGraph` / `graph/remap.ts` /
the `/api/version` endpoint). It is also the same-page-react primitive Task 169
(agent→browser push) will extend.

Prerequisites: the `pflow ui` server running on the URL's port; the chrome-devtools
MCP synced. After any `web/` change, rebuild the bundle (`make ui-build`).

## Inputs

### url

Full pflow-UI URL pointing at `wf_file`. MUST carry
`&focus=done&source=1&density=advanced&collapse=none` — the check focuses the seed's
`done` node, opens the source pane, and needs every node rendered. Example:
`http://127.0.0.1:8765/?workflow=/tmp/lr-probe.pflow.md&focus=done&source=1&density=advanced&collapse=none`.

- type: string
- required: true

### wf_file

A throwaway `.pflow.md` path the check OWNS — it writes the seed here, edits it, and
deletes it. Must match the `workflow=` in `url`.

- type: string
- required: true

### out_path

Where to write the final-state screenshot (the corrupted state — banner over the
last valid canvas).

- type: string
- required: false
- default: "/tmp/pflow-shots/live-reload.png"

## Outputs

### verdict

`{ passed, checks: { in_place, viewport_preserved, remap_focus_follows,
source_pane_refreshed, invalid_held }, counts }`. Run with `-p -o verdict | jq`.
Key is `passed` (not `ok`) — the api-warning-detector gotcha.

- source: ${verdict.result}
- stdout: true

## Steps

### seed

Write a valid two-node seed to `wf_file` BEFORE the page opens. `done` carries a
distinct purpose ("Finalize…") so the remap check can tell which node is focused.

- type: shell
- command: |
    python3 - "${wf_file}" <<'PY'
    import sys
    content = "# Live Reload Probe\n\nThrowaway workflow for the live-reload skill check.\n\n## Steps\n\n### greet\n\nGreet the world to begin the run.\n\n- type: shell\n- command: echo hello\n\n### done\n\nFinalize and report completion of the run.\n\n- type: shell\n- command: echo done\n"
    open(sys.argv[1], "w", encoding="utf-8").write(content)
    PY

### opened

Open the URL (now that the seed exists) and wait for the canvas to settle — the
shared `open + settle` core. Leaves the MCP Chrome on the settled page; every read
below acts on that SAME page.

- type: workflow
- workflow: ./shared/open-and-settle.pflow.md
- inputs:
    url: ${url}

### baseline

Read the settled state: rendered node count, viewport transform, the focused card's
text, source-pane marker, banner/full-screen flags.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const focused = (document.querySelector(".node.focused")?.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
      const vp = document.querySelector(".react-flow__viewport");
      const src = document.querySelector(".source-pane")?.textContent || "";
      return {
        nodes: document.querySelectorAll(".react-flow__node").length,
        transform: vp ? vp.style.transform : null,
        focused,
        src_marker: src.includes("RELOADMARKER"),
        banner: !!document.querySelector(".reload-banner"),
        fullscreen: !!document.querySelector(".banner.error"),
      };
    }

### append

Append a node at the end (does NOT renumber existing nodes) — the in-place + viewport check.

- type: shell
- command: |
    python3 - "${wf_file}" <<'PY'
    import sys
    block = "\n### tail\n\nAppended tail step for the in-place check.\n\n- type: shell\n- command: echo tail\n"
    open(sys.argv[1], "a", encoding="utf-8").write(block)
    PY

### wait_append

Let the poll detect the change, re-fetch, and re-layout.

- type: shell
- command: sleep 3

### after_append

Re-read on the SAME page after the append.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const focused = (document.querySelector(".node.focused")?.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
      const vp = document.querySelector(".react-flow__viewport");
      const src = document.querySelector(".source-pane")?.textContent || "";
      return {
        nodes: document.querySelectorAll(".react-flow__node").length,
        transform: vp ? vp.style.transform : null,
        focused,
        src_marker: src.includes("RELOADMARKER"),
        banner: !!document.querySelector(".reload-banner"),
        fullscreen: !!document.querySelector(".banner.error"),
      };
    }

### insert

Insert a `middle` node BEFORE `done` (renumbers done's flat id) with a unique marker
in its description — the remap + source-pane-refresh check.

- type: shell
- command: |
    python3 - "${wf_file}" <<'PY'
    import sys
    p = sys.argv[1]
    s = open(p, encoding="utf-8").read()
    block = "### middle\n\nRELOADMARKER inserted-before step for the remap check.\n\n- type: shell\n- command: echo middle\n\n"
    s = s.replace("### done", block + "### done", 1)
    open(p, "w", encoding="utf-8").write(s)
    PY

### wait_insert

Let the poll re-fetch, remap the focused selection, and refresh the source pane.

- type: shell
- command: sleep 3

### after_insert

Re-read: focus must still be `done` (Finalize…), and the source pane must now carry
the marker.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const focused = (document.querySelector(".node.focused")?.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
      const vp = document.querySelector(".react-flow__viewport");
      const src = document.querySelector(".source-pane")?.textContent || "";
      return {
        nodes: document.querySelectorAll(".react-flow__node").length,
        transform: vp ? vp.style.transform : null,
        focused,
        src_marker: src.includes("RELOADMARKER"),
        banner: !!document.querySelector(".reload-banner"),
        fullscreen: !!document.querySelector(".banner.error"),
      };
    }

### corrupt

Overwrite the source with an INVALID workflow (unknown node type → 422).

- type: shell
- command: |
    python3 - "${wf_file}" <<'PY'
    import sys
    content = "# Broken\n\n## Steps\n\n### x\n\nA step with an unknown type.\n\n- type: nonexistent_type_zzz\n"
    open(sys.argv[1], "w", encoding="utf-8").write(content)
    PY

### wait_corrupt

Let the poll re-fetch (→ 422) and surface the banner.

- type: shell
- command: sleep 3

### after_corrupt

Re-read: the non-blocking banner is present, the full-screen error is NOT, and the
node count is unchanged (last valid canvas held).

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const focused = (document.querySelector(".node.focused")?.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
      const vp = document.querySelector(".react-flow__viewport");
      const src = document.querySelector(".source-pane")?.textContent || "";
      return {
        nodes: document.querySelectorAll(".react-flow__node").length,
        transform: vp ? vp.style.transform : null,
        focused,
        src_marker: src.includes("RELOADMARKER"),
        banner: !!document.querySelector(".reload-banner"),
        fullscreen: !!document.querySelector(".banner.error"),
      };
    }

### shot

Capture the final state (banner over the last valid canvas).

- type: mcp-chrome-devtools-take_screenshot
- fullPage: true
- format: png
- filePath: ${out_path}

### cleanup

Delete the throwaway workflow.

- type: shell
- command: rm -f "${wf_file}"

### verdict

Combine the four reads into a pass/fail verdict (the four wrapped chrome-devtools
results parse by their lone brace span, like inspect's clean node).

- type: code
- inputs:
    baseline: ${baseline.result}
    after_append: ${after_append.result}
    after_insert: ${after_insert.result}
    after_corrupt: ${after_corrupt.result}

```python code
baseline: str
after_append: str
after_insert: str
after_corrupt: str

import json


def parse(s: str) -> dict:
    a, b = s.find("{"), s.rfind("}")
    return json.loads(s[a : b + 1]) if a != -1 else {}


base = parse(baseline)
app = parse(after_append)
ins = parse(after_insert)
cor = parse(after_corrupt)

checks = {
    "in_place": app.get("nodes", 0) > base.get("nodes", -1),
    "viewport_preserved": bool(base.get("transform")) and app.get("transform") == base.get("transform"),
    "remap_focus_follows": "Finalize" in ins.get("focused", "") and "RELOADMARKER" not in ins.get("focused", ""),
    "source_pane_refreshed": (not base.get("src_marker")) and bool(ins.get("src_marker")),
    "invalid_held": bool(cor.get("banner")) and not cor.get("fullscreen") and cor.get("nodes") == ins.get("nodes"),
}

result: dict = {
    "passed": all(checks.values()),
    "checks": checks,
    "counts": {"base": base.get("nodes"), "append": app.get("nodes"), "insert": ins.get("nodes"), "corrupt": cor.get("nodes")},
}
```
