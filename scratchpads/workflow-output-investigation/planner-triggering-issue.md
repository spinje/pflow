# Investigation: Why Commands Hang with 30+ Second Delays

## Root Cause Analysis

### 1. **The Planner IS Being Triggered (Incorrectly)**

When you provide a valid JSON workflow file with `--file`, the code flow is:
1. `main()` → `get_input_source()` → reads the file content
2. `process_file_workflow()` is called (line 952)
3. It successfully parses the JSON (line 576)
4. **BUT** - If the JSON parsing somehow fails OR if there's an issue with the JSON content that causes a JSONDecodeError, it falls back to the planner (line 585-592)

### 2. **The Planner Makes LLM API Calls**

The planner involves **6 different LLM calls** through various nodes:
- `WorkflowDiscoveryNode` - Makes LLM call to determine if existing workflow matches
- `ComponentBrowsingNode` - Makes LLM call to select relevant components
- `ParameterDiscoveryNode` - Makes LLM call to discover parameters
- `ParameterMappingNode` - Makes LLM call to map parameters
- `WorkflowGeneratorNode` - Makes LLM call to generate workflow
- `MetadataGenerationNode` - Makes LLM call to generate metadata

Each of these uses `llm.get_model("anthropic/claude-sonnet-4-0")` and makes API calls with `model.prompt()`.

### 3. **The 30+ Second Hang is Due to LLM API Timeouts**

The hang is happening because:
- The LLM library is trying to connect to the Anthropic API
- If the API key is not configured or there's a network issue, it will hang waiting for a response
- There's no explicit timeout set in the code
- Each node has `max_retries=2` with a 1-second wait between retries

### 4. **Why Your Valid JSON Might Trigger the Planner**

Looking at your workflow JSON:
```json
{
  "ir_version": "0.1.0",
  "outputs": {
    "content": {
      "description": "Content of the file",
      "type": "string"
    }
  },
  "nodes": [
    {
      "id": "reader",
      "type": "read-file",
      "params": {
        "file_path": "/tmp/test_data.txt"
      }
    }
  ]
}
```

This SHOULD work without triggering the planner. However, the planner might be triggered if:
1. The file has encoding issues causing JSONDecodeError
2. There's whitespace or BOM characters before the JSON
3. The verbose mode shows different behavior

## Code Analysis

### process_file_workflow function (src/pflow/cli/main.py)

```python
def process_file_workflow(ctx: click.Context, raw_input: str, stdin_data: str | StdinData | None = None) -> None:
    """Process file-based workflow, handling JSON and errors."""
    try:
        # Try to parse as JSON
        ir_data = json.loads(raw_input)

        # Parse parameters from remaining workflow arguments if using --file
        execution_params = _get_file_execution_params(ctx)

        execute_json_workflow(ctx, ir_data, stdin_data, ctx.obj.get("output_key"), execution_params, ctx.obj.get("output_format", "text"))

    except json.JSONDecodeError:
        # Not JSON - treat as natural language and send to planner
        if ctx.obj.get("verbose"):
            click.echo("cli: File contains natural language, using planner")

        _execute_with_planner(
            ctx, raw_input, stdin_data, ctx.obj.get("output_key"), ctx.obj.get("verbose"), ctx.obj.get("input_source")
        )
```

## Solutions

### Immediate Workaround
1. **Check if LLM is configured**: Run `llm models list` to see if the Anthropic API is configured
2. **Set the API key if missing**: `llm keys set anthropic`
3. **Use verbose mode** to see what's happening: `pflow --verbose --file /tmp/test_declared_output.json`

### The Code Issue
The problem is in `process_file_workflow()` - when it catches a `json.JSONDecodeError`, it assumes the content is natural language and sends it to the planner. This is incorrect behavior for the `--file` flag with JSON content.

### Fix Needed
The code should:
1. Better distinguish between actual natural language and malformed JSON
2. Add timeouts to LLM API calls
3. Not fall back to the planner for clearly structured JSON that has minor issues
4. Provide better error messages when LLM API is not configured

### Additional Findings

The read-file node itself is NOT the issue - it has minimal retries (3 retries with 0.1s wait = 0.3s max).

## Test Results

When testing with the workflow files:
- The JSON files are valid
- The read-file node works correctly
- The issue appears to be that when ANY error occurs during execution, the system might be falling back to the planner
- The 30+ second delays are consistent with LLM API timeout behavior

## Recommendations

1. **Add explicit timeout to LLM calls** in the planner nodes
2. **Better error messages** when LLM is not configured
3. **Don't fall back to planner** for clearly structured JSON files
4. **Add a flag to disable planner** for testing: `--no-planner`