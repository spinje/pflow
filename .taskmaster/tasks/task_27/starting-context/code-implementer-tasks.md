# Code-Implementer Tasks - Task 27

These are isolated, self-contained functions that can be implemented without deep context of the planner system.

## Task 1: Save Trace to File Utility

### Specification
Create a function that saves a trace dictionary to a JSON file with proper error handling.

### Location
Create this in: `src/pflow/planning/debug_utils.py`

### Implementation

```python
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

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

    Example:
        >>> data = {"execution_id": "123", "status": "success"}
        >>> path = save_trace_to_file(data)
        >>> print(path)
        /home/user/.pflow/debug/pflow-trace-20240111-103000.json
    """
    # Implementation requirements:
    # 1. Use default directory ~/.pflow/debug if not provided
    # 2. Create directory if it doesn't exist (parents=True)
    # 3. Generate filename: pflow-trace-YYYYMMDD-HHMMSS.json
    # 4. Handle large objects with default=str in json.dump
    # 5. If permission error, raise with helpful message
    # 6. Return full path as string
```

### Test Cases to Handle
- Directory doesn't exist → Create it
- Directory not writable → Raise PermissionError with message
- Non-serializable objects in trace_data → Use default=str
- Large trace files → Should still work (no size limit for now)

---

## Task 2: Format Progress Message

### Specification
Create a function that formats progress messages with emojis and timing.

### Location
Add to: `src/pflow/planning/debug_utils.py`

### Implementation

```python
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

    Example:
        >>> format_progress_message("WorkflowDiscoveryNode", 2.134, "complete")
        "🔍 Discovery... ✓ 2.1s"

        >>> format_progress_message("WorkflowGeneratorNode", None, "running")
        "🤖 Generating..."
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

    # Implementation requirements:
    # 1. Look up emoji and display name from mapping
    # 2. If not found, use node_name as display and "⚙️" as emoji
    # 3. Format duration to 1 decimal place (e.g., 2.1s)
    # 4. If status is "running", show "..."
    # 5. If status is "complete", show "✓" with duration
    # 6. If status is "failed", show "✗"
```

### Output Examples
- Running: `"🔍 Discovery..."`
- Complete: `"🔍 Discovery... ✓ 2.1s"`
- Failed: `"🔍 Discovery... ✗"`
- Unknown node: `"⚙️ CustomNode... ✓ 1.5s"`

---

## Task 3: Create LLM Interceptor

### Specification
Create a helper that returns a monkey-patch function for intercepting LLM calls.

### Location
Add to: `src/pflow/planning/debug_utils.py`

### Implementation

```python
from typing import Callable, Any

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

    Example:
        >>> def log_request(prompt, kwargs):
        ...     print(f"Prompt: {prompt[:50]}...")
        >>>
        >>> interceptor = create_llm_interceptor(log_request, log_response, log_error)
        >>>
        >>> # Use it to patch
        >>> import llm
        >>> original = llm.get_model
        >>> llm.get_model = interceptor(llm.get_model)
        >>> # ... use LLM ...
        >>> llm.get_model = original  # restore
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

### Usage Pattern
```python
# Create callbacks
def record_request(prompt, kwargs):
    # Store prompt
    pass

def record_response(response, duration):
    # Store response
    pass

def record_error(error):
    # Store error
    pass

# Create interceptor
wrapper = create_llm_interceptor(record_request, record_response, record_error)

# Apply it
import llm
original = llm.get_model
llm.get_model = wrapper(original)
try:
    # Use LLM
    pass
finally:
    llm.get_model = original  # Always restore
```

---

## Task 4: Format Trace Summary (Bonus - if time)

### Specification
Create a function that generates a human-readable summary from a trace file.

### Location
Add to: `src/pflow/planning/debug_utils.py`

### Implementation

```python
def format_trace_summary(trace_path: str) -> str:
    """
    Generate a summary from a trace JSON file.

    Args:
        trace_path: Path to trace JSON file

    Returns:
        str: Formatted summary for display

    Example:
        >>> summary = format_trace_summary("/path/to/trace.json")
        >>> print(summary)
        Execution ID: 550e8400-e29b-41d4
        Status: timeout
        Duration: 60.0s
        Path: B (Generation)

        LLM Calls (4):
          1. Discovery: 2.1s, 4500→120 tokens
          2. Browsing: 1.8s, 3800→95 tokens
          ...
    """
    # Requirements:
    # 1. Load JSON file
    # 2. Extract key fields: execution_id, status, duration, path
    # 3. Count and summarize LLM calls
    # 4. Format as multi-line string
    # 5. Handle missing fields gracefully
    # 6. If file doesn't exist, return "Trace file not found: {path}"
```

---

## General Requirements

1. **Error Handling**: All functions should handle errors gracefully
2. **Type Hints**: Use proper type hints for all parameters and returns
3. **Docstrings**: Include clear docstrings with examples
4. **No External Dependencies**: Only use standard library + existing project deps
5. **Path Handling**: Use pathlib.Path for all file operations

## Testing Notes

Each function should be independently testable without requiring the full planner system. Create simple unit tests that verify:
- Correct output format
- Error handling
- Edge cases (empty input, missing data, etc.)