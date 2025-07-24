# Task 17: Core Concepts and Constraints

This file contains critical concepts, constraints, and decision rationale for the Natural Language Planner.

## Parameter Extraction as Verification Gate

### Parameters Need Interpretation AND Verification
The ParameterExtractionNode serves as the critical convergence point where both paths meet. It's not just extracting parameters - it's verifying the workflow can actually execute:

1. **Extract**: Get concrete values from natural language
2. **Interpret**: Convert references like "yesterday" to actual dates
3. **Verify**: Ensure ALL required parameters are available
4. **Gate**: Block execution if parameters are missing

### Key Principles
1. **Convergence point**: Both paths (found/generate) must pass through here
2. **Execution feasibility**: Determines if workflow can run
3. **Fail early**: Better to catch missing params before execution
4. **Clear errors**: Tell user exactly what's missing

### Example: Verification Success
```
User: "fix github issue 1234"
Workflow needs: issue_number
Extracted: {issue_number: "1234"}
Verification: ✓ All parameters available
Result: Continue to execution
```

### Example: Verification Failure
```
User: "deploy the app"
Workflow needs: app_name, environment, version
Extracted: {} (nothing specific in input!)
Verification: ✗ Missing required params
Result: Cannot execute - prompt for missing parameters
```

This separation ensures workflows are only executed when they have all necessary inputs, preventing runtime failures and improving user experience.

## Template-Driven Workflow Architecture

### Core Insight: Templates Enable Reusability
The fundamental innovation that enables "Plan Once, Run Forever" is that workflows use **template variables in params**, allowing the same workflow to be reused with different parameters.

```python
# Workflows use $variables directly in node params
workflow = {
    "ir_version": "0.1.0",
    "nodes": [
        # Static structure with dynamic values
        {"id": "get", "type": "github-get-issue",
         "params": {"issue": "$issue_number"}},  # CLI parameter

        {"id": "fix", "type": "claude-code",
         "params": {"prompt": "Fix issue: $issue_data\nStandards: $coding_standards"}},
         # $issue_data from shared store, $coding_standards from file read

        {"id": "commit", "type": "git-commit",
         "params": {"message": "$commit_message"}}  # From previous node
    ],
    "edges": [
        {"from": "get", "to": "fix"},
        {"from": "fix", "to": "commit"}
    ]
}
```

### Concrete Example: Both Paths in Action

This example shows how the planner handles both Path A (reuse) and Path B (generate):

```
User: "fix github issue 1234"
↓
[PLANNER META-WORKFLOW]
Path A (if workflow exists):
  WorkflowDiscoveryNode: Found 'fix-issue' workflow
  ↓
  ParameterExtractionNode:
    - Extract: {"issue_number": "1234"}
    - Verify: Workflow needs issue_number ✓
  ↓
  ResultPreparationNode: Package for CLI

Path B (if no workflow exists):
  WorkflowDiscoveryNode: No complete match
  ↓
  ComponentBrowsingNode: Find github-get-issue, claude-code nodes
    (Can also select existing workflows as sub-workflows!)
  ↓
  GeneratorNode: Create workflow with params: {"issue": "$issue_number"}
    (Creates template variables, not hardcoded "1234")
  ↓
  ValidatorNode: Validate structure (max 3 retries)
    - If invalid → back to GeneratorNode (metadata skipped)
    - If valid → continue
  ↓
  MetadataGenerationNode: Extract metadata (name, description, inputs, outputs)
    (Only runs on validated workflows)
  ↓
  ParameterExtractionNode: Maps "1234" → $issue_number
    (Two-stage: Generator creates templates, this node maps values)
  ↓
  ResultPreparationNode: Package for CLI

[CLI EXECUTION]
- Shows approval prompt
- Saves workflow (preserving $variables)
- Executes with parameter substitution
```

### Simple Design: Runtime Resolution with Path Support

The system uses a **runtime resolution pattern** for template variables that now includes path traversal:

1. **CLI parameters**: `$issue_number` → resolved from `--issue_number=1234`
2. **Shared store values**: `$issue_data` → resolved from `shared["issue_data"]`
3. **Path traversal**: `$issue_data.user.login` → resolved from `shared["issue_data"]["user"]["login"]`
4. **Transparent to nodes**: Nodes receive already-resolved values

### MVP Enhancement: Template Paths

Template variables now support dot notation for accessing nested data:

```python
# Simple template variable
"$issue_number"  # Resolves to shared["issue_number"]

# Template with path
"$issue_data.user.login"  # Resolves to shared["issue_data"]["user"]["login"]

# In workflow params
{"id": "analyze", "type": "llm", "params": {
    "prompt": "Fix issue #$issue_data.number by $issue_data.user.login: $issue_data.title"
}}
```

This enhancement eliminates the need for proxy mappings in 90% of use cases with just ~20 lines of implementation:

```python
def resolve_template(var_name, shared):
    if '.' in var_name:
        parts = var_name.split('.')
        value = shared
        for part in parts:
            value = value.get(part, '')
            if not isinstance(value, dict):
                break
        return str(value)
    return str(shared.get(var_name, ''))
```

This approach ensures:
- No complex mapping structures needed for common cases
- Natural, intuitive syntax users already understand
- Clear separation of concerns
- Easy to understand and debug
- Backwards compatible with simple variables

## Critical Pattern: The Exclusive Parameter Fallback

### Core Architectural Insight

Every pflow node implements a universal fallback pattern that dramatically increases workflow generation flexibility:

```python
# In EVERY node's prep() method:
value = shared.get("key") or self.params.get("key")
```

This means **ALL inputs can also be provided as parameters**, not just the "exclusive parameters" shown in the context builder output.

### What This Means for the Planner

The planner can set ANY value either:
- **Via params** (static, determined at planning time)
- **Via shared store** (dynamic, determined at runtime from previous nodes)

This provides significant flexibility in how the planner connects nodes.

### Examples of the Pattern in Action

```json
// These are ALL valid for a read-file node:

// Option 1: Via shared store (dynamic - from previous node)
{"id": "read", "type": "read-file"}  // Expects shared["file_path"]

// Option 2: Via params (static - hardcoded value)
{"id": "read", "type": "read-file", "params": {"file_path": "config.json"}}

// Option 3: Via params with template variable (dynamic from shared store)
{"id": "read", "type": "read-file", "params": {"file_path": "$path"}}  // Resolves from shared["path"]

// Option 4: Mix of sources
{
  "id": "read",
  "type": "read-file",
  "params": {"encoding": "utf-8"}  // file_path from shared, encoding static
}
```

### How This Reduces Some (But Not All) Proxy Mapping Needs

The combination of fallback pattern + template variables handles many common data routing scenarios:

```json
// Scenario: path-generator writes to shared["path"], read-file expects shared["file_path"]

// Option 1: Using proxy mapping (traditional approach)
{
  "mappings": {
    "read": {"input_mappings": {"file_path": "path"}}
  }
}

// Option 2: Using template variable in params (cleaner approach)
{
  "nodes": [
    {"id": "get-path", "type": "path-generator"},
    {"id": "read", "type": "read-file", "params": {"file_path": "$path"}}
  ]
}
```

### When Proxy Mappings Would Be Needed (v2.0 Feature)

With template path support handling most data access needs, proxy mappings are deferred to v2.0 for specific advanced cases:

1. **Output collision avoidance** (v2.0):
   ```json
   // Two nodes writing to the same key
   {"id": "api1", "type": "api-call"},  // Writes to shared["response"]
   {"id": "api2", "type": "api-call"},  // Also writes to shared["response"] - collision!

   // MVP workaround: Use template paths to access both
   {"params": {"comparison": "API1: $api1.response\nAPI2: $api2.response"}}

   // v2.0 solution with output_mappings:
   {
     "mappings": {
       "api1": {"output_mappings": {"response": "api1_response"}},
       "api2": {"output_mappings": {"response": "api2_response"}}
     }
   }
   ```

2. **Type preservation for non-string parameters** (v2.0):
   - Template variables convert everything to strings
   - For MVP, this covers most use cases (prompts, messages, etc.)
   - v2.0 proxy mappings would preserve original types (int, float, bool, array, object)

3. **Complex transformations** (v2.0):
   - Array filtering, data aggregation
   - For MVP, use dedicated nodes for transformations

### Understanding the Context Builder Output

The context builder shows only "exclusive parameters" - params that are NOT also inputs:
```markdown
### write-file
**Inputs**: `content`, `file_path`, `encoding`
**Outputs**: `written`, `error` (error)
**Parameters**: `append`  # Only 'append' shown - it's exclusive!
```

But the planner can still use ANY input as a parameter:
```json
{
  "type": "write-file",
  "params": {
    "file_path": "/tmp/output.txt",  // Works even though not listed in Parameters!
    "content": "Hello World",         // Also works!
    "append": true                    // The exclusive parameter
  }
}
```

### Edge Case: Truthiness-Safe Pattern

When empty strings, 0, or False are valid values, nodes use a truthiness-safe pattern:
```python
# For values where empty/0/False are valid:
if "content" in shared:
    content = shared["content"]
elif "content" in self.params:
    content = self.params["content"]
else:
    raise ValueError("Missing required 'content'")
```

The planner doesn't need to worry about this - nodes handle it internally.

### Implications for Workflow Generation

1. **Use template paths**: For accessing nested data, use `$data.field.subfield` syntax
2. **Try params first**: For static values, set them directly in params
3. **Template variables for everything dynamic**: Both simple (`$var`) and paths (`$var.field`)
4. **No proxy mappings in MVP**: Deferred to v2.0 for advanced cases
5. **Maximum simplicity**: Focus on natural, readable workflows

This pattern is documented as a core architectural decision in `.taskmaster/knowledge/patterns.md` under "Shared Store Inputs as Automatic Parameter Fallbacks" and is implemented universally across all pflow nodes.

## Critical Constraints for Workflow Generation

### 1. Template Variables with Path Support

Template variables can **only** be used in the `params` field of nodes, now with path traversal:

```json
// ✅ CORRECT - Simple template in params
{"id": "analyze", "type": "llm", "params": {"prompt": "Fix: $issue_data"}}

// ✅ CORRECT - Template with path in params
{"id": "analyze", "type": "llm", "params": {"prompt": "Fix issue #$issue_data.number by $issue_data.user.login"}}

// ❌ IMPOSSIBLE - No "reads" or "writes" fields exist in IR
{"id": "analyze", "type": "llm", "reads": ["$issue_data"]}  // This field doesn't exist!
```

The JSON IR structure is:
- `id`: Node identifier
- `type`: Node type from registry
- `params`: Parameters (ONLY place for templates)
- No explicit reads/writes fields

### 2. MVP Simplification: Template Resolution Only

For MVP, the runtime only needs to handle template resolution with paths:

```json
// MVP approach using template paths:
{
  "nodes": [
    {"id": "api1", "type": "api-call"},  // Writes to shared["api1"]
    {"id": "api2", "type": "api-call"},  // Writes to shared["api2"]
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "Compare API responses:\n1: $api1.response\n2: $api2.response"
    }}
  ]
}
```

**v2.0 Note**: When proxy mappings are added, order of operations will matter:
1. Proxy mappings first (rename keys)
2. Template resolution second (access renamed keys)

### 3. Type Limitations of Template Variables

Template variables convert ALL values to strings:

```json
// shared["retries"] = 3 (integer)
// shared["enabled"] = true (boolean)
// shared["data"] = {"count": 5, "active": true}

// Using templates:
{"params": {"retries": "$retries"}}           // Becomes "3" (string!)
{"params": {"enabled": "$enabled"}}           // Becomes "true" (string!)
{"params": {"count": "$data.count"}}          // Becomes "5" (string!)

// For MVP, this covers most use cases (prompts, messages, file paths, etc.)
// v2.0 will add proxy mappings for type preservation when critical
```

### 4. MVP Approach: Template Variables for All Dynamic Data

**For MVP, use template variables (with optional path support) for all dynamic data access:**
- Simple values (most common): `$issue_number`, `$file_path`, `$prompt`
- Nested data (when needed): `$issue_data.user.login`, `$api_response.data.items[0]`
- String composition: `"Fix issue #$issue_number in $repo_name"`
- CLI parameters: `$issue_number` (from --issue_number=1234)

**For static values:**
- Direct params: `{"params": {"file_path": "config.json"}}`
- Boolean/number strings are fine: `{"params": {"retries": "3"}}`

**v2.0 Features (not in MVP):**
- Proxy mappings for output collisions
- Type preservation for non-string parameters
- Complex data transformations

### Summary for the MVP Planner

1. Use template paths (`$data.field`) for all data access
2. Put ALL template variables in node `params` only
3. Accept that everything becomes strings (covers 90% of use cases)
4. Keep workflows simple and readable
5. No proxy mappings in MVP - deferred to v2.0


## MVP Approach: Avoiding Collisions Through Node Naming

### Simplified Strategy

For MVP, avoid collisions by using descriptive node IDs that naturally namespace the data:

1. **Use descriptive node IDs** - `github1`, `github2` instead of generic names
2. **Leverage node ID as namespace** - Data naturally goes to `shared["github1"]`, `shared["github2"]`
3. **Access with template paths** - `$github1.issue_data`, `$github2.issue_data`
4. **Trust the LLM** - Modern LLMs understand this pattern well

### Prompt Guidance

Include this guidance in the planner prompt:
```
When using multiple nodes of the same type, give them descriptive IDs:
- "github_main" and "github_fork" instead of "node1" and "node2"
- "api_users" and "api_posts" instead of "api1" and "api2"

This naturally avoids collisions as each node writes to its own namespace.
Access the data using template paths: $github_main.issue_data
```

### Example Pattern
```json
{
  "nodes": [
    {"id": "github_main", "type": "github-get-issue", "params": {"issue": "123"}},
    {"id": "github_fork", "type": "github-get-issue", "params": {"issue": "456"}},
    {"id": "compare", "type": "llm", "params": {
      "prompt": "Compare:\nMain: $github_main.issue_data.title\nFork: $github_fork.issue_data.title"
    }}
  ]
}
```

### v2.0 Enhancement

Post-MVP, proxy mappings will provide more sophisticated collision handling and data reorganization. For now, descriptive naming provides a simple, effective solution.

## Risk Mitigation Strategies

### Hybrid Architecture Risk
**Risk**: Confusion about why only planner uses PocketFlow
**Mitigation**:
- Clear documentation in module docstring
- Explicit comments explaining the architectural decision
- Consistent pattern within the planner module

### Complex State Management
**Risk**: Difficult to track state across retries
**Mitigation**:
- Use PocketFlow's shared dict for retry context
- Clear logging of each attempt
- Preserve successful partial results
- Implement checkpoint pattern for recovery

### LLM Non-Determinism
**Risk**: Different outputs for same input
**Mitigation**:
- Structured output with Pydantic schemas
- Three-tier validation pipeline
- Clear success criteria (≥95% accuracy target)
- Progressive enhancement to guide LLM

### Template Variable Validation
**Risk**: LLM uses incorrect template variables or paths
**Mitigation**:
- Validate template variables match expected patterns (including paths)
- Use structure documentation to verify paths like `$data.user.login` exist
- Ensure CLI parameters are properly named
- Check that referenced nodes exist in the workflow
## Success Metrics and Targets

### Core Performance Targets
From the unified understanding of requirements:

1. **≥95% Success Rate**: Natural language → valid workflow generation
2. **≥90% Approval Rate**: Users approve generated workflows without modification
3. **Fast Discovery**: Near-instant workflow matching (LLM call + parsing)
4. **Clear Approval**: Users understand exactly what will execute

### Measuring Success
```python
# Track in shared state for monitoring
shared["metrics"] = {
    "generation_success": True,  # Did we produce valid IR?
    "user_approved": True,       # Did user approve without changes?
    "discovery_time_ms": 150,    # How long to find/generate?
    "total_attempts": 1,         # How many generation attempts?
}
```

## Open Questions and Decisions Needed

1. ~~**Directory Structure**: Which path to use?~~ **RESOLVED**: Use `src/pflow/planning/`
2. ~~**Approval Node Placement**: Is approval part of the planner flow or separate?~~ **RESOLVED**: Approval happens in CLI after planner returns results
3. **Error Feedback Node**: Should this be a separate node or part of validator?
4. **Retry Count Access**: Should we use `cur_retry` attribute or track in shared?
5. **Checkpoint Frequency**: After each successful node or only at key points?
6. **Template Variable Format**: Should we support both `$var` and `${var}` syntax?
7. **Workflow Storage Trigger**: Does the planner save new workflows automatically or prompt user?


### What Makes Implementation Succeed

1. **Understand the Meta-Workflow Nature**
   - The planner orchestrates discovery, generation, and parameter mapping
   - Returns structured results for CLI to execute
   - Two distinct paths that converge at parameter extraction
   - Parameter extraction is verification, not just extraction

2. **Template Variables are Sacred**
   - NEVER hardcode extracted values
   - Always preserve reusability

3. **Use Existing Infrastructure**
   - Don't reinvent validation, compilation, or registry access
   - Build on the solid foundation

4. **Test the Flow, Not Just Nodes**
   - Individual node testing isn't enough
   - Test complete paths through the meta-workflow

## Next Steps

With the directory structure resolved and patterns understood, the implementation should:
1. Create the planner module at `src/pflow/planning/` with PocketFlow patterns
2. Implement core nodes using the advanced patterns:
   - WorkflowDiscoveryNode (finds complete workflows)
   - ComponentBrowsingNode (finds building blocks when no complete match)
   - GeneratorNode with progressive enhancement
   - ValidatorNode using existing validate_ir()
   - MetadataGenerationNode (extracts metadata from validated workflows)
   - ParameterExtractionNode as convergence/verification point (NL → params)
   - ParameterPreparationNode for runtime format (format values for runtime substitution in CLI)
   - ResultPreparationNode to format output for CLI
3. Design flow with proper branching (found vs generate paths converging at parameter extraction)
4. Add comprehensive testing for complete execution paths
5. Integrate with CLI using the exact pattern shown above

---

*Note: This document will be updated as additional research files are analyzed and integrated.*
