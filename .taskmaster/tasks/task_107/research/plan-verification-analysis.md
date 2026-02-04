# Task 107: Plan Verification Analysis

> Cross-referencing all three documents (task-107.md, format-specification.md, implementation-plan.md)
> plus the ambiguity.md and codebase-verification-report.md against the actual codebase.

---

## 1. Internal Contradictions Between Documents

### C1. Save pipeline: `WorkflowManager.save()` signature disagreement

**Ambiguity doc A4** resolves to:
```python
def save(self, name: str, markdown_content: str, description: str = "", metadata: dict | None = None) -> str:
```
(Caller passes description, save does zero parsing.)

**Implementation plan Phase 2.2** shows:
```python
def save(self, name: str, markdown_content: str, metadata: dict | None = None) -> str:
```
(No `description` parameter. Plan says "Parse markdown to validate... Extract description from H1 prose".)

These are **directly contradictory**. The ambiguity resolution says "save does zero parsing" but the plan says "parse to extract description."

**Resolution needed**: Pick one. Ambiguity doc's approach (caller passes description) is cleaner — save() becomes a pure storage method. But then every caller must extract description before calling save(). Since callers already parse for validation, this is free.

### C2. Unknown param warnings: location disagreement

**Ambiguity doc A3** recommends: "Layer 8 in WorkflowValidator.validate()" — runs in all validation paths including `--validate-only` and MCP validation.

**Implementation plan Phase 2.8** says: "During compilation, after template validation (~line 1058)" — only runs during compilation, NOT during `--validate-only`.

The ambiguity resolution was made AFTER the plan but the plan wasn't updated.

**Resolution needed**: Use A3 recommendation (layer 8 in WorkflowValidator). The validator already accepts an optional `registry` parameter and has 7 layers. Adding layer 8 is natural.

### C3. MCP save flow: content preservation gap

**Format spec Decision 27** says: MCP tools accept "raw `.pflow.md` content strings or file paths — not IR dicts."

**Implementation plan Phase 2.5** says MCP save should reject dicts for save.

**Actual codebase**: The MCP save flow goes:
```
workflow_save() → ExecutionService.save_workflow() → resolve_workflow() → load_and_validate_workflow() → save_workflow_with_options(name, workflow_ir, description) → WorkflowManager.save(name, workflow_ir, description, metadata)
```

The ENTIRE chain passes IR dicts. Changing to pass markdown content requires restructuring **6 functions** in the chain, not just the resolver. The plan underestimates this.

**Resolution needed**: Define the exact new call chain. Proposal:
```
workflow_save(workflow_str_or_path, name)
  → detect type (content vs path)
  → read content if path
  → parse_markdown() to validate → get IR for format_save_success()
  → save_workflow_with_options(name, markdown_content)
  → WorkflowManager.save(name, markdown_content, description)
```

### C4. Test file list is incomplete

**Implementation plan Phase 3.3** lists 17 test files.

**Actual codebase** has at least 25+ files writing JSON workflows to disk:
- Missing from list: `test_workflow_save_cli.py` (13 writes), `test_validate_only.py` (11 writes), `test_dual_mode_stdin.py` (18 writes), `test_shell_stderr_warnings.py` (9 writes), `test_enhanced_error_output.py` (9 writes), `test_workflow_save.py` (8 writes), `test_workflow_manager.py` (3 writes), `test_workflow_manager_update_ir.py` (9 writes)

**Resolution needed**: Update the test file list. Total disk-write occurrences is ~200+, not ~50.

---

## 2. Wrong Assumptions in the Plan

### W1. "MCP execution_service.save_workflow() — No changes needed"

The MCP codebase searcher concluded "no changes needed" for execution_service.py because it "delegates to core service." This is WRONG. The execution_service signature is:
```python
def save_workflow(cls, workflow: Any, name: str, description: str, force: bool = False, generate_metadata: bool = False) -> str:
```

The `description` parameter must be removed (extracted from markdown content). The `generate_metadata` parameter must be gated. And `_save_and_format_result()` needs both the IR (for formatting) and the markdown content (for saving). This is non-trivial.

### W2. Planner tests indirectly affected

`test_planner_integration.py` doesn't write JSON files directly, BUT it calls `WorkflowManager.save()` which currently writes JSON. After Task 107, `WorkflowManager.save()` expects markdown content, not IR dicts. So planner tests WILL break unless:
- Planner tests are updated to pass markdown content
- OR `WorkflowManager.save()` keeps a dict-accepting path for programmatic use
- OR planner tests are gated/skipped

**Resolution needed**: Since planner is being gated (Decision 26), planner tests should be gated too. But verify the gating mechanism handles test imports correctly.

### W3. `_setup_workflow_execution()` has TWO `.json` references

Plan mentions the source_file_path check at line 3384. But lines 3387-3389 also strip `.json` for saved workflow names. Both need updating.

### W4. Agent instructions not addressed

`cli-agent-instructions.md` has ~13 references to JSON workflow examples. The spec mentions "Agent instruction rewrite — needed before launch but not part of this task" but doesn't list it as a TODO. The plan doesn't mention it at all.

If instructions are NOT updated, agents will continue generating JSON workflows that won't parse. This is a **functional regression** even if technically "out of scope."

**Resolution needed**: Either update instructions as part of Task 107, or create a blocking follow-up task.

### W5. `is_likely_workflow_name()` not mentioned

This function at main.py:3574 checks for `.json` extension. Not mentioned in any document. Must be updated to `.pflow.md`.

---

## 3. Gaps Requiring Deeper Exploration

### E1. WorkflowManager.load() return structure compatibility

Current callers expect:
```python
{"name": name, "description": str, "ir": dict, "created_at": str, "updated_at": str, "version": str, "rich_metadata": dict}
```

The plan says to flatten `rich_metadata` into top-level. This means callers checking `metadata.get("rich_metadata", {}).get("execution_count")` will break.

**Need to verify**: Which callers access `rich_metadata` directly? The `update_metadata()` method writes to it, `list_all()` returns it, and display formatters may read it.

### E2. WorkflowManager.save() programmatic use

Current signature accepts IR dicts. Multiple callers (planner tests, MCP service, executor_service) pass dicts. Changing to accept only markdown strings breaks all programmatic callers.

**Options**:
a) All callers must produce markdown strings — requires ir_to_markdown() in production code (spec explicitly rules this out)
b) Keep dict path for programmatic use, add markdown path — two APIs
c) Only accept markdown for file-based save, keep dict for programmatic save via different method

**The spec says**: "Markdown replaces JSON as the only workflow file format" but also "The in-memory dict (IR) remains for programmatic use." This suggests option (b) or (c).

### E3. MCP resolver content detection robustness

Plan says: "String with newlines → raw markdown content." But what if someone passes a multiline string that's NOT markdown? E.g., a multiline error message or path with newlines.

The detection heuristic (codebase verification report Decision 3) seems robust because:
- Library names can't contain newlines
- File paths are single-line
- Only markdown content would have newlines

But should there be a validation step after detection? If the string has newlines but doesn't parse as valid markdown, what error message appears?

### E4. Frontmatter roundtrip: YAML serialization gotchas

`yaml.dump()` can produce different formatting than the original frontmatter. E.g.:
- `created_at: "2026-01-14T15:43:57"` might become `created_at: '2026-01-14T15:43:57'`
- Lists might get different indentation
- Order might change

This matters for `update_metadata()` which reads/modifies/writes frontmatter. Repeated updates could cause formatting drift.

**Mitigation**: Use `yaml.dump(data, default_flow_style=False, sort_keys=False)` and accept that formatting may shift slightly. Not a functional issue.

### E5. `test_workflow_manager_update_ir.py` — 9 test methods

This file specifically tests `WorkflowManager.update_ir()`. The plan says `update_ir()` is "preserved but unreachable." But these tests call it directly. They'll still pass (method exists) but are testing dead code.

**Decision**: Leave tests in place or delete them? Low importance but should be documented.

### E6. Code blocks inside YAML `- ` param lines

What happens if an agent writes:
```markdown
- command: |
    echo "hello"
    echo "world"
```

This is valid YAML block scalar syntax under a `- ` param line. The parser needs to handle YAML block scalars (pipe `|` and `>`) correctly. The spec mentions "YAML continuation collection rules" but doesn't explicitly test block scalars.

**Need to verify**: Does the continuation rule (indented lines after `- key:`) correctly capture YAML block scalars? The `|` after `command:` followed by indented lines should be collected as one YAML item.

---

## 4. Implementation Risk Assessment (Updated)

### HIGH RISK

1. **MCP save flow restructuring** — Deeper than the plan acknowledges. 6 functions in the chain need signature changes. The format_save_success() dependency on IR while save needs markdown content creates a dual-data-flow requirement.

2. **Test migration scope** — 200+ disk-write occurrences across 25+ files, not 17. The `ir_to_markdown()` test utility must handle ALL IR patterns used in tests.

3. **WorkflowManager.save() API break** — Changing from dict to string input breaks all programmatic callers. Need a clear strategy (likely: accept both types, or separate methods).

### MEDIUM RISK

4. **YAML continuation parsing** — Block scalars (`|`, `>`), flow sequences, and nested dicts under `- ` lines. The parser must handle these correctly or error clearly.

5. **Frontmatter management** — update_metadata() must correctly split/merge frontmatter without corrupting the markdown body. Edge case: file with no frontmatter (authored file) being updated after first execution.

6. **Agent instructions** — If not updated, agents will generate JSON. Functional regression.

### LOW RISK

7. **Gating planner/repair** — Simple if-guards.
8. **Error message updates** — Find-and-replace style.
9. **Example conversion** — Mechanical but tedious.

---

## 5. Recommended Changes to Implementation Plan

### Change 1: Resolve save() signature (C1)

Use ambiguity doc approach: `save(name, markdown_content, description="", metadata=None)`. Caller extracts description during validation. Save does zero parsing. This keeps WorkflowManager as a pure storage layer.

For programmatic callers (tests, internal code that needs to save IR dicts), add:
```python
def save_from_ir(self, name: str, workflow_ir: dict, description: str = "", metadata: dict | None = None) -> str:
    """Save from IR dict — uses ir_to_markdown() internally. For programmatic use only."""
    from pflow.core.markdown_serializer import ir_to_markdown  # or inline
    content = ir_to_markdown(workflow_ir, title=name)
    return self.save(name, content, description, metadata)
```

Wait — the spec explicitly rules out IR-to-markdown serialization. But without it, how do programmatic callers save workflows? The MCP execute tool doesn't save, but what about the MCP save tool when it receives a dict (backward compat)?

**Alternative**: Since we're removing JSON support, the MCP save tool should ONLY accept markdown strings (per the spec). The dict path is removed. Tests use `ir_to_markdown()` from the test utility. This means `ir_to_markdown()` is test-only, NOT production code. Clean.

### Change 2: Move unknown param warnings to validator layer 8 (C2)

Per ambiguity resolution A3. This ensures `--validate-only` benefits.

### Change 3: Define exact MCP save chain (C3)

New MCP save flow:
```
workflow_save(workflow_str, name, force)
  → ExecutionService.save_workflow(workflow_str, name, force)
    → detect: content (has \n) or path (ends .pflow.md)
    → read file if path → markdown_content
    → result = parse_markdown(markdown_content)  # validates + extracts IR + description
    → save_workflow_with_options(name, markdown_content, result.description, force=force, metadata=None)
      → WorkflowManager.save(name, markdown_content, result.description, metadata)
    → return format_save_success(name, path, result.ir, ...)  # IR for display
```

### Change 4: Expand test file list (C4)

Add all missing files. Consider creating a script that does `grep -rl 'json.dump\|\.json' tests/ | sort` to catch everything.

### Change 5: Add agent instructions update as follow-up task (W4)

Create a blocking follow-up task for agent instruction updates. Without this, the feature is broken for its primary users (agents).

### Change 6: Add `is_likely_workflow_name()` to integration checklist (W5)

### Change 7: Handle `_setup_workflow_execution()` second `.json` reference (W3)

---

## 6. Verified: Plan Is Correct On These

- normalize_ir() behavior and what the parser should/shouldn't produce
- Edge generation from document order (mandatory)
- Param routing rules per section type
- Code block tag mapping
- Top-level IR field set
- Gating approach for planner/repair
- PyYAML dependency move
- Node ID format from headings
- Frontmatter for saved workflows only
- Description from H1 prose

---

## 7. Final Pre-Implementation Checklist

Before coding begins, resolve:

1. [ ] **Save() signature** — pick between ambiguity doc and plan approaches
2. [ ] **Unknown param warning location** — layer 8 in validator vs compiler
3. [ ] **MCP save chain** — define exact new flow with dual data (IR + content)
4. [ ] **WorkflowManager.save() programmatic use** — how do tests save workflows?
5. [ ] **Agent instructions** — in-scope or follow-up task?
6. [ ] **Planner test gating** — skip/gate planner tests or leave working?
7. [ ] **Block scalar YAML** — test this in parser design
8. [ ] **Complete test file inventory** — get exact count
