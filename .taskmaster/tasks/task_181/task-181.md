# Task 181: Code Handed to MCP Tools — Bare `${…}` Is the Embedded Language, Values Enter as `${x|json}`

## Description

Some MCP tool params carry a program in another language (JavaScript for `evaluate_script` and the
like). pflow cannot bind variables into a string another process executes, so those params stay
templated — but under a rule that mirrors Task 118's: the text is the embedded language, a bare
`${…}` in it is never a pflow Template, and a pflow value enters only through an explicit
`${x|json}` Reference that yields a quote-safe JSON/JS literal.

## Status
not started

## Priority

medium

## Roadmap

next

## Problem

- **#550 (observed):** a value pasted into JavaScript breaks on apostrophes (`Don't Stop`) —
  pflow's own screenshot workflows carry a "use double quotes inside" caveat
  (`examples/real-workflows/screenshot-pflow-web-ui/`, `.claude/skills/screenshot-pflow-web-ui/SKILL.md:35`).
- **#621, JavaScript half (observed again 2026-10-06 by the #714 lane):** a JS template literal
  `` `${…}` `` in such a param is read as a pflow Template — an Issue, or an "undeclared input"
  error — and must be escaped as `$${` on every brace.
- A boolean input reaches JavaScript as Python's `True` (same lane, same day).

## Design Decisions

- **DECIDED 2026-10-06 (user: *"go ahead with all your recommendations"*) — on a code-bearing MCP
  param a bare `${…}` is always the embedded language and passes through verbatim; a pflow value
  enters only as `${x|json}`.** This replaces the 2026-10-05 ruling ("tolerate every non-pflow
  `${…}`, identifier-shaped included, and keep resolving pflow references"), which a spec review
  showed to be unsafe: whether a `${…}` was "pflow" would depend on what is in scope, so a JS
  `` `${item.id}` `` inside a batch, or `` `${user.name}` `` when an input is named `user`, is
  silently replaced by the pflow value; and at run time an unresolved reference to a step on a
  skipped branch would pass through as literal text. With the explicit marker there is no
  collision and typo detection stays on every pflow Reference (`${nod.result|json}` is an error).
  Contract: ADR-0016.
- **DECIDED 2026-10-05 — a `${x|json}` filter** (#550): substitutes a JSON/JS literal, quote-safe
  by construction (`true`, `null`, a quoted and escaped string, an object literal).
- **Everything outside a `${x|json}` Reference is emitted from the source text unchanged** — a
  consequence of the rule above, stated because the parser would otherwise break it: today
  `` `Total: $${price}` `` parses to text with the escape collapsed (`${price}` — the JS dollar
  sign is lost), and `$${foo ${x|json}}` swallows the inner Reference (both executed). So on these
  params `$${` stays `$${`, a `|json` inside a `$${…}` span is a validation error, and the rule is
  policy over ONE parse result (every Expression and Issue carries its source span,
  `src/pflow/core/templates.py:256-277`) — never a second tokenization. Note this is policy over
  Expressions too (`${user.name}` parses as one), which goes beyond Task 170's "policy over
  Issues" note; ADR-0016 records it.
- **`|json` is accepted only on code-bearing MCP params at first.** Widening to every templated
  surface later is a code change; narrowing after workflows use it everywhere would be a corpus
  sweep.
- Split out of Task 118 on 2026-10-06: different surface and machinery (parser grammar, the
  TypeScript mirror), no dependency on the shell change.

## Open questions (resolve at start)

- **How a param is identified as code-bearing.** The node type string is
  `mcp-{server_name}-{tool}` (`src/pflow/mcp/registrar.py:121`) and the server name is
  user-chosen, so the type string cannot be matched whole; the tool name is its suffix and is
  also stored as registry metadata (`mcp_metadata.tool`, `registrar.py:368-374`) — but the param
  walks never see the registry (`iter_node_surfaces` takes only the IR, `split_params` has no node
  type). An
  allowlist leaves third-party code tools strict (safe failure: the author escapes as today); a
  schema heuristic can switch typo detection off on a param that is not code (unsafe failure). An
  author-visible marker would be new workflow grammar. State the mechanism and its failure mode.
  **Adding a tool to the set later is not free:** every existing bare `${x}` in that tool's param
  silently changes from "resolved" to "passed through"; the warning below is the required safety
  net, not only a discoverability aid.
  It should be the same classification Task 118 introduces for `shell.command` / `code.code`
  (one concern: a param's template mode — templated, body, embedded code), not a second mechanism.
- **Grammar.** `|` is not in the template grammar today (`src/pflow/core/templates.py:171-173`); `${x|json}` is
  an Issue on every surface. Is this a general filter position with one filter, or a one-off?
  Once the grammar lands `${x|json}` parses as an Expression everywhere (Python and `scan.ts`
  alike), so "not accepted on other surfaces" is a new policy over Expressions that needs a
  defined run-time behaviour too (validate/run parity) — it is no longer "an Issue, as today".
  How does it compose with Coalesce (`??`), a Dynamic index, and a whole-value Template (today a
  bare `${x}` as an entire param value keeps its type and auto-parses — which would undo the
  encoding)? What does `|json` on a non-code surface report?
- **What a grammar change carries** (Task 170's task-review): the change lives in `core/templates`
  only (a meta-test enforces it); `web/src/graph/scan.ts` changes in the same step, with parity
  rows in `tests/test_integration/test_template_parity.py`; and the web UI has three more scanners that read
  `${…}` on their own (`web/src/utils/format.ts` `REF_PATTERN`, `web/src/graph/sourceDecorate.ts`, `web/src/utils/batchItems.ts` — #683).
- **What depends on References found in such a param today** and changes when only `|json`
  forms count: forward-reference and undefined-input checks (`core/workflow/data_flow.py:317,
  343`), the unused-input ERROR (`runtime/template_validation/validator.py:555-612` — an unconverted
  `'${selector}'` would produce a misleading "unused input 'selector'"), graph data edges and
  canvas chips (`core/workflow/graph/scope.py:33`), and the memo key (the param moves from
  template to static params — one cache miss). Execution order is unaffected (edges only). The
  code-param diagnostic must fire alongside or instead of the unused-input error and name `|json`.
- **Discoverability.** #550's error comes from the MCP server (a JS SyntaxError), so an agent
  never learns `|json` exists from it. A validation warning when a pflow-shaped `${…}` sits in a
  code-bearing param — "this is passed to JavaScript as written; to insert a pflow value write
  `${x|json}`" — is where an agent would find it. Draft BEFORE/AFTER as a show-before-code
  checkpoint.
- **Terms.** `context/CONTEXT.md` lists "filter" as an avoid-word under the loop Condition entry;
  settle the noun for `|json` and for a code-bearing param there.

Solution / Requirements / Verification — finalized when the task is started (just-in-time).

## Dependencies

None blocking, but it builds after Task 118: both edit `runtime/engine/template_resolution.py`
(engine contact → lane A, plan-mode deep-review mandatory, serialized) and this task reuses the
classification 118 introduces. Read first: `.taskmaster/tasks/task_170/task-review.md`, Task 118's
task-review once it exists, issues #550 and #621 in full (body + comments).

## Verification (intent)

- `` `${user.name}` `` and `${a + b}` in an `evaluate_script` function reach the tool unchanged —
  inside a batch whose alias is `item`, and in a workflow with an input named `user`.
- `${title|json}` with the value `Don't Stop` arrives as a valid JS string literal; a boolean as
  `true`; an object as an object literal.
- `${nod.result|json}` (unknown step) is a validation error; `--validate-only` and the run agree.
- The in-tree screenshot workflows drop the double-quote caveat and still run (four sites convert:
  `examples/real-workflows/screenshot-pflow-web-ui/click.pflow.md:83-85`, `hover.pflow.md:56`).
- `` `Total: $${price}` `` reaches the tool with both dollar signs.

## References

- `context/adr/0016-118-code-bodies-untemplated-env-binding.md` · issues #550, #621, #620, #683.
- The Task 118 spec-review ledger's MCP findings are summarised above; nothing else is needed from it.
