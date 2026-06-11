# Task 170: One Template Language — consolidate `${…}` into core/templates

## Description

Give the `${…}` template language a single owning module: one parser producing a typed
structure, one value walk, one home for the semantic judgment calls — with the validator
consuming the same parsed segments and rules instead of re-implementing them. This closes the
codebase's worst drift seam (validation-time vs runtime template behavior) and makes the
language one small, typed thing an agent can load whole.

## Status

not started

## Priority

high

## Problem

The template language has no owner. An architecture review (2026-06-11) found, with file:line
evidence:

- **7 regex families** parse `${…}` (canonical 3-role contract in `TemplateResolver`, plus
  uncontracted copies in `markdown_parser._CACHE_TEMPLATE_RE`, `graph/scope.py` — which accepts
  digit-leading roots the canonical grammar rejects — and ad-hoc one-liners).
- **6+ independent path walkers** for `a.b[0].c` — including two near-identical loops *inside*
  `TemplateResolver` itself (`resolve_value` vs `variable_exists`/`_traverse_path_part`), which
  can disagree (exists=True, resolve=None) and which `resolve_coalesce` AND
  `_resolve_complex_match` each call twice per operand.
- **4 encodings of the type rules** (the str-auto-parses-as-JSON judgment is re-stated in ≥4
  places; the validator's compatibility matrix documents itself as a hand-maintained mirror of
  runtime coercion).
- **13 files split `??` operands themselves.**
- The static validator is a hand-written model of the resolver, held in sync only by comments:
  **≥7 shipped drift bugs** (#441 coalesce field-check, #460 generic-type drift, #266 `$${var}`
  escape, d5a1af8c batch dotted refs, 6b7faf8f batch-on-workflow, 8535ed9b malformed false
  positive, plus the historical save-vs-compile drift) and **no parity test** (verified: no test
  file exercises both `validate_workflow_templates` and resolver resolution).
- **Layering is inverted**: 16 `core/` files import `pflow.runtime.template_resolver` (core must
  not import runtime), two of them via private attributes.
- The strict/permissive grammar split is partly an artifact: `${a[${i}].x}` is valid language
  the strict regex can't express, so runtime grew a string-rewrite pre-pass
  (`resolve_nested_index_templates`) and validation grew a second grammar
  (`_PERMISSIVE_PATTERN`).

The failure mode is silent: a forgotten consumer is a regex that quietly stops matching, so
validation silently skips templates — the shape of several of the bugs above.

## Solution

One module, `core/templates` (single file initially; split only if it grows), owning:

- **One error-tolerant parse** (regex-*tokenized* internally — reuse the battle-tested
  patterns, no hand-written scanner) producing an immutable typed structure: template segments
  (text / expression), expressions with operands (reference or literal), references with path
  segments (field / index / **dynamic index** — first-class, retiring both the rewrite pre-pass
  and the permissive second grammar), parse issues as data (not exceptions), and source spans
  (needed by cache-block chunking). Parse results are cached (`lru_cache`) — engine, planner,
  and validator share one parse with no invalidation story.
- **One value walk** (`lookup`/`resolve`): JSON auto-parse, `??` fall-through, index bounds,
  stringification — the single home for resolution semantics.
- **One home for the judgment calls** that drifted historically: stringification rules,
  traversability ("which types may be walked into"), type compatibility (the #460 class).
- **String-in/string-out helpers stay public permanently** (`extract_root_node_id`-style),
  backed by `parse()` internally — the lasting interface for the long tail of callers whose
  question is genuinely string-shaped. The long tail (e.g. `prompt_cache_analysis` one-liners)
  is NOT migrated to the AST.

The **validator keeps its own direct structure-walk** over the same parsed segments, consuming
the shared rules — deliberately NOT unified with the runtime walk behind an abstraction (see
ADR-0006). Validator policy (namespacing, batch index-blocking, coalesce field-check exemption,
diagnostic wording) stays in `template_validation/` — the module hides the language, not its
callers' judgments.

Drift becomes loud through three meta-tests (pflow's native mechanism):
1. **Parity drift tests** — fixed table corpus + the historical bugs as named fixtures
   (mirrors `test_plan_drift.py`: "fix the divergence, never the test").
2. **Grammar-uniqueness AST-scan** — no regex containing `\$\{` compiled outside
   `core/templates` (same shape as the litellm seam test).
3. **Core-does-not-import-runtime** pin once the module moves (closes the 16-file inversion).

### Phases (each a legitimate resting point, in this order)

1. **Parity drift tests first** — land the corpus + historical fixtures + grammar-coherence
   assertions against the *current* code, before any production change. Pure bug-stopping at
   zero risk; everything after executes under its protection.
2. **One internal walk** — merge the duplicated traversal loops inside `TemplateResolver`
   behind a single found/value walk; coalesce and complex-match resolution stop walking twice.
3. **Relocate to `core/`** — module moves, `runtime/template_resolver.py` becomes a shim,
   16 core importers point the right way, layering meta-test lands.
4. **Typed parse + drift-site migration** — the AST and `parse()`; migrate the sites where
   drift actually lived: validation passes, `data_flow` operand loop, engine resolution,
   `template_errors` classification, cache-block chunking, `graph/scope.py`.
5. **Sweep and seal** — delete `split_template_path`, `_PERMISSIVE_PATTERN` machinery, the
   rewrite pre-pass, ad-hoc regex copies and the shim's dead halves; grammar-uniqueness
   AST-scan lands. Net LOC returns to ~baseline or below.

## Design Decisions

- **Separate walks, shared AST + rules — no World/port abstraction**: a fully worked
  ports-and-adapters design (ValueWorld/StructureWorld) was rejected via the deletion test;
  top-tier analogues (CEL checker/interpreter, actionlint, JMESPath) share the AST and
  conformance tests, not the walk. Recorded as **ADR-0006** — do not re-litigate.
- **Regex-tokenized parser, not a hand scanner**: the scanner was the riskiest part of the
  AST design for zero interface payoff; the existing regexes become the tokenizer.
- **Table corpus, not a property-test generator**: generation rejected as premature — the
  table covers every observed failure; build a generator only if a drift escapes the table.
- **Dynamic index as an AST node**: earns its place by *deleting* two existing hacks (rewrite
  pre-pass + second grammar) — not by hypothetical future syntax.
- **Speculative vocabulary trimmed**: an AST node or issue-kind exists only when a consumer
  branches on it (e.g. no `Escaped` node if `Text` suffices; issue kinds defined by actual
  consumers during implementation).
- **Partial migration is the end state, not a compromise**: drift sites move to the AST;
  string helpers remain the permanent public interface for everyone else.
- **Phases, not parallel work**: order is load-bearing (tests before production change);
  each phase leaves the codebase strictly better and is independently stoppable.
- **Module home `core/`**: forced by the 16-file inversion; precedent `core/trace_io.py`.
- Vocabulary fixed in `context/CONTEXT.md`: **Template, Reference, Coalesce, Operand**.

## Dependencies

None.

## Requirements

### Behavior freeze (no user-facing change anywhere in this task)
- JSON auto-parse on traversal: containers only; numeric strings stay strings (the
  Discord-snowflake rule).
- Simple templates preserve type; complex templates stringify via the exact
  `_convert_to_string` rules.
- `$$` escape: prevents resolution, does NOT strip the extra `$` (frozen partial behavior).
- `??` falls through on absent root OR absent field (#441); a literal operand always resolves
  and ends the chain; literal-first matching (keyword literals win over same-spelled
  identifiers).
- Literal grammar constraints: no leading-zero numbers, no `??` inside strings, composite
  literals excluded — must remain exactly aligned with what `try_parse_json` +
  operand-splitting can handle at runtime.
- Hyphens allowed in identifiers; nested bracket index (`${a[${i}].x}`) resolves to the same
  observable outcomes as today's pre-pass (non-int or unresolved inner → whole ref unresolved,
  template text unchanged).
- Unresolved templates remain textually unchanged in output; strict-mode error policy stays
  with the engine.
- Complex-template interpolation: write a characterization test for today's sequential
  `str.replace` behavior (resolved values containing `${…}`-like text) BEFORE changing
  interpolation; any diff is a frozen-behavior decision, not a silent improvement.
- `output_resolver._is_all_absent_coalesce` keeps its deliberately stricter semantics —
  consumes parsed operands but is NOT absorbed.

### Parity (the point of the task)
- One-way soundness: for templates over declared structure with conforming data, runtime
  resolves ⟹ validator emitted no ERROR (the validator may under-check, never over-reject).
- The six historical drift bugs exist as named regression fixtures citing issue/commit.
- Grammar coherence: every strictly-valid template is also discoverable by the loose/
  validation views; every literal-grammar match round-trips `try_parse_json`.
- Existence and resolution cannot disagree (single walk: found ⟺ value produced).

### Structure
- Exactly one place in `src/` compiles a `${…}` grammar (mechanically enforced).
- `core/` no longer imports `runtime` for template functionality; no private-attribute
  reaches across the module's interface remain.
- Validation passes, `data_flow`, engine resolution, error classification, and cache chunking
  consume parsed segments/operands — no `str.split(".")`-style re-segmentation at those sites.
- The module is importable without `litellm` entering `sys.modules` (repo invariant).
- Parse is pure, total (never raises on user input), and cached; malformedness is data.

### Out of scope
- Any new template syntax or semantics.
- Unifying the validator's structure walk with the value walk (ADR-0006).
- Migrating the string-helper long tail to the AST.
- The type-compatibility matrix's *content* (only its home consolidates).

## Implementation Notes

- Phase 4 is roughly half the total effort; the validation-pass migration
  (`path_validation.py` is the heaviest consumer) dominates it. Whole task ≈ a focused week;
  phases 1–3 ≈ two days and capture most of the bug value.
- Net size: ~400–500 LOC module replacing ~450 LOC of scattered patterns/splitters/duplicate
  walks — approximately LOC-neutral after phase 5.
- Phase 3 prep: grep for importlib string paths, monkeypatch tuples, and caplog logger names
  before moving symbols (Task 160's silent-failure lesson).
- Known behavior deltas to test-gate in phase 5: `_CACHE_TEMPLATE_RE` lacks the `$$`
  lookbehind the canonical extractor has; `graph/scope.py` accepts digit-leading roots
  (validator-rejected input anyway). Each replacement needs a characterization test and an
  explicit decision.
- `_PERMISSIVE_PATTERN` has no `$$`-escape handling — the phase-1 corpus will force an
  explicit decision (carve-out vs documented permissiveness).
- Stale docs to fix in passing: `template_validation/CLAUDE.md` claims `compile_validation.py`
  imports `validate_workflow_templates` (false — template passes run only in
  `WorkflowValidator`); update the consumer table when touching the package.
- The two "private reaches" (`data_flow.py:33`, `cache_overlap.py:32`) import the attribute
  (auto-sync) — hygiene, not a live drift risk; fix by exporting, don't treat as urgent.

## Verification

- `make test` and `make check` green after every phase (each phase is shippable).
- Phase 1's drift-test file passes against unmodified production code (proves the corpus
  encodes current behavior, not aspirations).
- Phase 2 gated by a differential test (old vs new walk over a path×context corpus), deleted
  with the second loop.
- All Requirements→Parity properties hold continuously from phase 1 onward; all
  Requirements→Structure properties hold by end of phase 5, each pinned by a meta-test.
- The existing resolver/validation suites pass unmodified through phases 2–4 (they are the
  behavior-freeze harness; the markdown/scope characterization deltas in phase 5 are the only
  sanctioned test changes, each with an explicit decision recorded).

## References

- `context/adr/0006-template-language-no-shared-walk.md` — the decided shape + rejected
  alternatives (created with this task)
- `context/CONTEXT.md` — Template / Reference / Coalesce / Operand vocabulary
- `src/pflow/runtime/template_resolver.py` — current canonical grammar + the duplicated walk
- `src/pflow/runtime/template_validation/` (+ its CLAUDE.md: 3-regex-role contract, pass map)
- `src/pflow/core/workflow/data_flow.py` (operand loop ~:779; `_PFLOW_VAR_RE` :33)
- `src/pflow/core/markdown_parser.py` :166, `src/pflow/core/workflow/graph/scope.py` :11-13,
  `src/pflow/runtime/engine/template_resolution.py`, `template_errors.py` — drift-site
  consumers for phase 4
- `tests/test_execution/test_plan_drift.py` — the in-repo precedent for seam-pinning drift
  tests; `tests/test_core/test_litellm_runtime.py` — precedent for the AST-scan meta-test
- Drift rap sheet: #441, #460 (PR #461), #266, commits d5a1af8c, 6b7faf8f, 8535ed9b
