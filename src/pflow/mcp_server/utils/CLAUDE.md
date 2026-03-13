# MCP Server Utils

Security and convenience layer between MCP services and core pflow. Three modules with single responsibilities:

- **errors.py** — Sanitize sensitive data (API keys, tokens) before returning to LLMs
- **resolver.py** — Unified workflow loading (handles dict/content/library name/file path)
- **validation.py** — Security validation (parameters, paths, dummy values for testing)

## resolver.py — Workflow Resolution

```python
resolve_workflow(workflow) -> (workflow_ir | None, error | None, source)

# 1. Dict → Use as IR directly
workflow = {"nodes": [...]}  # → (ir, None, "direct")

# 2. String with newline → Raw markdown content → parse
workflow = "# My Workflow\n## Steps\n..."  # → (ir, None, "content")

# 3. String ending .pflow.md → File path → read and parse
workflow = "./my-workflow.pflow.md"  # → (ir, None, "file")

# 4. Single-line string → Try as library name, then file path
workflow = "fix-issue"  # → (ir, None, "library")

# 5. Not found → Return suggestions
workflow = "fx"  # → (None, "Not found: 'fx'\n\nDid you mean:\n  - fix-issue", "")
```

**Suggestion mechanism**: Uses `find_similar_items()` from core (substring matching, not fuzzy). Returns top 5 sorted by length.

**Security note**: File reads have NO path validation. Design decision: local MCP server = trusted environment. `validate_file_path()` exists in validation.py but is never called here. Re-evaluate if adding remote MCP support.

## validation.py — Security Boundaries

### validate_execution_parameters()

Three-layer protection:

1. **Parameter name security** — Delegates to `core.validation_utils.is_valid_parameter_name()`. Blocks: `$`, `|`, `>`, `<`, `&`, `;`, spaces, quotes. Allows: hyphens, dots, numbers at start.
2. **Size limits** — 1MB max (DoS prevention via `json.dumps()` length check)
3. **Code injection detection** — Blocks patterns: `__import__`, `eval(`, `exec(`, `compile(`, `globals(`, `locals(`

**Used by**: `_resolve_and_validate_workflow()` in execution_service.py. **Only the execution path validates parameters** — check if new service entry points need validation too.

### generate_dummy_parameters()

Creates `__validation_placeholder__` values so templates like `${api_key}` resolve during validation without real API keys. **Moved to `pflow.core.validation_utils`** — re-exported from this file for backward compatibility.

### validate_file_path()

Path traversal prevention: blocks `..`, null bytes, optionally absolute paths. Resolution check ensures path stays within cwd.

**Status**: Exists but **never called** in the codebase. Design decision: local MCP = trusted environment.

## errors.py — Sensitive Data Redaction

`sanitize_parameters()` recursively redacts values matching SENSITIVE_KEYS from `core.security_utils`:

- **Key matching**: password, token, api_key, secret, auth, credential, private_key, access_key, client_secret, bearer, authorization, jwt, session_id, cookie, passphrase
- **Length truncation**: Strings >100 chars → first 20 chars + `...<truncated>`
- **Recursive**: Handles nested dicts and lists containing dicts
- **Skips internal params**: Keys starting with `__` are excluded

**Status**: Function exists but **never called in any service**. This is a **security gap** — sensitive data may leak in error messages returned to LLMs. Impact is low (MCP runs locally) but should be addressed.

## Security Gaps

Current implementation has three gaps:

1. **`sanitize_parameters()` unused** — Never called in services. Error messages may contain API keys.
2. **`validate_file_path()` unused** — Never called in resolver.py. File reads have no traversal protection.
3. **Partial parameter validation** — Only the execution path validates. Validation and save paths may not.

**Impact**: Low (MCP runs locally on user's machine), but should be addressed if adding remote MCP support.

**Recommendation**: Either wire sanitization into error paths throughout services, or remove the dead code to avoid false sense of security.

## Execution Path Security (What's Actually Wired)

```
ExecutionService._resolve_and_validate_workflow()
  1. resolve_workflow()              → source validation
  2. validate_execution_parameters() → injection protection
  3. sanitize on error               → NOT IMPLEMENTED
```

## When Adding New Utilities

1. Does core already provide this? (avoid duplication)
2. Should this be in core? (if CLI needs it too → yes)
3. Is this MCP-specific? (then utils is the correct place)
