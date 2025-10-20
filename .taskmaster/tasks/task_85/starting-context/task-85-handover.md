# Task 85 Handoff Memo: Runtime Template Resolution Hardening

**From**: Claude (Sonnet 4.5) - Context Window Session ending 2025-10-20
**To**: Next implementation agent
**Context**: Post-Fix 3 (Schema-Aware Type Checking), discovered by AI agent in production testing

---

## 🎯 Core Insight: This Isn't a Bug Fix, It's a Philosophy Change

**Critical Understanding**: The current behavior where unresolved templates remain as literal `${variable}` text is **INTENTIONAL**, not a bug. It's documented in architecture:

> "Unresolved templates: Remain for debugging visibility"

**Why it exists**: During development, seeing `${var}` in output helps developers debug which templates failed to resolve.

**Why it's catastrophic**: In production, this "debugging visibility" becomes **silent data corruption** where literal template strings end up in Slack messages, Google Sheets, and other user-facing outputs.

**Your challenge**: You're not fixing a bug, you're **changing a deliberate design decision** from "fail-soft for debugging" to "fail-hard for data integrity."

---

## 🔥 The Real Production Impact

**Source**: [GitHub Issue #95](https://github.com/spinje/pflow/issues/95) - AI agent's bug report

### What Actually Happened:

An AI agent building workflows discovered this while testing `slack-qa-responder`:

```
Workflow Output:
  ⚠️ analyze-questions (Nonems)
  ⚠️ save-message (Nonems)
  ✓ Workflow successful: True

Slack Message Received:
  "${save-message.stdout}"  ← Literal text sent to users!
```

**The emotional weight**: The agent said:
> "I only discovered it because I tested it manually. If this were automated (running on schedule), **broken Q&A would have been posted to Slack indefinitely** until someone noticed."

This isn't theoretical - this happened in real workflow testing, and the current behavior gave NO indication that something was wrong (just cryptic "Nonems" warnings).

---

## 🧩 Relationship to Fix 3 (Critical Distinction)

**You MUST understand**: Task 85 is NOT an extension of Fix 3. They're complementary but solve different problems at different stages.

### Fix 3: Schema-Aware Type Checking (COMPLETED)

**Problem**: Type mismatches at compile-time
```python
${llm.response}     # response exists, but is type 'dict'
↓                   # parameter expects 'str'
❌ Caught during validation BEFORE execution
```

**Solution**: `src/pflow/runtime/type_checker.py` - validates types match schemas

**What it catches**:
- `dict` → `str` parameter mismatches
- `int` → `str` mismatches
- Shows available fields with correct types

**File**: `src/pflow/runtime/type_checker.py` (221 lines)
**Tests**: `tests/test_runtime/test_type_checker.py` (25 tests)
**Integration**: Called from `template_validator.py` during compilation

### Task 85: Runtime Template Resolution (TODO)

**Problem**: Empty/failed node outputs at runtime
```python
${save-message.stdout}  # field exists in schema
↓                       # but save-message node FAILED at runtime
↓                       # stdout is empty/null
↓ Template can't resolve
↓ Current behavior: use literal "${save-message.stdout}"
❌ Sent to Slack as broken text
```

**Solution**: Detect unresolved templates BEFORE they reach external APIs

**What you're catching**:
- Nodes that fail/produce no output
- Templates that can't resolve due to missing data
- Literal `${...}` syntax in final output

---

## 📍 The Architecture You're Changing

### Current Template Resolution Flow

**Location**: `src/pflow/runtime/node_wrapper.py` lines 209-216 in `TemplateAwareNodeWrapper._run()`

```python
# Current behavior (from my code review):
for key, template in self.template_params.items():
    resolved_value, is_simple_template = self._resolve_template_parameter(
        key, template, context
    )
    resolved_params[key] = resolved_value

    # ⚠️ ERROR CHECK ONLY FOR COMPLEX TEMPLATES
    if not is_simple_template:  # ← This is the problem
        if resolved_value != template:
            # Success
            pass
        elif "${" in str(template):
            # This SHOULD fail but is skipped for simple templates
            raise ValueError(f"Template {template} could not resolve")
```

**The bug in current code**: Error detection is SKIPPED for simple templates (`${var}` format) because `is_simple_template = True`.

**Why this matters**: Most templates are simple (`${node.output}`), so most failures are never caught!

### The Template Wrapper Chain

Templates are resolved through this wrapper chain (from outer to inner):

```
InstrumentedNodeWrapper       ← Metrics, tracing, caching (your target!)
  └─ NamespacedNodeWrapper    ← Collision prevention
      └─ TemplateAwareNodeWrapper  ← Template resolution (current location)
          └─ ActualNode       ← Business logic
```

**Key insight**: You should add detection at the **InstrumentedNodeWrapper** level (outermost), not inside TemplateAwareNodeWrapper, because:

1. You want to check AFTER resolution is complete
2. You want to check BEFORE data enters shared store
3. You want metrics/tracing of these failures
4. InstrumentedNodeWrapper already handles errors and warnings

**File to modify**: `src/pflow/runtime/instrumented_wrapper.py`
**Current size**: 1168 lines (has space for this feature)

---

## 🔍 The Mystery of "Nonems"

**What the agent saw**: `⚠️ save-message (Nonems)`

**What I couldn't find**: Where "Nonems" comes from in the codebase.

**Your investigation TODO**:
1. Search for "Nonems" in the codebase
2. Likely it's error aggregation or a display bug
3. Might be related to `None` being stringified incorrectly
4. Check `src/pflow/execution/display_manager.py` (execution UX)
5. Check `src/pflow/runtime/workflow_trace.py` (trace formatting)

**Why this matters**: Understanding "Nonems" will tell you WHERE errors are being swallowed and help you fix error messaging.

---

## 🎛️ The Strict/Permissive Decision (Not Fully Specified)

The task says "Add strict/permissive mode" but doesn't specify:

### What I Discussed with User:

**Strict Mode (Recommended Default)**:
- ANY template resolution failure → fail workflow immediately
- No literal `${...}` ever reaches output
- Clear error with context
- User explicitly chooses this

**Permissive Mode (Current Behavior, Improved)**:
- Template fails → use empty string or null
- Log warning with context
- Mark workflow as "degraded" not "success"
- Continue execution

### What's NOT Decided:

1. **What's the default?**
   - I suggested strict (user agreed conceptually)
   - But this is a breaking change for existing workflows
   - MVP has zero users, so we CAN break things

2. **What's the fallback value in permissive mode?**
   - Empty string `""`?
   - Null `None`?
   - Literal template (current)?
   - Configurable?

3. **How do users configure this?**
   ```json
   {
     "workflow_config": {
       "template_resolution_mode": "strict",  // or "permissive"?
       "allow_partial_failure": false
     }
   }
   ```
   - Is this per-workflow or global setting?
   - Can it be overridden per-node?

4. **How does this interact with existing error handling?**
   - Some nodes already have retry logic
   - Some workflows use try/catch patterns
   - Does strict mode bypass these?

**Your decision**: You need to propose concrete defaults and get user approval before implementing.

---

## 🎯 Integration Points (Where and Why)

### 1. Detection Point (Critical)

**Where**: `src/pflow/runtime/instrumented_wrapper.py` in `_run()` method

**Why**:
- Outermost wrapper, sees final resolved values
- Already handles errors and tracing
- Perfect place to validate output before it enters shared store

**What to check**:
```python
# After node execution, before storing in shared store:
def _validate_no_unresolved_templates(output: Any) -> None:
    """Detect if output contains literal ${...} syntax."""
    if isinstance(output, str):
        if "${" in output:
            # Check if it's a real template or escaped
            if not is_escaped(output):
                raise TemplateResolutionError(...)
    elif isinstance(output, dict):
        for value in output.values():
            _validate_no_unresolved_templates(value)
    elif isinstance(output, list):
        for item in output:
            _validate_no_unresolved_templates(item)
```

### 2. Error Formatting

**Where**: `src/pflow/execution/display_manager.py`

**Why**: This is where "Nonems" probably gets displayed

**What to change**:
```python
# Instead of:
"⚠️ save-message (Nonems)"

# Show:
"❌ save-message (shell): No output produced
   • Command: cat
   • Exit code: 0
   • stdout: (empty)
   • stderr: (none)
   • Breaks downstream: ${save-message.stdout} in 'send-slack-response'"
```

### 3. Workflow Status

**Where**: `src/pflow/execution/executor_service.py` and `src/pflow/runtime/workflow_trace.py`

**Why**: Need to distinguish success/degraded/failed status

**Current**: Boolean `successful: True`
**Needed**: Tri-state status
```python
{
  "workflow_status": "partial_failure",  # or "success", "failed"
  "overall_success": false
}
```

### 4. Configuration Schema

**Where**: `src/pflow/core/ir_schema.py`

**Why**: Need to add config options for strict/permissive mode

**What to add**:
```python
workflow_config = {
    "template_resolution_mode": "strict",  # or "permissive"
    "template_fallback_value": None,       # for permissive mode
    "allow_partial_failure": False
}
```

---

## ⚠️ Hidden Gotchas (From My Investigation)

### 1. False Positives: Legitimate `${...}` in Output

**Problem**: What if user WANTS literal `${variable}` in output?

**Examples**:
- Documentation: "Use ${config.api_key} to configure..."
- JSON strings: `{"template": "${user.name}"}`
- Shell scripts: `echo "${VAR}"`

**Solution Ideas**:
1. Escape syntax: `\${variable}` → output as `${variable}`
2. Only check pflow-generated templates (track them somehow)
3. Configuration: disable checking for specific nodes

**Your decision**: Pick an approach and document it clearly.

### 2. MCP Nodes Return Dynamic Data

**Problem**: MCP nodes might return data containing `${...}` syntax

**Example**: Fetching a GitHub issue description that contains template syntax in the markdown

**Solution**: Only check **pflow template parameters**, not arbitrary node output

**How**:
- Mark which strings came from template resolution
- Only validate those, not raw node outputs
- Or: whitelist MCP nodes from checking

### 3. Performance: Checking Every Output

**Problem**: Recursively checking dicts/lists for `${` could be expensive

**Mitigation**:
- Only check in strict mode (optional for permissive)
- Only check string values (skip large binary data)
- Short-circuit on first match (don't find all)
- Cache check results per node

**Benchmarking**: Add performance tests for large workflows (50+ nodes)

### 4. Template Variables in JSON Strings

**Tricky case**:
```python
output = '{"message": "${user.name}"}'  # JSON string containing template
```

**Is this**:
- Unresolved template that should fail? ✅ Probably yes
- Legitimate JSON content? ❌ Probably not

**Implication**: Simple string checking IS correct, but you need to be aware of this case for error messages.

---

## 🔬 What Fix 3 Taught Me (Patterns to Reuse)

I just implemented Fix 3 (type checking), and these patterns worked well:

### 1. Error Messages with Concrete Suggestions

**Pattern**: When validation fails, show what's ACTUALLY available, not generic advice

**Example from Fix 3**:
```
❌ Type mismatch: ${issue.author} has type 'dict' but expects 'str'

💡 Available fields with correct type:
   - ${issue.author.id}
   - ${issue.author.login}
   - ${issue.author.name}
```

**Apply to Task 85**:
```
❌ Template ${save-message.stdout} could not resolve

Context:
  • Node 'save-message' produced no output
  • Exit code: 0
  • stdout: (empty)

💡 Check if:
   - Node 'save-message' is configured correctly
   - Upstream data is available
   - Command actually produces output
```

### 2. Integration into Existing Validation Pipeline

**Pattern**: Extend, don't replace

**Fix 3**: Added to `template_validator.py`, didn't create new validator

**Task 85**: Extend `InstrumentedNodeWrapper`, don't create new wrapper

### 3. Comprehensive Test Coverage

**Pattern**: Unit + Integration + Real-world tests

**Fix 3 Tests**:
- 25 unit tests (type compatibility, inference, lookup)
- 9 integration tests (workflows with type errors)
- Real workflow validation (slack-qa-responder)

**Task 85 Should Have**:
- Unit tests: Detect `${...}` in strings/dicts/lists
- Integration tests: Workflow fails before Slack message sent
- Real-world test: The exact slack-qa-responder scenario from Issue #95

---

## 📚 Critical Files to Read

### Must Read (Before Starting):

1. **`src/pflow/runtime/instrumented_wrapper.py`** (1168 lines)
   - Where you'll add detection logic
   - Look at lines 518-603 (checkpoint system) for patterns
   - Look at lines 737-1129 (API error detection) for similar validation

2. **`src/pflow/runtime/node_wrapper.py`** (285 lines)
   - Current template resolution (lines 209-216)
   - Understand `is_simple_template` bug
   - See how templates are resolved

3. **`src/pflow/runtime/template_resolver.py`** (385 lines)
   - Core resolution engine
   - `has_templates()` - detects `${...}` syntax
   - `extract_variables()` - gets variable names
   - Reuse these instead of regex

### Should Read (For Context):

4. **`src/pflow/runtime/template_validator.py`** (1118 lines)
   - How Fix 3 does compile-time validation
   - Pattern for generating helpful errors (lines 1075-1117)
   - Shows how to traverse nested structures

5. **`src/pflow/execution/executor_service.py`**
   - Main workflow execution entry point
   - Where workflow status is determined
   - Where you'll add tri-state success/degraded/failed

6. **`architecture/runtime/CLAUDE.md`**
   - Complete documentation of runtime system
   - Wrapper chain explanation
   - Error handling patterns

### For Error Messages:

7. **`src/pflow/execution/display_manager.py`**
   - Execution UX display coordination
   - Where "Nonems" likely comes from
   - Where you'll improve error formatting

8. **`src/pflow/runtime/workflow_trace.py`** (517 lines)
   - Trace collection format
   - Where error details are stored
   - Add resolution failure tracking here

---

## 🧪 Test Strategy Deep Dive

### The Exact Scenario to Reproduce (from Issue #95):

```python
def test_slack_qa_responder_empty_output():
    """
    Reproduce the exact bug from GitHub Issue #95:
    - LLM node produces response
    - Shell node (cat) receives input but produces empty output
    - Slack node tries to use ${shell.stdout}
    - In current code: Literal "${shell.stdout}" sent to Slack
    - Expected: Workflow fails before Slack message sent
    """
    workflow = {
        "nodes": [
            {
                "id": "analyze",
                "type": "llm",
                "params": {"prompt": "Analyze this"}
            },
            {
                "id": "save",
                "type": "shell",
                "params": {
                    "stdin": "${analyze.response}",
                    "command": "cat"  # Will fail if input is empty
                }
            },
            {
                "id": "slack",
                "type": "mcp-slack-SEND_MESSAGE",
                "params": {
                    "channel": "C123",
                    "text": "${save.stdout}"  # This will be literal if save fails
                }
            }
        ]
    }

    # In strict mode: Should raise TemplateResolutionError
    # In permissive mode: Should show degradation warning
```

### Edge Cases to Test:

1. **Empty string vs null vs missing**:
   - Node returns `""` (empty string)
   - Node returns `None`
   - Node doesn't set the output key at all
   - Each should be handled differently

2. **Escaped templates**:
   - Input: `"Use \\${config.key}"`
   - Should output: `"Use ${config.key}"` (not fail)

3. **Templates in nested data**:
   - `{"data": {"nested": "${var}"}}`
   - Should detect even in deep nesting

4. **MCP node responses**:
   - MCP returns `{"message": "Use ${variable}"}`
   - Is this a failure or legitimate data?

5. **Partial resolution**:
   - Template `"Hello ${name}, age ${age}"`
   - `name` resolves, `age` doesn't
   - Should fail even if partial success

---

## 🎨 Design Decisions You Need to Make

### 1. Default Mode

**Question**: Strict or permissive by default?

**Considerations**:
- **Strict**: Safer, fails loudly, catches bugs
- **Permissive**: More flexible, allows degraded operation
- **MVP**: Zero users, can change later
- **My recommendation**: Strict (but get user approval)

### 2. Escape Syntax

**Question**: How do users output literal `${...}` if they need to?

**Options**:
- `\${variable}` → `${variable}` (escaped)
- `$$${variable}` → `${variable}` (doubled)
- No escaping (can't output literal templates)
- Config flag to disable checking

**Recommendation**: Start with backslash escaping (common pattern)

### 3. Fallback Value (Permissive Mode)

**Question**: What value to use when template can't resolve?

**Options**:
- Empty string `""`
- Null `None`
- Literal template (current)
- Configurable per-workflow

**Recommendation**: Empty string (least surprising for string contexts)

### 4. Configuration Scope

**Question**: Where is mode configured?

**Options**:
- Global setting (all workflows)
- Per-workflow (in IR)
- Per-node (some strict, some permissive)

**Recommendation**: Per-workflow with global default

### 5. Error vs Warning

**Question**: In strict mode, should unresolved templates raise exceptions or just log?

**Options**:
- Raise exception (fail immediately)
- Return error status (fail gracefully)
- Both (log then raise)

**Recommendation**: Raise exception (clear failure signal)

---

## 🚨 What Could Go Wrong

### If You Get It Wrong:

1. **False positives break valid workflows**
   - User has legitimate `${...}` in output
   - Documentation workflows fail
   - JSON data with template syntax rejected

2. **Performance degradation**
   - Checking every output is expensive
   - Large workflows timeout
   - Recursive checking causes stack overflow

3. **Breaking changes users didn't expect**
   - Existing workflows suddenly fail
   - No migration path
   - User backlash (but we have zero users!)

4. **Mode confusion**
   - User thinks they're in strict mode but aren't
   - Or vice versa
   - Inconsistent behavior

### How to Avoid:

1. **Test with real workflows** (slack-qa-responder, etc.)
2. **Performance benchmarks** (50+ node workflows)
3. **Clear documentation** on mode differences
4. **Good error messages** so users understand failures
5. **Escape syntax** for edge cases

---

## 💡 Hidden Insights (What I Wish I Knew Earlier)

### 1. The "Nonems" Mystery is Important

Don't skip investigating "Nonems". It's a clue about:
- Where errors are being swallowed
- How the display system works
- What the current error handling does

**Finding it will save you time** understanding the error flow.

### 2. Template Resolution Happens in Multiple Places

It's not just `TemplateAwareNodeWrapper`:
- Initial params get resolved in compiler
- Runtime resolution in node wrapper
- Nested workflows have their own resolution
- Each place might need checking

**Map the full flow** before you start coding.

### 3. The Wrapper Chain is Your Friend

The three-wrapper chain (Instrumented → Namespaced → Template) is genius:
- Each layer has a single responsibility
- Easy to add behavior at the right level
- Doesn't break existing code

**Work with it, not against it.**

### 4. Agent's Feedback is Gold

The agent's bug report ([Issue #95](https://github.com/spinje/pflow/issues/95)) is incredibly detailed:
- Real production scenario
- Clear before/after expectations
- Emotional context (frustration with misleading success)
- Specific improvement suggestions

**Treat this as your requirements spec.** The agent is your user.

### 5. This Isn't About Adding, It's About Changing

You're not adding a feature, you're **changing behavior**:
- Current: "fail-soft, debug-friendly"
- New: "fail-hard, production-safe"

This is a **philosophy shift**, not just code changes.

---

## 🎯 Success Criteria (How You'll Know You're Done)

### 1. The Exact Bug is Fixed

Run this test and it should PASS:

```python
# The slack-qa-responder scenario from Issue #95
# Node fails → template can't resolve → workflow FAILS before Slack
```

### 2. Error Messages Are Clear

Instead of:
```
⚠️ save-message (Nonems)
✓ Workflow successful
```

Show:
```
❌ save-message (shell): No output produced
   • Affects: ${save-message.stdout} in 'send-slack-response'
   • Workflow status: FAILED
```

### 3. Strict Mode Works

```python
# In strict mode:
# - Unresolved template → workflow fails immediately
# - Clear error with context
# - No literal ${...} in output
assert workflow_fails_loudly()
```

### 4. Permissive Mode Works

```python
# In permissive mode:
# - Unresolved template → empty string
# - Warning logged
# - Workflow marked as "degraded" not "success"
assert workflow_continues_with_warning()
```

### 5. No False Positives

```python
# Legitimate use cases still work:
# - Escaped templates: \${var} → ${var}
# - MCP responses with ${...} syntax
# - Documentation workflows
assert valid_workflows_pass()
```

### 6. Performance is Acceptable

```python
# Large workflows don't timeout:
# - 50+ nodes
# - Nested data structures
# - <100ms overhead per node
assert performance_acceptable()
```

---

## 🤔 Questions I Couldn't Answer (Investigate These)

### 1. Where Does "Nonems" Come From?

Search the codebase:
```bash
grep -r "Nonems" src/
grep -r "None.*ms" src/  # Maybe it's "None" + "ms"?
```

Check:
- `display_manager.py`
- `workflow_trace.py`
- Error aggregation logic

### 2. Is There Existing Strict/Permissive Infrastructure?

Check if pflow already has:
- Configuration for error handling modes
- Workflow-level settings
- Per-node error handling options

Don't reinvent if it exists!

### 3. How Do Nested Workflows Handle This?

When workflow A calls workflow B:
- Does B's template failure affect A?
- Are they isolated or shared?
- What's the error propagation?

Check: `src/pflow/runtime/workflow_executor.py`

### 4. What About the Repair System?

From architecture docs, there's a repair/retry system:
- Does it affect this?
- Should unresolved templates trigger repair?
- Or is repair for different errors?

Check: `src/pflow/execution/repair_service.py`

---

## 📋 Implementation Checklist (High Level)

**Before you code**:
- [ ] Read all critical files listed above
- [ ] Find where "Nonems" comes from
- [ ] Map complete template resolution flow
- [ ] Decide: strict or permissive default?
- [ ] Decide: escape syntax for literal templates
- [ ] Get user approval on design decisions

**Core implementation**:
- [ ] Add detection logic to `instrumented_wrapper.py`
- [ ] Implement recursive checking for dicts/lists
- [ ] Add escape syntax handling
- [ ] Add strict/permissive mode configuration
- [ ] Update error message formatting
- [ ] Fix workflow success/degraded/failed status

**Testing**:
- [ ] Write test for exact Issue #95 scenario
- [ ] Test strict mode (fails on unresolved)
- [ ] Test permissive mode (continues with warning)
- [ ] Test escape syntax
- [ ] Test nested data structures
- [ ] Test MCP nodes
- [ ] Test performance with large workflows

**Integration**:
- [ ] Update IR schema for config
- [ ] Update architecture docs
- [ ] Add migration guide (if needed)
- [ ] Update error message catalog

---

## 🔗 Key References

1. **[GitHub Issue #95](https://github.com/spinje/pflow/issues/95)** - Original bug report (YOUR REQUIREMENTS)
2. **Fix 3 Implementation** - Pattern reference:
   - `src/pflow/runtime/type_checker.py` (type checking)
   - `tests/test_runtime/test_type_checker.py` (test patterns)
3. **Architecture Docs**:
   - `architecture/runtime/CLAUDE.md` (wrapper chain, error handling)
   - `src/pflow/runtime/CLAUDE.md` (runtime module guide)
4. **Related Files**:
   - `src/pflow/runtime/instrumented_wrapper.py` (WHERE to add logic)
   - `src/pflow/runtime/node_wrapper.py` (current template resolution)
   - `src/pflow/runtime/template_resolver.py` (resolution engine)
   - `src/pflow/execution/display_manager.py` (error display)

---

## 🎬 Final Words

This task is **high-impact**. The agent's feedback shows this is a real problem that breaks trust in production workflows.

You're not just adding validation - you're **changing the philosophy** from "fail-soft for debugging" to "fail-hard for data integrity."

**Be thoughtful**:
- Consider edge cases (escaped templates, MCP responses)
- Design clear error messages
- Make the default mode decision explicit
- Test with real workflows

**Be pragmatic**:
- We're at MVP with zero users
- Breaking changes are OK
- Simple solutions over complex ones
- Strict mode is probably the right default

**Be thorough**:
- Test the exact Issue #95 scenario
- Check performance with large workflows
- Handle nested data structures
- Provide escape syntax for edge cases

The next agent (might be you!) will thank you for good error messages and clear configuration options.

---

## ✅ Ready to Begin?

**DO NOT start implementing yet!**

Read this handoff memo thoroughly, review the referenced files, and make sure you understand:
1. Why this is a philosophy change, not just a bug fix
2. The relationship to Fix 3 (different problems)
3. The agent's real production experience
4. The design decisions you need to make

When you're ready to begin, say: **"I've read the handoff memo and I'm ready to begin Task 85"**

Then create an implementation plan, get user approval on design decisions, and start coding.

Good luck! 🚀
