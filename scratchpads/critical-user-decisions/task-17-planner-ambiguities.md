# Task 17: Natural Language Planner System - Critical Decisions & Ambiguities

## Executive Summary

Task 17 is the core feature that makes pflow unique - the Natural Language Planner that enables "Plan Once, Run Forever". After extensive research, I've identified several critical ambiguities and decisions that need to be made before implementation can begin.

**Update**: Tasks 14 and 15 have been completed successfully:
- **Task 14**: ✅ Implemented structured output metadata support, enabling the planner to see available paths for template variables
- **Task 15**: ✅ Extended the context builder for two-phase discovery, preventing LLM overwhelm while supporting workflow reuse

### Key Breakthrough Insights:
1. The workflow discovery mechanism can reuse the exact same pattern as node discovery - the context builder already provides the perfect format.
2. Workflows are reusable building blocks that can be composed into other workflows, not just standalone executions.
3. Two-phase approach separates discovery (what to use) from planning (how to connect), preventing information overload.
4. Hybrid validation approach: Use Pydantic models for type-safe IR generation with Simon Willison's LLM library, then validate with JSONSchema for comprehensive checking.
5. **Template paths** (`$data.field.subfield`) solve 90% of data access needs - see Section 2
6. No proxy mappings needed for MVP - dramatically simpler implementation

## 1. Template Variable Resolution Mechanism - Decision importance (5) ⚠️ MOST CRITICAL

There's a fundamental ambiguity about how template variables (`$variable`) work throughout the system.

**⚠️ CRITICAL WARNING**: The planner must NEVER hardcode values extracted from natural language. When user says "fix github issue 1234", the planner must generate `"issue_number": "$issue"` (NOT `"issue_number": "1234"`). The value "1234" is only for the first execution - saved workflows must work with ANY value.

### Context:
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

Without runtime resolution (Option B), each workflow would be single-use, defeating the entire purpose of workflow compilation.

### The Ambiguity:
- Documentation says template resolution is "planner-internal only"
- But examples show `$variables` in the JSON IR that gets saved and executed
- The planner.md states variables are resolved "during planning" but also mentions "runtime substitution"

### Options:

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

**Recommendation**: Option B with path support - Runtime resolution is ESSENTIAL. The addition of path support (e.g., `$issue_data.user.login`) eliminates the need for proxy mappings in most cases, dramatically simplifying the MVP while maintaining full power.

**Validation Note**: The validation pipeline (Section 9) ensures all template variables can be resolved by tracking data flow through mock execution.

**Implementation Note for Planner**: When the user says "fix github issue 1234", the planner must:
1. Recognize "1234" as a parameter value (not part of the intent)
2. Generate IR with `"issue_number": "$issue"` (NOT `"issue_number": "1234"`)
3. Store the workflow with template variables intact
4. The value "1234" is only used during the first execution, not baked into the workflow

**MVP Enhancement**: Template variables now support paths (e.g., `$issue_data.user.login`), eliminating the need for complex data routing with proxy mappings. See Section 2 for the complete architectural decision.

### CRITICAL CLARIFICATION: The Meta-Workflow Architecture

**The planner is a meta-workflow that creates workflows and prepares them for execution by the CLI.** This is a fundamental insight that affects the entire architecture:

1. **The Planner Workflow Includes**:
   - Discovery: Find existing workflow or determine need to create
   - Generation: Create new workflow if needed (with template variables)
   - Parameter Extraction: Extract "1234" from "fix github issue 1234"
   - Parameter Mapping: Prepare extracted values for template variable substitution
   - Result Preparation: Package workflow IR + parameter values for CLI

   **The CLI then handles**:
   - Confirmation: Show user what will execute
   - Execution: Actually run the workflow with parameter substitution

2. **MVP Architecture**: Every natural language request goes through the planner
   ```
   "fix github issue 1234" → Planner finds/creates → Extracts params → Returns to CLI → CLI executes
   ```

3. **Future v2.0+**: Known workflows can be executed directly
   ```
   pflow fix-issue --issue=1234  # Bypasses planner
   ```

This means the planner doesn't just generate and hand off - it orchestrates discovery, generation, and parameter mapping, then returns structured results to the CLI for execution.

## 2. Data Flow Orchestration and Proxy Mapping Strategy - Decision importance (5)

How should the planner orchestrate data flow between nodes with incompatible interfaces?

### Context:
Nodes are black boxes with fixed interfaces. When chaining nodes together, their inputs and outputs rarely align perfectly. This creates a fundamental data flow challenge that the planner must solve.

**The Core Problem:**
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

### Options:

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
  - Combine with templates: `"prompt": "Analyze: ${issue.title}"`
  - Most powerful and flexible approach
  - **Deferred to v2.0** due to implementation complexity

- [x] **Option D: Template Variables with Path Support (MVP CHOICE)**
  - Extend template variables to support paths: `$issue_data.user.login`
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

**Recommendation**: Option D - Template variables with path support provide the optimal balance of power and simplicity for MVP. This covers 90% of use cases with minimal implementation complexity.

**Implementation Approach**:
With structure documentation already implemented (Task 14), the planner can:
1. See available paths in the context (e.g., `issue_data.user.login`)
2. Generate template variables using these paths directly
3. Validate paths exist using the structure metadata

The validation framework can verify template variable paths are valid before execution.

## 2.1 Structure Documentation Enables Template Paths - Decision importance (5)

**UPDATE**: Task 14 successfully implemented structure documentation, which is essential for the template path approach (Option D above). The planner can now see available paths like `issue_data.user.login` in the context builder output and use them confidently in template variables.

The context builder now provides structure information in a dual format that's perfect for LLM consumption:

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

This enables the planner to generate valid template paths and the validator to verify they exist.

## 3. Workflow Storage and Discovery Implementation - Decision importance (4)

The "find or build" pattern is core to pflow but implementation details are now clearer.

### Updated Understanding:
- Discovery can work exactly like node discovery - using descriptions
- The context builder already provides the pattern we need
- Workflows just need a good description field for LLM matching
- **CRITICAL**: Workflows are building blocks that can be used inside other workflows, not just standalone executions

### The Simplified Approach:

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

### Implementation:
1. **Node Discovery**: Already works via context builder markdown
2. **Workflow Discovery**:
   - Load saved workflows from `~/.pflow/workflows/`
   - Format them like nodes: name + description
   - Append to context builder output
   - LLM selects from both nodes and existing workflows

**Key Insight**: The description field is all we need for semantic matching. The LLM can understand "fix github issue 1234" matches a workflow described as "Fetches a GitHub issue, analyzes it with AI, generates a fix".

### Workflow Storage Format:
```json
{
  "name": "fix-issue",
  "description": "Fetches a GitHub issue, analyzes it with AI, generates a fix, and creates a PR",
  "inputs": ["issue_number"],
  "outputs": ["pr_number", "pr_url"],
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [...],
    "edges": [...],
    "mappings": {...}
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

## 4. LLM Model Selection and Configuration - Decision importance (3)

✅ **RESOLVED**: We will use `claude-sonnet-4-20250514` with Simon Willison's llm library used directly from within the exec of a node in `nodes.py` (no llm client wrapper needed). All docs has been updated to reflect this.

## 5. Input Parameter Handling in Natural Language - Decision importance (5)

How does the planner extract and handle parameters from natural language?

### The Ambiguity:
- User says "fix github issue 1234" - how does planner know 1234 is the issue parameter?
- How are template variables created from natural language?
- What happens when parameters are missing?

### Options:

- [ ] **Option A: Strict parameter extraction**
  - LLM must identify all parameters in the input
  - Fail if any required parameters missing
  - More predictable but less flexible

- [x] **Option B: Smart parameter inference with prompting**
  - LLM infers parameters from context
  - Creates template variables for dynamic content
  - Prompts user for missing required inputs
  - More user-friendly

- [ ] **Option C: Two-phase approach**
  - First extract intent and parameters
  - Then generate workflow with templates
  - More structured but slower

### Context:

When creating a new workflow, the planner must perform several sophisticated steps:

  1. Intent + Parameter Extraction

  When user says "fix github issue 1234", the planner must:
  - Recognize the intent: "fix github issue"
  - Extract the concrete value: "1234"
  - Critical: Generate a template variable $issue_number instead of hardcoding "1234"

  2. Template Variable Generation

  The planner must be intelligent about creating reusable template variables:
  User input: "fix github issue 1234 in the pflow repo"
  ↓
  Planner extracts:
  - issue_number: 1234 → creates $issue_number
  - repo: pflow → creates $repo_name
  ↓
  Generates workflow with templates:
  github-get-issue --issue=$issue_number --repo=$repo_name

  3. Multi-Step Parameter Threading

  Complex workflows require parameter flow between nodes:
  User: "analyze the bug in issue 1234 and create a fix"

  Planner must:
  1. Create $issue_number from "1234"
  2. Plan that github-get-issue outputs to shared["issue_data"]
  3. Reference $issue_data in subsequent nodes
  4. Create template strings like "Fix for issue #$issue_number: $issue_title"

  4. Implicit Parameter Inference

  Sometimes parameters aren't explicitly stated:
  User: "summarize today's pull requests"

  Planner must infer:
  - date parameter → $date with default "today"
  - state parameter → $state with default "open"
  - repo parameter → $repo with prompt for user

  Reusing an Existing Workflow

  This is a fundamentally different process:

  1. Workflow Discovery Phase

  User: "fix github issue 5678"
  ↓
  Planner searches existing workflows:
  - Finds "fix-issue" workflow with description "Fetches GitHub issue and creates fix"
  - Recognizes semantic match

  2. Parameter Mapping

  The existing workflow already has template variables defined:
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

  3. Parameter Validation

  Before reuse, validate all required parameters are available:
  If workflow requires $issue_number and $repo_name:
  - User says "fix github issue" (missing number)
  - Planner must prompt: "What issue number?"
  - Or suggest: "Recent issues: #1234, #5678, #9012"

  Key Differences and Nuances

  Creation Challenges:

  1. Template Variable Naming: Must create meaningful, reusable variable names
  2. Parameter Flow Design: Must plan how data flows between nodes via templates
  3. Default Value Strategy: Must decide which params need defaults vs runtime values
  4. Comprehensiveness: Must capture ALL dynamic aspects as templates, not just obvious ones

  Reuse Challenges:

  1. Semantic Matching: "fix bug 123" should match "fix-github-issue" workflow
  2. Parameter Extraction Context: Same NL might map differently based on workflow expectations
  3. Missing Parameter Handling: Interactive prompting vs smart defaults
  4. Parameter Type Coercion: "issue twenty-three" → 23

  Critical Edge Cases:
  1. Ambiguous Parameter Extraction:
    - "fix the latest issue" → need to resolve "latest"
    - "analyze yesterday's data" → need date calculation

  Here the planner should identify that it should reuse an existing workflow but wrap it in a new workflow that has a node that resolves the "latest" parameter or a node that resolves the date.

  2. Multi-Value Parameters:
    - "fix issues 123, 456, and 789" → array handling

  The planner should identify that it should reuse an existing workflow but wrap it in BatchFlow that invokes the existing workflow for each issue number.

  > This essentially creates alternative workflows that extend an existing workflow. We dont have to implement this in the planner, but we should be able to identify that this is a valid use case and handle it appropriately or create comments in the code to indicate this is a valid use case and should be implemented in the future.

  What the planner should NOT do:
  1. Contextual Parameters:
    - "fix this issue" (referring to previous context)
    - "use the same settings as last time"

  Pocketflow does not have any state, so it cannot refer to previous context. These types of queries can however be handled perfectly when the user is interacting with an AI agent like Claude Code and the agent uses pflow as a tool. If the agent has an understanding of pflow, it can translate the user's query into a pflow query using its own state.

  The Two-Phase Approach:

  Phase 1 - Discovery/Selection:
  - For new: "What nodes should I use?"
  - For reuse: "Which existing workflow matches?"

  Phase 2 - Parameter Resolution:
  - For new: "What template variables do I need?"
  - For reuse: "How do parameters map to templates?"

  This separation is crucial because parameter handling strategy completely changes based on
  whether you're creating or reusing.

**Recommendation**: Option B - Smart inference makes the natural language interface more intuitive.

## 6. Prompt Template Design and Management - Decision importance (4)

How should prompt templates be structured and managed?

### The Ambiguity:
- Task mentions both inline prompts and template files
- How complex should prompts be?
- How to ensure prompts generate valid JSON IR?

### Options:

- [x] **Option A: Simple Python f-strings in code**
  - Define prompts as constants in prompts.py
  - Use f-strings for variable substitution
  - Easy to implement and modify
  - Example: `WORKFLOW_PROMPT = f"Given nodes: {nodes}\nGenerate workflow for: {request}"`

- [ ] **Option B: External template files**
  - Store prompts in separate files
  - Use Jinja2 for complex templating
  - Better separation but more complex

- [ ] **Option C: Prompt chaining system**
  - Multiple specialized prompts
  - Chain them based on complexity
  - Most flexible but overengineered for MVP

**Recommendation**: Option A - Simple f-strings are sufficient for MVP prompts.

## 7. JSON IR Generation Validation - Decision importance (4)

How to ensure LLM generates valid JSON IR every time?

### The Ambiguity:
- LLMs can generate malformed JSON
- How to handle validation failures?
- How many retries are acceptable?
- Should we use structured outputs with Pydantic?

### Options:

- [ ] **Option A: Strict JSON schema enforcement**
  - Validate against full schema
  - Reject any deviation
  - Most reliable but may reject valid variations

- [ ] **Option B: Liberal parsing with correction**
  - Try to parse and fix common issues
  - Validate essential fields only
  - Retry with error feedback to LLM
  - More forgiving and user-friendly

- [x] **Option C: Pydantic with Structured Output (Hybrid Approach)**
  - Use Pydantic models with LLM's structured output feature
  - Type-safe construction with `model.prompt(prompt, schema=FlowIR)`
  - Validate final output with existing JSONSchema
  - Best of both worlds: type safety + comprehensive validation
  - Leverages Simon Willison's LLM library capabilities

**Recommendation**: Option C - Pydantic models provide type safety during generation while JSONSchema ensures comprehensive validation. This leverages the LLM library's structured output capabilities optimally.

**Note**: While Pydantic ensures syntactically valid JSON, semantic validation (data flow and template path verification) is handled by the validation pipeline described in Section 9.

### Implementation Pattern:
```python
# Use Pydantic for generation
response = model.prompt(prompt, schema=FlowIR)
flow_dict = json.loads(response.text())

# Validate with JSONSchema for comprehensive checking
validate_ir(flow_dict)
```

## 8. User Approval Flow Implementation - Decision importance (3)

How should the approval process work in practice?

### Context:
With template paths, users see exactly what data is being accessed in a natural, readable format. The CLI display shows the template variables with their paths directly.

### How CLI Parameters Work:
1. **Each node has its own parameter namespace** - `--prompt` on one node doesn't conflict with `--prompt` on another
2. **Natural paths everywhere** - Users see `$issue_data.user.login` directly in prompts
3. **Data flow is transparent** - Template paths show exactly where data comes from
4. **Intuitive understanding** - `$data.field` syntax is familiar to developers

### Example:
```bash
# What user sees with template paths:
github-get-issue --issue=1234 >>
llm --prompt="Fix issue #$issue_data.id: $issue_data.title (by $issue_data.user.login)"

# Clear data flow:
# 1. github-get-issue writes to shared["issue_data"]
# 2. llm's prompt directly references the paths it needs
# 3. No hidden mappings or transformations
```

### The Ambiguity:
- Show JSON? CLI syntax? Both?
- How to handle modifications?
- What about headless/CI environments?

### Options:

- [x] **Option A: Show natural CLI syntax**
  - Display each node with its natural parameters
  - Show resolved values (not template variables) for this execution
  - Template variables shown in saved workflow name for reuse
  - Simple Y/n prompt for approval
  - Save on approval, execute after
  - **Key benefit**: No complex notation needed for mappings or data flow
  - **Clarification**: The approval prompt and workflow saving are handled by the CLI after the planner returns its results, not within the planner meta-workflow itself

- [ ] **Option B: Interactive modification**
  - Show CLI syntax
  - Allow inline editing
  - More powerful but complex UI

- [ ] **Option C: Multi-format display**
  - Show both CLI and visual representation
  - Toggle between views
  - Too complex for CLI interface

### What Users See:
```bash
$ pflow "fix github issue 1234"

Generated workflow:

github-get-issue --issue=1234 >>
claude-code --prompt="Fix this issue: $issue" >>
llm --prompt="Write commit message for: $code_report" >>
git-commit --message="$commit_message"

Save as 'fix-issue' and execute? [Y/n]: y
```

**Note**: The `$variables` shown are template placeholders that will be resolved from the workflow's data flow, not CLI parameters the user needs to provide.

**Recommendation**: Option A - Natural CLI syntax with visible template paths provides the clearest understanding of data flow while remaining intuitive.

## 9. Error Recovery, Error Handling and Validation Strategy - Decision importance (5)

**Architecture Context**: The planner itself is implemented as a pocketflow flow with multiple nodes (discovery, generation, validation, approval). This section covers how these planner nodes handle errors and how the validation node ensures generated workflows are correct. All error handling and validation happens within the planner flow using pocketflow's patterns.

How should the planner handle errors and ensure generated workflows will actually execute?

### The Ambiguity:
- What errors are recoverable vs fatal?
- How to ensure workflows will execute correctly before showing to users?
- How to provide useful feedback for recovery?
- How deep should validation go?

### Options:

- [ ] **Option A: Simple retry with backoff**
  - Retry all errors up to 3 times
  - Exponential backoff
  - Simple but may waste time on unrecoverable errors

- [x] **Option B: Error-specific recovery with validation pipeline**
  - Different strategies for different errors
  - Three-tier static validation before showing to user
  - Data flow analysis to verify execution order
  - Comprehensive error feedback for targeted fixes
  - More sophisticated and user-friendly

- [ ] **Option C: Fail fast with clear errors**
  - No retries, just clear error messages
  - Fastest but least helpful

### The Three-Tier Validation Pipeline:

**Implementation Note**: This validation is performed by a `ValidatorNode` within the planner flow. When validation fails, it returns actions like "validation_failed" that route back to the generator node with specific error feedback.

The planner uses a progressive static validation approach that catches issues at the earliest possible stage:

#### 1. **Syntactic Validation** (via Pydantic - see Section 7)
- Ensures well-formed JSON structure through Pydantic models
- Type-safe generation with `model.prompt(prompt, schema=FlowIR)`
- Immediate feedback on structural issues
- **Catches**: Malformed JSON, missing required fields, type mismatches

#### 2. **Static Analysis** (node and parameter validation)
- Verifies all referenced nodes exist in registry
- Checks parameter names and types match node metadata
- Validates template variable syntax
- Detects circular dependencies and unreachable nodes
- **Catches**: Unknown nodes, invalid parameters, structural issues

#### 3. **Data Flow Analysis** (execution order validation)
This is NOT mock execution - it's static analysis that tracks data flow through the workflow:

- **What it does**: Traverses nodes in execution order, tracking which keys are available in the shared store at each step
- **How it works**: Uses node metadata (inputs/outputs) to verify data dependencies are satisfied
- **Generic approach**: No per-node implementation needed - just uses the metadata from registry
- **Catches**: Missing inputs, overwritten outputs, unresolved template variables, invalid template paths

With structure documentation (Task 14), validation verifies template paths exist before execution.

**Example Data Flow Analysis Log**:
```
[Data Flow Analysis]
Node: github-get-issue
  Requires: issue_number ✓ (from CLI parameter)
  Produces: issue_data (with structure: {id, title, user: {login}, ...})

Node: claude-code
  Template: "Fix issue #$issue_data.id by $issue_data.user.login"
  Path validation: issue_data.id ✓, issue_data.user.login ✓
  Produces: code_report

Node: llm
  Template: "Write commit message for: $code_report"
  Path validation: code_report ✓
  Produces: commit_message

[Analysis Complete] ✓
All data dependencies satisfied
All template paths valid
No overwritten keys
```

### Integration with Error Recovery:

Each validation tier provides specific error information that guides recovery:

1. **Pydantic/Syntactic Errors** → Retry with format hints
   - "Expected 'nodes' array, got object"
   - "Missing required field 'type' in node"

2. **Static Analysis Errors** → Retry with specific fixes
   - "Node 'analyze-code' not found. Did you mean 'claude-code'?"
   - "Parameter 'temp' invalid. Did you mean 'temperature'?"
   - "Circular dependency: A → B → C → A"

3. **Data Flow Errors** → Retry with flow corrections
   - "Node 'llm' requires 'prompt' but no node produces it"
   - "Key 'summary' is written by multiple nodes"
   - "Template variable $code_report has no source"

### Error-Specific Recovery Strategies:

| Error Type | Recovery Strategy | Max Retries |
|------------|------------------|-------------|
| Malformed JSON | Add format example to prompt | 2 |
| Unknown node | Suggest similar nodes from registry | 3 |
| Missing data flow | Add hint about node outputs | 3 |
| Template unresolved | Show available variables | 2 |
| Circular dependency | Simplify to sequential flow | 1 |

### Planner Flow Implementation example:

The error recovery strategies above are implemented through pocketflow's action-based routing:

```python
# Planner flow structure with error handling
discovery_node >> generator_node >> validator_node >> approval_node

# Error recovery routes
generator_node - "malformed_json" >> generator_node  # Self-retry with hint
validator_node - "unknown_nodes" >> error_feedback >> generator_node
validator_node - "data_flow_error" >> error_feedback >> generator_node
validator_node - "success" >> approval_node

# Each node uses pocketflow's retry mechanism
class GeneratorNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=1.0)  # For LLM API failures
```

> Note: This example might differ from the actual implementation, but the idea is that the planner flow is a pocketflow flow with multiple nodes. See this as pseudo code code that will need heavy adaptation to the actual requirements.

**Recommendation**: Option B with three-tier static validation provides the best user experience. The validation is implemented as a node within the planner flow, using pocketflow's action-based routing to handle different validation outcomes. All three tiers are forms of static analysis with different focuses:
1. Structure (Pydantic)
2. Components (Static Analysis)
3. Data Flow (Data Flow Analysis)

This approach catches issues early without the complexity of runtime simulation, providing specific, actionable feedback for recovery.

## 10. Integration with Existing Context Builder - Decision importance (2)

How should the planner use the context builder from Task 16?

### The Ambiguity:
- Context builder outputs markdown - is this the right format?
- Should we modify the context builder output?
- How much context is too much?

### Options:

- [x] **Option A: Use context builder as-is**
  - Take markdown output directly
  - Include in LLM prompt unchanged
  - Simplest integration

- [ ] **Option B: Post-process context**
  - Convert markdown to structured format
  - Filter based on user intent
  - More optimal but more complex

- [ ] **Option C: Replace context builder**
  - Build context inline in planner
  - More control but duplicates code

**Recommendation**: Option A - Use existing context builder to avoid duplication.

## 11. MVP Feature Boundaries - Decision importance (5)

What exactly is in scope for the MVP planner?

### CRITICAL CLARIFICATION: System Layer vs User Layer

**This section defines boundaries for USER-FACING WORKFLOWS generated by the planner, NOT the planner's own implementation.** (since both are pocketflow workflows, making this clear is important to avoid confusion)

**System Layer (Planner Implementation)**:
- ✅ Uses full pocketflow features including action-based transitions
- ✅ Implements sophisticated error handling and retry logic
- ✅ Has validation feedback loops and conditional routing
- ✅ This is infrastructure code in Python using pocketflow patterns

**User Layer (Generated Workflows)**:
- ❓ What features can the generated JSON IR include?
- ❓ How complex can user workflows be?
- ❓ What's allowed vs deferred to v2.0?

### Critical Clarifications Needed:
1. **Action-based transitions**: Examples show them, but they're marked as v2.0
2. **Complex workflows**: How complex can MVP workflows be?
3. **Parameter types**: Just strings or full type support?
4. **Workflow modification**: Can users edit before saving?

### Options:

- [x] **Option A: Refined MVP scope for generated workflows**
  - **Allowed in generated workflows**:
    - Sequential node execution (A → B → C)
    - Template variables for reusability ($var syntax)
    - Basic parameter types (string, number, boolean, arrays)
    - Node-internal error handling (retries, fallbacks)
    - Complex sequential workflows (many nodes)
    - Path-based proxy mappings for data flow
    - Workflow composition (workflows using other workflows)

  - **Excluded from generated workflows**:
    - Action-based transitions between nodes (no branching)
    - Conditional workflow paths
    - Explicit error recovery branches in IR
    - Dynamic node selection based on runtime conditions
    - Parallel execution
    - User editing of generated workflows (just Y/n approval)
    - Custom node creation through planner

- [ ] **Option B: Include some v2.0 features**
  - Add simple branching
  - Support basic types
  - More useful but scope creep risk

**Recommendation**: Option A (Refined) - This provides a powerful MVP that can generate sophisticated sequential workflows while keeping implementation complexity manageable. The planner itself uses full pocketflow features internally, but limits generated workflows to sequential patterns.

## 12. Unified Discovery Pattern - Decision importance (5)

How should the planner discover both nodes and existing workflows?

### The Key Insight:
The context builder already solved this problem! We can use the same pattern for everything.

**UPDATE**: This pattern is being formalized by **Task 15: Extend context builder for two-phase discovery**, which splits the context builder into discovery and planning phases, preventing LLM overwhelm while enabling workflow reuse.

### Critical Refinements:
1. **Workflows ARE building blocks** - Other workflows can be used inside new workflows
2. **Two different contexts needed**:
   - **Discovery context**: Just names and descriptions (for finding what to use)
   - **Planning context**: Full interface details (only for selected nodes/workflows)
3. **Separation of concerns**: Discovery vs. implementation planning

### The Two-Phase Approach:

**Phase 1: Discovery Context (for finding nodes/workflows)**
```markdown
## Available Nodes

### github-get-issue
Fetches issue details from GitHub

### llm
General-purpose language model for text processing

### read-file
Reads content from a file

## Available Workflows (can be used as building blocks)

### fix-github-issue
Analyzes a GitHub issue and creates a PR with the fix

### analyze-error-logs
Reads log files and summarizes errors with recommendations
```

**Phase 2: Planning Context (only selected nodes/workflows)**
```markdown
## Selected Components

### github-get-issue
Fetches issue details from GitHub
**Inputs**: `issue_number`, `repo`
**Outputs**: `issue_data`, `issue_title`

### llm
General-purpose language model for text processing
**Inputs**: `prompt`
**Outputs**: `response`
**Parameters**: `model`, `temperature`
```

### Benefits:
1. **Workflows as first-class citizens** - Can compose workflows from other workflows
2. **Focused contexts** - Discovery gets minimal info, planning gets full details
3. **Performance** - Don't load full interface details for 100+ nodes during discovery
4. **Clarity** - LLM isn't overwhelmed with irrelevant interface details

### Implementation:
1. **Discovery phase** (via Task 15's `build_discovery_context()`):
   - Load all nodes (names + descriptions only)
   - Load all workflows (names + descriptions only)
   - LLM selects which to use
2. **Planning phase** (via Task 15's `build_planning_context(selected_components)`):
   - Load full details ONLY for selected nodes/workflows
   - LLM plans the shared store layout and connections
   - Generate IR with proper mappings

### Workflow Storage Format:
```json
{
  "name": "fix-github-issue",
  "description": "Analyzes a GitHub issue and creates a PR with the fix",
  "inputs": ["issue_number"],
  "outputs": ["pr_number"],
  "ir": { ... }  // The actual workflow IR
}
```

**Key Insight**: Workflows are just reusable node compositions - they should appear alongside nodes as building blocks!

## 13. JSON IR to CLI Syntax Relationship - Decision importance (4)

There's an implicit assumption that JSON IR can be "compiled" back to CLI syntax for user display, but this isn't straightforward.

### The Ambiguity:
- The planner generates JSON IR, but users need to see CLI syntax
- How do we convert complex JSON structures back to readable CLI commands?
- What about template variables in the display?

### Options:

- [ ] **Option A: Generate both JSON IR and CLI syntax**
  - Planner creates both formats
  - Ensures consistency
  - More complex prompting

- [x] **Option B: Compile JSON IR to CLI syntax**
  - Separate compiler step converts IR to CLI
  - Single source of truth (JSON IR)
  - Need to handle all IR features in CLI syntax

- [ ] **Option C: Show simplified CLI syntax**
  - Display only basic node chain
  - Hide complex details
  - Less informative for users

  more information in ## 8. IR to CLI syntax relationship

**Recommendation**: Option B - A separate IR-to-CLI compiler maintains separation of concerns and single source of truth. (see [8. IR to CLI syntax relationship](#13-json-ir-to-cli-syntax-relationship---decision-importance-4) for more information)

## 14. Planner Implementation Architecture - Decision importance (5)

How should the planner itself be implemented?

### Context

This decision goes to the heart of pflow's architectural philosophy and reveals a fundamental distinction in the system:

**The Two Layers of pflow:**
1. **User Layer**: Natural language → JSON IR → Saved workflows ("Plan Once, Run Forever")
2. **System Layer**: Infrastructure that enables the user layer

The planner sits firmly in the system layer. It's not a workflow that users discover with "find me a workflow that generates workflows" - it's the infrastructure that makes workflow generation possible.

**Why This Matters:**
- JSON IR is for **what users want to do** (their workflows)
- Python code is for **how the system works** (our infrastructure)
- The planner is "how", not "what"

**Pocketflow's Design Philosophy:**
According to pocketflow's "Agentic Coding" guide (`pocketflow/docs/guide.md`):
- Pocketflow is specifically designed to be **easy for AI agents to understand and modify**
- The framework provides clear patterns for system implementation
- Infrastructure components should follow the nodes.py + flow.py pattern

**The Meta Consideration:**
While it's intellectually appealing to use JSON IR to generate JSON IR (ultimate dogfooding), this would be using the wrong tool for the job. It's like trying to write a compiler in the language it compiles - possible but not practical for maintenance and debugging.

**Key References:**
- `pocketflow/docs/guide.md` - Shows the intended pattern for building systems
- `pocketflow/docs/core_abstraction/node.md` - Node design principles
- `docs/architecture/pflow-pocketflow-integration-guide.md` - Integration patterns
- The planner specification in `docs/features/planner.md` describes it as infrastructure

### The Decision

### Options:

- [ ] **Option A: JSON IR for the planner**
  - Ultimate dogfooding - use JSON IR to generate JSON IR
  - Intellectually elegant
  - **Problems**:
    - Bootstrap complexity (how do you generate the IR that generates IR?)
    - Debugging nightmare (debugging generated code that generates code)
    - Wrong abstraction level (JSON IR is for user workflows)
    - Against pocketflow's philosophy (guide shows Python for implementation)

- [x] **Option B: Python pocketflow code**
  - Planner written as nodes.py + flow.py
  - Follows pocketflow's "Agentic Coding" philosophy
  - Clear separation: System layer (Python) vs User layer (JSON IR)
  - Easy for AI agents to understand and modify (pocketflow is especially designed for this, see `pocketflow/docs/guide.md` for more details)
  - **Benefits**:
    - Direct debugging with Python tools
    - Version control shows meaningful diffs
    - Natural test writing
    - Follows established patterns
    - Comprehensive documentation available in the `pocketflow/` repo
    - Source just 100 lines of code and extremely easy to grasp for AI agents

- [ ] **Option C: Regular Python**
  - Just plain Python functions, no pocketflow
  - **Problems**:
    - Loses orchestration benefits
    - Harder to test individual components
    - Inconsistent with rest of system
    - Less clear structure for AI agents
    - No dogfooding

**Resolution**: Option B - The planner is infrastructure and belongs in the system layer as Python pocketflow code. This follows the framework's design philosophy perfectly and maintains proper architectural boundaries.

### Implementation Pattern

Following pocketflow's recommended structure:
```
src/pflow/planning/
├── nodes.py          # Planner nodes (discovery, generation, validation)
├── flow.py           # create_planner_flow()
├── ir_models.py      # Pydantic models for IR generation
├── utils/
│   ├── ir_utils.py   # IR manipulation utilities?
│   └── # More utils to be added as needed
└── prompts/
    └── templates.py  # Prompt templates
```

This structure:
- Follows the pattern shown in `pocketflow/docs/guide.md`
- Keeps planner logic organized and testable
- Makes it clear this is system infrastructure
- Enables AI agents to easily understand and modify the planner
- Separates Pydantic models for clean architecture

### Implementation with Pydantic Models

The planner will use a hybrid approach combining Pydantic's type safety with JSONSchema validation:

```python
# src/pflow/planning/ir_models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class NodeIR(BaseModel):
    """Node representation for IR generation."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    type: str = Field(..., description="Node type from registry")
    params: Dict[str, Any] = Field(default_factory=dict)

class EdgeIR(BaseModel):
    """Edge representation for IR generation."""
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    action: str = Field(default="default")

class FlowIR(BaseModel):
    """Flow IR for planner output generation."""
    ir_version: str = Field(default="0.1.0", pattern=r'^\d+\.\d+\.\d+$')
    nodes: List[NodeIR] = Field(..., min_items=1)
    edges: List[EdgeIR] = Field(default_factory=list)
    start_node: Optional[str] = None
    mappings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dict for validation with existing schema."""
        return self.model_dump(by_alias=True, exclude_none=True)

# src/pflow/planning/nodes.py
import llm
from pflow.core import validate_ir
from .ir_models import FlowIR

class WorkflowGeneratorNode(Node):
    def exec(self, shared, prep_res):
        model = llm.get_model("claude-sonnet-4-20250514")

        # Generate with Pydantic schema for type safety
        response = model.prompt(
            prompt=shared["planning_prompt"],
            schema=FlowIR,
            system="Generate a valid pflow workflow"
        )

        # Parse and convert to dict
        flow_dict = json.loads(response.text())

        # Validate with existing JSONSchema
        validate_ir(flow_dict)

        return flow_dict
```

This hybrid approach:
- Uses Pydantic for structured output generation with the LLM
- Validates the final result with JSONSchema for comprehensive checking
- Maintains compatibility with the existing validation system
- Provides type safety during development

## 15. Testing Strategy for LLM Components - Decision importance (4)

Testing LLM-based components requires special consideration due to their non-deterministic nature.

### Context:
- LLM outputs vary between runs
- Need to test success rate metrics (≥95% target)
- API calls are expensive during testing
- Must validate both syntactic correctness and semantic appropriateness

### Options:

- [ ] **Option A: Mock all LLM calls**
  - All tests use pre-recorded responses
  - Pros: Fast, deterministic, free
  - Cons: Doesn't test actual LLM behavior or prompt effectiveness
  - Implementation: Fixtures with expected responses

- [ ] **Option B: Real LLM calls with test budget**
  - All tests use actual LLM API
  - Pros: Real validation of prompts and outputs
  - Cons: Expensive, slow, non-deterministic
  - Implementation: Separate test API keys with spending limits

- [x] **Option C: Hybrid approach with separate LLM test commands**
  - Unit tests: Mock all LLM calls for component testing
  - Integration tests with mocked LLM: Run with `make test` (no cost)
  - Integration tests with real LLM: Separate command (costs money)
  - Pros: Balanced coverage, cost control, CI/CD friendly
  - Cons: More complex test setup
  - Implementation:
    - Mock LLM responses for all standard tests
    - Create mocked integration test that simulates full planner flow
    - Separate `make test-llm` command for real LLM integration test
    - Real LLM test validates basic workflow generation only
    - Extensive prompt evaluation deferred to v2.0
    - Always test the planner's internal LLM node (all LLM calls through pocketflow)

**Recommendation**: Option C - Separates costly LLM tests from regular test suite. Only the planner integration test uses real LLM, and it runs via separate command to control costs.

## 16. Batch Mode vs Interactive Mode - Decision importance (2)

The planner needs to handle both interactive terminal sessions and automated/CI environments differently.

### Context:
- Interactive mode: User at terminal, can respond to prompts
- Batch mode: Scripts, CI/CD, automated execution
- Missing parameters need different handling strategies

### The Clarification:

**Interactive Mode** (default):
- TTY detection shows user at terminal
- Can prompt for missing parameters
- Shows progress indicators
- Allows Y/n approval prompts
- Example: `pflow "fix github issue"` → "What issue number?"

**Batch Mode** (--batch flag or no TTY):
- No user interaction possible
- Missing parameters cause immediate failure
- No progress indicators (clean output)
- Auto-approve with --yes flag or fail
- Example: `pflow --batch "fix issue"` → ERROR: Missing issue parameter

### Implementation:
```python
# Detect mode
interactive = sys.stdin.isatty() and not args.batch

# Handle missing parameters
if param_missing:
    if interactive:
        param = prompt_user(f"Enter {param_name}: ")
    else:
        raise MissingParameterError(f"Batch mode: {param_name} required")
```

**MVP Scope**: Basic batch mode support with --batch flag and TTY detection. Full CI/CD optimizations deferred to v2.0.

**Implications for task 17**: No modifications to the CLI should be made, the task 17 implementation will ONLY provide the interfaces the the CLI-layer needs to interact with the planner. Keep it simple.

## 17. CLI Input Routing to Planner - Decision importance (3)

How the planner receives input from the CLI needs clarification, especially given the MVP's approach.

### Context:
- MVP routes all input through natural language planner (both quoted and unquoted)
- CLI collects raw string after 'pflow' command
- Planner must handle both natural language and CLI-like syntax

### Options:

- [x] **Option A: CLI passes raw string directly to planner**
  - Raw input string passed unchanged to planner
  - No parsing or preprocessing in CLI
  - Maximum flexibility for planner
  - Aligns with MVP philosophy
  - Implementation: `main.py` passes entire input string to planner

- [ ] **Option B: CLI does minimal pre-processing**
  - CLI detects quotes, operators, then passes structured data
  - Cleaner separation but duplicates logic
  - Against MVP principle of unified processing

- [ ] **Option C: CLI provides hints with raw string**
  - Pass both raw string and metadata
  - More complex for marginal benefit

**Recommendation**: Option A - Keep CLI simple, pass raw string directly. This aligns with documentation stating MVP routes everything through the LLM planner.

## 18. Parameter vs Static Value Detection - Decision importance (4)

The planner must decide which values in natural language should become parameters (reusable) vs static values (fixed).

### Context:
- Example: "fix issue 1234" - should "1234" be parameterized as `$issue`?
- Affects reusability of saved workflows
- Critical for "Plan Once, Run Forever" philosophy

### Options:

- [ ] **Option A: Explicit user annotation**
  - User marks what should be variable
  - Most accurate but poor UX
  - Requires user understanding of templates

- [x] **Option B: LLM-based heuristic detection**
  - LLM intelligently detects what should be parameters
  - Smart defaults based on context and patterns
  - Numbers, IDs, URLs, dates typically become parameters
  - Implementation: Prompt engineering guides LLM decisions

- [ ] **Option C: Make everything parameters**
  - Maximum flexibility but overwhelming
  - Creates overly complex workflows

**Recommendation**: Option B - Leverage LLM's intelligence to make smart parameter decisions. This follows the planner's philosophy as an LLM-powered system.

## Critical Next Steps

1. ~~**Clarify template variable resolution**~~ - ✅ RESOLVED: Runtime resolution with path support (Option B + paths)
2. **Implement path support in template variables** - Simple ~20 line addition to enable `$data.field.subfield`
3. ~~**Decide on workflow storage format**~~ - ✅ RESOLVED: Use simple JSON with name, description, inputs, outputs, and IR
4. ~~**Design discovery mechanism**~~ - ✅ RESOLVED: Two-phase approach with context builder
5. **Confirm MVP boundaries** - Especially regarding action-based transitions (Sequential workflows only, no branching)
6. **Design concrete prompt templates** - With examples of expected outputs
7. **Create test scenarios** - Cover all edge cases identified above
8. **Implement two context builder functions**:
   - `build_discovery_context()` - Lightweight descriptions only
   - `build_planning_context(selected)` - Full details for selected components
9. **Simplify prompt templates** - Focus on template paths instead of complex mappings
10. **Adapt validation for template paths** - Verify paths exist in structure documentation
11. **No proxy mapping implementation** - Entirely deferred to v2.0
12. **Update test scenarios** - Focus on template path patterns
13. **Implement path support in template variables** - ~20 line addition per Section 2
14. **Design prompt templates** that emphasize template paths usage
15. **Create validation** that checks paths exist in structure documentation
16. **Test scenarios** focused on template path patterns

## Implementation Recommendations

Based on this analysis, here's the recommended approach:

1. **Use Option B with path support** - Runtime resolution with `$data.field` syntax
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
- [ ] Use template variables (`$data`) and template variables withpaths (`$data.field.subfield`) per Section 2
- [ ] Workflows can use other workflows as building blocks
- [ ] Planner is infrastructure (Python pocketflow), not user workflow (JSON IR)
- [ ] Generated workflows are sequential only (no branching)
- [ ] Two-phase context (discovery vs planning) prevents LLM overwhelm
- [ ] Template variables ≠ CLI parameters (runtime resolution vs execution args)
- [ ] Planner can use full pocketflow features, but generated workflows are sequential only (MVP)

### Key Implementation Simplifications:
- No separate discovery system needed - reuse context builder pattern
- Workflows are reusable building blocks alongside nodes
- Two-phase approach: discovery (descriptions only) → planning (full details)
- The LLM prompt structure:
  - Discovery: "Here are available nodes and workflows. Which should we use?"
  - Planning: "Here are the selected components' interfaces. Plan the connections."

### Context Builder Evolution:
1. **build_discovery_context()** - Names and descriptions only (implemented in Task 15)
2. **build_planning_context(selected_components)** - Full interface details for selected items only (implemented in Task 15)

This separation prevents information overload and improves LLM performance. Task 15 provides exactly this two-phase approach, including workflow discovery support and structure documentation that shows available paths for template variables.

## Risks and Mitigations

1. **Risk**: Template variable complexity
   - **Mitigation**: Start with simple $variable substitution, enhance later

2. **Risk**: LLM generates invalid workflows
   - **Mitigation**: Strong validation with retry loop and error feedback

3. **Risk**: Discovery doesn't find relevant workflows
   - **Mitigation**: Good workflow naming and description conventions

4. **Risk**: Scope creep with "just one more feature"
   - **Mitigation**: Strict MVP checklist, defer everything else

This analysis should provide the clarity needed to begin implementation of Task 17.

## Context Gathering Update (2025-07-19)

After thorough investigation of the codebase and documentation, I've discovered the following:

### 1. Context Builder Implementation (Task 15/16)
- Task 16 created the initial context builder
- Task 15 enhanced it with two-phase discovery support
- **build_discovery_context()**: Lightweight browsing with names/descriptions only
- **build_planning_context()**: Detailed interface info for selected components
- Workflow loading from `~/.pflow/workflows/` is already implemented
- Structure documentation (JSON + paths) shows available paths for template variables

### 2. Template Variable Resolution Confirmed
Documentation has been updated to confirm template variables are preserved in JSON IR and resolved at runtime. This enables the "Plan Once, Run Forever" philosophy where workflows can be reused with different parameters.

### 3. CLI Integration Status
- CLI accepts natural language (quoted) and CLI syntax (unquoted)
- Both currently echo back the input (planner not integrated yet)
- JSON workflows can be executed if valid IR provided
- Stdin data handling is implemented

### 4. Runtime Integration
- Compiler takes JSON IR and creates pocketflow Flow objects
- Supports node instantiation, parameter setting, and edge wiring
- Ready to execute flows generated by the planner

### 5. Key Architectural Clarifications
From planner.md:
- Planner is implemented as a pocketflow flow (not regular Python)
- MVP routes BOTH natural language and CLI syntax through LLM planner
- Template string composition is a core planner responsibility
- Workflows can use other workflows as building blocks

### 6. Implementation Architecture Confirmed
The planner will be implemented as Python pocketflow code:
```
src/pflow/planning/
├── nodes.py          # Planner nodes (discovery, generation, validation)
├── flow.py           # create_planner_flow()
├── ir_models.py      # Pydantic models for IR generation
├── utils/
└── prompts/
    └── templates.py  # Prompt templates
```

### 7. Testing Strategy
- Unit tests: Mock LLM calls for component testing
- Integration tests: Real LLM for critical paths
- MVP validation suite: 10-20 common patterns
- Test planners internal LLM node (all LLM calls through pocketflow)

### Summary
The investigation confirms the architectural decisions in this document are correct. Template variables will be preserved in JSON IR for runtime resolution, enabling workflow reusability. The two-phase context builder is ready, and the planner should be implemented as a pocketflow flow using the pattern established in Option B (Section 14).

## How It All Fits Together: The Complete Planner Pipeline

The planner combines all these decisions into a cohesive workflow generation system:

1. **Input Processing**: Natural language → intent + parameter extraction
2. **Discovery Phase**: Context builder provides nodes + workflows → LLM selects components
3. **Generation Phase**:
   - Pydantic models ensure syntactically valid JSON
   - Template paths for data access (see Section 2)
   - Structure documentation shows available paths
4. **Validation Phase**:
   - Static analysis catches structural issues
   - Verifies template paths exist in structure docs
   - Specific error feedback for invalid paths
5. **Presentation**: Natural CLI syntax showing template paths
6. **Storage**: Workflows saved with template variables for reusability

This architecture ensures that every generated workflow is not only syntactically correct but also semantically valid and ready for execution.
