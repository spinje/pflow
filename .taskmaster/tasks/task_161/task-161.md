# Task 161: Safer Cache Defaults + Iteration Pattern Documentation

## Description

Flip pflow's memo-cache defaults so only `llm` nodes cache by default (every other node type defaults to `cache: false`), eliminating a silent-corruption class where iteration loops over external state re-served stale results while reporting success. Ships with the documentation that makes pflow's loop/iteration patterns discoverable, an extension of the `??` operator to accept JSON literal operands, a fix for `??` absent-field fall-through (#441), and a targeted validator error for reserved internal keys.

## Status

done

## Completed

2026-05-29

## Priority

high

## Problem

pflow's memo-cache key is computed from node type + static params + raw template strings + batch config + prompt-cache content + resolved inputs — it models **nothing about the world outside declared inputs** (no filesystem, clock, env, or network state). Under the old "cache everything by default":

- A `shell`/`code`/`http`/`file`/`mcp` node that reads external state (e.g. `cat queue.txt`) had a *stable* cache key even as the underlying state changed. Iteration 2+ of a loop silently re-served iteration 1's output while reporting success — a silent-corruption failure, the worst debugging case.
- The docs actively misled: `pflow guide core` had a `❌ No Loops or Iteration` section that was categorically false (loops via backward edges and bounded iteration via sub-workflow batch both work). Agents reading it stopped looking for loop-shaped patterns.
- `${node.x ?? literal}` was unsupported (literals weren't valid `??` operands), producing a misleading "malformed template" error and forcing seed-node workarounds.
- `${node.field ?? default}` did not fall through to `default` when the node ran but the field was absent (#441) — it errored, contradicting the universal `??`/`//`/`default()` mental model and breaking our own claude-code recovery example.

## Solution

- **Cache flip**: single predicate `_default_cache_for_node_type(node_type) == (node_type == "llm")` at the one compile-time default site; `NodeConfig.cache_enabled` field default flipped to `False` in lockstep. `llm` is the only node type whose output is purely a function of declared inputs.
- **Optional A** (`??` literals): `${a ?? 0}`, `${a ?? "x"}`, `${a ?? null}`, bare `${0}` parse and resolve, reusing `try_parse_json`. A `_LITERAL_PATTERN` grammar deliberately forbids leading-zero numbers and `??`-inside-strings so the validator catches them loudly instead of validating-clean-then-failing at runtime.
- **#441 fall-through**: `resolve_coalesce` falls through to the next operand when a node ran but the field is absent (matching JS/jq/Jinja), returning only `resolved`/`unresolved`. Validator Pass 5 stops hard-erroring on a missing field inside a `??` chain to keep validation and runtime consistent.
- **Validator UX**: reserved `__double_underscore__` keys (`${__execution__.x}`) get a targeted "reserved by pflow" error with the correct alternative; `${__index__.foo}` gets its own "is an integer" message. A reserved-literal-name guard rejects inputs/node IDs named `true`/`false`/`null`.
- **Docs**: removed the false "No Loops" section; added Loops (branching), Bounded iteration (sub-workflows), a `parallel: false` batch example, an explicit cache-scope subsection, loop/iteration intent routing in `entry.md`, and corrected the stale "upstream cached" `--only` guidance across guide / CLI ref / MCP mirrors / CLAUDE.md.
- **Lint deletion**: removed `_warn_inputless_shell_nodes` (its message became factually false after the flip).

## Design Decisions

- **Only `llm` caches by default** — purity, not expense, is the cache-safety criterion. `claude-code` is explicitly NOT cached-by-default despite being expensive: it is side-effecting like shell, and caching its summary divorces it from the on-disk work.
- **#441 → Option 2 (fall-through)**, not the schema-aware approach (Option 4). Option 4 (consult the producing node's declared output schema to tell "optional field" from "typo") was rejected because it false-positives on dynamic JSON access — `${shell.stdout_json.items ?? []}` where `items` is in no declared schema. Option 2 matches every mainstream coalescer; the bounded cost (a field typo on a valid root *inside a `??` chain* goes silent) is accepted because bare `${node.tpyo}` still errors and the root is still checked.
- **`is_literal_operand` is a coarse first-char classifier, gated by the grammar** — the regex (`_LITERAL_PATTERN` via `TEMPLATE_PATTERN`/`_PERMISSIVE_PATTERN`) is the load-bearing source of truth for "what is a usable literal." Documented as broader than the grammar on purpose; reviewer-flagged future-misuse risk left as-is (no current misuse; predicate must stay public — ~18 cross-module callers).
- **Reserved-internal-key rejection is validator-only**, not a runtime guard. All production `compile_workflow` callers validate first, so one source of truth beats a duplicate runtime guard (the runtime `TemplateResolver` could technically resolve `__execution__` against `dict(shared)`).
- **Bundled three load-bearing semantic changes in one PR** — flagged by review as the main structural concern; accepted for this MVP-stage repo.

## Dependencies

- Task 106 (Workflow Iteration Cache) and Task 159 (Prompt Caching) — establish the memo-cache mechanism this task re-defaults. No code dependency; historical context.

None blocking (work is complete).

## Requirements

### Cache defaults
- Only `llm` defaults to `cache: true`; `shell`/`code`/`claude-code`/`http`/`file`/`mcp` default to `cache: false`.
- The default lives in exactly one place (compiler) with the `NodeConfig` field default in lockstep.
- A sub-workflow batch (`parallel: false`) read/mutate/write-back loop produces correct results with NO `cache: false` annotations.

### `??` operator
- JSON literal operands (`number`, `"string"`, `true`/`false`/`null`, `[]`/`{}`, bare `${0}`) parse and resolve with correct types.
- Leading-zero numbers, `??`-inside-strings, and unterminated strings are rejected loudly at validation, not silently at runtime.
- Absent-field fall-through: `${ran_node.absent ?? default}` resolves to `default`; bare `${ran_node.absent}` (no fallback) still errors; the root is still validated.

### Validator UX
- `${__execution__.x}` (and other reserved `__k__` keys) produce a targeted reserved-key error, not "did you mean __index__?".
- Inputs/node IDs named `true`/`false`/`null` are rejected with a clear rename suggestion.

### Docs
- No "❌ No Loops or Iteration" content anywhere in the guide.
- Loops, Bounded iteration, and a `parallel: false` example are present and runnable.
- `--only` / cache-default guidance is consistent across guide, CLI reference, MCP mirrors, and CLAUDE.md.

## Implementation Notes

- Cache default site: `src/pflow/runtime/compilation/compiler.py` (`_default_cache_for_node_type`); field default at `src/pflow/runtime/engine/types.py`.
- `??` grammar + resolver: `src/pflow/runtime/template_resolver.py` (`_LITERAL_PATTERN`, `is_literal_operand`, `resolve_coalesce`, `resolve_template`, `_resolve_complex_match`). 13+ coalesce consumer sites filter literals via `is_literal_operand`.
- Validator: `src/pflow/runtime/template_validation/validator.py` (`_iter_template_operands` → `_field_checkable_templates`/`_extract_all_templates` split), `src/pflow/core/workflow/data_flow.py` (`_reserved_internal_key_diagnostic`, root-checking), `src/pflow/core/workflow/validator.py` (`_reject_reserved_literal_names`), `src/pflow/core/types.py` (`is_template_reserved_internal_key`).
- The `## Outputs` coalesce (`output_resolver._is_all_absent_coalesce`) intentionally does NOT fall through on a recovered-node failure — a different concern; left unchanged.

## Verification

- `tests/test_integration/test_iteration_pattern.py` — sub-workflow batch read/mutate/write-back over 5 distinct items with NO `cache: false`; mutation-checked (reverting the flip makes it fail).
- `tests/test_runtime/test_template_validation/test_literal_operands.py` — literal forms + loud rejection of leading-zero / `??`-in-string / unterminated.
- `tests/test_runtime/test_template_coalesce.py` + `tests/test_integration/test_branch_convergence.py` — absent-field fall-through and preserved bare-typo error.
- Migrated cache suites green (`test_cache_integration.py`, `test_memoization_integration.py`, `test_plan_drift.py`).
- Full gate: `make check` clean, `make test` 7195 passed / 1 skipped.

## Known Open / Follow-ups

- **#441** — closed by this task (fall-through implemented).
- **#443** — `--only` re-executes side-effecting upstream nodes after the cache flip (recommended fix: trace-based upstream restoration). Out of scope; docs carry an interim warning.
- Reserved-literal-name guard has no compile-time backstop (sound today; noted asymmetry).
- Considered-and-rejected follow-up (per user): a narrow lint for explicit `cache: true` on input-less shell nodes.

## References

- PR: https://github.com/spinje/pflow/pull/442
- Issues: #444 (umbrella problem, closed by this), #441 (coalesce fall-through, closed by this), #443 (follow-up: `--only` re-fires side-effecting upstream)
- Post-implementation review: `.taskmaster/tasks/task_161/task-review.md`
- Session-by-session journey + tacit knowledge: `.taskmaster/tasks/task_161/implementation/progress-log.md`
