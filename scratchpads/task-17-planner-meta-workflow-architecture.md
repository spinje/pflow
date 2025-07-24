# The Natural Language Planner Meta-Workflow Architecture

## Executive Summary

The Natural Language Planner is a **meta-workflow** - a PocketFlow workflow that orchestrates the entire lifecycle of finding or creating workflows based on user intent. It implements two distinct paths that converge at a critical parameter extraction and verification point.

## The Complete Architecture

```mermaid
graph TD
    START[User: "fix github issue 1234"] --> WD[WorkflowDiscoveryNode]

    WD --> CHECK{Complete workflow exists?}

    CHECK -->|YES: Found 'fix-issue'| FOUND_PATH[Path A: Reuse Existing]
    CHECK -->|NO: Must create| CREATE_PATH[Path B: Generate New]

    %% Path A: Direct reuse
    FOUND_PATH --> PE[ParameterExtractionNode<br/>Extract: "1234" → issue_number<br/>Verify: All params available?]

    %% Path B: Generation
    CREATE_PATH --> CB[ComponentBrowsingNode<br/>Find building blocks:<br/>nodes + sub-workflows]
    CB --> GEN[GeneratorNode<br/>LLM creates workflow<br/>Designs params: $issue_number]
    GEN --> VAL[ValidatorNode<br/>Validate IR structure]
    VAL -->|invalid| GEN
    VAL -->|valid| PE

    %% Convergence point
    PE --> VERIFY{Can map user input<br/>to workflow params?}
    VERIFY -->|YES| PP[ParameterPreparationNode<br/>Format for execution]
    VERIFY -->|NO| ERROR[Cannot Execute:<br/>Missing required params]

    PP --> RES[ResultPreparationNode<br/>Package for CLI]
    RES --> END[Return to CLI]

    style PE fill:#9ff,stroke:#333,stroke-width:4px
    style VERIFY fill:#ff9,stroke:#333,stroke-width:3px
    style WD fill:#f9f,stroke:#333,stroke-width:4px
```

## The Two Paths in Detail

### Path A: Reuse Existing Workflow (Fast Path)

This path is taken when a complete workflow already exists that can satisfy the user's entire intent.

**Flow:**
1. **WorkflowDiscoveryNode** searches saved workflows
2. If found → jump directly to **ParameterExtractionNode**
3. Extract parameters and verify executability
4. Package for CLI execution

**Example:**
```
User: "fix github issue 1234"
↓
WorkflowDiscoveryNode: Found 'fix-issue' workflow
↓
ParameterExtractionNode: Extract {issue_number: "1234"}
↓
Verify: ✓ All required params satisfied
↓
Ready to execute
```

### Path B: Generate New Workflow (Creation Path)

This path is taken when no existing workflow can satisfy the complete intent.

**Flow:**
1. **WorkflowDiscoveryNode** finds no complete match
2. **ComponentBrowsingNode** finds building blocks (nodes + sub-workflows)
3. **GeneratorNode** creates new workflow using LLM
4. **ValidatorNode** ensures IR correctness
5. Converge to **ParameterExtractionNode**
6. Extract parameters and verify executability
7. Package for CLI execution

**Example:**
```
User: "analyze youtube comments for sentiment"
↓
WorkflowDiscoveryNode: No complete match found
↓
ComponentBrowsingNode: Found yt-comments, llm nodes
↓
GeneratorNode: Creates workflow with params: {video_url: "$url"}
↓
ValidatorNode: ✓ Valid IR
↓
ParameterExtractionNode: ✗ Cannot extract URL from user input!
↓
Error: Missing required parameter 'url'
```

## Node Responsibilities

### 1. WorkflowDiscoveryNode
**Purpose**: Find workflows that can satisfy the ENTIRE user intent as-is

**Key Questions**:
- "Would executing this workflow achieve what the user wants?"
- "Is this a complete solution?"

**Implementation**:
```python
class WorkflowDiscoveryNode(Node):
    """Find complete workflow solutions."""
    def exec(self, shared):
        user_input = shared["user_input"]
        saved_workflows = self._load_saved_workflows()  # From ~/.pflow/workflows/

        # Use LLM to find exact matches
        prompt = f"""
        User wants to: {user_input}

        Available workflows:
        {self._format_workflows(saved_workflows)}

        Which workflow (if any) would completely satisfy this request?
        Return the workflow name or 'none' if no complete match.
        """

        match = self.llm.complete(prompt)
        if match != 'none':
            shared["found_workflow"] = saved_workflows[match]
            return "found_existing"
        else:
            return "not_found"
```

### 2. ComponentBrowsingNode
**Purpose**: Find building blocks for creating NEW workflows

**Key Points**:
- Only executes if no complete workflow found
- Finds both nodes AND workflows (as potential sub-components)
- Uses two-step context building for efficiency

**Implementation**:
```python
class ComponentBrowsingNode(Node):
    """Browse for components to build new workflows."""
    def exec(self, shared):
        # Step 1: Lightweight browse
        discovery_context = build_discovery_context()

        components = self._browse_for_building_blocks(
            shared["user_input"],
            discovery_context
        )

        # Step 2: Get details for selected components only
        planning_context = build_planning_context(
            components["node_ids"],
            components["workflow_names"]  # Sub-workflows!
        )

        shared["planning_context"] = planning_context
        return "generate"
```

### 3. GeneratorNode
**Purpose**: Create new workflow using building blocks

**Critical Behavior**:
- Designs the parameter interface (`$variables`)
- Uses template variables for reusability
- May compose multiple workflows as sub-components

### 4. ValidatorNode
**Purpose**: Ensure generated workflow is structurally valid

**Validation Includes**:
- IR schema compliance
- Node existence in registry
- Valid edges and connections
- Template variable syntax

### 5. ParameterExtractionNode (Convergence Point)
**Purpose**: Extract parameters AND verify workflow executability

**This is the critical verification gate:**
```python
class ParameterExtractionNode(Node):
    """Extract parameters and verify execution feasibility."""
    def exec(self, shared):
        user_input = shared["user_input"]  # Original query
        workflow = shared.get("found_workflow") or shared.get("generated_workflow")

        # Extract concrete values
        extracted = self._extract_from_natural_language(user_input, workflow)
        # Example: {"issue_number": "1234"} from "fix github issue 1234"

        # CRITICAL: Verify all required params are available
        required = self._get_required_params(workflow)
        missing = required - set(extracted.keys())

        if missing:
            shared["missing_params"] = missing
            return "params_incomplete"

        shared["extracted_params"] = extracted
        return "params_complete"
```

### 6. ParameterPreparationNode
**Purpose**: Format extracted parameters for execution

**Responsibilities**:
- Package parameter values for CLI
- Prepare for runtime template substitution
- No complex mappings (runtime proxy handles this)

### 7. ResultPreparationNode
**Purpose**: Package everything for CLI handoff

**Output Structure**:
```python
{
    "workflow_ir": {...},          # Complete IR with $variables
    "workflow_metadata": {...},     # Name, description, etc.
    "parameter_values": {...}       # Extracted from user input
}
```

## Critical Architectural Principles

### 1. Workflows are Dual-Purpose
- **Complete Solutions**: Found by WorkflowDiscoveryNode for direct execution
- **Building Blocks**: Found by ComponentBrowsingNode for composition

### 2. Parameter Work Happens Twice (Different Purposes)
- **During Generation**: LLM designs what parameters the workflow needs
- **During Extraction**: System verifies we can satisfy those parameters

### 3. The Verification Gate
ParameterExtractionNode is NOT just extraction - it's the execution feasibility check:
- Can we get all required values from the user's input?
- If not, execution cannot proceed
- This prevents attempting to run incomplete workflows

### 4. Context Building Efficiency
- **Discovery Context**: Lightweight (names + descriptions only)
- **Planning Context**: Detailed (full interfaces, but only for selected items)

## Example Execution Traces

### Example 1: Successful Reuse
```
User Input: "fix github issue 1234"

1. WorkflowDiscoveryNode
   - Searches saved workflows
   - Finds: 'fix-issue' workflow
   - Returns: "found_existing"

2. ParameterExtractionNode
   - Workflow needs: {issue_number}
   - Extracts: {issue_number: "1234"}
   - Verification: ✓ All params satisfied
   - Returns: "params_complete"

3. ParameterPreparationNode
   - Formats for execution

4. ResultPreparationNode
   - Packages for CLI

Result: Ready to execute 'fix-issue' with issue_number=1234
```

### Example 2: Generation Required
```
User Input: "analyze this week's support tickets"

1. WorkflowDiscoveryNode
   - Searches saved workflows
   - No exact match found
   - Returns: "not_found"

2. ComponentBrowsingNode
   - Finds: support-ticket-reader, date-filter, llm nodes
   - Loads detailed context

3. GeneratorNode
   - Creates workflow with params:
     - $start_date
     - $end_date
     - $analysis_type

4. ValidatorNode
   - Validates IR structure
   - Returns: "valid"

5. ParameterExtractionNode
   - Interprets "this week" → date range
   - Extracts: {
       start_date: "2024-01-15",
       end_date: "2024-01-21",
       analysis_type: "support"
     }
   - Verification: ✓ All params satisfied
   - Returns: "params_complete"

Result: New workflow created and ready to execute
```

### Example 3: Parameter Verification Failure
```
User Input: "deploy the app"

1. WorkflowDiscoveryNode
   - Finds: 'deploy-application' workflow
   - Returns: "found_existing"

2. ParameterExtractionNode
   - Workflow needs: {app_name, environment, version}
   - Can extract: {} (nothing specific in user input!)
   - Verification: ✗ Missing required params
   - Returns: "params_incomplete"

Result: Cannot execute - must prompt for missing parameters
```

## Why This Architecture Works

### 1. Efficiency Through Fast Path
- Try reuse first (fast)
- Only generate if necessary (slower)

### 2. Verification Prevents Failures
- Don't attempt execution without all parameters
- Catch problems early

### 3. Clear Separation of Concerns
- Discovery finds complete solutions
- Browsing finds building blocks
- Generation creates new solutions
- Extraction verifies executability

### 4. Unified Parameter Handling
- Both paths converge at the same verification point
- Consistent parameter extraction regardless of path

## Implementation Considerations

### State Management
The planner uses PocketFlow's shared dict to maintain state across nodes:
```python
shared = {
    # Input
    "user_input": "fix github issue 1234",

    # Path A state
    "found_workflow": {...},

    # Path B state
    "planning_context": "...",
    "generated_workflow": {...},

    # Convergence state
    "extracted_params": {"issue_number": "1234"},

    # Output
    "planner_output": {...}
}
```

### Error Handling
Each node can return error states that route appropriately:
- `not_found` → try generation path
- `invalid` → retry generation
- `params_incomplete` → cannot execute

### Performance Optimization
- Workflow discovery should be fast (simple search + LLM call)
- Component browsing can be slower (only when needed)
- Cache frequently used workflows for faster discovery

## Summary

The Natural Language Planner is a sophisticated meta-workflow that:
1. Attempts fast reuse of existing workflows
2. Falls back to intelligent generation when needed
3. Always verifies executability before returning
4. Maintains clear separation between finding complete solutions vs. building blocks
5. Uses parameter extraction as a critical verification gate

This architecture ensures reliable, efficient workflow discovery and creation while maintaining the "Plan Once, Run Forever" philosophy through template variables and verification.

## Unified Discovery Pattern Implementation

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
