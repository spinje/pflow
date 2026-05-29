# Task 161 Review: Safer Cache Defaults + Iteration Pattern Documentation

## Metadata
- **Implementation**: multi-session (plan → implement → #441 fix → PR → guide audit → code-review response)
- **Pull Request**: https://github.com/spinje/pflow/pull/442
- **Issues**: closes #444 (umbrella: cache-default corruption + undocumented iteration) and #441 (coalesce absent-field fall-through); spawned #443 (`--only` re-fires side-effecting upstream)
- **Scope**: 70 files vs `main` (+1586/−635), 4 commits
- **Gate**: `make check` clean; `make test` 7195 passed, 1 skipped

## Executive Summary

Flipped memo-cache defaults so only `llm` nodes cache by default; every other node type defaults to `cache: false`. This converts a silent-corruption failure mode (iteration loops re-serving stale cached results while reporting success) into a loud one (slower runs, visible in `pflow report`). Bundled with it: `??` literal operands, `??` absent-field fall-through (#441), reserved-internal-key validator errors, and the docs that make pflow's loop/iteration patterns discoverable.

## Implementation Overview

### What Was Built
- **Cache flip**: one predicate `_default_cache_for_node_type(node_type) -> node_type == "llm"` at the single compile-time default site; `NodeConfig.cache_enabled` field default flipped to `False` in lockstep.
- **`??` literals (Optional A)**: `${a ?? 0}`, `${a ?? "x"}`, `${a ?? null}`, bare `${0}` parse and resolve via `try_parse_json`, gated by a new `_LITERAL_PATTERN`.
- **`??` absent-field fall-through (#441)**: `resolve_coalesce` falls through on a missing field (not just a missing node), matching JS/jq/Jinja. The `"path_error"` status was **removed** — it now returns only `resolved`/`unresolved`.
- **Validator UX**: reserved `__k__` keys → targeted error; `${__index__.foo}` → "is an integer"; inputs/node IDs named `true`/`false`/`null` rejected.
- **Lint deletion**: `_warn_inputless_shell_nodes` (+ 9 tests) removed — its premise ("result is cached and reused") is false post-flip.
- **Docs**: removed false "No Loops" section; added Loops (branching), Bounded iteration (sub-workflows), `parallel: false` batch example, cache-scope subsection, loop/iteration intent routing in `entry.md`, and corrected the stale "upstream cached" `--only` guidance across 5 surfaces.

### Deviations from plan
- Test migration was done by **running the suite and fixing what broke**, not by the plan's (drifted) line numbers. Bulk perl replace added `cache: True` to shell/code/http nodes in big plan-drift files.
- `_field_checkable_templates`/`_extract_all_templates` split (validator) was NOT in the original plan — it emerged when #441's fall-through forced validator/runtime consistency.
- `--only` interaction (#443) was discovered late (not in the plan or first implementation), via the user's "are you FULLY happy?" prompt.

## Files Modified/Created

### Core (cache flip)
- `runtime/compilation/compiler.py` — `_default_cache_for_node_type` (the one default site).
- `runtime/engine/types.py` — `NodeConfig.cache_enabled` default `True`→`False` (lockstep; hidden second source of truth otherwise).
- `core/ir_schema.py` — `cache` field description.
- `core/workflow/validator.py` — deleted `_warn_inputless_shell_nodes`; added `_reject_reserved_literal_names`.

### Core (`??` operator)
- `runtime/template_resolver.py` — `_LITERAL_PATTERN`, `is_literal_operand`, literal short-circuit in `resolve_coalesce` + `resolve_template` + `_resolve_complex_match`; `path_error` removed from `resolve_coalesce`.
- `runtime/template_validation/validator.py` — `_iter_template_operands` → `_field_checkable_templates` / `_extract_all_templates` split; `_PERMISSIVE_PATTERN` extended with `_LITERAL_PATTERN`.
- `core/workflow/data_flow.py` — `_reserved_internal_key_diagnostic`; literal-filter before root-check.
- `core/types.py` — `is_template_reserved_internal_key`.
- 13+ coalesce consumer sites (`cache_overlap.py`, `prompt_refs.py`, `prompt_cache_analysis/*`, `mermaid/_scope.py`, `engine/template_errors.py`, `type_validation.py`, `batch_item_validation.py`) — filter literal operands.

### Tests (critical)
- `tests/test_integration/test_iteration_pattern.py` — **the load-bearing regression**. Mutation-checked.
- `tests/test_runtime/test_template_validation/test_literal_operands.py` — literal forms + loud rejection of `007`/`"a??b"`/unterminated.
- `tests/test_runtime/test_template_coalesce.py`, `tests/test_integration/test_branch_convergence.py` — #441 fall-through + preserved bare-typo error.
- Migrated: `test_cache_integration.py`, `test_memoization_integration.py`, `test_plan_drift.py`, `test_cache_opt_out*.py`, `test_plan.py`.

### Docs
- `guide/{core,entry,nodes/{llm,shell,code,claude-code},features/{branching,sub-workflows,batch}}.md`, `docs/{how-it-works/template-variables.mdx,reference/cli/index.mdx}`, `cli/CLAUDE.md`, `core/workflow/CLAUDE.md`, `mcp_server/CLAUDE.md`, 2 MCP instruction mirrors.

## Architectural Decisions & Tradeoffs

- **Only `llm` caches by default** — purity, not expense, is the cache-safety criterion. `claude-code` is explicitly NOT cached despite cost: it is side-effecting like shell; caching its summary divorces it from on-disk work.
- **#441 → Option 2 (fall-through), NOT schema-aware (Option 4)**. Option 4 (consult the producing node's declared output schema to distinguish optional-field from typo) was rejected because it false-positives on dynamic JSON access — `${shell.stdout_json.items ?? []}` where `items` is in no declared schema. Bounded cost accepted: a field typo on a *valid root inside a `??` chain* goes silent; bare `${node.tpyo}` still errors and the root is still checked. **This same reasoning rejects any "warn when path doesn't statically resolve" idea.**
- **`is_literal_operand` is a coarse first-char classifier, gated by the grammar.** `_LITERAL_PATTERN` (via `TEMPLATE_PATTERN`/`_PERMISSIVE_PATTERN`) is the load-bearing source of truth for "what is a usable literal." The predicate is intentionally broader (returns True for `[1,2]`, `007`) — it only runs on grammar-accepted operands. Do NOT assume `is_literal_operand(x)` ⇒ `try_parse_json(x)` succeeds.
- **Reserved-internal-key rejection is validator-only**, not a runtime guard. Runtime `TemplateResolver` *could* resolve `${__execution__.x}` against `dict(shared)`, but all production `compile_workflow` callers validate first. One source of truth > duplicate runtime guard.
- **Reserved-literal-name guard runs after structural validation, before the numbered semantic steps** (not a peer step 11). Documented in the `validate()` docstring + `core/workflow/CLAUDE.md` + `mcp_server/CLAUDE.md` (code-review item #4).

## Critical Knowledge (read before touching caching / `??` / `--only`)

### The cache key is blind to the world
Key = node type + static params + raw template strings + batch config + prompt-cache content + resolved inputs. It models **nothing** external: no filesystem, clock, env, or network. A `shell` running `cat queue.txt` has a stable key as the file changes. This is the whole bug class.

### `cache` is NOT part of the config hash
Load-bearing twice: (1) `test_cache_false_does_not_write_to_memo_cache` flips `cache:false`→`true` on otherwise-identical IR and gets the *same* key to probe write-leaks; (2) dry-run `_tag_from_entry` can't distinguish "explicitly disabled" from "default-disabled" — both surface as `cause="cache_disabled"` (so the tag is shown only for `LLMNode`).

### `--only` regression (#443) — THE thing to understand
The cache flip **silently changed `--only`**. `engine._run_inner` walks from `start_node` and executes every upstream node until the target, consulting the memo cache per node (no trace restoration). Before: non-llm upstream was cached → memo-hit → `exec()` skipped → **side effects did NOT re-fire**. After: non-llm upstream is uncached → `exec()` runs → **side effects re-fire** (e.g. `--only summarize` over `shell: gh pr create` re-creates the PR). Recommended fix: trace-based upstream restoration (hydrate from last `~/.pflow/debug/` trace). Docs carry an interim warning. **If you touch caching or `--only`, read #443 first.**

### Two critical silent-failure bugs caught ONLY by review (not the plan, not happy-path tests)
- Leading-zero ints (`007`/`01`): grammar accepted, `try_parse_json` rejected → raw `${...}` leaked. Fixed: `_LITERAL_PATTERN` number branch forbids leading zeros (`-?(?:0|[1-9]\d*)`).
- `??` inside a string literal (`"a ?? b"`): grammar accepted, the operand splitter shredded it. Fixed: string branch forbids `??` (`\?(?!\?)` allows a lone `?`).
Both were validate-clean-then-silently-fail — the exact failure mode this task set out to kill. **When two checks guard one value (grammar vs predicate vs `try_parse_json`), make one authoritative and document the others as deferring to it.**

### Source-line coupling
Removing `- cache: false` from `examples/error-handling/*.pflow.md` shifts line numbers that `test_failed_node_invariant.py` asserts on (those fixtures double as source-line-tracking tests). Editing an example file = editing a test's expected line numbers.

### `make test` does NOT run `src/` doctests
`testpaths = ["tests"]` means `--doctest-modules` only collects under `tests/`. ~22 pre-existing `src/` doctest failures (unrelated modules) are invisible to the gate. "make test passes" ≠ "src doctests pass."

### Cross-surface doc drift
The "upstream cached" / cache-default phrasing is mirrored across guide / CLI ref (`docs/reference/cli/index.mdx`) / MCP instruction files / CLAUDE.md. When correcting such a phrase, `grep` the whole repo — editing one surface re-introduces the drift the MCP-sync work fixed.

## Patterns Established

- **Mutation-checked regression test**: `test_iteration_pattern.py` runs a real workflow over real filesystem state with NO `cache: false`, and its docstring states that reverting the flip makes it fail. Verified by actually stashing the resolver change. Turns an implicit contract into an executable one. Reuse this shape for behavior-flip changes.
- **Dual-IR cache-leak test**: identical IR except the `cache` flag, so a leaked write collides with the probe read (the old test used different `purpose` strings → different keys → could never expose a leak).
- **Falsy-present guard**: `test_present_but_falsy_left_value_wins_over_literal` — `${node.x ?? 5}` with `x=0`/`""`/`False` returns the falsy value, guarding against a naive truthy reimplementation of `??`.
- **Single traversal source of truth**: `_iter_template_operands` yields `(operand, in_coalesce)`; both `_extract_all_templates` (unused-input detection, full set) and `_field_checkable_templates` (Pass 5, excludes coalesce operands) derive from it. Don't reimplement operand walking per-pass.

## Anti-Patterns / Gotchas

- Don't "unify" `resolve_coalesce` with `output_resolver._is_all_absent_coalesce` — the `## Outputs` coalesce intentionally does NOT fall through on a recovered-node failure (different concern: not swallowing recovery-handler failures in the output contract). The `resolve_coalesce` docstring documents this asymmetry.
- Don't make `is_literal_operand` module-private — ~18 cross-module callers need it public.
- Don't field-check coalesce operands in Pass 5 — that re-breaks #441 (a legitimately-optional field would hard-error).

## Breaking / Behavioral Changes
1. Non-`llm` nodes no longer cache by default → `claude-code`/`http` re-execute on re-run (cost/latency); add `- cache: true` for deterministic outputs. Also changes `--only` (#443).
2. `${node.field ?? default}` falls through on an absent field (incl. a typo on a valid node) instead of erroring; bare `${node.field}` still errors.
3. `resolve_coalesce` no longer returns `"path_error"` (only `resolved`/`unresolved`). Note: `engine/template_errors.py::classify_unresolved_references` independently still emits `status: "path_error"` for genuinely-unresolved bare refs — that diagnostics path is separate from `resolve_coalesce`.

## AI Agent Guidance

### Quick start for related work
Read first: `runtime/template_resolver.py` (`_LITERAL_PATTERN` + `resolve_coalesce` docstrings), `runtime/template_validation/validator.py` (`_iter_template_operands`), `runtime/compilation/compiler.py` (`_default_cache_for_node_type`), and **issue #443** if touching `--only` or caching.

### Common pitfalls
- Assuming `make test` covers `src/` doctests (it doesn't).
- Editing example `.pflow.md` cache annotations without updating `test_failed_node_invariant.py` line assertions.
- Adding a new `??` consumer without the `is_literal_operand` literal filter (literal `0` would become a bogus node ref / leak into error messages).
- "Fixing" the validator-only reserved-key check by adding a runtime guard (redundant; one source of truth).

### Verification recipe when modifying this area
1. `tests/test_integration/test_iteration_pattern.py` (cache-flip contract).
2. `tests/test_runtime/test_template_coalesce.py` + `test_literal_operands.py` (`??` semantics + grammar).
3. `tests/test_integration/test_branch_convergence.py` (end-to-end `??`).
4. Full `make check && make test`.

---

*Generated from implementation context of Task 161. Companion docs: `implementation/progress-log.md` (session-by-session journey).*
