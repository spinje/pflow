# MCP Server Utils

Security and convenience layer between MCP services and core pflow. Two modules:

- **errors.py** — Re-exports `sanitize_parameters()` from `core.security_utils` (backward-compat shim; redaction logic and callers live in core/runner/formatters)
- **validation.py** — `validate_execution_parameters()` plus a `generate_dummy_parameters` re-export from `core.validation_utils`

**Note**: `resolver.py` was removed — workflow resolution is now handled by the unified `pflow.execution.workflow_resolver` module.

## validation.py — Security Boundaries

### validate_execution_parameters()

Three-layer protection:

1. **Parameter name security** — Delegates to `core.validation_utils.is_valid_parameter_name()`. Blocks: `$`, `|`, `>`, `<`, `&`, `;`, spaces, quotes. Allows: hyphens, dots, numbers at start.
2. **Size limits** — 1MB max (DoS prevention via `json.dumps()` length check)
3. **Code injection detection** — Blocks patterns: `__import__`, `eval(`, `exec(`, `compile(`, `globals(`, `locals(`

**Used by**: ExecutionService at four entry points (execution_service.py:252, 361, 444, 655) — the system boundary before passing to WorkflowRunner. Only ExecutionService validates parameters; check if new service entry points need it too.

### generate_dummy_parameters()

Lives in `pflow.core.validation_utils`; re-exported here for backward compat. Creates `__validation_placeholder__` values so templates like `${api_key}` resolve during validation without real API keys.

## errors.py — Re-export shim

The actual `sanitize_parameters()` lives in `core.security_utils`; errors.py just re-exports it for backward compat. It IS wired up — called by `runner.py` (`_update_metadata`, metadata redaction before saving), `execution/formatters/error_formatter.py`, and `core/diagnostic_render.py`. For the redaction key set and behavior, see `core/security_utils.py`.

## When Adding New Utilities

1. Does core already provide this? (avoid duplication)
2. Should this be in core? (if CLI needs it too → yes)
3. Is this MCP-specific? (then utils is the correct place)
