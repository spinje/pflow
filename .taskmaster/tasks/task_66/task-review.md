# Task 66 Review: Structured Output for LLM Node

## Metadata
- Implementation Date: 2026-03-13
- Status: Complete, not yet committed

## Executive Summary

Added `output_schema` parameter to the LLM node. When set with a JSON Schema dict, it passes through to Simon Willison's `llm` library's `schema=` parameter, which delegates constrained decoding to provider plugins (Anthropic, Gemini, OpenAI). The response is guaranteed valid JSON, parsed to a dict in `post()`, and stored in `shared["response"]`. The implementation was ~15 lines of core logic — most of the infrastructure was already in place.

## Implementation Overview

### What Was Built

A single new parameter `output_schema` on the LLM node that:
1. Accepts a JSON Schema dict (parsed from `yaml output_schema` code blocks in `.pflow.md`)
2. Passes it as `schema=` to `model.prompt()` in `exec()`
3. Parses the JSON response to a dict in `post()` (instead of storing as string)
4. Skips `_strip_code_block()` when schema is set (API returns clean JSON)

### Deviation from Original Plans

The braindumps and research proposed several features that were **intentionally not implemented**:
- **Model capability detection** — unnecessary; the `llm` library raises `ValueError` if a model doesn't support schemas
- **Retry with stronger model on failure** — unnecessary; constrained decoding guarantees valid JSON
- **Model strength hints/warnings** — unnecessary; same reason
- **Simplified schema DSL** (Option C from braindump) — rejected in favor of standard JSON Schema, which AI agents generate natively and requires zero conversion

The research file (`llm-json-generation-failures.md`, dated 2025-01-19) was largely outdated — it focused on weak models failing at JSON generation, which structured output eliminates entirely.

## Files Modified

### Core Changes

- **`src/pflow/nodes/llm/llm.py`** — Added `import json`, `output_schema` param in docstring, `output_schema` passthrough in `prep()`, conditional `schema=` kwarg in `exec()`, `has_schema` boolean in exec return, conditional `json.loads()` vs `_strip_code_block()` in `post()`.

### Test Files

- **`tests/test_nodes/test_llm/test_llm.py`** — Added `TestStructuredOutput` class (10 tests). All tests follow the existing inline `patch("pflow.nodes.llm.llm.llm.get_model")` pattern. Critical tests: `test_structured_response_is_dict` (core contract), `test_output_schema_not_in_kwargs_when_absent` (no regression), `test_error_path_unaffected_by_schema` (error handling unchanged).

### Documentation

- **`src/pflow/nodes/llm/README.md`** — Added `output_schema` to params, added "Structured Output" section with `yaml output_schema` code block example.
- **`docs/reference/nodes/llm.mdx`** — Added to params/output tables, replaced prompt-based structured output example with schema-enforced approach.

## Integration Points & Dependencies

### Incoming Dependencies (what consumes this)

- **Template resolver** — `${llm-node.response.field}` now does direct dict access when response is a dict (more efficient than JSON string parsing). No code change needed — existing behavior.
- **Node wrapper type coercion** — When downstream node declares `response: str`, the wrapper auto-serializes the dict to JSON string via `coerce_to_declared_type()`. No code change needed.
- **Batch node** — Each batch item gets its own `inner_node._run(item_shared)` lifecycle. Schema applies per batch item. Deep-copy in parallel mode isolates params. No code change needed.

### Outgoing Dependencies (what this depends on)

- **`llm` library v0.28** — `model.prompt(text, schema=dict)` is the core mechanism. Raw dicts pass through `Prompt.__init__` unchanged (line 362-364 of `models.py`). If the library changes this interface, this feature breaks.
- **`llm-anthropic` plugin** — Uses `transform_schema()` for newer models (structured outputs API), tool-calling fallback for older models. Both accept dicts.
- **`llm-gemini` plugin** — Uses `cleanup_schema()` which strips `$defs`/`$ref`. Complex nested schemas with `$ref` may fail on Gemini.
- **Markdown parser** — `_CODE_BLOCK_TAG_TO_PARAM` maps `"output_schema"` at line 93. `yaml` prefix triggers `yaml.safe_load()`. Already existed before this task.

### Shared Store Keys

- `shared["response"]`: Now `str|dict` (was `str`). Dict when `output_schema` is set, str otherwise.
- `shared["llm_usage"]`: Unchanged.
- `shared["error"]`: Unchanged. Error path always stores `""` (string) regardless of schema.

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **JSON Schema format over simplified DSL** — AI agents generate JSON Schema natively from training data. No conversion layer needed. YAML representation is readable enough. The simplified syntax from the braindump (`talking_points: list[str]`) would require a custom parser and has less expressiveness (no enums, no field descriptions, no `required` control).

2. **`has_schema` boolean over passing full schema through exec_res** — We only need to know *whether* a schema was set in `post()`, not *what* it was. The API already validated conformance. Avoids carrying a potentially large dict through the pipeline.

3. **`json.loads()` in `post()`, not `exec()`** — Constrained decoding guarantees valid JSON. A `json.loads()` failure would indicate a broken library, not a model issue. Crashing in `post()` is correct — no retry would help. This was explicitly discussed with the user.

4. **Pipe syntax `str|dict` in docstring, not `Union[str, dict]`** — The metadata extractor and type checker parse types from docstrings using `|` as the union separator. `Union[...]` is not recognized and causes template validation failures.

## Unexpected Discoveries

### Docstring Types Are Runtime-Active

The LLM node docstring type `shared["response"]: str` is extracted by the metadata extractor and used by the template validator at compile time. Changing this to `Union[str, dict]` caused 2 test failures in unrelated test files (`test_workflow_validator.py`, `test_workflow_save.py`) because the type checker couldn't parse `Union[str, dict]` — it uses `|` pipe syntax for unions.

The type checker's union logic (line 91-93 of `type_checker.py`) requires ALL source types to be compatible with the target: `all(is_type_compatible(st, target_type) for st in source_types)`. For `str|dict` → `str`: both `str→str` and `dict→str` are in `TYPE_COMPATIBILITY_MATRIX`, so it passes.

### Everything Was Already Wired

The markdown parser already had `output_schema` in `_CODE_BLOCK_TAG_TO_PARAM`. The `llm` library already accepted raw dicts as `schema=`. The type compatibility matrix already handled `dict↔str` bidirectionally. The node wrapper already coerced dicts to strings when targets expect strings. The actual novel code was ~15 lines.

## Patterns Established

### Conditional kwargs for `model.prompt()`

```python
if prep_res["output_schema"] is not None:
    kwargs["schema"] = prep_res["output_schema"]
```

Follows the existing pattern for `system`, `max_tokens`, `attachments`. Only add to kwargs when not None — this ensures existing `assert_called_with` tests don't break (they check exact kwargs).

### Schema-to-library mapping

The param name in pflow is `output_schema` (matches Claude Code node convention). The kwarg name in the `llm` library is `schema`. This mapping happens in `exec()`: `kwargs["schema"] = prep_res["output_schema"]`.

## Testing Implementation

### Critical Test Cases

- `test_structured_response_is_dict` — Core contract: schema set → response is dict with correct values
- `test_output_schema_not_in_kwargs_when_absent` — No regression: schema not in kwargs when param missing
- `test_error_path_unaffected_by_schema` — Error path still stores empty string, not dict
- `test_output_schema_none_is_string_response` — Explicit None = string behavior unchanged

### Tests That Caught Real Bugs

The existing tests `test_valid_complex_workflow` and `test_save_workflow_with_mixed_inputs` caught the `Union[str, dict]` docstring format bug. These weren't tests I wrote — they're in the validator and MCP server test suites.

## AI Agent Guidance

### Quick Start for Related Tasks

If implementing Task 126 (structured output for Claude Code node): the Claude Code node already has `output_schema` but uses prompt injection + JSON extraction. Consider aligning with the LLM node's approach — but note Claude Code uses `claude_agent_sdk`, not the `llm` library, so the `schema=` parameter isn't available.

Key files to read:
1. `src/pflow/nodes/llm/llm.py` — the implementation (273 lines)
2. `src/pflow/runtime/type_checker.py` — union type handling and `TYPE_COMPATIBILITY_MATRIX`
3. `src/pflow/core/markdown_parser.py:85-94` — `_CODE_BLOCK_TAG_TO_PARAM` and code block routing

### Common Pitfalls

1. **Docstring type format**: Use `str|dict` pipe syntax, NOT `Union[str, dict]`. The metadata extractor parses these at runtime for template validation. Wrong format causes failures in unrelated tests.

2. **Gemini schema limitations**: The Gemini plugin's `cleanup_schema()` strips `$defs` and `$ref`. Complex schemas with recursive types or `$ref` references will fail on Gemini. Simple flat/nested schemas work fine.

3. **Don't validate response against schema in pflow**: The `llm` library and provider plugins handle schema enforcement via constrained decoding. Adding pflow-level validation would be redundant and create a maintenance burden for edge cases that can't happen.

### Test-First Recommendations

When modifying the LLM node:
1. Run `tests/test_nodes/test_llm/test_llm.py` first (fast, 0.4s, covers all LLM node behavior)
2. Run `make test` to catch cross-component type validation issues (the docstring type bug was only caught by full suite)

---

*Generated from implementation context of Task 66*
