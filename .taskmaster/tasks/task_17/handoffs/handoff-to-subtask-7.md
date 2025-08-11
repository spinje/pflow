# Handoff to Subtask 7: Integration & Polish

## 🚨 Critical Context: Validation Redesign Just Landed

We just fixed a fundamental design flaw. The old flow validated templates BEFORE extracting parameters, causing all workflows with required inputs to fail. The new flow extracts parameters FIRST, then validates with actual values.

**What changed:**
- **Old**: Generate → Validate (with {}) → Metadata → ParameterMapping
- **New**: Generate → ParameterMapping → Validate (with params) → Metadata

**CRITICAL**: The `execution_params` from planner MUST be passed to `execute_json_workflow` for template resolution. Without this, workflows with template variables ($input_file, etc.) will fail at runtime.

**New action string you must know about:**
- ParameterMappingNode now returns `"params_complete_validate"` for Path B (generated workflows)
- This is different from `"params_complete"` for Path A (found workflows)
- This routing happens in `nodes.py:824-835`

## 🎯 What's Actually Built vs What Needs Integration

**FULLY BUILT AND TESTED:**
- `create_planner_flow()` in `src/pflow/planning/flow.py` - ready to import
- All 9 nodes wired and working
- 69 integration tests passing
- Validation with extracted parameters working

**NOT BUILT:**
- CLI integration - the planner is never called
- The TODO is at `src/pflow/cli/main.py:517-523`
- Natural language input currently just gets collected and displayed

## 💡 Key Insight: When Missing Parameters Actually Happen

**Path B (Generation)**: Missing params are RARE
- User says "analyze data.csv" → generator creates `$input_file` → extractor finds "data.csv"
- Same input used for generation AND extraction = params usually found

**Path A (Reuse)**: Missing params are COMMON
- User says "run the analyzer" → found workflow needs `$input_file` → not in user input
- This is where "Missing required parameters" message matters

**Implication for you**: Focus interactive parameter collection on Path A scenarios

## 🔧 Integration Points You'll Touch

### CLI Entry Point
`src/pflow/cli/main.py:517-523` - Replace TODO with:
```python
from pflow.planning import create_planner_flow
from pflow.core.workflow_manager import WorkflowManager

# Create planner flow
planner_flow = create_planner_flow()
shared = {
    "user_input": natural_language_input,
    "workflow_manager": WorkflowManager(),  # Uses default ~/.pflow/workflows
    "stdin_data": stdin_data if stdin_data else None,
}
planner_flow.run(shared)

# Check result
planner_output = shared.get("planner_output", {})
if planner_output.get("success"):
    # Execute the workflow WITH execution_params for template resolution
    execute_json_workflow(
        ctx,
        planner_output["workflow_ir"],
        stdin_data,
        output_key,
        planner_output.get("execution_params")  # CRITICAL: Pass params for templates!
    )
else:
    click.echo(f"Planning failed: {planner_output.get('error')}", err=True)
```

### Result Handling
The planner sets `shared["planner_output"]` with this structure:
```python
{
    "success": bool,
    "workflow_ir": dict or None,        # The actual workflow to execute
    "execution_params": dict or None,   # Parameters for execution
    "missing_params": list or None,     # What's missing (for future prompting)
    "error": str or None,               # Human-readable error
    "workflow_metadata": dict or None   # For saving the workflow
}
```

## ⚠️ Gotchas and Edge Cases

### 1. WorkflowManager in Shared Store
The planner expects `shared["workflow_manager"]`. If not provided, nodes fall back to singleton. For testing, you can pass a test WorkflowManager for isolation.

### 2. Template Variables Now Work
Before our fix, generated workflows couldn't have required inputs. Now they can! Test with workflows that have `$input_file`, `$output_file`, etc.

### 3. Retry Mechanism Works
The validator will retry generation up to 3 times for ACTUAL generation errors (not missing params). You don't need triple mocks anymore.

### 4. Path Detection in ParameterMappingNode
The node detects which path it's on by checking `shared.get("generated_workflow")`. This determines routing:
- Path B (has generated_workflow) → `"params_complete_validate"` → Validator
- Path A (no generated_workflow) → `"params_complete"` → ParameterPreparation

## 📊 Test Infrastructure Available

**Integration tests** in `tests/test_planning/integration/`:
- All updated for new flow order
- No more triple generation mocks
- Realistic workflows with required inputs

**Key test pattern for CLI integration:**
```python
def test_cli_natural_language():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test WorkflowManager
        test_manager = WorkflowManager(tmpdir)

        # Mock to inject test manager
        with patch("pflow.core.workflow_manager.WorkflowManager") as mock_wm:
            mock_wm.return_value = test_manager

            result = runner.invoke(cli, ["analyze data.csv"])
            assert result.exit_code == 0
```

## 🔗 Critical Files and Locations

**Core Implementation:**
- `src/pflow/planning/flow.py` - The orchestration (updated for validation fix)
- `src/pflow/planning/nodes.py:796-835` - ParameterMappingNode routing logic
- `src/pflow/planning/nodes.py:1240-1253` - ValidatorNode using extracted_params

**Documentation:**
- `/Users/andfal/projects/pflow/scratchpads/task-17-validation-fix/validation-redesign-implementation-log.md` - Full details of what we changed
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/implementation/progress-log.md:1558-1606` - Progress log entry

**Tests:**
- `tests/test_planning/integration/test_planner_integration.py` - Full flow tests
- `tests/test_planning/integration/test_flow_structure.py` - Wiring verification

## 🎭 What Success Looks Like

When you're done, a user should be able to:
```bash
$ pflow "analyze sales_data.csv and generate a summary report"
Planning workflow...
Executing generated workflow...
[workflow executes]
Save this workflow? (y/n)
```

If parameters are missing (more likely in Path A):
```bash
$ pflow "run the analyzer"
Planning failed: Missing required parameters: input_file, output_file
```

## 🚫 What NOT to Worry About

1. **Interactive parameter collection** - Nice to have, not critical. The error message is enough for MVP.
2. **Validation bugs** - We fixed them. Templates validate with extracted params now.
3. **Test workarounds** - All removed. Tests use realistic workflows.

## 💭 Final Insight

The planner is a complete, working meta-workflow. It just needs to be called. The validation redesign ensures it will work with real workflows that have parameters. Focus on the integration - the orchestration is solid.

Remember: Path B (generation) rarely has missing params because the same user input is used for both generation and extraction. Path A (reuse) is where missing params are common and where future interactive collection would help most.