# PocketFlow Integration Validation

## Critical Integration Points

After reading pocketflow/__init__.py, here are key integration considerations:

### 1. Node Implementation Pattern

Tasks 10-16 describe creating nodes, but must follow pocketflow patterns exactly:

```python
class GitHubGetIssue(BaseNode):
    def prep(self, shared: dict):
        # Read from natural keys
        issue_number = shared.get("issue_number") or self.params.get("issue_number")
        repo = shared.get("repo") or self.params.get("repo")
        return {"issue_number": issue_number, "repo": repo}

    def exec(self, prep_res: dict):
        # Core logic using prep results
        issue_data = fetch_issue(prep_res["issue_number"], prep_res["repo"])
        return issue_data

    def post(self, shared: dict, prep_res: dict, exec_res: dict):
        # Write to natural keys
        shared["issue_data"] = exec_res
        shared["issue_title"] = exec_res.get("title", "")
```

### 2. Flow Compilation (Task 21)

The IR compiler must create pocketflow.Flow objects correctly:

```python
def compile_ir_to_flow(ir_json):
    nodes = {}

    # Instantiate nodes from IR
    for node_def in ir_json["nodes"]:
        node_class = registry.get_node_class(node_def["type"])
        node = node_class()
        node.set_params(node_def.get("params", {}))
        nodes[node_def["id"]] = node

    # Connect nodes based on edges
    for edge in ir_json["edges"]:
        from_node = nodes[edge["from"]]
        to_node = nodes[edge["to"]]
        action = edge.get("action", "default")

        # Set successor
        from_node.set_successor(to_node, action)

    # Create flow
    start_node = nodes[ir_json["start_node"]]
    return Flow(start=start_node)
```

### 3. Proxy Pattern (Task 3)

The NodeAwareSharedStore must maintain dict interface while providing transparent mapping:

```python
class NodeAwareSharedStore(dict):
    def __init__(self, shared_dict, input_mappings=None, output_mappings=None):
        super().__init__(shared_dict)
        self.input_mappings = input_mappings or {}
        self.output_mappings = output_mappings or {}

    def __getitem__(self, key):
        # Map on read
        mapped_key = self.input_mappings.get(key, key)
        return super().__getitem__(mapped_key)

    def __setitem__(self, key, value):
        # Map on write
        mapped_key = self.output_mappings.get(key, key)
        super().__setitem__(mapped_key, value)
```

## Questions for User:

1. Should nodes handle missing required inputs gracefully or fail fast?
2. How should node errors be surfaced - exceptions or error actions?
3. Should the proxy support nested mappings (e.g., "data.content" -> "file_data.text")?
