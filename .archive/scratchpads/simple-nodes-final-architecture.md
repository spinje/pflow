# Simple Nodes: The PocketFlow Way

*After deep analysis of pocketflow patterns, this document presents the final architecture recommendation: embrace simplicity.*

---

## The Revelation

After reading through pocketflow documentation and examples, the answer is clear:

**We've been massively over-engineering.**

The pocketflow philosophy is:
- **"Keep it simple, stupid!"**
- **One node, one purpose**
- **No complex features**
- **FAIL FAST**
- **Separation of concerns**

## What PocketFlow Examples Show

### Pattern 1: Simple, Focused Nodes for External Operations
```python
# From pocketflow-tool-search
class SearchNode(Node):
    """Node to perform web search - REAL API CALL"""
    def exec(self, inputs):
        searcher = SearchTool()  # External web search API
        return searcher.search(query, num_results)

# From pocketflow-tool-database
class CreateTaskNode(Node):
    """Node for database operations - SIDE EFFECTS"""
    def exec(self, inputs):
        execute_sql("INSERT INTO tasks VALUES (?)", data)
        return "Task created"
```

### Pattern 2: Nodes That Should Use LLM Instead
```python
# BAD: Too many specific prompt nodes
class GenerateOutline(Node):  # ❌ Should be: llm --prompt="Create outline for AI safety"
class WriteSimpleContent(Node):  # ❌ Should be: llm --prompt="Write introduction paragraph"
class ApplyStyle(Node):  # ❌ Should be: llm --prompt="Rewrite this text to be more formal"
class AnalyzeResults(Node):  # ❌ Should be: llm --prompt="Analyze these search results"

# GOOD: Use the general llm node
pflow llm --prompt="Create an outline for article about AI safety"
pflow llm --prompt="Analyze these search results and find key patterns"
```

**Key Insight:** Separate nodes for external operations, `llm` node for all prompt-based tasks!

## The Simple Architecture for pflow

### 1. One Node Per Operation (with exceptions for general nodes)

```python
# github_get_issue.py
class GitHubGetIssueNode(Node):
    """Get GitHub issue details.

    Interface:
    - Reads: shared["issue_number"] OR params["issue_number"]
    - Writes: shared["issue"]
    - Params: repo, token, issue_number (optional)
    """

    def prep(self, shared):
        # Check shared store first (dynamic), then params (static)
        issue_number = shared.get("issue_number") or self.params.get("issue_number")
        if not issue_number:
            raise ValueError("issue_number must be in shared store or params")
        return issue_number

    def exec(self, issue_number):
        repo = self.params.get("repo")
        token = self.params.get("token")
        return github_api.get_issue(repo, issue_number, token)

    def post(self, shared, prep_res, exec_res):
        shared["issue"] = exec_res
        return "default"
```

```python
# github_create_issue.py
class GitHubCreateIssueNode(Node):
    """Create GitHub issue.

    Interface:
    - Reads: shared["title"], shared["body"]
    - Writes: shared["created_issue"]
    - Params: repo, token
    """

    def prep(self, shared):
        return {
            "title": shared["title"],
            "body": shared["body"]
        }

    def exec(self, data):
        repo = self.params.get("repo")
        token = self.params.get("token")
        return github_api.create_issue(repo, data["title"], data["body"], token)

    def post(self, shared, prep_res, exec_res):
        shared["created_issue"] = exec_res
        return "default"
```

**Exception: General-purpose LLM Node**

To reduce clutter from many similar prompt-based nodes:

```python
# llm.py
class LLMNode(Node):
    """General-purpose LLM node wrapping Simon Willison's llm functionality.

    Interface:
    - Reads: shared["prompt"] - the prompt to send to LLM
    - Writes: shared["response"] - LLM's response
    - Params: model, temperature, system, max_tokens
    """

    def prep(self, shared):
        # Simple: just read the prompt from shared store
        prompt = shared.get("prompt")
        if not prompt:
            raise ValueError("Missing 'prompt' in shared store")
        return prompt

    def exec(self, prompt):
        # Future: Use Simon Willison's llm library
        # import llm
        # model = llm.get_model(self.params.get("model", "gpt-4"))
        # response = model.prompt(prompt, ...)

        return call_llm(
            prompt=prompt,
            model=self.params.get("model", "gpt-4"),
            temperature=self.params.get("temperature", 0.7),
            system=self.params.get("system"),
            max_tokens=self.params.get("max_tokens")
        )

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res
        return "default"
```

### 2. Shared Store vs Params: Clear Guidelines

**Use Shared Store for:**
- Dynamic data that flows between nodes
- User inputs and runtime values
- Results from previous nodes
- Data that changes per workflow execution

**Use Params for:**
- Static configuration (API endpoints, credentials)
- Node behavior settings (model, temperature)
- Default values and fallbacks
- Settings that rarely change

**Best Practice: Support Both**
```python
# Check shared store first (dynamic), then params (static)
value = shared.get("key") or self.params.get("key")
```

### 3. Registry Organization

```
registry/
├── nodes/
│   ├── github/                 # External API operations
│   │   ├── github-get-issue.py
│   │   ├── github-create-issue.py
│   │   ├── github-search-code.py
│   │   └── github-list-prs.py
│   ├── slack/                  # External messaging service
│   │   ├── slack-send-message.py
│   │   └── slack-get-messages.py
│   ├── web/                    # Web scraping and APIs
│   │   ├── yt-transcript.py
│   │   ├── web-search.py
│   │   └── fetch-url.py
│   ├── file/                   # File system operations
│   │   ├── read-file.py
│   │   ├── write-file.py
│   │   └── delete-file.py
│   └── core/                   # Essential processing
│       ├── llm.py              # ✨ Replaces dozens of prompt nodes
│       └── json-extract.py     # Structured data extraction
```

### 4. CLI Usage Examples

The CLI provides user-friendly interfaces while keeping nodes simple:

```bash
# Specific nodes for external operations
pflow github-get-issue --repo=owner/repo --issue=123
pflow yt-transcript --url=https://youtu.be/abc123
pflow read-file data.csv
pflow mcp-slack-send --channel=alerts

# General LLM node replaces many specific prompt nodes
pflow llm --prompt="Analyze this GitHub issue and suggest a fix"
pflow llm --prompt="Create an article outline about machine learning"
pflow llm --prompt="Summarize this transcript in bullet points"
pflow llm --system="You are a data analyst" --prompt="Find patterns in this CSV data"

# Real-world flow composition (simplified for MVP)
echo "Analyze this video transcript" | pflow llm >> write-file analysis.md

# Future: More complex flows with data passing
pflow yt-transcript --url=$VIDEO >> \
      transform --set-prompt="Extract key insights from this transcript" >> \
      llm >> \
      write-file insights.md
```

### 5. Planner Groups Nodes Logically

The planner can understand node relationships through:
- Naming conventions (`github-*` nodes)
- Metadata tags
- Natural language descriptions

```python
# Planner context generation
def get_grouped_nodes():
    nodes = registry.get_all_nodes()

    # Group by prefix for presentation
    groups = {}
    for node in nodes:
        prefix = node.split('-')[0]
        if prefix not in groups:
            groups[prefix] = []
        groups[prefix].append(node)

    return groups
```

## MCP Integration: Still Simple

For MCP, we generate simple nodes, not complex flows:

```python
def generate_mcp_node(server_name: str, tool_name: str, tool_spec: dict):
    """Generate a simple node for an MCP tool."""

    class_name = f"Mcp{server_name.title()}{tool_name.title()}Node"

    class McpNode(Node):
        f"""Auto-generated node for {server_name}/{tool_name}.

        {tool_spec['description']}
        """

        def __init__(self):
            super().__init__()
            self.mcp_client = McpClient(server_name)

        def prep(self, shared):
            # Extract inputs based on tool spec
            inputs = {}
            for param in tool_spec['inputSchema']['properties']:
                if param in shared:
                    inputs[param] = shared[param]
            return inputs

        def exec(self, inputs):
            return self.mcp_client.call_tool(tool_name, inputs)

        def post(self, shared, prep_res, exec_res):
            shared["result"] = exec_res
            return "default"

    McpNode.__name__ = class_name
    return McpNode
```

## Benefits of Simple Nodes

### 1. Follows PocketFlow Philosophy
- Each node has ONE clear purpose
- No complex dispatch logic
- Simple to understand and test

### 2. Natural Shared Store Usage
- No key collision issues
- Each node has its own interface
- Clear documentation

### 3. Easy for LLMs to Generate
```python
# Template for LLM generation
class {NodeName}Node(Node):
    """{Description}

    Interface:
    - Reads: shared["{input_key}"]
    - Writes: shared["{output_key}"]
    - Params: {params}
    """

    def prep(self, shared):
        return shared["{input_key}"]

    def exec(self, {input_var}):
        # Implementation here
        return result

    def post(self, shared, prep_res, exec_res):
        shared["{output_key}"] = exec_res
        return "default"
```

### 4. Framework Handles Complexity
- Parameters via `node.set_params()`
- Composition via flows
- Retry/error handling built-in
- No custom abstractions needed

## When to Use Flows

Flows are for **composition**, not action routing:

```python
# Good: Flow composes multiple operations
class GitHubPRFlow(Flow):
    """Complete PR workflow."""

    def __init__(self):
        create_branch = GitCreateBranchNode()
        commit_changes = GitCommitNode()
        push_branch = GitPushNode()
        create_pr = GitHubCreatePRNode()

        create_branch >> commit_changes >> push_branch >> create_pr
        super().__init__(start=create_branch)
```

## Migration Path

1. **Split action-based nodes** into simple nodes
2. **Use naming conventions** for grouping
3. **Let CLI handle** user-friendly interfaces
4. **Let planner group** nodes by metadata
5. **Generate simple MCP nodes** without flows

## Key Architectural Decisions

### 1. Simple Nodes with Clear Interfaces
- One node per specific operation (github-get-issue, slack-send-message)
- Exception: General-purpose nodes like `llm` to reduce clutter
- Every node documents its interface clearly (Reads/Writes/Params)

### When to Create a Specific Node vs Using LLM

**Create a Specific Node When:**
- External API calls (GitHub, Slack, databases)
- File system operations (read, write, delete)
- Data transformations with specific logic
- Tool integrations (web search, PDF parsing)
- Operations with side effects

**Use the LLM Node When:**
- Text generation or transformation
- Analysis and summarization
- Content creation (outlines, articles, reports)
- Question answering
- Any task that's essentially a prompt

**Examples:**
```bash
# Specific nodes (external operations)
pflow github-create-issue           # ✅ API call
pflow read-file                     # ✅ File system
pflow mcp-weather-get              # ✅ External service
pflow yt-transcript                # ✅ YouTube API

# LLM node (prompt operations)
pflow llm --prompt="..."           # ✅ All text generation
# Instead of: GenerateOutline, WriteContent, ApplyStyle, AnalyzeText, etc.
```

### 2. Shared Store vs Params Pattern
- **Shared Store**: Dynamic workflow data that flows between nodes
- **Params**: Static configuration and settings
- **Best Practice**: Check both, with shared store taking precedence

### 3. LLM Node Strategy
- Single `llm` node replaces many specific prompt nodes
- Simple `--prompt` parameter for MVP (templates can come later)
- Future integration with Simon Willison's llm CLI for model management
- Reduces node proliferation while maintaining flexibility

**Why One LLM Node is Better:**
- **Maintainability**: Update LLM logic in one place
- **Discoverability**: Users know to use `llm` for any text task
- **Simplicity**: Just pass a prompt, no complex templates initially
- **Consistency**: Same interface for all prompt operations
- **Evolution**: Easy to add features like templates later

### 4. CLI Intelligence
- CLI handles user-friendly grouping and aliases
- Natural language planner understands node relationships
- Users don't need to know internal node organization

## Conclusion

The pocketflow way is the right way:
- **Simple nodes** that do one thing
- **General-purpose nodes** only where it reduces significant clutter
- **Clear separation** between dynamic data (shared) and config (params)
- **Natural interfaces** without collision
- **Framework composition** via flows
- **CLI/Planner intelligence** for grouping

This architecture:
- ✅ Follows pocketflow patterns exactly
- ✅ Reduces node clutter intelligently
- ✅ Provides clear data flow patterns
- ✅ Is easier to implement and maintain
- ✅ Is more testable and debuggable
- ✅ Is what the framework was designed for

## The Final Word

We embrace:
- **Simple, focused nodes** (with smart exceptions)
- **Clear shared store vs params guidelines**
- **Simple prompt-based LLM integration**
- **Good naming conventions**
- **Smart CLI/planner capabilities**

This is the way pocketflow was meant to be used. Simple, clear, and powerful.
