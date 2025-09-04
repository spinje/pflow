# Current Interactive Mode Implementation Analysis

## 1. Interactive Mode Detection (Line 1361 in main.py)

### Current Implementation:
```python
# Handle post-execution based on workflow source
# Only prompt in fully interactive mode (both stdin and stdout are TTY).
# This prevents hanging when output is piped (e.g., to jq), because the
# downstream process waits for EOF which won't occur if we prompt.
if sys.stdin.isatty() and sys.stdout.isatty():
```

### How Interactive Mode is Detected:
- **Dual TTY Check**: Both `sys.stdin.isatty()` AND `sys.stdout.isatty()` must be `True`
- **Location**: Only used for save workflow prompts around line 1361
- **Purpose**: Prevents hanging when output is piped to other commands like `jq`

### What Happens When Running Non-Interactively:
- **Save prompts are completely skipped** - no workflow save offer
- **Rerun command display is skipped** - no helpful commands shown
- **All workflow execution output still goes to stdout** (no control currently)

## 2. Save Workflow Prompt Logic Flow (Lines 486-549)

### Full `_prompt_workflow_save` Implementation:
```python
def _prompt_workflow_save(ir_data: dict[str, Any], metadata: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    """Prompt user to save workflow after execution."""

    # 1. Initial save prompt
    save_response = click.prompt("\nSave this workflow? (y/n)", type=str, default="n").lower()
    if save_response != "y":
        return (False, None)

    # 2. Get workflow name (with AI-suggested default if available)
    workflow_manager = WorkflowManager()
    default_name = metadata.get("suggested_name", "") if metadata else ""

    # 3. Loop until successful save or user cancels
    while True:
        if default_name:
            workflow_name = click.prompt("Workflow name", default=default_name, type=str)
        else:
            workflow_name = click.prompt("Workflow name", type=str)

        # 4. Use AI-generated description automatically
        description = metadata.get("description", "") if metadata else ""

        try:
            # 5. Save with rich metadata
            workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
            click.echo(f"\n✅ Workflow saved as '{workflow_name}'")
            return (True, workflow_name)

        except WorkflowExistsError:
            # 6. Handle name conflicts with retry option
            click.echo(f"\n❌ Error: A workflow named '{workflow_name}' already exists.")
            retry = click.prompt("Try with a different name? (y/n)", type=str, default="n").lower()
            if retry != "y":
                return (False, None)
            # Continue loop to try again

        except WorkflowValidationError as e:
            click.echo(f"\n❌ Error: Invalid workflow name: {e!s}")
            return (False, None)

        except Exception as e:
            click.echo(f"\n❌ Error saving workflow: {e!s}")
            return (False, None)
```

### Logic Flow:
1. **Initial Prompt**: "Save this workflow? (y/n)" [default: n]
2. **If Yes**: Enter name collection loop
3. **Name Prompt**: Use AI-suggested name as default if available
4. **Auto Description**: Use AI-generated description (no prompt)
5. **Save Attempt**: Try to save with rich metadata
6. **Error Handling**:
   - **Name Conflict**: Offer retry with different name
   - **Validation Error**: Exit (don't retry)
   - **Other Errors**: Exit (don't retry)

### Interactive Features in Save Flow:
- **4 different `click.prompt()` calls**:
  1. `"Save this workflow? (y/n)"` - Initial save decision
  2. `"Workflow name"` (with default) - When AI suggested name available
  3. `"Workflow name"` (no default) - When no AI suggestion
  4. `"Try with a different name? (y/n)"` - On name conflict

## 3. Other Interactive Features in Codebase

### Search Results - All Interactive Prompts:
```bash
/src/pflow/cli/main.py:497:    save_response = click.prompt("\nSave this workflow? (y/n)", type=str, default="n").lower()
/src/pflow/cli/main.py:511:            workflow_name = click.prompt("Workflow name", default=default_name, type=str)
/src/pflow/cli/main.py:513:            workflow_name = click.prompt("Workflow name", type=str)
/src/pflow/cli/main.py:540:            retry = click.prompt("Try with a different name? (y/n)", type=str, default="n").lower()
```

### Other TTY Detection:
```python
# In shell_integration.py:64
def detect_stdin() -> bool:
    """Check if stdin is piped (not a TTY)."""
    return not sys.stdin.isatty()
```

### Progress Display Systems:

#### A) PlannerProgress Class (Lines 588-612 in planning/debug.py):
```python
class PlannerProgress:
    """Displays progress indicators in terminal."""

    def on_node_start(self, node_name: str) -> None:
        """Display node start with emoji and name."""
        display_name = self.NODE_ICONS.get(node_name, node_name)
        click.echo(f"{display_name}...", err=True, nl=False)

    def on_node_complete(self, node_name: str, duration: float) -> None:
        """Display node completion with duration."""
        click.echo(f" ✓ {duration:.1f}s", err=True)
```

**Current Usage**: Always displays planner progress to stderr - NO interactive mode check!

#### B) InstrumentedNodeWrapper (Lines 223-277 in runtime/instrumented_wrapper.py):
- **Metrics Collection**: Always records execution metrics
- **LLM Usage Tracking**: Always captures LLM call data
- **Trace Recording**: Always records detailed execution traces
- **NO Progress Callbacks**: Currently no user-visible progress during workflow execution

## 4. Issues with Current Implementation

### A) Inconsistent Interactive Detection:
- **Save prompts**: Check both stdin AND stdout TTY
- **Planner progress**: NO TTY check - always displays
- **Workflow execution**: NO progress display at all

### B) Output Control Problems:
- **Planner progress always goes to stderr** (could contaminate when piped)
- **No unified output controller**
- **No way to suppress progress in non-interactive mode**
- **No progress during workflow execution** (users think it crashed)

### C) Missing Features:
- **No -p/--print flag** for explicit non-interactive mode
- **No progress callbacks** in InstrumentedNodeWrapper
- **No unified is_interactive logic** across components

## 5. How Unified Output Controller Would Work

### Required Changes:

#### A) OutputController Class (as specified in task):
```python
class OutputController:
    def __init__(self, print_flag: bool = False,
                 output_format: str = "text",
                 stdin_tty: bool = None,
                 stdout_tty: bool = None):
        # ... initialization logic

    def is_interactive(self) -> bool:
        """Determine if running in interactive mode."""
        # Precedence: print_flag > JSON mode > TTY detection
        if self.print_flag:
            return False
        if self.output_format == "json":
            return False
        return self.stdin_tty and self.stdout_tty

    def create_progress_callback(self) -> Optional[Callable]:
        """Create progress callback for workflow execution."""
        # Returns callback if interactive, None otherwise
```

#### B) Integration Points:
1. **Save Prompts**: Replace TTY check with `output_controller.is_interactive()`
2. **PlannerProgress**: Check interactive mode before displaying
3. **InstrumentedNodeWrapper**: Add progress callback support
4. **CLI**: Add -p/--print flag and create OutputController

#### C) Progress Flow:
```
CLI creates OutputController →
_prepare_shared_storage adds callback →
InstrumentedNodeWrapper calls callback →
Progress goes to stderr if interactive
```

## 6. Current State Summary

### ✅ What Works:
- Save prompts correctly detect dual TTY and avoid hanging on pipes
- Planner progress displays useful information during planning
- Error handling works correctly in save flow

### ❌ What's Broken:
- Planner progress always displays (ignores non-interactive mode)
- No workflow execution progress (users think it crashed)
- No unified output control system
- Missing -p flag for CI/CD override

### 🎯 What Needs Implementation:
1. **OutputController class** with unified is_interactive logic
2. **-p/--print CLI flag** for explicit non-interactive mode
3. **Progress callbacks** in InstrumentedNodeWrapper
4. **Integration** of OutputController throughout CLI
5. **Conditional progress display** in PlannerProgress class

The current implementation has the right idea (dual TTY check) but it's incomplete and inconsistent across the codebase. The task's OutputController approach would unify all interactive behavior under a single, testable system.
