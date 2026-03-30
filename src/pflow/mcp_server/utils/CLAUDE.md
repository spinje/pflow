# MCP Server Utils

Security and convenience layer between MCP services and core pflow. Two modules with single responsibilities:

- **errors.py** — Sanitize sensitive data (API keys, tokens) before returning to LLMs
- **validation.py** — Security validation (parameters, paths, dummy values for testing)

**Note**: `resolver.py` was removed — workflow resolution is now handled by the unified `pflow.execution.workflow_resolver` module.

## validation.py — Security Boundaries

### validate_execution_parameters()

Three-layer protection:

1. **Parameter name security** — Delegates to `core.validation_utils.is_valid_parameter_name()`. Blocks: `$`, `|`, `>`, `<`, `&`, `;`, spaces, quotes. Allows: hyphens, dots, numbers at start.
2. **Size limits** — 1MB max (DoS prevention via `json.dumps()` length check)
3. **Code injection detection** — Blocks patterns: `__import__`, `eval(`, `exec(`, `compile(`, `globals(`, `locals(`

**Used by**: `execute_workflow()` and `run_registry_node()` in execution_service.py (called at system boundary before passing to WorkflowRunner). **Only the execution path validates parameters** — check if new service entry points need validation too.

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
2. **`validate_file_path()` unused** — Never called anywhere. File reads have no traversal protection.
3. **Partial parameter validation** — Only the execution path validates. Validation and save paths may not.

**Impact**: Low (MCP runs locally on user's machine), but should be addressed if adding remote MCP support.

**Recommendation**: Either wire sanitization into error paths throughout services, or remove the dead code to avoid false sense of security.

## Execution Path Security (What's Actually Wired)

```
ExecutionService.execute_workflow() / run_registry_node()
  1. validate_execution_parameters() → injection protection (system boundary)
  2. WorkflowRunner.run()            → resolution + validation + execution
  3. sanitize on error               → NOT IMPLEMENTED
```

## When Adding New Utilities

1. Does core already provide this? (avoid duplication)
2. Should this be in core? (if CLI needs it too → yes)
3. Is this MCP-specific? (then utils is the correct place)
