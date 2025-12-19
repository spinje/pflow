# Bug Report Summary: Inconsistent LLM Model Name Handling

> **Source**: User-provided bug report during investigation session
> **Status**: Root cause identified, fix not yet implemented

---

## The Three Core Issues

### Issue 1: Invalid Model Names Silently Fail in Workflows

**Reproduction:**
```json
{
  "inputs": {},
  "nodes": [{
    "id": "test-llm",
    "type": "llm",
    "params": {
      "prompt": "Say hello in exactly 5 words.",
      "model": "claude-sonnet-4-20250514"
    }
  }]
}
```

```bash
pflow /path/to/workflow.json
```

**Expected**: Error indicating invalid model name
**Actual**: Workflow completes "successfully", reports token usage, but response is empty string

**Evidence from trace file:**
```json
{
  "response": "",
  "llm_usage": {
    "model": "claude-sonnet-4-20250514",
    "input_tokens": 11627,
    "output_tokens": 8,
    "total_tokens": 11635
  }
}
```

---

### Issue 2: Valid Claude Models Fail in `registry run` But Work in Workflows

**Reproduction:**

```bash
# Step 1: Verify model exists in llm library
uv run --directory /Users/andfal/projects/pflow llm models list | grep "sonnet-4-5"
# Output: Anthropic Messages: anthropic/claude-sonnet-4-5 (aliases: claude-sonnet-4.5)

# Step 2: Try registry run - FAILS
pflow registry run llm prompt="What is 2+2?" model="claude-sonnet-4-5"
# Error: LLM call failed after 3 attempts. Model: claude-sonnet-4-5

# Step 3: Try same model in workflow - WORKS
pflow /path/to/workflow.json  # with model="claude-sonnet-4-5"
# Response: "4"
```

---

### Issue 3: Inconsistent Behavior Summary Table

| Model Name | `llm` CLI | `registry run` | Workflow |
|------------|-----------|----------------|----------|
| `gemini-2.5-flash` | works | works | works |
| `gemini-2.5-flash-lite` (default) | works | works | works |
| `gpt-4o-mini` (OpenAI) | works | works | works |
| `claude-4-sonnet` (valid alias) | works | works | works |
| `claude-sonnet-4.5` (valid alias) | works | ? | ? |
| `claude-sonnet-4-5` (dash, not alias) | **FAILS** | **FAILS** | works |
| `claude-sonnet-4-20250514` (unlisted) | **FAILS** | **FAILS** | works (small), **silent fail** (large) |
| `totally-fake-model-12345` | N/A | **FAILS** | **FAILS** |

**Key observation**: The issue is specific to Claude models. Non-Claude models (Gemini, OpenAI) behave consistently.

---

## User's Direct `llm` CLI Tests

```bash
# This works - correct alias with dot
pflow read-fields exec-XXX result | uv run --directory /Users/andfal/projects/pflow llm -m claude-sonnet-4.5 "Convert to markdown:"
# Returns full formatted transcript

# This fails - dash instead of dot
uv run --directory /Users/andfal/projects/pflow llm -m claude-sonnet-4-5 "test"
# Error: 'Unknown model: claude-sonnet-4-5'
```

**Conclusion from user**: The `llm` CLI works correctly. The issue is in pflow's model name handling.

---

## Valid Models List (from `llm models list`)

```
anthropic/claude-sonnet-4-0 (aliases: claude-4-sonnet)
anthropic/claude-sonnet-4-5 (aliases: claude-sonnet-4.5)
anthropic/claude-3-5-sonnet-latest (aliases: claude-3.5-sonnet)
```

Note: `claude-sonnet-4-20250514` does NOT exist in this list.

---

## Reproduction Commands (from bug report)

```bash
# 1. Verify llm tool works
uv run --directory /Users/andfal/projects/pflow llm -m gemini-2.5-flash-lite "Say hi"

# 2. Show valid models fail in registry run
pflow registry run llm prompt="Hi" model="claude-sonnet-4-5"

# 3. Show invalid models silently fail in workflow
cat > /tmp/test.json << 'EOF'
{"inputs": {}, "nodes": [{"id": "t", "type": "llm", "params": {"prompt": "Hi", "model": "claude-sonnet-4-20250514"}}]}
EOF
pflow /tmp/test.json

# 4. Check trace for empty response
ls -t ~/.pflow/debug/workflow-trace-*.json | head -1 | xargs cat | jq '.nodes[].shared_after'
```

---

## User's Hypotheses (from bug report)

1. **Different code paths**: `registry run` and workflow execution may use different code for LLM invocation
2. **Model name resolution**: Workflow execution might pass model names directly to API without validation
3. **Error suppression**: Workflow LLM node might catch exceptions and return empty response
4. **llm tool integration**: Need to check how pflow calls the `llm` tool

---

## Impact (from bug report)

- Users can accidentally use invalid model names without errors
- Tokens are consumed but no useful output is produced
- Debugging is difficult because workflow reports success
- Valid Claude models can't be tested with `registry run`

---

> **NOTE TO IMPLEMENTING AGENT**: This is a summary of the user's bug report. Verify these behaviors yourself before assuming they are accurate. The user's environment and pflow version may differ from yours.
