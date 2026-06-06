# Research: Task 155 — two deep verifications (Scope↔identity, source back-ref)

Reference-grade `file:line` findings from two parallel verification passes (2026-06-06). These close
the last two open design inputs before the implementation plan. **Non-overlap:** the four earlier
verification passes (routing-map separability, ID alignment, IR inventory, container/rename) are in
`starting-context/braindump-verification-and-build-handoff.md` §1 — not repeated here. ADR-0003 records
the *node-identity decision*; this file is the *migration map* under it. ADR-0004, the spec, and the
braindumps cover the rest.

Trust boundary: **verified by searcher, line numbers as reported** — the mermaid package is changing;
re-anchor a line if it looks off. (Proven-stale example: mermaid `CLAUDE.md` write-site lines.)

---

## 1. Scope ↔ structural identity (the ADR-0003 migration map)

**The tension:** ADR-0003 requires the model to key nodes by structural identity
`(node_id, ancestor_path, batch_index?)`. The spec says "reuse `Scope`." But `Scope.resolve` returns a
**flat, prefix-accumulated mermaid-ID string** — squarely on the wrong side of ADR-0003. This section is
how to reconcile them.

### What `Scope.resolve(root, field)` returns (`_scope.py:54-90`)

Three branches, each a flat string (or `None`):
- **Batch item** (`:67-73`): `_to_mermaid_id(ctx.prefix + batch_source)`; returns `None` if the source is
  in `has_expanded_outputs` (intentional edge suppression). Ancestry encoded via `ctx.prefix`.
- **Sibling node, optional output-field routing** (`:76-84`): `_to_mermaid_id(ctx.prefix + root)`, OR — when
  the sibling is an expanded sub-workflow/batch with outputs — a flat **output-node ID read verbatim out of
  `ctx.outgoing_routes`** (e.g. `parent__child__out_result`). **This branch is the hard part:** the returned
  string is a renderer-synthesized IO-node ID. `field` is consumed *inside* Scope to pick the output; the
  caller never sees it as structural data.
- **Declared input** (`:87-88`): `input_ids[root]` → `input_{name}` (depth 0) or `{ctx.prefix}in_{name}`
  (sub-workflow), per `for_level` (`:99-103`).

So the return value is scope-aware AND ancestry-encoded — the final renderable endpoint, not a scope-local
handle.

### The resolution surface — Scope is only ~1/4 of it (the blast-radius surprise)

`Scope.resolve` has **exactly one caller**. The other ref-resolution paths use the static parse-only
helpers `Scope.refs_in` / `Scope.source_refs_in` and then **hand-roll the flat ID inline** — they bypass
`Scope.resolve` entirely:

| Path | Site | Uses `Scope.resolve`? | What it does |
|---|---|---|---|
| data-flow → sub-wf input | `_generate_data_flow_edges` `_edges.py:209-227` (`.resolve` at `:224`) | **YES (only caller)** | emits `{source_mid} --> {target_mid}` straight to `ctx.lines` |
| batch-item data-flow | `_generate_batch_item_data_flow` `_edges.py:263-276` | no — `refs_in` + inline `_to_mermaid_id(ctx.prefix+root)` | direct emit |
| output-source wiring | `_connect_sources_to_output` `_io.py:214-239` | no — `source_refs_in` + inline 3-case (hand-rolled copy of `resolve`, w/ `*outgoing_maps`+`input_ids`) | direct emit |
| top-level input→consumer | `_connect_input_from_params` `_io.py:99-109`, `_connect_input_from_batch` `_io.py:124-131` | no — `refs_in` + inline `input_{root}` | direct emit |

(Also `_extract_batch_source` `_edges.py:93-96` uses `refs_in` to return a **bare `root`** — convention-free,
structural. `_dynamic_batch_label` `_context.py:263` uses `refs_in` for a display string only.)

Edge-endpoint routing for **structural IR edges** (`_resolve_edge_endpoints` `_edges.py:104-140`,
`_render_edge` `:148-175`) never touches Scope — it flattens `edge["from"]/["to"]` via
`_to_mermaid_id(ctx.prefix + ...)` and routes through `outgoing_routes`/`incoming_map`/`fork_join_map`.

**Every consumer emits the resolved ID directly into a mermaid edge line** — none stores it or looks it up.
The flat IDs are terminal.

> **Stale-doc warning:** mermaid `CLAUDE.md` claims *"all ref-consuming sites use `Scope.resolve`."* **False**
> — only `_generate_data_flow_edges` does. Don't size the migration off that claim.

### Coupling analysis — Scope's *logic* is already structural

- **No mermaid syntax** in `_scope.py` — never touches `ctx.lines`, emits no `-->`/brackets/`classDef`. Pure
  resolution returning `Optional[str]` + `(root, field)` tuples.
- **Decision inputs are structural / IR-derived**: `sibling_node_ids` (`_render.py:109`), `parent_inputs`
  (`:108`), `batch_source` (from `node["batch"]["items"]`), and `ctx.prefix` — which **literally *is* the
  ancestor_path, just serialized as a `parent__` string** instead of a list.
- **Flattening inputs are render-time**: `_to_mermaid_id` + the `prefix`/`in_`/`out_`/`input_` naming
  convention, and the output-node IDs read from `ctx.outgoing_routes`.

So the conversion question isn't "can Scope be structural?" — its logic is — it's "where does the flat-ID
*synthesis* move to?"

### Recommendation: Option A (Scope returns structural identity)

Change `Scope.resolve` to return a structural handle — `(node_id, ancestor_path, output_field?)` or `None`
— and let renderers derive the flat ID *forward* via a thin `flatten(handle)` shim.
- **Cleanest mechanism:** replace `ctx.prefix` (the `parent__` string) with a **structured ancestor list**
  on `MermaidContext`; ancestry then falls out for free, and the flat ID is derived forward (lossless).
- **The hard branch** (`_scope.py:78-83`): instead of returning an output-node ID from `outgoing_routes`,
  return `(node_id, ancestor_path, field)` and let the renderer map `(node, field) → out-node-id`.
- **The real scope:** to make the model *fully* structural you must **also migrate the three hand-rolled
  resolvers** (`_io.py:214`, `_edges.py:263`, `_io.py:99`/`:124`) onto the structural Scope — otherwise
  structural identity lives on only the one data-flow path and the rest stay flat (a half-migrated model).
  They were never folded into `resolve` (likely because `_connect_sources_to_output`'s `*outgoing_maps` +
  input-vs-sibling precedence doesn't fit `resolve`'s current shape) — folding them in is the larger but
  correct change, and it consolidates genuine duplication.

**Option B (parse flat→structural at the edge boundary) is rejected** — fragile: `__` is ambiguous (ancestry
separator AND inside `__in_`/`__out_`), and `_to_mermaid_id` is identity so node IDs can contain `_`/hyphens.
You cannot reliably reverse `parent__child__out_result` → `(node_id, ancestor_path, field)`. ADR-0003 exists
precisely to avoid parsing flat IDs; Option B reintroduces the parse at a new layer.

**Consequence:** golden files (`tests/test_core/golden_mermaid/`) assert exact flat-ID edge lines; under
Option A they regenerate (expected — parity is a tripwire, not a contract). Unit tests asserting
`Scope.resolve` returns specific flat strings also change.

---

## 2. Source back-ref population (the click-to-read field design)

**The question:** the spec requires a per-node "source back-ref" so a UI can open a node's prompt/command/
code at its origin. (IR inventory is in braindump §1.C — *not* repeated.) This is the **population matrix**:
when is each of `_source_files` / `_source_lines` / `_source_line` actually present?

### Write sites + conditions

- **`_source_files[param]`** — `file_resolver.py:149` (node params; `:177` batch string, `:197` batch-item
  params). Set **ONLY** when the param's bullet value was an external file reference (`is_file_reference`,
  `:49-92`: `./x.md`, `../x.py`, `dir/x.md` with a known extension — rejects multi-line, spaces, `${...}`)
  AND the param is in `FILE_RESOLVABLE_PARAMS` (`:38-46`: `command`, `code`, `prompt`, `source`, `stdin`,
  `headers`, `output_schema`). **Value = the original path string** (provenance); `params[param]` becomes the
  file *content*. Pipeline order (`compiler.py:849-866`): parse → THEN resolve file refs, so a file-ref is a
  bullet at parse time and **never** a code block.
- **`_source_lines[param]`** — `markdown_parser.py:1198-1199`, in `_route_code_blocks_to_node`. Set **ONLY**
  for **non-YAML fenced code-block** params (`is_yaml_config` is true only for ` ```yaml…` tags, `:770-778`).
  **Value = content line** (fence line + 1, 1-based). Inline `- key: value` bullet params get **no** entry
  (they flow to `node["params"]` at `:1618-1619` with no line metadata).
- **`_source_line`** (node) — `markdown_parser.py:1627`, **unconditional**, = the `###` heading line.

### The matrix (per content param: `prompt`/`command`/`code`/`source`)

| Content origin | `_source_files[param]` | `_source_lines[param]` | `_source_line` |
|---|---|---|---|
| (a) inline fenced code block (```prompt) | **absent** | **present** (content line) | present (heading) |
| (b) `./file.md` ref bullet | **present** (path string) | **absent** | present (heading) |
| (c) inline `- key: value` bullet | absent | absent | present (heading) |

The two per-param fields are **mutually exclusive** — content is either inline (→ `_source_lines`) or from a
file (→ `_source_files`), never both. **Uniform across node types** (keyed off param name + block tag, not
node type): `llm.prompt`, `shell.command`, `python.code`, `claude-code.prompt` behave identically.

**Asymmetry to know:** `system`/`system_prompt`/`content`/`body`/`url` are code-block params (get
`_source_lines` when inline) but are NOT in `FILE_RESOLVABLE_PARAMS` → can never get `_source_files`. Only
`prompt`/`command`/`code`/`source`/`stdin` have both paths reachable.

### Field-design conclusion

A single `(file)` or single `(line)` field is insufficient. The back-ref must carry **a file path AND an
optional line**, resolved per-param:
- **file** = `_source_files.get(param)` if present (external file), else the workflow's own `.pflow.md` path.
- **line** = `_source_lines.get(param)` if present (inline code-block), else `None`/`1` for a file-ref,
  falling back to `_source_line` (heading) for inline bullet params.

i.e. *if `_source_files[param]` → open that file (line 1); else open the `.pflow.md` at `_source_lines[param]`
if present, else at the node heading `_source_line`.* Two primary cases — "external file, no line" and
"workflow file, specific line" — plus the heading fallback.

**Caveats:** batch file-refs use **compound provenance keys** in `_source_files` (`batch.items[i].prompt`,
`file_resolver.py:191-197`) — a back-ref handling batch-item content must parse these. And the two dicts hold
different value types (`_source_files` = path strings; `_source_lines` = 1-based ints). Existing consumer for
semantics reference: `template_validation/path_validation.py:414-443`.

---

## For the implementing agent

These two findings change the plan in concrete ways:
1. **The Scope migration is bigger than "adapt one function"** — it's ~4 resolution paths, of which only one
   uses `Scope.resolve`. Budget for migrating the three hand-rolled resolvers, or accept (and document) a
   half-structural model. The lowest-risk mechanism is `ctx.prefix` → structured ancestor list + derive-flat-
   forward.
2. **The click-to-read back-ref field carries `(file, line?)`** with the documented fallback, handles the
   inline-vs-file-ref split, and must cope with batch compound keys. It is *not* "store the prompt's file."
