# Task 66: Structured Output for LLM Node

## Status
done

## Completed
2026-03-13

## Problem Statement

Users who need JSON from LLM nodes must prompt for it and hope the model complies — leading to code-fence wrapping, schema drift, and defensive parsing downstream. There was no way to guarantee structured JSON responses.

### Before
```
# Must prompt for JSON and parse defensively
- type: llm
- prompt: "Return JSON with fields: name, age. No markdown."
# Response: ```json\n{"name": "Alice", "age": 30}\n```  (or worse)
```

### After
````markdown
### extract
- type: llm
- prompt: Extract from ${read.content}
- temperature: 0

```yaml output_schema
type: object
properties:
  people:
    type: array
    items:
      type: string
required:
  - people
```
````
Response is a guaranteed-valid parsed `dict` in `shared["response"]`.

## Solution Implemented

Added `output_schema` parameter to the LLM node. When set with a JSON Schema dict, it passes through to Simon Willison's `llm` library's `schema=` parameter, enabling constrained decoding via provider APIs (Anthropic, Gemini, OpenAI).

### How It Works

1. **`prep()`** extracts `output_schema` from `self.params`
2. **`exec()`** passes it as `schema=` to `model.prompt()` — provider plugins handle constrained decoding
3. **`post()`** parses the JSON response via `json.loads()` and stores a `dict` in `shared["response"]`
4. `_strip_code_block()` is skipped when schema is set (API returns clean JSON)
5. Downstream `${node.response.field}` works via direct dict lookup

### Key Design Decisions

1. **JSON Schema format over simplified DSL** — AI agents generate JSON Schema natively. No conversion layer needed. YAML representation is readable enough.
2. **`has_schema` boolean in exec_res, not full schema dict** — `post()` only needs to know *whether* a schema was set, not *what* it was. The API already validated conformance.
3. **`json.loads()` in `post()`, not `exec()`** — Constrained decoding guarantees valid JSON. A parse failure would indicate a broken library, not a model issue. Crashing is correct — no retry would help.
4. **No pflow-level schema validation** — The `llm` library and provider plugins handle enforcement. Redundant validation was explicitly rejected.
5. **Pipe syntax `str|dict` in docstring** — The metadata extractor parses types from docstrings at runtime using `|` as union separator. `Union[str, dict]` caused test failures.

### What Was Intentionally Not Implemented

- **Model capability detection** — the `llm` library raises `ValueError` if a model doesn't support schemas
- **Retry with stronger model on failure** — constrained decoding guarantees valid JSON
- **Simplified schema DSL** — rejected in favor of standard JSON Schema

## Files Changed

### Core
- **`src/pflow/nodes/llm/llm.py`** — `output_schema` param in `prep()`, conditional `schema=` kwarg in `exec()`, conditional `json.loads()` in `post()` (~15 lines of core logic)

### Tests
- **`tests/test_nodes/test_llm/test_llm.py`** — `TestStructuredOutput` class with 10 tests covering schema passthrough, response type contract, error paths, edge cases

### Documentation
- **`src/pflow/nodes/llm/README.md`** — Added `output_schema` to params table, added "Structured Output" section
- **`docs/reference/nodes/llm.mdx`** — Updated params/output tables, replaced prompt-based example with schema-enforced approach
- **`src/pflow/cli/resources/cli-agent-instructions.md`** — Updated agent instructions
- **`src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md`** — Updated MCP agent instructions

## Shared Store Contract Change

- `shared["response"]`: Now `str|dict` (was `str`). Dict when `output_schema` is set, string otherwise.
- `shared["llm_usage"]`: Unchanged.
- `shared["error"]`: Unchanged.

## Acceptance Criteria

- [x] `output_schema` parameter passes JSON Schema to `llm` library's `schema=`
- [x] Response stored as parsed `dict` when schema is set
- [x] Response remains `str` when no schema is set (backward compatible)
- [x] `_strip_code_block()` skipped with schema (API returns clean JSON)
- [x] Downstream `${node.response.field}` template access works
- [x] Error path unaffected by schema
- [x] 10 unit tests covering all paths
- [x] All existing tests pass, `make check` clean
- [x] User-facing docs updated

## Unexpected Discovery

**Docstring types are runtime-active**: The LLM node docstring type `shared["response"]: str` is extracted by the metadata extractor and used by the template validator at compile time. Changing to `Union[str, dict]` caused 2 test failures in unrelated suites because the type checker uses `|` pipe syntax for unions, not `Union[...]`.

## PR

- PR #95: `feat: add structured output support for LLM node`
- Merged: 2026-03-13
- Commit: `f784b230`

## Related

- Task 126: Structured Output for Claude Code Node (separate — uses `claude_agent_sdk`, not `llm` library)
- Implementation review: `.taskmaster/tasks/task_66/task-review.md`
- Progress log: `.taskmaster/tasks/task_66/implementation/progress-log.md`
