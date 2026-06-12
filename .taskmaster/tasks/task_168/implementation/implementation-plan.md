# Plan: Markdown + Code Rendering in the pflow Web UI

> Audience: an implementing agent working in isolation. Everything here was verified
> against the codebase on branch `feat/workflow-visualization-static-viewer`
> (worktree `/Users/andfal/projects/pflow-worktrees/feat-workflow-visualization-static-viewer`)
> on 2026-06-12 by three pflow-codebase-searcher passes. **Zero Python/contract
> changes** — this is entirely a `web/` frontend task. NEVER git add/commit/push
> (project rule). Read `web/CLAUDE.md` before starting.

## Context

Workflow authors write real markdown in `description:` fields (backtick code spans,
`**bold**`, `*` bullet lists) and real Python/JSON/bash in params — the `pflow ui`
frontend currently renders all of it as inert plain text (raw asterisks in panels,
flat grey `<pre>` blocks for code). This task renders it properly:

- **Rendered markdown** for prose descriptions in the panels (ReadPanel, IoPanel) and
  catalog (inline-only).
- **Syntax highlighting** for code-shaped param values (Python, bash, JSON, YAML) and
  **markdown-source coloring** for prompts (verbatim text, colored like VS Code — NOT
  rendered; user decision).
- **Markdown stripping** for the 2-line-clamped canvas description lines and `title=`
  tooltips (can't render formatting there — hide the symbols instead).

User decisions (locked):
- (a) Canvas cards + tooltips: strip markdown to plain text.
- (b) Catalog descriptions: inline-only markdown (bold/code spans), never block
  formatting (one row must not grow tall).
- Prompts render as **highlighted markdown SOURCE**, not rendered markdown.
- Future consideration shaping the design (NOT built now): a full `.pflow.md` source
  pane with GitHub-style diffs. The highlighter must therefore be ONE seam that the
  future pane can consume (markdown grammar with embedded yaml/python fences = Shiki's
  strength; the reason lowlight/highlight.js was rejected).
- Optimize for simplicity of the FINAL code (what the top 10% of similar codebases
  would do), not ease of getting there. No overengineering.

## Library decisions (researched + verified 2026-06-12)

- **react-markdown + remark-gfm** for rendered prose. Safe by construction (React
  elements, raw HTML not rendered by default — workflows are third-party content;
  no `dangerouslySetInnerHTML` anywhere). Current: react-markdown 10.x.
- **Shiki 4.x, fine-grained** (`shiki/core` + `shiki/engine/javascript` +
  `@shikijs/langs/<lang>` + `@shikijs/themes/github-dark-default`) for ALL code
  highlighting, behind ONE lazy-loaded module (the lazy-ELK precedent).
  **Version facts verified against shiki 4.2.0 (the current major; review-checked
  on the registry):** `createHighlighterCore`/`codeToHast` exported; the
  `shiki/core` and `shiki/engine/javascript` subpaths exist in v4's exports map;
  shiki 4 has NO per-language `shiki/langs/<lang>` subpath — grammars/themes import
  from `@shikijs/langs/*` and `@shikijs/themes/*`, so **declare `@shikijs/langs`
  and `@shikijs/themes` as direct deps** (never import an undeclared transitive).
  The pure-JS regex engine supports all built-in languages (since 3.9.1, holds in
  4.x) — no oniguruma WASM. Do NOT use `@shikijs/langs-precompiled` (needs ES2024
  RegExp `v`, known issues). If a 4.x API diverges from these notes, the shiki docs
  win — but verify against https://shiki.style, don't guess.
- Grammar set: `python`, `yaml`, `json`, `bash`, `markdown` (+ `diff` deferred until
  the source pane). Unknown language → plain text, fail-closed. All five grammars load
  eagerly INSIDE the lazy shiki chunk (one `createHighlighterCore` call — simpler than
  per-language lazy; the whole chunk is already lazy).
- Theme: built-in `github-dark-default` (the app's kind colors are GitHub-dark palette
  values — `#7ee787`, `#ffa657` etc., so token colors will sit naturally). Override the
  theme's `<pre>` background to `var(--bg)` via CSS (shiki inlines its own bg).
- Output path: `codeToHast` → React elements via `hast-util-to-jsx-runtime` (declare it
  as a direct dep; react-markdown already uses it internally — same ecosystem, no
  innerHTML anywhere). The existing `${ref}` highlight (ParamBlock `highlightRef`)
  survives as a post-walk over hast TEXT nodes wrapping `${...}` matches in the
  existing `.ref-mark`.

## Inventory of surfaces (verified exhaustive by searcher, 2026-06-12)

All paths under `web/src/`. The sweep `grep -rn "\.purpose\|\.description\|previewValue(\|fullValue(" web/src` confirmed no other surfaces exist.

### 1. Full markdown render (panels — prose descriptions)
- `components/ReadPanel.tsx:161` — `node.purpose` in `<p className="read-panel-purpose">`.
  **TRAP**: EdgePanel.tsx:174/177/179 renders app-written strings with the SAME
  `.read-panel-purpose` class — do NOT restyle that class for markdown; give the
  markdown component its own class (`.md`) and add it alongside.
- `components/IoPanel.tsx:102` — `port.description` in `<p className="io-port-desc">`.
  (`.io-port-desc` also wraps the `default:` line at :103-107 — leave that one plain.)
- NOTE: `.read-panel-purpose` (index.css:1188) and `.io-port-desc` (index.css:1400)
  both use `white-space: pre-wrap` as the current "respect authored newlines"
  mechanism — the markdown container must NOT inherit pre-wrap (markdown owns
  paragraphs/lists).

### 2. Highlighted code (Shiki)
- `components/ReadPanel.tsx:41-77` ParamBlock — `<pre className="read-param-value">`
  via `fullValue(param.value)`; used by ReadPanel (all params) and EdgePanel:222
  (one param + `highlightRef` ref-marking via parseTemplate, lines 59-72).
  This is THE code surface. Language per the policy table (below).
- `.read-param-value` CSS recipe to preserve (index.css:1245-1257): bg var(--bg),
  1px var(--border), radius 6px, mono 11px, pre-wrap, max-height 280px scroll.

### 3. Strip markdown → plain text (canvas + tooltips; stripMarkdown() helper)
- `components/nodes/WorkflowNode.tsx:287-289` — `.node-name` purpose line (2-line clamp).
- `components/nodes/GroupNode.tsx:150-155` — `.node-name` host purpose on container header.
- `components/nodes/IOCardNode.tsx:67-69, 89-91` — soleDescription as title + tooltip.
- `components/nodes/PortRows.tsx:25-30` — `rowTitle(port)` tooltip (description part).
- This list is COMPLETE — independently re-verified by two review passes (the only
  other sweep hit, `flow.ts:719`, derives `Port.description` consumed by the
  surfaces above). Do not hunt for more.

### 4. Inline-only markdown
- `views/CatalogView.tsx:47` — `item.description` in `.catalog-item-desc`
  (index.css:129-131). Inline elements only (bold/italic/code/links-as-text);
  block constructs flatten to one flowing line.

### 5. Deliberately UNTOUCHED (authored expressions in tiny truncated pills — plain text is correct)
- `components/edges/GradientEdge.tsx:267-285` condition pill; `LoopEdge.tsx:73-88`
  loop label; `DataEdge.tsx:99-113` field label; `BranchPorts.tsx:36-40` condition
  rows; `WorkflowNode.tsx:363-377` loop-rule rows; `ChipRail.tsx:20-29` tooltips
  (authored conditions/source_refs — tooltips can't render, and these are code
  fragments, not prose — no stripping either, `**` in a python expr is power-op).
- ReadPanel StructuralFacts / OutcomeTable condition `<dd>`s, EdgePanel condition
  facts — single-line expressions; highlighting one-liners adds noise, skip in v1.
- WorkflowNode ParamValue (canvas param previews + ref chips) — already purpose-built.

## Infra patterns to follow (verified by searcher, 2026-06-12)

- **Lazy loading = promise-memoized dynamic import, NOT React.lazy/Suspense** (there is
  zero Suspense in the codebase). Template = `web/src/graph/layout.ts:16-53`:
  type-only static import + `let p: Promise<X> | null = null; const load = () => (p ??= import(...))`,
  awaited inside an already-async path, failure surfaced (never swallowed).
  Shiki must follow this shape. ELK loads as its own Vite chunk purely because its only
  non-type references are dynamic imports — same will hold for shiki.
- **Async UX pattern**: hook-managed status state (`useWorkflowGraph`'s
  loading/ready/empty/error), not Suspense. For highlighting: render plain `<pre>` text
  immediately, swap in highlighted hast when ready (no spinner — text is already
  readable; highlight is progressive enhancement).
- **No bundle-size guard exists** (the "size tripwire" is a dev-only node-overflow
  console.warn in WorkflowNode.tsx:230-244 — unrelated). Only Vite's stock 500 kB
  chunk warning. Plan must not invent a size-check infra; just keep shiki+markdown in
  lazy/own chunks and note expected sizes.
- **Tests**: default env node; jsdom opt-in via `// @vitest-environment jsdom` first
  line. No setupFiles — explicit per-file setup, `afterEach(cleanup)`. Panel tests
  build fixtures with small builder fns (`node()/edge()/group()` + spread overrides,
  flat ids deliberately ≠ ref.node_id). Async assertions: testing-library
  `waitFor`/`findBy*`. Pure helpers (format.ts) get node-env tests with behavior-named
  descriptions. RF mocks (`test/rf-jsdom.ts`) only needed when mounting ReactFlow —
  panel tests don't need them.
- **tsconfig**: `moduleResolution: "bundler"` (shiki subpath exports + ESM-only
  react-markdown resolve cleanly), `strict` + `noUncheckedIndexedAccess` (indexing
  returns `T | undefined` — watch hast-walk code). `npm run build` runs
  `tsc --noEmit` first.
- **Deps**: `web/package-lock.json` is committed; CI/`make ui-build` runs `npm ci`;
  release CI pins Node 22. Adding deps = edit package.json + run `npm install` to
  update the lockfile (then commit both — but NEVER git-commit unless user asks).
- **CI gap (flag, don't fix here)**: PR CI has no Node step — web tests are
  local-discipline only.

## Language policy (verified against node interfaces + parser + corpus)

Facts the policy rests on (searcher-verified):
- `RFNode.kind` is the raw IR `type` verbatim: `shell`, `http`, `llm`, `claude-code`,
  `code`, `workflow`, `read-file`/`write-file`/`copy-file`/`move-file`/`delete-file`,
  and `mcp-<server>-<tool>` (never bare `mcp`).
- `RFParam.value` ships as the RAW parsed object/string (never serialized text):
  dict-authored params (` ```yaml output_schema `, `inputs:`, `headers:`) arrive as
  JSON objects; fence-authored text (` ```python code `, ` ```prompt `) arrives as raw
  string. A param like `output_schema` CAN legally be a string (templated/other fence
  tag) — so branch on the VALUE TYPE, never assume by name.
- File-referenced prompts (`- prompt: ./x.prompt.md`) ship as the file's CONTENT
  (resolve_workflow contract) — markdown coloring is valid for them.
- MCP param names are tool-defined and unenumerable → fail-closed.
- No authored `description:` contains `${...}` (corpus grep) → ref-marking stays a
  ParamBlock concern only; the Markdown prose component does NOT handle refs.

`paramLanguage(kind: string, name: string, value: unknown): string | null` — new pure
helper in `utils/format.ts`:

| Rule (first match wins) | Language |
|---|---|
| `typeof value === "object" && value !== null` | `"json"` (text is already `fullValue`'s JSON.stringify) |
| kind `code`, name `code` | `"python"` |
| kind `shell`, name `command` | `"bash"` |
| kind `llm`, name `prompt` or `system` | `"markdown"` |
| kind `claude-code`, name `prompt` or `system_prompt` | `"markdown"` |
| anything else (http `body` strings, `write-file` `content`, mcp strings, templates…) | `null` → plain `<pre>` (today's rendering) |

Fail-closed: `null` means "render exactly as today". Do NOT add cleverness (no
file-extension sniffing on write-file content, no JSON.parse probing of strings).

---

## Implementation phases

> Each phase is independently verifiable; run `cd web && npx vitest run && npm run
> build` (build includes `tsc --noEmit`, strict + `noUncheckedIndexedAccess`) after
> each. Dev loop: `uv run pflow ui --no-open` + `cd web && npm run dev`.

### Phase 1 — green baseline + deps + pure helpers (`stripMarkdown`, `paramLanguage`)

0. **Restore the green baseline (user-decided 2026-06-12):** update the one failing
   pre-existing test, `web/src/views/GraphView.test.tsx:135-137`, to the NameLabel
   design (which is staying): the no-purpose node's name ("done") is no longer the
   `.node-name` fallback text — assert it on the NameLabel chrome instead
   (`.node-name-label` renders `node.ref.node_id`; in beautiful density it's
   `humanizeId(name)`, in advanced the verbatim name — check the density the test
   drives before picking the matcher). Do NOT change WorkflowNode.tsx behavior; the
   test catches up to the design, not vice versa. Run the suite — all green before
   anything else. (The `MOCK:` comments in WorkflowNode.tsx:269/282-285 can be
   reworded to normal comments in passing IF touching that file later anyway —
   otherwise leave them.)
1. Add deps in `web/`: `npm install react-markdown remark-gfm shiki @shikijs/langs
   @shikijs/themes hast-util-to-jsx-runtime` (latest stable; lockfile updates
   automatically — `package-lock.json` is committed, leave staging/commits to the
   user). Imports: `shiki/core`, `shiki/engine/javascript`, `@shikijs/langs/<lang>`,
   `@shikijs/themes/github-dark-default` (see the version facts in Library
   decisions). `moduleResolution: "bundler"` handles the exports maps.
2. `utils/format.ts` — add two pure exports:
   - `stripMarkdown(text: string): string` — strip, keeping content: emphasis
     markers, backticks (keep code text), ATX `#` heading markers, list markers
     (`-`/`*`/`+`/`1.` at line start), blockquote `>`, links `[text](url)` → `text`,
     images `![alt](url)` → `alt`, then collapse whitespace runs to single spaces
     (reuse `collapseWhitespace`). NOT a markdown parser — a display de-noiser; it
     must never throw and never drop non-marker text.
     **Emphasis regexes MUST require CommonMark-ish flanking (review-critical —
     naive pairing corrupts prose):** an opening `*`/`**`/`_`/`__` delimiter must be
     followed by non-space, a closing one preceded by non-space, and `_` must NOT
     match intraword. Otherwise "joins items_list and total_count" →
     "joins itemslist and totalcount", "delete *.tmp and *.log" loses the globs,
     "2*3 and 4*5" → "23 and 45" — while react-markdown (CommonMark flanking)
     renders all of these LITERALLY in the panel one click away, so the canvas
     would silently disagree with both the file and the panel.
   - `paramLanguage` per the table above.
3. Tests in `utils/format.test.ts` (node-env, existing style — behavior-named):
   stripMarkdown: bold/italic/code-span/bullets/heading/link/image cases + "leaves
   plain text untouched" + "never throws on pathological input (`**unclosed`)" +
   the THREE corruption pins: `snake_case identifiers survive`, `*.py globs
   survive`, `2*3 arithmetic survives`.
   paramLanguage: full table matrix + fail-closed pins (object on mcp-* → json;
   `output_schema` as STRING → null; llm `prompt` → markdown; unknown kind → null).

### Phase 2 — strip markdown on canvas + tooltips (independent, ship-alone-able)

Apply `stripMarkdown(...)` at exactly these sites (searcher-verified exhaustive):
- `components/nodes/WorkflowNode.tsx:287-289` — `{node.purpose ?? ""}` →
  `{stripMarkdown(node.purpose ?? "")}` (title attr is `node.ref.node_id` — not
  prose, leave).
- `components/nodes/GroupNode.tsx:150-155` — the `{hostNode ? (hostNode.purpose ?? "") : title}`
  arm → strip the purpose arm only.
- `components/nodes/IOCardNode.tsx:67-69` — strip `soleDescription` once where it's
  derived (feeds both the visible `title` line and the `tooltip` string).
- `components/nodes/PortRows.tsx:25-30` — `rowTitle()`: strip the `port.description`
  segment only (name/type/required are not prose).
Tests: one jsdom pin per component file where a test file already exists; otherwise
cover via the format.test.ts unit tests + a single GraphView-level assertion that a
markdown-authored purpose renders without `**` (fixture: a node whose purpose is
`"finds **tensions** in `code`"`).

### Phase 3 — the highlight seam (`utils/highlight.ts`) + `CodeBlock`

1. `utils/highlight.ts` — the ONE highlighter seam (pure, no React; node-env
   testable). Follow the lazy-ELK template (`graph/layout.ts:16-53`):
   type-only static imports; `let p: Promise<Highlighter> | null = null;
   const loadHighlighter = () => (p ??= create())` where `create()` dynamic-imports
   `shiki/core` + `shiki/engine/javascript` + the 5 grammars from
   `@shikijs/langs/<lang>` + `@shikijs/themes/github-dark-default` and calls
   `createHighlighterCore`. ONE deviation from the ELK template (deliberate —
   review-confirmed): on REJECTION, reset `p = null` before returning, so a
   transient chunk-load failure (stale tab across a rebuild → 404'd chunk hash)
   doesn't permanently disable highlighting for the session; `console.warn` per
   attempt. (ELK's rejection is user-visible via the error banner; ours is
   invisible-by-design, so retry is the honest behavior.) Exports:
   - `const HIGHLIGHT_LANGS = ["python", "bash", "json", "yaml", "markdown"] as const`
   - `highlight(code: string, lang: string): Promise<HastRoot | null>` — `null` for
     unknown lang AND for `code.length > 50_000` (a file-referenced prompt can be
     arbitrarily large and shiki tokenizes synchronously on the main thread —
     fail-closed to plain text, which already handles big values via scroll);
     `null` + warn on any load/highlight failure. Degrade, never throw into the
     panel.
   - `markRefs(root: HastRoot, highlightRef: string): number` — walks TEXT nodes,
     splits on `/\$\{[^}]+\}/g`, wraps segments matching `highlightRef` in
     `{type:"element", tagName:"mark", properties:{className:["ref-mark"]}}`.
     Returns the COUNT of marks landed (not a boolean — see the count rule below).
     Matching rule = EXACTLY the coalesce-operand logic currently inline in
     ParamBlock (ReadPanel.tsx:63-66) — EXTRACT that into
     `refMatchesHighlight(refBody: string, highlightRef: string): boolean` in
     `utils/format.ts` and consume it from BOTH places (single copy).
     Residual (document in code): a `${ref}` split across hast text nodes by the
     tokenizer stays unmarked — handled by the count-based fallback below, never by
     cross-node merging.
2. `components/CodeBlock.tsx` — `{ code: string; lang: string | null; highlightRef?: string }`.
   **THE FIRST-PAINT RULE (review-critical — three existing EdgePanel tests pin
   synchronous `.ref-mark` presence):** the immediate synchronous render is the
   LEGACY rendering — today's exact output, parseTemplate + ref-marks when
   `highlightRef` is set (that JSX moves here from ParamBlock lines 57-74, making
   CodeBlock the ONE component that renders a param value). The shiki hast only ever
   SWAPS IN later; highlighting is strictly an upgrade, never a downgrade of marks.
   No spinner, no Suspense — plain state + effect like the rest of the app.
   - `useEffect` (deps: `code`, `lang`, `highlightRef`; standard `let cancelled`
     stale-async guard): if `lang`, `await highlight(code, lang)`. If hast returned
     and `highlightRef` is set: compute `expected` = the number of ref segments in
     the plain text that match (`parseTemplate` + `refMatchesHighlight` — both
     already in hand), run `markRefs`, and **swap to the highlighted hast ONLY if
     `marksLanded === expected`** — a partial marking (tokenizer-split ref) would
     tell the user something false in the exact panel built to answer "which ref is
     this line", and `expected === 0` means marks add nothing so the swap is free.
     Without `highlightRef`, swap unconditionally. Render hast via `toJsxRuntime`
     (hast-util-to-jsx-runtime + react/jsx-runtime).
   - **DOM structure (review-pinned):** ONE `<pre>` — render the hast `<code>`
     children INSIDE our own `<pre className="read-param-value shiki-host">`; never
     nest shiki's `<pre>` inside ours (the inner UA `white-space: pre` defeats the
     container's `pre-wrap` → horizontal scrollbars on long prompt lines, a
     regression). The existing box recipe (index.css:1245-1257, incl.
     `white-space: pre-wrap; word-break: break-word`) stays the single container
     style.
3. `components/ReadPanel.tsx` ParamBlock — replace the `<pre>` block (lines 57-74)
   with `<CodeBlock code={fullValue(param.value)} lang={paramLanguage(kind, param.name, param.value)} highlightRef={highlightRef}/>`.
   ParamBlock gains a `kind: string` prop. Call sites: ReadPanel.tsx:181 passes
   `node.kind`; EdgePanel.tsx:222 passes the param OWNER's kind —
   `targetNode?.io ? (targetHost?.kind ?? "") : (targetNode?.kind ?? "")`
   (for an IO-port target the param comes from `bindingParam(targetHost, …)` at
   EdgePanel.tsx:120-126, so `targetNode.kind` would be the port's `"input"`, not
   the owner's — latent-wrong, review-caught).
4. CSS (index.css, read-panel section ≥1137): token colors arrive inline from the
   theme; the container bg is ours — no `!important` needed when shiki's `<pre>` is
   not rendered (step 2's structure): only the `<code>` children carry token spans.
   `.ref-mark` (index.css:1296) applies inside hast output unchanged.
5. Tests:
   - `utils/highlight.test.ts` (node-env): python/json/markdown produce hast with
     token spans; unknown lang → null; oversize input → null; `markRefs` returns the
     mark COUNT, 0 when nothing matches; coalesce-operand matching via the shared
     helper; failure path (mock import failure) → null + warn, never throw, and a
     SECOND call retries (the rejection is not memoized).
   - `components/CodeBlock.test.tsx` (jsdom): legacy output (incl. `.ref-mark`)
     renders SYNCHRONOUSLY; highlighted spans appear after `await findBy*`; the
     count rule — a fixture with TWO matching refs where only one is markable in
     hast keeps the legacy rendering (mixed-tokenization case); `lang=null` renders
     exactly the legacy path; NO nested `<pre>` in the highlighted output.
   - **Insulate the existing EdgePanel suite (review-required):** add
     `vi.mock("../utils/highlight")` (highlight → resolves null) in
     `EdgePanel.test.tsx` so its three ParamBlock-rendering tests stay synchronous —
     otherwise the real shiki load runs under jsdom and its setState lands AFTER the
     tests' assertions (act warnings + cross-test bleed through the memoized
     promise). The suite's six `.ref-mark` pins must pass UNCHANGED (first-paint
     rule guarantees it).

### Phase 4 — Markdown component + the three prose surfaces

1. `components/Markdown.tsx` — `{ text: string; inline?: boolean }` wrapping
   react-markdown + remark-gfm:
   - **Block mode** (panels): container `<div className="md">`. Component map:
     `a` → `target="_blank" rel="noreferrer"`; `img` → render `alt` text only (no
     remote fetches from third-party workflow content); `pre` → extract the child
     `<code>`'s `language-X` className + text → `<CodeBlock code lang>` (lang must be
     in `HIGHLIGHT_LANGS` else null — fail-closed); inline `code` → plain `<code>`
     (styled). Raw HTML is NOT rendered (react-markdown default — keep it; this is
     the security stance, pin it in a test).
   - **Inline mode** (catalog): `allowedElements={["p","li","em","strong","del","code","a","img"]}`
     + `unwrapDisallowed`. **Separator rule (review-critical):** the component map
     does NOT run for unwrapped (disallowed) elements, so `p` and `li` must stay
     ALLOWED and be mapped to a Fragment that appends a trailing `" "` — otherwise
     `unwrapDisallowed` concatenates block boundaries with no whitespace
     (`- first\n- second` → "first itemsecond item"). `a` maps to its children text
     (catalog items are `<button>`s — a nested `<a>` is invalid HTML); `img` maps to
     its `alt` text (unwrapping an img yields NOTHING — alt lives in an attribute,
     not children). Inline mode renders NO block wrapper at all (no `.md` div — the
     call site is a `<span>` inside the button). Result: one flowing line with
     bold/italic/code only, words separated.
2. Apply:
   - `components/ReadPanel.tsx:161` → `{node.purpose && <div className="read-panel-purpose md-host"><Markdown text={node.purpose}/></div>}`.
     Do NOT restyle `.read-panel-purpose` itself (EdgePanel's app-written strings
     share it — searcher-verified trap); markdown-specific CSS hangs off `.md`.
   - `components/IoPanel.tsx:102` → same treatment for `port.description` — and the
     wrapper must become a `<div>` (it's a `<p>` today; a `<p>` wrapping Markdown's
     `<p>` children triggers validateDOMNesting warnings). Keep the `default:` line
     at :103-107 plain.
   - `views/CatalogView.tsx:47` → `<span className="catalog-item-desc"><Markdown text={item.description} inline/></span>`.
3. CSS (index.css): one `.md` block in the read-panel section —
   **`white-space: normal` FIRST (review-critical: `.read-panel-purpose` at
   index.css:1188 and `.io-port-desc` at :1400 both set `pre-wrap`, which INHERITS
   into every rendered `<p>`/`<li>` — without the explicit reset, every soft
   newline in authored prose becomes a hard break and block spacing doubles)**;
   then `p` margins (6px 0), `ul/ol` padding-left 18px + tight margins, `li` 2px
   gaps, inline `code` chip (mono 11px, `var(--bg)` bg, 1px `var(--border)`, 3px
   radius, 1px 4px padding), headings capped small (h1-h6 → 13px/600, no giant
   headers in a side panel), `blockquote` left border `var(--border-strong)` +
   `var(--text-muted)`. Match the existing var vocabulary exactly (prose =
   `--text-muted`, metadata = `--text-faint`).
4. Tests `components/Markdown.test.tsx` (jsdom): bold/code-span/bullet-list render
   as elements (no literal `**`); fenced block routes to CodeBlock; `<script>` and
   raw HTML render as TEXT not elements (the security pin); inline mode: list+
   paragraphs flatten to one line, no `<a>`/`<p>` elements; image renders alt text
   only. Plus one assertion each in IoPanel.test.tsx (description with `**bold**`
   shows a `<strong>`) and a ReadPanel purpose pin (add to an existing jsdom suite
   or GraphView.test.tsx).

### Phase 5 — docs, code review, final gates

- `web/CLAUDE.md`: new bullet "Authored text rendering" — the three treatments
  (render/highlight/strip), the `utils/highlight.ts` single seam + lazy pattern, the
  `paramLanguage` fail-closed table, the markRefs fallback rule, the
  `.read-panel-purpose` shared-class trap, and that the seam is what the future
  source-pane/diff feature consumes.
- `.taskmaster/tasks/task_168/visualization-requirements.md`: add an Implemented
  bullet (markdown + code rendering; prompts = colored markdown SOURCE not rendered;
  strip on canvas/tooltips; catalog inline-only).
- `.taskmaster/tasks/task_168/implementation/progress-log.md`: dated entry per repo
  practice (decisions: shiki-over-lowlight because of the future source pane;
  value-type-first language policy; the first-paint + count-based fallback rules).
- **Code review (repo practice):** after the gates pass, invoke the `/code-review`
  skill on the changes and work the confirmed findings before declaring done.

## Verification

> **KNOWN-RED BASELINE (verified 2026-06-12; user decision: fix in Phase 1):**
> `GraphView.test.tsx > GraphView mount > mounts the full pipeline...` fails on the
> base commit — pre-existing, caused by the NameLabel rework in WorkflowNode.tsx
> (`MOCK:` comments; the design is STAYING): the node's name (`ref.node_id`) renders
> as chrome above the card (`.node-name-label`, NameLabel component), and the
> `.node-name` title line no longer falls back to `node_id` — a no-purpose node
> shows an empty title line. The test still expects the old fallback
> (`getByText("done")` at GraphView.test.tsx:137). See Phase 1 step 0.

1. `cd web && npx vitest run` — no NEW failures vs the baseline above (289 existing
   pass today; especially EdgePanel `.ref-mark` pins and lossless.test.ts must stay
   green).
2. `cd web && npm run build` — tsc strict clean; confirm in the build output that
   shiki lands in its OWN chunk (like the elk chunk) and the main chunk grows only
   by react-markdown (~40 kB gz). No Python changed → `make test` not required, but
   harmless.
3. Real browser (`.claude/skills/screenshot-pflow-web-ui`; server restart not needed
   — zero Python changes, but the bundle must be rebuilt: `make ui-build`):
   - Write a scratch workflow `/tmp/md-render-test.pflow.md` with: a description
     containing bullets + `**bold**` + backticks + a fenced ```python block; a code
     node; a shell node; an llm node whose prompt contains markdown headers + a
     `${ref}`; an `inputs:` dict param.
   - Screenshot: ReadPanel of the llm node (prompt = colored markdown source,
     `${ref}` chips/marks intact), ReadPanel of the code node (python colors),
     the `inputs` param (JSON colors), IoPanel (rendered description, no raw `*`),
     canvas card description line (no `**`), catalog row (inline bold, single line),
     EdgePanel for a data edge into the prompt (ref-mark highlighted INSIDE
     highlighted code).
   - Cross-check one real example: `examples/agent-orchestration/plan-to-code/`
     (file-referenced prompts ship as content → markdown-colored).
4. Mutation spot-checks (the project's bar): break `paramLanguage`'s object rule →
   format test red; remove the markRefs fallback → CodeBlock test red.

## Explicit non-goals (do not build)

- No `.pflow.md` source pane, no diffs, no `/api/source` endpoint (future increment —
  the highlight seam is its consumer-to-be, that's all).
- No highlighting of one-line condition/loop expressions (pills, facts tables).
- No ref-chip handling inside rendered prose markdown (corpus has none).
- No Python/contract changes of any kind; no new bundle-size infrastructure.
- No `@shikijs/langs-precompiled` (needs ES2024 RegExp `v`; known issues).
