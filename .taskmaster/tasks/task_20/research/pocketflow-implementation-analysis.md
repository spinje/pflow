# Task 20: Planner Output Approval and Storage - PocketFlow Implementation Analysis

## Why Approval and Storage Benefits from PocketFlow

The approval and storage system involves user interaction, workflow validation, persistence, and pattern matching for workflow reuse. It's a multi-step process with external dependencies and multiple paths.

### The Approval and Storage Flow

```
Generated Workflow
        │
        v
Present to User
        │
        ├─> Format Display ─> Syntax Highlight ─> Show Parameters ─┐
        │                                                           │
        └─> Cost Estimation ─> Token Count ─> Price Calculation ───┘
                                                                    │
                                                                    v
                                                            User Decision
                                                                    │
                    ┌───────────────────────┬───────────────────────┼───────────────────────┬─────────────────┐
                    │                       │                       │                       │                 │
                    v                       v                       v                       v                 v
                 Approve               Modify Parameters         Reject                Save for Later    Run Without Save
                    │                       │                       │                       │                 │
                    v                       v                       │                       v                 │
              Validate Name          Show Edit UI                   │              Generate Auto-Name        │
                    │                       │                       │                       │                 │
                    v                       v                       │                       v                 │
            Check Duplicates         Apply Changes                  │               Save to Drafts           │
                    │                       │                       │                       │                 │
                    v                       v                       │                       │                 │
              Save Workflow         Re-validate                     │                       │                 │
                    │                       │                       │                       │                 │
                    v                       v                       v                       v                 v
            Index for Search      Back to Approval               Exit                 Exit with ID        Execute
                    │
                    v
            Pattern Analysis
                    │
                    v
         Update Workflow Cache
```

### Complex Requirements

1. **User-Friendly Display** - Show workflow in understandable format
2. **Interactive Editing** - Allow parameter modifications
3. **Smart Storage** - Organize workflows for easy retrieval
4. **Pattern Matching** - Find similar workflows for reuse
5. **Version Control** - Track workflow changes over time

### PocketFlow Implementation

#### 1. Presentation Flow

```python
class PresentWorkflowNode(Node):
    def exec(self, shared):
        workflow = shared["generated_workflow"]

        # Format for display
        shared["display_lines"] = []

        # Convert IR to CLI syntax for user understanding
        for i, node in enumerate(workflow["nodes"]):
            if i > 0:
                shared["display_lines"].append("  >>")

            line = f"{node['type']}"
            if node.get("params"):
                params_str = " ".join([f"--{k}={v}" for k, v in node["params"].items()])
                line += f" {params_str}"

            shared["display_lines"].append(line)

        # Check if we need cost estimation
        has_llm = any("llm" in node["type"] for node in workflow["nodes"])

        if has_llm:
            return "estimate_cost"
        else:
            return "show_approval"

class EstimateCostNode(Node):
    def __init__(self, token_counter, pricing_db):
        super().__init__()
        self.token_counter = token_counter
        self.pricing_db = pricing_db

    def exec(self, shared):
        workflow = shared["generated_workflow"]

        total_tokens = 0
        total_cost = 0.0
        cost_breakdown = []

        for node in workflow["nodes"]:
            if "llm" in node["type"]:
                # Estimate tokens from parameters
                prompt = node.get("params", {}).get("prompt", "")
                tokens = self.token_counter.count(prompt)

                # Get pricing
                model = node.get("params", {}).get("model", "gpt-3.5-turbo")
                price_per_1k = self.pricing_db.get_price(model)

                cost = (tokens / 1000) * price_per_1k

                cost_breakdown.append({
                    "node": node["type"],
                    "tokens": tokens,
                    "cost": cost,
                    "model": model
                })

                total_tokens += tokens
                total_cost += cost

        shared["cost_estimate"] = {
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "breakdown": cost_breakdown
        }

        return "show_approval"
```

#### 2. Interactive Approval Flow

```python
class ShowApprovalNode(Node):
    def exec(self, shared):
        # Display workflow
        print("\n" + "="*50)
        print("Generated Workflow:")
        print("="*50)

        for line in shared["display_lines"]:
            print(line)

        # Show cost if available
        if "cost_estimate" in shared:
            cost = shared["cost_estimate"]
            print(f"\nEstimated Cost: ${cost['total_cost']:.4f}")
            print(f"Total Tokens: {cost['total_tokens']:,}")

        # Show options
        print("\nOptions:")
        print("1. Approve and save")
        print("2. Modify parameters")
        print("3. Run without saving")
        print("4. Save as draft")
        print("5. Reject")

        # Get user input
        choice = shared.get("user_choice") or input("\nYour choice (1-5): ")

        routes = {
            "1": "approve",
            "2": "modify",
            "3": "run_once",
            "4": "save_draft",
            "5": "reject"
        }

        return routes.get(choice, "invalid_choice")

class ModifyParametersNode(Node):
    def __init__(self):
        super().__init__(max_retries=3)  # User might make mistakes

    def exec(self, shared):
        workflow = shared["generated_workflow"]

        print("\nCurrent parameters:")
        for i, node in enumerate(workflow["nodes"]):
            if node.get("params"):
                print(f"\n[{i}] {node['type']}:")
                for key, value in node["params"].items():
                    print(f"  {key}: {value}")

        # Get modifications
        modifications = shared.get("modifications", {})

        if not modifications:
            node_idx = input("\nNode index to modify (or 'done'): ")
            if node_idx == "done":
                return "validate_changes"

            param_name = input("Parameter name: ")
            new_value = input("New value: ")

            modifications[int(node_idx)] = {param_name: new_value}

        # Apply modifications
        for idx, params in modifications.items():
            workflow["nodes"][idx]["params"].update(params)

        shared["modified_workflow"] = workflow
        return "validate_changes"

    def exec_fallback(self, shared, exc):
        print(f"\nError modifying parameters: {exc}")
        return "show_approval"  # Back to approval
```

#### 3. Storage and Indexing Flow

```python
class ValidateWorkflowNameNode(Node):
    def exec(self, shared):
        suggested_name = shared.get("workflow_name")

        if not suggested_name:
            # Generate from user query
            query = shared.get("original_query", "")
            suggested_name = self._generate_name(query)

        print(f"\nSuggested name: {suggested_name}")

        name = input("Workflow name (Enter to accept): ").strip()
        if not name:
            name = suggested_name

        # Validate name
        if not self._is_valid_name(name):
            shared["name_error"] = "Invalid name. Use only letters, numbers, dash, underscore."
            return "retry_name"

        shared["workflow_name"] = name
        return "check_duplicates"

    def _generate_name(self, query):
        # Simple name generation
        words = query.lower().split()[:3]
        name = "-".join(words)
        return name[:30]  # Limit length

class CheckDuplicatesNode(Node):
    def __init__(self, storage):
        super().__init__()
        self.storage = storage

    def exec(self, shared):
        name = shared["workflow_name"]

        if self.storage.exists(name):
            existing = self.storage.load(name)

            print(f"\nWorkflow '{name}' already exists.")
            print("Options:")
            print("1. Overwrite")
            print("2. Create new version")
            print("3. Choose different name")

            choice = input("Your choice (1-3): ")

            if choice == "1":
                shared["overwrite"] = True
                return "save"
            elif choice == "2":
                shared["workflow_name"] = self._version_name(name)
                return "save"
            else:
                return "retry_name"
        else:
            return "save"

    def _version_name(self, name):
        # Add version number
        version = 2
        while self.storage.exists(f"{name}-v{version}"):
            version += 1
        return f"{name}-v{version}"

class SaveWorkflowNode(Node):
    def __init__(self, storage):
        super().__init__(max_retries=3)
        self.storage = storage

    def exec(self, shared):
        name = shared["workflow_name"]
        workflow = shared.get("modified_workflow", shared["generated_workflow"])

        # Add metadata
        workflow["metadata"] = {
            "name": name,
            "created": datetime.now().isoformat(),
            "query": shared.get("original_query", ""),
            "approved": True,
            "version": 1,
            "tags": self._extract_tags(workflow),
            "description": shared.get("description", "")
        }

        # Save to storage
        path = self.storage.save(name, workflow)
        shared["saved_path"] = path

        return "index_workflow"

    def _extract_tags(self, workflow):
        # Auto-tag based on nodes used
        tags = set()
        for node in workflow["nodes"]:
            node_type = node["type"]
            if "github" in node_type:
                tags.add("github")
            elif "llm" in node_type:
                tags.add("ai")
            elif "file" in node_type:
                tags.add("file-io")
        return list(tags)
```

#### 4. Pattern Analysis Flow

```python
class IndexWorkflowNode(Node):
    def __init__(self, indexer):
        super().__init__()
        self.indexer = indexer

    def exec(self, shared):
        workflow = shared["saved_workflow"]

        # Extract patterns for future matching
        patterns = {
            "nodes": [n["type"] for n in workflow["nodes"]],
            "params": self._extract_param_patterns(workflow),
            "flow_signature": self._compute_signature(workflow),
            "complexity": len(workflow["nodes"])
        }

        # Index for search
        self.indexer.add(
            name=workflow["metadata"]["name"],
            patterns=patterns,
            tags=workflow["metadata"]["tags"],
            query=workflow["metadata"]["query"]
        )

        return "analyze_similar"

    def _compute_signature(self, workflow):
        # Create a signature for similarity matching
        node_types = [n["type"] for n in workflow["nodes"]]
        return "-".join(sorted(set(node_types)))

class AnalyzeSimilarWorkflowsNode(Node):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer

    def exec(self, shared):
        workflow = shared["saved_workflow"]

        # Find similar workflows
        similar = self.analyzer.find_similar(
            workflow,
            threshold=0.8,
            limit=5
        )

        if similar:
            shared["similar_workflows"] = similar

            # Learn patterns for future generation
            common_patterns = self.analyzer.extract_common_patterns(similar)
            shared["learned_patterns"] = common_patterns

            return "update_cache"
        else:
            return "complete"
```

### Why Traditional Code Struggles

```python
# Traditional approach becomes a tangled mess
def approve_and_save_workflow(workflow, storage):
    # Display (mixed with logic)
    print("Workflow:")
    for node in workflow["nodes"]:
        print(f"  {node}")

    # Cost estimation (where's error handling?)
    if has_llm_nodes(workflow):
        cost = estimate_cost(workflow)  # What if this fails?
        print(f"Cost: ${cost}")

    # Approval (deeply nested)
    while True:
        choice = input("Approve? (y/n/m): ")

        if choice == "y":
            # Save (but what about duplicates?)
            name = input("Name: ")

            if storage.exists(name):
                # Now what? More nesting...
                overwrite = input("Overwrite? ")
                # ...
        elif choice == "m":
            # Modify (getting complex)
            # How to validate changes?
            # How to re-display?
```

Issues:
- User interaction mixed with business logic
- No clear flow between states
- Error handling scattered or missing
- Hard to test (how to mock user input?)
- No separation of concerns

### Advanced PocketFlow Patterns

#### Parallel Validation

```python
class ParallelValidationNode(AsyncNode):
    async def exec_async(self, shared):
        workflow = shared["workflow"]

        # Validate multiple aspects concurrently
        results = await asyncio.gather(
            self._validate_syntax(workflow),
            self._validate_costs(workflow),
            self._validate_permissions(workflow),
            self._check_rate_limits(workflow)
        )

        all_valid = all(r["valid"] for r in results)
        shared["validation_results"] = results

        return "valid" if all_valid else "show_errors"
```

#### Learning from User Choices

```python
class LearnFromChoicesNode(Node):
    def exec(self, shared):
        if shared.get("user_rejected"):
            # Learn what users don't like
            rejection_reason = shared.get("rejection_reason")
            workflow_features = self._extract_features(shared["workflow"])

            self.ml_model.record_rejection(
                features=workflow_features,
                reason=rejection_reason
            )
        elif shared.get("user_modified"):
            # Learn common modifications
            original = shared["generated_workflow"]
            modified = shared["modified_workflow"]

            diff = self._compute_diff(original, modified)
            self.ml_model.record_modification(diff)

        return "continue"
```

### Real-World Benefits

#### 1. Smart Workflow Suggestions
```
Similar workflows found:
- "github-issue-analyzer" (90% match)
- "pr-review-helper" (85% match)

Would you like to use one of these as a template?
```

#### 2. Cost Transparency
```
Workflow Cost Breakdown:
- analyze-with-gpt4: 2,341 tokens ($0.0234)
- summarize-with-claude: 1,822 tokens ($0.0146)
Total: $0.0380 per run
```

#### 3. Version Control
```
Workflow: github-issue-fixer
Versions:
  v1 - Created 2024-01-15 (original)
  v2 - Modified 2024-01-16 (added error handling)
  v3 - Modified 2024-01-17 (switched to GPT-4) <- current
```

### Conclusion

The approval and storage system is not just saving files - it's a complete user interaction and knowledge management pipeline that needs to:
- Present information clearly
- Handle user interactions gracefully
- Manage storage and versioning
- Learn from user behavior
- Enable workflow discovery

PocketFlow provides:
- Clear separation of presentation, interaction, and storage
- Explicit flow between user decision points
- Testable components (can mock user input)
- Error recovery for each operation
- Extensibility for ML and analytics

The traditional approach would mix all these concerns, creating an unmaintainable tangle of user interaction, business logic, and I/O operations.
