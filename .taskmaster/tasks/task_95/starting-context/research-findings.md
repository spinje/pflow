# Research Findings: LLM Model Handling Investigation

> **Status**: Research phase complete, implementation not started
> **Confidence levels indicated for each finding**

---

## Finding 1: The Monkey-Patch Location

**Confidence: HIGH (verified via grep)**

`install_anthropic_model()` is called in these locations:

| File | Lines | Context |
|------|-------|---------|
| `src/pflow/cli/main.py` | 3549-3550 | Called for ALL workflow executions |
| `src/pflow/cli/registry.py` | 645-647 | `registry discover` command |
| `src/pflow/cli/commands/workflow.py` | 142-144 | `workflow discover` command |
| `src/pflow/cli/commands/workflow.py` | 264-266 | Another `workflow discover` variant |
| `src/pflow/mcp_server/main.py` | 41-43 | MCP server startup |

**Key observation**: `main.py:3550` is called BEFORE workflow type is determined, affecting ALL workflows.

**NOT YET VERIFIED**:
- Whether there are other code paths that install the patch
- Whether the patch persists across function calls or is re-installed

---

## Finding 2: The Monkey-Patch Implementation

**Confidence: HIGH (verified via code read)**

Location: `src/pflow/planning/utils/anthropic_llm_model.py:272-299`

```python
def install_anthropic_model() -> None:
    import llm
    original_get_model = llm.get_model

    def get_model_with_anthropic(name: Optional[str] = None, _skip_async: bool = False) -> Any:
        is_anthropic_model = name and (
            name.startswith("anthropic/") or
            name.startswith("claude-") or
            "claude" in name.lower()
        )

        if is_anthropic_model and name is not None:
            return AnthropicLLMModel(name)
        else:
            return original_get_model(name, _skip_async)

    llm.get_model = get_model_with_anthropic
```

**Key observation**: ANY model name containing "claude" (case-insensitive) gets intercepted.

**NOT YET VERIFIED**:
- Whether this function is idempotent (safe to call multiple times)
- Whether there's cleanup/uninstall functionality

---

## Finding 3: AnthropicLLMModel Stores But Ignores User's Model

**Confidence: HIGH (verified via code read)**

Location: `src/pflow/planning/utils/anthropic_llm_model.py:25-35`

```python
def __init__(self, model_name: str = "claude-sonnet-4-20250514"):
    self.model_name = model_name  # Stored here
    self.model_id = model_name   # And here (for compatibility)
    api_key = self._get_api_key()
    self.client = AnthropicStructuredClient(api_key=api_key)  # But client is created without it
```

**Key observation**: `model_name` is stored but never passed to `AnthropicStructuredClient`.

**NOT YET VERIFIED**:
- Whether `model_name` is used anywhere else in `AnthropicLLMModel`
- Whether there's a reason for this design

---

## Finding 4: AnthropicStructuredClient Has Hardcoded Model

**Confidence: HIGH (verified via code read)**

Location: `src/pflow/planning/utils/anthropic_structured_client.py:67`

```python
self.model = "claude-sonnet-4-20250514"  # Model specified in requirements
```

This hardcoded model is used in all API calls:
- Line 160: `"model": self.model`
- Line 296: `"model": self.model`
- Line 385: `"model": self.model`

**Key observation**: ALL Claude models are redirected to `claude-sonnet-4-20250514` regardless of user input.

**NOT YET VERIFIED**:
- Whether `claude-sonnet-4-20250514` is a valid Anthropic API model
- Whether this model has different behavior for large inputs
- Why this design decision was made (intentional for planner? oversight?)

---

## Finding 5: Registry Run Does NOT Install Monkey-Patch

**Confidence: HIGH (verified via grep)**

`src/pflow/cli/registry_run.py` has NO calls to `install_anthropic_model()`.

This explains why `registry run` and workflow execution behave differently:
- `registry run`: Uses original `llm` library → strict validation
- Workflow: Uses monkey-patched `llm.get_model()` → intercepts Claude models

**NOT YET VERIFIED**:
- Whether this was intentional or an oversight
- Whether there are any other differences between the two paths

---

## Finding 6: LLM Node Error Handling Pattern

**Confidence: MEDIUM (read but not traced end-to-end)**

Location: `src/pflow/nodes/llm/llm.py`

The LLM node follows PocketFlow retry pattern:
1. `exec()` has NO try/except - lets exceptions bubble up
2. After max retries, `exec_fallback()` is called
3. `exec_fallback()` returns error dict with `status="error"`
4. `post()` checks for error and returns `"error"` action

**Key observation**: Errors should NOT be silently swallowed. If the monkey-patch is installed and routes to `AnthropicLLMModel`, exceptions would be handled differently.

**NOT YET VERIFIED**:
- The complete error flow through `AnthropicLLMModel` and `AnthropicStructuredClient`
- Whether `AnthropicStructuredClient` has error handling that swallows errors
- Why large inputs return empty responses

---

## Finding 7: Planner Needs Monkey-Patch Features

**Confidence: MEDIUM (inferred from code structure)**

`AnthropicLLMModel` provides:
1. **Prompt caching** - via `cache_blocks` parameter
2. **Thinking tokens** - via `thinking_budget` parameter
3. **Structured output** - via Pydantic schema integration

These are Anthropic SDK features not available through the generic `llm` library.

**NOT YET VERIFIED**:
- Whether the planner actually uses all these features
- Whether there's an alternative way to provide these features
- Whether the `llm` library has plugins for these features

---

## Finding 8: Workflow Execution Path

**Confidence: MEDIUM (traced via search, not executed)**

```
main.py:workflow_command()
  → main.py:3550 _install_anthropic_model_if_needed()  # PATCH INSTALLED HERE
  → ... workflow resolution ...
  → execute_json_workflow() or planner flow
  → executor_service.execute_workflow()
  → compiler.compile_ir_to_flow()
  → flow.run()
  → InstrumentedNodeWrapper._run()
  → LLM node calls llm.get_model()  # PATCH INTERCEPTS HERE
```

**NOT YET VERIFIED**:
- The exact control flow in `workflow_command()`
- Where the branch between file/saved/NL workflows occurs
- Whether the patch can be moved after the branch point

---

## Unresolved Questions

1. **Why do large inputs return empty responses?**
   - Is this `AnthropicStructuredClient` error handling?
   - Is this the Anthropic API behavior for the hardcoded model?
   - Is this rate limiting or token limits?

2. **Is `claude-sonnet-4-20250514` a valid model?**
   - The `llm` library doesn't list it
   - But it might be valid at the Anthropic API level
   - The naming pattern suggests a dated model release

3. **Where exactly does workflow type get determined?**
   - Need to trace `workflow_command()` to find the branch point
   - This determines where to move the monkey-patch

4. **Are there tests that depend on current behavior?**
   - Some tests might be inadvertently relying on the hardcoded model
   - Need to run test suite after any changes

---

## Conclusions (To Be Verified by Implementing Agent)

Based on this research, the likely explanation is:

1. **Root cause**: Monkey-patch at `main.py:3550` is called too early, affecting all workflows
2. **Secondary issue**: `AnthropicStructuredClient` hardcodes the model, ignoring user input
3. **Fix approach**: Move monkey-patch to only the planner code path

**IMPORTANT**: These conclusions are based on code reading and grep searches. The implementing agent should:
- Verify the actual runtime behavior
- Trace the code execution path
- Test the hypotheses before implementing fixes
- Draw their own conclusions based on evidence

---

> **NOTE TO IMPLEMENTING AGENT**: Do not assume these findings are complete or correct. Use them as starting points for your own investigation. The code may have changed, or there may be runtime behavior not captured in static analysis.
