# Task 167: LSP Support for `.pflow.md` (Editor Diagnostics + Optional Language Server)

## Description

Surface pflow's existing workflow-validation diagnostics inside code editors via the Language
Server Protocol, so a human authoring a `.pflow.md` gets inline error feedback (and optionally
quick-fixes) as they type. pflow's `Diagnostic` model is already ~7/8 of the LSP shape, so the
editor ecosystem is unusually cheap to reach.

**The implementer chooses the scope** (see Solution): the minimal "LSP/SARIF-parity diagnostic
output" tier, or the full "build the actual language server + VS Code extension" tier.

## Status

not started

## Priority

low

> Value is **contingent**: pflow is agent-first. Agents author `.pflow.md` via the CLI/MCP server and
> already consume `pflow validate` output directly — they don't need editor squiggles. This is a
> "cool, nice-for-the-developers-using-it-now" feature, not a core need. Do not invest in the full
> server (Tier B) unless human authoring of `.pflow.md` in an editor is a confirmed real use case.

## Problem

pflow already understands its own DSL deeply — the validator parses `.pflow.md` and emits rich
structured diagnostics (severity, line, "did you mean", fix suggestions). But today those only
appear when you run `pflow validate` on the CLI. A human editing a `.pflow.md` in VS Code / Neovim
gets **no inline feedback** — no squiggles on errors, no on-type validation, no one-click fixes.

Because pflow's `Diagnostic` model already carries 7 of LSP's 8 useful `Diagnostic` fields (only
`range` is missing), the cost of reaching the entire editor ecosystem is unusually low — which is
why it's worth capturing even though the payoff is contingent on human authoring.

## Solution

Two tiers. **The implementer picks one** based on how much human editor-authoring actually matters.

### Tier A — LSP/SARIF-parity diagnostic output (no server)
Pure data-shaping over the existing validator; no protocol, transport, or lifecycle.
- Add a location `range` to the diagnostic output (whole-line range is spec-legal and enough for
  squiggles — pflow has no column data, and that's fine for Tier A).
- Map `Severity` → LSP's numeric enum, surface `Diagnostic.id` → `code`/ruleId.
- Emit a machine-readable format: `pflow validate --sarif` (SARIF 2.1.0) and/or `--lsp-json`.
- This alone lights up **Neovim (none-ls)** and **VS Code (SARIF Viewer extension / problem
  matcher)** with zero server work. Cheap, reversible, additive.

### Tier B — Full language server (builds on A)
- `pflow lsp` subcommand → a `pygls` server on stdio over the **existing validator**.
- LSP lifecycle: initialize, document sync (`didOpen`/`didChange`/`didClose`), `publishDiagnostics`.
  Validates the **live unsaved buffer**, so feedback is on-type (the real win over CLI `validate`).
- A thin **VS Code extension** (separate Node package) that launches `pflow lsp` and registers the
  `.pflow.md` language; published to the Marketplace. Other editors need only a config snippet.
- **Optional** quick-fixes (`codeAction`/QuickFix + `WorkspaceEdit`) — the expensive part; requires
  new character-column tracking in the parser (see Implementation Notes). Treat as a separate
  sub-investment, not part of basic Tier B.

## Design Decisions

- **Implementer's choice of tier, left open deliberately.** Tier A is cheap and unlocks some
  editors; Tier B is "cool" but probably low-ROI for an agent-first tool. The user explicitly left
  the A-vs-B call to whoever implements.
- **Reuse the existing validator/Diagnostic in both tiers.** `pygls` (Tier B) is just a transport
  shell — no re-implementation of validation logic. The brains stay in pflow's Python.
- **Borrow LSP's data model, not a bespoke one.** pflow's `Diagnostic` already aligns 7/8; the only
  gap is `range`.
- **Optional dependency + lazy import (Tier B).** `pygls` behind a `pflow[lsp]` extra, imported only
  inside `pflow lsp`, so the base install and CLI cold-start are untouched (mirrors the litellm
  lazy-import discipline). pflow has no extras today — this introduces that standard pattern.
- **Separate from Task 133.** That task is the execution/observability (trace) side; this is the
  authoring side. No shared code — do not couple them. They only ever appeared together because both
  were "reuse a standard?" opportunities from the same investigation.

## Dependencies

None hard.
- Tier B optional runtime dep: `pygls` (see Implementation Notes for the verified footprint).
- Relates to — but does not depend on — the diagnostic/validator subsystem (`core/diagnostic.py`,
  `core/workflow/validator.py`).

## Requirements

### Tier A — Diagnostic LSP/SARIF parity (no server)
- Diagnostic output must carry a location `range` with line **and** character positions. Whole-line
  ranges (`{line:N, character:0}` → end-of-line) are LSP-legal and sufficient. Capturing real
  columns is **not** required for Tier A.
- `Severity` must map to the LSP numeric enum (ERROR=1, WARNING=2, INFO=3). pflow has no Hint — fine.
- `Diagnostic.id` (e.g. `cache.order-mismatch`) → LSP `code` / SARIF `ruleId`.
- A machine-readable emitter: `pflow validate --sarif` (SARIF 2.1.0) and/or `--lsp-json`, serialized
  from the existing `Diagnostic` (`to_dict()` already exists).
- Output validated end-to-end in at least one consumer (VS Code SARIF Viewer, Neovim none-ls, or a
  VS Code problem matcher).

### Tier B — Language server (builds on A)
- `pflow lsp` starts a `pygls` server on stdio.
- Implements initialize/initialized, document sync, `publishDiagnostics`; validates the in-memory
  buffer (unsaved edits), not the on-disk file.
- Translates pflow `Diagnostic` → `lsprotocol` `Diagnostic` (reuse the Tier A mapping).
- `pygls` behind optional extra `pflow[lsp]`; lazy-imported; `pflow lsp` errors helpfully if the
  extra is absent.
- A VS Code extension (separate Node package) launches `pflow lsp` and registers `.pflow.md`;
  publishable to the Marketplace.
- (Optional) Quick-fixes: `codeAction`/QuickFix + `WorkspaceEdit`. **Requires** real character-column
  tracking added to the parser + template tokenizer — pflow has **zero** column data today. The
  "did you mean" corrected values exist (template-error refs) but lack the span to apply them, so
  this is a separate, larger sub-investment.

### Constraints
- **No new required runtime deps.** Tier B's `pygls` is an optional extra only.
- **Base CLI cold-start must be unaffected** — `pygls` lazy-imported inside `pflow lsp` only.

## Implementation Notes

### Verified diagnostic facts (don't re-derive — confirmed against code this session)
- **Fields** (`core/diagnostic.py:41-54`): `severity`, `message`, `title`, `suggestions`, `node_id`,
  `source`, `context`, `see_also`, `id`. Seven map to LSP; only `range` is missing. `to_dict`/
  `from_dict` (`:106-140`), `to_display_dict` (`:142-150`).
- **Severity** (`core/diagnostic.py:11-16`): exactly 3 values — ERROR / WARNING / INFO. No Hint.
- **Location is LINE-ONLY — zero columns anywhere.** It is not a field on `Diagnostic`; it's
  assembled at render time by `_format_location` (`core/diagnostic_render.py:199-222`) from
  `context["path"|"source_file"]` + `context["line"|"source_line"]` (1-based). No range/column/offset
  exists in the model or renderer.
- **Suggestions** are prose strings (not edits), **except** template errors, which carry structured
  refs in `context["unresolved_references"]` with `did_you_mean` / `corrected_var` (a full corrected
  variable string) — but **no character span** (`runtime/engine/template_errors.py:126-224, 302-322`).

### Quick-fix column work (only if pursuing Tier B quick-fixes)
- Would touch `core/markdown_parser.py` and the template tokenizer (`runtime/template_resolver.py`
  `TEMPLATE_PATTERN`/`TEMPLATE_EXTRACT_PATTERN`) to record where each `${...}`/token starts and ends.
  **Scope unverified.**
- **UTF-16 caveat:** LSP `character` positions are UTF-16 code units by default. Whole-line ranges at
  char 0 are immune, but real end-columns need UTF-16 counting or negotiating
  `PositionEncodingKind: utf-8`.

### Dependencies (verified against `uv.lock`)
- Net-new: **`pygls`** + transitive **`lsprotocol`**, **`cattrs`** — all pure-Python, no native
  builds. `attrs` is **already present** (transitive, likely via `jsonschema`), so not net-new.
- Add as `[project.optional-dependencies] lsp = ["pygls>=1.3"]` (pflow has no extras today).

### Framework & build/install story
- **`pygls`** is the canonical Python LSP framework (handles JSON-RPC, stdio, lifecycle — you write
  handlers). A publish-diagnostics server is ~70-80 lines per its examples; a realistic pflow server
  is a few hundred lines wrapping the existing validator.
- The server **ships with pflow** as `pflow lsp` — no separate server install.
- **VS Code** has no generic LSP config → needs a small extension (a few dozen lines using
  `vscode-languageclient`) published to the Marketplace; one-click install. Its Node deps
  (`vscode-languageclient`, `typescript`, `esbuild`, `@vscode/vsce`) live in the extension's own
  `package.json`, **never** in pflow's `pyproject.toml`.
- **Neovim / Helix / Emacs** have built-in LSP clients → a few config lines (`filetype pflow` →
  `pflow lsp`). Contribute an `nvim-lspconfig` entry to make it a one-liner.

### The functional win over CLI `validate`
The server validates the **live unsaved buffer** (`didChange`), so feedback is on-type;
`pflow validate` reads the saved file from disk. Same validator underneath — different input source.

## Verification

- **Tier A:** `pflow validate --sarif` on a known-bad `.pflow.md` produces valid SARIF that the VS
  Code SARIF Viewer (or Neovim none-ls) renders with correct file/line/severity/message. Round-trip a
  few error fixtures from `examples/invalid/`.
- **Tier B:** open a `.pflow.md` in VS Code (with the extension) and/or Neovim; introduce an error in
  the **unsaved** buffer; confirm a squiggle appears on-type (before save) with the right message;
  fix it; confirm it clears.
- **Isolation:** base `pflow` installed *without* `[lsp]` is unchanged; `pflow lsp` errors helpfully
  pointing at `pip install pflow[lsp]`.
- **Cold-start:** time a normal `pflow validate` with and without `[lsp]` installed — no regression
  (`pygls` must not be imported on the base path).

## References

- `src/pflow/core/diagnostic.py` — `Diagnostic` dataclass, `Severity`, `to_dict`/`from_dict`
- `src/pflow/core/diagnostic_render.py` — `_format_location` (`:199-222`), the only (line-only)
  location assembler
- `src/pflow/runtime/engine/template_errors.py` — `unresolved_references` structure,
  `did_you_mean`/`corrected_var` (`:126-224, 302-322`)
- `src/pflow/core/markdown_parser.py` + `src/pflow/runtime/template_resolver.py` — where column
  tracking would be added for quick-fixes (Tier B optional)
- `pyproject.toml` — add `[project.optional-dependencies] lsp` (no extras exist today)
- External: LSP 3.17 spec; `pygls` (+ `lsprotocol`); SARIF 2.1.0; `none-ls.nvim`; VS Code SARIF
  Viewer; `nvim-lspconfig`
- Origin: emerged from the OpenTelemetry/standards investigation as the **authoring-side**
  counterpart; deliberately separate from **Task 133** (trace/execution side).
