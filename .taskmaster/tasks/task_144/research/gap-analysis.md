# Gap Analysis: Diagnostic Rendering Baseline

Based on 56 captured outputs across 21 fixtures, 3 rendering categories.
Context coverage: **76%** (96/127 keys rendered, 31 silently dropped).

## Summary of Problems

### 1. Six inconsistent error formats

The same system produces six visually distinct output styles:

| Format | Used by | Example header |
|--------|---------|---------------|
| Runtime default | CompilationError, runtime errors with node_id | `Error at node 'X':` |
| User-friendly | UserFriendlyError, MCPError, OutputResolutionError | `Error: Title` |
| Validation | WorkflowValidationError, SchemaValidationError | `❌ Message` |
| Simple | FileNotFoundError, PermissionError, parse errors | `✗ Message` |
| Not-found | WorkflowNotFoundError | `❌ Workflow 'X' not found.` |
| Max-visits shortcut | MaxNodeVisitsError (no error_number) | `❌ Long message...` |

An agent can't predict or parse the format — it changes based on the exception type.

### 2. Same error, different rendering based on parameters

Validation errors render TWO COMPLETELY DIFFERENT ways based on `error_number`:

Without error_number:
```
❌ Unknown node type 'httpp'
   At: nodes[0].type
   👉 Use 'shell', 'http', 'llm', 'file', or 'mcp'
```

With error_number=1:
```
Error 1:
  Category: validation
  Message: Unknown node type 'httpp'

  Suggestion: Use 'shell', 'http', 'llm', 'file', or 'mcp'
  At: nodes[0].type
```

Same diagnostic, completely different visual structure.

### 3. Simple errors are information-poor

```
✗ workflow.pflow.md
```

That's the ENTIRE output for a FileNotFoundError. No title, no context, no suggestion.
An agent seeing this has zero actionable information.

```
✗ Permission denied: /etc/pflow/config
```

Same problem. Compare with the user-friendly format which always has title + explanation + suggestions.

### 4. Category rendering is inconsistent

- Runtime default: shows `Category: X` label
- User-friendly: category is in context but NEVER rendered
- Validation (no error_number): category dropped
- Simple: category dropped
- Not-found: category dropped

### 5. Bypass paths produce a third style

Registry run formatters produce yet another format:
```
❌ Failed to execute node 'fetch'

Error: input.txt

Verify the file path exists and is accessible.
```

Compare with the diagnostic pipeline's output for the same FileNotFoundError:
```
✗ workflow.pflow.md
```

Two completely different renders for the same exception type.

---

## Per-Fixture Gap Analysis

### compilation-error

**Available**: category, phase, node_type, sub_workflow_path
**Rendered**: category, node_type, sub_workflow_path
**Dropped**: `phase` — agent can't tell if compilation failed during node_import, template_resolution, or edge_building

**Format**: Runtime default (`Error at node 'fetch': / Category: compilation / Message: ...`)
**Agent impact**: Medium — `phase` helps narrow diagnosis. The `Category:` / `Message:` labels are mechanical compared to user-friendly format.

### max-visits-error

**Without error_number**: `❌ Node 'process' exceeded maximum visits (100/100)...` — one line, no structure. `visit_count` and `max_visits` are embedded in the message string but not as structured fields. No `category` shown.

**With error_number**: Full runtime format with category, message, suggestion. Much more informative.

**Gap**: The shortcut path (no error_number) drops ALL structure. This is the path used by `display_exception_text()` — the most common error display path. The agent gets a wall of text instead of structured diagnostics.

### workflow-validation-error (3 errors)

**Format without error_number**: `❌ msg / At: path / 👉 suggestion` — clean but different from everything else.
**Format with error_number**: `Error 1: / Category: validation / Message: ...` — runtime default format.

**Gap**: No title. The `❌` icon and inline format are unique to validation. An agent parsing this output has to handle a different format than runtime errors.

### schema-validation-error

Same observations as workflow-validation-error. Clean format but inconsistent with other types.

### markdown-parse-error

**Available**: category, line
**Rendered**: line (embedded in message via `MarkdownParseError.__str__()`)
**Dropped**: `category` (without error_number)

**Format**: Simple (`✗ Line 42: Unclosed code fence / → suggestion`)
**Gap**: Line number is in the message string, not a structured field. Fine for humans, harder for agents to extract. The `category: parse_error` is available but not shown.

### workflow-not-found-with-suggestions

**Available**: category, workflow_name, similar_names, hint
**Rendered**: workflow_name, similar_names (hint is None here)
**Dropped**: category

**Format**: Unique not-found format with "Did you mean" list.
**Assessment**: This format is actually good — clear, actionable. But it's unique and unpredictable for agents.

### workflow-not-found-with-hint

**Available**: category, workflow_name, similar_names, hint
**Rendered**: hint only
**Dropped**: category, workflow_name, similar_names (but these are intentionally irrelevant when hint overrides)

**Format**: Just `❌ {hint}` — one line.
**Assessment**: Fine when hint is a complete message. But no structure.

### output-resolution-error

**Available**: category, title, explanation, suggestions, technical_details, failures, output_name, source_expr
**Rendered**: title, explanation, suggestions, technical_details (verbose), failures (via explanation text), output_name (via explanation), source_expr (via explanation)
**Dropped**: category (always)

**Format**: User-friendly (title / explanation / numbered suggestions / verbose details)
**Assessment**: Best format in the codebase. Rich, structured, actionable. All other errors should look like this. `category` drop is harmless (title conveys the information).

### mcp-error

**Available**: category, title, explanation, suggestions, technical_details
**Rendered**: All except technical_details (shown with verbose)
**Dropped**: Nothing significant

**Format**: User-friendly
**Assessment**: Excellent. The model for all errors.

### user-friendly-error

Same as mcp-error. Excellent format.

### file-not-found-error

**Available**: category
**Rendered**: Nothing (without error_number). Category (with error_number).

**Format**: `✗ workflow.pflow.md` — the worst output in the entire codebase.
**Gap**: CRITICAL. No title, no suggestion, no context. An agent gets a filename with a cross mark. Compare with the registry_run bypass path which at least says "Verify the file path exists."

### permission-error

Same as file-not-found. `✗ Permission denied: /etc/pflow/config` with nothing else.
**Gap**: CRITICAL. No suggestion.

### valueerror-with-node-annotation

**Format**: Runtime default (`Error at node 'parse': / Category: execution_failure / Message: ...`)
**Assessment**: Acceptable but the `Category:` / `Message:` labels are mechanical.

### valueerror-without-annotation

**Format**: Simple (`✗ Missing required field 'type' in node configuration`)
**Gap**: No context, no suggestion, no indication of where this happened. Same ValueError renders completely differently depending on whether `_pflow_node_id` was set.

### generic-exception-typeerror

**Available**: category, exception_type
**Rendered**: category
**Dropped**: `exception_type` — agent can't tell it was a TypeError vs RuntimeError vs AttributeError.

**Gap**: `exception_type` is useful for debugging. Should be shown.

### runtime-shell-error

**Available**: category, action, shell_command, shell_exit_code, shell_stdout, shell_stderr
**Rendered**: All except `action`
**Dropped**: `action` — low value, always "error"

**Format**: Runtime default with shell context block
**Assessment**: Good — shell details are rich and actionable. But no title, and `Category:` / `Message:` labels are mechanical.

### runtime-api-error

**Available**: category, action, status_code, raw_response
**Rendered**: All except `action`
**Assessment**: Good — API response details are rich. Status code NOT explicitly rendered as a field (it's in the message).

### runtime-mcp-error

**Rendered**: All keys
**Assessment**: Good — MCP error details are structured.

### runtime-template-error

**Available**: category, action, available_fields, available_fields_total, available_fields_truncated
**Rendered**: All except `available_fields_truncated` (boolean, used to decide whether to show the trace file hint — so it IS rendered indirectly)
**Assessment**: Good — field list is helpful.

### Warnings

Both warning fixtures render well. Single clean path. Context key `template` appears in the output indirectly (the rendered text matches the template value). No changes needed.

---

## Bypass Path Gaps

### registry format_node_not_found_error vs diagnostic not-found

| Aspect | Diagnostic | Registry bypass |
|--------|-----------|----------------|
| Header | `❌ Workflow 'X' not found.` | `❌ Node 'X' not found in registry` |
| Suggestions | "Did you mean one of these?" with names | Uses `format_did_you_mean()` with different phrasing |
| Guidance | "Use 'pflow workflow list'" | "Use registry_discover / registry_list" |

Two different renderers for the same concept, with different wording and guidance.

### registry format_execution_error vs diagnostic error

The registry formatter has its own exception dispatch:
- FileNotFoundError → "Verify the file path" (better than diagnostic's bare `✗ input.txt`)
- PermissionError → "Check file permissions" (better than diagnostic's bare `✗ Permission denied`)
- ValueError with "required" → "Use registry_describe" (diagnostic has no suggestion)
- Timeout → "Try increasing timeout" (diagnostic has no special handling)
- MCP nodes → verbose-only MCP-specific guidance (diagnostic has none)

**Irony**: The bypass path is BETTER than the diagnostic path for simple errors because it at least provides guidance. The diagnostic path for FileNotFoundError literally just shows the filename.

### registry format_ambiguous_node_error

No diagnostic equivalent. Shows match list + examples.
Can be represented as a "similar_names" context block + suggestions.

---

## Scorecard Targets (what "better" means for each fixture after implementation)

| Fixture | Must improve | Metric |
|---------|-------------|--------|
| compilation-error | Show `phase`, use titled format | phase visible, consistent format |
| max-visits-error | Show `visit_count`/`max_visits` as structured fields, use titled format | all context visible, consistent format |
| workflow-validation-error | Consistent format regardless of error_number, show suggestion | same format always |
| schema-validation-error | Same as above | same format always |
| markdown-parse-error | Show `line` as structured field (not embedded in message), use titled format | line visible, consistent format |
| workflow-not-found | Consistent format with other errors | consistent with titled format |
| output-resolution-error | Already excellent — maintain quality | no regression |
| mcp-error | Already excellent — maintain quality | no regression |
| user-friendly-error | Already excellent — maintain quality | no regression |
| file-not-found-error | MUST add title and suggestion | agent can act on it |
| permission-error | MUST add title and suggestion | agent can act on it |
| valueerror-with-annotation | Use titled format instead of Category/Message labels | consistent format |
| valueerror-without-annotation | Add title and suggestion, consistent format | agent can act on it |
| generic-exception-typeerror | Show exception_type, use titled format | exception_type visible |
| runtime-shell-error | Use titled format, keep shell context block | consistent format, no info loss |
| runtime-api-error | Use titled format, keep API context block | consistent format, no info loss |
| runtime-mcp-error | Use titled format, keep MCP context block | consistent format, no info loss |
| runtime-template-error | Use titled format, keep template context block | consistent format, no info loss |
| Bypass paths | Delete — all go through diagnostic pipeline | zero bypass paths |

### Non-negotiable outcomes

1. **Zero dropped context keys** (except `action` which is always "error" — low value)
2. **One error format** for all error types (titled format, adaptive to content)
3. **Every error has a title** (derived if not explicit)
4. **Every error with available suggestions shows them**
5. **Context blocks render universally** for all error types that have them
6. **File-not-found and permission-error** go from worst to acceptable (title + suggestion)
7. **Bypass paths eliminated** — registry_run uses diagnostic pipeline
