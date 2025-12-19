# Task 95 Handoff Memo: LLM Unification & Bug Fix

## Critical Discovery: The Real Bug

**The bug is NOT about model validation.** The bug is that **ALL Claude models are silently redirected to a hardcoded model**, and the user's model choice is completely ignored.

Here's what actually happens:

```
User specifies: model="claude-sonnet-4.5"
                    ↓
AnthropicLLMModel stores: self.model_name = "claude-sonnet-4.5"  (IGNORED!)
                    ↓
AnthropicStructuredClient hardcodes: self.model = "claude-sonnet-4-20250514"
                    ↓
API call uses: "claude-sonnet-4-20250514"  (ALWAYS)
```

The symptoms in the bug report (invalid models "working", valid models failing in registry run) are just manifestations of this deeper issue.

---

## The Exact Code Flow (with line numbers)

### Why Workflows Accept Any Claude Model

1. **`src/pflow/cli/main.py:3550`** - `_install_anthropic_model_if_needed(verbose)` is called for ALL workflow executions (not just planner)

2. **`src/pflow/planning/utils/anthropic_llm_model.py:272-299`** - `install_anthropic_model()` monkey-patches `llm.get_model()`:
   ```python
   def get_model_with_anthropic(name, ...):
       if name.startswith("claude-") or "claude" in name.lower():
           return AnthropicLLMModel(name)  # Intercepts ALL Claude models
       return original_get_model(name)
   ```

3. **`src/pflow/planning/utils/anthropic_llm_model.py:25-35`** - `AnthropicLLMModel.__init__()`:
   ```python
   self.model_name = model_name  # Stored but NEVER USED
   self.client = AnthropicStructuredClient(api_key=api_key)  # Creates client
   ```

4. **`src/pflow/planning/utils/anthropic_structured_client.py:67`** - The hardcoded model:
   ```python
   self.model = "claude-sonnet-4-20250514"  # ALWAYS uses this model
   ```

### Why Registry Run Fails

`src/pflow/cli/registry_run.py` NEVER calls `install_anthropic_model()`. So:
- `llm.get_model("claude-sonnet-4-5")` → Original `llm` library → Validates strictly → Rejects invalid models

---

## Key Files (Priority Order)

### Phase 1 - Bug Fix

| File | What to Do | Lines |
|------|------------|-------|
| `src/pflow/cli/main.py` | Move `_install_anthropic_model_if_needed()` to planner-only path | ~3549-3550 |
| `src/pflow/cli/main.py` | Identify where workflow type is determined (file vs NL) | Search for workflow resolution logic |

### Phase 2+ - Discovery Migration

| File | What to Do |
|------|------------|
| `src/pflow/cli/registry.py:645-647` | Remove `install_anthropic_model()` from `registry discover` |
| `src/pflow/cli/commands/workflow.py:142-144, 264-266` | Remove from `workflow discover` |
| `src/pflow/core/smart_filter.py` | Replace Anthropic with `llm` library |

---

## The Fix Strategy

The fix is about **WHEN** the monkey-patch is installed, not about removing it entirely.

**Current (broken):**
```python
# main.py workflow_command() - line 3550
_install_anthropic_model_if_needed(verbose)  # Called for ALL workflows
# ... later ...
# workflow resolution happens here
```

**Fixed:**
```python
# main.py workflow_command()
# ... workflow resolution happens here ...
if is_natural_language_input:  # Only for planner path
    _install_anthropic_model_if_needed(verbose)
```

The challenge: You need to identify WHERE in `workflow_command()` the code branches between:
1. File-based workflow (`pflow workflow.json`)
2. Saved workflow (`pflow my-saved-workflow`)
3. Natural language (`pflow "do something"`)

Only path 3 should get the monkey-patch.

---

## Critical Understanding: Why the Planner Needs the Monkey-Patch

`AnthropicLLMModel` provides features the planner needs:
1. **Prompt caching** - Multi-block cache control for cost optimization
2. **Thinking tokens** - Extended thinking budget allocation
3. **Structured output** - Pydantic model validation via tool use

User workflows do NOT need these features. They just need `llm.get_model()` to work normally.

---

## Testing Gotchas

### What the Bug Fix Tests MUST Verify

1. **Invalid Claude model → proper error**
   ```bash
   pflow workflow.json  # where workflow has model="totally-fake-claude"
   # Expected: Error from llm library about unknown model
   ```

2. **Valid Claude model → uses that model (not hardcoded)**
   ```bash
   pflow workflow.json  # where workflow has model="claude-sonnet-4.5"
   # Expected: Trace shows claude-sonnet-4.5 was used, NOT claude-sonnet-4-20250514
   ```

3. **Registry run and workflow behave identically**
   ```bash
   pflow registry run llm prompt="Hi" model="claude-sonnet-4.5"
   pflow /tmp/workflow.json  # same model
   # Expected: Both succeed or both fail the same way
   ```

4. **Natural language planner still works**
   ```bash
   pflow "create a poem about cats"
   # Expected: Planner uses Anthropic features successfully
   ```

### Watch Out For

- The monkey-patch is **GLOBAL** and **PERSISTENT** within a Python process
- Once installed, it affects ALL subsequent `llm.get_model()` calls
- Tests might pass individually but fail when run together if patch leaks between tests
- Check for `PYTEST_CURRENT_TEST` environment variable - some code skips the patch during tests

---

## User Context: Planner Deprecation

The user mentioned:
> "the planner should be deprecated or migrated to use the claude code node (Task 92)"

This means:
- The monkey-patch is **temporary technical debt**
- Task 92 will eventually remove the need for `AnthropicLLMModel` entirely
- For now, we just need to scope it properly (not remove it)

---

## Questions to Investigate During Implementation

1. **Where exactly is workflow type determined?**
   - Search for `resolve_workflow` or similar in `main.py`
   - Need to find the exact branch point

2. **Are there tests that depend on the current (buggy) behavior?**
   - Run `make test` after the fix to see what breaks
   - Some tests might be inadvertently relying on the hardcoded model

3. **Does `_install_anthropic_model_if_needed()` have idempotency protection?**
   - Check if calling it twice causes issues
   - The planner path might call it again after you move it

4. **What happens if the planner is invoked but the patch isn't installed?**
   - The planner nodes use `llm.get_model()` internally
   - Need to ensure the patch is installed BEFORE any planner node runs

---

## Files to Read First

1. **`src/pflow/cli/main.py`** - Find the workflow resolution logic and the `_install_anthropic_model_if_needed()` call
2. **`src/pflow/planning/utils/anthropic_llm_model.py`** - Understand the full monkey-patch
3. **`src/pflow/nodes/llm/llm.py`** - See how LLM node uses `llm.get_model()` (this is what should work for user workflows)

---

## Anti-Patterns to Avoid

1. **Don't remove the monkey-patch entirely** - The planner still needs it
2. **Don't try to "fix" AnthropicStructuredClient to use user's model** - That's a bigger refactor for Task 92
3. **Don't add model validation inside AnthropicLLMModel** - The goal is to NOT use AnthropicLLMModel for user workflows

---

## Summary: The One-Liner Fix

Move `_install_anthropic_model_if_needed(verbose)` from "always called" to "only called when entering natural language planner path."

Everything else in Task 95 (discovery migration, smart filtering, configuration) can come after this bug fix is in place.

---

**IMPORTANT: Do not begin implementing yet.** Read this memo, review the task spec at `.taskmaster/tasks/task_95/task-95.md`, and confirm you understand the approach before proceeding. Reply that you are ready to begin.
