# Task 154: Type Vocabulary Coherence

## Description

Fix the incoherent type vocabulary at pflow's workflow authoring surface. Today `## Inputs` and `## Outputs` accept 12 type names as silent synonyms (JSON Schema canonical + undocumented Python aliases), `type: object` silently accepts any value (not just dicts), and `type: any` — the natural escape hatch — is rejected outright. Code-block annotations using bare `Any` fail with a misleading error that tells the agent to add `Any` to the inputs dict.

This task shrinks the `## Inputs` / `## Outputs` `type:` vocabulary to seven canonical JSON Schema names, makes `object` mean dict-only, introduces `any` as the explicit wildcard, and auto-injects `typing.Any` into Python code-block exec namespaces. Breaking change, shipped as one atomic PR.

The implementation plan lives at `implementation/implementation-plan.md` in this task folder — this file captures the **what** and **why**; the plan captures the **how**.

## Status

not started

## Priority

medium

## Problem

Authoring `.pflow.md` files today is dragged down by three compounding incoherences in the type system (reproduced as executable probes in `scratchpads/type-vocabulary-incoherence/repro-files/` and documented in full at `scratchpads/type-vocabulary-incoherence/bug-report.md`):

1. **Two vocabularies for the same thing, one undocumented.** The IR schema accepts both `string` and `str`, `object` and `dict`, `array` and `list`, etc. — 12 names doing the job of 6 concepts. Only the JSON Schema names are documented. Agents pattern-match against whatever example they see first; the same repo ends up with `type: str` in one file and `type: string` in another, authored by the same agent on different days.

2. **`type: object` is a hidden wildcard.** Probe E confirms pflow accepts any value (string, list, int, dict) through `type: object`. A type label that looks restrictive but behaves permissively creates false confidence — downstream bugs surface as schema bugs disguised as application bugs. The natural wildcard name `any` is rejected at the declaration layer; the unnatural one (`object`) does the wildcard's job silently.

3. **`Any` in code blocks requires import ceremony — and the error message is misleading.** Writing bare `x: Any` in a code block produces `NameError: name 'Any' is not defined`, which pflow's error handler incorrectly formats as `"Add 'Any' to the inputs dict: {"Any": ...}"` — sending agents to fix a nonexistent missing-input problem. Users must write `from typing import Any` not because Python needs it but because pflow's exec path didn't pre-inject it.

Compounding these, the user-facing documentation (`src/pflow/guide/core.md`, MCP agent instructions, mintlify reference) teaches only the 5-name JSON Schema vocabulary — silently under-stating what the parser accepts and never explaining what any of the words actually mean at runtime.

## Solution

Ship a single atomic PR that:

1. **Collapses S1 vocabulary to 7 canonical names.** `## Inputs` and `## Outputs` `type:` accepts exactly `string | number | integer | boolean | array | object | any`. Python aliases (`str`, `int`, `float`, `bool`, `dict`, `list`) become hard errors with actionable fix suggestions ("Use 'string' instead of 'str'").

2. **Makes `object` mean dict-only (semantically and in docs).** Documents the change; the `any` keyword becomes the explicit wildcard. Strict runtime rejection of non-dict values for `type: object` is deferred to Task 120 — this task is vocabulary, not enforcement strictness.

3. **Auto-injects `typing.Any` into Python code-block exec namespaces.** `x: Any` works without `from typing import Any`. Lowercase `x: any` in code blocks becomes a hard error with a message that teaches the two-surface model. The misleading NameError handler is fixed for common typing names (`Union`, `List`, `Dict`, etc. — with modern `int | None` syntax suggested as an alternative).

4. **Centralizes vocabulary knowledge in a new `TypeSpec` class** (`src/pflow/core/types.py`). Canonical parsing, acceptance semantics, JSON Schema export, and structured error types in one place — so Task 120 (strict coercion) and future union-type work have a single model to grow from.

5. **Extends `SchemaValidationError` to carry structured context** (`similar_names`, `available_fields`, `suggestions_list`) — bringing type-vocabulary errors in line with the producers-are-self-describing diagnostic pipeline the rest of the codebase already uses.

6. **Updates every doc surface that teaches the old vocabulary** — guides, MCP agent instructions, architecture specs, changelog. The new S1↔S2 bridge is documented in one place and cross-referenced from all type-teaching surfaces.

## Rationale

### Why separate S1 and S2 vocabularies (vs one shared vocabulary)

S1 is an external contract; external consumers (CLI users, MCP clients, non-Python tooling) shouldn't need Python context to read an `## Inputs` declaration. S2 must be Python because the runtime is Python. They serve different purposes, so they use different dialects. Four independent AI agents polled on this question independently landed on the same framing: "authoring surface speaks its native dialect; the bridge is documented once." Forcing them to match character-for-character either drags Python into the contract or forces the code block to accept non-Python spellings that break syntax highlighting.

### Why `object` → dict and `any` → wildcard instead of keeping `object` as the wildcard

A type label that looks restrictive but behaves permissively is worse than no label. Author predictability trumps implementation convenience. Making `object` restrictive and introducing `any` as the explicit wildcard aligns the vocabulary with its own name.

### Why ship both breaking changes in one PR

Single-user repo — no backward-compat debt. Two breaks in one release = one migration. Spread across releases = a confused intermediate state where `object` is strict but `str` still works. Polls of five independent reviewers unanimously recommended atomic shipping.

### Why hard errors, not deprecation warnings

Agents ignore warnings until they become errors. The confusing intermediate state ("works but will break") is a worse cost than the focused "here's the fix" error. Error quality (copy-pasteable suggestions like `"Use 'string' instead of 'str'"`) is what makes hard errors acceptable.

### Why `Any` auto-injected but lowercase `any` rejected in code blocks

Python code should BE Python. Each surface speaks its native dialect. But `from typing import Any` ceremony is pure tax; injecting `Any` (like `Optional` is already injected) removes the tax without leaking `typing` knowledge into workflow authoring. Lowercase `any` is a clear signal of surface confusion — rejecting it with a fix suggestion teaches the two-surface model rather than silently mapping.

## Scope

### In scope

- IR schema enum for `inputs.*.type` and `outputs.*.type` (shrink 12 → 7)
- Python code-block `Any` auto-injection
- Vocabulary-rejection error messages with actionable suggestions
- Parameterized-generic rejection at S1 parse time (e.g., `list[str]` → "Use 'array'")
- `TypeSpec` centralization class
- `SchemaValidationError` structured-context extension
- Full doc sweep (guides, MCP instructions, architecture specs, changelog)
- Test fixture migration for the few tests authored with Python aliases
- Example workflow cleanup (`examples/output_validation_demo.pflow.md:43`)

### Out of scope — deferred

- **Strict runtime enforcement** for non-dict values passed to `type: object` inputs (deferred to Task 120)
- **Complex / nested input schemas** (`properties:`, `required: [...]`) — separate follow-up task
- **Union syntax at S1** (`string | null`, `int | float`) — `null` is dropped from the vocabulary for now; unions land in a later task
- **Registry `Interface:` docstring canonicalization** — node Interface metadata stays Python-named; it's a third dialect with different consumers and a different migration story
- **Claude Code `output_schema` vocabulary** — intentionally Python-named because it's embedded into LLM prompt construction; documented as third dialect, not migrated

## Dependencies

None blocking. Task lands independently.

## Sequencing with other work

- **Unblocks Task 120** (strict input type validation) — that task adds validate-time enforcement against the `TypeSpec` model this task introduces, rather than adding another independent vocabulary surface.
- **Unblocks future complex-schema work** — nested input schemas can reuse the flat `{field: {type, description}}` YAML convention that the Claude Code `output_schema` feature already uses, now against a consistent S1 vocabulary.
- **Independent of Task 153** (reserved for another refactor).

## Success Criteria

1. Every probe in `scratchpads/type-vocabulary-incoherence/repro-files/` produces the expected post-refactor behavior (A3 passes; A1/A2 fail with exact fix suggestions; B2 passes without import).
2. `make test` and `make check` both pass.
3. `grep -rnE "type: (str|int|float|bool|dict|list)\b"` across `src/pflow/guide/`, `docs/`, `architecture/`, and `src/pflow/mcp_server/resources/instructions/` returns zero hits in workflow-IR contexts.
4. JSON-formatted validation errors (`--output-format json`) carry structured `context.similar_names` / `context.available_fields` / `context.available_fields_label` — not just prose suggestions.
5. The `scratchpads/type-vocabulary-incoherence/bug-report.md` file gets a "Post-fix behavior" appendix documenting the new expected outputs.
6. No production `.pflow.md` workflow regresses (most already use canonical names; zero mechanical migration needed in `examples/`).

## Research

- Full problem analysis and reproducible probes: `scratchpads/type-vocabulary-incoherence/bug-report.md`
- Fourteen minimal probe workflows demonstrating each bug: `scratchpads/type-vocabulary-incoherence/repro-files/`
- Five-agent code review of the implementation plan (5 confirmed critical findings, 7 warnings, all addressed): captured in the implementation plan's revision history

## Implementation

See `implementation/implementation-plan.md` for the atomic, line-level implementation plan — including exact file paths, code changes, test additions, documentation edits, and a probe-based verification strategy. The plan is self-contained and executable by a single AI agent without further research.
