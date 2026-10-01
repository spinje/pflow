# Task 170: One Template Language — consolidate `${…}` into core/templates

## Description

Give the `${…}` template language a single owning module: one parser producing a typed
structure, one value walk, one home for the semantic judgment calls — with the validator
consuming the same parsed segments and rules instead of re-implementing them. This closes the
codebase's worst drift seam (validation-time vs runtime template behavior) and makes the
language one small, typed thing an agent can load whole.

## Status

done

## Completed

2026-10-01

## Priority

high

## Roadmap

next

## Problem

_Refreshed 2026-09-28 against main `871ae780` (session-08 spec battery: two searchers + six
review lenses, most claims executed). Counts below are measured, not inherited._

The template language has no owner:

- **12 compiled regexes in 8 files parse `${…}`**: 5 in `TemplateResolver`
  (`TEMPLATE_PATTERN` :60, `_INTERPOLATION_PATTERN` :64, `TEMPLATE_EXTRACT_PATTERN` :70,
  `SIMPLE_TEMPLATE_PATTERN` :75, `_BRACKET_INDEX_PATTERN` :81), 2 in
  `template_validation/validator.py` (`_PERMISSIVE_PATTERN` :51 — the second grammar — and
  `_TEMPLATE_OPEN` :53), `type_validation.py:29`, `markdown_parser.py:167`
  (`_CACHE_TEMPLATE_RE`, no `$$` lookbehind), `graph/scope.py:13`, `yaml_utils.py:43` (a
  deliberate *lexical mask*, see Structure), `renderers/mermaid.py:790`. Plus the grammar
  compiled **by symbol** with no `\$\{` literal: `data_flow.py:34`, `cache_overlap.py:32`,
  `graph/scope.py:56`, `template_validation/validator.py:50,:652` (the private reaches).
- **Path walkers**: 4 over runtime values (`resolve_value` :565, `variable_exists` :536 via
  `_traverse_path_part` :491 — two near-identical loops inside `TemplateResolver` that
  `resolve_coalesce` :366-367, `_resolve_inline_expr` :789/:794 and the simple path :731-732
  each run twice per operand; `trace_report._check_path_against_upstream` :540;
  `engine._diagnose_carry_ref` :130), 4 over validation structures (`path_validation`,
  `type_checker.py:141`, `type_validation._traverse_to_structure` :942,
  `batch_item_validation.py:150/:244`), and ≥7 bare segmenters (`str.split(".")`).
- **≥4 encodings of the type rules** — and a live disagreement: `type_checker.py:223/:248`
  leaves `str` out of the traversable set while `path_validation.py:188-190/:284/:328` walks
  into it via JSON auto-parse.
- **12 files repeat the split-operands + skip-literals loop** around `split_coalesce_operands`.
- **The static validator is a hand-written model of the resolver**, held in sync by comments:
  drift bugs shipped as #441, #460 (PR #461), #266, d5a1af8c, 6b7faf8f, 8535ed9b/4516cd72,
  and 2026-09-28's #620 (PR #632: `_PERMISSIVE_PATTERN` lacked the escape lookbehind) and #630.
  **No parity corpus exists** (`tests/test_runtime/test_template_escape.py` is end-to-end for one
  feature only).
- **≥6 places decide "unresolved" by comparing text** instead of asking the resolver:
  `engine/template_resolution.py:237-250` (#630), `:295-298` (`inject_none_for_optional_inputs`),
  `engine.py:245` (loop carried inputs), `engine.py:393-401` (`_resolve_template_string`, feeds
  the batch warm-up `system`), `output_resolver.py:42/:161`, `batch_executor.py:122`,
  `prompt_cache.py:174/:249`.
- **Layering is inverted**: 11 `core/` files import `pflow.runtime.template_resolver` directly,
  4 more through `prompt_cache_analysis/context.py:47-54`, and `core/workflow/validator.py:446`
  imports `runtime.template_validation` (sanctioned, see Structure).
- **The strict/permissive grammar split is partly an artifact**: `${a[${i}].x}` is valid language
  the strict regex can't express, so runtime grew a string-rewrite pre-pass
  (`resolve_nested_index_templates` :107-162) and validation grew the permissive grammar.

The failure mode is silent, in **both directions**, and the battery executed both:

- *Validation accepts what the runtime never resolves.* `${c.result.0}`, `${data.result.}`,
  `${data..result.x}`, `${src.stdout.0}`: the permissive grammar accepts them, the strict grammar
  rejects them, `has_templates` is False, `split_params` (`template_resolution.py:113`) routes
  them as **static** params, and the node receives the literal text with exit 0.
  `${lsit[${__index__}].x ?? "default"}` hides a root typo — every item silently gets
  `"default"`. `batch.items: ["${data.result[0]", …]` is never malformed-checked (the pass walks
  `params` only, `validator.py:680/:736`). A `## Cache` field typo (`${plan.stdot}`) drops the
  chunk from the system prompt with no error (`prompt_cache.py:164-175`).
- *Dynamic-index templates return rewritten text.* `${a[${i}].x}` with an out-of-range, non-int,
  `"1\n"`, `-1`, `None` or `True` inner value ships `'${a[5].x}'`-style literals unflagged
  (strict mode compares variable-name sets of original vs rewritten text); with `??` the
  fallback never fires; `${r[${__index__}]}` on a dict param yields a JSON **string** where
  `${r[0]}` yields a dict (`is_simple_template` runs on the original text,
  `template_resolution.py:190`, gating auto-parse :352-360, type validation :368, inline-object
  parse `template_resolver.py:866`); declared outputs write the literal (`output_resolver.py:161`);
  `Optional` code inputs get the literal instead of `None` (:297); `classify_unresolved_references`
  names the *inner* variable as a non-executed node (`template_errors.py:137`).

## Solution

One module, `core/templates` (single file initially; split only if it grows), owning:

- **One error-tolerant parse** (regex-*tokenized* internally — reuse the battle-tested
  patterns, no hand-written scanner) producing an **immutable** typed structure: template
  segments (text / expression), expressions with operands (reference or literal), references
  with path segments (field / index / **dynamic index** — first-class, retiring both the rewrite
  pre-pass and the permissive second grammar), parse issues as data (not exceptions), and
  source spans (consumed by cache-block chunking `markdown_parser.py:1737-1745`, Task 167's
  editor tokens, Task 46's export). **Every unescaped `${` becomes an Expression or an Issue —
  never Text**; "no `Escaped` node if `Text` suffices" applies to escapes only. Parse is pure,
  total, **context-free** (no per-param mode — the deferred #621 tolerance is *policy over
  Issues*, never a parse flag), and cached with a **bounded** `lru_cache` keyed on **author
  template text only** — helpers that run on resolved runtime values (cost analysis
  `row_builder.py:928`, `token_estimation.py:414/:448/:452`, `sub_workflow_walker.py:537`,
  `engine.py:400`) never route through the cache.
- **One value walk** (`lookup`/`resolve`) that also **returns the set of references it could
  not resolve** — the single judge of "unresolved" for the engine's strict check
  (`template_resolution.py:237-250`, #630), `inject_none_for_optional_inputs` (:295-301), the
  loop-carry check (`engine.py:245`), `_resolve_template_string` (:393-401), `output_resolver`,
  `batch_executor.py:122`, `prompt_cache.py:174/:249`, and `classify_unresolved_references`
  (`template_errors.py:126-161`) — one set feeds check and diagnostic alike. A dynamic-index
  reference whose outer path fails for *any* reason is in the set. The set is engine-internal:
  **no new trace field** (`trace_report.py:526` keeps its heuristic; the trace format is
  untouched). JSON auto-parse, `??` fall-through, index bounds and stringification live here.
  Found ⟺ the walk reached a value (possibly `None`) — `success_formatter.py:226-231` and
  `workflow_output.py:191` rely on exists=True/value=None.
- **One home for the judgment calls** that drifted historically: stringification (excluding
  `prompt_cache.deterministic_serialize` :107-124, which is deliberately different and pinned by
  `test_prompt_cache.py:38-58`), traversability ("which types may be walked into" — resolves the
  `type_checker`/`path_validation` disagreement above), type compatibility (the #460 class; the
  matrix's *home* is the planner's call — `core/types.py` already holds `outer_base_type` and
  Tasks 112/120 point at `type_checker.py` for non-template checks; update their pointers
  either way).
- **One validator-side operand classifier** (field-checkable / root-only / skip) consumed by
  every validation pass — today Pass 5, Pass 8, type inference, `data_flow`, the cache root
  check and the output-source root check each decide for themselves, and Pass 5 vs Pass 8
  already disagree on `??` operands (#441 is pinned for Pass 5 only). Validator *policy*
  (namespacing, batch index-blocking, coalesce field-check exemption, diagnostic wording) stays
  in `template_validation/` — the module hides the language, not its callers' judgments.
- **String-in/string-out helpers stay public permanently**, backed by `parse()` internally.
  The permanent interface is the set callers use today: `resolve_template`, `resolve_nested`,
  `resolve_coalesce`, `resolve_value`/`variable_exists` (the walk pair — CLI `-o`,
  `read-fields`, MCP `field_service.py:74`, formatters, `loop_control`), `has_templates`,
  `extract_variables`, `is_simple_template`, `extract_simple_template_var`,
  `is_coalesce_expression`, `is_literal_operand`, `split_coalesce_operands`,
  `extract_first_field_segment`, `extract_root_node_id`, plus a **span-yielding finditer-style
  helper** (12 files use compiled patterns for match spans today — either the patterns stay
  public or this helper exists). **User-typed paths are not templates**: `-o`, `read-fields` and
  MCP `read_fields` resolve `result.@type`, `result.dc:title`, `result.my key`, `result.0` today
  — the walk pair keeps a raw-string path mode for them.

The **validator keeps its own direct structure-walk** over the same parsed segments, consuming
the shared rules — deliberately NOT unified with the runtime walk behind an abstraction (see
ADR-0006).

Drift becomes loud through three meta-tests (pflow's native mechanism):
1. **Parity drift tests** — fixed table corpus + the historical bugs as named fixtures
   (mirrors `test_plan_drift.py`: "fix the divergence, never the test" from phase 2 on; in
   phase 1 known divergences are `xfail(strict=True)` rows citing an issue).
2. **Grammar-uniqueness AST-scan** — no regex containing `\$\{` compiled outside
   `core/templates` (same shape as `test_litellm_runtime.py:926`), **with a named allowlist and
   a reason per entry** (`mcp/auth_utils.py:14` — a different language, MCP-config env
   expansion; `core/yaml_utils.py:40-44` — a lexical YAML mask that deliberately allows one
   nested `{}` level and no `$$` handling, own guard in `test_yaml_shielding_hygiene.py`;
   `core/ir_schema.py` jsonschema `pattern` strings) **plus a second rule**: no `re.*` call
   outside the module whose pattern references a `core.templates` attribute (the by-symbol
   copies above are the historical drift vector). Scope is Python under `src/`; the web UI's
   TypeScript copies (`web/src/graph/scan.ts:55-62`, `sourceDecorate.ts:32`, `batchItems.ts:26`,
   `format.ts:9`) are a known out-of-scope mirror — see Phases.
3. **Core-does-not-import-the-resolver pin** — "no module under `core/` imports
   `pflow.runtime.template_resolver` or its shim" (in `tests/test_import_hygiene.py` next to
   `test_runtime_does_not_import_ui`). Not "core imports nothing from runtime": `core/` imports
   nine non-template runtime symbols (`prompt_cache.py:163`, `trace_report.py:30`, …) and
   `core/workflow/validator.py:446` lazily imports `runtime.template_validation` — both
   sanctioned and out of scope.

### Phases (each a legitimate resting point, in this order)

1. **Parity drift tests first** — land the corpus + historical fixtures + grammar-coherence
   assertions against the *current* code, before any production change. Corpus rows are
   `(surface, template, declared metadata, runtime context, strict|permissive)`; the runtime
   side is `engine.resolve_templates` (it includes `split_params` routing and the strict check —
   bare `resolve_template` cannot show the static-routing class); surfaces: node params
   (nested dicts/lists), `batch.items` (string and inline list) and alias params, loop
   `while/until/max_iterations/carry`, output `source:` in all three syntaxes, `## Cache`
   vars, sub-workflow `inputs:`/`workflow:`. The validator entry point is
   `WorkflowValidator` as `runner.validate` calls it (with `_pflow_workflow_file`) — #643
   records the save-path asymmetry until fixed. **Known divergences on main are recorded as
   `xfail(strict=True)` rows, each citing its issue**: #262 (`${arr[0]}` on a list input
   rejected; `split_template_path` never splits `[`), Pass 8 rejecting `${item.maybe ?? "none"}`
   on batch items, `${a ?? "${b}"}` reported as a malformed literal, `_LITERAL_PATTERN`
   accepting `"\q"`/`"\u12"`/raw-tab literals that `try_parse_json` rejects, and every
   Sanctioned delta below. Phase 1 also adds `WorkflowRunner` characterization tests for the
   dynamic-index consumers listed in Problem (shape, strict check, declared outputs, Optional
   inputs, diagnostics, `??`), so phase 4's flips are measured, not discovered.
2. **One internal walk + the unresolved set** — merge the duplicated traversal loops inside
   `TemplateResolver` behind a single found/value walk; coalesce and inline-expression
   resolution stop walking twice; the walk returns its unresolved references and the engine's
   strict check consumes them (#630 — the one Sanctioned delta that lands here; its xfail rows
   flip to pass). `tests/test_runtime/test_node_wrapper.py:195-222` (tests the re-scan directly)
   is a sanctioned test change.
3. **Relocate to `core/`** — module moves, `runtime/template_resolver.py` becomes a shim, the
   15 core dependents point the right way, the layering pin lands. Instruction files that name
   the old path are updated in this phase (`.claude/agents/pflow-codebase-searcher.md:124`, the
   five `review-*.md` lenses, `src/pflow/core/CLAUDE.md:156`, `runtime/CLAUDE.md`,
   `template_validation/CLAUDE.md` — whose "three patterns, do not unify" rule is superseded:
   three *views* over one parse; rewrite the table) — the shim keeps the old path alive, so
   `test_agent_references.py` cannot catch the staleness. Prep: grep importlib string paths,
   monkeypatch tuples (`test_cache_analysis_token_estimation.py:508/:528`,
   `test_cache_analysis_analyze.py:5930` patch the class object — survive a re-exporting shim)
   and caplog logger names.
4. **Typed parse + drift-site migration** — the AST and `parse()`; migrate the sites where
   drift actually lived: validation passes (`path_validation.py` is the heaviest consumer; the
   operand classifier lands here), `data_flow` operand loop (:787-796), engine resolution
   (`template_resolution.py`, `engine.py:150-156` — the segment split inside
  `_diagnose_carry_ref`, `engine.py:245` carry check,
   `_resolve_template_string` :393-401), `template_errors` classification (:137, :320),
   `output_resolver` (:41-53 wraps the whole source; the prose-in-`source:` drift is fixed by
   Sanctioned delta 7), `batch_executor.resolve_batch_items` :108-131, `loop_control` :131-153 (own
   resolution path, no pre-pass), dry-run's per-item child inputs `execution/plan.py:1547`
   (bypasses `resolve_templates`) and `:2037`, `core/workflow/validator.py:1733`, cache-block
   chunking (`markdown_parser.py:1737-1745` — chunk names are the RAW source text between `${`
   and `}` (:1740-1744, invariant :1779-1790) and `prompt_cache:` lists refer to them by that
   name: slice from spans, never re-render from the AST), the second interpolator
   `prompt_cache._resolve_static_prefix_for_cache` :224-256 (never unescapes; `llm.py:726`),
   `graph/scope.py` — **and `web/src/graph/scan.ts` in the same step as `scope.py`** (its
   header says it mirrors scope's walk; the accepted `${data[0].field}` → `("data","field")`
   change would otherwise desync the canvas read-scan from the Python-built edges). The
   Sanctioned deltas for the dynamic index, the grammar class and the cache-block escape land
   here, each flipping its phase-1 xfail row.
5. **Sweep and seal** — delete `split_template_path` (with `TestSplitTemplatePath` in
   `test_nested_templates.py:70-129` and the export in `template_validation/__init__.py`),
   `_PERMISSIVE_PATTERN`, `_TEMPLATE_OPEN`, the rewrite pre-pass + `_BRACKET_INDEX_PATTERN`,
   `_INTERPOLATION_PATTERN`, ad-hoc regex copies and the shim's dead halves; the
   grammar-uniqueness scan with its allowlist lands; `contains_unresolved_template` goes only
   once no consumer (the carry check) depends on it. Net LOC returns to ~baseline or below.

Roadmap value note: bug value arrives by phase 3; the **roadmap** value — unblocking the
#621/#550 language ruling and Task 118 — arrives only at phase 5. Stopping at phase 3 keeps
them blocked; say so at any park.

## Design Decisions

- **Separate walks, shared AST + rules — no World/port abstraction**: a fully worked
  ports-and-adapters design (ValueWorld/StructureWorld) was rejected via the deletion test;
  top-tier analogues (CEL checker/interpreter, actionlint, JMESPath) share the AST and
  conformance tests, not the walk. Recorded as **ADR-0006** (amended 2026-09-28 with the
  allowlist policy, the operand classifier and the converse parity property) — do not
  re-litigate.
- **Regex-tokenized parser, not a hand scanner**: the scanner was the riskiest part of the
  AST design for zero interface payoff; the existing regexes become the tokenizer.
- **Table corpus, not a property-test generator**: generation rejected as premature — the
  table covers every observed failure; build a generator only if a drift escapes the table.
  Consider a data-file corpus so the TypeScript mirror and Task 167 can consume it.
- **Dynamic index as an AST node**: earns its place by *deleting* two existing hacks (rewrite
  pre-pass + second grammar) — not by hypothetical future syntax.
- **Speculative vocabulary trimmed**: an AST node or issue-kind exists only when a consumer
  branches on it (no `Escaped` node if `Text` suffices for escapes; issue kinds defined by
  actual consumers during implementation) — but an unescaped `${` is never Text (Solution).
- **Partial migration is the end state, not a compromise**: drift sites move to the AST;
  string helpers remain the permanent public interface for everyone else.
- **Phases, not parallel work**: order is load-bearing (tests before production change);
  each phase leaves the codebase strictly better and is independently stoppable.
- **Module home `core/`**: forced by the layering inversion; precedent `core/trace_io.py`.
- Vocabulary fixed in `context/CONTEXT.md`: **Template, Reference, Coalesce, Operand** (its
  "one parse serves both surfaces" line describes this task's end state).

### Decision ledger (rulings that gate the build — DECIDED 2026-09-28, session-08)

- **Strict grammar wins.** Templates the permissive grammar accepts but the strict grammar
  rejects (digit-leading, hyphen-leading or empty field segments; a non-variable inner index
  `${arr[${idx ?? 0}]}`; root typos hidden under a dynamic index + `??`) become validator
  ERRORS — never static params. Rationale: no users, tightening is free, and typo detection is
  the thing at risk.
- **A dynamic-index template is one Reference.** `${a[${i}].x}` is *simple* (type-preserving:
  a dict param gets a dict, not a JSON string) and any failure inside it — inner absent,
  non-int, out of range, outer path missing — makes the whole reference unresolved (strict
  mode errors; `??` falls through; Optional inputs get `None`; a non-coalesce unresolved
  declared output is an `OutputResolutionError`, skipped only for an all-absent `??` — a silent
  skip is the failure class this task ends; wording amended 2026-09-28, session-08). This is
  the task's deliberate user-visible delta set, recorded per consumer in the phase-1
  characterization tests. The `${results[str]}` partial rewrite pinned by
  `test_nested_templates.py:54-59` flips.
- **Escapes in `## Cache` blocks — option (a)**: `$${…}` in cache prose is honoured (the
  chunk regex skips it) and unescaped at render by ONE helper that both the hash site
  (`plan_node.py:199` `_render_cache_for_hash`) and the prepare site
  (`prompt_cache.py:416/:420` `build_cache_system_blocks`, also the prewarm path
  `batch_executor.py:643`) call; `CacheChunkIR.prose_before` stays escaped because graph
  build re-emits it as template text (`graph/build.py:682` `cached_prefix`). Today `$${topic}`
  with a declared `topic` validates and silently sends `$` + the value. Matches
  `docs/how-it-works/template-variables.mdx:328`. ADR-0015 records it, with the consequence
  (a `prompt_cache:` list naming an escaped span becomes an undeclared-chunk error; later
  chunks' `prose_before` and cache key change — none in-tree).
- **The escape consumes through the closing `}`**: `$${a[${i}]}` is literal `${a[${i}]}`; today
  the pre-pass rewrites inside the escape (`'${a[0]}'`) and `$${FOO:-${bar}}` resolves `${bar}`.
  Both flip; corpus rows record the before-values.
- **Task 118 waits** (moved to `then`, blocked-by recorded in its spec); the #621/#550 ruling is
  taken once after phase 5 (Out of scope).
- **The runtime-only `$node.x` output-source form is removed** (`output_resolver._normalize_source`
  drops its `$`-prefix branch) so validator and runtime agree by rejecting it. The validator always
  rejected it, so no saved workflow can use it; admitting it would add a surface nothing calls.
  DECIDED 2026-09-28 (session-08).
- **A `??` chain as a `## Cache` chunk var is rejected explicitly at parse.** Today the runtime
  silently drops such chunks (`_resolve_chunk_value` gates on the whole var's root) even when the
  validator accepts the dotted form — loud beats silent. Lift only if the runtime ever resolves
  chunk vars per operand. DECIDED 2026-09-28 (session-08).

## Dependencies

None. **Collision notes for the planner** (measured 2026-09-28): #520 (malformed templates in
batch data / dict keys) sits beside this task and collides on `validator.py`'s malformed pass —
build it on `parse()` after phase 4; #503 (strict-mode `ValueError` → `PflowError`) collides on
`engine/template_resolution.py` with the phase-2 #630 change — sequence it, never interleave;
#628 (sourceless outputs, lane B, in flight at spec time) touches the output-source validation
region — merge before phase 4; #643 (save vs `--validate-only` params) is the entry-point
asymmetry the corpus cites; Tasks 112/120 collide on the type-compatibility matrix rehome.

## Requirements

### Behavior freeze (true on main `871ae780`; everything else user-facing is unchanged)

- JSON auto-parse on traversal: containers only; numeric strings stay strings (the
  Discord-snowflake rule).
- Simple templates preserve type; complex templates stringify via the exact
  `_convert_to_string` rules. Complex interpolation is a **single left-to-right pass**
  (`_INTERPOLATION_PATTERN.sub`, :747-753, PR #632) — substituted values are never re-scanned;
  pinned by `TestEscapeAndSinglePassInterpolation` (`test_template_resolver.py:497`), keep it
  green.
- `$${…}` escape (PR #632): any content after it is literal and resolves to `${…}` (one `$`
  stripped); a bare `$$` is untouched; validator and resolver both skip it. Known exceptions
  today, each a Sanctioned delta or out of scope: the nested-bracket pre-pass rewrites inside an
  escape; cache prose (`_CACHE_TEMPLATE_RE`) and the static-prefix interpolator
  (`prompt_cache.py:253`) do not unescape.
- `??` falls through on absent root OR absent field (#441); a literal operand always resolves
  and ends the chain; literal-first matching (keyword literals win over same-spelled
  identifiers). `??` on a field that exists with value `null` returns `None`
  (`test_template_coalesce.py:299/:370`).
- Literal grammar constraints: no leading-zero numbers, no `??` inside strings, composite
  literals excluded — aligned with what `try_parse_json` + operand-splitting handle at runtime
  (the three known mismatches are xfail rows, phase 1).
- Hyphens allowed in identifiers. Multi-index `${m[0][1]}` is rejected by both layers.
- Dynamic index today (the **before** side of the Sanctioned delta; corpus records it):
  inner absent → text unchanged; inner int with the outer path missing → `'${a[0].x}'`
  (rewritten, unflagged); inner non-int → `'${a[abc].x}'` (rewritten, warning logged
  :152-156, unflagged); `${a[${i}].x ?? b}` with a non-int inner → fallback never tried,
  with an int inner and a missing outer path → the fallback fires (kept).
- Unresolved templates remain textually unchanged in output; the strict-vs-permissive **error
  policy** (raise vs record, `template_resolution.py:441-459`) stays with the engine (ADR-0014)
  — only the *detection* moves to the resolver's unresolved set.
- `output_resolver._is_all_absent_coalesce` keeps its deliberately stricter semantics —
  consumes parsed operands but is NOT absorbed. Output `source:` with surrounding prose
  interpolates (`source: prefix ${run.stdout}` → `prefix ok`), Sanctioned delta 7.
- Loop conditions: validator (`template_validation/validator.py:258-266`) and runtime (`loop_control.py:132`) share
  `extract_simple_template_var`; batch `continue` mode blocks dynamic indices
  (`path_validation.py:165-172`).

### Sanctioned deltas (the ONLY user-visible changes; each has a phase-1 xfail row and flips in
the named phase)

1. **#630** (phase 2): strict mode consumes the resolver's unresolved set; a correct `$${x}`
   beside `${x}`, and an upstream value containing literal `${b}` text, no longer error; a
   partially rewritten dynamic index now does.
2. **Strict grammar wins** (phase 4): the loose-accepted / strict-rejected shapes become
   validator ERRORs (ledger).
3. **Dynamic index is one Reference** (phase 4): shape, strict check, `??`, Optional inputs,
   declared outputs, diagnostics — per the ledger and the phase-1 characterization tests.
4. **Escape consumes through `}`** (phase 4): `$${a[${i}]}` and `$${FOO:-${bar}}` stay literal.
5. **Cache-block escape, option (a)** (phase 4/5): `$${` honoured in cache prose; hash and
   prepare stay byte-symmetric.
Validator-only corrections that the Parity section forces are sanctioned alongside the deltas
above and listed in the plan: over-rejections the runtime resolves (#262; a `[N]` index inside a
declared nested structure or on a `list`-typed output; Pass 8 field-checking `??` operands) flip to
accepted, and under-checks the runtime does not catch (coalesce roots in `batch.items`; an Issue on
any surface) flip to ERROR. A runtime-only syntax the validator always rejected (`$node.x` output
sources) is removed rather than admitted.

6. Phase-4 type passes may emit **new** validator errors on the *outer* dynamic-index reference
   (today `extract_variables('${a[${i}].x}') == {'i'}`; inner references were never validated —
   `data_flow.py:287` skips them; an input used only inside a dynamic index is reported "never
   used"). The validator walk recurses into DynamicIndex operands for root, forward-reference and
   unused-input accounting.
7. **Prose-wrapped output source interpolates** (phase 4a): the output normalizer wraps only a
   bare source in `${…}`; a source that already contains template syntax is resolved as written,
   so validator and runtime agree on the interpolated value. User ruling 2026-10-01; previously
   the runtime produced the recorded drift `'${prefix S}'`.

### Parity (the point of the task)

- One-way soundness: for templates over declared structure with conforming data, runtime
  resolves ⟹ validator emitted no ERROR (the validator may under-check, never over-reject).
- **Converse (the silent direction)**: validator emits no ERROR ⟹ every unescaped `${` that
  validation treats as a template is routed by the runtime and either resolves or lands in the
  unresolved set. Every Issue on every template-bearing surface (params, `batch.items`, loop
  fields, output `source:`, `## Cache` vars, sub-workflow `inputs:`) is a validator ERROR — the
  Issue-emitting pass covers the same surface set as reference extraction
  (`_node_template_value_sources`, `validator.py:764`).
- Under-checks are visible: a static check that defers on `has_templates` must key on
  "contains a Reference", not "needs rewriting" (after #632 the two differ for escape-only
  values: `core/workflow/validator.py:1008/:1047/:1155/:1262`, `template_validation/validator.py:1226`,
  `core/workflow/sub_workflow_resolver.py:93` currently skip agent params, both `output_schema`
  keys, the LLM `model` key, templated child refs and downstream type
  inference for them); any deliberate under-check that remains gets an INFO advisory or a named
  corpus row.
- The historical drift bugs and today's (#620/#632, #630) exist as named regression fixtures
  citing issue/commit.
- Grammar coherence: every strictly-valid template is also discoverable by the loose/
  validation views; every literal-grammar match round-trips `try_parse_json`.
- Existence and resolution cannot disagree (single walk: found ⟺ the walk reached a value).
- `$$` skipping is consistent across every layer (today only `_CACHE_TEMPLATE_RE` differs).

### Structure

- Exactly one place in `src/` compiles a `${…}` grammar, enforced by meta-test 2 with its
  named allowlist; no `re.*` outside the module references a `core.templates` attribute.
- No module under `core/` imports `pflow.runtime.template_resolver` or its shim (meta-test 3);
  no private-attribute reaches across the module's interface remain
  (`data_flow.py:34`, `cache_overlap.py:32`, `graph/scope.py:56`,
  `template_validation/validator.py:50/:652`).
- Validation passes, `data_flow`, engine resolution, error classification, cache chunking and
  the other phase-4 sites consume parsed segments/operands — no `str.split(".")`-style
  re-segmentation at those sites (the bare-segmenter long tail outside them — `[2:-1]` strips in
  `prompt_cache_analysis`, `diagnostic_render.py:735` — is out of scope and named as such;
  `template_validation/CLAUDE.md:99-100`'s "never `str.split('.')`" is made true for the
  package: `type_validation.py:955`, `type_checker.py:141`, `batch_item_validation.py:150`).
- The module is importable without `litellm` entering `sys.modules` — it needs its **own** pin
  (precedents `test_litellm_runtime.py:883`, `tests/test_cli/test_lazy_imports.py:25`).
- Parse is pure, total (never raises on user input), context-free, immutable (frozen
  dataclasses/tuples, pinned by a test — a consumer mutating a cached AST in the long-lived MCP
  server would contaminate later runs) and bounded-cached on author text only.

### Out of scope

- Any new template syntax or semantics beyond the Sanctioned deltas.
  **Deferred by design — a follow-on task after phase 5, decided as ONE language ruling
  (recorded 2026-09-28 at the #620 ruling):** whether non-grammar `${…}` content (shell
  `${VAR:-x}`, JS template literals) is tolerated without escaping — and where (everywhere as
  a warning vs only inside code-bearing params: `shell command`, `code`, MCP code/function
  params, file-referenced code) — #621; a raw/untemplated mode for a code block (#621, option
  3); the `${var|json}` filter (#550). Constraints the follow-on inherits: identifier-shaped
  unknowns (`${nod.result}`) stay an ERROR (typo detection is the thing at risk); the `$${`
  escape (#620) is the opt-out that exists today; Task 118's shell variable injection changes
  what `${X}` means in a shell block and needs the same ruling (blocked on this task). Adding
  semantics BEFORE this task lands means adding them to twelve regexes — that is why they wait.
  Under the AST, tolerance is policy over Issues (which Issues are ERRORs on which surface),
  never a parse mode.
- Unifying the validator's structure walk with the value walk (ADR-0006).
- Migrating the string-helper long tail to the AST; the ~40 lexical `"${" in x` presence checks.
- The type-compatibility matrix's *content* (only its home consolidates).
- Unresolved elements of an inline-list `batch.items` stay literal (never flagged, as today);
  the completion handback files a lane-B issue for it together with the cache-var-typo INFO
  advisory (chunk silently ABSENT). DECIDED 2026-09-28 (session-08).
- The web UI's TypeScript grammar mirrors beyond `scan.ts` (three lack the `$$` lookbehind:
  `batchItems.ts:26`, `format.ts:9`, `sourceDecorate.ts:32` — a separate issue).
- `prompt_refs.first_per_item_position` tearing a nested index (`'Static text. ${results[${item.i}].x}'`
  cuts at 23) — an existing bug, recorded for a lane.
- #643's save-path params — fixed separately on main (PR #664, `validate_with_placeholder_inputs`).
  #262 is not point-fixed but flips as a consequence of Pass 5 consuming parsed segments
  (the root of `items[0]` is `items`) — its corpus row records the flip.

## Implementation Notes

- The June 2026 plan is **superseded** (`implementation/implementation-plan-2026-06-12-SUPERSEDED.md`,
  kept for its truth tables and site lists; wrong post-#632 in at least five places, e.g. a
  `has_templates == bool(parse().exprs)` facade would re-break #620 — escape-only params must
  keep routing through resolution, `template_resolver.py:98`,
  `test_escape_only_value_needs_resolution`). The planner regenerates.
- Phase 4 is roughly half the total effort; the validation-pass migration
  (`path_validation.py`) dominates it. Phases 1–3 ≈ two days and capture most of the bug value.
- Net size: ~400–500 LOC module replacing ~450 LOC of scattered patterns/splitters/duplicate
  walks — approximately LOC-neutral after phase 5 (June estimate, unverified).
- Cache-key note: PR #632 already moved escape-only params from static to template params in
  the config hash (`instrumentation.py:163-169`); Sanctioned delta 2 moves the strict-rejected
  shapes the other way (they become errors, so no hash question arises).
- `_resolve_static_prefix_for_cache` (`prompt_cache.py:245-255`) is a second interpolation
  engine using `deterministic_serialize`, hidden by the fallback at `llm.py:733-755` — migrate
  its interpolation, keep its serializer.
- The batch warm-up `system` path (`engine._resolve_template_string` → `batch_executor.py:628-637`)
  re-scans output: a `$${x}` in `system` would drop the user system prompt and warm a different
  cache prefix (read, not executed — verify in phase 1).
- Phase 4d (the `web/src/graph/scan.ts` mirror) needs `npm ci` in `web/` first — the worktree
  carries no `node_modules`; then `npx vitest run src/graph/scan.test.ts`.
- Stale-doc fixes in passing: `template_validation/CLAUDE.md`'s regex table (add the current
  patterns, then rewrite as views in phase 3); `template_validation/CLAUDE.md`'s "`data_flow`
  still checks their roots" (false under a dynamic index + `??`).

## Verification

- `make test` and `make check` green after every phase (each phase is shippable).
- Phase 1's drift-test file passes against unmodified production code **with the xfail rows
  strict** (proves the corpus encodes current behavior and names the divergences, not
  aspirations).
- Phase 2 gated by a differential test (old vs new walk over a path×context corpus), deleted
  with the second loop.
- All Parity properties that hold on main hold continuously from phase 1; each Sanctioned delta
  flips exactly one xfail row in its named phase; all Structure properties hold by end of
  phase 5, each pinned by a meta-test.
- The existing resolver/validation suites pass unmodified through phases 2–4 **except the
  sanctioned test changes**: `test_node_wrapper.py:195-222` (phase 2), the dynamic-index pins
  (`test_nested_templates.py:54-59`, phase 4), the markdown/scope characterization deltas and
  the deletion of tests for deleted internals (`TestSplitTemplatePath`, phase 5) — each with an
  explicit decision recorded.
- Manual end-to-end after phase 4 and at completion: the #620 docs example, both #630 repros, a
  batch using `${results[${__index__}]…}` into a dict param, a `## Cache` block containing `$${`,
  a prewarm batch prompt containing an escape, `pflow -o result.@type` and `read-fields`, and a
  byte-identical run of `examples/` before and after.
- Mid-task review after phase 4 (the validation-pass migration is atomic and crosses layers)
  and the completion gate at the end (ORCHESTRATION "Review policy").
- Task-159 baseline: not a trace-format change (no new trace field); if the planner finds one
  is unavoidable, that is a hand-back, not a bump.

## References

- `context/adr/0006-template-language-no-shared-walk.md` — the decided shape + rejected
  alternatives; `context/adr/0015-170-cache-block-escape-unescaped-at-render.md` — the cache-block escape ruling;
  `context/adr/0014-135-engine-orchestration-shared-store-only.md` — the engine reads
  `dict(shared)`; resolution stays engine-driven
- `context/CONTEXT.md` — Template / Reference / Coalesce / Operand vocabulary (:38-50)
- `src/pflow/runtime/template_resolver.py` — current canonical grammar (:28, :60-81) + the
  duplicated walk (:491-633) + the pre-pass (:107-162) + single-pass interpolation (:747-753)
- `src/pflow/runtime/template_validation/` (+ its CLAUDE.md: regex-role table, pass map) —
  `validator.py:47-53` (permissive grammar), `:680-736` (malformed pass), `:752` / `:816-825`
  (operand extraction), `utils.py:20-65` (`split_template_path`)
- `src/pflow/runtime/engine/template_resolution.py` (`split_params` :113, strict check
  :237-250, `inject_none` :295-301, error policy :441-459), `engine.py:130-167/:245/:393-401`,
  `engine/template_errors.py` (:126-161, :320), `batch_executor.py:108-131/:122/:628-637`
- `src/pflow/core/workflow/data_flow.py` (`_PFLOW_VAR_RE` :34, operand loop :787-796, cache
  root check :1148-1159), `core/markdown_parser.py:167/:1737-1790`,
  `core/workflow/graph/scope.py:13-14/:56`, `core/prompt_cache.py:164-175/:224-256/:395-399`,
  `core/yaml_utils.py:40-44`, `runtime/output_resolver.py:41-53/:81/:161`,
  `execution/plan.py:1547/:2037`, `web/src/graph/scan.ts:55-62`
- `tests/test_execution/test_plan_drift.py` — the in-repo precedent for seam-pinning drift
  tests; `tests/test_core/test_litellm_runtime.py:926` — precedent for the AST-scan meta-test;
  `tests/test_import_hygiene.py:106` — home for the layering pin;
  `tests/test_runtime/test_template_escape.py`, `test_template_resolver.py:497` — the #632 pins
- Drift rap sheet: #441, #460 (PR #461), #266, commits d5a1af8c, 6b7faf8f, 8535ed9b + 4516cd72;
  #620 (PR #632), #630; related open: #262, #503, #520, #621, #550, #643
- Session-08 spec battery ledger (local, gitignored): `scratchpads/session-08/task-170-spec-refresh.md`
