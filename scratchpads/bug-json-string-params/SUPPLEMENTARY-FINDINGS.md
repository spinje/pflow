# Supplementary Findings: Template-Dependent Auto-Coercion Behavior

**Date:** 2026-01-13
**Related to:** BUG-REPORT.md in this folder

## Summary

While building a release announcements workflow, I discovered that the auto-coercion behavior for object→string is **inconsistent and depends on whether the object contains template variables**. This is separate from (but related to) the main bug documented in BUG-REPORT.md.

---

## The Discovery

### Context

Building a workflow to post to Discord using `mcp-discord-execute_action`, which expects:
- `path_params: str` - JSON string like `'{"channel_id": "123"}'`
- `body_schema: str` - JSON string like `'{"content": "message"}'`

### Expected Behavior

Using object syntax should auto-coerce to JSON string:
```json
"body_schema": {"content": "${message}"}
```
Should become: `'{"content": "actual message"}'`

### Actual Behavior

Auto-coercion **only works when the object contains a template variable**. The behavior also depends on **sibling parameters**.

---

## Complete Test Matrix

| path_params | body_schema | Result |
|-------------|-------------|--------|
| object WITH template `{"channel_id": "${id}"}` | object WITH template `{"content": "${msg}"}` | ✅ Works |
| object WITHOUT template `{"channel_id": "123"}` | object WITH template `{"content": "${msg}"}` | ❌ Fails |
| object WITH template `{"channel_id": "${id}"}` | object WITHOUT template `{"content": "hello"}` | ❌ Fails |
| object WITHOUT template `{"channel_id": "123"}` | object WITHOUT template `{"content": "hello"}` | ❌ Fails |
| string `"{\"channel_id\": \"123\"}"` | object WITH template `{"content": "${msg}"}` | ✅ Works |
| string `"{\"channel_id\": \"123\"}"` | object WITHOUT template `{"content": "hello"}` | ❌ Fails |

**Key insight:** An object only gets auto-coerced to a JSON string if:
1. It contains a template variable (`${...}`), AND
2. No sibling param is an object WITHOUT a template

---

## Reproducible Test Cases

All test files are in: `/Users/andfal/projects/pflow-evals/demo-outputs/release-posts/pflow-cli/003/`

### Test 1: Both objects have templates → WORKS

**File:** `test-discord-object.json`
```json
{
  "inputs": {
    "message": {"type": "string", "required": true},
    "discord_channel_id": {"type": "string", "required": true}
  },
  "nodes": [{
    "id": "post-to-discord",
    "type": "mcp-discord-execute_action",
    "params": {
      "server_name": "discord",
      "category_name": "DISCORD_CHANNELS_MESSAGES",
      "action_name": "create_message",
      "path_params": {"channel_id": "${discord_channel_id}"},
      "body_schema": {"content": "${message}"}
    }
  }],
  "edges": []
}
```

**Run:**
```bash
pflow test-discord-object.json \
  message='Test with "quotes" and
newlines' \
  discord_channel_id="1458059302022549698"
```
**Result:** ✅ Success - message posted with proper escaping

---

### Test 2: path_params object without template → FAILS

**File:** `test-mcp-string-param.json`
```json
{
  "inputs": {
    "message": {"type": "string", "required": true}
  },
  "nodes": [{
    "id": "test-string-param",
    "type": "mcp-discord-execute_action",
    "params": {
      "server_name": "discord",
      "category_name": "DISCORD_CHANNELS_MESSAGES",
      "action_name": "create_message",
      "path_params": {"channel_id": "1458059302022549698"},
      "body_schema": {"content": "${message}"}
    }
  }],
  "edges": []
}
```

**Run:**
```bash
pflow test-mcp-string-param.json message='Test'
```
**Result:** ❌ `Error: the JSON object must be str, bytes or bytearray, not dict`

---

### Test 3: path_params as string, body_schema object with template → WORKS

**File:** `test-hardcoded-path.json`
```json
{
  "inputs": {
    "message": {"type": "string", "required": true}
  },
  "nodes": [{
    "id": "test",
    "type": "mcp-discord-execute_action",
    "params": {
      "server_name": "discord",
      "category_name": "DISCORD_CHANNELS_MESSAGES",
      "action_name": "create_message",
      "path_params": "{\"channel_id\": \"1458059302022549698\"}",
      "body_schema": {"content": "${message}"}
    }
  }],
  "edges": []
}
```

**Run:**
```bash
pflow test-hardcoded-path.json message='Test'
```
**Result:** ✅ Success

---

### Test 4: body_schema without template → FAILS

**File:** `test-no-body-template.json`
```json
{
  "inputs": {
    "channel_id": {"type": "string", "required": true}
  },
  "nodes": [{
    "id": "test",
    "type": "mcp-discord-execute_action",
    "params": {
      "server_name": "discord",
      "category_name": "DISCORD_CHANNELS_MESSAGES",
      "action_name": "create_message",
      "path_params": {"channel_id": "${channel_id}"},
      "body_schema": {"content": "hardcoded message"}
    }
  }],
  "edges": []
}
```

**Run:**
```bash
pflow test-no-body-template.json channel_id="1458059302022549698"
```
**Result:** ❌ `Error: the JSON object must be str, bytes or bytearray, not dict`

---

## How stdin Auto-Serialize Differs

The shell node's `stdin` parameter is typed as `any` with documented "dict/list auto-serialized to JSON". This works correctly:

```json
{
  "id": "build-object",
  "type": "shell",
  "params": {
    "stdin": {"content": "${message}"},
    "command": "cat"
  }
}
```

**Output with `message='Hello "world"\nLine 2'`:**
```
{"content": "Hello \"world\"\nLine 2"}
```

The escaping is correct (`\n` is two characters, quotes are escaped).

**Contrast with string template substitution:**
```json
{
  "id": "show-body",
  "type": "shell",
  "params": {
    "command": "echo '${body}'"
  }
}
```

Where `body` is an object input - the newline becomes a LITERAL newline (0x0a), not escaped `\n`.

---

## Root Cause Hypothesis

The template resolution code likely has two paths:

1. **Objects with templates:** Triggers a "process and serialize" path
   - Templates get resolved
   - Object gets serialized to JSON string (with proper escaping)

2. **Objects without templates:** Passed through as-is
   - No template resolution needed
   - Object stays a Python dict
   - MCP node receives dict instead of expected string

The presence of an object-without-template in ANY param seems to affect the processing of sibling params, possibly due to:
- Early return in template resolution
- Different code path for "has templates" vs "no templates"
- Batch processing of params where one failure affects others

---

## Relationship to Main Bug Report

This is a **subset** of the bug documented in BUG-REPORT.md:

- **Main bug:** pflow doesn't auto-coerce dict→str for string-typed params
- **This finding:** The auto-coercion partially works but ONLY when templates are present

The implementation plan in IMPLEMENTATION-PLAN.md should fix both issues, as it proposes type-aware coercion based on declared param type regardless of template presence.

---

## Suggested Fix Verification

When the fix from IMPLEMENTATION-PLAN.md is implemented, verify these cases:

1. ✅ Object WITH template → coerced to JSON string
2. ✅ Object WITHOUT template → coerced to JSON string
3. ✅ Object with template + sibling object without template → both coerced
4. ✅ Existing dict-typed params → NOT coerced (stay as dict)
5. ✅ Proper escaping of newlines, quotes, backslashes

---

## Documentation Improvements for cli-agent-instructions.md

After the bug is fixed, add the following to the instructions.

**Location:** After the existing section "Critical: Automatic JSON Parsing for Simple Templates" (line ~973), add a new section for the REVERSE direction.

### New Section: "Automatic JSON Serialization for String-Typed Parameters" (add after line 973)

```markdown
### Automatic JSON Coercion for String Parameters

When a node parameter is declared as `str` but you provide an object or array, pflow automatically serializes it to a JSON string. This is particularly useful for MCP tools that expect JSON-formatted string parameters.

**Example - Discord MCP:**
```json
{
  "id": "post-message",
  "type": "mcp-discord-execute_action",
  "params": {
    "server_name": "discord",
    "category_name": "DISCORD_CHANNELS_MESSAGES",
    "action_name": "create_message",
    "path_params": {"channel_id": "${channel_id}"},
    "body_schema": {"content": "${message}"}
  }
}
```

Even though `path_params` and `body_schema` are typed as `str`, you can use object syntax. pflow will:
1. Resolve templates: `${channel_id}` → `"123"`, `${message}` → `"Hello\nWorld"`
2. Serialize to JSON: `{"channel_id": "123"}` → `'{"channel_id": "123"}'`
3. Properly escape special characters: newlines become `\n`, quotes become `\"`

**Why this matters:**
- Cleaner workflow syntax (no escaped quotes)
- Automatic escaping prevents JSON parsing errors
- Works with dynamic content containing special characters

**When to use object syntax vs string syntax:**

| Use Object Syntax | Use String Syntax |
|-------------------|-------------------|
| Dynamic content with templates | Static, known JSON |
| Content may have special chars | Simple values, no escaping needed |
| Better readability preferred | Explicit control needed |

```json
// Object syntax (recommended for dynamic content)
"body_schema": {"content": "${user_message}"}

// String syntax (works but requires manual escaping)
"body_schema": "{\"content\": \"${user_message}\"}"  // May break with special chars!
```

**Note:** String syntax with inline templates does NOT auto-escape. If `${user_message}` contains newlines or quotes, the JSON will be invalid. Always use object syntax when the content may contain special characters.
```

### Update: "Common Agent Mistakes to Avoid" table (line ~1730)

Add this row to the existing table:

| Mistake | Why It Happens | Prevention |
|---------|----------------|------------|
| **Manual JSON string construction** | Trying to build `"{\"key\": \"${val}\"}"` | Use object syntax: `{"key": "${val}"}` - auto-serializes with proper escaping |

### Update: "Common Mistakes - Detailed Solutions" section (line ~1528)

Add new item:

```markdown
#### 8. Manual JSON string construction for string-typed params

**Impact**: JSON parsing errors when content contains newlines, quotes, or backslashes
**Fix**: Use object syntax instead of string syntax

```json
// ❌ WRONG - breaks with special characters
"body_schema": "{\"content\": \"${message}\"}"
// If ${message} = 'Hello "world"\nLine 2', result is invalid JSON

// ✅ RIGHT - auto-serializes with proper escaping
"body_schema": {"content": "${message}"}
// Result: '{"content": "Hello \"world\"\\nLine 2"}' (valid JSON)
```

**Why this happens**: String template substitution does raw replacement without escaping. Object syntax triggers JSON serialization which properly escapes special characters.
```

---

## Files Created During Investigation

In `/Users/andfal/projects/pflow-evals/demo-outputs/release-posts/pflow-cli/003/`:

- `test-discord-object.json` - Template in both params (works)
- `test-mcp-string-param.json` - Hardcoded path_params object (fails)
- `test-mcp-with-template.json` - Template in path_params (works)
- `test-hardcoded-path.json` - String path_params (works)
- `test-no-body-template.json` - No template in body_schema (fails)
- `test-body-template-only.json` - Template only in body_schema (fails)
- `test-string-path-no-body-template.json` - String path + no body template (fails)
- `test-string-approach.json` - Manual JSON string construction demo
- `test-object-approach.json` - Object auto-serialize demo
- `test-object-in-command.json` - Object in string template context
- `test-object-to-string-param.json` - Multi-node test
