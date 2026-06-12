# Manual Source Pane Browser Check

Drive the real chrome-devtools browser against the built pflow UI and return a compact
JSON report for the source-pane interactions that jsdom cannot verify.

## Inputs

### url

Full pflow UI URL to open.

- type: string
- required: true

## Outputs

### report

JSON report of source-pane browser checks.

- source: ${clean.result}
- stdout: true

## Steps

### prepare

Open the requested URL and wait until the React Flow canvas has settled.

- type: workflow
- workflow: ../../examples/real-workflows/screenshot-pflow-web-ui/shared/open-and-settle.pflow.md
- inputs:
    url: ${url}

### drive

Click through the source pane interactions in the real browser and return a JSON-ish
object through the chrome-devtools MCP result wrapper.

- type: mcp-chrome-devtools-evaluate_script
- function: |
    async () => {
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const visibleText = (el) => (el ? el.textContent || "" : "");
      const basename = (path) => path ? path.split(/[\\/]/).pop() : null;
      const sourceCode = () => document.querySelector(".source-code");
      const sourceLabel = () => sourceCode()?.getAttribute("aria-label") || null;
      const activeLine = () => document.querySelector(".src-line-active");
      const activeText = () => visibleText(activeLine()).trim();
      const sourceTokenCount = () => document.querySelectorAll(".source-code .src-content span").length;
      const sourceHasStyledTokens = () =>
        [...document.querySelectorAll(".source-code .src-content span")].some((span) =>
          span.hasAttribute("style") || (span.getAttribute("class") || "").length > 0
        );
      const nodeByTitle = (title) =>
        [...document.querySelectorAll(".react-flow__node")].find((node) =>
          node.querySelector('.node-name[title="' + title + '"]')
        );
      const click = (el) => {
        if (!el) return false;
        el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
        return true;
      };
      const waitFor = async (predicate, timeout = 4000) => {
        const start = Date.now();
        while (Date.now() - start < timeout) {
          const value = predicate();
          if (value) return value;
          await sleep(100);
        }
        return null;
      };

      await waitFor(() => document.querySelector(".source-pane") && document.querySelector(".react-flow__node"));
      await waitFor(() => sourceTokenCount() > 0, 8000);
      const initial = {
        hasPane: !!document.querySelector(".source-pane"),
        file: basename(sourceLabel()),
        tokenSpans: sourceTokenCount(),
        styledTokens: sourceHasStyledTokens(),
      };

      const hostNode = await waitFor(() => nodeByTitle("execute-plan"));
      click(hostNode?.querySelector(".node") || hostNode);
      await sleep(250);
      const hostClick = {
        clicked: !!hostNode,
        file: basename(sourceLabel()),
        activeText: activeText(),
      };

      const toggle = hostNode?.querySelector(".group-toggle");
      click(toggle);
      const childNode = await waitFor(() => nodeByTitle("plan-review-fix"));
      click(childNode?.querySelector(".node") || childNode);
      await waitFor(() => basename(sourceLabel()) === "execute-plan.pflow.md");
      const memberClick = {
        expanded: !!childNode,
        file: basename(sourceLabel()),
        crumbs: [...document.querySelectorAll(".source-crumb")].map((el) => visibleText(el).trim()),
        activeText: activeText(),
      };

      const sourceLine = [...document.querySelectorAll(".src-line")].find((line) =>
        visibleText(line).includes("### breakdown")
      );
      click(sourceLine);
      await waitFor(() => (document.querySelector(".read-panel h2")?.textContent || "").includes("breakdown"), 3000);
      const sourceLineClick = {
        clicked: !!sourceLine,
        activeText: activeText(),
        focusedNode: document.querySelector(".react-flow__node .node.focused .node-name")?.getAttribute("title") || null,
        selectedPanelHeading: document.querySelector(".read-panel h2")?.textContent || null,
      };

      const beforeWidth = document.querySelector(".canvas")?.getBoundingClientRect().width || 0;
      const sourceButton = [...document.querySelectorAll('.toolbar-group[aria-label="source"] button')]
        .find((button) => visibleText(button).trim() === "source");
      click(sourceButton);
      await waitFor(() => !document.querySelector(".source-pane"));
      const afterWidth = document.querySelector(".canvas")?.getBoundingClientRect().width || 0;
      const toggleOff = {
        closed: !document.querySelector(".source-pane"),
        canvasReclaimedWidth: afterWidth > beforeWidth,
      };

      return { initial, hostClick, memberClick, sourceLineClick, toggleOff };
    }

### clean

Strip the chrome-devtools result wrapper and pretty-print the JSON report.

- type: code
- inputs:
    raw: ${drive.result}

```python code
raw: str

import json

start = raw.find("{")
end = raw.rfind("}")
result: str = json.dumps(json.loads(raw[start : end + 1]), indent=2) if start != -1 else "{}"
```
