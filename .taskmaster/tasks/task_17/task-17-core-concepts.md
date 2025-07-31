# Task 17: Core Concepts and Constraints

This file contains critical concepts, constraints, and decision rationale for the Natural Language Planner.

## Executive Summary

Task 17 is the core feature that makes pflow unique - the Natural Language Planner that enables "Plan Once, Run Forever". After extensive research, I've identified several critical ambiguities and decisions that need to be made before implementation can begin.

**Update**: Prerequisites completed:
- **Task 14**: ✅ Structure documentation for seeing available data paths
- **Task 15**: ✅ Two-phase context builder for smart discovery
- **Task 18**: ✅ Template variable system for workflow reusability

### Key Breakthrough Insights:
1. The workflow discovery mechanism can reuse the exact same pattern as node discovery - the context builder already provides the perfect format.
2. Workflows are reusable building blocks that can be composed into other workflows, not just standalone executions.
3. Two-phase approach separates discovery (what to use) from planning (how to connect), preventing information overload.
4. Hybrid validation approach: Use Pydantic models for type-safe IR generation with Simon Willison's LLM library, then validate with JSONSchema for comprehensive checking.
5. **Template variables** (`$variable`) enable workflow reusability, with path support (`$data.field.subfield`) as a bonus for complex cases
6. No proxy mappings needed for MVP - dramatically simpler implementation

### How It All Fits Together

The planner combines all these decisions into a cohesive workflow generation system:

1. **Input Processing**: Natural language → intent + parameter discovery
2. **Discovery Phase**: Context builder provides nodes + workflows → LLM selects components
3. **Generation Phase**:
   - Pydantic models ensure syntactically valid JSON
   - Template paths for data access
   - Structure documentation shows available paths
4. **Validation Phase**:
   - Static analysis catches structural issues
   - Verifies template paths exist in structure docs
   - Specific error feedback for invalid paths
5. **Presentation**: Natural CLI syntax showing template paths
6. **Storage**: Workflows saved with template variables for reusability

This architecture ensures that every generated workflow is not only syntactically correct but also semantically valid and ready for execution.

### Implementation Challenges to Consider

Understanding these challenges helps avoid common pitfalls during implementation:

1. **Early misconceptions persist** - Previous understanding may influence implementation incorrectly
2. **Two-path architecture is subtle** - Easy to miss that both paths converge at parameter mapping
3. **Parameter mapping dual role** - It's not just extraction, but also verification of executability
4. **Separation of concerns** - Planner prepares workflows, CLI handles approval and execution
5. **Template variables in params** - Templates go directly in params, not in separate structures

## Parameter Mapping as Verification Gate

### Parameters Need Interpretation AND Verification
The ParameterMappingNode serves as the critical convergence point where both paths meet. It's not just extracting parameters - it's verifying the workflow can actually execute:

1. **Extract**: Get concrete values from natural language
2. **Interpret**: Convert references like "yesterday" to actual dates
3. **Verify**: Ensure ALL required parameters are available
4. **Gate**: Block execution if parameters are missing

### The Three Core Responsibilities

ParameterMappingNode performs three distinct but related functions:

1. **Simple Extraction**: Direct value extraction
   - "fix issue 1234" → {"issue_number": "1234"}
   - "analyze report.pdf" → {"file": "report.pdf"}

2. **Complex Interpretation**: Context-aware value resolution
   - "yesterday" → {"date": "2024-11-30"}
   - "latest release" → {"version": "v2.1.0"} (via API call)
   - "this quarter" → {"start": "2024-10-01", "end": "2024-12-31"}

3. **Verification Gate**: Completeness check
   - Compare workflow requirements vs extracted values
   - Route to "params_incomplete" or "params_complete"
   - Package missing params info for CLI escalation

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

### Example: Intent Match with Missing Parameters
```
User: "fix github issue"  (no issue number!)
WorkflowDiscoveryNode: Finds "fix-issue" workflow (intent matches)
Workflow needs: issue_number
Extracted: {} (no number in input)
Verification: ✗ Missing required params
Result: Return to CLI with missing params list
CLI: Prompts user "What issue number?"
```

This separation ensures workflows are only executed when they have all necessary inputs, preventing runtime failures and improving user experience.

## Two-Phase Parameter Handling Architecture

The planner uses a sophisticated two-phase approach to parameter handling:

### Phase 1: Parameter Discovery (Path B only)
- **When**: Before workflow generation
- **What**: Extract named parameters from natural language
- **Purpose**: Provide context for intelligent workflow generation
- **Example**: "fix issue 1234" → discovers {"issue_number": "1234"}

### Phase 2: Parameter Mapping (Both paths)
- **When**: After workflow is found/generated
- **What**: Map discovered parameters to workflow's expected parameters
- **Purpose**: Verify executability and prepare for runtime
- **Example**: {"issue_number": "1234"} → verified against workflow's required params

This architecture enables:
1. Context-aware generation (generator knows available values)
2. Full validation (validator has all needed information)
3. Unified error handling (both paths check parameter availability)

## Input Parameter Handling in Natural Language

### The Core Challenge
How does the planner extract and handle parameters from natural language?
- User says "fix github issue 1234" - how does planner know 1234 is the issue parameter?
- How are template variables created from natural language?
- What happens when parameters are missing?

### The Decision: Smart Parameter Inference with Prompting

**Resolution**: Smart parameter inference with prompting
- LLM infers parameters from context
- Creates template variables for dynamic content
- Prompts user for missing required inputs
- More user-friendly

### Creating New Workflows: Parameter Extraction Process

When creating a new workflow, the planner must perform several sophisticated steps:

#### 1. Intent + Parameter Extraction

When user says "fix github issue 1234", the planner must:
- Recognize the intent: "fix github issue"
- Extract the concrete value: "1234"
- Critical: Generate a template variable $issue_number instead of hardcoding "1234"

#### 2. Template Variable Generation

The planner must be intelligent about creating reusable template variables:
```
User input: "fix github issue 1234 in the pflow repo"
↓
Planner extracts:
- issue_number: 1234 → creates $issue_number
- repo: pflow → creates $repo_name
↓
Generates workflow with templates:
github-get-issue --issue=$issue_number --repo=$repo_name
```

#### 3. Multi-Step Parameter Threading

Complex workflows require parameter flow between nodes:
```
User: "analyze the bug in issue 1234 and create a fix"

Planner must:
1. Create $issue_number from "1234"
2. Plan that github-get-issue outputs to shared["issue_data"]
3. Reference $issue_data in subsequent nodes
4. Create template strings like "Fix for issue #$issue_number: $issue_title"
```

#### 4. Implicit Parameter Inference

Sometimes parameters aren't explicitly stated:
```
User: "summarize today's pull requests"

Planner must infer:
- date parameter → $date with default "today"
- state parameter → $state with default "open"
- repo parameter → $repo with prompt for user
```

### Reusing Existing Workflows: Parameter Mapping Process

This is a fundamentally different process:

#### 1. Workflow Discovery Phase

```
User: "fix github issue 5678"
↓
Planner searches existing workflows:
- Finds "fix-issue" workflow with description "Fetches GitHub issue and creates fix"
- Recognizes semantic match
```

#### 2. Parameter Mapping

The existing workflow already has template variables defined:
```
Existing workflow expects:
- $issue_number (required)
- $repo_name (optional, default: current)
- $priority (optional, default: normal)

User provided: "fix github issue 5678"
↓
Planner maps:
- 5678 → $issue_number
- Missing: $repo_name (use default)
- Missing: $priority (use default)
```

#### 3. Parameter Validation

Before reuse, validate all required parameters are available:
```
If workflow requires $issue_number and $repo_name:
- User says "fix github issue" (missing number)
- Planner must prompt: "What issue number?"
- Or suggest: "Recent issues: #1234, #5678, #9012"
```

### Key Differences Between Creation and Reuse

**Creation Challenges:**
1. Template Variable Naming: Must create meaningful, reusable variable names
2. Parameter Flow Design: Must plan how data flows between nodes via templates
3. Default Value Strategy: Must decide which params need defaults vs runtime values
4. Comprehensiveness: Must capture ALL dynamic aspects as templates, not just obvious ones

**Reuse Challenges:**
1. Semantic Matching: "fix bug 123" should match "fix-github-issue" workflow
2. Parameter Extraction Context: Same NL might map differently based on workflow expectations
3. Missing Parameter Handling: Interactive prompting vs smart defaults
4. Parameter Type Coercion: "issue twenty-three" → 23

### Critical Edge Cases

#### Ambiguous Parameter Extraction:
- "fix the latest issue" → need to resolve "latest"
- "analyze yesterday's data" → need date calculation

Here the planner should identify that it should reuse an existing workflow but wrap it in a new workflow that has a node that resolves the "latest" parameter or a node that resolves the date.

#### Multi-Value Parameters:
- "fix issues 123, 456, and 789" → array handling

The planner should identify that it should reuse an existing workflow but wrap it in BatchFlow that invokes the existing workflow for each issue number.

> This essentially creates alternative workflows that extend an existing workflow. We don't have to implement this in the planner, but we should be able to identify that this is a valid use case and handle it appropriately or create comments in the code to indicate this is a valid use case and should be implemented in the future.

### What the Planner Should NOT Do

**Contextual Parameters:**
- "fix this issue" (referring to previous context)
- "use the same settings as last time"

Pocketflow does not have any state, so it cannot refer to previous context. These types of queries can however be handled perfectly when the user is interacting with an AI agent like Claude Code and the agent uses pflow as a tool. If the agent has an understanding of pflow, it can translate the user's query into a pflow query using its own state.

### The Two-Phase Approach

**Phase 1 - Discovery/Selection:**
- For new: "What nodes should I use?"
- For reuse: "Which existing workflow matches?"

**Phase 2 - Parameter Resolution:**
- For new: "What template variables do I need?"
- For reuse: "How do parameters map to templates?"

This separation is crucial because parameter handling strategy completely changes based on whether you're creating or reusing.

## Template Variable Resolution Mechanism - Most Critical Decision

### The Core Ambiguity
There's a fundamental ambiguity about how template variables (`$variable`) work throughout the system.

**⚠️ CRITICAL WARNING**: The planner must NEVER hardcode values extracted from natural language. When user says "fix github issue 1234", the planner must generate `"issue_number": "$issue"` (NOT `"issue_number": "1234"`). The value "1234" is only for the first execution - saved workflows must work with ANY value.

### The Ambiguity
- Documentation says template resolution is "planner-internal only"
- But examples show `$variables` in the JSON IR that gets saved and executed
- The planner.md states variables are resolved "during planning" but also mentions "runtime substitution"

Without runtime resolution (Option B), each workflow would be single-use, defeating the entire purpose of workflow compilation.

### Three Types of Parameters

Understanding the distinction between different parameter types is crucial:

1. **Node Configuration Parameters** (from Registry)
   - Static configuration options that nodes accept (e.g., `append: bool`, `encoding: str`)
   - Stored in registry under `interface.params`
   - Context builder shows only "exclusive params" (those NOT also in inputs)
   - Can have default values specified in node implementation

2. **Initial Parameters** (Workflow-level)
   - Values extracted from natural language by the planner
   - In MVP: These come ONLY from natural language, never from CLI flags
   - Examples: "1234" from "fix issue 1234" becomes `{"issue_number": "1234"}`
   - These are the `execution_params` passed to template validation

3. **Template Variables** (Runtime References)
   - Placeholders in workflow params: `$issue_number`, `$issue_data.title`
   - Can reference either:
     - Initial parameters: `$issue_number` → resolved from extracted values
     - Node outputs: `$issue_data` → resolved from shared store at runtime
   - Enable workflow reusability - same workflow, different parameters

### Standardized Parameter Terminology

To ensure clarity and consistency across the planner implementation, we use these standardized terms:

1. **`extracted_params`** - Raw parameters extracted from natural language (both paths)
   - Example: User says "fix issue 1234" → `{"issue_number": "1234"}`

2. **`discovered_params`** - Same as extracted_params but specifically for Path B context
   - Kept for backward compatibility and clarity about pre-generation context
   - Provides parameter context to the generator before workflow creation

3. **`verified_params`** - Parameters after ParameterMappingNode verification
   - Confirms all required workflow parameters have values
   - Routes to error handling if parameters are missing

4. **`execution_params`** - Final parameters ready for execution
   - What the planner returns to the CLI
   - What the compiler receives for runtime substitution
   - Replaces the confusing `parameter_values`/`initial_params` duality

### Context
Template variables are the KEY to pflow's "Plan Once, Run Forever" value proposition. They enable workflow reusability by allowing parameters to change between executions while keeping the workflow structure constant.

**Workflow Lifecycle Example:**
```bash
# 1. PLANNING TIME: User provides natural language with specific value
pflow "fix github issue 1234"

# 2. PLANNER GENERATES: IR with template variables (NOT hardcoded values)
{
  "nodes": [{
    "type": "github-get-issue",
    "params": {"issue_number": "$issue"}  # Template variable preserved
  }]
}

# 3. WORKFLOW SAVED: Template variables remain in saved workflow
~/.pflow/workflows/fix-issue.json  # Contains $issue variable

# 4. RUNTIME: Different values substituted each execution
pflow fix-issue --issue=1234  # $issue → "1234"
pflow fix-issue --issue=5678  # $issue → "5678"
```

**Critical Distinction:**
- **Planning Time**: Extract parameters from natural language and create template variables
- **Runtime**: Substitute actual values into template variables from CLI flags

### Options Considered

- [ ] **Option A: Planner resolves all templates during generation**
  - Planner replaces `$issue` with actual shared store references in the IR
  - JSON IR contains no `$variables`, only concrete references
  - Simpler implementation, clearer execution model
  - **Problem**: How do saved workflows handle different parameters?

- [x] **Option B: Runtime resolves template variables WITH PATH SUPPORT**
  - JSON IR contains `$variables` that get resolved during execution
  - Enables parameterized workflows (the core value prop!)
  - **MVP Enhancement**: Template variables support paths: `$issue_data.user.login`
  - Handles 90% of data access needs without proxy mappings
  - **Confirmed**: This is the correct approach for MVP

- [ ] **Option C: Hybrid approach**
  - Some variables resolved by planner (like prompt templates)
  - Others remain as parameters for runtime (like `$issue_number`)
  - Most flexible but most complex

**Resolution**: Option B - Runtime resolution is ESSENTIAL. Template variables are resolved during execution, enabling parameterized workflows (the core value prop!). Most use cases need simple variables (`$issue_number`, `$file_path`), with path support (`$data.user.login`) available for complex data access.

**Validation Note**: The template validator (updated in Task 19) uses the registry to check template variables against actual node outputs, ensuring all required variables can be resolved before execution with clear error messages.

**Implementation Note for Planner**: When the user says "fix github issue 1234", the planner must:
1. Recognize "1234" as a parameter value (not part of the intent)
2. Generate IR with `"issue_number": "$issue_number"` (NOT `"issue_number": "1234"`)
3. Store the workflow with template variables intact
4. Pass `{"issue_number": "1234"}` as `execution_params` to the compiler

**Simple variables are most common**: `$issue_number`, `$file_path`, `$repo_name`. Path traversal (`$data.field`) is supported but less frequently needed.

**Runtime Resolution**: Templates are resolved during workflow execution, NOT during compilation. The compiler validates that required parameters exist in execution_params (unless validate=False), enabling access to both execution_params and runtime shared store data.

## Template-Driven Workflow Architecture

### Core Insight: Templates Enable Reusability
The fundamental innovation that enables "Plan Once, Run Forever" is that workflows use **template variables in params**, allowing the same workflow to be reused with different parameters.

```python
# Workflows use $variables directly in node params
workflow = {
    "ir_version": "0.1.0",
    "nodes": [
        # Simple variables (most common)
        {"id": "get", "type": "github-get-issue",
         "params": {"issue": "$issue_number", "repo": "$repo_name"}},  # From execution_params

        {"id": "fix", "type": "claude-code",
         "params": {"prompt": "Fix issue: $issue_data"}},  # From shared store

        # Path variables for nested data (when needed)
        {"id": "notify", "type": "send-message",
         "params": {"user": "$issue_data.user.login", "title": "$issue_data.title"}}
    ],
    "edges": [
        {"from": "get", "to": "fix"},
        {"from": "fix", "to": "notify"}
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
  ParameterMappingNode:
    - Map: {"issue_number": "1234"}
    - Verify: Workflow needs issue_number ✓
  ↓
  ResultPreparationNode: Package for CLI

Path B (if no workflow exists):
  WorkflowDiscoveryNode: No complete match
  ↓
  ComponentBrowsingNode: Find github-get-issue, claude-code nodes
    (Can also select existing workflows as sub-workflows!)
  ↓
  ParameterDiscoveryNode: Extract named parameters from input
    - Discovers: {"issue_number": "1234"}
    - Provides context for generation
  ↓
  GeneratorNode: Create workflow with params: {"issue": "$issue_number"}
    (Creates template variables using discovered parameters as context)
  ↓
  ValidatorNode: Validate structure AND templates
    - Has discovered params for full validation
    - If invalid → back to GeneratorNode (metadata skipped)
    - If valid → continue
  ↓
  MetadataGenerationNode: Extract metadata (name, description, inputs, outputs)
    (Only runs on validated workflows)
  ↓
  ParameterMappingNode: Maps discovered parameters to workflow parameters
    - Connects {"issue_number": "1234"} to workflow's expected params
    - Verifies all required params available
  ↓
  ResultPreparationNode: Package for CLI

[CLI EXECUTION]
- Shows approval prompt
- Saves workflow (preserving $variables)
- Executes with parameter substitution
```

## Data Flow Orchestration and Proxy Mapping Strategy

How should the planner orchestrate data flow between nodes with incompatible interfaces?

### The Core Problem
Nodes are black boxes with fixed interfaces. When chaining nodes together, their inputs and outputs rarely align perfectly. This creates a fundamental data flow challenge that the planner must solve.

**Example:**
```
youtube-transcript writes: shared["transcript"]
llm reads: shared["prompt"]
↓
How does transcript → prompt?
```

**Why This Matters:**
Without a sophisticated solution, workflows would need many intermediate "glue" nodes just to move data around, making them complex and hard to maintain.

### The Ambiguity:
- Should the planner use template strings to compose data?
- Should proxy mappings just do simple key renaming?
- Can proxy mappings handle complex data extraction?
- Who is responsible for avoiding/managing shared store collisions?

### Options Considered:

- [ ] **Option A: Template String Composition Only**
  - All data transformation via template strings
  - Example: `"prompt": "Summarize: $transcript"`
  - Simple but limited to string concatenation
  - Can't handle nested data or complex transformations

- [ ] **Option B: Simple Key-to-Key Proxy Mappings**
  - Basic renaming: `{"prompt": "transcript"}`
  - Handles 1:1 mappings only
  - Clean but limited flexibility
  - Can't compose multiple values or extract nested data

- [ ] **Option C: Path-Based Proxy Mappings with Nested Extraction**
  - Support JSONPath/dot notation: `{"prompt": "api_response.data.content"}`
  - Extract from arrays: `{"labels": "issue.labels[*].name"}`
  - Combine with templates: `"prompt": "Analyze: $issue.title"`
  - Most powerful and flexible approach
  - **Deferred to v2.0** due to implementation complexity

- [x] **Option D: Template Variables with Path Support (MVP CHOICE)**
  - Extend template variables to support paths: `$issue_data.user.login`
  - Covers 90% of data access needs with minimal implementation (~20 lines)
  - Example: `"prompt": "Fix issue #$issue_data.number by $issue_data.user.login"`
  - Proxy mappings entirely deferred to v2.0
  - Collision handling in MVP: Design workflows to avoid collisions
  - If two nodes write same key: That's a validation error, not something to fix with mappings

### The Decision: Template Variables with Path Support (MVP)

**Resolution**: Extend template variables to support paths: `$issue_data.user.login`
- Covers 90% of data access needs with minimal implementation (~20 lines)
- Example: `"prompt": "Fix issue #$issue_data.number by $issue_data.user.login"`
- Proxy mappings entirely deferred to v2.0
- Collision handling in MVP: Design workflows to avoid collisions
- If two nodes write same key: That's a validation error, not something to fix with mappings

### Examples of Template Path Simplicity:

**1. Direct Path Access (MVP Approach):**
```json
// github-get-issue writes to shared["issue_data"]:
{
  "id": 1234,
  "title": "Fix login",
  "user": {"login": "john"},
  "labels": [{"name": "bug"}, {"name": "urgent"}]
}

// Simply use paths in template variables:
{
  "nodes": [{
    "id": "analyzer",
    "type": "llm",
    "params": {
      "prompt": "Issue #$issue_data.id: $issue_data.title (by $issue_data.user.login)"
    }
  }]
}
```

**2. Complex Prompts Without Mappings:**
```json
{
  "nodes": [{
    "id": "summarize",
    "type": "llm",
    "params": {
      "prompt": "Summarize PR #$pr_data.number:\nTitle: $pr_data.title\nAuthor: $pr_data.user.login\nFiles changed: $pr_data.changed_files"
    }
  }]
}
```

**3. Collision Handling in MVP:**
```json
// If two nodes write to same key, that's a validation error:
// "Error: Both 'api1' and 'api2' write to 'response'.
//  Please use different node types or design workflow to avoid collisions."

// In v2.0, proxy mappings will solve this:
{
  "mappings": {
    "api1": {"output_mappings": {"response": "api1_response"}},
    "api2": {"output_mappings": {"response": "api2_response"}}
  }
}
```

### Critical Insights:
1. **Template paths solve most data access needs** - Direct access via `$data.field.subfield`
2. **Simpler is better for MVP** - ~20 lines of code vs ~200 for full proxy mappings
3. **Structure documentation still helps** - Shows planner what paths are available
4. **Proxy mappings become v2.0 feature** - Not needed for MVP at all

### Planner Responsibilities (Simplified for MVP):
1. Track what each node outputs (data shape from structure docs)
2. Generate template variables with appropriate paths
3. Ensure workflows don't have collisions (validation error if they do)

**Implementation Approach**:
With structure documentation already implemented (Task 14), the planner can:
1. See available paths in the context (e.g., `issue_data.user.login`)
2. Generate template variables using these paths directly
3. Validate paths exist using the structure metadata

The validation framework can verify template variable paths are valid before execution.

### Structure Documentation Enables Template Paths

**UPDATE**: Task 14 successfully implemented structure documentation, and Task 19 enhanced it further by storing pre-parsed interface metadata in the registry. The planner can now see available paths like `issue_data.user.login` in the context builder output and use them confidently in template variables.

The context builder now provides structure information in a dual format that's perfect for LLM consumption (using pre-parsed data from the registry's interface field):

```
Structure (JSON format):
{
  "issue_data": {
    "user": {
      "login": "str"
    }
  }
}

Available paths:
- issue_data.user.login (str)
```

This enables the planner to generate valid template paths and the validator to verify they exist using actual node outputs from the registry.

### Simple Design: Runtime Resolution with Path Support

The system uses a **runtime resolution pattern** for template variables:

1. **CLI parameters**: `$issue_number` → resolved from execution_params
2. **Shared store values**: `$issue_data` → resolved from `shared["issue_data"]`
3. **Path traversal**: `$issue_data.user.login` → resolved from nested data
4. **NO node ID prefixes**: `$api1.response` does NOT work (nodes write to fixed keys)

### MVP Enhancement: Template Paths

Template variables support dot notation for accessing nested data:

```python
# ✅ CORRECT - Simple template variable
"$issue_number"  # From execution_params

# ✅ CORRECT - Shared store key
"$issue_data"    # From shared["issue_data"]

# ✅ CORRECT - Nested path
"$issue_data.user.login"  # From shared["issue_data"]["user"]["login"]

# ❌ WRONG - Node ID prefix (doesn't work)
"$api1.response"  # Nodes don't write to ID-prefixed keys!

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

**Note**: This is a conceptual example. The actual implementation handles edge cases like None values, missing paths, and proper string conversion. The planner just needs to generate workflows with `$variables` and pass extracted values as `execution_params` to the compiler.

This approach ensures:
- No complex mapping structures needed for common cases
- Natural, intuitive syntax users already understand
- Clear separation of concerns
- Easy to understand and debug
- Backwards compatible with simple variables

## Workflow Storage and Discovery Concepts

### Core Insight: Workflows as Building Blocks

The "find or build" pattern is core to pflow's value proposition. A critical insight is that **workflows are building blocks that can be used inside other workflows**, not just standalone executions.

### Updated Understanding

The "find or build" pattern is core to pflow but implementation details are now clearer:
- Discovery can work exactly like node discovery - using descriptions
- The context builder already provides the pattern we need
- Workflows just need a good description field for LLM matching
- **CRITICAL**: Workflows are building blocks that can be used inside other workflows, not just standalone executions

### Discovery Through Context Builder Pattern

Discovery works exactly like node discovery - using descriptions:
- For nodes: Context builder generates markdown with descriptions
- For workflows: Store with description field in same format
- LLM sees both nodes and workflows in unified format
- Reuses existing infrastructure perfectly

### The Simplified Approach

- [x] **Use Context Builder Pattern for Everything**
  - For nodes: Context builder generates markdown with descriptions
  - For workflows: Store with description field in same format
  - LLM sees both nodes and workflows in unified format
  - Example workflow entry:
    ```markdown
    ### fix-github-issue
    Fetches a GitHub issue, analyzes it with AI, generates a fix, and creates a PR
    ```
  - Reuses existing infrastructure perfectly

### Implementation
1. **Node Discovery**: Already works via context builder markdown
2. **Workflow Discovery**:
   - Load saved workflows from `~/.pflow/workflows/`
   - Format them like nodes: name + description
   - Append to context builder output
   - LLM selects from both nodes and existing workflows

Example workflow entry in context:
```markdown
### fix-github-issue
Fetches a GitHub issue, analyzes it with AI, generates a fix, and creates a PR
```

### Key Discovery Principle

The description field is all we need for semantic matching. The LLM can understand "fix github issue 1234" matches a workflow described as "Fetches a GitHub issue, analyzes it with AI, generates a fix".

### Workflow Storage Format

```json
{
  "name": "fix-issue",
  "description": "Fetches a GitHub issue, analyzes it with AI, generates a fix, and creates a PR",
  "inputs": ["issue_number"],
  "outputs": ["pr_number", "pr_url"],
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [...],
    "edges": [...]
  },
  "created": "2025-01-01T00:00:00Z",
  "version": "1.0.0"
}
```

**Key Fields**:
- `name`: Workflow identifier for execution (`pflow fix-issue`)
- `description`: Natural language description for discovery matching
- `inputs`: Expected parameters (enables validation and prompting)
- `outputs`: What the workflow produces (for composition)
- `ir`: Complete JSON IR with template variables preserved

### Workflow Interface Declarations (Task 21)

Workflows now declare their expected inputs and outputs:

```json
{
  "name": "fix-issue",
  "description": "Fixes GitHub issues and creates PR",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {
      "issue_number": {
        "description": "GitHub issue number to fix",
        "required": true,
        "type": "string"
      }
    },
    "outputs": {
      "pr_url": {
        "description": "URL of created pull request",
        "type": "string"
      }
    },
    "nodes": [...],
    "edges": [...]
  }
}
```

This enables:
- Parameter validation at compile time
- Better discovery matching
- Clear workflow contracts
- Integration with WorkflowManager for proper storage

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

   // MVP limitation: Both API calls write to same key - collision! This is a known limitation for the system when implementing task 17. And will be fixed in task 9, AFTER task 17 is complete.
   // Using same node type twice will overwrite data
   {"params": {"comparison": "API response: $response"}}  // Only gets last API's response

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
// MVP approach - collision limitation:
{
  "nodes": [
    {"id": "api1", "type": "api-call"},  // Writes to shared["response"]
    {"id": "api2", "type": "api-call"},  // Overwrites shared["response"] - collision!
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "Analyze API response: $response"  // Only sees api2's response
    }}
  ]
}
// Note: Using same node type twice causes collision - known MVP limitation. Create examples that only use one node type once when implementing the planner (task 17).
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
- Nested data (when needed): `$issue_data.user.login`, `$api_response.data.items` (**Note: Array indexing like [0] is NOT supported**)
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


## MVP Approach: Node Output Behavior

### Nodes Write to Fixed Keys
**CRITICAL**: In the MVP, nodes write to FIXED output keys
- `github-get-issue` ALWAYS writes to `shared["issue_data"]`
- `llm` ALWAYS writes to `shared["response"]`
- `read-file` ALWAYS writes to `shared["content"]`
- Node IDs are for workflow clarity only, they don't affect data storage

### Collision Problem
**MVP Limitation**: Using the same node type twice causes data collision:
```json
{
  "nodes": [
    {"id": "api1", "type": "api-call"},  // Writes to shared["response"]
    {"id": "api2", "type": "api-call"}   // OVERWRITES shared["response"]!
  ]
}
```

### Workarounds
1. **Use different node types when possible**:
   ```json
   [{"id": "get_data", "type": "http-get"},
    {"id": "post_data", "type": "http-post"}]
   ```
2. **Use workflow composition to isolate repeated operations**:
   ```json
   {"type": "workflow", "params": {"workflow_name": "api-caller"}}
   ```
3. **Design workflows to avoid same-type repetition**

### No Collision Detection
MVP assumes each node type is used once or sequentially. If the same node type is used multiple times, later executions overwrite earlier data. This limitation is acceptable for MVP and will be addressed in v2.0 with proxy mappings.

## MVP Feature Boundaries

### CRITICAL CLARIFICATION: System Layer vs User Layer

**This section defines boundaries for USER-FACING WORKFLOWS generated by the planner, NOT the planner's own implementation.** (since both are pocketflow workflows, making this clear is important to avoid confusion)

**System Layer (Planner Implementation)**:
- ✅ Uses full pocketflow features including action-based transitions
- ✅ Implements sophisticated error handling and retry logic
- ✅ Has validation feedback loops and conditional routing
- ✅ This is infrastructure code in Python using pocketflow patterns

**User Layer (Generated Workflows)**:
- What features can the generated JSON IR include?
- How complex can user workflows be?
- What's allowed vs deferred to v2.0?

### MVP Scope for Generated Workflows

**Allowed in generated workflows**:
- Sequential node execution (A → B → C)
- Template variables for reusability ($var syntax)
- Basic parameter types (string, number, boolean, arrays)
- Node-internal error handling (retries, fallbacks)
- Complex sequential workflows (many nodes)
- Path-based template variables for data flow
- Workflow composition (workflows using other workflows)

**Excluded from generated workflows**:
- Action-based transitions between nodes (no branching)
- Conditional workflow paths
- Explicit error recovery branches in IR
- Dynamic node selection based on runtime conditions
- Parallel execution
- User editing of generated workflows (just Y/n approval)
- Custom node creation through planner

This provides a powerful MVP that can generate sophisticated sequential workflows while keeping implementation complexity manageable. The planner itself uses full pocketflow features internally, but limits generated workflows to sequential patterns.

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

### Template Variable Complexity
**Risk**: Template variable system becomes too complex
**Mitigation**:
- Start with simple $variable substitution, enhance later
- Focus on path support (`$data.field`) for MVP
- Defer advanced features to v2.0

### Invalid Workflow Generation
**Risk**: LLM generates invalid workflows despite prompting
**Mitigation**:
- Strong validation with retry loop and error feedback
- Progressive enhancement on each retry attempt
- Bounded retries (max 3) to prevent infinite loops

### Discovery Failures
**Risk**: Discovery doesn't find relevant workflows
**Mitigation**:
- Good workflow naming and description conventions
- Semantic matching based on descriptions
- Over-inclusive browsing to avoid missing components

### Scope Creep
**Risk**: Adding "just one more feature" beyond MVP
**Mitigation**:
- Strict MVP checklist in documentation
- Clear v2.0 deferral for advanced features
- Focus on sequential workflows only
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

### Implementation Recommendations

Based on comprehensive analysis, here's the recommended approach:

1. **Use runtime resolution with path support** - Runtime resolution with `$data.field` syntax
2. **Use unified discovery pattern** - Context builder lists both nodes and workflows
3. **Store workflows with descriptions** - Simple JSON with name, description, and IR
4. **Use claude-sonnet-4-20250514** for planning with structured prompts
5. **Show CLI syntax only** for approval (with template paths visible)
6. **Implement smart error recovery** with specific strategies
7. **Strictly limit to sequential workflows** for MVP
8. **Implement planner as Python pocketflow code** - nodes.py + flow.py pattern, not JSON IR
9. **Use Pydantic models for IR generation** - Hybrid approach with JSONSchema validation
10. **Simplify validation** - Focus on verifying template paths exist in structure docs
11. **No proxy mappings in MVP** - Entirely deferred to v2.0

**Critical Implementation Details**:
- Template path resolution: ~20 lines of code to split on '.' and traverse dictionaries
- Use Simon Willison's `llm` library with model "claude-sonnet-4-20250514"
- Pydantic models for type-safe IR generation, then JSONSchema validation

**Implementation Checklist**:
- Use template variables (`$data`) and template variables with paths (`$data.field.subfield`)
- Workflows can use other workflows as building blocks
- Planner is infrastructure (Python pocketflow), not user workflow (JSON IR)
- Generated workflows are sequential only (no branching)
- Two-phase context (discovery vs planning) prevents LLM overwhelm
- Template variables ≠ CLI parameters (runtime resolution vs execution args)
- Planner can use full pocketflow features, but generated workflows are sequential only (MVP)

### Key Implementation Simplifications:
- No separate discovery system needed - reuse context builder pattern
- Workflows are reusable building blocks alongside nodes
- Two-phase approach: discovery (descriptions only) → planning (full details)

## Implementation Resolutions

Based on implementation clarifications, the following key decisions have been resolved:

### 1. Complete Workflow Matching Threshold - RESOLVED ✓
**Resolution**: WorkflowDiscoveryNode only returns "found_existing" if the workflow **completely** satisfies the user's entire request. No partial matches are considered complete.

### 2. Component Browsing Scope - RESOLVED ✓
**Resolution**: ComponentBrowsingNode can select BOTH individual nodes AND existing workflows to use as sub-workflows. This enables workflow composition and reuse.

Example: If user wants "fix github issue and notify team", and "fix-github-issue" workflow exists, ComponentBrowsingNode can select that workflow plus a "send-notification" node to create a new composite workflow.

### 3. Parameter Extraction Two-Phase Architecture - RESOLVED ✓
**Resolution**: Parameter handling uses a sophisticated two-phase approach:

**Phase 1 - Parameter Discovery (Path B only)**:
- ParameterDiscoveryNode extracts named parameters BEFORE workflow generation
- Provides context for intelligent workflow design
- Example: "fix issue 1234" → discovers {"issue_number": "1234"}

**Phase 2 - Parameter Mapping (Both paths)**:
- ParameterMappingNode maps values to workflow parameters
- Verifies all required parameters are available
- Routes to "params_incomplete" if missing

This architecture enables context-aware generation and full validation in the planner.

### 4. Validation Depth - RESOLVED ✓
**Resolution**: MVP includes all three validation tiers:
1. **Syntactic Validation** (via Pydantic) ✓
2. **Static Analysis** (node and parameter validation) ✓
3. **Data Flow Analysis** (static path verification) ✓

Mock execution is deferred to v2.0. The MVP performs static analysis to verify template paths exist in structure documentation without simulating execution.

### 5. Error Recovery Limits - RESOLVED ✓
**Resolution**: All nodes have a maximum of 3 retries for any error type. This applies uniformly across:
- LLM generation failures
- Validation errors
- Structure errors
- Any other recoverable errors

### 6. Metadata Generation - RESOLVED ✓
**Resolution**: A new **MetadataGenerationNode** will be added after ValidatorNode in Path B. This node:
- Extracts metadata from the VALIDATED workflow
- Creates suggested_name, description, inputs, outputs
- Only runs after successful validation (efficiency optimization)
- Skipped entirely when validation fails and flow returns to generator

Updated flow for Path B:
```
ComponentBrowsingNode → ParameterDiscoveryNode → GeneratorNode → ValidatorNode → MetadataGenerationNode → ParameterMappingNode
```

### 7. Template Validation Timing - RESOLVED ✓
**Resolution**: Dual validation approach

**Planner Validation**:
- ValidatorNode performs FULL template validation
- Uses discovered parameters from ParameterDiscoveryNode
- Enables retry/fixing through planner's self-correcting flow

**Runtime Validation**:
- Re-validates as safety check with actual execution parameters
- Uses same TemplateValidator class for consistency
- Catches edge cases and ensures execution readiness

This dual approach provides early error detection with retry opportunity while maintaining runtime safety.

## Open Questions and Decisions Needed

1. ~~**Directory Structure**: Which path to use?~~ **RESOLVED**: Use `src/pflow/planning/`
2. ~~**Approval Node Placement**: Is approval part of the planner flow or separate?~~ **RESOLVED**: Approval happens in CLI after planner returns results
3. ~~**Error Feedback Node**: Should this be a separate node or part of validator?~~ **RESOLVED**: Part of validator with specific routing
4. ~~**Retry Count Access**: Should we use `cur_retry` attribute or track in shared?~~ **RESOLVED**: Use node's max_retries (3 for all nodes)
5. ~~**Checkpoint Frequency**: After each successful node or only at key points?~~ **RESOLVED**: Not needed for MVP
6. ~~**Template Variable Format**: Should we support both `$var` and `${var}` syntax?~~ **RESOLVED**: `$var` and `$var.field.subfield` path syntax for MVP (no `${var}` braces). Path support implemented by Task 18.
7. ~~**Workflow Storage Trigger**: Does the planner save new workflows automatically or prompt user?~~ **RESOLVED**: CLI handles after user approval


### What Makes Implementation Succeed

1. **Understand the Meta-Workflow Nature**
   - The planner orchestrates discovery, generation, and parameter mapping
   - Returns structured results for CLI to execute
   - Two distinct paths that converge at parameter mapping
   - Parameter mapping is verification, not just extraction

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
   - ParameterDiscoveryNode (extracts named parameters from NL before generation)
   - GeneratorNode with progressive enhancement
   - ValidatorNode using existing validate_ir() and full template validation
   - MetadataGenerationNode (extracts metadata from validated workflows)
   - ParameterMappingNode as convergence/verification point (maps values → params)
   - ParameterPreparationNode for runtime format (format values for runtime substitution in CLI)
   - ResultPreparationNode to format output for CLI
3. Design flow with proper branching (found vs generate paths converging at parameter mapping)
4. Add comprehensive testing for complete execution paths
5. Integrate with CLI using the exact pattern shown above

---

*Note: This document will be updated as additional research files are analyzed and integrated.*
