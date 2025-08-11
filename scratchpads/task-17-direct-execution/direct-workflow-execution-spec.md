# Direct Workflow Execution Specification

## Overview

This specification defines two critical features for MVP that enable fast, direct execution of workflows without going through the planner. These features are essential for the "Plan Once, Run Forever" philosophy to actually work in practice.

## Motivation

### The Problem
Currently, all non-JSON input goes through the planner, which:
- Takes 2-5 seconds per execution
- Costs ~$0.01 in API fees each time
- Makes development iteration painfully slow
- Defeats the purpose of saving workflows for reuse

### The Solution
Enable direct execution of workflows by:
1. Loading saved workflows by name
2. Parsing parameters from command line
3. Bypassing the planner entirely when possible

### Impact
- **Speed**: 20-50x faster (100ms vs 2-5s)
- **Cost**: Zero API fees for saved workflows
- **Development**: Rapid iteration during testing
- **User Experience**: Instant execution of saved workflows

## Feature 1: Registry Name Resolution

### Description
Allow users to run saved workflows by name with parameters, bypassing the planner.

### Syntax
```bash
# Basic usage
pflow my-analyzer input_file=data.csv

# Multiple parameters
pflow my-analyzer input_file=data.csv output_dir=results/ format=json

# With stdin data
echo "some data" | pflow my-analyzer output_file=result.txt
```

### Implementation Logic
```
1. Parse first argument
2. IF looks like workflow name:
   a. Try to load from WorkflowManager
   b. IF found:
      - Parse remaining args as parameters
      - Execute directly with params
   c. IF not found:
      - Fall through to planner
3. ELSE:
   - Send all args to planner
```

## Feature 2: Direct File Execution with Parameters

### Description
Allow direct execution of workflow JSON files with parameters for debugging and development.

### Syntax
```bash
# Basic usage
pflow --file workflow.json input_file=data.csv

# Multiple parameters
pflow --file /path/to/workflow.json input_file=data.csv output_dir=results/

# With stdin data
echo "some data" | pflow --file workflow.json
```

### Implementation Logic
```
1. Load and parse JSON file
2. IF valid workflow JSON:
   a. Parse remaining args as parameters
   b. Execute directly with params
3. ELSE:
   - Treat as natural language (send to planner)
```

## Design Decisions

### 1. Workflow Name Detection

**Question**: How to determine if first argument is a workflow name vs natural language?

**Options Considered**:
1. **Always try to load first** - Attempt WorkflowManager.load() for everything
2. **Pattern matching** - Check for kebab-case, no spaces, etc.
3. **Explicit prefix** - Require `workflow:my-analyzer` syntax
4. **Check for '=' in remaining args** - If params present, assume workflow name

**Proposed Solution**: Hybrid approach
```python
def is_likely_workflow_name(text: str, remaining_args: tuple[str, ...]) -> bool:
    """Determine if text is likely a workflow name."""
    # If there are parameter-like args following, likely a workflow name
    if remaining_args and any('=' in arg for arg in remaining_args):
        return True

    # If it's a single kebab-case word, likely a workflow name
    if not ' ' in text and '-' in text:
        return True

    # If it's a single word (no spaces), might be a workflow name
    if not ' ' in text and len(text) < 50:
        return True

    return False
```

**Rationale**:
- Fast path for obvious cases (params present)
- Reasonable heuristics for common patterns
- Falls back to planner if wrong (no harm done)

### 2. Parameter Format

**Question**: What format should parameters use?

**Options Considered**:
1. **Simple key=value** - `input_file=data.csv`
2. **CLI flags** - `--input-file data.csv`
3. **JSON values** - `params='{"input_file": "data.csv"}'`
4. **Mixed** - Support multiple formats

**Proposed Solution**: Simple key=value format only
```
input_file=data.csv
output_dir=results/
limit=100
verbose=true
```

**Rationale**:
- Simple and intuitive
- No ambiguity with CLI flags
- Easy to parse
- Covers 99% of use cases

### 3. Type Inference

**Question**: How to handle parameter types?

**Options Considered**:
1. **Everything as strings** - Let nodes handle conversion
2. **Smart inference** - Detect numbers, booleans, etc.
3. **Type hints from workflow** - Use workflow's input definitions
4. **JSON parsing** - Parse values as JSON for complex types

**Proposed Solution**: Smart inference with JSON fallback
```python
def infer_type(value: str) -> Any:
    """Infer type from string value."""
    # Boolean
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'

    # Number
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # JSON (for arrays/objects)
    if value.startswith(('[', '{')):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    # Default to string
    return value
```

**Rationale**:
- Handles common cases automatically
- Supports complex types via JSON
- Falls back safely to strings
- Matches user expectations

### 4. Execution Precedence

**Question**: In what order should we try different execution methods?

**Proposed Execution Flow**:
```
1. IF --file option:
   a. Load file
   b. IF valid JSON workflow:
      - Parse params from remaining args
      - Execute directly
   c. ELSE:
      - Send to planner as natural language

2. ELIF stdin contains JSON workflow:
   a. Parse JSON
   b. Execute directly (no params from args)

3. ELIF args provided:
   a. IF first arg likely workflow name:
      - Try to load from WorkflowManager
      - IF found:
        * Parse remaining args as params
        * Execute directly
      - ELSE:
        * Send all args to planner
   b. ELSE:
      - Send all args to planner

4. ELSE:
   - Error: No input provided
```

### 5. Error Handling

**Missing Required Parameters**:
```python
# When executing directly, if required params missing:
click.echo(f"Error: Workflow '{workflow_name}' requires parameters:", err=True)
for param_name, param_spec in missing_params.items():
    description = param_spec.get('description', 'No description')
    click.echo(f"  - {param_name}: {description}", err=True)
click.echo("\nUsage: pflow {workflow_name} {param_name}=value ...", err=True)
sys.exit(1)
```

**Workflow Not Found**:
```python
# When workflow name not found, fall back to planner silently
# The planner might find a semantic match or generate new workflow
# Don't error immediately - let planner handle it
```

**Invalid Parameter Values**:
```python
# If parameter type validation fails:
click.echo(f"Error: Invalid value for parameter '{param_name}'", err=True)
click.echo(f"  Expected: {expected_type}", err=True)
click.echo(f"  Provided: {provided_value}", err=True)
sys.exit(1)
```

## Implementation Details

### Code Location
- Main logic in `src/pflow/cli/main.py`
- Parameter parsing helper functions in same file
- No new dependencies needed

### Key Functions to Add

```python
def parse_workflow_params(args: tuple[str, ...]) -> dict[str, Any]:
    """Parse key=value parameters from command arguments."""
    params = {}
    for arg in args:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = infer_type(value)
    return params

def try_direct_execution(
    ctx: click.Context,
    workflow_name: str,
    remaining_args: tuple[str, ...],
    stdin_data: Optional[Union[str, StdinData]]
) -> bool:
    """Try to execute workflow directly by name.

    Returns True if executed, False if should fall back to planner.
    """
    try:
        wm = WorkflowManager()
        workflow_ir = wm.load(workflow_name)

        # Parse parameters from remaining args
        execution_params = parse_workflow_params(remaining_args)

        # Execute directly
        execute_json_workflow(
            ctx,
            workflow_ir,
            stdin_data,
            ctx.obj.get("output_key"),
            execution_params
        )
        return True

    except WorkflowNotFoundError:
        # Fall back to planner
        return False
    except Exception as e:
        # Other errors should be reported
        click.echo(f"Error loading workflow '{workflow_name}': {e}", err=True)
        ctx.exit(1)
```

### Integration Points

**Modify main() function**:
1. After input source determination
2. Before sending to planner
3. Add direct execution attempt for args source

**Modify process_file_workflow()**:
1. When JSON is valid workflow
2. Parse params from remaining context args
3. Pass to execute_json_workflow

## Testing Strategy

### Unit Tests
- Parameter parsing with various formats
- Type inference for different value types
- Workflow name detection heuristics

### Integration Tests
- Direct execution with valid workflow name
- Direct execution with --file option
- Fallback to planner when workflow not found
- Parameter validation and error messages

### End-to-End Tests
- Full flow: save workflow → execute by name → verify output
- Complex parameters with JSON values
- Stdin data handling with direct execution

## Migration Path

### Phase 1: Core Implementation
1. Add parameter parsing functions
2. Add workflow name resolution
3. Integrate with existing CLI flow

### Phase 2: Testing
1. Add comprehensive tests
2. Test with real workflows
3. Performance benchmarking

### Phase 3: Documentation
1. Update CLI help text
2. Add examples to README
3. Document parameter format

## Success Metrics

- **Performance**: <200ms for direct execution (vs 2-5s with planner)
- **Reliability**: 100% success rate for valid workflows with params
- **Usability**: Intuitive parameter syntax that "just works"
- **Development Speed**: 10x faster iteration during development

## Open Questions for User

1. **Parameter Format**: Is `key=value` sufficient or do we need to support `--key value` format too?

2. **Type System**: Should we use smart type inference or keep everything as strings?

3. **Error Messages**: Should workflow-not-found silently fall back to planner or show a message?

4. **Performance**: Is 200ms target reasonable or do we need even faster execution?

5. **Complex Values**: Do we need JSON support for array/object parameters or is that over-engineering?

## Decision Log

*To be filled in after user feedback*

- [ ] Parameter format decision: ___
- [ ] Type inference approach: ___
- [ ] Error handling strategy: ___
- [ ] Performance requirements: ___
- [ ] Complex value support: ___