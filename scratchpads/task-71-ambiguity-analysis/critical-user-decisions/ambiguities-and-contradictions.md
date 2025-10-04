# Task 71: Ambiguities and Contradictions Analysis

**Date**: 2025-10-02
**Analyst**: Claude (using Epistemic Manifesto principles)
**Purpose**: Surface ALL ambiguities, contradictions, and unclear decisions in Task 71 documentation

---

## Analysis Methodology

Following the Epistemic Manifesto:
1. **Assume documentation may be incomplete or wrong**
2. **Ambiguity is a STOP signal**
3. **Verify assumptions against code**
4. **Surface unknowns explicitly**
5. **What would have to be true for this to work reliably under change?**

---

## CRITICAL AMBIGUITIES IDENTIFIED

### 1. Error Enhancement Architecture - Implementation Location Ambiguity (Severity: 5)

**The Contradiction**:

**ERROR_FLOW_ANALYSIS.md says** (lines 207-242):
```python
# ADD to _extract_error_from_shared()
if "response" in shared:
    error["raw_response"] = shared["response"]
```

**VERIFIED_RESEARCH_FINDINGS.md reveals** (lines 21-32):
```
_extract_error_from_shared() DOES NOT EXIST
Actual function: _build_error_list() at line 218
```

**IMPLEMENTATION_REFERENCE.md Step 0 says** (lines 418-475):
```python
# Update _build_error_list() (lines 218-249)
# Add enhancements AFTER line 248
```

**The Ambiguity**:
Which approach is correct?
- Option A: Modify `_build_error_list()` directly (single-function modification)
- Option B: Create new helper `_enhance_error_with_rich_data()` (extract to helper)
- Option C: Modify one of the 5 existing helper methods

**What's unclear**:
1. Should we add logic directly to `_build_error_list()` after line 248?
2. Should we create a new helper function and call it?
3. Which of the 5 helpers should be modified if we're not adding to _build_error_list?
4. Does the enhancement need to happen in multiple places (e.g., both `_extract_node_level_error()` AND `_build_error_list()`)?

**Impact if wrong**:
- Modifying wrong function → rich data not captured
- Adding to wrong location → data already discarded by earlier extraction
- Multiple modification points → maintenance burden and bugs

**Context**:
```python
# Current architecture (VERIFIED_RESEARCH_FINDINGS.md lines 24-32):
1. _build_error_list()              # Main entry - constructs error dict
2. _extract_error_info()            # Message and node extraction
3. _extract_root_level_error()      # Root-level errors
4. _extract_node_level_error()      # Node-level errors (WHERE response MIGHT BE)
5. _extract_error_from_mcp_result() # MCP parsing
```

**Options**:

- [ ] **Option A: Single-point enhancement in _build_error_list()** (IMPLEMENTATION_REFERENCE.md approach)
  - **Pros**:
    - Centralized location
    - All error types enhanced consistently
    - Simpler to maintain
    - Clear single modification point
  - **Cons**:
    - `shared` store might already be pruned by helpers
    - May not have access to node-specific data
    - Assumes all rich data still available at line 248
  - **Assumption**: Rich error data (response, result) still exists in `shared` when `_build_error_list()` executes

- [ ] **Option B: Create new helper `_enhance_error_with_rich_data()`** (VERIFIED_RESEARCH_FINDINGS.md suggestion)
  - **Pros**:
    - Separation of concerns
    - Testable in isolation
    - Doesn't bloat existing function
    - Easier to extend in future
  - **Cons**:
    - Additional function to maintain
    - Slightly more complex call chain
    - Need to determine correct parameters
  - **Assumption**: Helper can access all needed data from `shared` and `failed_node`

- [ ] **Option C: Modify `_extract_node_level_error()` where data exists**
  - **Pros**:
    - Data definitely available (at extraction point)
    - Closest to source of truth
    - No risk of pruned data
  - **Cons**:
    - Would need to return richer dict structure
    - Changes signature/contract
    - May not cover all error types (what about root-level?)
  - **Assumption**: All rich error data passes through `_extract_node_level_error()`

**Recommendation**: **Option B with verification** - Create `_enhance_error_with_rich_data()` helper called from `_build_error_list()` after line 248, BUT:

1. **VERIFY FIRST** that `shared` store still contains:
   - `shared["response"]` for HTTP nodes
   - `shared[node_id]["result"]` for MCP nodes
   - At the point `_build_error_list()` executes (line 248)

2. **If data is pruned by that point**: Fall back to Option C - modify extraction helpers to preserve rich data

3. **Test with failing workflow** to confirm data availability

**Why this recommendation**:
- Follows existing architecture (helpers called from main function)
- Testable and maintainable
- Can be extended easily
- BUT contingent on data availability verification

---

### 2. --validate-only Parameter Requirements - Contradiction (Severity: 4)

**The Contradiction**:

**CLI_COMMANDS_SPEC.md says** (line 183):
```
- Validation must check schema, templates, compilation, and runtime
- Template resolution validates with partial params
```

**VERIFIED_RESEARCH_FINDINGS.md Section 3 says** (lines 128-170):
```
ValidatorNode requires ALL required parameters
If required workflow input missing → validation fails
This is intentional - validation means FULL validation, not partial
```

**TEST_CRITERIA in task-71-spec.md says** (line 284):
```
7. workflow validate requires all required parameters (fails if missing required inputs)
```

**IMPLEMENTATION_REFERENCE.md Step 4 says** (line 243):
```python
# NOTE: ValidatorNode requires ALL required parameters
# If workflow has required inputs not provided in params, validation will fail
# This is intentional - validation means FULL validation, not partial
```

**The Ambiguity**:
The docs say "validates with partial params" but verification proves "requires ALL required parameters".

**What's unclear**:
1. Is partial validation supported or not?
2. What does "partial params" mean in CLI_COMMANDS_SPEC?
3. Should agents provide all params even for validation?
4. What's the UX when required param is missing?

**Impact if wrong**:
- Agents waste time providing all params for validation
- OR validation fails unexpectedly without all params
- Confusing error messages

**Options**:

- [ ] **Option A: Require all params (current ValidatorNode behavior)**
  - **Reasoning**:
    - Matches actual code behavior (VERIFIED)
    - Validation = "can this execute?" → needs all params
    - Clear, predictable behavior
    - Agent knows exactly what to provide
  - **UX**: `pflow --validate-only workflow.json repo=owner/repo pr=123`
  - **Error if missing**: "Required parameter 'X' not provided for validation"

- [ ] **Option B: Make params optional for validation**
  - **Reasoning**:
    - Validate schema/structure without full execution readiness
    - Faster iteration (validate before gathering params)
    - Agents can check workflow before param discovery
  - **UX**: `pflow --validate-only workflow.json` (no params needed)
  - **Would require**: Modifying ValidatorNode to skip template validation if params not provided
  - **Breaking change**: Changes ValidatorNode contract

**Recommendation**: **Option A** - Require all params, fix documentation

**Why**:
1. Matches verified code behavior (no changes needed)
2. Validation means "ready to execute" = needs all inputs
3. Partial validation is less useful (can't catch template errors)
4. Agents can use `registry describe` to discover params first
5. Clear error messages guide agents to provide params

**Documentation fixes needed**:
- Remove "validates with partial params" from CLI_COMMANDS_SPEC.md
- Update to "requires all required parameters for full validation"
- AGENT_INSTRUCTIONS.md should emphasize: "validation requires same params as execution"

---

### 3. MetadataGenerationNode Input Expectations - Clarification Needed (Severity: 3)

**The Documentation**:

**IMPLEMENTATION_REFERENCE.md Section 5 says** (lines 352-365):
```python
# Add --generate-metadata and --delete-draft options
if generate_metadata:
    from pflow.planning.nodes import MetadataGenerationNode
    node = MetadataGenerationNode()
    shared = {"validated_workflow": validated_ir}  # Uses "validated_workflow"
    node.run(shared)
    metadata = shared.get("workflow_metadata", {})
```

**VERIFIED_RESEARCH_FINDINGS.md Section 4 says** (lines 173-223):
```python
# Input requirements (prep() lines 2459-2483):
return {
    "workflow": shared.get("generated_workflow", {}),  # Uses "generated_workflow"
    "user_input": shared.get("user_input", ""),
}
```

**task-71.md says** (line 157):
```
Note on --generate-metadata: Research confirmed MetadataGenerationNode only needs
raw workflow IR, NOT ValidatorNode-specific output.
```

**The Ambiguity**:
Which key should we use in the shared store?
- `"validated_workflow"` (IMPLEMENTATION_REFERENCE says)
- `"generated_workflow"` (actual code expects per VERIFIED_RESEARCH)

**What's unclear**:
1. Does the key name matter or does MetadataGenerationNode look for both?
2. Is "validated_workflow" a typo or intentional distinction?
3. Should we call validate_ir() before passing to MetadataGenerationNode?

**Impact if wrong**:
- MetadataGenerationNode receives empty workflow dict
- Metadata generation silently fails
- No rich metadata created

**Context from code** (VERIFIED_RESEARCH_FINDINGS.md lines 184-189):
```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow": shared.get("generated_workflow", {}),  # ONLY looks for "generated_workflow"
        "user_input": shared.get("user_input", ""),
    }
```

**Options**:

- [ ] **Option A: Use "generated_workflow" (match actual code)**
  - **Reasoning**: Code explicitly looks for this key
  - **Safe**: Verified to work
  - **Consistent**: Matches planner's usage
  - **Code**:
    ```python
    shared = {
        "generated_workflow": validated_ir,
        "user_input": "",
        "cache_planner": False,
    }
    ```

- [ ] **Option B: Use "validated_workflow" (documentation preference)**
  - **Reasoning**: Semantically clearer (we DID validate it)
  - **Risk**: If MetadataGenerationNode only checks "generated_workflow" → fails
  - **Would need**: Code verification or MetadataGenerationNode modification

**Recommendation**: **Option A** - Use "generated_workflow"

**Why**:
1. **Trust the code** (Epistemic Manifesto: code reveals truth)
2. Verified in VERIFIED_RESEARCH_FINDINGS.md
3. No risk of failure
4. Can always add both keys if semantic clarity desired:
   ```python
   workflow_ir = validated_ir
   shared = {
       "generated_workflow": workflow_ir,  # What code expects
       "validated_workflow": workflow_ir,  # Semantic clarity (unused)
   }
   ```

**Documentation fix needed**:
- Update IMPLEMENTATION_REFERENCE.md line 360 to use "generated_workflow"
- Add comment: `# MetadataGenerationNode expects "generated_workflow" key`

---

### 4. Workflow Name Validation - CLI vs WorkflowManager Confusion (Severity: 3)

**The Specification**:

**CLI_COMMANDS_SPEC.md says** (lines 309-319):
```python
# Validate name format
if not re.match(r'^[a-z0-9-]+$', name):
    click.echo(f"Error: Name must be lowercase with hyphens only", err=True)

if len(name) > 30:
    click.echo(f"Error: Name must be 30 characters or less", err=True)
```

**IMPLEMENTATION_REFERENCE.md says** (lines 313-320):
```python
# Pattern: lowercase letters, numbers, and hyphens only (agent-friendly)
# Max: 30 characters (WorkflowManager allows 50)
# Rationale: Shell-safe, URL-safe, git-branch-compatible names for agents
if not re.match(r'^[a-z0-9-]+$', name):
    # ...
if len(name) > 30:
    # ...
```

**VERIFIED_RESEARCH_FINDINGS.md Section 6 says** (lines 269-298):
```python
# WorkflowManager pattern: ^[a-zA-Z0-9._-]+$
# Max length: 50 characters
# CLI can add stricter rules: YES - CLI validates first, WorkflowManager provides backup.
```

**The Ambiguity**:
Why have TWO different validation rules? What happens if they conflict?

**What's unclear**:
1. **Decision rationale**: Why 30 chars in CLI vs 50 in WorkflowManager?
2. **Character sets**: Why exclude uppercase/dots/underscores in CLI?
3. **Failure modes**: What if CLI allows something WorkflowManager rejects?
4. **Backward compat**: Can users bypass CLI and call WorkflowManager directly?
5. **Future evolution**: Will we need to sync these rules?

**Impact if wrong**:
- Users confused by different limits in different contexts
- CLI accepts name that WorkflowManager rejects
- Inconsistent behavior across interfaces (CLI vs MCP vs Python API)
- Documentation shows one limit, code enforces another

**Current State**:
```
CLI validation:        ^[a-z0-9-]+$        max 30 chars   (strict)
WorkflowManager:       ^[a-zA-Z0-9._-]+$   max 50 chars   (permissive)
```

**Options**:

- [ ] **Option A: Keep dual validation (strict CLI, permissive WM)**
  - **Pros**:
    - CLI guides agents to safe names
    - WorkflowManager allows broader usage from Python API
    - Flexibility for different use cases
  - **Cons**:
    - Confusing different limits
    - Maintenance burden (keep in sync)
    - CLI can't access workflows with uppercase/dots (if created via API)
  - **Rationale given**: "agent-friendly", "shell-safe", "git-branch-compatible"

- [ ] **Option B: Make WorkflowManager match CLI (both strict)**
  - **Pros**:
    - Single source of truth
    - Consistent across all interfaces
    - Simpler mental model
  - **Cons**:
    - **Breaking change** for existing workflows with uppercase/dots
    - Reduces flexibility
    - May affect existing users
  - **Risk**: HIGH - breaks backward compatibility

- [ ] **Option C: Make CLI match WorkflowManager (both permissive)**
  - **Pros**:
    - Maximum flexibility
    - No artificial CLI restrictions
    - Agents can use full character set
  - **Cons**:
    - Loses "shell-safe" guarantee
    - Dots in names might confuse shell/URLs
    - Uppercase in names not as agent-friendly
  - **Risk**: MEDIUM - less restrictive for agents

- [ ] **Option D: Document the difference clearly**
  - **Pros**:
    - No code changes needed
    - Acknowledges two valid use cases
    - CLI "recommends" safe names, WM "allows" broader set
  - **Cons**:
    - Complexity persists
    - Confusion persists
  - **Fix**: Clear documentation of WHY two rules exist

**Recommendation**: **Option A + D** - Keep dual validation BUT document it clearly

**Why**:
1. **Rationale is sound**: CLI targets agents (need shell-safe names), WM supports broader Python API usage
2. **No breaking changes**: Preserves backward compatibility
3. **Defense in depth**: CLI provides guidance, WM provides safety net
4. **Clear separation**: CLI = opinionated defaults, WM = permissive library

**Documentation fixes needed**:

1. **In AGENT_INSTRUCTIONS.md**, add section:
   ```markdown
   ## Workflow Naming Conventions

   The CLI enforces agent-friendly naming:
   - Pattern: `^[a-z0-9-]+$` (lowercase, numbers, hyphens only)
   - Max length: 30 characters
   - Examples: `my-workflow`, `pr-analyzer-v2`

   **Why these restrictions?**
   - Shell-safe: No escaping needed in bash/zsh
   - URL-safe: Works in web interfaces without encoding
   - Git-friendly: Compatible with branch naming

   **Note**: WorkflowManager (Python API) allows broader names
   (uppercase, dots, underscores, up to 50 chars) for advanced use cases.
   ```

2. **In CLI_COMMANDS_SPEC.md**, add clarification:
   ```markdown
   **CLI Validation** (stricter, agent-friendly):
   - Pattern: ^[a-z0-9-]+$
   - Max: 30 characters
   - Rationale: Shell-safe, URL-safe, git-branch-compatible

   **WorkflowManager Validation** (permissive backup):
   - Pattern: ^[a-zA-Z0-9._-]+$
   - Max: 50 characters
   - Rationale: Supports broader Python API usage
   ```

3. **In workflow save command help**:
   ```python
   @click.argument('name')  # Add help
   """Workflow name (lowercase, numbers, hyphens only, max 30 chars).
   Examples: 'my-workflow', 'pr-analyzer'"""
   ```

**Remaining Question**: Should `workflow save --force` bypass CLI validation?
- **Answer**: No - force only bypasses "already exists" check, NOT name validation
- **Reasoning**: Name validation is about correctness, not conflicts

---

### 5. Error Display - What if `result` is None? (Severity: 2)

**The Code Pattern**:

**IMPLEMENTATION_REFERENCE.md Step 1 says** (lines 481-492):
```python
def _handle_workflow_error(
    ctx: click.Context,
    result: ExecutionResult | None,  # CAN BE NONE
    # ...
):
```

**Step 2 says** (lines 496-570):
```python
if result and result.errors:  # Checks for None
    for error in result.errors:
        # Display rich errors
else:
    # Fallback to original generic message
    click.echo(f"cli: Workflow execution failed...", err=True)
```

**The Ambiguity**:
When would `result` be None? What scenarios lead to this?

**What's unclear**:
1. Can execution fail with `result=None`?
2. What error conditions produce None vs empty errors list?
3. Is the fallback message sufficient for None case?
4. Should we differentiate None (catastrophic failure) vs empty errors (unexpected state)?

**Impact if wrong**:
- Unhelpful error message for certain failures
- Agents can't diagnose catastrophic errors
- Loss of error information

**Scenarios to consider**:

| Scenario | result value | result.errors | What user sees |
|----------|-------------|---------------|----------------|
| Normal execution success | ExecutionResult | [] | Success output |
| Node returns error action | ExecutionResult | [{...}] | Rich error details |
| Template resolution fails | ExecutionResult | [{...}] | Rich error details |
| **Catastrophic failure?** | None | N/A | Generic fallback |
| Compilation error | ? | ? | ? |
| Invalid workflow IR | ? | ? | ? |

**Options**:

- [ ] **Option A: Current fallback is sufficient**
  - **Reasoning**: Rare edge case, generic message okay
  - **Risk**: Agents get no actionable info

- [ ] **Option B: Enhance fallback to check other sources**
  - **Reasoning**: There might be error info elsewhere (shared_storage?)
  - **Code**:
    ```python
    if result and result.errors:
        # Display rich errors
    elif result:
        # Execution failed but no errors captured
        click.echo("Workflow execution failed without error details", err=True)
        click.echo("This may indicate a compilation or system error", err=True)
    else:
        # No result object at all
        click.echo("Workflow execution failed catastrophically", err=True)
        if shared_storage and "__execution__" in shared_storage:
            # Try to extract what we can
            exec_info = shared_storage["__execution__"]
            click.echo(f"Failed at: {exec_info.get('failed_node', 'unknown')}", err=True)
    ```

- [ ] **Option C: Investigate when result can be None**
  - **Action**: Search codebase for `ExecutionResult` creation
  - **Verify**: All execution paths return ExecutionResult (even on failure)
  - **If always exists**: Make parameter non-optional `result: ExecutionResult`

**Recommendation**: **Option C first, then A or B based on findings**

**Why**:
1. **Verify assumption**: Is None actually possible?
2. **If not possible**: Remove Optional, simplify code
3. **If possible**: Determine what scenarios and add specific handling

**Action needed**:
- Search for `ExecutionResult` creation in `executor_service.py`
- Trace all return paths to verify None is possible/impossible
- Update signature and handling based on evidence

---

### 6. Registry Discover Output - When to Use Planning Context vs Browsing Context (Severity: 2)

**The Specification**:

**CLI_COMMANDS_SPEC.md Section 2 says** (lines 104-111):
```python
# ComponentBrowsingNode returns two things:
shared["browsed_components"]  # Selected node IDs
shared["planning_context"]    # Full interface details

# Display planning context
if "planning_context" in shared:
    click.echo(shared["planning_context"])
```

**IMPLEMENTATION_REFERENCE.md Section 2 says** (lines 99-134):
```python
action = node.run(shared)

# Access results
browsed_components = shared['browsed_components']
planning_context = shared['planning_context']  # Full interface details (markdown)
```

**COMPLETE_RESEARCH_FINDINGS.md says** (lines 90-106):
```python
### build_nodes_context()
- Returns: Lightweight numbered list for browsing
- Format: "1. node-id - Description"
- Use Case: LLM selection in ComponentBrowsingNode

### build_planning_context()
- Returns: FULL interface documentation
- Format: Complete inputs, outputs, parameters with types
- Use Case: Detailed node specifications
```

**The Ambiguity**:
ComponentBrowsingNode ALREADY builds planning context internally. But `registry describe` command ALSO uses `build_planning_context()`.

**What's unclear**:
1. Does `registry discover` show the SAME output as `registry describe [selected-nodes]`?
2. If yes, why have both commands?
3. If no, what's the difference?
4. Should we use browsing context (lightweight) for discover and planning context for describe?

**Impact if wrong**:
- Redundant commands with same output
- Confusing UX (when to use which?)
- Wasted implementation effort

**Current Design**:
```
registry discover "query"
  → ComponentBrowsingNode
  → LLM selects relevant nodes
  → Returns shared["planning_context"]  ← FULL details

registry describe node1 node2
  → build_planning_context(["node1", "node2"])
  → Returns FULL details ← SAME as above?
```

**Options**:

- [ ] **Option A: Different outputs (lightweight vs detailed)**
  - **discover**: Show browsing context (node list with descriptions)
  - **describe**: Show planning context (full interface specs)
  - **Rationale**: discover = overview, describe = deep dive
  - **Code change**:
    ```python
    # registry discover
    if "browsed_components" in shared:
        node_ids = shared["browsed_components"]["node_ids"]
        context = build_nodes_context(node_ids, registry_metadata)
        click.echo(context)
    ```

- [ ] **Option B: Same output (both show full details)**
  - **discover**: Agent describes need, gets full specs of relevant nodes
  - **describe**: Agent requests specific nodes, gets full specs
  - **Rationale**: Agents need complete info in both cases
  - **No code change** - current design works
  - **UX**: discover = filtered, describe = explicit

- [ ] **Option C: Merge commands**
  - **Single command**: `registry search` with both query and explicit IDs
  - **Usage**: `registry search "query"` OR `registry search node1 node2`
  - **Rationale**: Simpler interface, less duplication
  - **Code**: Detect query vs IDs, route accordingly

**Recommendation**: **Option B** - Keep both with full details

**Why**:
1. **Different workflows**:
   - `discover`: "I need to do X, what nodes exist?" → LLM helps
   - `describe`: "Tell me about nodes A, B, C" → Direct lookup
2. **Agents need full info**: Lightweight list insufficient for building workflows
3. **Complementary**: Discover finds, describe verifies/expands
4. **Already implemented**: ComponentBrowsingNode returns planning context

**Documentation clarity needed**:

In AGENT_INSTRUCTIONS.md, add:
```markdown
## Discovery Commands Comparison

**When to use `registry discover`**:
- You have a task description: "I need to fetch GitHub data and analyze it"
- You want LLM to select relevant nodes
- You don't know exact node names
- Returns: Full interface details for selected nodes (3-5 typically)

**When to use `registry describe`**:
- You know exact node IDs: `github-get-pr`, `llm`
- You want specs for specific nodes
- No LLM filtering needed
- Returns: Full interface details for requested nodes (exact matches)

**Both return complete interface specifications** - the difference is HOW nodes are selected.
```

---

### 7. Enhanced Error Output - HTTP vs MCP Data Structures (Severity: 2)

**The Implementation**:

**ERROR_FLOW_ANALYSIS.md shows** (lines 23-83):
```python
# HTTP Node stores:
shared["response"] = response_json  # Full API response
shared["status_code"] = response.status_code

# Example GitHub error:
{
  "message": "Validation Failed",
  "errors": [{"field": "assignees", "code": "invalid", ...}],
  "documentation_url": "..."
}

# MCP Node stores:
shared[node_id]["result"] = result  # Complete MCP response

# Example MCP error:
{
  "error": {
    "code": "invalid_blocks",
    "message": "...",
    "details": {"field": "assignee", ...}
  }
}
```

**IMPLEMENTATION_REFERENCE.md Step 0 says** (lines 454-473):
```python
# Capture raw HTTP responses
if "response" in shared:
    error["raw_response"] = shared["response"]

# Capture MCP error details
if failed_node and failed_node in shared:
    node_data = shared[failed_node]
    if isinstance(node_data, dict):
        if "result" in node_data:
            if "error" in node_data["result"]:
                error["mcp_error"] = node_data["result"]["error"]
```

**The Ambiguity**:
The data structures are inconsistent:
- HTTP: Response at root level `shared["response"]`
- MCP: Response nested under node ID `shared[node_id]["result"]`

**What's unclear**:
1. Will BOTH patterns work in all error scenarios?
2. Do HTTP nodes also store under `shared[node_id]`?
3. What if we have multiple failed nodes (is that possible)?
4. Should we check BOTH root and node-namespaced locations?

**Impact if wrong**:
- Miss capturing errors from some node types
- Incomplete error enhancement
- Agents don't see all available error details

**Questions to verify**:
1. Do HTTP nodes ONLY write to root, or also to namespaced store?
2. Can errors occur in nodes that don't follow either pattern?
3. What about shell nodes? Do they have different error structures?

**Options**:

- [ ] **Option A: Check both root and namespaced (defensive)**
  - **Code**:
    ```python
    # Try root level first (HTTP pattern)
    if "response" in shared:
        error["raw_response"] = shared["response"]
        if "status_code" in shared:
            error["status_code"] = shared["status_code"]

    # Also check namespaced (MCP pattern + HTTP might be here too)
    if failed_node and failed_node in shared:
        node_data = shared[failed_node]
        if isinstance(node_data, dict):
            # MCP error
            if "result" in node_data and isinstance(node_data["result"], dict):
                if "error" in node_data["result"]:
                    error["mcp_error"] = node_data["result"]["error"]

            # HTTP might also be namespaced
            if "response" in node_data and "raw_response" not in error:
                error["raw_response"] = node_data["response"]
                if "status_code" in node_data:
                    error["status_code"] = node_data["status_code"]
    ```
  - **Pros**: Catches all patterns, defensive coding
  - **Cons**: More complex, potential duplication

- [ ] **Option B: Current implementation (trust HTTP root, MCP namespaced)**
  - **Pros**: Simpler, matches documented behavior
  - **Cons**: May miss edge cases
  - **Risk**: Medium - relies on assumption about storage patterns

- [ ] **Option C: Investigate actual storage patterns first**
  - **Action**:
    1. Check `src/pflow/nodes/http/http.py` - where does it store response?
    2. Check `src/pflow/nodes/mcp/node.py` - where does it store result?
    3. Check `src/pflow/runtime/namespaced_wrapper.py` - does it affect storage?
    4. Verify with actual failing workflow traces
  - **Then**: Implement based on evidence

**Recommendation**: **Option C** - Investigate storage patterns BEFORE implementing

**Why**:
1. **Epistemic Manifesto**: "Trust the code, not assumptions"
2. **Risk mitigation**: Wrong assumption = missing errors
3. **15 min investigation** prevents days of debugging later

**Action needed**:
```bash
# Check HTTP node storage
grep -n 'shared\["response"\]' src/pflow/nodes/http/http.py
grep -n 'shared\[.*\]\["response"\]' src/pflow/nodes/http/http.py

# Check MCP node storage
grep -n 'shared\[.*\]\["result"\]' src/pflow/nodes/mcp/node.py
grep -n 'shared\["result"\]' src/pflow/nodes/mcp/node.py

# Check if namespacing affects this
grep -n "namespaced" src/pflow/runtime/namespaced_wrapper.py
```

**If investigation shows**:
- HTTP stores at root only → Use Option B (current)
- HTTP stores namespaced too → Use Option A (defensive)
- Mixed patterns → Use Option A + document the patterns

---

## MEDIUM PRIORITY AMBIGUITIES

### 8. Workflow Discovery Confidence Score - Display Format (Severity: 2)

**Current Spec**:
```python
confidence = result.get('confidence', 0)
click.echo(f"**Confidence**: {confidence:.0%}")  # Shows as percentage
```

**Questions**:
1. Is confidence 0-1 float or 0-100 int from LLM?
2. Should we show "95%" or "0.95"?
3. What if confidence is very low (< 50%) - should we warn?
4. Should we sort multiple results by confidence?

**Options**:
- [ ] A: Show as percentage (current): `95%`
- [ ] B: Show as decimal: `0.95`
- [ ] C: Show both: `95% (0.95)`
- [ ] D: Add threshold warning: `95% (strong match)` vs `30% (weak match)`

**Recommendation**: **Option A with threshold** - Show percentage, add warning if <70%

**Why**: Percentages more intuitive, threshold helps agents decide if match is useful

---

### 9. Delete Draft Behavior - Safety Considerations (Severity: 2)

**Current Spec**:
```python
if delete_draft:
    try:
        Path(file_path).unlink()
        click.echo(f"✓ Deleted draft: {file_path}")
    except Exception as e:
        click.echo(f"Warning: Could not delete draft: {e}", err=True)
```

**Questions**:
1. Should we confirm before deleting?
2. What if file is outside `.pflow/workflows/`?
3. Should we refuse to delete if not in draft location?
4. What if save failed but we still try to delete?

**Safety Scenarios**:
| Scenario | Current Behavior | Risk |
|----------|-----------------|------|
| Save succeeds, delete fails | Warning shown, file remains | Low |
| Save fails, delete attempted | Depends on code flow | **HIGH** - may delete before save confirmed |
| File is outside .pflow/ | Deleted if writable | **MEDIUM** - unexpected deletion |
| File is important (not draft) | Deleted if --delete-draft used | **HIGH** - data loss |

**Options**:
- [ ] A: Current (delete if save succeeds)
- [ ] B: Add path validation (only delete if in .pflow/)
- [ ] C: Add confirmation prompt
- [ ] D: B + C (validate path AND confirm)

**Recommendation**: **Option B** - Validate path is in `.pflow/workflows/` before deletion

**Code**:
```python
if delete_draft:
    file_path_obj = Path(file_path).resolve()
    draft_dir = Path.cwd() / ".pflow" / "workflows"

    if not file_path_obj.is_relative_to(draft_dir):
        click.echo(f"Warning: File not in draft directory, skipping deletion", err=True)
        click.echo(f"  File: {file_path}")
        click.echo(f"  Expected in: {draft_dir}")
    else:
        try:
            file_path_obj.unlink()
            click.echo(f"✓ Deleted draft: {file_path}")
        except Exception as e:
            click.echo(f"Warning: Could not delete draft: {e}", err=True)
```

**Why**: Prevents accidental deletion of files outside draft directory, no UX disruption (automatic validation)

---

### 10. Node Discovery Empty Results - UX (Severity: 1)

**Current Spec**:
```python
else:
    click.echo("No relevant nodes found.")
    click.echo("\nTip: Try a more specific query or use 'pflow registry list'")
```

**Questions**:
1. Should we show similar nodes anyway (partial matches)?
2. Should we suggest related queries?
3. Should we show top N nodes regardless of relevance?
4. What if LLM fails (not empty results, but error)?

**Options**:
- [ ] A: Current (just message + tip)
- [ ] B: Show top 5 nodes anyway with "These might help"
- [ ] C: Suggest query refinements based on input
- [ ] D: Fall back to keyword search if LLM returns nothing

**Recommendation**: **Option A** - Keep simple, clear

**Why**: Empty results means query too vague or no match. Showing random nodes unhelpful. Agent should refine query or use `registry list`.

---

## DOCUMENTATION CONSISTENCY ISSUES

### 11. Function Naming Inconsistencies

**VERIFIED_RESEARCH_FINDINGS.md found**:
- Docs say `_extract_error_from_shared()` - DOES NOT EXIST
- Actual function: `_build_error_list()`

**Action**: Update all docs to use correct function name

---

### 12. Shared Store Key Naming

**Inconsistency**:
- Some docs: `"validated_workflow"`
- Code expects: `"generated_workflow"`

**Action**: Standardize on `"generated_workflow"` to match code

---

## CRITICAL QUESTIONS FOR USER

Based on epistemic analysis, these questions MUST be answered before implementation:

1. **Error Enhancement Architecture** (Ambiguity #1):
   - Should we modify `_build_error_list()` directly or create helper?
   - Need to VERIFY data availability first

2. **Validation Parameter Requirements** (Ambiguity #2):
   - Confirm: Validation requires ALL parameters (no partial validation)?
   - Update docs to match this behavior?

3. **Workflow Naming** (Ambiguity #4):
   - Confirm dual validation (CLI strict, WM permissive) is intentional?
   - Document the reasoning clearly?

4. **Delete Draft Safety** (Ambiguity #9):
   - Should we validate file is in .pflow/ before deletion?
   - Add this safety check?

5. **Error Data Storage Patterns** (Ambiguity #7):
   - INVESTIGATE: Where do HTTP/MCP nodes actually store error data?
   - Then decide on extraction approach

---

## RECOMMENDATIONS SUMMARY

### High Confidence Recommendations (Clear Best Option)
1. ✅ Use `"generated_workflow"` key for MetadataGenerationNode (Ambiguity #3)
2. ✅ Keep dual validation for workflow names with clear docs (Ambiguity #4)
3. ✅ Keep both discover and describe commands - different use cases (Ambiguity #6)
4. ✅ Validate path before delete-draft (Ambiguity #9)

### Needs Investigation Before Deciding
1. 🔍 Error enhancement approach - verify data availability first (Ambiguity #1)
2. 🔍 HTTP/MCP error storage patterns - check code first (Ambiguity #7)
3. 🔍 When is ExecutionResult None - trace code paths (Ambiguity #5)

### Needs User Decision
1. ❓ Validation parameter requirements - confirm no partial validation (Ambiguity #2)
2. ❓ Confidence score display format - percentage + threshold? (Ambiguity #8)

---

## NEXT STEPS

1. **User confirms** critical decisions above
2. **Investigation tasks** executed (data patterns, None scenarios)
3. **Documentation updated** with corrections and clarifications
4. **Implementation** proceeds with verified architecture
