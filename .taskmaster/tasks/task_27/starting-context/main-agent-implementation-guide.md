# Main Agent Implementation Guide - Task 27

## Critical Context

You are implementing the core debugging infrastructure for the planner. The planner is a PocketFlow Flow with 9 nodes that creates workflows. We need to wrap these nodes to capture debugging data WITHOUT modifying the nodes themselves.

## Implementation Order (MUST FOLLOW)

1. Create `src/pflow/planning/debug.py` with all core classes
2. Modify `src/pflow/planning/flow.py` to wrap nodes
3. Modify `src/pflow/cli/main.py` to add flags and timeout

## Part 1: Core Debug Infrastructure (`src/pflow/planning/debug.py`)

### Critical Requirements
- The DebugWrapper MUST delegate ALL unknown attributes to the wrapped node
- The wrapper MUST preserve `successors` attribute for Flow compatibility
- The wrapper MUST handle special methods (__copy__, __deepcopy__) to prevent recursion
- The wrapper MUST NOT break the node lifecycle (prep, exec, post)
- The wrapper MUST observe only, never recreate Flow logic

### DebugWrapper Class (MOST CRITICAL)

```python
import time
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional
import click

class DebugWrapper:
    """Wraps PocketFlow nodes to capture debugging data"""

    def __init__(self, node, trace_collector: 'TraceCollector', progress: 'PlannerProgress'):
        self._wrapped = node
        self.trace = trace_collector
        self.progress = progress
        # CRITICAL: Copy Flow-required attributes
        self.successors = node.successors
        self.params = getattr(node, 'params', {})

    def __getattr__(self, name):
        """CRITICAL: Delegate ALL unknown attributes to wrapped node"""
        # Handle special methods to prevent recursion
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(self._wrapped, name)

    def __copy__(self):
        """CRITICAL: Flow uses copy.copy() on nodes (lines 99, 107 of pocketflow/__init__.py)
        This MUST be implemented or Flow will break when it copies nodes!
        """
        import copy
        # Create new wrapper with copied inner node, but SAME trace/progress (shared)
        return DebugWrapper(copy.copy(self._wrapped), self.trace, self.progress)

    def __deepcopy__(self, memo):
        """Prevent recursion when deep copying"""
        import copy
        return DebugWrapper(copy.deepcopy(self._wrapped, memo), self.trace, self.progress)

    def set_params(self, params):
        """Flow calls this to set parameters"""
        self.params = params
        if hasattr(self._wrapped, 'set_params'):
            self._wrapped.set_params(params)

    def _run(self, shared):
        """Main execution - Flow calls this"""
        node_name = getattr(self._wrapped, 'name', self._wrapped.__class__.__name__)
        self.progress.on_node_start(node_name)
        start_time = time.time()

        # Store trace collector in shared for access
        shared['_trace_collector'] = self.trace

        try:
            result = self._wrapped._run(shared)
            duration = time.time() - start_time
            self.progress.on_node_complete(node_name, duration)
            self.trace.record_node_execution(node_name, duration, "success")
            return result
        except Exception as e:
            duration = time.time() - start_time
            self.trace.record_node_execution(node_name, duration, "failed", str(e))
            raise

    def prep(self, shared):
        """Wrap prep phase"""
        start = time.time()
        result = self._wrapped.prep(shared)
        self.trace.record_phase(self._wrapped.__class__.__name__, "prep", time.time() - start)
        return result

    def exec(self, prep_res):
        """Wrap exec phase with LLM interception"""
        start = time.time()
        node_name = self._wrapped.__class__.__name__

        # Set up LLM interception if this node uses LLM
        import llm
        original_get_model = None
        if 'model_name' in prep_res:  # Node uses LLM
            original_get_model = llm.get_model

            def intercept_get_model(*args, **kwargs):
                model = original_get_model(*args, **kwargs)
                original_prompt = model.prompt

                def intercept_prompt(prompt_text, **prompt_kwargs):
                    prompt_start = time.time()
                    # Record the prompt BEFORE calling
                    self.trace.record_llm_request(node_name, prompt_text, prompt_kwargs)

                    try:
                        response = original_prompt(prompt_text, **prompt_kwargs)
                        # Record the response AFTER calling
                        self.trace.record_llm_response(
                            node_name,
                            response,
                            time.time() - prompt_start
                        )
                        return response
                    except Exception as e:
                        self.trace.record_llm_error(node_name, str(e))
                        raise

                model.prompt = intercept_prompt
                return model

            llm.get_model = intercept_get_model

        try:
            result = self._wrapped.exec(prep_res)
        finally:
            if original_get_model:
                llm.get_model = original_get_model

        self.trace.record_phase(node_name, "exec", time.time() - start)
        return result

    def post(self, shared, prep_res, exec_res):
        """Wrap post phase"""
        start = time.time()
        result = self._wrapped.post(shared, prep_res, exec_res)
        self.trace.record_phase(
            self._wrapped.__class__.__name__,
            "post",
            time.time() - start,
            {"action": result}
        )
        return result
```

### TraceCollector Class

```python
class TraceCollector:
    """Collects execution trace data"""

    def __init__(self, user_input: str):
        self.execution_id = str(uuid.uuid4())
        self.start_time = datetime.utcnow()
        self.user_input = user_input
        self.events = []
        self.llm_calls = []
        self.node_executions = []
        self.final_status = "running"
        self.path_taken = None  # Will be "A" or "B"

    def record_node_execution(self, node: str, duration: float, status: str, error: str = None):
        self.node_executions.append({
            "node": node,
            "duration_ms": int(duration * 1000),
            "status": status,
            "error": error
        })

        # Detect path based on nodes executed
        if node == "ComponentBrowsingNode":
            self.path_taken = "B"
        elif node == "ParameterMappingNode" and self.path_taken is None:
            self.path_taken = "A"

    def record_phase(self, node: str, phase: str, duration: float, extra: dict = None):
        self.events.append({
            "timestamp": datetime.utcnow().isoformat(),
            "node": node,
            "phase": phase,
            "duration_ms": int(duration * 1000),
            "extra": extra
        })

    def record_llm_request(self, node: str, prompt: str, kwargs: dict):
        # Store the pending request
        self.current_llm_call = {
            "node": node,
            "timestamp": datetime.utcnow().isoformat(),
            "model": kwargs.get("model", "unknown"),
            "prompt": prompt,
            "prompt_kwargs": {k: v for k, v in kwargs.items() if k != "schema"}
        }

    def record_llm_response(self, node: str, response, duration: float):
        if hasattr(self, 'current_llm_call'):
            self.current_llm_call["duration_ms"] = int(duration * 1000)

            # Extract response data
            if hasattr(response, 'json'):
                try:
                    response_data = response.json()
                    self.current_llm_call["response"] = response_data
                except:
                    self.current_llm_call["response"] = str(response)
            else:
                self.current_llm_call["response"] = str(response)

            # Try to get token counts if available
            if hasattr(response, 'usage'):
                self.current_llm_call["tokens"] = {
                    "input": response.usage.get("input_tokens", 0),
                    "output": response.usage.get("output_tokens", 0)
                }

            self.llm_calls.append(self.current_llm_call)
            delattr(self, 'current_llm_call')

    def record_llm_error(self, node: str, error: str):
        if hasattr(self, 'current_llm_call'):
            self.current_llm_call["error"] = error
            self.llm_calls.append(self.current_llm_call)
            delattr(self, 'current_llm_call')

    def set_final_status(self, status: str, shared_store: dict = None, error: dict = None):
        self.final_status = status
        if shared_store:
            # Only save important keys, not internal ones
            self.final_shared_store = {
                k: v for k, v in shared_store.items()
                if not k.startswith('_') and k not in ['workflow_manager']
            }
        if error:
            self.error_info = error

    def save_to_file(self) -> str:
        """Save trace to JSON file"""
        # Create directory
        trace_dir = Path.home() / ".pflow" / "debug"
        trace_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"pflow-trace-{timestamp}.json"
        filepath = trace_dir / filename

        # Prepare trace data
        trace_data = {
            "execution_id": self.execution_id,
            "timestamp": self.start_time.isoformat(),
            "user_input": self.user_input,
            "status": self.final_status,
            "duration_ms": int((datetime.utcnow() - self.start_time).total_seconds() * 1000),
            "path_taken": self.path_taken,
            "llm_calls": self.llm_calls,
            "node_execution": self.node_executions,
            "events": self.events
        }

        if hasattr(self, 'final_shared_store'):
            trace_data["final_shared_store"] = self.final_shared_store
        if hasattr(self, 'error_info'):
            trace_data["error"] = self.error_info

        # Write file
        with open(filepath, 'w') as f:
            json.dump(trace_data, f, indent=2, default=str)

        return str(filepath)
```

### PlannerProgress Class

```python
class PlannerProgress:
    """Displays progress in terminal"""

    # Node name to emoji mapping
    NODE_ICONS = {
        "WorkflowDiscoveryNode": "🔍 Discovery",
        "ComponentBrowsingNode": "📦 Browsing",
        "ParameterDiscoveryNode": "🔎 Parameters Discovery",
        "ParameterMappingNode": "📝 Parameters",
        "ParameterPreparationNode": "📋 Preparation",
        "WorkflowGeneratorNode": "🤖 Generating",
        "ValidatorNode": "✅ Validation",
        "MetadataGenerationNode": "💾 Metadata",
        "ResultPreparationNode": "📤 Finalizing"
    }

    def on_node_start(self, node_name: str):
        display_name = self.NODE_ICONS.get(node_name, node_name)
        click.echo(f"{display_name}...", err=True, nl=False)

    def on_node_complete(self, node_name: str, duration: float):
        click.echo(f" ✓ {duration:.1f}s", err=True)
```

## Part 2: Utility Functions (`src/pflow/planning/debug_utils.py`)

Create this file with helper functions for debugging support:

```python
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Callable

def save_trace_to_file(trace_data: Dict[str, Any], directory: Path = None) -> str:
    """
    Save trace data to a JSON file with timestamp.

    Args:
        trace_data: Dictionary containing trace information
        directory: Directory to save file (default: ~/.pflow/debug)

    Returns:
        str: Full path to saved file

    Raises:
        PermissionError: If directory is not writable
    """
    if directory is None:
        directory = Path.home() / ".pflow" / "debug"

    # Create directory if it doesn't exist
    directory.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"pflow-trace-{timestamp}.json"
    filepath = directory / filename

    # Save with proper error handling
    try:
        with open(filepath, 'w') as f:
            json.dump(trace_data, f, indent=2, default=str)
    except PermissionError as e:
        raise PermissionError(f"Cannot write to {directory}: {e}")

    return str(filepath)

def format_progress_message(
    node_name: str,
    duration: float = None,
    status: str = "running"
) -> str:
    """
    Format a progress message with emoji and optional duration.

    Args:
        node_name: Name of the node (e.g., "WorkflowDiscoveryNode")
        duration: Execution time in seconds (None if still running)
        status: One of "running", "complete", "failed"

    Returns:
        str: Formatted message like "🔍 Discovery... ✓ 2.1s"
    """
    # Node to display name mapping
    NODE_DISPLAY = {
        "WorkflowDiscoveryNode": ("🔍", "Discovery"),
        "ComponentBrowsingNode": ("📦", "Browsing"),
        "ParameterDiscoveryNode": ("🔎", "Parameters Discovery"),
        "ParameterMappingNode": ("📝", "Parameters"),
        "ParameterPreparationNode": ("📋", "Preparation"),
        "WorkflowGeneratorNode": ("🤖", "Generating"),
        "ValidatorNode": ("✅", "Validation"),
        "MetadataGenerationNode": ("💾", "Metadata"),
        "ResultPreparationNode": ("📤", "Finalizing")
    }

    # Get emoji and display name
    emoji, display = NODE_DISPLAY.get(node_name, ("⚙️", node_name))

    # Format based on status
    if status == "running":
        return f"{emoji} {display}..."
    elif status == "complete" and duration is not None:
        return f"{emoji} {display}... ✓ {duration:.1f}s"
    elif status == "failed":
        return f"{emoji} {display}... ✗"
    else:
        return f"{emoji} {display}"

def create_llm_interceptor(
    on_request: Callable[[str, dict], None],
    on_response: Callable[[Any, float], None],
    on_error: Callable[[str], None]
) -> Callable:
    """
    Create a function that intercepts llm.get_model() calls.

    Args:
        on_request: Called with (prompt, kwargs) before LLM call
        on_response: Called with (response, duration) after LLM call
        on_error: Called with error message if LLM fails

    Returns:
        A function that replaces llm.get_model() and intercepts model.prompt()
    """
    def create_wrapper(original_get_model):
        """Returns a wrapper for llm.get_model"""

        def wrapped_get_model(*args, **kwargs):
            # Get the model instance
            model = original_get_model(*args, **kwargs)

            # Save original prompt method
            original_prompt = model.prompt

            # Create intercepted prompt method
            def intercepted_prompt(prompt_text, **prompt_kwargs):
                import time
                start_time = time.time()

                # Call on_request callback
                on_request(prompt_text, prompt_kwargs)

                try:
                    # Call original prompt
                    response = original_prompt(prompt_text, **prompt_kwargs)

                    # Call on_response callback
                    duration = time.time() - start_time
                    on_response(response, duration)

                    return response

                except Exception as e:
                    # Call on_error callback
                    on_error(str(e))
                    raise

            # Replace prompt method
            model.prompt = intercepted_prompt
            return model

        return wrapped_get_model

    return create_wrapper
```

## Part 3: Flow Integration (`src/pflow/planning/flow.py`)

### Add a new function to create debug-wrapped flow

Add this function to the flow.py file:

```python
def create_planner_flow_with_debug(user_input: str, trace_enabled: bool = False):
    """Create planner flow with debugging enabled"""
    from pflow.planning.debug import DebugWrapper, TraceCollector, PlannerProgress

    # Create debugging infrastructure
    trace = TraceCollector(user_input)
    progress = PlannerProgress()

    # Create all nodes
    discovery_node = WorkflowDiscoveryNode()
    component_browsing = ComponentBrowsingNode()
    parameter_discovery = ParameterDiscoveryNode()
    parameter_mapping = ParameterMappingNode()
    parameter_preparation = ParameterPreparationNode()
    workflow_generator = WorkflowGeneratorNode()
    validator = ValidatorNode()
    metadata_generation = MetadataGenerationNode()
    result_preparation = ResultPreparationNode()

    # Wrap all nodes
    discovery_node = DebugWrapper(discovery_node, trace, progress)
    component_browsing = DebugWrapper(component_browsing, trace, progress)
    parameter_discovery = DebugWrapper(parameter_discovery, trace, progress)
    parameter_mapping = DebugWrapper(parameter_mapping, trace, progress)
    parameter_preparation = DebugWrapper(parameter_preparation, trace, progress)
    workflow_generator = DebugWrapper(workflow_generator, trace, progress)
    validator = DebugWrapper(validator, trace, progress)
    metadata_generation = DebugWrapper(metadata_generation, trace, progress)
    result_preparation = DebugWrapper(result_preparation, trace, progress)

    # Create flow with existing wiring (copy the existing flow creation)
    flow = Flow(start=discovery_node)

    # [Copy all the existing node connections here]
    # discovery_node - "found_existing" >> parameter_mapping
    # ... etc

    return flow, trace
```

## Part 4: CLI Integration (`src/pflow/cli/main.py`)

### Add CLI flags

Find the main click command and add:

```python
@click.option(
    '--trace',
    is_flag=True,
    help='Save debug trace even on success'
)
@click.option(
    '--planner-timeout',
    type=int,
    default=60,
    help='Timeout for planner execution (seconds)'
)
```

### Modify planner execution

Find where the planner is executed and modify:

```python
import threading
from pflow.planning.flow import create_planner_flow_with_debug

def execute_with_planner_debug(user_input: str, timeout: int = 60, trace: bool = False):
    """Execute planner with debugging

    IMPORTANT: Threading in Python cannot be interrupted. Timeout detection
    happens AFTER the planner completes, not during execution.
    """
    # Create flow with debugging
    flow, trace_collector = create_planner_flow_with_debug(user_input, trace)

    # Create shared store
    shared = {
        "user_input": user_input,
        "workflow_manager": WorkflowManager(),
        "_trace_enabled": trace
    }

    # Set up timeout detection (can only detect after completion)
    timed_out = threading.Event()
    timer = threading.Timer(timeout, lambda: timed_out.set())
    timer.start()

    try:
        # Run planner (BLOCKING - cannot be interrupted)
        flow.run(shared)

        # Check timeout AFTER completion
        if timed_out.is_set():
            click.echo(f"\n⏰ Operation exceeded {timeout}s timeout", err=True)
            trace_collector.set_final_status("timeout", shared)
            trace_file = trace_collector.save_to_file()
            click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
            return {"success": False, "error": "timeout"}

        # Get result
        planner_output = shared.get("planner_output", {})

        # Set final status
        if planner_output.get("success"):
            trace_collector.set_final_status("success", shared)
        else:
            trace_collector.set_final_status("failed", shared, planner_output.get("error"))

        # Save trace if needed
        if trace or not planner_output.get("success"):
            trace_file = trace_collector.save_to_file()
            if not planner_output.get("success"):
                click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
            elif trace:
                click.echo(f"📝 Trace saved: {trace_file}")

        return planner_output

    except Exception as e:
        trace_collector.set_final_status("error", shared, {"message": str(e)})
        trace_file = trace_collector.save_to_file()
        click.echo(f"❌ Planner failed: {e}", err=True)
        click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
        raise

    finally:
        timer.cancel()
```

## Critical Integration Points

1. **Node Wrapping**: The DebugWrapper MUST preserve all node attributes that Flow expects
2. **Special Methods**: MUST implement __copy__ and __deepcopy__ to prevent recursion
3. **LLM Interception**: Intercept at prompt method level, not module level
4. **Shared Store**: Don't save internal keys (starting with _) or large objects in trace
5. **Progress Output**: Use click.echo with err=True to avoid interfering with stdout
6. **Timeout**: Can only detect after completion, cannot interrupt (Python limitation)
7. **Logging**: Don't use logging.basicConfig() - it affects all libraries globally

## Implementation Checklist

### Pre-Implementation
- [ ] Understand Flow's _run() lifecycle
- [ ] Review existing planner nodes
- [ ] Check current test infrastructure status

### During Implementation
- [ ] Create DebugWrapper with special method handling
- [ ] Test delegation works for all attributes
- [ ] Verify copy operations don't cause recursion
- [ ] Implement LLM interception at prompt level
- [ ] Add progress indicators with clean output
- [ ] Create utility functions in debug_utils.py
- [ ] Integrate with flow.py
- [ ] Add CLI flags and timeout handling

### Testing
- [ ] Wrapped nodes still execute correctly
- [ ] Progress shows for each node
- [ ] LLM calls are captured in trace
- [ ] Timeout is detected after completion
- [ ] Trace files are saved to ~/.pflow/debug/
- [ ] --trace flag works
- [ ] Failures auto-save traces
- [ ] No recursion errors with copy operations

## Common Pitfalls to Avoid

1. **DO NOT** modify the original nodes - wrap only
2. **DO NOT** forget special method handling in __getattr__
3. **DO NOT** forget to implement __copy__ and __deepcopy__
4. **DO NOT** intercept at module level - use prompt method level
5. **DO NOT** forget to restore LLM methods in finally block
6. **DO NOT** save sensitive data in traces
7. **DO NOT** try to interrupt threads (Python limitation)
8. **DO NOT** use logging.basicConfig() - it's global state
9. **DO NOT** recreate Flow logic - observe only

## Known Python Gotchas

1. **Threading**: Cannot interrupt running threads - timeout is detection only
2. **__getattr__**: Can cause recursion with copy.copy() if not handled
3. **Logging**: Global state affects all libraries when using basicConfig
4. **Wrapper Pattern**: Must preserve successors and params attributes for Flow