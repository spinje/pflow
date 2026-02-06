# Braindump: JSON Auto-Parse Bug → Full System Design Audit

**Date**: 2026-02-06
**Context**: User filed a bug in the LLM node's `parse_json_response`, but the conversation evolved into a full design audit of every auto-parse point in pflow. This braindump captures the architectural analysis and the user's design direction.

## Where I Am

We completed a thorough investigation but **wrote zero code**. The conversation was purely analytical:
1. Verified the bug in `llm.py:67-71`
2. Read task reviews for Tasks 105, 103, 12, 95 to understand the full JSON parsing story
3. Researched how LangChain, Vercel AI SDK, n8n, and Simon Willison's `llm` handle this
4. Inventoried every auto-parse point in pflow (6 locations)
5. Assessed each against best practices
6. Reached consensus on direction but haven't implemented anything

The user has NOT explicitly approved the implementation approach yet. We were in discussion when context ran out.

## User's Mental Model

The user thinks in **systems**, not patches. Three critical moments:

1. **First redirect**: After I presented the bug fix options (A/B/C), the user said: *"can you try to understand the bigger picture here before we jump to conclusions. What are the related task-review.md files we should read first?"* — They wanted architectural context before any fix discussion.

2. **Second redirect**: After I presented bigger-picture options (A/B/C/D with task review context), the user said: *"lets take a step back do we have enough information to make a great decision here? how do systems similar to this handle this? whats in your training data (great code)"* — They wanted external validation against industry best practices, not just internal consistency.

3. **Third redirect**: After I recommended removing LLM auto-parsing based on industry patterns, the user asked: *"yes we should probably remove this from the node, but is the rest of pflow good design aligned with best practices? we are doing alot of auto parsing right at a system level?"* — They noticed pflow has auto-parsing everywhere and wanted the full audit.

**The user's real concern is not the bug — it's the design pattern.** They want to know if pflow's approach to JSON parsing is architecturally sound or if it's a systemic smell. The bug is just the symptom that surfaced the question.

## Key Insights

### The Universal Pattern From Best Systems

Every well-designed LLM orchestration system (LangChain, Vercel AI SDK, n8n, `llm` library, OpenAI/Anthropic APIs) follows the same principle: **parsing is never implicit at the producer level**. The producer stores raw output. Parsing is either:
- **Explicit** (LangChain output parsers, Vercel's `output` schema property)
- **Schema-driven at the consumer** (consumer declares expected type)
- **On-demand** (parse only when nested access is requested)

Zero of these systems do what pflow's LLM node does: speculatively extract code blocks and try `json.loads()` as default behavior.

### The Three Layers That Don't Coordinate

pflow has three independent JSON parsing systems that were built at different times by different tasks and don't share infrastructure:

1. **LLM Node** (`llm.py:47-78`): Own inline parser with code block unwrapping. Does NOT use `json_utils`. This is the bug.
2. **Template Resolver** (`template_resolver.py`): Uses `json_utils.try_parse_json()`. Added by Task 105.
3. **Output Display** (CLI + formatters): Uses `json_utils.parse_json_or_original()`.

Task 105 consolidated 7 duplicate JSON parsers into `json_utils.py` but **missed the LLM node** — it still has its own inline implementation. This is both the technical root cause and a consolidation gap.

### The 6 Auto-Parse Points (Complete Inventory)

I built a complete inventory. This is the key artifact from this conversation:

| # | File:Lines | When It Fires | Intent Signal? | Verdict |
|---|-----------|---------------|----------------|---------|
| **1** | `llm.py:67-71` | Every LLM response | None | **REMOVE** — the bug |
| **2** | `template_resolver.py:202-231` | `${node.stdout.field}` dot access | Yes (dot notation) | **GOOD** — lazy, on-demand |
| **3** | `template_resolver.py:632-638` | `{"data": "${shell.stdout}"}` inline objects | Partial | **DEFENSIBLE** — see below |
| **4** | `node_wrapper.py:827-842` | Target node declares `dict`/`list` type | Yes (schema) | **GOOD** — schema-driven |
| **5** | `batch_node.py:262-271` | Batch items resolve to string | Yes (semantic) | **GOOD** — items must be iterable |
| **6** | `cli/main.py` + formatters | Output display | N/A | **FINE** — read-only presentation |

### The #3 Subtlety (resolve_nested auto-parse)

This is the one I'd flag as "70% sure it's fine, needs watching." Here's the specific behavior:

```python
# template_resolver.py:632
if isinstance(resolved, str) and TemplateResolver.is_simple_template(value):
    success, parsed = try_parse_json(resolved)
    if success and isinstance(parsed, (dict, list)):
        return parsed
```

**What it does**: When you write `{"body": "${shell.stdout}"}` and stdout is a JSON string like `'{"key":"value"}'`, it auto-parses the inner value to prevent double-encoding.

**Why it's needed**: Without it, HTTP bodies, MCP tool arguments, etc. would get `{"body": "{\"key\":\"value\"}"}` — double-encoded. #4 (node wrapper) can't fix this because it checks top-level param types, not inner values of nested dicts.

**The interaction with removing #1**: After we remove LLM auto-parsing, if someone writes `{"data": "${llm.response}"}` and the LLM returned raw JSON (no code blocks), #3 would parse it to a dict. This partially re-introduces what we're removing. **However**, the critical difference is:
- #3 doesn't do code block unwrapping (the actual bug mechanism)
- #3 only fires inside inline objects, not top-level params
- Prose with embedded JSON code blocks won't trigger #3 because prose doesn't start with `{`
- #3 uses `try_parse_json` which has a first-character check: `first_char not in '{["tfn-0123456789'`

So the prose-destruction bug cannot resurface through #3. The guard conditions are sufficient.

ASSUMPTION: I assumed that the container-only guard (`isinstance(parsed, (dict, list))`) plus the first-character check in `try_parse_json` make #3 safe for the prose case. This hasn't been tested with edge cases like LLM responses that start with `{` but aren't JSON.

NEEDS VERIFICATION: Test that removing #1 while keeping #3 behaves correctly for these cases:
- LLM returns prose with embedded `{...}` (not valid JSON) — should stay string
- LLM returns pure JSON `{"key": "value"}` — #3 would parse in inline objects, acceptable?
- LLM returns code-block-wrapped JSON — stays as raw string (code blocks aren't valid JSON for `json.loads`)

## Assumptions & Uncertainties

**ASSUMPTION**: The user soft-agreed with removing LLM auto-parsing ("yes we should probably remove this from the node") but hasn't given explicit go-ahead for implementation. They were still asking about systemic design when context ran out.

**ASSUMPTION**: Task 66 (Structured Output) will be the proper long-term solution for "I want JSON from the LLM." This means removing auto-parse now is safe because Task 66 will add the explicit mechanism later.

**UNCLEAR**: Whether removing auto-parse from the LLM node should be its own task/PR or folded into Task 66. The bug fix is small (delete `parse_json_response`, store raw string, use `json_utils` if needed) but the implications touch workflows that rely on `${llm.response}` returning a dict.

**UNCLEAR**: The user's appetite for breaking existing workflows (like the generate-changelog workflow). Since there are "NO USERS" per CLAUDE.md, backward compat isn't a concern, but internal workflows might need updating.

**NEEDS VERIFICATION**: I didn't check whether any existing test assertions depend on `parse_json_response` returning a dict. The LLM node tests in `tests/test_nodes/test_llm/test_llm.py` likely test this method directly.

## Unexplored Territory

**UNEXPLORED**: What happens to the `shared["response"]` type annotation in the LLM node's docstring? Currently says `any` (JSON dict or string). After removing auto-parse, it should say `str` always. This affects the type checker (Task 84), template validator warnings, and downstream compile-time validation.

**UNEXPLORED**: The `node_output_formatter.py:489` (`_try_parse_json_string`) — this is in the display layer and does its own JSON parsing for pretty-printing node outputs. It's read-only so it's safe, but the next agent should be aware it exists.

**CONSIDER**: Should the code block unwrapping logic move to a utility function for Task 66? When Task 66 adds structured output, it may need to unwrap code blocks from LLM responses. The `startswith("```")` guard from the bug report is actually good logic — just in the wrong place (production default vs explicit opt-in).

**CONSIDER**: The LLM node docstring says `Writes: shared["response"]: any`. If we change to always storing strings, this becomes `str`. But Task 105's template resolver uses the declared type to decide whether to show a warning when you do `${llm.response.field}` on a `str` type. Changing the declared type from `any` to `str` would trigger compile-time warnings for nested access — which is actually correct behavior (you're accessing nested fields on a string, the resolver will try to parse).

**MIGHT MATTER**: The `parse_json_response` method is `@staticmethod`. It's called only from `post()` on line 178. But it's public API — if any external code calls `LLMNode.parse_json_response()` directly (unlikely but possible), removing it is a breaking change.

**MIGHT MATTER**: The generate-changelog workflow (`examples/real-workflows/generate-changelog/workflow.pflow.md`) is the workflow that surfaced this bug. After fixing, the output of LLM nodes in that workflow will change. The workflow may need updating if downstream nodes expect dicts from `${llm-node.response}`.

## What I'd Tell Myself

1. **Start by reading the bug report** at `scratchpads/json-parse-bug/bug-report.md` — it's excellent, thorough, and accurate. The suggested fix (`startswith`) is correct but the user wants a deeper solution.

2. **Don't jump to the fix.** The user explicitly redirected THREE TIMES away from "just fix the bug" toward understanding the design. They care about architectural integrity, not patching symptoms.

3. **The conversation consensus** (not formally approved): Remove `parse_json_response` from the LLM node entirely. Store raw string. Let Task 105's template resolver handle lazy parsing for nested access. Let Task 66 add explicit structured output later.

4. **Read the task reviews first**: Task 105 (`auto-parse JSON during traversal`), Task 103 (`type preservation`), and Task 12 (`original LLM node`) are essential context. They're at `.taskmaster/tasks/task_{105,103,12}/task-review.md`.

5. **The key file you'll modify is small**: `src/pflow/nodes/llm/llm.py:46-78` (the `parse_json_response` method) and line 178 where it's called from `post()`.

## Open Threads

1. **Implementation decision not finalized**: Should this be a standalone bug fix PR, or part of Task 66? The user may have an opinion.

2. **Test impact unknown**: Need to check `tests/test_nodes/test_llm/test_llm.py` for tests that assert on `parse_json_response` behavior. These will need updating.

3. **#3 (resolve_nested) tech debt**: I flagged this as "defensible but weakest link." The user didn't push back but also didn't explicitly endorse it. If they ask about it again, the key argument is: it prevents double-encoding in inline objects and has container-only + simple-template-only guards.

4. **The display layer** (`cli/main.py:973-997`, `success_formatter.py:120-141`) does `parse_json_or_original` on workflow outputs. This is at the output boundary and is read-only. I didn't discuss this with the user but it's fine — it's presentation, not data mutation.

5. **I was about to suggest**: Creating a new task specifically for "Remove LLM node auto-parsing" as a quick bug fix, separate from Task 66. Task 66 is bigger (structured output with schemas). The bug fix is small and can land independently.

## Relevant Files & References

### Must-Read
- `scratchpads/json-parse-bug/bug-report.md` — The bug report (excellent quality)
- `scratchpads/json-parse-bug/test-parse-bug.pflow.md` — Reproduction workflow
- `src/pflow/nodes/llm/llm.py:46-78` — The buggy code
- `src/pflow/core/json_utils.py` — The shared JSON utility (Task 105)

### Task Reviews (Read for Context)
- `.taskmaster/tasks/task_105/task-review.md` — Auto-parse JSON during template traversal
- `.taskmaster/tasks/task_103/task-review.md` — Type preservation in templates
- `.taskmaster/tasks/task_12/task-review.md` — Original LLM node implementation
- `.taskmaster/tasks/task_66/research/llm-json-generation-failures.md` — Task 66 research

### Auto-Parse Points (The Full Inventory)
- `src/pflow/nodes/llm/llm.py:67-71` — #1 LLM node (REMOVE)
- `src/pflow/runtime/template_resolver.py:202-231` — #2 Traversal parsing (KEEP)
- `src/pflow/runtime/template_resolver.py:632-638` — #3 resolve_nested (KEEP, watch)
- `src/pflow/runtime/node_wrapper.py:827-842` — #4 Type coercion (KEEP)
- `src/pflow/runtime/batch_node.py:262-271` — #5 Batch items (KEEP)
- `src/pflow/cli/main.py:973-997` + `src/pflow/execution/formatters/success_formatter.py:120-141` — #6 Display (KEEP)

### Industry References
- LangChain uses explicit OutputParsers, never auto-parses
- Vercel AI SDK deprecated `generateObject()`, unified into `generateText()` with explicit `output` schema
- n8n has separate "Structured Output Parser" nodes between LLM and consumers
- Simon Willison's `llm` library returns raw text, no auto-parsing

## For the Next Agent

**Start by**: Asking the user to confirm the direction. We reached soft consensus on "remove LLM auto-parsing" but the user hasn't given explicit approval. They may want to discuss implementation approach (new task vs. part of Task 66, etc.).

**Don't bother with**: Re-investigating the bug or re-reading all the task reviews. The analysis is complete. The bug is verified. The inventory is done.

**The user cares most about**: Architectural integrity and alignment with best practices. They will redirect you if you try to jump to code. Lead with design reasoning, not implementation details.

**When implementing**: The actual code change is tiny — delete `parse_json_response()`, change line 178 in `post()` to store raw string. But update the tests and the docstring (`any` → `str`). Consider implications for Task 84's type checker.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
