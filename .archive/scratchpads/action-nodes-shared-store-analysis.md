# Critical Analysis: Action-Based Nodes and Shared Store Patterns

*This document examines potential problems with the proposed action-based node architecture, particularly focusing on shared store usage patterns.*

---

## Problem 1: Input/Output Key Collisions

### The Issue

Different actions within the same node might use the same shared store keys but with different meanings:

```python
class GitHubNode(Node):
    """
    Actions:
      search-issues:
        Inputs: query (str), repo (str)
        Outputs: issues (list)

      get-issue:
        Inputs: repo (str), issue (int)
        Outputs: issue_data (dict)

      create-issue:
        Inputs: repo (str), title (str), body (str)
        Outputs: issue_data (dict)
    """
```

**Problem**: Both `get-issue` and `create-issue` write to `issue_data`, but the content might be different. If these are chained in a flow, data gets overwritten.

### Example Flow Demonstrating the Problem

```python
# User wants to: Get an issue, then create a related issue
shared = {
    "repo": "owner/repo",
    "issue": 123,
    "title": "Follow-up issue",
    "body": "Related to #123"
}

# Step 1: Get issue #123
github_get = GitHubNode()
github_get.set_params({"action": "get-issue"})
github_get.run(shared)
# shared["issue_data"] now contains data for issue #123

# Step 2: Create new issue
github_create = GitHubNode()
github_create.set_params({"action": "create-issue"})
github_create.run(shared)
# shared["issue_data"] now contains data for the NEW issue
# Original issue data is lost!
```

## Problem 2: Action-Specific Input Requirements

### The Issue

The current `prep()` method extracts ALL inputs defined in the schema, but what if some inputs should be action-specific parameters instead?

```python
def prep(self, shared):
    action = self.params.get("action")
    schema = self.get_action_schema(action)

    # This extracts from shared store
    inputs = {}
    for key in schema["inputs"]:
        if key in shared:
            inputs[key] = shared[key]

    # But what if "format" should come from CLI params, not shared store?
    # github --action=get-issue --format=json
```

### Example Confusion

```bash
# User expectation:
pflow github --action=get-issue --repo=owner/repo --issue=123 --format=json

# But our current design expects:
echo '{"repo": "owner/repo", "issue": 123, "format": "json"}' | pflow github --action=get-issue
```

## Problem 3: Natural Key Naming Conflicts

### The Issue

Natural naming leads to conflicts when composing flows:

```python
# Both nodes naturally want to use "content" as output
markdown_node.run(shared)  # writes shared["content"] = markdown_text
html_node.run(shared)      # writes shared["content"] = html_text
# Markdown content is lost!
```

## Problem 4: Static vs Dynamic Interface Declaration

### The Issue

Our metadata declares static interfaces, but actual behavior might be dynamic:

```python
class GitHubNode(Node):
    def post(self, shared, prep_res, exec_res):
        action = self.params.get("action")

        if action == "search-issues":
            # Might return 0, 1, or many issues
            if len(exec_res) == 0:
                return "no_results"
            elif len(exec_res) == 1:
                shared["issue"] = exec_res[0]
                return "single_result"
            else:
                shared["issues"] = exec_res
                return "multiple_results"
```

How do we declare this in static metadata?

## Exploring Solutions

### Solution A: Namespaced Keys (Verbose but Safe)

```python
class GitHubNode(Node):
    def post(self, shared, prep_res, exec_res):
        action = self.params.get("action")

        # Namespace outputs by action
        if action == "get-issue":
            shared["github.get_issue.result"] = exec_res
        elif action == "create-issue":
            shared["github.create_issue.result"] = exec_res
```

**Problems**:
- Loses natural interface beauty
- Complex key names in flows
- Against pflow philosophy

### Solution B: Action-Specific Shared Stores (Complex)

```python
class ActionAwareSharedStore:
    def __init__(self):
        self.global_store = {}
        self.action_stores = {}

    def get_action_store(self, node_id, action):
        key = f"{node_id}.{action}"
        if key not in self.action_stores:
            self.action_stores[key] = {}
        return self.action_stores[key]
```

**Problems**:
- Adds complexity to shared store
- Breaks simplicity principle
- How do nodes access data from other actions?

### Solution C: Explicit Input/Output Mapping (Current Approach Extended)

Keep natural keys but use proxy mappings for composition:

```python
# Flow IR with explicit mappings
{
  "nodes": [
    {
      "id": "get-original",
      "registry_id": "github",
      "params": {"action": "get-issue"}
    },
    {
      "id": "create-followup",
      "registry_id": "github",
      "params": {"action": "create-issue"}
    }
  ],
  "mappings": {
    "get-original": {
      "output_mappings": {"issue_data": "original_issue"}
    },
    "create-followup": {
      "input_mappings": {"title": "new_title", "body": "new_body"},
      "output_mappings": {"issue_data": "created_issue"}
    }
  }
}
```

**This is already in the architecture!** But we need to ensure it works well with actions.

## Solution D: Rethinking Action-Based Nodes (Hybrid Approach)

Perhaps the answer is to be more selective about when to use action-based nodes:

### Pattern 1: Simple Focused Nodes (Original pflow Vision)
```python
class GitHubGetIssueNode(Node):
    """Get a single GitHub issue.

    Interface:
    - Reads: shared["repo"], shared["issue_number"]
    - Writes: shared["issue"]
    """
```

### Pattern 2: Platform Nodes for Related Operations
```python
class GitHubSearchNode(Node):
    """Search GitHub using various criteria.

    Interface:
    - Reads: shared["query"], shared["search_type"]
    - Writes: shared["results"]
    - Params: type (issues|prs|code|users)
    """
```

### Pattern 3: Action-Based Only for MCP Wrappers
```python
class McpGitHubNode(Node):
    """Auto-generated wrapper for GitHub MCP server."""
    # Action-based because we're wrapping an external service
```

## Critical Insight: The Real Problem

After analysis, the core issue isn't with action-based nodes themselves, but with **how we think about shared store keys in the context of actions**.

### Current Thinking (Problematic)
"Each action has its own inputs/outputs that map to shared store keys"

### Better Thinking
"The node has a consistent interface, and actions are internal implementation details"

## Proposed Solution: Consistent Node Interfaces

### Design Principle
**Nodes should have consistent shared store interfaces regardless of internal actions.**

### Implementation Pattern

```python
class GitHubNode(Node):
    """GitHub operations with consistent interface.

    Interface:
    - Reads:
        shared["github_operation"] - what to do (get_issue, create_issue, search)
        shared["github_params"] - operation-specific parameters
    - Writes:
        shared["github_result"] - operation result
        shared["github_error"] - error details if failed
    - Actions: success, error, not_found, rate_limited
    """

    def prep(self, shared):
        operation = self.params.get("action")  # From CLI
        if not operation:
            operation = shared.get("github_operation")  # From flow

        # Get parameters either from shared["github_params"] or directly from shared
        if "github_params" in shared:
            params = shared["github_params"]
        else:
            # Backward compatibility: look for specific keys
            params = self._extract_params_for_operation(operation, shared)

        return operation, params

    def exec(self, prep_res):
        operation, params = prep_res

        if operation == "get_issue":
            return self._get_issue(params["repo"], params["issue"])
        elif operation == "create_issue":
            return self._create_issue(params["repo"], params["title"], params["body"])
        # etc.

    def post(self, shared, prep_res, exec_res):
        if isinstance(exec_res, Exception):
            shared["github_error"] = str(exec_res)
            return "error"

        shared["github_result"] = exec_res
        return "success"
```

### Usage Examples

#### CLI Usage (Natural)
```bash
pflow github --action=get-issue --repo=owner/repo --issue=123
```

#### Flow Composition (Clean)
```python
# Flow that gets an issue and creates a follow-up
shared = {
    "github_params": {
        "repo": "owner/repo",
        "issue": 123
    }
}

# Step 1: Get original issue
get_issue = GitHubNode()
get_issue.set_params({"action": "get_issue"})
get_issue.run(shared)
original = shared["github_result"]

# Step 2: Create follow-up
shared["github_params"] = {
    "repo": "owner/repo",
    "title": f"Follow-up to #{original['number']}",
    "body": f"Related to #{original['number']}: {original['title']}"
}
create_issue = GitHubNode()
create_issue.set_params({"action": "create_issue"})
create_issue.run(shared)
new_issue = shared["github_result"]
```

## But Wait... This Breaks Natural Interfaces!

The above solution makes interfaces less natural. Let's try another approach:

## Final Solution: Action Nodes with Contextual Interfaces

### Key Insight
**Actions can have different interfaces, but they must be explicit about their context.**

### Implementation

```python
class GitHubNode(Node):
    """GitHub platform operations.

    Actions determine the interface:

    get-issue:
      Reads: shared["repo"], shared["issue_number"]
      Writes: shared["issue"]

    create-issue:
      Reads: shared["repo"], shared["title"], shared["body"]
      Writes: shared["created_issue"], shared["issue_url"]

    search-issues:
      Reads: shared["query"], shared["repo"] (optional)
      Writes: shared["search_results"]
    """

    # Define DISTINCT output keys per action
    ACTION_OUTPUTS = {
        "get-issue": {"issue": "issue"},
        "create-issue": {"issue": "created_issue", "url": "issue_url"},
        "search-issues": {"results": "search_results"}
    }

    def post(self, shared, prep_res, exec_res):
        action = self.params.get("action")
        outputs = self.ACTION_OUTPUTS[action]

        if isinstance(exec_res, dict):
            for internal_key, shared_key in outputs.items():
                if internal_key in exec_res:
                    shared[shared_key] = exec_res[internal_key]
        else:
            # Single output
            first_shared_key = list(outputs.values())[0]
            shared[first_shared_key] = exec_res

        return "default"
```

### This Solves Our Problems!

1. **No Key Collisions**: Different actions write to different keys
2. **Natural Interfaces**: Keys still make sense in context
3. **Clear Documentation**: Each action's interface is explicit
4. **Flow Composition**: No data overwrites

### Example Flow (Working Correctly)

```python
# Get an issue and create a follow-up
shared = {
    "repo": "owner/repo",
    "issue_number": 123
}

# Step 1: Get original issue
get_node = GitHubNode()
get_node.set_params({"action": "get-issue"})
get_node.run(shared)
# shared["issue"] contains original issue

# Step 2: Create follow-up
shared["title"] = f"Follow-up to #{shared['issue']['number']}"
shared["body"] = f"Related to: {shared['issue']['title']}"

create_node = GitHubNode()
create_node.set_params({"action": "create-issue"})
create_node.run(shared)
# shared["created_issue"] contains new issue
# shared["issue"] still contains original issue!
```

## Conclusion: Best Practices for Action-Based Nodes

1. **Each action should write to distinct keys** to avoid collisions
2. **Document interfaces per action** in docstrings
3. **Use descriptive key names** that indicate context (e.g., "created_issue" vs just "issue")
4. **Consider if actions are necessary** - sometimes separate nodes are clearer
5. **Parameters vs Inputs**:
   - CLI flags → node parameters
   - Shared store → node inputs
   - Don't mix the two!

## Recommended Architecture Pattern

```python
class PlatformNode(Node):
    """Platform operations with action dispatch.

    Design principles:
    1. Each action has distinct input/output keys
    2. Natural naming within action context
    3. No key collisions between actions
    4. Clear documentation per action
    """

    @abstractmethod
    def get_action_interfaces(self) -> Dict[str, ActionInterface]:
        """Define interfaces for each action."""
        pass

    def prep(self, shared):
        action = self.params.get("action")
        interface = self.get_action_interfaces()[action]

        # Extract only what this action needs
        inputs = {}
        for key in interface.inputs:
            if key in shared:
                inputs[key] = shared[key]
            elif interface.is_required(key):
                raise ValueError(f"Missing required input: {key}")

        return inputs

    def post(self, shared, prep_res, exec_res):
        action = self.params.get("action")
        interface = self.get_action_interfaces()[action]

        # Write to action-specific keys
        for internal, external in interface.output_mapping.items():
            if internal in exec_res:
                shared[external] = exec_res[internal]

        return "default"
```

This pattern provides the best balance of:
- Natural interfaces
- No key collisions
- Clear action separation
- MCP compatibility
- Flow composition safety

## Alternative: Embrace Simple Nodes?

After all this analysis, we should ask: **Are action-based nodes the right choice?**

### Option 1: Simple Focused Nodes (Original Vision)

```python
# Instead of one GitHubNode with actions, have:
class GitHubGetIssueNode(Node):
    """Get GitHub issue details.

    Interface:
    - Reads: shared["repo"], shared["issue_number"]
    - Writes: shared["issue"]
    """

class GitHubCreateIssueNode(Node):
    """Create GitHub issue.

    Interface:
    - Reads: shared["repo"], shared["title"], shared["body"]
    - Writes: shared["created_issue"], shared["issue_url"]
    """

class GitHubSearchIssuesNode(Node):
    """Search GitHub issues.

    Interface:
    - Reads: shared["query"], shared["repo"] (optional)
    - Writes: shared["search_results"]
    """
```

**Pros:**
- Crystal clear interfaces
- No action dispatch complexity
- Each node does one thing well
- No key collision concerns
- Easier to test and understand

**Cons:**
- More nodes to manage (30+ vs 6)
- Naming can get verbose
- Less alignment with MCP pattern

### Option 2: Hybrid Approach

Use action-based nodes ONLY for:
1. **MCP wrappers** (where tools naturally map to actions)
2. **True platform operations** (where actions share significant code)

Use simple nodes for:
1. **Core operations** (read_file, transform, prompt)
2. **Distinct functionalities** (even if same platform)

### The Verdict: Context-Dependent Architecture

```python
# MCP Wrapper: Action-based makes sense
class McpGitHubNode(Node):
    """Auto-generated from MCP server."""
    # Actions map 1:1 to MCP tools

# Platform with shared logic: Action-based makes sense
class LLMNode(Node):
    """LLM operations with different modes.

    Actions:
    - complete: Simple completion
    - chat: Chat conversation
    - analyze: Structured analysis
    """
    # All actions share auth, rate limiting, etc.

# Distinct operations: Simple nodes better
class ReadFileNode(Node):
    """Read file contents."""

class WriteFileNode(Node):
    """Write file contents."""

# NOT FileNode with read/write actions!
```

## Final Recommendations

### 1. When to Use Action-Based Nodes

✅ **Use when:**
- Wrapping MCP servers (natural tool mapping)
- Actions share significant implementation (auth, connections, parsing)
- Platform naturally has "modes" of operation
- Reducing cognitive load is worth the complexity

❌ **Avoid when:**
- Actions have completely different interfaces
- No shared implementation logic
- Key collision risk is high
- Simplicity is more important than grouping

### 2. If Using Action-Based Nodes

**Must follow these rules:**

1. **Distinct Output Keys**: Each action writes to different keys
   ```python
   "get-issue": writes to shared["issue"]
   "create-issue": writes to shared["created_issue"]  # NOT shared["issue"]!
   ```

2. **Clear Interface Documentation**: Per-action in docstring
   ```python
   """
   Actions:
     get-issue:
       Reads: shared["repo"], shared["issue_number"]
       Writes: shared["issue"]
   """
   ```

3. **Parameter vs Input Clarity**:
   - `--flag` → `self.params["flag"]` (CLI parameter)
   - `shared["key"]` → Input data (from flow)
   - Never mix them!

4. **Consistent Error Handling**: All actions return same error actions
   ```python
   return "not_found"  # All actions can return this
   return "rate_limited"  # All actions can return this
   ```

### 3. Architecture Decision Tree

```
Is this an MCP wrapper?
  Yes → Use action-based node
  No → Continue...

Do operations share >50% implementation?
  No → Use separate simple nodes
  Yes → Continue...

Do operations have similar interfaces?
  No → Use separate simple nodes (avoid confusion)
  Yes → Continue...

Would users think of this as one "tool"?
  No → Use separate simple nodes
  Yes → Use action-based node with distinct output keys
```

## The Final Pattern

```python
from typing import Dict, Any, NamedTuple
from abc import abstractmethod

class ActionInterface(NamedTuple):
    """Interface definition for an action."""
    inputs: Dict[str, type]
    outputs: Dict[str, type]
    required_inputs: List[str]
    description: str

class ActionBasedNode(Node):
    """Base class for action-based nodes with safe interfaces."""

    @abstractmethod
    def get_interfaces(self) -> Dict[str, ActionInterface]:
        """Return interface definitions for all actions."""
        pass

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Extract inputs based on action interface."""
        action = self.params.get("action")
        if not action:
            raise ValueError("action parameter required")

        interfaces = self.get_interfaces()
        if action not in interfaces:
            raise ValueError(f"Unknown action: {action}")

        interface = interfaces[action]
        inputs = {}

        # Extract required inputs
        for key in interface.required_inputs:
            if key not in shared:
                raise ValueError(f"Missing required input: {key}")
            inputs[key] = shared[key]

        # Extract optional inputs
        for key, type_hint in interface.inputs.items():
            if key in shared and key not in inputs:
                inputs[key] = shared[key]

        return inputs

    def exec(self, prep_res: Dict[str, Any]) -> Any:
        """Dispatch to action method."""
        action = self.params.get("action")
        method = getattr(self, f"_do_{action.replace('-', '_')}", None)

        if not method:
            raise NotImplementedError(f"Action {action} not implemented")

        return method(**prep_res)

    def post(self, shared: Dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        """Write outputs based on action interface."""
        if isinstance(exec_res, str):
            # Action result for flow control
            return exec_res

        action = self.params.get("action")
        interface = self.get_interfaces()[action]

        # Write each output to its designated key
        if isinstance(exec_res, dict):
            for key in interface.outputs:
                if key in exec_res:
                    shared[key] = exec_res[key]
        else:
            # Single output - use first output key
            output_key = list(interface.outputs.keys())[0]
            shared[output_key] = exec_res

        return "default"

# Example implementation
class GitHubNode(ActionBasedNode):
    """GitHub operations - only for truly related actions."""

    def get_interfaces(self):
        return {
            "get-issue": ActionInterface(
                inputs={"repo": str, "issue_number": int},
                outputs={"issue": dict},
                required_inputs=["repo", "issue_number"],
                description="Get issue details"
            ),
            "create-issue": ActionInterface(
                inputs={"repo": str, "title": str, "body": str, "labels": list},
                outputs={"created_issue": dict, "issue_url": str},
                required_inputs=["repo", "title", "body"],
                description="Create new issue"
            )
        }

    def _do_get_issue(self, repo: str, issue_number: int) -> dict:
        # Implementation
        return {"issue": {"number": issue_number, "repo": repo}}

    def _do_create_issue(self, repo: str, title: str, body: str, labels=None) -> dict:
        # Implementation
        return {
            "created_issue": {"number": 123, "title": title},
            "issue_url": f"https://github.com/{repo}/issues/123"
        }
```

This final pattern ensures:
1. **No key collisions** (distinct outputs per action)
2. **Natural interfaces** (within each action's context)
3. **Type safety** (via interface definitions)
4. **Clear documentation** (forced by structure)
5. **MCP compatibility** (maps naturally to tool schemas)
