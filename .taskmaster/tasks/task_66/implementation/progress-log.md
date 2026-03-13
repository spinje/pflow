# Task 66: Structured Output for LLM Node — Progress Log

## 2026-03-13 — Context Gathering & Research

Read all starting context files:
- `braindump-ai-sales-os-consumer-perspective.md` — Real consumer pain: code fence wrapping, schema drift, prompt bloat from schema instructions. Highest-impact workflows: pitch-prep and handoff-briefs.
- `braindump-json-parse-design-audit.md` — Full audit of 6 auto-parse points in pflow. Consensus: remove `parse_json_response` from LLM node (already done), add structured output (Task 66) as the explicit mechanism.
- `research/llm-json-generation-failures.md` — Older research (2025-01) about weak models failing at JSON. Partially outdated.

Key findings from codebase exploration:
- `parse_json_response` already removed — LLM node stores raw strings via `_strip_code_block()`
- Simon Willison's `llm` library (v0.28) has first-class `schema=` on `model.prompt()`
- Anthropic plugin: native structured outputs API for newer models, tool-calling fallback for older
- Gemini plugin: `response_schema` with `response_mime_type: "application/json"`
- pflow already uses `schema=` internally (smart_filter.py, planning system) — all via Pydantic models
- Markdown parser already has `"output_schema"` in `_CODE_BLOCK_TAG_TO_PARAM` (line 93)

Verified assumptions:
1. `llm` library accepts raw dicts as `schema=` (not just Pydantic models) — confirmed in `Prompt.__init__`
2. `response.text()` returns raw JSON string when schema is set — caller must `json.loads()`
3. No downstream system changes needed (IR schema, compiler, node wrapper, template resolver, batch node all handle dict responses already)

## 2026-03-13 — Design Decisions

**Schema format**: JSON Schema (standard), not custom DSL. AI agents generate JSON Schema from training data effortlessly. Zero conversion needed — YAML-parsed dict passes straight to `llm` library.

**Workflow syntax**: `yaml output_schema` code block tag in `.pflow.md`. Already supported by parser.

**Response type**: `shared["response"]` becomes `dict` when schema is set, stays `str` otherwise.

**Error handling**: No special handling needed. Constrained decoding guarantees valid JSON. A `json.loads()` failure would mean the library is broken — crashing is correct.

**`_strip_code_block` skipped**: When schema is set, API returns clean JSON, no code fences.

## 2026-03-13 — Implementation

### Step 1: LLM node changes (`src/pflow/nodes/llm/llm.py`)

Changes applied:
- Added `import json`
- Updated docstring: added `output_schema: dict` param, changed response type to `str|dict`
- `prep()`: added `"output_schema": self.params.get("output_schema")` to return dict
- `exec()`: added conditional `kwargs["schema"] = prep_res["output_schema"]` following existing optional kwarg pattern
- `exec()`: added `"has_schema"` boolean to return dict (avoids carrying full schema dict through pipeline)
- `post()`: conditional branch — `json.loads()` when `has_schema`, else `_strip_code_block()` as before

All changes mechanical and localized. No existing behavior affected when `output_schema` is not set.

### Step 2: Tests (`tests/test_nodes/test_llm/test_llm.py`)

Added `TestStructuredOutput` class with 10 tests:
1. `test_output_schema_passed_to_model_prompt` — verifies `schema=` in kwargs
2. `test_output_schema_not_in_kwargs_when_absent` — verifies no `schema` when not set
3. `test_structured_response_is_dict` — response parsed to dict
4. `test_structured_output_skips_strip_code_block` — code block stripping bypassed
5. `test_nested_json_response` — deep dict access works
6. `test_array_response` — list responses work (schema type: array)
7. `test_usage_metrics_preserved_with_schema` — llm_usage unaffected
8. `test_error_path_unaffected_by_schema` — errors still store empty string
9. `test_output_schema_none_is_string_response` — explicit None = string behavior
10. `test_action_returns_default_with_schema` — returns "default"

- **49/49 tests passed** (39 existing + 10 new) in 0.42s

### Step 3: Lint fix

- Ruff flagged `SIMPLE_SCHEMA` class attribute as needing `ClassVar` annotation → added `ClassVar[dict]` type hint and `from typing import ClassVar` import.

### Step 4: Docstring type format fix

- ❌ Used `Union[str, dict]` in docstring initially
- 💡 Template validator parses types from docstrings and uses `|` pipe syntax for unions, not `Union[...]`
- Caused 2 test failures: `test_valid_complex_workflow` and `test_save_workflow_with_mixed_inputs` — both had LLM nodes where downstream `str` params failed type check against `union[str,` (malformed parse of `Union[str, dict]`)
- ✅ Fixed to `str|dict` — type checker's `all()` union check passes because both `str→str` and `dict→str` are compatible in `TYPE_COMPATIBILITY_MATRIX`

### Step 5: Documentation

Updated:
- `src/pflow/nodes/llm/README.md` — added `output_schema` to params, added "Structured Output" section with workflow example
- `docs/reference/nodes/llm.mdx` — added to params table, updated output table, replaced prompt-based structured output example with schema-enforced example

### Step 6: Final verification

- `make check`: all passed (ruff, mypy, deptry)
- `make test`: **3800 passed, 0 failed, 485 skipped** in 6.98s

## Files Modified

| File | Change |
|------|--------|
| `src/pflow/nodes/llm/llm.py` | Core implementation: output_schema in prep/exec/post |
| `tests/test_nodes/test_llm/test_llm.py` | 10 new tests in TestStructuredOutput class |
| `src/pflow/nodes/llm/README.md` | Added output_schema docs and structured output section |
| `docs/reference/nodes/llm.mdx` | Updated params/output tables, structured output example |

## What Did NOT Need Changing (Verified)

- Markdown parser — already maps `output_schema`
- IR schema — `additionalProperties: True`
- Compiler — opaque param bag
- Node wrapper — dict↔str coercion works
- Template resolver — direct dict access, no JSON parse needed
- Batch node — full lifecycle per item, no interference

## Lessons Learned

- **Docstring types matter at runtime**: pflow extracts types from node docstrings for template validation. `Union[str, dict]` doesn't parse — use `str|dict` pipe syntax.
- **The `llm` library is more capable than pflow uses**: Raw dict schemas work fine despite all existing usage being Pydantic-based. No conversion layer needed.
- **Most of the work was already done**: Parser support, type compatibility matrix, downstream coercion — all pre-existing. The actual code change was ~15 lines.
