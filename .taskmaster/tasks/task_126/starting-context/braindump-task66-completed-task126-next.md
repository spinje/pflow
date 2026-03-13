# Braindump: Task 126 — Structured Output for Claude Code Node

**Date**: 2026-03-13
**Context**: Task 66 (Structured Output for LLM Node) just completed. User considered doing Task 126 in the same session. After I explained the differences, they decided to braindump instead. Task 126 is NOT started.

## Where I Am

Task 66 is done and merged-ready. The LLM node now accepts `output_schema` (JSON Schema dict) via `yaml output_schema` code block in `.pflow.md`, passes it as `schema=` to the `llm` library, and stores the parsed dict in `shared["response"]`. All tests pass, `make check` clean.

Task 126 was discussed but NOT implemented. The user asked "should we do task 126 as well, its very similar right?" — I explained why it's actually quite different despite the same user-facing syntax. The user accepted this and chose to braindump for later.

## User's Mental Model

The user thinks of Task 66 and Task 126 as a **pair** — both are "structured output" and should have the same workflow syntax. They asked: "we the markdown ir planned to be the same?" — Yes, the markdown format is identical (`yaml output_schema` code block with JSON Schema). The user cares about **consistency** between these two nodes from a workflow author's perspective.

The user is an AI-agent-first thinker. When I asked "what is most natural for AI agents like you to write?" about schema format, they immediately aligned on JSON Schema over a custom DSL. Their reasoning: AI agents generate JSON Schema from training data. No learning curve, no docs to read.

The user also asked "and this could also be expressed in a yaml code block right?" — confirming they want the same `yaml output_schema` code block syntax for both nodes. This is the expected format for Task 126.

## Key Insight: Task 126 Is NOT "Same as Task 66"

The task spec (task-126.md) says "This is the Claude Code equivalent of Task 66." This is misleading. The implementation is fundamentally different:

| Aspect | Task 66 (LLM node) | Task 126 (Claude Code node) |
|--------|--------------------|-----------------------------|
| Library | Simon Willison's `llm` | `claude_agent_sdk` |
| Mechanism | `model.prompt(schema=dict)` — constrained decoding | No native schema support (needs investigation) |
| Response | `response.text()` returns JSON string | Agentic text with JSON extraction |
| Code change | ~15 lines | Unknown — may need prompt rewrite, validation, retry |
| Confidence | High — library handles everything | Low — SDK may not support structured output |

The Claude Code node already has `output_schema` working (it's in the docstring, line 10 of `claude_code.py`), but via a completely different mechanism than what Task 66 uses.

## What Already Exists in Claude Code Node

The Claude Code node at `src/pflow/nodes/claude/claude_code.py` (1035 lines) already has:

1. **`output_schema` parameter** — accepts a dict, but in a DIFFERENT format than JSON Schema:
   ```python
   {"risk_level": {"type": "str", "description": "high/medium/low"},
    "score": {"type": "int", "description": "Security score 1-10"}}
   ```
   This is NOT JSON Schema. It's a flat field-name → {type, description} mapping.

2. **`_build_schema_prompt()`** (lines 786-832) — converts schema to aggressive system prompt instructions demanding JSON-only output, including a template like `{"risk_level": "<str: high/medium/low>"}`

3. **`_build_prompt()`** (lines 736-762) — wraps user prompt with "RESPOND WITH JSON ONLY" bookends when schema is present

4. **`_extract_json()`** (lines 942-966) — 3 extraction strategies: code block regex, raw JSON object regex, brace-matching from end of string

5. **`_store_results()`** (lines 834-940) — stores `shared["result"]` as dict on success, falls back to raw text with `shared["_schema_error"]` on failure

6. **`_validate_schema()`** — only checks key names are valid identifiers and count < 50. Does NOT validate the type/description structure.

ASSUMPTION: The existing `output_schema` format may have users (the Claude Code node is used in skills). Changing the format is a breaking change. But per CLAUDE.md: "We have NO USERS yet" — so this is probably fine.

NEEDS VERIFICATION: Check if any example workflows or saved workflows use the Claude Code node's existing `output_schema` format. Grep for `output_schema` in `examples/` and `~/.pflow/workflows/`.

## The Three Paths for Task 126

### Path A: Upgrade to JSON Schema + keep prompt injection
- Change schema format from custom to JSON Schema
- Rewrite `_build_schema_prompt()` to convert JSON Schema → prompt instructions
- Keep the `_extract_json()` extraction approach
- Add JSON Schema validation of the response
- Pro: Works today, no SDK dependency
- Con: Still fragile (prompt injection), verbose prompt conversion logic

### Path B: Investigate `claude_agent_sdk` native structured output
- The SDK may have added structured output support since the node was written
- Task spec line 46: "Investigate whether the Claude Agent SDK / CLI supports structured output natively"
- If it does, this becomes as clean as Task 66
- Pro: Reliable, clean
- Con: Unknown if supported, may not exist

### Path C: Use `llm` library's Anthropic plugin instead of `claude_agent_sdk`
- The `llm-anthropic` plugin already supports `schema=` with native structured outputs for newer Claude models
- But `claude_agent_sdk` is fundamentally different — it's an agentic SDK (multi-turn, tool use, file editing), not a simple prompt→response interface
- CONSIDER: Can you even get structured output from an agentic session? The agent uses tools, writes files, has multi-turn conversations. Constraining its final output to JSON is a different problem than constraining a single-turn prompt.

UNCLEAR: Whether structured output even makes sense for the Claude Code node's agentic paradigm. The LLM node is single-turn: prompt → response. The Claude Code node is multi-turn: prompt → agent does work → final result. Structured output on the final result may need a different mechanism entirely.

## Assumptions & Uncertainties

ASSUMPTION: The user wants both nodes to accept the same JSON Schema format in `yaml output_schema` code blocks. This was discussed and agreed.

ASSUMPTION: The existing simple format `{"field": {"type": "str", "description": "..."}}` can be replaced with JSON Schema without backward compatibility concerns (no users).

UNCLEAR: Whether `claude_agent_sdk` supports structured output natively. This is the first thing to investigate.

UNCLEAR: Whether the markdown parser's existing `output_schema` code block handling produces JSON Schema that the Claude Code node's `_validate_schema()` would accept. Currently `_validate_schema()` expects the simple format — it would reject JSON Schema because keys like `type`, `properties`, `required` aren't valid field names for the simple format.

NEEDS VERIFICATION: Check `claude_agent_sdk` version and capabilities. Look at `.venv/lib/python3.13/site-packages/claude_agent_sdk/` for any `schema`, `structured_output`, `json_schema`, or `output_format` parameters.

NEEDS VERIFICATION: Check if any existing workflows use the Claude Code node's current `output_schema` format.

## What Almost Broke in Task 66 (Learn From This)

**Docstring type annotation format**: I used `Union[str, dict]` in the LLM node docstring. The template validator parses types from docstrings and uses `|` pipe syntax (`str|dict`), not Python's `Union[...]`. This caused 2 test failures in unrelated tests (`test_valid_complex_workflow`, `test_save_workflow_with_mixed_inputs`) because the validator saw `union[str,` as the type string and couldn't match it.

**Fix**: Use `str|dict` in Interface docstrings, not `Union[str, dict]`.

The Claude Code node's docstring currently says `shared["result"]: any` (line 11). If Task 126 changes this to a union type, use pipe syntax: `str|dict`.

## Unexplored Territory

UNEXPLORED: The Claude Code node writes to `shared["result"]`, not `shared["response"]` like the LLM node. Task 126 should keep this — it's an established difference between the two nodes.

UNEXPLORED: The Claude Code node's `_extract_json()` uses 3 regex-based strategies to find JSON in Claude's agentic output. This is because Claude as an agent generates verbose text alongside JSON ("Analysis complete.\n" before the JSON block). Even with structured output, Claude Code's agentic nature means it may always produce mixed text+JSON output. The extraction strategies may still be needed even with schema enforcement.

CONSIDER: The Claude Code node has `shared["_schema_error"]` for graceful degradation when JSON extraction fails. The LLM node (Task 66) doesn't have this — it crashes on `json.loads()` failure because the API guarantees valid JSON. For Claude Code, degradation may still be the right pattern since the agentic output is less predictable.

MIGHT MATTER: The Claude Code node is tested with a module-level `sys.modules` mock for `claude_agent_sdk` (see `tests/CLAUDE.md` pitfall 17). This mock persists for the entire pytest session. Any changes to how the SDK is called must be compatible with this mock pattern.

MIGHT MATTER: The Claude Code node already parses JSON in `post()` when `output_schema` is present. The LLM node (pre-Task 66) deliberately did NOT parse in post (stored raw strings). Task 66 changed this for the schema path. The Claude Code node's pattern is actually the precedent we followed.

CONSIDER: Should Task 126 also add retry-on-schema-failure? The task spec mentions it (line 50: "consider retry with error feedback"). The LLM node doesn't need this (API guarantees), but Claude Code's extraction-based approach might benefit from it. However, the node already has 2 retries built into PocketFlow's retry mechanism — if `_extract_json()` raises, it would retry the entire agentic session, which is expensive (~$0.05+ per attempt). A targeted "your JSON was malformed, try again" prompt within the same session might be better than a full retry.

## What I'd Tell Myself

1. **Start by checking the SDK**: `claude_agent_sdk` may have added structured output since the node was written. Check the installed version, read the SDK source in `.venv/`. This determines whether you take Path A (prompt injection upgrade) or Path B (native support).

2. **Don't assume it's easy**: Task 66 was ~15 lines because the `llm` library handles everything. The Claude Code node is 1035 lines with complex agentic logic. The structured output mechanism is deeply intertwined with `_build_prompt()`, `_store_results()`, and `_extract_json()`.

3. **The user wants format consistency, not implementation consistency**: Both nodes should accept JSON Schema in `yaml output_schema` code blocks. But the internal mechanisms can (and should) differ.

4. **Read the existing implementation thoroughly**: `_build_schema_prompt()`, `_extract_json()`, `_store_results()` — understand these before planning changes. The existing code works; the task is upgrading the format and reliability, not a rewrite.

5. **The task spec (task-126.md) is partially wrong**: It says "currently returns free-form text output" — this is false for the schema path. The node already has `output_schema` support. The real task is upgrading it from the simple format to JSON Schema, improving reliability, and potentially leveraging native SDK support.

## Open Threads

1. **SDK investigation not done**: The first action for Task 126 is checking `claude_agent_sdk` capabilities. This determines the entire approach.

2. **Schema format migration**: How to go from `{"field": {"type": "str", "description": "..."}}` to JSON Schema. Is this a clean replace or does the simple format need to be supported as legacy?

3. **The task spec proposes JSON Schema format** (lines 23-42) — which aligns with Task 66. But the spec was written before the existing simple format was implemented. It needs re-scoping.

4. **Retry strategy**: Full PocketFlow retry (re-run entire agentic session) vs. in-session feedback loop. Not decided.

## Relevant Files & References

### Must-Read
- `src/pflow/nodes/claude/claude_code.py` — Full implementation (1035 lines), especially:
  - Lines 786-832: `_build_schema_prompt()` — current prompt injection
  - Lines 736-762: `_build_prompt()` — "RESPOND WITH JSON ONLY" wrapping
  - Lines 942-966: `_extract_json()` — 3 extraction strategies
  - Lines 834-940: `_store_results()` — result storage with schema handling
- `tests/test_nodes/test_claude/test_claude_code.py` — Tests (1037 lines, 23 criteria)
- `.taskmaster/tasks/task_126/task-126.md` — Task spec (partially outdated)

### Reference (Task 66 implementation)
- `src/pflow/nodes/llm/llm.py` — Completed Task 66 implementation (clean example)
- `tests/test_nodes/test_llm/test_llm.py` — TestStructuredOutput class (10 tests, pattern to follow)
- `.taskmaster/tasks/task_66/implementation/progress-log.md` — Full implementation log

### SDK Investigation
- `.venv/lib/python3.13/site-packages/claude_agent_sdk/` — Check for structured output support
- `.venv/lib/python3.13/site-packages/llm_anthropic.py` — Reference for how Anthropic structured outputs work at API level

## For the Next Agent

**Start by**: Investigating `claude_agent_sdk` for native structured output support. This is the fork in the road that determines everything else.

**Don't bother with**: Re-reading Task 66's research or braindumps. Task 66 is done. The LLM node implementation is clean and can be read directly in `llm.py`.

**The user cares most about**: Consistency in workflow syntax (`yaml output_schema` code block with JSON Schema) between LLM and Claude Code nodes. They don't care if the internals differ — they care that a workflow author writes the same format for both.

**When implementing**: The Claude Code node is 5x larger than the LLM node and uses a completely different SDK. Don't treat this as "same as Task 66 but different node." Treat it as a new implementation that happens to share the same user-facing format.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
