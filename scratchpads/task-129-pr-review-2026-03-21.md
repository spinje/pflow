# Task 129 PR Review

## Critical — must fix before merge

1. Parent-relative file references are rejected, which breaks a documented part of the feature and makes external refs less capable than existing workflow refs.

`is_file_reference()` explicitly accepts `../...`, but `_read_file()` then rejects anything that resolves outside `base_dir`:

- `src/pflow/core/file_resolver.py` accepts `value.startswith("../")`
- `src/pflow/core/file_resolver.py` then raises if `resolved_path.is_relative_to(resolved_base)` is false
- existing workflow path resolution explicitly supports `../child/child.pflow.md` via `WorkflowExecutor._resolve_safe_path()`

That means a perfectly reasonable layout like `workflow.pflow.md` in `workflows/` and shared prompts in `../prompts/` now fails with `escapes workflow directory`. I verified this locally with `resolve_file_references()` against `../shared/prompt.md`, and the current test suite codifies that behavior in `tests/test_core/test_file_resolver.py`.

Why this matters:
- the task spec lists `../` as a supported detection pattern
- relative-path semantics elsewhere in the codebase already allow traversing to sibling directories
- this blocks common repo layouts where prompts/scripts live next to, not inside, the workflow directory

## Warnings — should be addressed

1. Malformed IR can crash before structured validation because the new pre-validation resolver assumes `params` is always a dict.

`resolve_file_references()` does `for key, value in params.items()` and `has_file_references()` does the same in `_collect_param_file_refs()` without guarding `params` type. Since both now run before schema validation:

- `compile_ir_to_flow()` can raise `AttributeError: 'str' object has no attribute 'items'`
- `ExecutionService.validate_workflow()` can crash in `_check_inline_file_references()` with the same traceback

This is especially relevant for MCP, which explicitly accepts direct IR dicts from agents. I verified both the compiler and MCP validation paths with `{"params": "oops"}` and they fail with raw `AttributeError` instead of the usual validation error formatting.

2. File paths containing spaces are silently treated as inline literals, so a valid external file can never be resolved.

`is_file_reference()` immediately returns `False` when `" " in value`. As a result:

- `- prompt: "./my prompt.md"` is not resolved
- no file-not-found error is raised
- downstream validation sees the literal path string, which is confusing and hard to diagnose

I verified this locally: after `resolve_file_references()`, the parameter remained `"./my prompt.md"` unchanged. The task spec does not forbid spaces, and existing path handling elsewhere (`Path(...)`, workflow file resolution) does not impose this restriction either.

## Open Questions / Assumptions

- I’m assuming the task requirement to support `../` still stands. If the new containment rule is intentional, the task docs/tests should be updated and the same policy question should be answered for sub-workflow path resolution too.

## Verification

Targeted regression suite passed:

- `tests/test_core/test_file_resolver.py`
- `tests/test_core/test_file_resolver_integration.py`
- `tests/test_cli/test_validate_only.py`
- `tests/test_cli/test_nested_workflow_cli.py`
- `tests/test_mcp_server/test_validation_service.py`

All 96 targeted tests passed.
