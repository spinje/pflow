# Task 118 Review: Shell and Code Bodies Are Plain Code — `env:` Binding for Shell Steps

## Metadata
- Two PRs (plan §4.0). **Part 1** — `env:` as a working channel + the two tooling workflows — PR #723, merged as
  `012f358c` (2026-10-07); its record is the PR body and the log. **Part 2** — display, corpus conversion, the flip,
  web, docs — branch `feat/task-118-part-2-bodies-untemplated` (2026-10-07 → 10-08), `origin/main` `a42f55e2`
  (v0.16.0) merged in; PR opened at close-out. Breaking change (no external users).
- Built by Opus phase implementers I1 (P0/PA), I2 (PD, PC1), I3 (PC2), I4 (PB + its mid-task review), I5 (PE), I6
  (PF), gate-runner G1 (PZ), orchestrated from the Fable planner's plan. Contract: ADR-0016. Journey, every
  deviation and ruling: `implementation/progress-log.md`. Ruled message text: `implementation/diagnostics-checkpoint.md`.

## Read First — the load-bearing block
- **What exists now:** `shell.command` and `code.code` are never scanned, validated or resolved as Templates; a
  shell step reads values only as environment variables bound in `env:` (each value `core/templates.to_string`
  text, a string byte-for-byte, never JSON-parsed), a code step through `inputs:`. A `${…}` left in a body that
  pflow would once have resolved, and any `$${`, is a validation ERROR naming the fix — at validate-only, at run
  and at compile.
- **Read these first:** `core/workflow/template_surfaces.py` (`param_mode`, `_BODIES`, `template_params`,
  `code_bodies`, `binds_as_text`); `core/workflow/data_flow.py` → the "Code bodies" section (`step_scope`/`StepScope`,
  `body_references`, `body_reference_roots`, `_validate_bodies`); `nodes/shell/env_binding.py` (`bind_env`,
  `env_problems`, `merge_env`, `displayable_env`, `EnvBindingError`); `runtime/engine/template_resolution.py`
  (`split_params(…, node_type)`, `parses_leaves`); `web/src/utils/format.ts::isCodeBody`.
- **Invariants that must NOT break:**
  1. **Every param walk reaches bodies only through `param_mode` / `template_params` / `code_bodies`.** A walk over
     `node["params"]` directly brings back phantom data-flow edges, ref chips, Pass-6 type checks and MCP env
     expansion from `${HOME}` in a body. The guard is the consumer table (`test_code_body_consumers.py`), one row per
     consumer, each mutation-verified — a new walk needs a new row.
  2. **`split_params` decides `param_mode == "body"` BEFORE `has_templates`.** `$${X}` counts as a template; testing
     it first would collapse the escape to `${X}` in a body.
  3. **`env:` leaves are never JSON-parsed** (`binds_as_text` → `parses_leaves` → `auto_parse` off). Breaking it
     re-serializes JSON text (`{"a":1}` → `{"a": 1}`). Task 120 *replaces* this predicate with its declared-type rule
     — keep any extension a predicate on `(node_type, key)`, never `key == "env"`.
  4. **Binding is node-owned, in `prep()`.** Engine, batch item, the single-node probe and direct node use all cross
     it. A binding failure is `EnvBindingError` (`retriable = False`, `batch_fatal = False`) and `exec_fallback`
     re-raises any `PflowError` — so it is never "exit code -2", never retried, never swallowed by `ignore_errors`.
  5. **A failing shell step records only `displayable_env` (redacted by name, 200-char cap) as `shared["env"]`.**
     A failed child's output rides the child-failure bundle into batch error records that CLI text, JSON and MCP emit
     unredacted — writing raw bound values there leaks secrets and payloads. Full values live in the trace
     (`node_params.env`) for `pflow report`.
  6. **The body rule lives in `validate_data_flow`, which the compiler also runs.** The UI's compile-only preflight,
     dict IR and nested children rely on it; its WARNINGs (ruling 2) stay out of `CompilationError`.
  7. **Leftover scope is per step (`step_scope`), not the validator's workflow-wide set**, and a step id counts only
     with a path (`${count.stdout}`, never bare `${count}`). Widening it flags correct sh (a `for item` loop on a
     non-batch step) with a fix that fails at run.
  8. **No `${` regex outside `core/templates`** (Task 170 meta-test 2): escape detection uses `str` methods.
  9. **The trace format did not change** (D12) — the display copy is node output the trace already records.

## What Was Built (actual vs. planned)
Phases as planned (PD → PC → PB → PE → PF → PZ in Part 2). Divergences that matter (each ruled in the log):
- **D9's "pop the copy on success" was not built** — dead code: a failed namespace moves wholesale to `__failures__`
  (`runtime/node_state.py::mark_node_failed`), so no stale copy can survive. PD test 9 guards that premise.
- **`code_bodies` yields `(param, language, text)`** and `body_references` lives in `data_flow.py` (it takes a
  `StepScope`), not `template_surfaces.py`.
- **The leftover detector reads more than D5 drafted** — each closed a silent hole found by a reviewer or the
  falsifier: sh's colon-less default `${limit-10}` is split at `-` (pflow names allow `-`, sh names do not) for
  Expressions and Issues alike; an Issue's interior is re-read (`${UNSET:-${item}}`); a code body is read as each
  literal's *source* text (bytes literals; adjacent literals `"$$" "{PRICE}"` stay apart; line numbers survive `\n`
  escapes); every in-scope root of a leftover counts as used; a `\`-preceded `$${` gets a two-readings message.
- **Plan amendments from a cross-model plan read:** a fifth file-reference site (`_resolve_batch_file_references`,
  batch items) routed through `is_param_file_reference`; the `prompt_cache_analysis` prediction-walk row DROPPED
  (LLM-only — narrowing it would lose `batch`/`inputs` coverage); batch-item report pages read the item's own
  resolution before the host's static params (`trace_report._resolved_or_static` — literal `env:` and legacy traces).
- **Built beyond the plan:** per-item read-panel expansion for dict/list params (`web/src/utils/batchItems.ts`) —
  every batch shell step's values moved into the `env:` dict, so leaving that pre-existing gap open would have removed
  the per-item preview from every batch shell step.
- **Tests deleted, not replaced:** Pass 7's suite and `test_nodes/test_shell/test_command_validation.py` (PA's
  binding tests already cover node-level binding).
- Task-159 case `12-…/04-guide-auto-detect` was regenerated (guide output only); `verify.sh` 76 / 11 / 0.

## Patterns & Anti-Patterns
- **One classification, consulted by name.** New behaviour on "how pflow reads a param's text" goes into
  `param_mode` (Task 181 adds `"embedded"`); callers compare `== "body"`, never `== "template"`, so a new mode does
  not silently stop walking `env:`.
- **Corpus first, flip second** (D13): convert under the old semantics with no braced `${NAME}` in any body, prove
  outputs identical (per-node trace dumps, an sh equivalence harness with stubbed `PATH`), then flip on a clean
  corpus. The instrumented suite run (a temporary hook in `split_params` + `iter_node_surfaces` logging the test id)
  found the ~50 sites a static scan cannot see — reuse it for any future corpus-wide syntax change.
- **Messages carry their fix**, branch on whether the step already has `env:`/`inputs:`, and are verified by
  applying the fix and running it.
- **Anti-patterns rejected:** `set -u` as the leftover guard (still exits 0 inside `$(…)`); a shell lexer / quote-aware
  scan (a single-quoted `'\$${X}'` therefore gets the two-readings message too); the validator's workflow-wide scope;
  making every consumer redact instead of recording one safe copy; a declared `dict[str, str]` type for `env:` (Task
  112 would reject `PORT: 8080`).

## Gotchas & Non-Obvious Coupling
- **`NamespacedSharedStore.pop("env")` raises `KeyError` when the ROOT has an `env` key** (a step/input named
  `env`) — do not re-add the success-path pop.
- **After a step fails, `shared[node_id]` is gone** (moved to `__failures__`): an absence assertion there passes for
  free — read `__failures__[node_id]` instead (Part 1's test-reflect caught exactly this).
- **The shell Interface comment must not contain `, X: `** — the metadata extractor splits on `, ` and registers a
  fake param.
- **A value routed through `inputs:` (and every loop Carry, and a sub-workflow input) is JSON-parsed there** and
  re-serialized by `to_string` — #686, Task 120's. Bind directly in `env:` when the bytes matter.
- **On a shell step `inputs:` is only the namespace `env:`/`stdin`/`cwd` read from**; an `inputs:` key no other param
  references gets the "not visible to the command" warning (`_validate_unread_step_inputs`).
- **Windows (observed on `tests-windows`):** a native path bound in `env:` works untranslated; Git Bash imports
  `PATH`/`TEMP` upper-cased and path-converts their values (CP-2 ruling: documented, pinned); a 200 KB value binds.
  Linux refuses one value over 128 KiB; macOS ~1 MB for arguments + environment together.
- **Memo cache:** a converted body moved from `template_params` to `params` — one miss per such step, once.
- **Masking is whole-word** (`security_utils.is_sensitive_parameter`): `TOKEN_LIMIT` is masked, `MY_KEY`/`BEARER`
  are not — the guide states the words.
- **The docs harness** (`test_guide_example_validation.py`) declares bare names from template *surfaces*, never a
  regex over the file — otherwise a guide `${HOME}` in a fence becomes an in-scope root.
- **Task-159 capture must run each case in its real directory** (repo-relative paths and `/var` vs `/private/var`
  produce false diffs elsewhere).

## Integration Points
- **Task 181 (MCP code params) builds on:** `param_mode` (a third answer), `template_params`, `TemplateConfig.node_type`,
  `split_params(params, expected_types, node_type)`, the scope rule `data_flow.step_scope(workflow_ir, node) ->
  StepScope` with `StepScope.owner(root, *, has_path) -> str | None` (reuse that alone — `body_references` is
  sh/Python-specific), the unused-input hook = the `| body_reference_roots(workflow_ir)` term of the union passed to
  `_validate_unused_inputs` in `runtime/template_validation/validator.py::validate_workflow_templates`, and
  `isCodeBody` (`web/src/utils/format.ts:146`, called at `web/src/graph/scan.ts:139`, `web/src/components/ReadPanel.tsx:76`;
  `sourceDecorate.ts` keys on fence grammar via `tealsRefs`, not `isCodeBody`). A literal `${` inside an
  `evaluate_script` `function:` is still a pflow ref — that is 181's surface.
- **Task 120 inherits** the value-to-text rule (`to_string`) and *replaces* `binds_as_text`/`parses_leaves`. Open for
  it (from Part 1's falsifier): literal YAML numbers reinterpret silently (`1.10` → `1.1`, `0755` → `493`); a
  declared `type: string` CLI input is still type-inferred (`cli/param_parsing.py`).
- **Task 182 (linting):** `code_bodies` yields the language; shellcheck's SC2153 did-you-mean works with UPPER_SNAKE
  names given a preamble that assigns the bound names; the bare `$ENDPONT` typo class is deliberately left to it (D6).
- **Contracts changed:** shell failure output gains `env` (display-safe) → JSON `shell_env`; `pflow report` shell
  pages always show `## Command` and `## Env`; MCP single-node runs no longer env-expand a body; Pass 7 is gone.
  Unchanged: trace format, MCP code params (strict, `$${` as before).
- **Issue #727** (stdin encode failure after spawn): not built. The encodability half of
  `env_binding._value_problem` is the reusable pre-spawn check — moving `stdin` text through it in `prep()` makes the
  fix small.

## Tests That Matter
- `tests/test_integration/test_code_body_consumers.py` — one row per body consumer, each with an `env:` presence half;
  the mutation ledger (log, PB + review) shows each row red when its site's body rule is removed.
- `tests/test_integration/test_code_body_leftovers.py` — leftover shapes, hard cases (a)–(g), false positives (legal
  sh), escapes, code bodies, unused-input coupling; ~30 mutations recorded.
- `tests/test_core/test_workflow_data_flow.py:493/521` — `${array[@]}`/`${#count}` in a body must stay silent
  (over-fire guard).
- `tests/test_integration/test_template_parity.py` — `BODY_ROWS`, `shell_body`/`code_body`/`shell_env` surfaces.
- `tests/test_integration/test_shell_env_binding.py` + `tests/test_nodes/test_shell/test_env_binding.py` — every
  value type, JSON byte identity (mutation: restore `auto_parse` → red), failures before spawn under `ignore_errors` /
  retry / batch `continue`, and the D8 Windows rows (CI is the oracle).
- `tests/test_integration/test_shell_failure_display.py` + `tests/test_core/test_trace_report.py` — redaction, cap,
  `to_string` text, batch/sub-workflow leak paths, legacy item command.
- `tests/test_docs/test_guide_example_validation.py` — every guide/docs fence validates under the rule.
- `tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match` — drifts only when a body's
  memo key changes.
- Web: `scan.test.ts` parity rows, `sourceDecorate.test.ts` (instant, null-highlight, line-mismatch tiers),
  `batchItems.test.ts`, `ParamBlock.test.tsx`.

## Breaking changes
- Old-form workflows (a `${…}` in a shell command or code block) fail validation with the fix — including the
  user's saved library under `~/.pflow/workflows/` (converting it is the user's call; the skill symlinks keep showing
  agents the old form until then). A paused or failed run of an old-form workflow resumes only after the file is
  converted **and** with `pflow resume --force` (content hash). A worktree whose `workflows/` copy predates Part 1
  must merge `main`.
- `docs/changelog.mdx`'s v0.16.0 entry and `task_148/verification/*.pflow.md` keep old-form text as history.

## Follow-ups (verified, not built)
- Web per-item preview substitutes `$${item.x}` as a ref and renders `true`/`null` where the command receives
  `True`/empty (`batchItems.substitute`; pre-existing, display-only).
- The terminal approval preview shows typed `env:` values (`true`) and truncates the `env` line at 200 chars — plan
  D11 kept it out of scope; approvers now see it where they used to see the resolved command.
- A `__`-prefixed `env:` name is missing from `pflow report` `## Env` (the trace writer drops `__` keys —
  `runtime/workflow_trace.py`).
- MCP `registry_run` success never forwards validation warnings (pre-existing; ruling-2 and `env:` warnings included).
- The two MCP instruction resources carry only the rule edits — not the guide's `env:` names/limits/masking section.
- A `${input}` inside a shell comment is a blocking leftover (ruled whole-body read; low frequency).
- Screenshot skill: no read-panel scroll primitive.
- Plan §10: carry resolved params on the failure record (#698) and retire `shared["env"]`/`command`;
  `gate.masked_preview` duplicates `redact_sensitive`; an empty secret-named value shows `<REDACTED>`; http
  `headers`/`params` share the old JSON-parse hazard (Task 120's predicate); Task-159's remaining 11 drifts need the
  re-record follow-up.

---
*Distilled from the implementation context of Task 118 (both parts). The chronological journey lives in
`implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration of it.*
