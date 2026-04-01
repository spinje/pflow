# Task 141: Pre-Implementation Baseline

Captured: 2026-03-31, branch `refactor/consolidate-exception-hierarchy`, commit `917e4bb2`

## Test Suite

- **4655 tests collected** (4646 passed, 9 skipped, 0 failed)
- Duration: 26.63s

## Exception Base Classes (BEFORE)

```
class ValidationError(Exception)       <- core/ir_schema.py:75
class MarkdownParseError(ValueError)   <- core/markdown_parser.py:31
class UserFriendlyError(Exception)     <- core/user_errors.py:10
class PflowError(Exception)            <- core/exceptions.py:6 (7 subclasses)
```

**4 independent trees. No catch-all possible.**

## Lazy Exception Imports in `src/pflow/` (BEFORE)

### ValidationError from ir_schema (4 sites, 3 aliases)
| File | Line | Alias |
|------|------|-------|
| `cli/error_output.py` | 156 | `IrSchemaValidationError` |
| `core/workflow/validator.py` | 131 | `SchemaValidationError` |
| `execution/runner.py` | 299 | `IRValidationError` |
| `runtime/compilation/compile_validation.py` | 11 | (none, module-level) |

### MarkdownParseError from markdown_parser (10 sites)
| File | Line | Lazy? |
|------|------|-------|
| `cli/commands/workflow.py` | 239 | Yes |
| `cli/error_output.py` | 157 | Yes |
| `cli/error_output.py` | 274 | Yes (inside helper) |
| `core/workflow/dependency_discovery.py` | 16 | No (module-level) |
| `core/workflow/manager.py` | 26 | No (module-level) |
| `core/workflow/save_service.py` | 14 | No (module-level) |
| `core/workflow/validator.py` | 691 | Yes |
| `execution/runner.py` | 300 | Yes |
| `execution/runner.py` | 495 | Yes |
| `mcp_server/services/execution_service.py` | 302 | Yes |

### CompilationError from .compiler (5 lazy sites in compilation/)
| File | Line |
|------|------|
| `runtime/compilation/compile_validation.py` | 81 |
| `runtime/compilation/compile_validation.py` | 150 |
| `runtime/compilation/ir_preparation.py` | 189 |
| `runtime/compilation/mcp_resolution.py` | 114 |
| `runtime/compilation/node_loader.py` | 40 |

### CompilationError from pflow.runtime (3 lazy sites + 1 module-level)
| File | Line | Lazy? |
|------|------|-------|
| `execution/runner.py` | 301 | Yes |
| `execution/runner.py` | 330 | Yes |
| `execution/runner.py` | 496 | Yes |
| `runtime/workflow_executor.py` | 13 | No (module-level, out of scope) |

### Other lazy exception imports in runner.py
| File | Line | Import |
|------|------|--------|
| `execution/runner.py` | 298 | `WorkflowValidationError` |
| `execution/runner.py` | 359 | `WorkflowValidationError` |
| `execution/runner.py` | 494 | `MaxNodeVisitsError, WorkflowValidationError` |
| `runtime/engine/engine.py` | 59 | `CompilationError` |
| `runtime/engine/engine.py` | 79 | `CompilationError` |
| `runtime/engine/batch_executor.py` | 419 | `CompilationError` (redundant — already at line 19) |

## Hacks and Anti-Patterns (BEFORE)

### Duck-type hack (1 site)
```
runner.py:549: type(exception).__name__ == "ValidationError" and hasattr(exception, "path")
```

### _is_markdown_parse_error helper (1 definition, 1 call)
```
error_output.py:272: def _is_markdown_parse_error(exception)
error_output.py:296: _is_markdown_parse_error(exception)
```

### ValidationError aliases (3 different names for same class)
```
validator.py:131:     as SchemaValidationError
error_output.py:156:  as IrSchemaValidationError
runner.py:299:         as IRValidationError
```

### CompilationError-as-parameter pattern
```
compile_validation.py:102: def _validate_data_flow_at_compile_time(ir_dict, CompilationError: type)
compile_validation.py:160: _validate_data_flow_at_compile_time(ir_dict, CompilationError)
```

### ValueError miscategorization
```
runner.py:545: isinstance(exception, (MarkdownParseError, ValueError)) -> category: "validation"
  (ALL ValueErrors get "validation", even node execution errors like HTTP timeouts)
```

### save_service.py implicit MarkdownParseError catch
```
save_service.py:311: except (FileNotFoundError, ValueError) — catches MarkdownParseError via ValueError inheritance
```

## Test Imports (BEFORE)

### ValidationError in tests (8 files)
```
test_cli/test_unified_error_output.py:225          from pflow.core.ir_schema (lazy)
test_core/test_ir_examples.py:15                   from pflow.core
test_core/test_ir_schema.py:5                      from pflow.core
test_core/test_ir_schema_output_suggestions.py:11  from pflow.core.ir_schema
test_core/test_workflow_interfaces.py:5            from pflow.core
test_docs/test_example_validation.py:19            from pflow.core
test_runtime/test_compiler_interfaces.py:12        from pflow.core.ir_schema
test_runtime/test_output_validation.py:8           from pflow.core.ir_schema
```

### MarkdownParseError in tests (4 files)
```
test_core/test_file_resolver_integration.py:10     from pflow.core.markdown_parser
test_core/test_ir_examples.py:17                   from pflow.core.markdown_parser
test_docs/test_example_validation.py:21            from pflow.core.markdown_parser
test_integration/test_workflow_manager_integration.py:20  from pflow.core.markdown_parser
```

### pytest.raises(ValueError) catching MarkdownParseError (1 site)
```
test_workflow_executor_comprehensive.py:226  pytest.raises(ValueError) — catches MarkdownParseError
test_workflow_executor_comprehensive.py:689  pytest.raises(ValueError) — catches plain ValueError (NOT affected)
```

## Summary Counts (BEFORE → AFTER targets)

| Metric | Before | After |
|--------|--------|-------|
| Independent exception trees | 4 | 1 |
| Lazy exception imports in src/pflow/ | 24 | 0 |
| ValidationError aliases | 3 | 0 |
| Duck-type hacks | 1 | 0 |
| _is_markdown_parse_error helpers | 1 | 0 |
| CompilationError-as-parameter pattern | 1 | 0 |
| ValueError miscategorization | Yes | Fixed |
| `except PflowError` catches all pflow exceptions | No | Yes |
| Tests passing | 4646 | 4646+ (new tests added) |
