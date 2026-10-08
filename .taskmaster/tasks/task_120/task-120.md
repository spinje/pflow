# Task 120: Declared Input Types Are Honoured — Strict at the Boundary, Never Re-Inferred

## Description

A workflow's `## Inputs` declare a type for each input, but today that type is consulted once,
leniently, and then forgotten: a value that cannot be coerced only logs a warning and passes
through; the CLI guesses a type for every token before the declarations are known; and every
later hop re-guesses the type from the value. Make the declared type hold at every boundary a
value crosses: parse strictly where the value enters, fail with an actionable error, and never
re-infer it downstream.

## Status
not started

## Priority

medium

## Roadmap

next

> **Rewritten 2026-10-06 against main `b2cd92e3`** from an Opus investigation that executed every
> break below (probe workflows, no paid calls). Owns #686 and #687 by user ruling the same day.
> **NOT launch-ready: the user decisions below must be ruled before a planner starts.**

## Problem

The rule (user ruling 2026-10-06): *a declared input type is honoured at every boundary the value
crosses.* Executed on `b2cd92e3` — `--validate-only` printed "✓ Workflow is valid" for 1–3 and 9:

1. `type: array` given `topics=tea` → run: `WARNING: Cannot parse string as JSON array`, then
   `batch items must be an array, got str`. `type: boolean` given `maybe` → warning, then the code
   node fails `expects bool but received str`. A `type: number` given `abc` with no annotated
   consumer: warning, **exit 0**, the string flows on.
2. **#686** — `type: string` given `{"a":1}` or `[1,2]` reaches a code node as dict / list. Same
   through byte-exact stdin and through MCP `workflow_execute`.
3. **#687** — `type: string` given `02134` arrives as `2134` (CLI and web UI only; MCP is intact);
   `true` → `"True"`; JSON text is re-spaced.
4. `type: integer` silently accepts `3.0`, `3.5`, `1e3`, `true`.
5. `type: boolean` given `0` / `1` arrives as int, no warning.
6. `type: number` given `007` → 7, `1e3` → 1000.0.
7. `type: object` given `[1,2]` → a list, no warning (non-string values are never checked);
   `type: array` given `{"a":1}` likewise.
8. `type: any` given `02134` → int, `{"a":1}` → dict.
9. `${v.a}` on a `type: string` input validates and resolves.
10. A sub-workflow's declared inputs are never coerced when the parent supplies them: a child
    `s: string` given `{"a":1}` receives a dict; `n: integer` given `"7"` receives the string.
11. `--only` reseeds `0099` as `99`.
12. (Observed by Task 118 Part 1, 2026-10-07.) A numeric YAML literal written into a param is re-typed
    before anything sees it — `env: {VERSION: 1.10}` binds `1.1`, `{MODE: 0755}` binds `493`. Same family
    for literals as #687 is for CLI values; the guide tells authors to quote, a warning is this task's call.

## Current state (verified — re-check line numbers at start)

- **The only runtime site that reads the declared type** is `prepare_inputs`
  (`runtime/compilation/ir_preparation.py:280`) → `coerce_workflow_input`
  (`core/param_coercion.py:229`), whose every failure branch logs and `return value`
  (`:116-209`). Non-string values are passed through unchecked. `--validate-only` never calls it
  (`execution/runner.py:443-445`, #297).
- **Before it**, the CLI runs `infer_type` (`cli/param_parsing.py:9-46`: bool / int / float /
  JSON) on every `key=value` token without knowing the declarations — the cause of #687. Callers:
  `cli/commands/run.py:1053`, `resume.py:56`, `_probe_impl.py:52`, `analyze_cache.py:145`,
  `ui/server.py:1018`. Declared defaults are pre-filled raw and never validated against `type`
  (`runner.py:671-687`).
- **After it**, template resolution re-infers: `inputs:` of code / workflow nodes per key with
  `auto_parse=True` (`runtime/engine/template_resolution.py:261` — #686), every dict/list param
  (`:267`), plus JSON parsing during path traversal (`core/templates.py:413-425`). The resolver
  cannot tell a declared input from an upstream step's output: `TemplateConfig`
  (`runtime/engine/types.py:13-21`) carries no input names. The static validator can
  (`runtime/template_validation/type_checker.py:41-44`) but allows string → object.
- **Sub-workflows**: supplied child inputs bypass coercion — `workflow_executor.py:430-433` seeds
  declared defaults only for absent keys, then writes the raw values; `_validate_child_params`
  (`:800-861`) checks shape only.
- **The primitive exists, unused**: `TypeSpec.accepts` (`core/types.py:115`) — strict, canonical
  names only, zero callers in `src/`.
- **Why auto-parse exists**: every motivating case is UPSTREAM output (`${node.stdout.field}`,
  inline objects); `architecture/core-concepts/data-type-coercion.md:95-107` calls it the
  "weakest design point". The guide's promise ("Upstream JSON is auto-parsed before your code
  runs", `guide/nodes/code.md:64`) is upstream-scoped. **No in-tree workflow relies on a DECLARED
  input arriving parsed** (89 `.pflow.md` files checked); upstream auto-parse is relied on heavily
  and stays.

## Design intent (confirm at start — the planner's to settle within the decisions below)

The investigation's recommended shape: **strict at the boundary, typed thereafter.**
- One strict coercer, `declared value → typed value | error`: a string goes through the
  string → type parse, a non-string is checked with `TypeSpec.accepts`. It replaces the
  log-and-return branches.
- Declared inputs keep the raw argv string — CLI type inference runs only for undeclared params.
- The coercer is called everywhere a declared input enters: `prepare_inputs`, sub-workflow child
  seeding, and validate-only with supplied params (#297 parity).
- The resolver never re-infers a value whose root is a declared input: the compiler passes the
  declared input names to the resolver.
- The validator rejects string → container and a path on a non-object input.

The shape it does not cover: a value from an upstream step (`${shell.stdout}`) reaching a code
param annotated `str` — the other half of #686; see decision (e). The resolver site is shared
with
Task 118 (the `env:` leaves): 118 expresses its no-parse rule as a per-leaf predicate this task
extends, never a second branch.

## Decisions for the user (resolve BEFORE the planner starts)

Each changes what an existing invocation receives or rejects. Recommendations are the main
orchestrator's.

- **(a) Fail instead of warn** when a value cannot be coerced to its declared type. Rec: fail —
  exit 0 with a wrong-typed value is the bug.
- **(b) Accepted spellings.** integer: `3.0`? `1e3`? number: `007`? boolean: `0`/`1`, `yes`/`no`,
  case-insensitive? Rec: integer accepts only integer text; number accepts any JSON/float text;
  boolean accepts `true/false/yes/no/1/0` case-insensitively — spelled out in the error.
- **(c) A declared `string` used as a container** (into `x: dict`, `${v.a}`, batch `items`):
  validation error, or parse at the consumer? Rec: error — the author declared a string.
- **(d) `type: any` from the CLI**: raw text or inferred? Rec: inferred (today's behaviour; `any`
  means "don't check").
- **(e) Scope: also the upstream half of #686** (`${shell.stdout}` → a code `inputs:` key annotated
  `str` still arrives parsed). Rec: yes, via the consumer's annotation — it is the same symptom an
  author meets, and the code node already knows the annotation.
- **(f) Fold in two adjacent bugs** the investigation executed: sub-workflow child coercion (wider
  than #188) — rec: yes, it is the rule; an env-var input losing to its own `default:`
  (`ir_preparation.py:300-305` vs the pre-fill at `runner.py:671-687`) — rec: no, file separately.
- **(g) Boolean text rendering.** A boolean becomes `True` inside a command / `env:` (Task 118's
  `to_string` ruling) but `true` on shell stdin. Rec: leave both as they are here (118 ruled the
  first); note the inconsistency for a future one-line ruling.

## Constraints

- **Engine contact** (`runtime/engine/template_resolution.py`, `workflow_executor.py`): plan-mode
  deep-review is mandatory; builds after Task 118, which edits the same lines.
- **The error message is show-before-code.** One error format for input-type failures, shared
  with Task 112 (literal node params) when that lands — no shared format exists today. Input-type
  failures must not print "To resume from the failed step" (`resume --force` replays the bad input).
- Tests that pin today's leniency flip deliberately and are named in the plan
  (`tests/test_core/test_param_coercion.py` `*returns_original`;
  `tests/test_runtime/test_prepare_inputs_coercion.py:18,153,163`).
- Stale surfaces: `guide/core.md:439-456` (claims scalars auto-parse; only containers do),
  `docs/reference/cli/index.mdx:152-158`, `src/pflow/core/CLAUDE.md:198-200`,
  `runtime/compilation/CLAUDE.md`, `architecture/core-concepts/data-type-coercion.md` (cites
  deleted files).

## Dependencies

Builds after Task 118 (same resolver lines; inherits its `to_string` rule for `env:`). Read
first: Task 118's plan and task-review, Task 170's task-review, issues #686 #687 #297 #188 in
full (body + comments), Task 112's top block.

## Verification (intent)

Every numbered break above becomes either an actionable error at validation or input time, or a
correctly typed value, per the decisions; `--validate-only` with supplied inputs and the run
agree; upstream-output auto-parse (`${x.stdout}` as batch items, `${x.stdout.field}`) is unchanged.

## References

- Investigation (main orchestrator's session-11 log); issues #686, #687, #297, #188.
