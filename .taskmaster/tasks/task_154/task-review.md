# Task 154 Review: Type Vocabulary Coherence Refactor

> **⚠️ Round-2 Addendum — read this first before acting on any guidance below.**
>
> This review was written after round-1 review-prompted fixes but **before round-2**. Round-2 deleted code that round-1 preserved as defense-in-depth, replacing the dual-map architecture with a single validation chokepoint. Several sections below are structurally stale as a result. Specifically:
>
> **Deleted in round-2 (any reference below is stale):**
> - `_TYPE_ALIASES` dict in `src/pflow/core/param_coercion.py` — DELETED. The "Two intentionally-duplicated alias maps" section (lines ~100-105), the "Defense-in-depth comments cite concrete bypass paths" pattern example (~135-145), and the "Technical debt" bullet on `_TYPE_ALIASES` duplication (~123) all describe state that no longer exists.
> - `_normalize_type` helper in `param_coercion.py` — DELETED. Its sole caller was `coerce_workflow_input`; now the raw `declared_type` is used directly.
> - `test_alias_maps_stay_in_sync` / `TestTypeAliasesSyncWithCanonicalSource` — DELETED. The drift-guard test (line ~37 executive summary, ~67 tests section, ~150 pattern section) is no longer needed because the duplication is gone.
> - `test_type_aliases_work_as_defense_in_depth` — DELETED (line ~73). Its reason for existing (pinning the bypass behavior) went away with the bypass close.
> - `TypeSpec.python_type()` — DELETED (line ~207 extension points). Zero production callers; `TypeSpec.accepts()` is the documented extension point for Task 120.
>
> **Added in round-2:**
> - `normalize_ir(workflow_ir)` + `validate_ir(workflow_ir)` at `src/pflow/runtime/workflow_executor.py:208-209` (inside the cache-miss branch of `_compile_sub_workflow`) — the single chokepoint that replaced the dual-map defense. Every IR path now goes through `validate_ir` before reaching `compile_workflow`.
> - AST-walk in `_check_annotation_vocabulary` (`nodes/python/python_code.py`) — catches lowercase `any` nested in generics (`list[any]`, `dict[str, any]`, `int | any`, `Optional[any]`) at the same layer as `x: any`. `Literal['any']` correctly passes through (it's an `ast.Constant`, not `ast.Name`).
> - Claude Code `output_schema` acknowledged as deliberate fourth Python-aliased surface in `src/pflow/core/types.py` module docstring.
>
> **Common pitfall correction (line ~249):** The pitfall "Do NOT remove `_TYPE_ALIASES` in `param_coercion.py`" is **contradicted by reality**. The code has been removed. The new invariant is: **single validation boundary at `compile_workflow` entry** — every IR entry point runs through `validate_ir` before reaching coercion. The `validate_ir` call at `workflow_executor.py:208-209` is the round-2 addition that made `_TYPE_ALIASES` removable.
>
> **For future agents working on Task 120** (strict runtime enforcement): start at `TypeSpec.accepts()` in `src/pflow/core/types.py`. The plumbing point is `param_coercion.coerce_workflow_input` (still lenient). Do NOT reintroduce `_TYPE_ALIASES` — it is intentionally gone. Do NOT add duplicate validation at `_compile_sub_workflow` — `validate_ir` is already there.
>
> **For the full reasoning trail of round-2**, see `implementation/progress-log.md` → "[2026-04-16 post-merge-review round 2]" entry (the "Option B → Option D pivot"). It documents why the dual-map defense was replaced with the single chokepoint.
>
> Sections below are preserved for their architectural context and round-1 reasoning. Read with this addendum in mind.

## Metadata

- **Branch**: `fix/type-vocab-incoherence`
- **Date**: 2026-04-16
- **Issue**: [#291](https://github.com/spinje/pflow/issues/291) (retrospective motivating issue)
- **PR**: [#290](https://github.com/spinje/pflow/pull/290)
- **Commit**: `a32eda47`
- **Diff**: 45 files, +3,765 / -193 lines (round-1 figures; round-2 is net-deletion — see progress-log)
- **Tests**: 4,846 pass at round-1 (+5 new regression guards); 4,849 at round-2 (net +3 after drift-guard/defense-in-depth test deletions)

## Executive Summary

Shrunk the Surface-1 (workflow IR `## Inputs` / `## Outputs`) `type:` enum from 12 silent synonyms to 7 canonical JSON Schema names (`string | number | integer | boolean | array | object | any`). Made `object` dict-only (documented; runtime enforcement deferred to Task 120), introduced `any` as the explicit wildcard, auto-injected `Any` / `Optional` / `typing` into code-block exec namespaces. Breaking change shipped atomically. Introduced `TypeSpec` as the single source of truth for future vocabulary work (unions, complex schemas, strict runtime validation).

## Implementation Overview

### What was built

**Core vocabulary refactor (per plan):**
- New `src/pflow/core/types.py` module: `TypeSpec` dataclass, `TypeVocabularyError`, `CANONICAL_TYPES`, `PYTHON_ALIASES_AT_S1`
- IR schema enum shrink (12 → 7 values) in both `inputs.*.type` and `outputs.*.type`
- `SchemaValidationError` extended with four keyword-only structured-context kwargs
- `_suggest_for_invalid_type` helper routes all type-vocab errors through `TypeSpec.parse` and threads structured context into diagnostics
- `Any` + `Optional` + `typing` auto-injected into code-block exec namespace
- Lowercase `any` in code annotations rejected with `NonRetriableError` teaching the two-surface split
- Parameterized generics (`list[str]`, `dict[str, int]`) rejected at S1 parse time

**Added during review-prompted polish (10 review findings + 1 bonus):**
- Opinionated one-fix-per-case NameError hints (PEP 585 for generics, PEP 604 for Union, import for others) — replaced prior menu-of-options
- `_get_suggestion` rewritten to use list-based path check (catches both `enum` and `type` validator failures at `inputs.*.type` / `outputs.*.type`, drops brittle substring match)
- `_suggest_for_invalid_type(None)` maps to `"null"` so YAML `- type: null` (parses to Python None) reaches the TypeSpec.parse("null") branch
- `_get_output_suggestion` case 3 deleted (dead code after routing consolidation)
- Renderer truncation policy: show-all when `len(available_fields) <= 10`, truncate only beyond
- Parameterized-generic `suggestions_list` rewritten as self-contained (`"Use 'array' — parameterized generics not supported at '## Inputs' / '## Outputs' (got 'list[str]')"`) — full prose survives the `to_diagnostics` preemption
- Drift-guard test: `_TYPE_ALIASES == PYTHON_ALIASES_AT_S1`
- Canonical syntax table in `guide/nodes/code.md` + one-line pointers from 3 other surfaces
- Cross-layer in-process regression test: `validate_ir → to_diagnostics → format_diagnostic` contract

### Deviations from spec (load-bearing to know)

- **Plan §5.3 listed 3 test fixture files; actual migration needed 16.** The extras were test files constructing IR dicts *programmatically* rather than via markdown — they bypass the parser but still hit `validate_ir`. Future vocabulary changes must grep for direct `"type": "<alias>"` dict literals across `tests/`, not just `.pflow.md` fixture strings.
- **Plan §10.3 expected grep `"Parameterized generics not supported"` to match CLI output; it didn't.** The prose lived in `SchemaValidationError.message` but `suggestions_list` preempted it in `to_diagnostics`. Review finding #1 caught this. Fix: populate `suggestions_list` with a self-contained entry that includes the WHY.
- **Plan §2.9 claimed `list[any]` would surface as NameError at exec time. False.** Python's `any` is a valid builtin (the `any()` function); `list[any]` evaluates cleanly via PEP 585 `__class_getitem__`. The limitation is genuine — no runtime safety net. Progress log corrected.
- **Plan §2.5 described `_TYPE_ALIASES` as defense-in-depth for "programmatically-constructed IR dicts, cached IRs, future MCP entry points".** The validation-consistency review identified the *one concrete production path* that actually matters: template-referenced sub-workflows (`workflow: ${dynamic_var}`) bypass `validate_ir` at `sub_workflow_resolver.py:64`. Comment in `param_coercion.py` now cites this specifically to prevent "dead code" cleanup.

## Files Modified / Created

### Core changes (single-source-of-truth surfaces)

- `src/pflow/core/types.py` (NEW, 214 lines) — `TypeSpec`, `TypeVocabularyError`, vocabulary constants. Every future vocabulary consumer should import from here.
- `src/pflow/core/ir_schema.py` — enum shrink, `_suggest_for_invalid_type`, `_get_suggestion` rewritten to return `tuple[str, dict]` and route via list-based path check.
- `src/pflow/core/exceptions.py::SchemaValidationError` — four keyword-only kwargs (`similar_names`, `available_fields`, `available_fields_label`, `suggestions_list`) thread through to `Diagnostic.context`.
- `src/pflow/core/param_coercion.py` — added `"any"` dispatch entry with `(value, log_context)` signature matching convention; kept `_TYPE_ALIASES` as defense-in-depth with specific bypass-path comment.
- `src/pflow/core/diagnostic_render.py::_format_available_fields_block` — truncation policy: show-all for ≤10 entries.
- `src/pflow/core/markdown_parser.py:147` — hint text `str` → `string` (coupled with `test_markdown_parser.py:2355`).

### Code annotation surface (S2)

- `src/pflow/nodes/python/python_code.py` — `Any` injected at line 344, `_check_annotation_vocabulary` rejects lowercase `any`, `_suggest_for_nameerror` helper emits one canonical fix per case (`_MODERN_GENERIC_NAMES` → PEP 585 lowercase, `Union` → PEP 604 pipe, `_REQUIRES_TYPING_IMPORT` → import).

### Tests

**Critical regression guards (added, in priority order):**
- `tests/test_core/test_ir_schema.py::TestInputTypeAliases::test_full_render_pipeline_for_type_vocabulary_error` — cross-layer end-to-end: `validate_ir → to_diagnostics → format_diagnostic`. **Single most load-bearing test** — would have caught the critical review finding.
- `tests/test_core/test_param_coercion.py::TestTypeAliasesSyncWithCanonicalSource::test_alias_maps_stay_in_sync` — pins `_TYPE_ALIASES == PYTHON_ALIASES_AT_S1`. Prevents silent drift between runtime bypass path and validator error source.
- `tests/test_core/test_ir_schema.py::test_null_as_python_none_rejected_with_same_suggestion` — pins that YAML `- type: null` (Python None) routes to the same "Use 'any'" suggestion as the string `"null"` case.
- `tests/test_core/test_types.py::test_parse_rejects_parameterized_generics` — asserts the self-contained `suggestions_list[0]` content (`"Use 'array'" + "parameterized generics not supported"`). Regression guard for suggestions_list preemption.
- `tests/test_nodes/test_python/test_python_code.py::test_nameerror_for_list_suggests_lowercase_generic` / `test_nameerror_for_union_suggests_pipe_syntax` / `test_nameerror_for_literal_suggests_import` — pin the opinionated one-fix-per-case hint; each asserts the correct suggestion AND that the alternative isn't mentioned (no menu regression).

**Existing test renamed (defense-in-depth clarity):**
- `tests/test_runtime/test_prepare_inputs_coercion.py::test_type_aliases_work_as_defense_in_depth` — renamed from `test_type_aliases_work` + expanded docstring explicitly warning future agents NOT to misread it as "Python aliases are supported vocabulary." They're rejected at the validator; this test pins the one legitimate bypass.

**Fixture migrations**: 16 test files updated from Python aliases (`str`/`int`/`list`) to canonical names (`string`/`integer`/`array`) — listed in progress log §4.1.

### Documentation

- `src/pflow/guide/nodes/code.md` — new "Type annotation syntax" section with canonical table. **Single source of truth for allowed syntax.**
- `src/pflow/guide/core.md` — S1↔S2 bridge table + pointer to `pflow guide code`.
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` + `mcp-sandbox-agent-instructions.md` — modern-syntax summary + pointer.

## Integration Points & Dependencies

### Validation routing chain

`TypeSpec.parse(raw)` → raises `TypeVocabularyError(message, offending, similar_names, available_fields, available_fields_label, suggestions_list)` → caught in `_suggest_for_invalid_type` → returns `(suggestion_str, context_kwargs)` → consumed by `_get_suggestion` → threaded as `**kwargs` into `SchemaValidationError.__init__` in `validate_ir` → stored on exception → `SchemaValidationError.to_diagnostics()` produces `Diagnostic` with structured `context` → `format_diagnostic` renders.

**Every link in this chain must preserve structured context.** No prose flattening.

### Cross-surface consumers of `CANONICAL_TYPES`

- `ir_schema.py` — `enum: list(CANONICAL_TYPES)` for both inputs and outputs
- `ir_schema.py` description strings — `f"Data type: one of {', '.join(CANONICAL_TYPES)}"`
- `types.py` — `TypeSpec.__post_init__` validation
- `types.py` — `find_similar_items(..., list(CANONICAL_TYPES), ...)` for fuzzy match

Any new surface rendering the vocabulary must import from `pflow.core.types` — do not hardcode the 7-name list.

### Two intentionally-duplicated alias maps

- `pflow.core.types.PYTHON_ALIASES_AT_S1` — source of truth for validator error suggestions
- `pflow.core.param_coercion._TYPE_ALIASES` — runtime defense-in-depth

**They must stay equal.** Enforced by `test_alias_maps_stay_in_sync`. A future cleanup consolidating them into one import (e.g., `from pflow.core.types import PYTHON_ALIASES_AT_S1 as _TYPE_ALIASES`) is legitimate but out of scope for this task.

## Architectural Decisions & Tradeoffs

### Key decisions

**Separate S1 and S2 vocabularies (not unified Python)** — S1 is an external contract; external consumers (CLI users, MCP clients, non-Python tooling) shouldn't need Python context. S2 must be Python because the runtime is Python. Four poll agents voted 3-of-4 for unified Python; two external reviewers caught the "contract vs implementation" framing that unanimously rerouted to separate-with-bridge. **Lesson**: authoring-agent preference polls optimize for cognitive load, not architectural coherence — cross-check with reviewers.

**Three intentional vocabularies (S1 / S2 / S3)** — S1 = workflow IR (canonical 7), S2 = Python code annotations (modern PEP 585/604), S3 = node registry `Interface:` docstrings + Claude Code `output_schema` (Python-named, feeds LLM prompt construction). **The S1↔S2 bridge is documented; S3 is acknowledged as a deliberate third dialect.** Unifying S3 would break LLM prompt embedding (`_build_schema_prompt` uses the literal Python names).

**Opinionated one-fix-per-case error messages (not menus)** — Pattern matches FastAPI / Pydantic / Typer. A menu (`"option 1: import; option 2: modern syntax"`) forces the agent to decide; the one canonical answer teaches the project's stance. For `List[str]` → `"Use 'list[str]' (PEP 585 lowercase built-in)"`, no import alternative offered. Regression-guarded: each opinionated test asserts the OTHER fix is NOT mentioned.

**`suggestions_list` preempts `suggestion` in `to_diagnostics`** — load-bearing contract. Numbered-list rendering kicks in when `len(suggestions_list) > 1`; single-entry `suggestions_list` overrides `suggestion` prose. **This is why the parameterized-generic fix populates `suggestions_list` with a self-contained entry containing both the fix AND the WHY** — the prose in `suggestion`/`message` is invisible at the renderer layer when `suggestions_list` is non-empty.

**Hard errors, no deprecation window** — No external users = no backward-compat debt. Deprecation warnings create a "works but will break later" intermediate state that agents ignore until it matters.

### Technical debt incurred

- `_TYPE_ALIASES` in `param_coercion.py` duplicates `PYTHON_ALIASES_AT_S1` in `types.py` — intentional defense-in-depth, drift-guarded by test. Consolidation is a legitimate follow-up.
- `TYPE_COMPATIBILITY_MATRIX` in `runtime/template_validation/type_checker.py` carries both Python and JSON Schema names as first-class keys (bridges S1↔S3). Future S3 canonicalization could shrink it.
- `TypeVocabularyError` subclasses `ValueError` not `PflowError` — a `core/CLAUDE.md` convention violation, but the exception is always caught internally and converted to `SchemaValidationError`. Switching the base class likely requires a circular-import refactor; deferred.

## Patterns Established

### Producers are self-describing

`TypeVocabularyError` carries structured fields (`similar_names`, `available_fields`, `available_fields_label`, `suggestions_list`) that thread through `_suggest_for_invalid_type` → `SchemaValidationError` → `Diagnostic.context`. The renderer consumes the structure; agents reading JSON get programmatic access; CLI users get formatted text — all from one structured source.

**Propagate this**: any new error-producing code should populate structured context at the detection site, never flatten to prose for downstream code to reverse-engineer. `src/pflow/core/CLAUDE.md` documents this as project-wide principle; Task 154 is the canonical implementation example.

### Defense-in-depth comments cite concrete bypass paths

```python
# Kept as defense-in-depth for template-referenced sub-workflows that skip
# `validate_ir`: `WorkflowValidator._validate_sub_workflows` returns None for
# template refs (see `core/workflow/sub_workflow_resolver.py`), so the child IR
# reaches `coerce_workflow_input` without the S1 enum check. Task 154 progress
# log §2.5 documents this as defense-in-depth, not dead code.
```

**Not** `"# Kept for non-S1 entry points that may bypass validation."` Generic defense-in-depth comments invite "this looks dead, remove it" cleanups. Concrete-path comments preserve the rationale.

### Drift-guard tests for duplicated-by-design state

```python
def test_alias_maps_stay_in_sync():
    from pflow.core.param_coercion import _TYPE_ALIASES
    from pflow.core.types import PYTHON_ALIASES_AT_S1
    assert _TYPE_ALIASES == PYTHON_ALIASES_AT_S1
```

Cheap, specific, catches a real drift mode. Pattern: when two modules must share state by design (not by import), assert the sync in a test.

### Cross-layer in-process rendering tests (not subprocess)

Per `core/CLAUDE.md`: *"CLI, JSON, and MCP all flow through the same `format_diagnostic()` pipeline — the only place rendering happens."* This means testing the full chain (`validate_ir → to_diagnostics → format_diagnostic`) in-process covers every consumer. ~3ms vs ~500ms subprocess, identical coverage for everything except the CLI entry wiring (stable contract). **Subprocess tests remain correct for progress-streaming / logger-interleaving / pipe-routing scenarios** per the user memory on CliRunner — but rendering pipeline tests should be in-process.

### List-based path checks > substring checks for jsonschema routing

```python
# GOOD — precise, covers both enum and type validator errors at the right path
is_type_vocab_path = (
    len(path_list) >= 3
    and path_list[0] in ("inputs", "outputs")
    and path_list[-1] == "type"
)

# BAD — substring check on deque repr. Matches nodes[N].type accidentally;
# requires validator-name guard to compensate.
if error.validator == "enum" and "type" in str(error.absolute_path):
```

## Anti-Patterns to Avoid

**Menu-of-options error suggestions.** If you find yourself writing `"Two options: 1. Do X. 2. Do Y."` — stop. Pick the canonical answer and emit only that. Agents pattern-match one option and ignore the other; you've wasted the other option's bytes and introduced ambiguity.

**Invisible source rewriting of user code.** Poll P1 rejected design A (lowercase `any` silently rewritten to `Any` in code blocks) forcefully. Once a tool starts transforming user source, every debugging session becomes harder because the code shown ≠ the code run. **Namespace injection is fine** (Jupyter-style pre-bound names); **text rewriting is not**.

**Trusting Python runtime claims without verification.** The plan's `list[any]` NameError safety-net claim was false. Always verify Python edge-case claims against an actual interpreter before documenting them as invariants.

**Substring path-checking for precise validation routing.** `"type" in path_str` matched `nodes[N].type` by accident; it was only correct because `error.validator == "enum"` guarded it. List-based checks (`path_list[-1] == "type"`) are both shorter and correct.

## Breaking Changes

**S1 vocabulary**: `type: str` / `int` / `float` / `bool` / `dict` / `list` are now hard errors at `validate_ir`. Migration is mechanical sed to canonical names.

**`object` semantic shift**: documented as dict-only (though runtime enforcement is deferred to Task 120). Workflows using `type: object` as a wildcard should migrate to `type: any`.

**Parameterized generics**: `type: list[str]` / `dict[str, int]` rejected at parse time. Use bare `array` / `object`.

**`null` dropped**: use `type: any` for nullable inputs (union syntax not yet supported).

**Code-block annotation**: lowercase `x: any` is a hard error; use `x: Any` (auto-injected).

Saved workflows in `~/.pflow/workflows/` containing Python aliases will fail validation on next load or `--force` re-save. Manual migration; no tooling.

## Future Considerations

### Extension points for Task 120 (strict runtime enforcement)

- `TypeSpec.accepts(value)` — currently unused in production; designed as the strict-check entry point. Semantics: `integer` rejects `bool` (JSON Schema convention), `object` is dict-only, `any` returns True. Asymmetry with Python-lax `_TYPE_MAP` is documented.
- `TypeSpec.python_type()` — returns isinstance-compatible type(s). Tuples for `number` (int, float).
- `_coerce_to_object` in `param_coercion.py` currently lenient; Task 120's tightening point.

### Extension points for union syntax

- `TypeSpec.parse` currently rejects `null` with a "use `any`" hint and `A | B` as an unknown type. Union syntax lands here.
- `TYPE_COMPATIBILITY_MATRIX` already handles `"int|float"` via split-on-pipe in `is_type_compatible`.
- `_suggest_for_invalid_type` would need to recognize union-shaped offending values.

### Extension points for complex schemas

- The flat `{field: {type, description}}` YAML convention used by Claude Code `output_schema` is the natural shape. Agent-ux review noted the `llm` node uses the same YAML parsing path.
- Integration would recurse `TypeSpec.parse` into nested `properties` fields.

### Scope boundary that must be preserved

**Three vocabularies coexist intentionally.** A future agent tempted to unify S3 (registry Interface docstrings + Claude Code `output_schema`) must know:
- `_build_schema_prompt` in `claude_code.py` embeds the literal Python names (`str`, `int`, `dict`) into LLM prompts
- Registry Interface metadata is authored by node library writers as Python annotations
- `TYPE_COMPATIBILITY_MATRIX` bridges S1↔S3 and would need rethinking

## AI Agent Guidance

### Quick start for related tasks

**Task 120 (strict input type validation):**
1. Start at `src/pflow/core/types.py::TypeSpec.accepts` — already designed for this.
2. Plumbing point: `src/pflow/core/param_coercion.py::coerce_workflow_input` — currently lenient, needs a strict mode that calls `TypeSpec.accepts`.
3. Error path: produce `WorkflowValidationError` with structured context matching Task 154's pattern — populate `similar_names` / `available_fields` / `suggestions_list`.
4. Test template: cross-layer rendering test like `test_full_render_pipeline_for_type_vocabulary_error`.

**Union syntax at S1 (`A | B`):**
1. Extend `TypeSpec.parse` — currently raises on `|` via the unknown-type branch.
2. Update `TYPE_COMPATIBILITY_MATRIX` — already has a `split("|")` path, extend for canonical names.
3. Remove the "null deferred" branch; `string | null` becomes the canonical nullable spelling.

**Complex nested schemas (properties):**
1. Reuse the `yaml output_schema` convention from `nodes/claude/claude_code.py::_validate_schema`.
2. Extend `TypeSpec.parse` to accept nested dicts.
3. IR schema gains `properties` sibling field on input/output declarations.

### Common pitfalls

- **Do NOT remove `_TYPE_ALIASES` in `param_coercion.py`.** Reachable via template-referenced sub-workflows that skip `validate_ir`. Drift-guard test prevents accidental desync from `PYTHON_ALIASES_AT_S1` but doesn't prevent outright removal.
- **Do NOT change `suggestions_list` to complement `suggestion` in `SchemaValidationError.to_diagnostics`.** The preemption is deliberate and catches multi-suggestion cases. Changing it reintroduces the parameterized-generic prose loss bug.
- **Do NOT unify S1 / S2 / S3 vocabularies.** The three-dialect coexistence is architectural; `_build_schema_prompt` LLM prompt construction depends on the Python names.
- **Do NOT tighten runtime coercion outside of Task 120.** Lenient `_coerce_to_object` accepting non-dict values is a deliberate scope boundary; Task 120 owns this.
- **Do NOT claim `any`-in-generics (`list[any]`) produces a NameError safety net.** Python's `any` is a valid builtin; `list[any]` evaluates cleanly. This is a documented limitation, not a runtime catch.
- **Do NOT use substring path-checking (`"X" in path_str`) for precise jsonschema error routing.** Use list-based checks via `list(error.absolute_path)`.
- **Do NOT emit menu-of-options error suggestions.** One canonical fix per case.

### Test-first recommendations for related work

- **Write the cross-layer rendering test first.** Per-layer unit tests miss `suggestions_list` preemption bugs and context-threading regressions. See `test_full_render_pipeline_for_type_vocabulary_error` as the template.
- **If you touch `SchemaValidationError`**: run `tests/test_core/test_ir_schema.py::TestInputTypeAliases` — that class pins every vocabulary contract.
- **If you touch `param_coercion.py`**: run `tests/test_core/test_param_coercion.py::TestTypeAliasesSyncWithCanonicalSource` and `tests/test_runtime/test_prepare_inputs_coercion.py::test_type_aliases_work_as_defense_in_depth` — these protect the bypass path.
- **If you touch `diagnostic_render.py::_format_available_fields_block`**: the truncation policy (show-all when ≤10) is poll-validated agent-UX. `test_full_render_pipeline_for_type_vocabulary_error` pins it.

---

*Generated from implementation context of Task 154. Progress log at `.taskmaster/tasks/task_154/implementation/progress-log.md` carries the full reasoning trail — 7 sections covering planning journey, reviewer findings that reshaped the plan, non-obvious implementer traps, implementation notes, verification strategy, methodology notes, and append-only live log across 4 implementation passes.*
