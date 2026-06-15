# Plan: `.pflow.md` Source Pane (left) with Canvas Click-Sync

> Audience: an implementing agent working in isolation. Verified against the codebase on
> branch `feat/workflow-visualization-static-viewer` on 2026-06-12 by three
> pflow-codebase-searcher passes (frontend shell seams / server + SourceRef semantics /
> contract + mapping). Small Python surface (ONE new read-only endpoint + tests);
> everything else is `web/`. NEVER git add/commit/push (project rule). Read
> `web/CLAUDE.md` and `src/pflow/ui/CLAUDE.md` before starting.

## Context

The canvas reveals a workflow's implicit structure; the `.pflow.md` file is the truth.
This increment links them: a collapsible LEFT pane showing the raw source (shiki
markdown-colored — the seam `utils/highlight.ts` was explicitly built for this, its
header names the source pane as its next consumer), with bidirectional click-sync —
click a node, see its authored lines; click a line, focus its node.

User decisions (locked, 2026-06-12 conversation):

- **Comprehension-only. NO diff view** — the user reviews agent edits as unstaged diffs
  in their IDE (Cursor) and stages as approval; an in-UI textual diff would duplicate a
  better tool. (Consequence for the FUTURE editor increment, recorded here so it isn't
  re-litigated: write to the working tree unstaged and lean on that loop — no in-UI
  apply-preview/approval. The only diff-shaped thing the IDE can't do is a STRUCTURAL
  canvas diff — out of scope, wait for observed pain.)
- **Multi-file = one file at a time, auto-switching with selection** (option A; tabs and
  inline-stitching rejected — stitching fabricates a document that exists nowhere on
  disk, breaking line numbers and the staging mental model). A breadcrumb header names
  where you are (`run-from-plan → execute-plan`); crumbs are clickable.
- **Host clicks land in the PARENT file** at the invoking `### step` (that's where the
  host's SourceRef points — and where its `inputs:` bindings live); **member clicks land
  in the CHILD file**. This falls out of the contract for free (see Facts).
- Batch item copies share one source line (one line → many canvas nodes): inverse
  mapping picks the first rendered instance, the `resolveNodeFlatId` precedent.
- Registry-resolved sub-workflows live under `~/.pflow/workflows/` — the breadcrumb
  tooltip carries the full absolute path so the short name can't hide that you're
  reading an installed copy.

## Verified facts the design rests on (searcher-cited, 2026-06-12)

### Contract / mapping (no Python contract changes needed)

- `SourceRef {file, line}` ships per node (`RFNode.source`, types.ts:84) and per param
  (`RFParam.source`, types.ts:22-29). `file` is an **absolute, symlink-resolved** path
  in every server-reachable flow (workflow_resolver.py:142/211, manager.py:304-313,
  sub_workflow_resolver.py:144-185). `line` is 1-based: the `### node-id` heading line
  for nodes (markdown_parser.py:1637). (Per-param line coverage VARIES — code-block
  params get lines via `_source_lines`; markdown_parser:1666/:1673 track OUTPUT
  `source:` lines, not params — nothing in this plan depends on param lines; v1 maps
  node lines only.) **`SourceRef.line` can be null on a non-null SourceRef**
  (build.py:735-739 always constructs one) — every line comparison must filter
  `line != null` first (JS `null <= n` coerces true → a null-line node would read as
  line 0; review-critical).
- Sub-workflow members carry the **child** file (build.py:269/278); the host node
  carries the **parent** file (its `### step` line). This is exactly the locked
  host-vs-member behavior — zero special-casing.
- `source` is null on: `kind:"input"` io nodes (build.py:152-191 passes no `source=`),
  synthetic `kind:"end"` nodes. `kind:"output"` nodes DO carry source (build.py:226).
  **Contract gap, accepted for v1:** `## Inputs` declaration lines are unmappable; a
  later Python addition mirroring build.py:226 closes it. Input-row clicks don't scroll
  the source in v1.
- Breadcrumb derivation is pure-frontend: ancestor k of a selected node resolves to the
  RFNode with `ref.node_id === path[k].node_id` AND `ref.ancestor_path` equal to the
  prefix `path[0..k-1]` AND `is_group_host` (node_id alone is NOT unique — deep-research
  has a workflow host `score` (n10) and an output port `score` (n16); the prefix +
  is_group_host filter disambiguates). **A crumb stores the host's CONTRACT flat id and
  resolves it through `resolveEndpointFlatId` AT CLICK TIME (review-critical):** an
  expanded host's own flat id is never in `renderedIds` (its representative GROUP is) —
  `onNavigate(rawHostId, …)` would dim the whole canvas against an id nothing carries.
  Resolution `null` → switch the file only, no canvas action (the same degrade rule as
  line clicks).
- Inverse mapping (line → node) is a pure filter: nodes whose `source.file` matches the
  displayed file AND `source.line != null`, pick greatest `source.line <= clickedLine`.
  Resolution to a rendered flat id: **iterate the tied/equal-line candidates in contract
  order until ONE resolves** via `resolveEndpointFlatId(graph, renderedIds, node.id)`
  (viewParams.ts:98-108 — handles suppressed group hosts and shell batches; a literal
  batch can have item 0 collapsed while item 1 is visible — first-that-RESOLVES, not
  first-in-order, review-caught). An IO-MEMBER candidate (`ref.port != null` — output
  nodes carry source but never render as nodes) resolves to its wrapper GROUP's flat id
  (the io card id IS the wrapper group id) so clicking an output's `source:` line
  focuses the Outputs card. All candidates `null` (hidden in a collapsed ancestor) →
  no-op on canvas, still highlight the line locally (the EdgePanel disabled-chip
  precedent: degrade visibly, never silently mis-fire).
- File sizes: largest example `.pflow.md` is 32.5k chars (generate-changelog), 1,121
  lines; execute-plan is 20.3k. **The existing 50k highlight cap needs NO change** — an
  over-cap file degrades to plain text with the existing console.info, which is the
  correct behavior for a pathological file anyway. Do not add a cap override.
- Shiki output is one `span.line` element per line with `"\n"` text nodes between
  (per-line click/scroll targets exist structurally; `codeChildren()` in highlight.ts
  already unwraps `pre > code`).

### Server (`/api/source`)

- Routes live in `create_app()` (server.py:135-158); a new `Route("/api/source", source)`
  goes in the list BEFORE the static mount/catch-all (registration order is precedence —
  pinned rule in ui/CLAUDE.md).
- **Design: inline-ALL files in one response; NO client-supplied file path.**
  `GET /api/source?workflow=<name|path>` → `{"root": "<abs path>", "files": {"<abs
  path>": "<text>", ...}}`. The server already re-parses the workflow per request (the
  task-168 inline-all precedent); collecting `{n.source.file for n in model.nodes if
  n.source and n.source.file}` from the **GraphModel** returned by
  `resolve_validate_build` and reading each file kills the whole `?file=` +
  whitelist + 403/404-arm + traversal surface. Error arms mirror `/api/graph` exactly:
  400 missing param, 422 `WorkflowGraphValidationError` (broken workflows get no source
  — consistent with the frontend error branch, see below), anything else → loud 500.
- **Derive the file set from the GraphModel, NEVER the rendered RFGraph** — batch
  truncation (react_flow.py:194-198, items index ≥ 2 hidden when count > 4) can drop a
  child file from the RFGraph entirely; the GraphModel keeps every expanded level
  (RFGraph file set ⊆ GraphModel file set, searcher-verified).
- Scope: serve files from `Node.source` only — NOT `param_sources` (those include
  referenced prompt/code files like `./prompts/x.prompt.md`, whose content the panel
  already shows inline as the param value; serving them is a later want, not v1).
- Edge cases the handler must tolerate: an inline-content workflow (the `?workflow=`
  param containing newlines is parsed as literal markdown, workflow_resolver.py:98-101)
  → `file_path=None` → every SourceRef.file is None → return `{"root": null, "files":
  {}}` (the pane shows an empty-state message, never crashes). A file that vanished
  between resolve and read → skip it with a logged warning (the workflow still renders;
  losing one file beats a 500). `depth_limit`-unexpanded children contribute no file —
  honest limitation, document in the endpoint docstring.
- Security: with no client file param there is no traversal surface; exposure equals
  what `/api/graph` already serializes (it inlines all param values including full
  prompts). The pre-existing **DNS-rebinding residual** (no Host check,
  server.py:149-158 SECURITY comment) is NOT widened in kind by this endpoint but is
  worth a Host-header middleware as a SEPARATE follow-up — flag in the PR, do not
  scope-creep here.
- Test patterns: `TestClient(create_app())` in-process (test_ui.py:49), workflow
  fixtures via `write_workflow_file` + `_save_workflow` (test_ui.py:27-43), one focused
  test per status arm, 500 via `raise_server_exceptions=False` + patch.

### Frontend shell

- The pane is the FIRST child of `.graph-body` (GraphView.tsx:396-475), before
  `.canvas`, with its own resizer between pane and canvas. `.graph-body` is a flex row;
  `.canvas` is `flex: 1 1 auto; min-width: 0` (index.css:201-205).
- Selection is plain `useState` in `GraphCanvas` (`selectedId`, GraphView.tsx:78) with
  derived arms `selectedNode` (:283-289 — a selected container already resolves to its
  HOST node, which gives the parent-file behavior for free), `selectedIoGroup`
  (:294-298), `selectedEdge` (:303-306). **No selection context exists** — the pane
  renders inside `GraphCanvas` and takes props (the established panel pattern; do not
  invent a context).
- Source-line click → canvas = exactly `onNavigate(flatId, flatId)` (GraphView.tsx:333-345
  — sets focus, opens the panel, camera-follows with padding 0.45 / maxZoom 1.2 when
  rendered).
- `PanelResizer` is right-anchored in ONE line (`window.innerWidth - ev.clientX`,
  PanelResizer.tsx:21) — gains a `side: "left" | "right"` prop (default `"right"`,
  zero churn at the one existing call site; left = `ev.clientX`); the `.panel-resizer`
  CSS negative margins/accent (index.css:1151-1170) need a mirrored variant class.
- `panelWidth.ts` is single-purpose: hardcoded `STORAGE_KEY` (:7) and a
  `min(860, viewport*0.7)` clamp (:11-14) that assumes ONE panel. Parameterize the
  load/save with a key (defaulting to the existing key — zero churn for the right
  panel) and make the clamp **SYMMETRIC (review-critical, flagged by three lenses)**:
  `clampPaneWidth(width, viewport, reserved)` where `reserved` = the OTHER column's
  width + `CANVAS_MIN = 320` — applied to BOTH panes. The source pane reserves the
  right panel's persisted width **even while no panel is open** (selecting a node
  mounts the ReadPanel without a drag — it must not crush the canvas); the right
  panel reserves the OPEN source pane's width. Re-clamp both whenever either width
  OR open-state changes (a one-effect re-clamp in GraphCanvas), not only on window
  resize.
- Toolbar toggles are controlled button groups (Toolbar.tsx:30-46); a single `source`
  toggle button slots after the direction group. The toolbar renders in BOTH the normal
  and error branches — **the toggle is HIDDEN in the error branch** (no `.graph-body`
  exists there; an active-looking dead button that only writes a URL param is worse
  than absence — gate it on a prop the error branch sets).
- URL params: add `source` (`1`/`0`-style open flag) as a READ+WRITTEN param like
  `density` (viewParams.ts:12-63; syncUrl GraphView.tsx:107-111) — deep links are how
  agents screenshot states. Pane width persists in localStorage (its own key); open
  state rides the URL only (default closed).
- **Error branch** (GraphView.tsx:375-389) renders no `.graph-body` — accepted for v1
  and actually CONSISTENT: a broken workflow 422s on `/api/source` too (same
  resolve+validate path), so there is no source to show through this app's data path.
  Document, don't restructure.
- `api/client.ts` pattern for `fetchSource`: encodeURIComponent param, `!ok` →
  `ApiError`, shape-validate the 200 (never cast).

## Implementation phases

> Gates after each phase: `cd web && npx vitest run && npm run build` for frontend
> phases; `uv run pytest tests/test_cli/test_ui.py` + `make check` for Phase 1 (it
> touches Python). Dev loop: `uv run pflow ui --no-open` + `cd web && npm run dev`.

### Phase 1 — `/api/source` endpoint (Python; independent, ship-alone-able)

1. `src/pflow/ui/server.py`: new `async def source(request)` —
   - missing/empty `workflow` → 400 (mirror `graph()`'s arm verbatim).
   - `model = resolve_validate_build(workflow, max_depth=_MAX_DEPTH)` inside the same
     `WorkflowGraphValidationError` → 422 handling.
   - `files = sorted({n.source.file for n in model.nodes if n.source and n.source.file})`
     — **GraphModel nodes, not the RF render** (truncation gap; see Facts). The double
     guard is load-bearing: io input nodes ship `source=None`, inline-content nodes ship
     `SourceRef(file=None)`.
   - Root derivation (**review-critical — the naive rule is WRONG**): `build_level`
     adds INPUT nodes first, with `ancestor_path == ()` and **no source** — so "the
     first top-level node's file" picks an input and yields `root: None` on any
     workflow with `## Inputs` (i.e. nearly all). Correct rule: the `source.file` of
     the first node with `node.id.ancestor_path == ()` AND `node.source is not None`
     AND `node.source.file`. If NO node carries a file (inline-content workflow) →
     `{"root": None, "files": {}}`. An inline root invoking SAVED-NAME sub-workflows
     can yield `root: None` with a NON-empty files map — the pane then shows the first
     file (sorted order) with the root crumb disabled.
   - Read each file (`Path(f).read_text()`); a read failure skips that file with
     `logger.warning` (never a 500 for one missing file).
   - Respond via `_json({"root": root, "files": files_map})`.
   - Register `Route("/api/source", source)` before the catch-all; add the endpoint to
     the module docstring's list (server.py:3-11) AND the `_frontend_not_built` message
     ("The API is live at …", server.py:128-130) — both enumerate endpoints in-file.
2. Tests in `tests/test_cli/test_ui.py`, new class `TestSourceEndpoint` mirroring
   `TestGraphEndpoint`: 200 single-file (body text equals disk content; root set —
   **the fixture workflow MUST declare `## Inputs`**, or the root-derivation bug this
   plan corrects passes undetected); 200 multi-file (parent + sub-workflow under
   `tmp_path`, both present, an unrelated `tmp_path` file ABSENT from the map); 400
   missing param; 422 invalid workflow; inline-content workflow → empty files, not a
   crash.
3. Update `src/pflow/ui/CLAUDE.md` (endpoint table + the GraphModel-not-RFGraph rule).

### Phase 2 — pure frontend helpers + data seam (`utils/sourceMap.ts`, `fetchSource`)

1. `web/src/types.ts`: `SourceFiles { root: string | null; files: Record<string, string> }`.
2. `web/src/api/client.ts`: `fetchSource(workflow)` per the house pattern (ApiError +
   shape guard).
3. `web/src/utils/sourceMap.ts` — pure, node-env testable (NO React):
   - `nodeAtLine(graph: RFGraph, file: string, line: number): RFNode[]` — ALL
     candidates at the greatest `source.line <= line` among nodes with
     `source.file === file` AND **`source.line != null`** (the null-coercion guard,
     Facts), in contract order — the caller iterates until one RESOLVES (batch copies:
     item 0 may be collapsed while item 1 renders).
   - `breadcrumbFor(node: RFNode, graph: RFGraph): Crumb[]` — walk `ref.ancestor_path`
     resolving each ancestor host via the prefix + `is_group_host` rule (Facts);
     `Crumb { label: node_id, hostContractId: the host RFNode's id (resolved through
     resolveEndpointFlatId at CLICK time, never stored pre-resolved), file: parent
     file, line }` + a final crumb for the node's own file. Root crumb label = the
     workflow name slot the caller passes.
   - `fileChainFor(file, graph)` — the crumb chain for a DISPLAYED file when there is no
     selection (manual crumb navigation): map each file to the host whose members live
     in it (first member's prefix; a sub-workflow invoked TWICE maps to its first
     invocation — documented rule), root file → root-only chain, and an ORPHAN file
     (in the served map but absent from the RFGraph — truncation can produce one) →
     root-only chain, never a throw.
4. Tests `web/src/utils/sourceMap.test.ts` (node-env) against the committed real
   contract fixtures (`web/src/test/fixtures/contracts/deep-research.json` spans 4
   files — the searcher-verified shapes): nodeAtLine exact-hit, between-nodes,
   before-first-node (empty), batch-copy tie (all candidates, contract order), wrong
   file (empty), **a null-line node never matches** (synthetic fixture — deep-research
   has no sourceless-line outputs, so this needs its own case); breadcrumb for the
   nested `evaluate` node (`analyze-sources → score`) including the score-vs-score
   host/port disambiguation; fileChainFor root + nested + orphan-file fallback.

### Phase 3 — the pane (`components/SourcePane.tsx`) + shell integration

1. **The source FETCH lives beside the graph fetch, not in the pane (review-critical,
   two lenses).** `GraphCanvas` (or `useWorkflowGraph`) fetches `fetchSource(workflow)`
   together with the graph, keyed by workflow, cached across pane toggles. Why: (a) a
   pane-mounted fetch races the `?focus=…&source=1` deep link — the flagship screenshot
   scenario — and any click landing before the fetch resolves; (b) graph and source
   fetched minutes apart can be MUTUALLY inconsistent across an agent edit (every line
   mapping silently wrong — the exact window this feature serves); fetching both in one
   place takes one snapshot and a reload refreshes both; (c) re-opening the pane must
   not refetch + flash. A fetch error → in-pane banner (the pane never blanks the
   canvas). Residual drift (file edited after BOTH fetched) is documented: stale
   together is internally consistent; refresh reloads both.
2. `SourcePane.tsx` is PRESENTATIONAL — props:
   `{ source: SourceFiles | null, sourceError, graph, selectedNode, renderedIds, onNavigate }`.
   - Displays ONE file: state `currentFile`, defaulting to `root` (root null +
     non-empty files → first file, root crumb disabled; root null + empty files →
     the empty-state message, never `files[null]`).
   - **A `currentFile` ABSENT from the files map** (server skipped an unreadable file;
     SourceRefs still point at it) → keep the previous file and show an in-pane notice
     ("source for `<basename>` could not be read") — never render `undefined`
     (review-caught: the plan built the producing arm; this is the consuming arm).
   - Header = breadcrumb; a crumb carries the host's CONTRACT id and resolves via
     `resolveEndpointFlatId` at click time (Facts) — resolved: switch file +
     `onNavigate(resolved, resolved)`; null: switch file only. Basename + absolute
     path on the tooltip.
   - Renders `highlight(text, "markdown")` per file, memoized per file path (cold-load
     degrades to plain text then upgrades — the CodeBlock first-paint pattern). Walk
     the hast `codeChildren` grouping by `span.line` elements into per-line rows:
     gutter number + content, `data-line`, `onClick`. Plain-text fallback =
     `text.split("\n")` rows (same row chrome, no colors).
   - Line click: `nodeAtLine` candidates → iterate-until-resolves (Facts) →
     `onNavigate(flatId, flatId)`; all-null: mark the line locally only.
   - Canvas→source sync: an effect on `[selectedNode, source]` — **depending on the
     files map is load-bearing** (when files land AFTER a deep-link selection, the
     effect re-applies the CURRENT selection; review-caught race). Guard null
     `selectedNode` (edge/io selections) AND null `source` (input/end nodes) → keep the
     current file, no scroll. **The SCROLL lives in its OWN effect keyed on
     `[currentFile, activeLine]`** — never in the effect that switches `currentFile`
     (the new file's rows don't exist in the DOM during that run; same-effect scroll
     silently no-ops on every cross-file click, and jsdom can't catch it —
     review-caught). `scrollIntoView({block:"center"})` optional-called (IoPanel
     precedent); `.src-line-active` is state-driven.
3. GraphView integration: `sourceOpen` state from the URL param (`readViewParams`),
   toolbar toggle writes it via `syncUrl` (hidden in the error branch); render
   `<SourcePane …/>` + a `<PanelResizer side="left" …/>` as the first children of
   `.graph-body`; width state via the parameterized `loadPanelWidth("pflow-ui:source-w", …)`
   and the SYMMETRIC two-pane clamp (Facts — both directions, closed-state
   reservation, re-clamp on open-state change); `--source-w` var set inline beside
   `--panel-w`.
4. `PanelResizer` gains `side` (default `"right"` — zero churn at the existing call
   site); CSS: `.panel-resizer.left` mirrored margins/accent; new `.source-pane` block
   (flex column; header; scrollable mono body; `.src-line` grid `[gutter|content]`,
   hover bg, `.src-line-active` accent bg; gutter `--text-faint`).
5. Toolbar: `source` toggle button (label `source`, active state), after the direction
   group; prop drilled like density; hidden in the error branch.
6. `viewParams.ts`: `source` param read+write + tests beside the existing ones (note:
   `viewParams.test.ts:12` asserts a full-object `toEqual` — adding the field breaks it
   loudly; expected churn).

### Phase 4 — tests, docs, verification

1. jsdom tests `components/SourcePane.test.tsx` (mock `../utils/highlight` → null for
   sync rendering, the established insulation pattern; source data passed as props —
   the fetch lives in GraphCanvas): renders lines with gutter numbers from plain text;
   line click on a node's heading line calls `onNavigate` with the resolved flat id;
   line click below the last node maps to the last node; selectedNode change switches
   file + marks the line (the SCROLL itself is jsdom-untestable — the active-line
   STATE is the assertion; scroll position is a Phase-4.3 manual check, explicitly);
   the empty-files state renders its message; a `currentFile` missing from the files
   map renders the could-not-read notice; source error → in-pane banner. GraphView
   integration pins: toggling `source` mounts the pane and a node click marks the
   expected line — **add `fetchSource: vi.fn()` to the existing `api/client` mock
   factory** (it spreads `...actual`, so an un-mocked fetchSource hits real fetch) and
   **follow the file's try/finally URL-reset pattern** (syncUrl replaceState leaks
   `source=1` into subsequent tests — the documented cross-test trap). Also:
   PanelResizer left-arm test beside the existing right-anchored one
   (PanelResizer.test.tsx:22-28 pins the math); `panelWidth.test.ts` cases for the
   parameterized key + symmetric clamp; `client.test.ts` fetchSource arms (the four
   fetchGraph-style cases: 200, malformed-200 shape guard, 422 diagnostics, non-JSON
   body).
2. Docs: `web/CLAUDE.md` (new "Source pane" bullet: one-file-at-a-time + breadcrumb
   semantics, the GraphModel-derived file map, the fetch-with-graph snapshot rule, the
   no-diff decision + why, the inputs-line contract gap AND the io-card-selection gap);
   `src/pflow/ui/CLAUDE.md` (endpoint); **`.claude/skills/screenshot-pflow-web-ui/SKILL.md`
   URL-params table gains `source`** (deep links are how agents screenshot — the table
   is the agent surface; add the pre-existing missing `collapse` row in passing);
   task-168 `visualization-requirements.md` Implemented bullet; progress-log entry
   (decisions: inline-all-files over `?file=` whitelist; no-diff rationale; the
   GraphModel-not-RFGraph truncation trap; fetch-with-graph over pane-mounted fetch).
3. Real browser (screenshot-pflow-web-ui; rebuild via `make ui-build`):
   `?workflow=examples/agent-orchestration/plan-to-code/run-from-plan.pflow.md&source=1`
   — pane shows colored source; click the `execute-plan` container → pane stays in
   run-from-plan.pflow.md at the invoking step; expand + click a member → file switches
   to execute-plan.pflow.md, breadcrumb shows both levels; click a `### step` line →
   canvas focuses that node (verify via the inspect workflow's focus state); toggle
   off → canvas reclaims the width.
4. **Code review (repo practice):** after gates pass, `/code-review` the changes and
   work confirmed findings.

## Explicit non-goals (do not build)

- **No diff view of any kind** (user decision — the IDE staging loop is the review
  surface; the `diff` grammar stays unloaded).
- No editing/write-back; no auto-expanding collapsed ancestors on line-click misses.
- No serving of param-referenced prompt/code files (panel already shows their content).
- No `## Inputs` line mapping (contract gap — needs a Python `_add_inputs` change;
  noted, not built). Likewise no canvas→source sync from an IO-CARD selection
  (`selectedIoGroup` leaves `selectedNode` null — output nodes carry source, but a
  wrapper has no single line; documented gap beside inputs, NOT an ad-hoc fix).
  The reverse direction DOES work: an output's `source:` line click focuses the
  Outputs card (the io-member → wrapper-group arm, Facts).
- No Host-header/DNS-rebinding middleware (pre-existing residual for ALL endpoints —
  flag in the PR as a separate follow-up).
- No highlight-cap override; no tabs; no stitched multi-file view.
