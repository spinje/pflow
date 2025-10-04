# Task 71: Comprehensive Implementation Plan

## Context Gathering Complete ✅

Deployed 5 parallel subagents to gather critical implementation context:
1. ✅ Workflow.py command structure - Patterns and imports identified
2. ✅ Registry.py command structure - Command patterns documented
3. ✅ _handle_workflow_error function - Signature and call site located
4. ✅ _build_error_list function - Error dict structure confirmed
5. ✅ CLI flag definition pattern - Flag addition pattern identified

## Implementation Strategy

### Phase-Based Approach
Following the IMPLEMENTATION_REFERENCE.md order with dependencies clearly marked.

---

## Phase 1: Discovery Commands (90 min total)

### Task 1.1: workflow discover (30 min)
**File**: `src/pflow/cli/commands/workflow.py`
**Dependencies**: None
**Parallel**: Can run with registry commands

**Implementation**:
- Add import: `from pflow.planning.nodes import WorkflowDiscoveryNode`
- Add command after `describe_workflow` function
- Use direct node reuse pattern: `node.run(shared)`
- Format output with workflow metadata, flow, inputs, outputs, confidence

**Verification**:
- Command appears in `pflow workflow --help`
- Returns workflow when match found
- Shows helpful message when no match

### Task 1.2: registry discover (30 min)
**File**: `src/pflow/cli/commands/registry.py`
**Dependencies**: None
**Parallel**: Can run with workflow commands

**Implementation**:
- Add import: `from pflow.planning.nodes import ComponentBrowsingNode`
- Add command in registry command group
- Use direct node reuse pattern: `node.run(shared)`
- Display `shared["planning_context"]` directly (already formatted markdown)

**Verification**:
- Command appears in `pflow registry --help`
- Returns relevant nodes with full interface details
- LLM failures handled gracefully

### Task 1.3: registry describe (30 min)
**File**: `src/pflow/cli/commands/registry.py`
**Dependencies**: None
**Parallel**: Can run with other commands

**Implementation**:
- Add import: `from pflow.planning.context_builder import build_planning_context`
- Accept multiple node IDs: `@click.argument("node_ids", nargs=-1, required=True)`
- Validate node IDs exist before calling context builder
- Display complete specifications

**Verification**:
- Accepts multiple node IDs
- Errors gracefully for unknown nodes
- Shows complete interface details

---

## Phase 2: Validation Flag (45 min)

### Task 2.1: Add --validate-only flag (45 min)
**File**: `src/pflow/cli/main.py`
**Dependencies**: None (independent)
**Parallel**: Can implement independently

**Implementation Steps**:
1. Add flag definition around line 2792 (with other CLI options)
2. Add `validate_only: bool` to `workflow_command` signature
3. Add validation logic after workflow loading (around line 2950)
4. Use `WorkflowValidator.validate()` with `extracted_params=None` for static validation
5. Display validation results (schema, data flow, node types)
6. Exit without execution: `ctx.exit(0)` on success, `ctx.exit(1)` on failure

**Static Validation Layers**:
- ✅ Schema validation (IR structure, required fields)
- ✅ Data flow validation (execution order, acyclic graph)
- ❌ Template validation (SKIPPED when params=None)
- ✅ Node types validation (node types exist in registry)

**Verification**:
- Flag appears in `pflow --help`
- Validates workflow structure without execution
- Clear success/failure messages
- No side effects occur

---

## Phase 3: Workflow Save Command (45 min)

### Task 3.1: workflow save (45 min)
**File**: `src/pflow/cli/commands/workflow.py`
**Dependencies**: None
**Parallel**: Can implement independently

**Implementation Steps**:
1. Add imports: `from pflow.planning.nodes import MetadataGenerationNode`, `from pflow.core.ir_schema import validate_ir`
2. Add command with arguments: FILE_PATH, NAME, DESCRIPTION
3. Add options: `--delete-draft`, `--force`, `--generate-metadata`
4. Validate name (CLI strict): `^[a-z0-9-]+$`, max 30 chars
5. Load and validate workflow IR
6. Optionally generate metadata using MetadataGenerationNode
7. Call `WorkflowManager.save()`
8. Optionally delete draft with safety check (must be in `.pflow/workflows/`)

**Name Validation Logic**:
```python
# CLI validation (strict)
if not re.match(r'^[a-z0-9-]+$', name):
    error("lowercase, numbers, hyphens only")
if len(name) > 30:
    error("max 30 characters")

# WorkflowManager provides backup validation (permissive)
```

**Verification**:
- Validates name format correctly
- Saves to `~/.pflow/workflows/`
- --generate-metadata creates rich metadata
- --delete-draft removes source (with safety check)
- --force overwrites existing

---

## Phase 4: Enhanced Error Output (90 min) ⚠️ TWO LAYERS

### Task 4.1: Data Layer - Extract Rich Error Data (45 min)
**File**: `src/pflow/execution/executor_service.py`
**Dependencies**: MUST BE DONE FIRST (before display layer)
**Critical**: Display layer won't work without this

**Implementation**:
1. Locate `_build_error_list()` function at line 218
2. After line 248 (where error dict is created), add enhancement code
3. Extract rich data from `shared[failed_node]`:
   - `status_code`, `response`, `response_headers` for HTTP nodes
   - `error_details`, `result["error"]` for MCP nodes
   - `available_fields` for template errors (list node output keys)
4. Add fields to error dict before return

**Code Location**:
```python
# Around line 248, after error dict creation
error = {
    "source": "runtime",
    "category": category,
    "message": error_info["message"],
    "action": action_result,
    "node_id": error_info["failed_node"],
    "fixable": True,
}

# ADD ENHANCEMENT HERE
failed_node = error_info.get("failed_node")
if failed_node:
    node_output = shared.get(failed_node, {})
    if isinstance(node_output, dict):
        # HTTP node data
        if "status_code" in node_output:
            error["status_code"] = node_output["status_code"]
            error["raw_response"] = node_output.get("response")

        # MCP node data
        if "error_details" in node_output:
            error["mcp_error_details"] = node_output["error_details"]

        # Template errors
        if category == "template_error":
            error["available_fields"] = list(node_output.keys())[:20]

return [error]
```

**Verification**:
- Error dict includes rich data fields
- HTTP errors include raw_response
- MCP errors include error_details
- Template errors include available_fields

### Task 4.2: Display Layer - Show Rich Error Context (45 min)
**File**: `src/pflow/cli/main.py`
**Dependencies**: Requires Task 4.1 complete
**Critical**: Won't show anything without data layer enhancement

**Implementation**:
1. Update `_handle_workflow_error` signature (line ~1034):
   - Add `result: ExecutionResult` parameter
   - Add `no_repair: bool` parameter
2. Update call site (line ~1205):
   - Pass `result=result`
   - Pass `no_repair=no_repair`
3. Enhance display logic for text mode:
   - Show node_id, category, message
   - Display raw_response for API errors (field-level details)
   - Display mcp_error for MCP errors
   - Display available_fields for template errors
   - Show fixable hint if no_repair is True
4. Enhance JSON mode to include structured errors

**Display Pattern**:
```python
if result and result.errors:
    for error in result.errors:
        click.echo(f"❌ Workflow execution failed", err=True)
        click.echo(f"\nError at node '{error.get('node_id')}':", err=True)
        click.echo(f"  Category: {error.get('category')}", err=True)
        click.echo(f"  Message: {error.get('message')}", err=True)

        # Show API response details
        if raw := error.get('raw_response'):
            click.echo("\n  API Response:", err=True)
            if isinstance(raw, dict):
                if errors := raw.get('errors'):
                    for e in errors[:3]:
                        field = e.get('field', 'unknown')
                        msg = e.get('message', e.get('code'))
                        click.echo(f"    - Field '{field}': {msg}", err=True)
```

**Verification**:
- Text mode shows rich error details
- JSON mode includes structured errors
- API errors show field-level information
- Template errors show available fields

---

## Phase 5: Documentation (45 min)

### Task 5.1: Create AGENT_INSTRUCTIONS.md (45 min)
**File**: `docs/AGENT_INSTRUCTIONS.md`
**Dependencies**: All commands implemented
**Parallel**: Can write while testing

**Content Structure**:
1. Quick Start - Complete workflow example
2. Discovery Commands - workflow discover, registry discover, registry describe
3. Building Workflows - Structure, template variables
4. Validation - Static validation with --validate-only
5. Error Handling - Enhanced error output examples
6. Workflow Library - Save and reuse
7. File Organization - Local drafts vs global library
8. Complete Example - End-to-end agent workflow
9. Tips for Agents - Best practices

**Verification**:
- Comprehensive coverage of all new commands
- Clear examples for each command
- Error handling guidance
- Complete end-to-end workflow

---

## Phase 6: Testing (varies per component)

### Test Strategy
Use `test-writer-fixer` subagent for ALL test writing and fixing.

**Deploy subagent AFTER each phase completes**:
- Give subagent the implemented code
- Ask it to write comprehensive tests
- Focus on quality over quantity
- Test real behaviors, not just coverage

### Test Priorities (in order):
1. **Discovery commands** - LLM integration, output formatting
2. **Validation flag** - Static validation layers, no side effects
3. **Save command** - Name validation, file operations
4. **Error enhancement** - Both data and display layers
5. **Integration** - Complete agent workflow

### Testing Approach:
- Mock LLM calls at node level
- Test command invocation and output
- Verify error handling
- Integration tests for complete workflows

---

## Phase 7: Quality Checks (30 min)

### Task 7.1: Run make test
**Command**: `uv run python -m pytest tests/test_cli/`
**Fix Issues**: Use test-writer-fixer subagent

### Task 7.2: Run make check
**Command**: `make check`
**Fix Issues**: Address linting, type errors

### Task 7.3: Manual Testing
**Test each command manually**:
```bash
pflow workflow discover "analyze GitHub PRs"
pflow registry discover "GitHub operations"
pflow registry describe github-get-pr llm
pflow --validate-only test-workflow.json
pflow workflow save draft.json my-workflow "Test"
```

---

## Critical Dependencies

### Must Be Done In Order:
1. Error data layer (Task 4.1) → Error display layer (Task 4.2)

### Can Be Done In Parallel:
- All discovery commands (Tasks 1.1, 1.2, 1.3)
- Validation flag (Task 2.1)
- Workflow save (Task 3.1)

### Blocking Relationships:
- Documentation (Task 5.1) requires all commands implemented
- Testing (Phase 6) requires corresponding implementation complete
- Quality checks (Phase 7) require all tests passing

---

## Subagent Deployment Strategy

### During Implementation (Code Writing):
- I write the code myself following patterns from context gathering
- Deploy subagents in parallel for independent components

### During Testing (Test Writing):
- Deploy `test-writer-fixer` subagent AFTER each component is implemented
- Give small, isolated tasks (one file at a time)
- Provide comprehensive context and requirements

### Example Subagent Task:
```
Task: Write tests for workflow discover command

Context:
- Command in src/pflow/cli/commands/workflow.py:132-208
- Uses WorkflowDiscoveryNode directly
- Returns workflow with metadata or "no match" message

Test Requirements:
- Mock WorkflowDiscoveryNode
- Test successful discovery (action="found_existing")
- Test no match found (action="not_found")
- Test error handling
- Verify output format

Create tests in tests/test_cli/test_workflow_discover.py
```

---

## Risk Mitigation

### Known Risks:
1. **Error enhancement two-layer requirement** - MUST do data layer first
2. **LLM defaults** - Verified nodes have defaults, safe to proceed
3. **Validation parameters** - Using static validation (params=None)

### Mitigations:
1. Implement and test data layer before display layer
2. Trust node defaults (verified in research)
3. Clear documentation about static validation limitations

---

## Success Criteria

### Implementation Complete When:
- ✅ All 6 commands/enhancements implemented
- ✅ Error output shows rich context (two layers)
- ✅ AGENT_INSTRUCTIONS.md created
- ✅ All tests passing (`make test`)
- ✅ All quality checks passing (`make check`)
- ✅ Manual testing successful for each command

### Quality Metrics:
- No regressions in existing tests
- Type checking passes
- Linting passes
- Clear, helpful error messages
- Complete documentation

---

## Timeline Estimate

| Phase | Tasks | Time | Dependencies |
|-------|-------|------|--------------|
| 1. Discovery Commands | 3 commands | 90 min | None (parallel) |
| 2. Validation Flag | 1 flag | 45 min | None (independent) |
| 3. Workflow Save | 1 command | 45 min | None (independent) |
| 4. Error Enhancement | 2 layers | 90 min | Data layer first! |
| 5. Documentation | 1 doc | 45 min | All commands done |
| 6. Testing | Per component | 120 min | Implementation done |
| 7. Quality Checks | 3 checks | 30 min | Tests passing |
| **Total** | | **~7 hours** | |

Note: Original estimate was 4 hours. Adding testing brings it to ~7 hours total.

---

## Current Progress

### Completed:
- ✅ Context gathering (5 parallel subagents)
- ✅ Implementation plan created

### In Progress:
- 🔄 workflow discover command (partially implemented - needs completion)

### Next Steps:
1. Complete workflow discover implementation
2. Implement remaining discovery commands in parallel
3. Implement validation flag
4. Implement workflow save
5. Implement error enhancement (data layer, then display layer)
6. Create documentation
7. Write tests using test-writer-fixer subagent
8. Run quality checks

---

## Notes

- Following epistemic manifesto: verify assumptions, question patterns, ensure robustness
- Using direct node reuse pattern throughout (no extraction)
- Error enhancement is CRITICAL and requires both layers
- Testing strategy uses test-writer-fixer for quality over quantity
- Manual testing will validate end-to-end agent workflow
