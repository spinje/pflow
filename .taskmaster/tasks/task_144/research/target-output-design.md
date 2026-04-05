# Target Output Design: Single-Format Diagnostic Rendering

## The Template

Every error uses the same structure. Sections are omitted when their data is absent.

```
Error[  N]: {title}

{message}
  At: {location}

  {context block(s)}

To fix this:
  1. {suggestion}

Run with --verbose for technical details.
```

### Rules

1. **Title**: Always present. Read from `diagnostic.title` (first-class field). Set by `to_diagnostics()` methods on exception classes, or by the built-in exception fallback handler.
2. **Message**: Always present. The `diagnostic.message` field.
3. **Location** (`At:`): Shown when `node_id`, `path`, or `line` is available. Format: `node 'X'`, `nodes[0].type`, `line 42`. Multiple parts comma-separated.
4. **Context blocks**: Named subsections. Rendered for ALL error types when the data exists. Each block type has its own renderer (shell, API, MCP, template, compilation, similar-names, failures).
5. **Suggestions**: Read from `diagnostic.suggestions` (first-class list field). Single → `→ text`. Multiple → numbered list under `To fix this:`.
6. **Verbose hint**: Last line. Only shown when `technical_details` exists in context and `verbose=False`.
7. **Warnings**: Unchanged (already one clean path).

### Title Derivation

For PflowError subclasses, `to_diagnostics()` sets `title=` directly. For built-in exceptions that can't have `to_diagnostics()`, the fallback handler derives from category:

| Category | Derived Title |
|----------|--------------|
| `compilation` | Compilation Failed |
| `max_visits` | Infinite Loop Detected |
| `validation` | Validation Error |
| `parse_error` | Parse Error |
| `not_found` | Workflow Not Found |
| `file_not_found` | File Not Found |
| `permission_denied` | Permission Denied |
| `execution_failure` | Execution Failed |
| `api_validation` | API Validation Error |
| `template_error` | Template Error |
| `mcp` | MCP Error |
| `cli` | Error |
| (fallback) | Error |

---

## Per-Fixture Before/After

### compilation-error

**BEFORE:**
```
Error at node 'fetch':
  Category: compilation
  Message: Node type 'httpp' is not registered

  Suggestion: Check available node types with: pflow registry list
  Node type: httpp
  Sub-workflow: ./child.pflow.md
```

**AFTER:**
```
Error: Compilation Failed

Node type 'httpp' is not registered
  At: node 'fetch'

  Phase: node_import
  Node type: httpp
  Sub-workflow: ./child.pflow.md

  → Check available node types with: pflow registry list
```

**With error_number=1:**
```
Error 1: Compilation Failed

Node type 'httpp' is not registered
  At: node 'fetch'

  Phase: node_import
  Node type: httpp
  Sub-workflow: ./child.pflow.md

  → Check available node types with: pflow registry list
```

**What improved:**
- Title replaces `Error at node:` header
- `phase` now shown (was DROPPED)
- No `Category:` / `Message:` labels
- Same format with or without error_number
- Location on `At:` line instead of in header

---

### max-visits-error

**BEFORE (no error_number):**
```
❌ Node 'process' exceeded maximum visits (100/100). This likely indicates an infinite loop in the workflow. Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional.
```

**AFTER:**
```
Error: Infinite Loop Detected

Node 'process' exceeded maximum visits (100/100). This likely indicates an infinite loop in the workflow.
  At: node 'process'

  → Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional.
```

**What improved:**
- Title instead of bare `❌` + wall-of-text
- Suggestion separated from message (was embedded at the end)
- Location shown on `At:` line
- Same structure with or without error_number (was completely different)

---

### workflow-validation-error [1/3]

**BEFORE (no error_number):**
```
❌ Unknown node type 'httpp'
   At: nodes[0].type
   👉 Use 'shell', 'http', 'llm', 'file', or 'mcp'
```

**BEFORE (error_number=1):**
```
Error 1:
  Category: validation
  Message: Unknown node type 'httpp'

  Suggestion: Use 'shell', 'http', 'llm', 'file', or 'mcp'
  At: nodes[0].type
```

**AFTER (both):**
```
Error: Validation Error

Unknown node type 'httpp'
  At: nodes[0].type

  → Use 'shell', 'http', 'llm', 'file', or 'mcp'
```

```
Error 1: Validation Error

Unknown node type 'httpp'
  At: nodes[0].type

  → Use 'shell', 'http', 'llm', 'file', or 'mcp'
```

**What improved:**
- Consistent format regardless of error_number (was completely different styles)
- Title replaces `❌` / `Category: validation`
- No `Category:` / `Message:` labels

---

### schema-validation-error

**BEFORE:**
```
❌ 'steps' is not a valid section name
   At: root.sections
   👉 Did you mean '## Steps'? Section names are case-sensitive.
```

**AFTER:**
```
Error: Validation Error

'steps' is not a valid section name
  At: root.sections

  → Did you mean '## Steps'? Section names are case-sensitive.
```

**What improved:** Consistent format with all other errors. Title line.

---

### markdown-parse-error

**BEFORE:**
```
✗ Line 42: Unclosed code fence
    → Add a closing ``` to terminate the code block.
```

**AFTER:**
```
Error: Parse Error

Unclosed code fence
  At: line 42

  → Add a closing ``` to terminate the code block.
```

**What improved:**
- Title line
- `line` shown as structured location, not embedded in message text
- Consistent format

**Implementation note:** `MarkdownParseError.__str__()` embeds "Line N:" in the message. `MarkdownParseError.to_diagnostics()` uses `self.raw_message` (to be added, same pattern as `CompilationError.raw_message`) for a clean message without the prefix.

---

### workflow-not-found-with-suggestions

**BEFORE:**
```
❌ Workflow 'my-workfow' not found.

Did you mean one of these?
  - my-workflow
  - my-workflow-v2
```

**AFTER:**
```
Error: Workflow Not Found

Workflow 'my-workfow' not found.

Did you mean one of these?
  - my-workflow
  - my-workflow-v2

  → Use 'pflow workflow list' to see all available workflows.
```

**What improved:**
- Title line for consistency
- Generic guidance suggestion added (agents always get next steps)
- "Did you mean" list preserved as context block

**Implementation note:** `WorkflowNotFoundError.to_diagnostics()` sets `suggestions=["Use 'pflow workflow list' to see all available workflows."]` (generic guidance). The "Did you mean" similar names are in `context["similar_names"]` and rendered as a context block.

---

### workflow-not-found-with-hint

**BEFORE:**
```
❌ No saved workflows found. Use 'pflow save' to save a workflow first.
```

**AFTER:**
```
Error: Workflow Not Found

No saved workflows found. Use 'pflow save' to save a workflow first.
```

**What improved:** Title for consistency. Otherwise the hint was already a good message.

---

### output-resolution-error

**BEFORE:**
```
Error: 2 workflow outputs could not be resolved

  Output 'summary' (source: ${branch-a.result}):
    - Node 'branch-a' did not execute on this path
  Output 'details' (source: ${branch-b.response}):
    - Key 'response' not found in node 'branch-b' output

To fix this:
  1. Use the ?? coalesce operator for branch-dependent outputs: source: ${branch-a.result ?? branch-b.result}
  2. Check that source expressions reference nodes that always execute on this path

Run with --verbose for technical details.
```

**AFTER: Same.** Already uses the titled format. This IS the target format.

---

### mcp-error

**BEFORE / AFTER: Same.** Already uses the titled format. No changes.

---

### user-friendly-error

**BEFORE / AFTER: Same.** Already uses the titled format. No changes.

---

### file-not-found-error

**BEFORE:**
```
✗ workflow.pflow.md
```

**AFTER:**
```
Error: File Not Found

workflow.pflow.md

  → Check the file path and ensure the file exists.
```

**What improved:**
- **CRITICAL**: From 4 characters of content to structured, actionable output
- Title identifies the error type
- Suggestion added (agent knows what to do)
- Consistent format

**Implementation note:** The built-in exception fallback handler produces `Diagnostic(title="File Not Found", suggestions=["Check the file path and ensure the file exists."], ...)`.

---

### permission-error

**BEFORE:**
```
✗ Permission denied: /etc/pflow/config
```

**AFTER:**
```
Error: Permission Denied

Permission denied: /etc/pflow/config

  → Check file permissions and access rights.
```

**What improved:** Same as file-not-found — from bare message to structured, actionable output.

---

### valueerror-with-node-annotation

**BEFORE:**
```
Error at node 'parse':
  Category: execution_failure
  Message: Invalid JSON response from API
```

**AFTER:**
```
Error: Execution Failed

Invalid JSON response from API
  At: node 'parse'
```

**What improved:**
- Title instead of `Error at node:` header
- No `Category:` / `Message:` labels
- Location on `At:` line

---

### valueerror-without-annotation

**BEFORE:**
```
✗ Missing required field 'type' in node configuration
```

**AFTER:**
```
Error: Validation Error

Missing required field 'type' in node configuration
```

**What improved:** Title. Consistent format with all other errors.

---

### generic-exception-typeerror

**BEFORE:**
```
Error at node 'transform':
  Category: execution_failure
  Message: Expected str, got int for parameter 'count'
```

**AFTER:**
```
Error: Execution Failed

Expected str, got int for parameter 'count'
  At: node 'transform'
  Type: TypeError
```

**What improved:**
- `exception_type` now shown (was DROPPED) — agent can identify the exception class
- Title instead of `Error at node:`
- No `Category:` / `Message:` labels

---

### runtime-shell-error

**BEFORE:**
```
Error at node 'deploy':
  Category: execution_failure
  Message: Command failed with exit code 1

  Shell details:
    Command: npm run build && npm run deploy
    Stdout: Building project...
Build complete.
    Stderr: Error: Cannot find module 'react'
  at Function.Module._resolveFilename
```

**AFTER:**
```
Error: Execution Failed

Command failed with exit code 1
  At: node 'deploy'

  Shell details:
    Command: npm run build && npm run deploy
    Stdout: Building project...
Build complete.
    Stderr: Error: Cannot find module 'react'
  at Function.Module._resolveFilename
```

**What improved:** Title. No labels. Location on `At:` line. Context block preserved exactly.

---

### runtime-api-error

**BEFORE:**
```
Error at node 'create-issue':
  Category: api_validation
  Message: HTTP request failed with status 422

  API Response:
    - Field 'title': Title is required
    - Field 'labels': Invalid label: 'urgent'

  Documentation: https://docs.github.com/rest/issues
```

**AFTER:**
```
Error: API Validation Error

HTTP request failed with status 422
  At: node 'create-issue'

  API Response:
    - Field 'title': Title is required
    - Field 'labels': Invalid label: 'urgent'

  Documentation: https://docs.github.com/rest/issues
```

**What improved:** Title (more descriptive than "Error at node"). No labels. Context block preserved.

---

### runtime-mcp-error

**BEFORE:**
```
Error at node 'mcp-jira-search_issues':
  Category: execution_failure
  Message: MCP tool 'search_issues' returned an error

  MCP Tool Error:
    Field: jql
    Expected: valid JQL query
    Received: project = INVALID
```

**AFTER:**
```
Error: Execution Failed

MCP tool 'search_issues' returned an error
  At: node 'mcp-jira-search_issues'

  MCP Tool Error:
    Field: jql
    Expected: valid JQL query
    Received: project = INVALID
```

---

### runtime-template-error

**BEFORE:**
```
Error at node 'fetch':
  Category: template_error
  Message: Undefined variable '${api_key}' in node 'fetch'

  Available fields in node (showing 5 of 12):
    - stdout
    - stderr
    - exit_code
    - result
    - response

  📁 Complete field list available in trace file
     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
```

**AFTER:**
```
Error: Template Error

Undefined variable '${api_key}' in node 'fetch'
  At: node 'fetch'

  Available fields in node (showing 5 of 12):
    - stdout
    - stderr
    - exit_code
    - result
    - response

  📁 Complete field list available in trace file
     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
```

---

### Warnings (UNCHANGED)

```
  ⚠ Section heading '## Input' looks like a typo
    → Rename to '## Inputs' (plural) for it to be recognized.
```

```
  ⚠ [send-alert] Cache enabled but node has side effects
    → Consider adding 'cache: false' to this node.
```

No changes. Warning rendering is already a single clean path.

---

## Wrapper Function Targets

### format_validation_failure(3 errors)

**BEFORE:**
```
✗ Static validation failed:
  • Unknown node type 'httpp'
  • Missing required field 'type'
  • Undefined template variable '${api_key}'

Suggestions:
  • Use 'registry list' to see available nodes
  • Check template syntax: ${node.output}
```

**AFTER:**
```
✗ Validation failed (3 errors):

  1. Unknown node type 'httpp'
     At: nodes[0].type
     → Use 'shell', 'http', 'llm', 'file', or 'mcp'

  2. Missing required field 'type'
     At: nodes[1]
     → Every node must have a 'type' field

  3. Undefined template variable '${api_key}'
     At: nodes[2].params.url
```

**What improved:**
- Each error shows its SPECIFIC suggestion (from Diagnostic) instead of generic auto-generated ones
- Each error shows its LOCATION (from `context["path"]`)
- Numbered for clarity
- No information lost — gained location and specific suggestions

### format_validation_failure(15 errors, truncation)

**BEFORE:**
```
✗ Static validation failed:
  • Validation error 0
  • Validation error 1
  ...
  • Validation error 9
  ... and 5 more errors
```

**AFTER:**
```
✗ Validation failed (15 errors):

  1. Validation error 0
  2. Validation error 1
  3. Validation error 2
  4. Validation error 3
  5. Validation error 4

  ... and 10 more errors
```

**What changed:** Truncation at 5 (was 10) because each error can be multi-line with location + suggestion. Errors with no path/suggestion are single-line within the list.

---

### _build_error_text(1 error + 1 warning)

**BEFORE:**
```
❌ Command failed with exit code 1 (1 warnings)

Error details:
Error at node 'deploy':
  Category: execution_failure
  Message: Command failed with exit code 1

  Shell details:
    Command: npm run deploy
    Stderr: Error: EACCES permission denied

Warnings:
  ⚠ [send-alert] Cache enabled but node has side effects
```

**AFTER:**
```
❌ Execution Failed (1 warning)

Command failed with exit code 1
  At: node 'deploy'

  Shell details:
    Command: npm run deploy
    Stderr: Error: EACCES permission denied

Warnings:
  ⚠ [send-alert] Cache enabled but node has side effects
```

**What improved:**
- Header uses diagnostic title (was raw error message)
- Error detail uses titled format (consistent with standalone rendering)
- No `Category:` / `Message:` labels
- "1 warnings" → "1 warning" (grammar)
- "Error details:" label removed

---

### _build_error_text(3 errors + 0 warnings)

**BEFORE:**
```
❌ Workflow execution failed

Error details:
Error 1 at node 'fetch':
  Category: execution_failure
  Message: Node 'fetch' failed: timeout
Error 2 at node 'parse':
  Category: execution_failure
  Message: Node 'parse' failed: invalid JSON
Error 3 at node 'deploy':
  Category: execution_failure
  Message: Node 'deploy' skipped: upstream failure
```

**AFTER:**
```
❌ Workflow execution failed

Error 1: Execution Failed

Node 'fetch' failed: timeout
  At: node 'fetch'

Error 2: Execution Failed

Node 'parse' failed: invalid JSON
  At: node 'parse'

Error 3: Execution Failed

Node 'deploy' skipped: upstream failure
  At: node 'deploy'
```

**What improved:** Each error uses titled format. No labels. Clear separation between errors.

---

### format_success_as_text(2 warnings)

**BEFORE / AFTER: Identical.** Warning rendering unchanged. The only difference is the data flow (Diagnostics passed directly instead of dict round-trip), not the visual output.

---

## Bypass Path Targets (eliminated — replaced by diagnostic pipeline)

### registry format_node_not_found_error → Diagnostic pipeline

**BEFORE (bypass):**
```
❌ Node 'read-fle' not found in registry

No similar nodes found. Available nodes:
  - http
  - llm
  - read-file
  - read-url
  - shell
  - write-file

To find the right node:
  - Use registry_discover to search: "describe what you want to do"
  - Use registry_list to see all available nodes
```

**AFTER (diagnostic):**
```
Error: Node Not Found

Node 'read-fle' not found in registry.

Did you mean one of these?
  - read-file

To fix this:
  1. Use 'pflow registry discover' to search for nodes
  2. Use 'pflow registry list' to see all available nodes
```

**Implementation:** The registry_run command constructs a Diagnostic directly (not via exception):
```python
Diagnostic(severity=ERROR, title="Node Not Found",
           message="Node 'read-fle' not found in registry.",
           suggestions=["Use 'pflow registry discover' to search for nodes", ...],
           source="registry",
           context={"category": "not_found", "similar_names": [...]})
```

Then calls `format_diagnostic()`. Same pipeline as workflow errors.

### registry format_execution_error → Diagnostic pipeline

**BEFORE (bypass, FileNotFoundError):**
```
❌ Failed to execute node 'fetch'

Error: input.txt

Verify the file path exists and is accessible.
```

**AFTER (diagnostic):**
```
Error: File Not Found

input.txt

  → Check the file path and ensure the file exists.
```

Uses `exception_to_diagnostics(FileNotFoundError)` + `format_diagnostic()`. Same output as if the error occurred in a workflow.

### registry format_ambiguous_node_error → Diagnostic pipeline

**BEFORE (bypass):**
```
❌ Ambiguous node name 'search'. Found in multiple servers:
  - mcp-confluence-search
  - mcp-github-search
  - mcp-jira-search

Please specify the full node ID or use format: {server}-{tool}

Examples:
  registry_run('mcp-github-search')  # Full format
  registry_run('github-search')  # Server-qualified
```

**AFTER (diagnostic):**
```
Error: Ambiguous Node Name

Ambiguous node name 'search'. Found in multiple servers.

Matching nodes:
  - mcp-confluence-search
  - mcp-github-search
  - mcp-jira-search

To fix this:
  1. Specify the full node ID (e.g., 'mcp-github-search')
  2. Use format: {server}-{tool}
```

**Implementation:** Direct Diagnostic construction with `title="Ambiguous Node Name"`, `suggestions=[...]`, and `context={"similar_names": [...]}`. Reuses the same similar-names context block renderer. Examples folded into suggestions.

---

## Summary: What Changes

| Fixture | Before format | After format | Key improvement |
|---------|--------------|-------------|-----------------|
| compilation-error | Runtime default | Titled | `phase` shown, no labels |
| max-visits-error | `❌` one-liner | Titled | Structure, suggestion separated |
| validation errors | `❌`/`👉` OR runtime default | Titled | Consistent regardless of params |
| schema-validation | `❌`/`👉` | Titled | Consistent format |
| markdown-parse | `✗` simple | Titled | `line` as location, title |
| not-found | Unique `❌` format | Titled | Consistent, suggestion added |
| output-resolution | Titled ✓ | Same | No change needed |
| mcp-error | Titled ✓ | Same | No change needed |
| user-friendly | Titled ✓ | Same | No change needed |
| file-not-found | `✗ filename` | Titled | **CRITICAL: was 4 chars, now actionable** |
| permission-error | `✗ message` | Titled | **CRITICAL: suggestion added** |
| valueerror-annotated | Runtime default | Titled | No labels |
| valueerror-unannotated | `✗` simple | Titled | Title |
| generic-exception | Runtime default | Titled | `exception_type` shown |
| runtime-shell | Runtime default | Titled | No labels, title |
| runtime-api | Runtime default | Titled | Better title |
| runtime-mcp | Runtime default | Titled | No labels |
| runtime-template | Runtime default | Titled | Better title |
| validation failure list | Bullets, generic suggestions | Numbered, specific suggestions | Location + per-error suggestions |
| MCP error text | Labels | Titled | Consistent format |
| Registry bypasses | Separate formatter | Diagnostic pipeline | One system, no drift |

### Non-negotiable outcomes (scorecard)

1. ✅ One error format for all types
2. ✅ Every error has a title
3. ✅ `phase` shown for compilation errors
4. ✅ `exception_type` shown for generic exceptions
5. ✅ File-not-found and permission-error have suggestions
6. ✅ Validation errors show location and specific suggestions
7. ✅ Same format with or without error_number
8. ✅ Context blocks render for all error types
9. ✅ Registry bypass paths eliminated
10. ✅ Warning format unchanged
