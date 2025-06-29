# Task 22: Named Workflow Execution - PocketFlow Implementation Analysis

## Why Named Workflow Execution Needs PocketFlow

Named workflow execution is the core user-facing feature that delivers the "Plan Once, Run Forever" value. It involves multiple I/O operations, validation steps, and parameter processing - a perfect fit for PocketFlow.

### The Execution Flow

```
User Command: pflow fix-issue --issue=1234
                    │
                    v
            Parse Command Name
                    │
                    v
            Load Workflow File
                    │
            ┌───────┴────────┐
            │                │
            v                v
        File Found      File Not Found
            │                │
            v                v
     Load JSON IR      Suggest Similar
            │                │
            v                v
    Validate Schema    Show Available
            │
            v
     Check Lockfile
            │
    ┌───────┴────────┐
    │                │
    v                v
  Valid          Outdated
    │                │
    v                v
Apply Parameters  Warn User
    │
    v
Validate Params
    │
    ├─────────────┐
    │             │
    v             v
All Present   Missing Required
    │             │
    v             v
Execute Flow  Prompt for Values
    │
    v
Return Result
```

### Complex Requirements

1. **File Operations** - Load workflow and lockfile from disk
2. **Validation Chain** - Schema → Lockfile → Parameters
3. **Error Recovery** - Missing files, outdated lockfiles, missing params
4. **User Interaction** - Prompting for missing values
5. **Parameter Resolution** - Template variable substitution

### PocketFlow Implementation

#### 1. Command Resolution Flow

```python
class ResolveCommandNode(Node):
    def __init__(self, storage):
        super().__init__()
        self.storage = storage

    def exec(self, shared):
        command_name = shared["command_name"]
        params = shared["cli_params"]

        # Check if workflow exists
        workflow_path = self.storage.get_path(command_name)

        if workflow_path.exists():
            shared["workflow_path"] = workflow_path
            shared["lockfile_path"] = workflow_path.with_suffix('.lock')
            return "load_workflow"
        else:
            # Find similar workflows
            similar = self.storage.find_similar(command_name)
            shared["similar_workflows"] = similar
            return "not_found"

class SuggestSimilarNode(Node):
    def exec(self, shared):
        similar = shared["similar_workflows"]

        if similar:
            print(f"Workflow '{shared['command_name']}' not found.")
            print("\nDid you mean:")
            for name, score in similar[:5]:
                print(f"  - {name}")
            return "prompt_retry"
        else:
            print("No workflow found. Available workflows:")
            for name in self.storage.list():
                print(f"  - {name}")
            return "exit"
```

#### 2. Loading and Validation Flow

```python
class LoadWorkflowNode(Node):
    def __init__(self):
        super().__init__(max_retries=3)  # File I/O can be flaky

    def exec(self, shared):
        workflow_path = shared["workflow_path"]

        try:
            with open(workflow_path) as f:
                workflow = json.load(f)

            shared["workflow"] = workflow
            shared["workflow_metadata"] = workflow.get("metadata", {})
            return "validate_schema"

        except json.JSONDecodeError as e:
            shared["load_error"] = f"Invalid JSON in workflow: {e}"
            return "corrupted"
        except IOError as e:
            shared["load_error"] = f"Failed to read workflow: {e}"
            return "io_error"

    def exec_fallback(self, shared, exc):
        # Try backup location
        backup_path = shared["workflow_path"].with_suffix('.backup')
        if backup_path.exists():
            shared["workflow_path"] = backup_path
            return "retry_with_backup"
        return "fatal_error"

class ValidateSchemaNode(Node):
    def __init__(self, validator):
        super().__init__()
        self.validator = validator

    def exec(self, shared):
        workflow = shared["workflow"]

        result = self.validator.validate(workflow)

        if result.is_valid:
            return "check_lockfile"
        else:
            shared["schema_errors"] = result.errors
            return "invalid_schema"

class CheckLockfileNode(Node):
    def __init__(self):
        super().__init__(max_retries=2)

    def exec(self, shared):
        lockfile_path = shared["lockfile_path"]

        if not lockfile_path.exists():
            # No lockfile = first run
            return "apply_parameters"

        try:
            with open(lockfile_path) as f:
                lockfile = json.load(f)

            # Verify versions match
            workflow_hash = self._compute_hash(shared["workflow"])

            if lockfile["workflow_hash"] == workflow_hash:
                shared["lockfile"] = lockfile
                return "apply_parameters"
            else:
                shared["lockfile_mismatch"] = True
                return "outdated_lockfile"

        except Exception as e:
            # Corrupted lockfile shouldn't block execution
            shared["lockfile_warning"] = str(e)
            return "apply_parameters"
```

#### 3. Parameter Application Flow

```python
class ApplyParametersNode(Node):
    def exec(self, shared):
        workflow = shared["workflow"]
        cli_params = shared["cli_params"]

        # Find all template variables in workflow
        templates = self._find_templates(workflow)
        shared["required_params"] = templates

        # Apply CLI parameters
        resolved = {}
        missing = []

        for param in templates:
            if param in cli_params:
                resolved[param] = cli_params[param]
            elif param in os.environ:
                # Fallback to environment
                resolved[param] = os.environ[param]
            else:
                missing.append(param)

        shared["resolved_params"] = resolved
        shared["missing_params"] = missing

        if missing:
            return "prompt_missing"
        else:
            return "resolve_templates"

class PromptMissingParamsNode(Node):
    def exec(self, shared):
        missing = shared["missing_params"]
        resolved = shared["resolved_params"]

        print("\nMissing required parameters:")

        for param in missing:
            # Show context
            desc = self._get_param_description(param, shared["workflow"])
            if desc:
                print(f"\n{param}: {desc}")

            value = input(f"Enter value for '{param}': ")

            if not value:
                return "abort"

            resolved[param] = value

        shared["resolved_params"] = resolved
        return "resolve_templates"

class ResolveTemplatesNode(Node):
    def exec(self, shared):
        workflow = shared["workflow"]
        params = shared["resolved_params"]

        # Deep copy to avoid modifying original
        resolved_workflow = copy.deepcopy(workflow)

        # Replace all template variables
        def replace_templates(obj):
            if isinstance(obj, str):
                for key, value in params.items():
                    obj = obj.replace(f"${key}", value)
                    obj = obj.replace(f"${{{key}}}", value)
                return obj
            elif isinstance(obj, dict):
                return {k: replace_templates(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_templates(item) for item in obj]
            else:
                return obj

        resolved_workflow = replace_templates(resolved_workflow)
        shared["resolved_workflow"] = resolved_workflow

        return "execute"
```

#### 4. Execution and Error Handling

```python
class ExecuteWorkflowNode(Node):
    def __init__(self, compiler, tracer):
        super().__init__()
        self.compiler = compiler
        self.tracer = tracer

    def exec(self, shared):
        workflow = shared["resolved_workflow"]

        try:
            # Compile IR to Flow
            flow = self.compiler.compile(workflow)

            # Initialize shared store
            initial_store = {
                "workflow_name": shared["command_name"],
                "execution_id": str(uuid.uuid4()),
                "start_time": time.time()
            }

            # Add any stdin if piped
            if shared.get("stdin"):
                initial_store["stdin"] = shared["stdin"]

            # Execute with tracing
            if shared.get("trace_enabled"):
                result = self.tracer.execute(flow, initial_store)
            else:
                result = flow.run(initial_store)

            shared["execution_result"] = result
            shared["execution_time"] = time.time() - initial_store["start_time"]

            return "success"

        except CompilationError as e:
            shared["compilation_error"] = str(e)
            return "compilation_failed"
        except ExecutionError as e:
            shared["execution_error"] = str(e)
            shared["failed_node"] = e.node_id
            return "execution_failed"

class HandleExecutionErrorNode(Node):
    def exec(self, shared):
        error = shared.get("execution_error", "Unknown error")
        failed_node = shared.get("failed_node", "Unknown")

        print(f"\nExecution failed at node '{failed_node}': {error}")

        # Offer recovery options
        print("\nOptions:")
        print("1. Retry execution")
        print("2. Edit workflow and retry")
        print("3. Save error report")
        print("4. Exit")

        choice = input("Your choice (1-4): ")

        return {
            "1": "retry",
            "2": "edit_workflow",
            "3": "save_report",
            "4": "exit"
        }.get(choice, "exit")
```

### Building the Complete Flow

```python
def create_execution_flow(storage, validator, compiler, tracer):
    flow = Flow()

    # Command resolution
    resolve = ResolveCommandNode(storage)
    suggest = SuggestSimilarNode(storage)

    # Loading and validation
    load = LoadWorkflowNode()
    validate = ValidateSchemaNode(validator)
    check_lock = CheckLockfileNode()

    # Parameter handling
    apply_params = ApplyParametersNode()
    prompt_missing = PromptMissingParamsNode()
    resolve_templates = ResolveTemplatesNode()

    # Execution
    execute = ExecuteWorkflowNode(compiler, tracer)
    handle_error = HandleExecutionErrorNode()

    # Connect the flow
    flow.start(resolve)

    # Resolution paths
    resolve - "load_workflow" >> load
    resolve - "not_found" >> suggest

    suggest - "prompt_retry" >> resolve  # User picks similar
    suggest - "exit" >> flow.end

    # Loading paths
    load - "validate_schema" >> validate
    load - "corrupted" >> handle_error
    load - "io_error" >> handle_error
    load - "retry_with_backup" >> load  # Self-loop with backup

    # Validation paths
    validate - "check_lockfile" >> check_lock
    validate - "invalid_schema" >> handle_error

    check_lock - "apply_parameters" >> apply_params
    check_lock - "outdated_lockfile" >> warn_outdated >> apply_params

    # Parameter paths
    apply_params - "prompt_missing" >> prompt_missing
    apply_params - "resolve_templates" >> resolve_templates

    prompt_missing - "resolve_templates" >> resolve_templates
    prompt_missing - "abort" >> flow.end

    # Execution paths
    resolve_templates - "execute" >> execute

    execute - "success" >> format_result >> flow.end
    execute - "compilation_failed" >> handle_error
    execute - "execution_failed" >> handle_error

    # Error recovery
    handle_error - "retry" >> execute
    handle_error - "edit_workflow" >> edit_flow >> resolve_templates
    handle_error - "save_report" >> save_report >> flow.end
    handle_error - "exit" >> flow.end

    return flow
```

### Why Traditional Code Would Struggle

```python
# Traditional approach quickly becomes nested and hard to follow
def execute_named_workflow(name, params):
    try:
        # Load workflow
        workflow_path = storage.get_path(name)
        if not workflow_path.exists():
            # Find similar... but how to loop back?
            similar = storage.find_similar(name)
            # ...

        with open(workflow_path) as f:
            workflow = json.load(f)  # What if invalid JSON?

        # Validate
        if not validator.validate(workflow):
            # How to handle? Log? Raise? Return?

        # Check lockfile
        try:
            # More nesting...
            pass
        except:
            # Ignore? Warn? Fail?

        # Apply parameters
        missing = find_missing_params(workflow, params)
        if missing:
            # Interactive prompt in the middle of execution?
            # What about batch mode?

        # Execute
        try:
            flow = compiler.compile(workflow)
            # But what about retries?
            # What about different error types?
```

The traditional approach leads to:
- Deeply nested try/except blocks
- Unclear error handling strategy
- Difficult to add new validation steps
- Hard to test individual components
- No clear separation between stages

### Real-World Benefits

#### 1. Progressive Enhancement
Easy to add new features:
```python
# Add workflow caching
class CheckCacheNode(Node):
    def exec(self, shared):
        cache_key = self._compute_key(shared["resolved_workflow"])
        if self.cache.has(cache_key):
            shared["cached_result"] = self.cache.get(cache_key)
            return "use_cache"
        return "execute"

# Just insert into flow
check_cache >> execute
check_cache - "use_cache" >> format_cached_result >> flow.end
```

#### 2. Detailed Error Messages
Each node can provide specific context:
```
Failed to load workflow 'fix-issue':
- File: ~/.pflow/workflows/fix-issue.json
- Error: Invalid JSON at line 15, column 3
- Suggestion: Check for missing commas or quotes
```

#### 3. Testing Individual Steps
```python
def test_parameter_prompting():
    node = PromptMissingParamsNode()
    shared = {
        "missing_params": ["issue_number", "repo"],
        "resolved_params": {}
    }

    # Mock input
    with mock_input(["123", "myrepo"]):
        action = node.exec(shared)

    assert action == "resolve_templates"
    assert shared["resolved_params"] == {
        "issue_number": "123",
        "repo": "myrepo"
    }
```

### Conclusion

Named workflow execution is not just "load and run" - it's a complex orchestration involving:
- File I/O with fallbacks
- Multi-level validation
- Interactive parameter resolution
- Template processing
- Error recovery options

PocketFlow provides:
- Clear flow visualization
- Built-in retry for I/O operations
- Easy testing of individual steps
- Natural points for enhancement
- Explicit error handling paths

This is exactly the kind of multi-step, I/O-heavy, user-facing operation that PocketFlow excels at handling.
