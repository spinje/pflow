# Braindump: Unified JSON Error Structures

## Where I Am

This task emerged during Task 115 (Stdin Routing) review. We discovered that pflow has two different JSON error structures - one for validation errors, one for runtime errors. The user asked: "should we combine these into the same structure?" We decided yes, but as a separate task to keep Task 115 focused.

This task has NOT been started. Task 115 will follow the existing validation error pattern for consistency. Task 117 will unify everything later.

## User's Mental Model

The user thinks about this from a **consumer perspective**. Their key question was:

> "shouldnt the error structure look as close as possible to the working json?"

They want:
1. **Consistency** - One structure to handle, not two
2. **Predictability** - Consumers shouldn't need to detect which error type they got
3. **Simplicity** - Easier to document, easier to parse

When I explained the two structures exist, they immediately asked if we should unify them. They didn't want to just accept historical inconsistency.

## How We Discovered This

1. Testing Task 115 stdin routing with `--output-format json`
2. Found stdin routing error outputs plain text (not JSON)
3. Investigated how to fix it - discovered two different JSON patterns
4. User asked why two patterns exist
5. I explained: validation errors (early) vs runtime errors (during execution)
6. User asked: should we unify them?
7. Decision: Yes, but separate task (Task 117)

## The Two Existing Structures

### Validation Errors (lines 2099-2113 in main.py)

```json
{
  "success": false,
  "error": "Workflow validation failed",
  "validation_errors": ["Error message 1", "Error message 2"],
  "metadata": {"action": "unsaved", "name": "/path/to/workflow.json"}
}
```

**Characteristics:**
- Simple string array for errors
- Uses `metadata` for workflow info
- No metrics, execution, or duration (doesn't exist yet)
- Created inline, no helper function

### Runtime Errors (`_create_json_error_output()`)

```json
{
  "success": false,
  "status": "failed",
  "error": "Workflow execution failed",
  "is_error": true,
  "errors": [
    {
      "source": "runtime",
      "category": "execution_failure",
      "message": "Command failed with exit code 1",
      "node_id": "shell-1",
      "fixable": true,
      "shell_command": "...",
      "shell_exit_code": 1
    }
  ],
  "failed_node": "shell-1",
  "execution": {
    "duration_ms": 123.45,
    "nodes_executed": 2,
    "nodes_total": 3,
    "steps": [...]
  },
  "duration_ms": 123.45,
  "metrics": {...}
}
```

**Characteristics:**
- Rich structured error objects with metadata
- Uses `workflow` for workflow info (not `metadata`)
- Includes execution state, metrics, timing
- Uses helper function `_create_json_error_output()`

### Key Differences

| Aspect | Validation | Runtime |
|--------|------------|---------|
| Error format | String array | Object array |
| Field name | `validation_errors` | `errors` |
| Workflow info | `metadata` | `workflow` |
| Has metrics | No | Yes |
| Has execution | No | Yes |
| Has duration | No | Yes |
| Helper function | No (inline) | Yes |

## Why They're Different

**ASSUMPTION:** This is historical - different features added at different times by different implementations. No deliberate design decision to have two structures.

**VERIFIED:** Validation errors happen BEFORE execution starts, so no metrics/execution/duration data exists. This is a real constraint, not just laziness.

## Proposed Unified Structure

We discussed this structure:

```json
{
  "success": false,
  "error": "Human readable summary",
  "errors": [
    {
      "source": "validation" | "runtime" | "cli",
      "category": "stdin_routing" | "template_error" | "execution_failure",
      "message": "Detailed error message",
      "suggestion": "How to fix (optional)",
      // Additional fields depending on source/category
    }
  ],
  "workflow": {"name": "...", "action": "unsaved" | "reused" | "created"},

  // Optional fields (null or omitted for validation errors)
  "duration_ms": null,
  "metrics": null,
  "execution": null
}
```

**Key design decisions:**
- Use `errors` array (not `validation_errors`) for all error types
- Add `source` field to distinguish validation vs runtime
- Use `workflow` consistently (not `metadata`)
- Optional fields are null/omitted when not applicable

## Assumptions & Uncertainties

**ASSUMPTION:** We have no external consumers yet ("we don't have any users"), so breaking changes are acceptable.

**UNCLEAR:** Should optional fields be `null` or omitted entirely?
- `null` is explicit but verbose
- Omitted is cleaner but requires checking existence

**UNCLEAR:** Should there be a schema version field for future compatibility?

**NEEDS VERIFICATION:** Are there any MCP server consumers that expect the current structure? Check `src/pflow/mcp_server/` for JSON output handling.

**ASSUMPTION:** The `errors` array structure from runtime errors is more useful than simple strings. Validation errors should adopt it.

## Unexplored Territory

**UNEXPLORED:** The MCP server (`src/pflow/mcp_server/`) may have its own error handling. Does it use the same structures? Should it be unified too?

**UNEXPLORED:** The execution formatters in `src/pflow/execution/formatters/` - specifically `error_formatter.py`. This might be a good place for unified error structure logic.

**CONSIDER:** Should there be a shared error formatter that both CLI and MCP server use? Currently CLI has `_create_json_error_output()` which is CLI-specific.

**MIGHT MATTER:** The `is_error` field in runtime errors - is it used anywhere? It seems redundant with `success: false`. Consider removing it in unified structure.

**MIGHT MATTER:** The `status` field ("failed") - is this the tri-state from Task 85 (success/degraded/failed)? If so, should validation errors also have status?

**UNEXPLORED:** What about warnings? Runtime has `__warnings__` for degraded status. Should unified structure include warnings array?

## What I'd Tell Myself

1. **Start by auditing all error sites** - Search for `ctx.exit(1)` and `"success": False` in main.py to find all JSON error constructions.

2. **Don't just change the structure** - Create a shared helper function that both validation and runtime errors use. This prevents drift.

3. **The `errors` array structure is better** - Structured objects with `source`, `category`, `message` are more useful than plain strings.

4. **Validation errors need source field** - To distinguish `"source": "validation"` from `"source": "runtime"`.

5. **Consider the formatters module** - `src/pflow/execution/formatters/` might be the right place for a unified error formatter.

6. **Test with jq** - Consumers will parse with `jq`. Test that the unified structure works: `pflow ... | jq '.errors[0].message'`

## Open Threads

### Questions to answer before implementing

1. **Null vs omitted** for optional fields?
2. **Version field** for JSON output format?
3. **MCP server** - does it need the same treatment?
4. **Warnings** - include in unified structure?

### Potential helper function location

Could go in:
- `src/pflow/cli/main.py` (current location of `_create_json_error_output`)
- `src/pflow/execution/formatters/error_formatter.py` (shared formatters)
- New file `src/pflow/core/json_output.py` (if used by multiple modules)

### Migration approach

1. Create unified structure/helper
2. Migrate runtime errors first (already use helper)
3. Migrate validation errors (currently inline)
4. Migrate stdin routing error (from Task 115)
5. Update tests
6. Remove old code

## Relevant Files & References

**Current error implementations:**
- `src/pflow/cli/main.py:1019-1133` - `_create_json_error_output()` (runtime)
- `src/pflow/cli/main.py:2099-2113` - Validation error pattern (inline)
- `src/pflow/cli/main.py:3112-3132` - `_show_stdin_routing_error()` (after Task 115 fix)

**Formatters (potential location for unified helper):**
- `src/pflow/execution/formatters/error_formatter.py`
- `src/pflow/execution/formatters/` directory

**MCP server (may need same treatment):**
- `src/pflow/mcp_server/`

**Tests to update:**
- Any test checking JSON error output structure
- Search for `"validation_errors"` in tests

## For the Next Agent

**Start by:** Auditing all error sites in main.py. Search for `ctx.exit(1)` and `"success": False`.

**Key decision to make early:** Where should the unified error helper live? CLI-only or shared?

**Don't bother with:** Backward compatibility - we have no users.

**The user cares most about:** Consistency. One structure, predictable fields, easy to parse.

**Prerequisite:** Task 115 should be complete first. It will have fixed stdin routing error to use the current validation pattern. This task then unifies everything.

**Suggested approach:**
1. Design the unified structure (propose to user)
2. Create helper function
3. Migrate all error sites
4. Update tests
5. Document the JSON output format

---

**Note to next agent**: Read this document fully before taking any action. Also read `task-117.md` for the formal task description. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
