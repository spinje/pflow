## Ambiguities Requiring Resolution

### A1. Parser error type (Phase 1)

The plan says "clear errors with line numbers" but doesn't specify the exception type.

**Options**:

a) **Custom `MarkdownParseError(ValueError)`** with structured fields:
   ```python
   class MarkdownParseError(ValueError):
       def __init__(self, message: str, line: int | None = None, suggestion: str | None = None):
           self.line = line
           self.suggestion = suggestion
           super().__init__(message)
   ```
   - Pro: Callers can access line/suggestion programmatically
   - Pro: `ValueError` subclass so existing `except ValueError` catches work unchanged

b) **Plain `ValueError` with formatted message strings**:
   - Pro: Simpler, no new class
   - Con: No structured access to line numbers

c) **Reuse existing `WorkflowValidationError`**:
   - Pro: Consistent with existing error handling
   - Con: That exception is for post-parse validation, not parse-time errors

**Recommendation**: Option (a). A lightweight custom exception that's a ValueError subclass. Catches work unchanged, but callers that care about line numbers (e.g., CLI error display) can access them.

### A2. What happens when someone runs natural language with planner gated (Phase 0.2)

Currently, if `resolve_workflow()` returns nothing, the CLI falls through to `_execute_with_planner()`. With planner gated, what UX?

**Options**:

a) Show error: `"Natural language workflow generation is temporarily unavailable. Provide a workflow file (.pflow.md) or saved workflow name instead."`

b) Show error with example: Same message + `"Example: pflow ./my-workflow.pflow.md or pflow my-saved-workflow"`

**Recommendation**: Option (b). Simple and actionable.

### A3. Where to add unknown param warnings (Phase 2.8)

**Options**:

a) **New validation layer 8 in `WorkflowValidator.validate()`**:
   - Pro: Runs in all validation paths (CLI, MCP, save)
   - Pro: Consistent with existing validation architecture
   - Con: Needs registry passed in (already optional parameter)

b) **In compiler after template validation (~line 1058)**:
   - Pro: Near related code (template validation already loads interface metadata)
   - Con: Only runs during compilation, not during `--validate-only`

**Recommendation**: Option (a). Add as layer 8 in WorkflowValidator. It already accepts an optional `registry` parameter. This way `--validate-only` and MCP validation also benefit.

### A4. Double-parsing in save pipeline (Phase 2)

The save flow currently looks like:

```
CLI save:    read file -> parse_markdown() -> validate IR -> save_workflow_with_options(content)
             └─ parse #1                                     └─ WorkflowManager.save(content)
                                                                 └─ parse_markdown() again?  ← parse #2
```

Should `WorkflowManager.save()` re-parse the content to validate, or trust the caller?

**Options**:

a) **Parse once, trust the caller**: `WorkflowManager.save()` accepts pre-validated content and just prepends frontmatter. No re-parsing.
   - Pro: No wasted work
   - Con: If someone calls `save()` directly with invalid content, it gets saved

b) **Always parse in save()**: Defensive double-validation.
   - Pro: `save()` is self-contained and safe
   - Con: Parsing twice for every save

c) **Accept both**: `save()` takes `markdown_content` + optional `parsed_result: MarkdownParseResult = None`. If parsed_result is provided, skip re-parsing.
   - Pro: Flexible
   - Con: More complex API

**Recommendation**: Option (a). `WorkflowManager.save()` trusts the caller. All callers (CLI save, MCP save, workflow_save_service) already validate before calling save. This matches the current pattern — `json.dump()` doesn't re-validate the dict either. The save method's job is storage, not validation.

But `save()` DOES still need to parse to extract the description (from H1 prose) for the return value metadata. So it's not zero parsing — it's a lightweight parse for metadata extraction only. Actually, even this can be avoided if the caller passes the description. Let me refine:

**Refined recommendation**: `save()` signature:
```python
def save(self, name: str, markdown_content: str, description: str = "", metadata: dict | None = None) -> str:
```
Caller extracts description during validation and passes it. `save()` does zero parsing — just prepends frontmatter and writes.

### A5. Node ID validation regex (Phase 1)

The spec says "lowercase alphanumeric with hyphens or underscores (no spaces)" but doesn't give an exact regex.

**Questions**:
- Can IDs start with a digit? (e.g., `1-fetch`)
- Can IDs have consecutive hyphens? (e.g., `fetch--data`)
- Can IDs have leading/trailing hyphens? (e.g., `-fetch-`)
- Underscores and hyphens mixed? (e.g., `fetch_data-v2`)

**Recommendation**: `^[a-z][a-z0-9_-]*$` — must start with a lowercase letter, followed by lowercase letters, digits, hyphens, underscores. No consecutive special chars, no leading/trailing special chars enforced by "must start with letter." This matches existing conventions in all example workflows.

### A6. `ir_to_markdown()` — how to handle arbitrary param values (Phase 0.3)

Most params are simple (`- url: https://example.com`). But some params are complex dicts/lists. The test utility needs to decide how to serialize them.

**Rule set**:
- `str`, `int`, `float`, `bool`: inline `- key: value`
- `dict` or `list` that's a known param (`stdin`, `headers`, `output_schema`): `yaml {param_name}` code block
- `dict` or `list` that's NOT a known param: inline YAML using `yaml.dump()` with flow style
  ```
  - complex_param: {nested: value, list: [1, 2]}
  ```

**Recommendation**: This rule set. Simple values inline, known complex params as code blocks, unknown complex params as inline YAML. The utility doesn't need to be perfect — it just needs to produce parseable markdown for tests.

### A7. Prose joining rules (Phase 1)

How exactly is prose collected and joined?

**Proposed rules**:
1. Non-blank lines that aren't `- ` params, code fences, or headings = prose lines
2. Consecutive prose lines are joined with `\n` (preserving original line breaks)
3. Prose groups separated by blank lines, params, or code blocks are joined with `\n\n`
4. Final result is stripped of leading/trailing whitespace

**Example**:
```markdown
### analyze

First paragraph about
what this does.

- type: llm

Second paragraph with
design rationale.
```

Purpose: `"First paragraph about\nwhat this does.\n\nSecond paragraph with\ndesign rationale."`

**Recommendation**: These rules. Matches natural markdown paragraph behavior.

### A8. What about `- ` lines that aren't valid YAML key-value pairs? (Phase 1)

Example: `- This is just a note` (no colon, not a key-value pair).

`yaml.safe_load("- This is just a note")` produces `["This is just a note"]` — a string, not a dict.

**Recommendation**: After YAML parsing, validate each item is a `dict`. If not, error:
```
Line 15: '- This is just a note' is not a valid parameter.

Parameters must use key: value format:
    - key: value

For documentation bullets, use * instead of -:
    * This is just a note
```

This is critical because it's the primary mitigation for the `- ` footgun.