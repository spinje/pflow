# Node Architecture Journey: Towards the Perfect pflow Node Design

*This document captures the exploration and insights as we work towards defining the ideal node architecture for pflow, with heavy inspiration from MCP (Model Context Protocol) design patterns.*

---

## Core Challenge: Dynamic API Discovery

The fundamental challenge we're solving is that action-based nodes have dynamic APIs that change based on the action parameter. This creates several requirements:

1. **Planner needs to know** what actions are available and their parameters
2. **CLI validation needs to know** if a command is valid before execution
3. **Autocomplete needs to know** what parameters to suggest
4. **Runtime needs to validate** inputs/outputs match expectations

## MCP Design Patterns to Learn From

### 1. Tool Discovery Pattern
MCP servers expose their capabilities through a `tools/list` RPC that returns:
```json
{
  "tools": [
    {
      "name": "search_code",
      "description": "Search for code in the repository",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Search query"},
          "path": {"type": "string", "description": "Path to search in"}
        },
        "required": ["query"]
      }
    }
  ]
}
```

**Key Insight**: Tools (actions) are discovered dynamically with complete schema information.

### 2. Server = Platform, Tool = Action
MCP's natural hierarchy maps perfectly to our needs:
- MCP Server (e.g., `github-server`) → Platform Node (e.g., `github`)
- MCP Tool (e.g., `search_code`) → Action (e.g., `--action=search-code`)
- Tool InputSchema → Action Parameters

### 3. Runtime Discovery vs Static Declaration
MCP uses runtime discovery - servers expose their tools when connected. For pflow, we need a hybrid:
- **Static metadata** for planning/validation (extracted from code)
- **Runtime discovery** for MCP wrapper nodes

## Current Architecture Tensions

### From typed-node-interfaces-insights.md:
- **Simple focused nodes** are LLM-friendly but create discovery challenges
- **Platform nodes with actions** match user mental models but complicate typing
- **Static typing conflicts** with dynamic action-based interfaces

### From mcp-first-architecture-insights.md:
- **MCP wrapping should be trivial** - the pattern should work for both MCP and native
- **Single connection per platform** is more efficient
- **Metadata drives everything** - need upfront schemas

### From architectural-insights.md:
- **Natural interfaces** with shared store are fundamental
- **Validation-first** approach prevents AI hallucination damage
- **Progressive complexity** - users start simple, grow to advanced

## Design Explorations

### Option 1: Pure Runtime Discovery (MCP-style)
```python
class GitHubNode(Node):
    def list_actions(self) -> List[ActionSchema]:
        """Runtime discovery of available actions"""
        return [
            ActionSchema(
                name="get-issue",
                inputs=["repo", "issue"],
                outputs=["issue_data"],
                params={"format": "json|yaml"}
            ),
            ActionSchema(
                name="create-issue",
                inputs=["repo", "title", "body"],
                outputs=["issue_data"],
                params={}
            )
        ]

    def exec(self, prep_res):
        action = self.params.get("action")
        # Dispatch based on action
```

**Problems**:
- Can't validate CLI before instantiating node
- Metadata extraction becomes complex
- Planning requires runtime introspection

### Option 2: Static Action Registry
```python
class GitHubNode(Node):
    ACTIONS = {
        "get-issue": {
            "inputs": {"repo": str, "issue": int},
            "outputs": {"issue_data": dict},
            "params": {"format": str}
        },
        "create-issue": {
            "inputs": {"repo": str, "title": str, "body": str},
            "outputs": {"issue_data": dict},
            "params": {}
        }
    }
```

**Problems**:
- Duplication between ACTIONS and implementation
- Type safety is weak
- Still doesn't solve the "which type for prep/exec/post" problem

### Option 3: Action Methods with Decorators
```python
class GitHubNode(Node):
    @action("get-issue",
            inputs=["repo", "issue"],
            outputs=["issue_data"],
            params={"format": "json|yaml"})
    def get_issue(self, repo: str, issue: int, format: str = "json") -> dict:
        return github_api.get_issue(repo, issue)
```

**Problems**:
- Breaks the prep/exec/post lifecycle
- Not compatible with pocketflow framework
- Complex decorator implementation

## The Key Insight: Two-Phase Design

After exploring these options, the solution becomes clear: **separate metadata from execution**.

### Phase 1: Metadata Declaration (Static)
```python
class GitHubNode(Node):
    """Platform node for GitHub operations."""

    class Meta:
        actions = {
            "get-issue": ActionMeta(
                description="Get issue details from repository",
                inputs={"repo": Required[str], "issue": Required[int]},
                outputs={"issue_data": dict},
                params={"format": Optional[str]},
                example="github --action=get-issue --format=json"
            ),
            "create-issue": ActionMeta(
                description="Create new issue in repository",
                inputs={"repo": Required[str], "title": Required[str], "body": Required[str]},
                outputs={"issue_data": dict, "issue_url": str},
                params={"labels": Optional[List[str]]},
                example="github --action=create-issue --labels=bug,high-priority"
            )
        }
```

### Phase 2: Execution (Runtime)
```python
    def prep(self, shared):
        """Extract inputs based on current action"""
        action = self.params.get("action")
        meta = self.Meta.actions[action]

        # Extract only the inputs this action needs
        inputs = {}
        for key, type_hint in meta.inputs.items():
            if key in shared:
                inputs[key] = shared[key]
            elif isinstance(type_hint, Required):
                raise ValueError(f"Missing required input: {key}")

        return inputs

    def exec(self, prep_res):
        """Dispatch to action implementation"""
        action = self.params.get("action")

        if action == "get-issue":
            return self._get_issue(**prep_res)
        elif action == "create-issue":
            return self._create_issue(**prep_res)
        else:
            raise ValueError(f"Unknown action: {action}")
```

## Why This Works

1. **Static Metadata**: Available for CLI validation, planning, autocomplete
2. **Type Safety**: Each action has clear input/output types
3. **MCP Alignment**: Easy to generate from MCP tool schemas
4. **LLM Friendly**: Clear pattern for generation
5. **Validation First**: Can validate before execution
6. **Natural Interfaces**: Still uses intuitive shared store keys

## Implementation Pattern

### For Native Platform Nodes:
```python
class SlackNode(Node):
    """Platform node for Slack operations."""

    class Meta:
        actions = {
            "send-message": ActionMeta(
                description="Send message to Slack channel",
                inputs={"channel": Required[str], "message": Required[str]},
                outputs={"message_id": str, "timestamp": str},
                params={"thread_ts": Optional[str]},
                example="slack --action=send-message --thread_ts=123.456"
            )
        }

    def exec(self, prep_res):
        action = self.params.get("action")
        if action == "send-message":
            return slack_api.send_message(**prep_res, **self.params)
```

### For MCP Wrapper Nodes:
```python
def create_mcp_node(server_name: str) -> Type[Node]:
    """Generate platform node from MCP server"""

    # Connect and discover tools
    client = McpClient(server_name)
    tools = client.list_tools()

    # Build actions metadata
    actions = {}
    for tool in tools:
        actions[tool.name] = ActionMeta(
            description=tool.description,
            inputs=parse_schema_to_types(tool.inputSchema),
            outputs={"result": Any},  # MCP doesn't specify outputs
            params={},
            example=f"{server_name} --action={tool.name}"
        )

    # Create node class
    class McpPlatformNode(Node):
        class Meta:
            actions = actions

        def __init__(self):
            self.client = McpClient(server_name)

        def exec(self, prep_res):
            action = self.params.get("action")
            return self.client.call_tool(action, prep_res)

    return McpPlatformNode
```

## Benefits of This Approach

### For Planning:
- Planner can see all available actions and their schemas
- Can validate workflow feasibility before execution
- Natural language descriptions for each action

### For CLI:
- Validate command syntax before running
- Autocomplete can suggest valid actions and parameters
- Clear error messages for invalid usage

### For Runtime:
- Type-safe execution with validation
- Consistent error handling across all actions
- Natural integration with shared store

### For Developers:
- Clear pattern to follow
- Separation of metadata and logic
- Easy to test individual actions

## Next Steps

1. **Define ActionMeta class** with all needed fields
2. **Create metadata extractor** that can parse these declarations
3. **Update registry** to understand action-based metadata
4. **Implement CLI validation** using action metadata
5. **Create MCP wrapper generator** following this pattern

## Open Questions

1. **Parameter Inheritance**: Should all actions inherit platform-level params (like API tokens)?
2. **Output Variations**: How to handle actions that might produce different outputs based on success/failure?
3. **Streaming Actions**: How to handle actions that produce streaming outputs?
4. **Composite Actions**: Should we support actions that chain other actions?

## The Deeper Dive: Action Metadata Architecture

### Current State Analysis

After examining the existing documentation, several key insights emerge:

1. **Action-based nodes are already chosen** (docs/action-nodes.md)
2. **MCP integration requires action dispatch** (docs/mcp-integration.md)
3. **Metadata extraction exists for docstrings** (docs/implementation-details/metadata-extraction.md)
4. **Schema includes action arrays** (docs/schemas.md)

However, there's a critical gap: **How do we handle action-specific metadata?**

### The Core Problem: Action Parameter Variance

Current metadata schema assumes uniform interface across all actions:
```json
{
  "interface": {
    "inputs": {"repo": "str", "issue": "int"},  // Which action needs these?
    "outputs": {"issue_data": "dict"},           // What if actions produce different outputs?
    "params": {"format": "str"},                  // Are these global or action-specific?
    "actions": ["get-issue", "create-issue"]     // Just a list, no metadata per action
  }
}
```

This doesn't capture that:
- `get-issue` needs `repo` and `issue` inputs
- `create-issue` needs `repo`, `title`, and `body` inputs
- Each action might have different parameter sets

### Evolution of the Schema

We need to evolve from flat metadata to action-aware metadata:

#### Option 1: Nested Action Metadata (Complex but Complete)
```json
{
  "interface": {
    "global_inputs": {},  // Inputs all actions share
    "global_outputs": {}, // Outputs all actions produce
    "global_params": {    // Parameters available to all actions
      "token": {"type": "str", "description": "GitHub API token"}
    },
    "actions": {
      "get-issue": {
        "description": "Retrieve issue details",
        "inputs": {"repo": "str", "issue": "int"},
        "outputs": {"issue_data": "dict"},
        "params": {"format": {"type": "str", "default": "json"}},
        "example": "github --action=get-issue --format=json"
      },
      "create-issue": {
        "description": "Create new issue",
        "inputs": {"repo": "str", "title": "str", "body": "str"},
        "outputs": {"issue_data": "dict", "issue_url": "str"},
        "params": {"labels": {"type": "list", "optional": true}},
        "example": "github --action=create-issue --labels=bug,urgent"
      }
    }
  }
}
```

#### Option 2: Action Dispatch Table (Simpler but Limited)
```json
{
  "interface": {
    "dispatch_mode": "action",
    "dispatch_key": "action",
    "actions": ["get-issue", "create-issue"],
    "inputs": {  // Union of all possible inputs
      "repo": {"type": "str", "required_for": ["get-issue", "create-issue"]},
      "issue": {"type": "int", "required_for": ["get-issue"]},
      "title": {"type": "str", "required_for": ["create-issue"]},
      "body": {"type": "str", "required_for": ["create-issue"]}
    },
    "outputs": {  // Union of all possible outputs
      "issue_data": {"type": "dict", "produced_by": ["get-issue", "create-issue"]},
      "issue_url": {"type": "str", "produced_by": ["create-issue"]}
    }
  }
}
```

### The MCP Alignment Solution

Looking at how MCP handles this:
```json
{
  "tools": [
    {
      "name": "search_code",
      "inputSchema": {"type": "object", "properties": {...}},
      "description": "Search for code"
    },
    {
      "name": "get_issue",
      "inputSchema": {"type": "object", "properties": {...}},
      "description": "Get issue details"
    }
  ]
}
```

MCP treats each tool as a separate entity with its own schema. This suggests **Option 1 (Nested Action Metadata)** aligns better with MCP.

### Implementation in Python Nodes

How would nodes declare this?

#### Using Class Attributes (Static)
```python
class GitHubNode(Node):
    """GitHub platform operations."""

    ACTIONS = {
        "get-issue": {
            "description": "Get issue details",
            "inputs": {"repo": str, "issue": int},
            "outputs": {"issue_data": dict},
            "params": {"format": str}
        },
        "create-issue": {
            "description": "Create new issue",
            "inputs": {"repo": str, "title": str, "body": str},
            "outputs": {"issue_data": dict, "issue_url": str},
            "params": {"labels": List[str]}
        }
    }
```

#### Using Decorated Methods (Discovery)
```python
class GitHubNode(Node):
    @action("get-issue",
            inputs={"repo": str, "issue": int},
            outputs={"issue_data": dict})
    def _get_issue(self, repo: str, issue: int) -> dict:
        return github_api.get_issue(repo, issue)
```

#### Using Docstring Sections (Current Pattern Extended)
```python
class GitHubNode(Node):
    """GitHub platform operations.

    Interface:
    - Actions:
        get-issue:
            Description: Get issue details from repository
            Inputs: repo (str), issue (int)
            Outputs: issue_data (dict)
            Params: format (str, default="json")
        create-issue:
            Description: Create new issue in repository
            Inputs: repo (str), title (str), body (str)
            Outputs: issue_data (dict), issue_url (str)
            Params: labels (list, optional)
    """
```

### The Path Forward

1. **Extend the metadata schema** to support action-specific metadata
2. **Update extraction infrastructure** to parse action subsections
3. **Modify planner context** to understand action parameters
4. **Enhance CLI validation** to check action-specific requirements

## Conclusion

The key to perfect node architecture is **action-aware metadata** that:

- Maintains backward compatibility with simple nodes
- Enables rich action-specific parameter validation
- Aligns perfectly with MCP tool patterns
- Supports both static declaration and dynamic discovery

The nested action metadata approach (Option 1) provides the richest model while maintaining the natural prep/exec/post lifecycle that makes pflow nodes simple to write.

## Technical Deep Dive: Implementing Action-Aware Nodes

### The Execution Flow Challenge

With action-based nodes, the prep/exec/post lifecycle needs to handle dynamic interfaces:

```python
class GitHubNode(Node):
    def prep(self, shared):
        action = self.params.get("action")

        # Problem: How do we know which keys to extract?
        # Solution: Use action metadata
        action_meta = self.ACTIONS[action]

        inputs = {}
        for key, type_hint in action_meta["inputs"].items():
            if key in shared:
                inputs[key] = shared[key]
            elif action_meta.get("required", {}).get(key, True):
                raise ValueError(f"Missing required input '{key}' for action '{action}'")

        return inputs
```

### Runtime Type Validation

The metadata enables runtime validation before node execution:

```python
class ActionValidator:
    """Validates inputs/outputs against action metadata."""

    def validate_inputs(self, node_class, action: str, shared: dict) -> List[str]:
        """Validate shared store has required inputs for action."""
        errors = []
        action_meta = node_class.ACTIONS.get(action)

        if not action_meta:
            return [f"Unknown action: {action}"]

        for input_key, input_type in action_meta["inputs"].items():
            if input_key not in shared:
                if action_meta.get("required", {}).get(input_key, True):
                    errors.append(f"Missing required input: {input_key}")
            elif not isinstance(shared[input_key], input_type):
                errors.append(
                    f"Type mismatch for {input_key}: "
                    f"expected {input_type.__name__}, "
                    f"got {type(shared[input_key]).__name__}"
                )

        return errors
```

### MCP Wrapper Generation Pattern

For MCP integration, we generate nodes that follow the action metadata pattern:

```python
def generate_mcp_node(server_name: str, tools: List[McpTool]) -> Type[Node]:
    """Generate action-based node from MCP server tools."""

    # Build ACTIONS dictionary from MCP tools
    actions = {}
    for tool in tools:
        actions[tool.name] = {
            "description": tool.description,
            "inputs": parse_mcp_schema_to_types(tool.inputSchema),
            "outputs": {"result": Any},  # MCP doesn't specify output schema
            "params": {},  # Tool-specific params from inputSchema
        }

    # Generate node class
    class McpGeneratedNode(Node):
        f"""Auto-generated node for {server_name} MCP server."""

        ACTIONS = actions

        def __init__(self):
            super().__init__()
            self.mcp_client = McpClient(server_name)

        def prep(self, shared):
            action = self.params.get("action")
            if action not in self.ACTIONS:
                raise ValueError(f"Unknown action: {action}")

            # Extract inputs based on action metadata
            action_meta = self.ACTIONS[action]
            inputs = {}
            for key in action_meta["inputs"]:
                if key in shared:
                    inputs[key] = shared[key]

            return inputs

        def exec(self, prep_res):
            action = self.params.get("action")
            return self.mcp_client.call_tool(action, prep_res)

        def post(self, shared, prep_res, exec_res):
            shared["result"] = exec_res
            return "default"

    return McpGeneratedNode
```

### CLI Parameter Resolution

The CLI needs to understand action-specific parameters:

```python
class ActionAwareCLI:
    """CLI that validates parameters based on action."""

    def resolve_node_params(self, node_id: str, cli_args: dict) -> dict:
        """Resolve CLI arguments to node parameters."""

        # Get node metadata
        node_meta = registry.get_metadata(node_id)

        # Check if this is an action-based node
        if "dispatch_mode" in node_meta.get("interface", {}):
            action = cli_args.get("action")
            if not action:
                raise ValueError("Action-based node requires --action parameter")

            # Get action-specific metadata
            action_meta = node_meta["interface"]["actions"].get(action)
            if not action_meta:
                valid_actions = list(node_meta["interface"]["actions"].keys())
                raise ValueError(
                    f"Unknown action '{action}'. "
                    f"Valid actions: {', '.join(valid_actions)}"
                )

            # Validate parameters against action metadata
            return self._validate_action_params(action_meta, cli_args)

        # Non-action node, use standard resolution
        return self._standard_param_resolution(node_meta, cli_args)
```

### Planner Integration

The planner needs rich context about available actions:

```python
def build_action_aware_context(nodes: List[str]) -> str:
    """Build LLM context with action-specific details."""

    context = ["Available pflow nodes and their actions:\n"]

    for node_id in nodes:
        meta = registry.get_metadata(node_id)
        interface = meta.get("interface", {})

        if "actions" in interface and isinstance(interface["actions"], dict):
            # Action-based node with rich metadata
            context.append(f"\n{node_id}: {meta['documentation']['description']}")

            for action_name, action_meta in interface["actions"].items():
                context.append(f"  --action={action_name}: {action_meta['description']}")

                # Show inputs
                inputs = [f'{k} ({v})' for k, v in action_meta['inputs'].items()]
                context.append(f"    Inputs: {', '.join(inputs)}")

                # Show outputs
                outputs = [f'{k} ({v})' for k, v in action_meta['outputs'].items()]
                context.append(f"    Outputs: {', '.join(outputs)}")

                # Show example if available
                if "example" in action_meta:
                    context.append(f"    Example: {action_meta['example']}")
        else:
            # Simple node or legacy action list
            context.append(f"\n{node_id}: {meta['documentation']['description']}")
            if "actions" in interface:
                actions = interface["actions"]
                if isinstance(actions, list):
                    context.append(f"  Actions: {', '.join(actions)}")

    return "\n".join(context)
```

### Metadata Extraction Enhancement

Extending the docstring parser to handle action subsections:

```python
class EnhancedInterfaceParser(InterfaceSectionParser):
    """Parse Interface sections with action-specific metadata."""

    def parse_interface(self, docstring: str) -> Dict:
        """Parse Interface section including action subsections."""

        # Check for Actions: subsection
        if self._has_actions_subsection(docstring):
            return self._parse_action_based_interface(docstring)
        else:
            return super().parse_interface(docstring)

    def _parse_action_based_interface(self, docstring: str) -> Dict:
        """Parse action-based interface format."""

        interface = {
            "dispatch_mode": "action",
            "global_params": {},
            "actions": {}
        }

        # Extract Actions subsection
        actions_match = re.search(
            r'Actions:\s*\n(.*?)(?=\n\n|\n[A-Z][a-z]+:|\Z)',
            docstring,
            re.DOTALL
        )

        if actions_match:
            actions_text = actions_match.group(1)

            # Parse each action block
            action_blocks = self._split_action_blocks(actions_text)

            for action_name, action_text in action_blocks.items():
                interface["actions"][action_name] = self._parse_action_block(action_text)

        return interface

    def _parse_action_block(self, action_text: str) -> Dict:
        """Parse individual action metadata block."""

        meta = {
            "description": "",
            "inputs": {},
            "outputs": {},
            "params": {}
        }

        # Parse Description line
        desc_match = re.search(r'Description:\s*(.+)', action_text)
        if desc_match:
            meta["description"] = desc_match.group(1).strip()

        # Parse Inputs line
        inputs_match = re.search(r'Inputs:\s*(.+)', action_text)
        if inputs_match:
            meta["inputs"] = self._parse_field_list(inputs_match.group(1))

        # Parse Outputs line
        outputs_match = re.search(r'Outputs:\s*(.+)', action_text)
        if outputs_match:
            meta["outputs"] = self._parse_field_list(outputs_match.group(1))

        # Parse Params line
        params_match = re.search(r'Params:\s*(.+)', action_text)
        if params_match:
            meta["params"] = self._parse_param_list(params_match.group(1))

        return meta
```

### The Complete Picture

With action-aware metadata:

1. **Nodes declare rich action metadata** (via docstrings or class attributes)
2. **Registry extracts and indexes** action-specific information
3. **CLI validates parameters** against action requirements
4. **Planner understands** what each action does and needs
5. **Runtime validates** inputs/outputs for type safety
6. **MCP integration** naturally maps tools to actions

This creates a cohesive system where action-based nodes are first-class citizens with full tooling support.

## Insights from pocketflow-mcp Example

Examining the pocketflow-mcp cookbook example reveals several important patterns:

### 1. Tool Discovery as Metadata

The MCP example discovers tools dynamically and formats them as metadata:
```python
# From GetToolsNode.post()
for i, tool in enumerate(tools, 1):
    properties = tool.inputSchema.get('properties', {})
    required = tool.inputSchema.get('required', [])

    params = []
    for param_name, param_info in properties.items():
        param_type = param_info.get('type', 'unknown')
        req_status = "(Required)" if param_name in required else "(Optional)"
        params.append(f"    - {param_name} ({param_type}): {req_status}")
```

This is exactly the kind of metadata we need for action-based nodes!

### 2. Decision Node Pattern

The `DecideToolNode` uses an LLM to select which tool to use, but in pflow's case:
- The action is specified by the user via `--action` flag
- No LLM decision needed at runtime
- But the planner still needs this metadata during flow composition

### 3. Execution Abstraction

The example abstracts tool execution:
```python
def call_tool(server_script_path=None, tool_name=None, arguments=None):
    if MCP:
        return mcp_call_tool(server_script_path, tool_name, arguments)
    else:
        return local_call_tool(server_script_path, tool_name, arguments)
```

This maps perfectly to our action dispatch pattern:
```python
def exec(self, prep_res):
    action = self.params.get("action")
    if self.is_mcp_node:
        return self.mcp_client.call_tool(action, prep_res)
    else:
        return self._dispatch_local_action(action, prep_res)
```

### 4. Schema-Driven Interface

The MCP tools have rich schemas:
```python
{
    "name": "add",
    "description": "Add two numbers together",
    "inputSchema": {
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"}
        },
        "required": ["a", "b"]
    }
}
```

This is the exact pattern we need for action metadata in pflow!

### Key Takeaways for pflow

1. **Tool schemas ARE action schemas** - The MCP inputSchema pattern is perfect for defining action-specific parameters

2. **Discovery happens at different times**:
   - MCP: Runtime discovery when connecting to server
   - pflow: Build-time discovery during metadata extraction
   - But both need the same rich schema information

3. **The prep/exec/post pattern works well** with schema-driven interfaces:
   - `prep()`: Extract inputs based on schema
   - `exec()`: Dispatch to appropriate action/tool
   - `post()`: Handle results uniformly

4. **Local vs Remote is an implementation detail** - The node interface remains the same whether calling local methods or MCP tools

### Applying to pflow's Architecture

The pocketflow-mcp example validates our approach:

```python
class GitHubNode(Node):
    """GitHub platform operations.

    Actions:
        get-issue:
            description: Get issue details from repository
            inputSchema:
                properties:
                    repo: {type: string, description: "Repository name"}
                    issue: {type: integer, description: "Issue number"}
                required: [repo, issue]
            outputSchema:
                properties:
                    issue_data: {type: object, description: "Issue details"}
    """

    def prep(self, shared):
        action = self.params.get("action")
        # Use inputSchema to extract required fields from shared
        schema = self.get_action_schema(action)
        return self.extract_by_schema(shared, schema)

    def exec(self, prep_res):
        action = self.params.get("action")
        # Dispatch to action implementation
        return self.dispatch_action(action, prep_res)
```

The pattern from pocketflow-mcp shows us that:
1. Schema-driven interfaces are powerful and necessary
2. The prep/exec/post lifecycle handles schema validation naturally
3. Tools (actions) need rich metadata for both discovery and validation
4. The same patterns work for both local and remote execution

This reinforces that our action-aware metadata approach is on the right track!

## Final Architecture Proposal

Based on all our exploration, here's the optimal node architecture for pflow:

### 1. Metadata Schema Evolution

Extend the current schema to support action-specific metadata:

```json
{
  "node": {
    "id": "github",
    "type": "platform",  // New field to indicate action-based node
    "namespace": "core",
    "version": "1.0.0"
  },
  "interface": {
    "dispatch": {
      "mode": "action",
      "parameter": "action",  // Which param contains the action
      "actions": {
        "get-issue": {
          "description": "Retrieve issue details",
          "inputSchema": {
            "type": "object",
            "properties": {
              "repo": {"type": "string", "description": "Repository name"},
              "issue": {"type": "integer", "description": "Issue number"}
            },
            "required": ["repo", "issue"]
          },
          "outputSchema": {
            "type": "object",
            "properties": {
              "issue_data": {"type": "object", "description": "Issue details"}
            }
          },
          "parameters": {
            "format": {"type": "string", "enum": ["json", "yaml"], "default": "json"}
          }
        }
      }
    },
    "globalParameters": {
      "token": {"type": "string", "description": "GitHub API token", "required": true}
    }
  }
}
```

### 2. Docstring Format Extension

```python
class GitHubNode(Node):
    """GitHub platform operations.

    Platform Parameters:
    - token (str): GitHub API token - required for all actions

    Actions:
      get-issue:
        Description: Retrieve issue details from repository
        Inputs:
          repo (str): Repository name
          issue (int): Issue number
        Outputs:
          issue_data (dict): Complete issue information
        Parameters:
          format (str): Output format - json or yaml (default: json)
        Example: github --action=get-issue --repo=owner/name --issue=123

      create-issue:
        Description: Create new issue in repository
        Inputs:
          repo (str): Repository name
          title (str): Issue title
          body (str): Issue description
        Outputs:
          issue_data (dict): Created issue information
          issue_url (str): URL of created issue
        Parameters:
          labels (list): Labels to apply (optional)
          assignees (list): Users to assign (optional)
        Example: github --action=create-issue --labels=bug,urgent
    """
```

### 3. Base Class Pattern

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ActionBasedNode(Node, ABC):
    """Base class for action-based platform nodes."""

    @abstractmethod
    def get_action_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Return action schemas for metadata extraction."""
        pass

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Extract inputs based on action schema."""
        action = self.params.get("action")
        if not action:
            raise ValueError("Action-based node requires 'action' parameter")

        schemas = self.get_action_schemas()
        if action not in schemas:
            valid = ", ".join(schemas.keys())
            raise ValueError(f"Unknown action '{action}'. Valid: {valid}")

        # Extract inputs based on schema
        schema = schemas[action]
        inputs = {}

        for prop, spec in schema.get("inputSchema", {}).get("properties", {}).items():
            if prop in shared:
                inputs[prop] = shared[prop]
            elif prop in schema.get("inputSchema", {}).get("required", []):
                raise ValueError(f"Missing required input '{prop}' for action '{action}'")

        return inputs

    def exec(self, prep_res: Dict[str, Any]) -> Any:
        """Dispatch to action implementation."""
        action = self.params.get("action")
        method_name = f"_exec_{action.replace('-', '_')}"

        if hasattr(self, method_name):
            return getattr(self, method_name)(**prep_res)
        else:
            raise NotImplementedError(f"Action '{action}' not implemented")

    def post(self, shared: Dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        """Write outputs based on action schema."""
        if isinstance(exec_res, str):
            # Action string for flow control
            return exec_res

        action = self.params.get("action")
        schemas = self.get_action_schemas()
        schema = schemas[action]

        # Handle different output patterns
        output_schema = schema.get("outputSchema", {})
        if "properties" in output_schema:
            # Multiple outputs
            if isinstance(exec_res, dict):
                for key, value in exec_res.items():
                    if key in output_schema["properties"]:
                        shared[key] = value
            else:
                # Single output, use first property name
                first_key = list(output_schema["properties"].keys())[0]
                shared[first_key] = exec_res

        return "default"
```

### 4. Concrete Implementation

```python
class GitHubNode(ActionBasedNode):
    """GitHub platform operations."""

    def get_action_schemas(self) -> Dict[str, Dict[str, Any]]:
        return {
            "get-issue": {
                "description": "Retrieve issue details",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "issue": {"type": "integer"}
                    },
                    "required": ["repo", "issue"]
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "issue_data": {"type": "object"}
                    }
                }
            },
            "create-issue": {
                "description": "Create new issue",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["repo", "title", "body"]
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "issue_data": {"type": "object"},
                        "issue_url": {"type": "string"}
                    }
                }
            }
        }

    def _exec_get_issue(self, repo: str, issue: int) -> Dict[str, Any]:
        """Get issue implementation."""
        token = self.params.get("token")
        # API call here
        return {"issue_data": {"id": issue, "repo": repo}}

    def _exec_create_issue(self, repo: str, title: str, body: str) -> Dict[str, Any]:
        """Create issue implementation."""
        token = self.params.get("token")
        # API call here
        return {
            "issue_data": {"id": 123, "title": title},
            "issue_url": f"https://github.com/{repo}/issues/123"
        }
```

### 5. Benefits of This Architecture

1. **Full MCP Compatibility**: Action schemas match MCP tool schemas exactly
2. **Static Metadata**: Available for planner and CLI validation
3. **Type Safety**: Schema-driven validation at multiple levels
4. **Backward Compatible**: Simple nodes without actions still work
5. **LLM Friendly**: Clear patterns for code generation
6. **Natural Interfaces**: Maintains shared store simplicity
7. **Extensible**: Easy to add new actions to existing nodes

### 6. Integration Points

- **Metadata Extraction**: Enhanced parser reads action schemas from docstrings or class attributes
- **CLI Validation**: Check action and parameters against schema before execution
- **Planner Context**: Rich action descriptions for LLM selection
- **Registry Storage**: Action schemas stored in node metadata
- **MCP Wrapper**: Direct mapping from MCP tools to action schemas

This architecture provides the perfect balance between flexibility and structure, enabling rich action-based nodes while maintaining pflow's simplicity principles.
