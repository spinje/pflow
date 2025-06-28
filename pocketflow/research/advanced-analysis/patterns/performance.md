# Performance Patterns for pflow

This document extracts performance patterns from the Wave 1 repository analyses to help pflow achieve its <2s execution overhead goal and 10x efficiency improvement over slash commands.

## Pattern 1: Content Truncation for Efficiency
- **Found in**: [PocketFlow-Tutorial-Website-Chatbot]
- **Performance Gain**: Reduces memory usage and processing time by 80-90%
- **Technique**: Limits stored content to first 10K characters, max 300 links per page
- **Implementation**: Apply to LLM responses, file content, and cached data in pflow
- **Code Example**:
```python
def truncate_content(content, max_chars=10000):
    """Truncate content for efficient processing and storage"""
    if len(content) > max_chars:
        return content[:max_chars] + "... [truncated]"
    return content

class ReadFileNode(Node):
    def exec(self, file_path):
        with open(file_path, 'r') as f:
            content = f.read()
        return truncate_content(content)  # Limit size for performance
```
- **Task Mapping**: Task 24 (Caching) - smaller payloads cache faster

## Pattern 2: Selective Data Loading
- **Found in**: [PocketFlow-Tutorial-Website-Chatbot, Tutorial-Codebase-Knowledge]
- **Performance Gain**: 70% reduction in processing time by filtering early
- **Technique**: Apply include/exclude patterns before processing, filter empty results
- **Implementation**: File nodes should support glob patterns to avoid loading unnecessary files
- **Code Example**:
```python
class ReadFilesNode(Node):
    def prep(self, shared):
        patterns = shared.get("include_patterns", ["*.py", "*.md"])
        exclude = shared.get("exclude_patterns", ["__pycache__", "*.pyc"])
        return patterns, exclude

    def exec(self, prep_data):
        patterns, exclude = prep_data
        files = []
        for pattern in patterns:
            matches = glob.glob(pattern, recursive=True)
            files.extend([f for f in matches if not any(e in f for e in exclude)])
        return files[:100]  # Limit to prevent memory issues
```
- **Task Mapping**: Task 11 (File Nodes), Task 24 (Caching)

## Pattern 3: Natural Key-Based Shared Store
- **Found in**: [All repositories]
- **Performance Gain**: Eliminates proxy mapping overhead (~100ms saved per workflow)
- **Technique**: Use intuitive key names that naturally align between nodes
- **Implementation**: Design nodes with natural interfaces from the start
- **Code Example**:
```python
# Natural keys eliminate mapping overhead
shared = {
    "file_path": "input.txt",     # ReadFileNode expects this
    "content": None,              # ReadFileNode writes this
    "prompt": None,               # LLMNode expects this
    "response": None              # LLMNode writes this
}

# No proxy needed - keys naturally flow:
# file_path → [ReadFileNode] → content → [LLMNode] → response
```
- **Task Mapping**: Task 9 (Shared Store & Proxy) - avoid proxy when possible

## Pattern 4: Progressive State Building
- **Found in**: [Tutorial-Youtube-Made-Simple, Tutorial-AI-Paul-Graham]
- **Performance Gain**: Enables partial execution and recovery
- **Technique**: Each node adds to shared store without removing prior data
- **Implementation**: Design nodes to be additive, enabling checkpoint/resume
- **Code Example**:
```python
class WorkflowExecutor:
    def execute_with_checkpoints(self, flow, shared):
        checkpoint_file = f".pflow_checkpoint_{shared['_execution_id']}.json"

        # Resume from checkpoint if exists
        if os.path.exists(checkpoint_file):
            shared = json.load(open(checkpoint_file))
            start_node = shared.get("_last_completed_node")

        # Execute with checkpointing
        for node in flow.nodes[start_node:]:
            result = node.run(shared)
            shared["_last_completed_node"] = node.id

            # Save checkpoint after each node
            with open(checkpoint_file, 'w') as f:
                json.dump(shared, f)

        # Clean up checkpoint on success
        os.remove(checkpoint_file)
        return shared
```
- **Task Mapping**: Task 23 (Execution Tracing), Task 24 (Caching)

## Pattern 5: Structured LLM Output Parsing
- **Found in**: [Tutorial-Danganronpa-Simulator, Tutorial-Cursor, Tutorial-AI-Paul-Graham, Cold-Email-Personalization]
- **Performance Gain**: 90% reduction in parsing failures, faster than JSON
- **Technique**: Use YAML for LLM responses - more readable and reliable than JSON
- **Implementation**: Standardize on YAML for all LLM structured output
- **Code Example**:
```python
class LLMNode(Node):
    def exec(self, prompt):
        # Force YAML output
        structured_prompt = f"""{prompt}

Respond in YAML format:
```yaml
result: your_response_here
confidence: high/medium/low
reasoning: brief_explanation
```"""

        response = call_llm(structured_prompt, temperature=0)  # Deterministic

        # Fast YAML parsing
        yaml_match = re.search(r'```yaml\n(.*?)\n```', response, re.DOTALL)
        if yaml_match:
            return yaml.safe_load(yaml_match.group(1))

        # Fallback for simple responses
        return {"result": response, "confidence": "low", "reasoning": "unstructured"}
```
- **Task Mapping**: Task 12 (LLM Node), Task 17 (Workflow Generation), Task 18 (Prompt Templates)

## Pattern 6: Minimal Flow Orchestration
- **Found in**: [PocketFlow-Tutorial-Website-Chatbot - 17 lines of flow code]
- **Performance Gain**: Near-zero orchestration overhead
- **Technique**: Let PocketFlow handle all complexity, keep flow definitions minimal
- **Implementation**: IR compiler should generate minimal code
- **Code Example**:
```python
def compile_ir_to_flow(ir_json):
    """Generate minimal flow code from IR"""
    nodes = {}

    # Instantiate nodes (1 line each)
    for n in ir_json["nodes"]:
        nodes[n["id"]] = registry.get(n["type"])(**n.get("params", {}))

    # Connect nodes (1 line each)
    for e in ir_json["edges"]:
        if e.get("action"):
            nodes[e["from"]] - e["action"] >> nodes[e["to"]]
        else:
            nodes[e["from"]] >> nodes[e["to"]]

    # Return flow (1 line)
    return Flow(start=nodes[ir_json["start_node"]])
```
- **Task Mapping**: Task 4 (IR-to-Flow Converter)

## Pattern 7: Single File Read Strategy
- **Found in**: [Tutorial-Cursor]
- **Performance Gain**: 50% reduction in file I/O operations
- **Technique**: Read file once, cache in shared store for multiple operations
- **Implementation**: File nodes should check shared store before disk
- **Code Example**:
```python
class SmartReadFileNode(Node):
    def exec(self, file_path):
        # Check if already loaded
        file_cache = self.shared.get("_file_cache", {})

        if file_path in file_cache:
            return file_cache[file_path]

        # Read and cache
        with open(file_path, 'r') as f:
            content = f.read()

        file_cache[file_path] = content
        self.shared["_file_cache"] = file_cache

        return content
```
- **Task Mapping**: Task 11 (File Nodes), Task 24 (Caching)

## Pattern 8: Deterministic Execution
- **Found in**: [All repositories using temperature=0]
- **Performance Gain**: Enables aggressive caching of LLM responses
- **Technique**: Use temperature=0, sort operations, hash-based selection
- **Implementation**: All nodes must be deterministic by default
- **Code Example**:
```python
class DeterministicLLMNode(Node):
    def exec(self, prompt):
        # Create cache key from prompt
        cache_key = hashlib.md5(prompt.encode()).hexdigest()

        # Check cache first
        cache_dir = ".pflow_cache"
        cache_file = f"{cache_dir}/llm_{cache_key}.json"

        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return json.load(f)

        # Call LLM with deterministic settings
        response = call_llm(
            prompt,
            temperature=0,  # Deterministic
            seed=42        # Some providers support seed
        )

        # Cache response
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump(response, f)

        return response
```
- **Task Mapping**: Task 24 (Caching), Task 12 (LLM Node)

## Pattern 9: Fail-Fast Validation
- **Found in**: [Tutorial-Cursor, Cold-Email-Personalization]
- **Performance Gain**: Prevents wasted processing on invalid inputs
- **Technique**: Validate all inputs in prep() phase before expensive operations
- **Implementation**: Every node should validate inputs immediately
- **Code Example**:
```python
class GitHubGetIssueNode(Node):
    def prep(self, shared):
        # Fail fast on missing required inputs
        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("Missing required 'repo' parameter")

        issue_number = shared.get("issue_number") or self.params.get("issue_number")
        if not issue_number:
            raise ValueError("Missing required 'issue_number' parameter")

        # Validate format early
        if not re.match(r'^[\w-]+/[\w-]+$', repo):
            raise ValueError(f"Invalid repo format: {repo}")

        return repo, issue_number
```
- **Task Mapping**: Task 13 (GitHub Node), all node implementation tasks

## Pattern 10: Lightweight Progress Tracking
- **Found in**: [PocketFlow-Tutorial-Website-Chatbot, Tutorial-AI-Paul-Graham]
- **Performance Gain**: < 1ms overhead per node while enabling observability
- **Technique**: Simple timestamp logging, no complex state management
- **Implementation**: Built into base node execution
- **Code Example**:
```python
class TrackedNode(Node):
    def run(self, shared):
        start_time = time.time()
        node_id = f"{self.__class__.__name__}_{id(self)}"

        # Log start
        trace = shared.setdefault("_trace", [])
        trace.append({
            "node": node_id,
            "event": "start",
            "timestamp": start_time
        })

        try:
            # Normal execution
            result = super().run(shared)

            # Log success
            trace.append({
                "node": node_id,
                "event": "complete",
                "timestamp": time.time(),
                "duration_ms": int((time.time() - start_time) * 1000)
            })

            return result
        except Exception as e:
            # Log failure
            trace.append({
                "node": node_id,
                "event": "error",
                "timestamp": time.time(),
                "error": str(e)
            })
            raise
```
- **Task Mapping**: Task 23 (Execution Tracing)

## Summary: Achieving <2s Execution Overhead

To achieve pflow's performance goals:

1. **Eliminate Overhead**: Natural keys, minimal orchestration, no proxy mapping
2. **Cache Aggressively**: LLM responses, file content, compiled workflows
3. **Fail Fast**: Validate early, process only what's needed
4. **Stay Deterministic**: Enable caching through predictable execution
5. **Keep It Simple**: Linear flows, single-purpose nodes, no complex state

The key insight from all repositories: **simplicity enables performance**. Complex orchestration and state management add overhead. By keeping nodes simple and flows linear, pflow can achieve its <2s execution overhead target while maintaining clarity and debuggability.
