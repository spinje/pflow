# Typed Node Interfaces: Core Design Insights

*This document captures the critical insights from exploring typed shared stores vs docstring parsing for node interface definition in pflow.*

---

## 1. The Fundamental Question

**Should node interfaces be defined via docstrings or Python type annotations?**

Since nothing is implemented yet, we can choose the path of least resistance while maximizing benefits.

---

## 2. Parsing Complexity Analysis

### Docstring Parsing: Complex and Fragile
- **~500 lines** of regex-heavy parsing code
- Multiple format variations to support
- Error-prone extraction of types and defaults
- Complex state machines for different sections
- Maintenance burden as formats evolve

### Python Type Parsing: Simple and Reliable
- **~50 lines** using built-in AST parsing
- Structured, unambiguous data from Python's type system
- No regex needed - traverse AST nodes
- Leverages existing tooling (mypy, IDE support)
- Self-documenting through type annotations

**Verdict: Python type parsing is 10x easier to implement and maintain.**

---

## 3. Action-Based Nodes Expose Docstring Weakness

### The Complexity Problem
Action-based platform nodes (e.g., `github` with `get-issue`, `create-issue`, `list-prs` actions) make docstring approaches unwieldy:

```python
class GitHubNode(Node):
    """GitHub API operations via action dispatch.

    Interface:
    - Actions: get-issue, create-issue, list-prs, create-pr
    - Global Params: token (string) - GitHub API token

    Action: get-issue
    - Reads: shared["repo"], shared["issue"]
    - Writes: shared["issue_data"]
    - Params: repo (string), issue (integer)

    Action: create-issue
    - Reads: shared["repo"], shared["title"], shared["body"]
    - Writes: shared["issue_data"]
    - Params: repo (string), title (string), body (string)

    # ... more actions
    """
```

**This scales poorly and becomes maintenance nightmare.**

Typed approach handles this elegantly through separate type definitions per action.

---

## 4. LLM-First Design Principle (CRITICAL)

**Most Important Insight: Node code must be easy for LLMs to generate.**

This fundamentally changes the design priorities:

### LLM Requirements
1. **Extremely predictable patterns** - template-driven generation
2. **Minimal cognitive overhead** - no complex inheritance/meta-programming
3. **Copy-paste friendly** - each node file self-contained
4. **Simple, focused logic** - one purpose per node

### LLM-Optimal Solution: Simple Focused Nodes
Instead of complex platform nodes with action dispatch:

```python
class GitHubGetIssueInputs(TypedDict):
    repo: Required[str]     # GitHub repository name
    issue: Required[int]    # Issue number to retrieve

class GitHubGetIssueOutputs(TypedDict):
    issue_data: dict        # Retrieved issue information

@dataclass
class GitHubGetIssueParams:
    token: str = field()    # GitHub API token

class GitHubGetIssueNode(Node):
    """Retrieves issue details from GitHub repository."""

    Inputs = GitHubGetIssueInputs
    Outputs = GitHubGetIssueOutputs
    Params = GitHubGetIssueParams

    def prep(self, shared: GitHubGetIssueInputs):
        return shared["repo"], shared["issue"]

    def exec(self, prep_res):
        repo, issue_num = prep_res
        return github_api.get_issue(repo, issue_num, self.params.token)

    def post(self, shared, prep_res, exec_res):
        shared["issue_data"] = exec_res
        return "default"
```

**Benefits for LLMs:**
- Clear template pattern to follow
- No complex dispatch logic
- Each node completely self-contained
- Natural shared store usage

---

## 5. Structural Typing Solves the "Unused Types" Problem

### The Concern
Defining types but not using them in code feels like pointless ceremony:

```python
class NodeInputs(TypedDict):
    url: Required[str]

def prep(self, shared):  # Not using the type!
    return shared["url"]
```

### The Solution: Actually Use the Types
**TypedDict uses structural typing** - "has at least these keys with these types":

```python
class GitHubGetIssueInputs(TypedDict):
    repo: Required[str]
    issue: Required[int]

def prep(self, shared: GitHubGetIssueInputs):
    # This works! shared might have 50 other keys, but this node only cares about repo/issue
    return shared["repo"], shared["issue"]  # Fully typed with IDE support
```

**Key Insight:** The node doesn't care about other keys in the shared store - it only reads what it needs. Structural typing reflects this reality perfectly.

---

## 6. Action-Based Nodes vs Simple Nodes: The Core Tension

### The Static Typing Problem
Actions that require completely different inputs/outputs fundamentally conflict with static typing:

```python
class GitHubInputs(TypedDict):
    repo: Required[str]
    issue: int           # Only for get-issue
    title: str           # Only for create-issue
    body: str            # Only for create-issue
    # This type is a lie - no action needs ALL these fields
```

You cannot have a single type that accurately represents multiple different interfaces.

### The Resolution
**Platform nodes optimize for human cognitive load but create LLM cognitive load.**

**Simple focused nodes optimize for LLM generation while CLI patterns handle human discoverability.**

```bash
# Discovery through naming patterns and CLI autocomplete
$ pflow github-<TAB>
github-get-issue    github-create-issue    github-list-prs
github-create-pr    github-merge-pr        github-add-comment
```

**Verdict: Abandon platform nodes in favor of simple, focused, LLM-friendly nodes.**

---

## 7. Architectural Decisions

### Type Structure (DECIDED)
```python
class Node:
    Inputs = NodeInputs     # Separate TypedDict for inputs
    Outputs = NodeOutputs   # Separate TypedDict for outputs
    Params = NodeParams     # Dataclass for parameters
```

### Parameter Handling (DECIDED)
```python
@dataclass
class NodeParams:
    language: str = "en"        # Has default = optional
    timeout: int = field()      # No default = required
    max_retries: int = 3        # Has default = optional
```

### Optional/Required Fields (DECIDED)
```python
class NodeInputs(TypedDict, total=False):
    url: Required[str]      # Must be provided
    language: str           # Optional, fallback to param default
```

### Runtime Validation (DECIDED)
- Validate in **execution engine before calling each node**
- Not at node level - keeps node code simple
- Validate types match and required fields exist

### Human Documentation (DECIDED)
```python
class NodeInputs(TypedDict):
    repo: Required[str]     # GitHub repository name
    issue: Required[int]    # Issue number to retrieve
```

Comments on the same line as field definitions.

---

## 8. Implementation Strategy

### Registry Organization
```
registry/
├── aws/
│   ├── aws-get-s3-bucket.py
│   ├── aws-create-s3-bucket.py
│   └── aws-delete-s3-bucket.py
├── github/
│   ├── github-get-issue.py
│   ├── github-create-issue.py
│   └── github-list-prs.py
```

One focused file per capability, LLM generates using consistent template.

### Metadata Extraction
```python
def extract_metadata_from_typed_node(node_class):
    """Extract metadata from typed node - much simpler than docstring parsing!"""

    inputs = get_type_hints(node_class.Inputs)
    outputs = get_type_hints(node_class.Outputs)
    params = get_type_hints(node_class.Params)

    return {
        "inputs": process_typed_dict(inputs),
        "outputs": process_typed_dict(outputs),
        "params": process_dataclass(params)
    }
```

### LLM Generation Template
```
Generate a pflow node for: "{purpose}"

Follow this exact template:
1. Define {Purpose}Inputs TypedDict with Required[] fields and comments
2. Define {Purpose}Outputs TypedDict with result fields and comments
3. Define {Purpose}Params dataclass with field() for required, defaults for optional
4. Define {Purpose}Node class with simple prep/exec/post methods
5. Use natural shared store keys like "bucket", "files", etc.
```

---

## 9. Key Benefits Summary

### For Implementation
- **10x simpler** metadata extraction (50 lines vs 500 lines)
- **More reliable** - leverages Python's type system instead of regex parsing
- **Future-proof** - evolves with Python typing improvements

### For Node Authors (LLMs)
- **Predictable template** - same pattern every time
- **Type safety** - IDE support and validation
- **Self-contained** - each node file completely independent
- **Copy-paste friendly** - easy to generate variations

### For Users
- **Better tooling** - IDE autocompletion for shared store keys
- **Clear interfaces** - types document exactly what each node needs
- **Reliable execution** - runtime validation prevents type errors

### For System Architecture
- **Natural interfaces preserved** - nodes still use intuitive shared store keys
- **Proxy mapping compatible** - structural typing works with key translation
- **Registry friendly** - clean metadata for planning and discovery

---

## 10. The Meta-Insight

**The choice between docstring and typed approaches isn't just about parsing complexity - it's about the fundamental architecture of the system.**

Typed interfaces naturally push toward:
- **Simple, focused nodes** (LLM-friendly)
- **Clear separation of concerns** (easy to understand and generate)
- **Reliable tooling integration** (IDE support, validation)

While docstring approaches enable:
- **Complex platform nodes** (human cognitive load optimization)
- **Flexible documentation** (but harder to parse and validate)
- **Action-based dispatch** (but conflicts with static typing)

**For an LLM-first system, typed interfaces with simple focused nodes is the clear winner.**

---

## Conclusion

The typed interface approach with simple, focused nodes provides:
1. **10x easier implementation** than docstring parsing
2. **LLM-optimal generation patterns** for sustainable node ecosystem
3. **Better tooling support** through static typing
4. **Architectural consistency** that scales as the system grows

This approach aligns with pflow's core principles while optimizing for the reality that most nodes will be LLM-generated.

**Recommendation: Implement typed node interfaces with simple, focused node architecture.**
