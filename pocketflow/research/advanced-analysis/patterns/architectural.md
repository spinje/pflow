# Architectural Patterns for pflow

This document extracts architectural patterns from Wave 1 repository analyses that are relevant to pflow's "Plan Once, Run Forever" philosophy. These patterns support deterministic execution, CLI-first workflow compilation, and simple node design.

## Linear Flow Composition

- **Found in**: [Tutorial-Codebase-Knowledge, Tutorial-Youtube-Made-Simple, Tutorial-Cold-Email-Personalization, PocketFlow-Tutorial-Website-Chatbot, Tutorial-AI-Paul-Graham]
- **Purpose**: Enables deterministic execution without complex control flow
- **Implementation**: Use the `>>` operator to chain nodes sequentially
- **Code Example**:
  ```python
  # From Tutorial-Codebase-Knowledge
  fetch_repo >> identify_abstractions >> analyze_relationships >> order_chapters >> write_chapters >> combine_tutorial

  # For pflow MVP
  read_file >> llm >> write_file
  ```
- **Task Mapping**:
  - Task 3 (Hello World Workflow) - Basic flow construction
  - Task 4 (IR-to-Flow Converter) - Target pattern for compilation

## Natural Shared Store Keys

- **Found in**: [All analyzed repositories]
- **Purpose**: Avoids key collisions without complex namespacing or proxy mapping
- **Implementation**: Use intuitive, descriptive key names that reflect the data's purpose
- **Code Example**:
  ```python
  # From Tutorial-AI-Paul-Graham
  shared["query"]           # User input
  shared["embeddings"]      # Processing result
  shared["final_response"]  # Output

  # For pflow
  shared["file_path"]       # CLI input
  shared["content"]         # File contents
  shared["response"]        # LLM output
  ```
- **Task Mapping**:
  - Task 9 (Shared Store & Proxy) - Natural keys often eliminate proxy need
  - Task 3 (Hello World) - Shared store initialization pattern

## Single-Purpose Node Design

- **Found in**: [All analyzed repositories]
- **Purpose**: Maintains clarity, testability, and reusability of workflow components
- **Implementation**: Each node performs exactly one task with clear inputs/outputs
- **Code Example**:
  ```python
  # From Tutorial-Youtube-Made-Simple
  class ProcessYouTubeURL(Node):
      def prep(self, shared):
          return shared.get("url", "")

      def exec(self, url):
          return get_video_info(url)  # Single purpose

      def post(self, shared, prep_res, exec_res):
          shared["video_info"] = exec_res
          return "default"
  ```
- **Task Mapping**:
  - Task 11 (File I/O Nodes) - Template for simple nodes
  - Task 12 (LLM Node) - Single responsibility pattern
  - Task 13 (GitHub Node) - Focused external API interaction

## Structured LLM Communication

- **Found in**: [PocketFlow-Tutorial-Danganronpa-Simulator, Tutorial-Cursor, Tutorial-AI-Paul-Graham, Tutorial-Youtube-Made-Simple]
- **Purpose**: Ensures deterministic and parseable LLM responses
- **Implementation**: Use YAML/JSON format requests with explicit schemas
- **Code Example**:
  ```python
  # From PocketFlow-Tutorial-Danganronpa-Simulator
  prompt = f"""
  Output Format (Strictly follow this YAML format):
  ```yaml
  decision: answer/explore
  reasoning: |
    Explain your decision
  selected_indices: [1, 3, 5]
  ```"""

  response = call_llm(prompt)
  result = yaml.safe_load(response)
  ```
- **Task Mapping**:
  - Task 17 (LLM Workflow Generation) - Pattern for IR generation
  - Task 18 (Prompt Templates) - Structured prompt format
  - Task 12 (LLM Node) - Reliable parsing approach

## Progressive State Building

- **Found in**: [Tutorial-Youtube-Made-Simple, Tutorial-Codebase-Knowledge, PocketFlow-Tutorial-Website-Chatbot]
- **Purpose**: Maintains full context throughout execution for debugging and tracing
- **Implementation**: Each node adds to shared store without removing previous data
- **Code Example**:
  ```python
  # From Tutorial-Youtube-Made-Simple
  # Initial: shared = {"url": "..."}
  # After node 1: shared["video_info"] = {...}
  # After node 2: shared["topics"] = [...]
  # After node 3: shared["chapters"] = [...]
  # Final state contains complete history
  ```
- **Task Mapping**:
  - Task 23 (Execution Tracing) - Natural audit trail
  - Task 3 (Execute Workflow) - State evolution pattern

## CLI-to-Shared-Store Pattern

- **Found in**: [Tutorial-Codebase-Knowledge, Tutorial-Cold-Email-Personalization]
- **Purpose**: Clean mapping from CLI arguments to workflow state
- **Implementation**: Direct translation of CLI flags to shared store keys
- **Code Example**:
  ```python
  # From Tutorial-Codebase-Knowledge
  parser.add_argument("--repo", help="GitHub repository URL")
  parser.add_argument("--max-abstractions", type=int, default=10)

  shared = {
      "repo_url": args.repo,
      "max_abstraction_num": args.max_abstractions,
  }
  ```
- **Task Mapping**:
  - Task 2 (CLI Setup) - Argument handling pattern
  - Task 8 (Shell Integration) - stdin integration approach

## Utility Function Separation

- **Found in**: [Tutorial-Cursor, Tutorial-AI-Paul-Graham, Tutorial-Cold-Email-Personalization]
- **Purpose**: Keeps nodes focused on orchestration while utilities handle implementation
- **Implementation**: Create a `utils/` directory with single-purpose functions
- **Code Example**:
  ```python
  # Node focuses on orchestration
  class LLMNode(Node):
      def exec(self, prompt):
          return call_llm(prompt)  # Delegate to utility

  # utils/call_llm.py handles actual API call
  def call_llm(prompt):
      # API interaction logic
  ```
- **Task Mapping**:
  - Task 15 (LLM API Client) - Utility pattern
  - Task 11-14 (All Node Tasks) - Separation of concerns

## Error-First Validation

- **Found in**: [Tutorial-Youtube-Made-Simple, Tutorial-Cursor]
- **Purpose**: Fail fast with clear error messages for better debugging
- **Implementation**: Validate inputs early in prep phase
- **Code Example**:
  ```python
  # From Tutorial-Youtube-Made-Simple
  def prep(self, shared):
      url = shared.get("url", "")
      if not url:
          raise ValueError("No YouTube URL provided")
      return url
  ```
- **Task Mapping**:
  - Task 9 (Shared Store Validation) - Input validation
  - All node implementation tasks - Error handling pattern

## Flow Factory Pattern

- **Found in**: [PocketFlow-Tutorial-Danganronpa-Simulator, PocketFlow-Tutorial-Website-Chatbot]
- **Purpose**: Programmatic flow creation from configuration or IR
- **Implementation**: Functions that create and wire nodes dynamically
- **Code Example**:
  ```python
  # From PocketFlow-Tutorial-Danganronpa-Simulator
  def create_character_decision_flow() -> AsyncFlow:
      decision_node = DecisionNode(max_retries=3, wait=1)
      return AsyncFlow(start=decision_node)

  # For pflow IR compilation
  def compile_ir_to_flow(ir_json):
      nodes = {}
      for node_def in ir_json["nodes"]:
          NodeClass = registry.get(node_def["type"])
          nodes[node_def["id"]] = NodeClass(**node_def.get("params", {}))

      for edge in ir_json["edges"]:
          nodes[edge["from"]] >> nodes[edge["to"]]

      return Flow(start=nodes[ir_json["start_node"]])
  ```
- **Task Mapping**:
  - Task 4 (IR-to-Flow Converter) - Core pattern for compilation

## History-Based Debugging

- **Found in**: [Tutorial-Cursor, PocketFlow-Tutorial-Website-Chatbot]
- **Purpose**: Provides audit trail for debugging complex workflows
- **Implementation**: Maintain action history in shared store
- **Code Example**:
  ```python
  # From Tutorial-Cursor
  shared["history"].append({
      "tool": "read_file",
      "params": {"file": "config.json"},
      "result": None  # Filled by action node
  })

  # For pflow tracing
  shared["_trace"].append({
      "node": "llm",
      "input": prep_res,
      "output": exec_res,
      "timestamp": time.time()
  })
  ```
- **Task Mapping**:
  - Task 23 (Execution Tracing) - Trace structure
  - Task 9 (Shared Store) - Debug information pattern

## Deterministic Retry Configuration

- **Found in**: [Tutorial-Codebase-Knowledge, PocketFlow-Tutorial-Danganronpa-Simulator]
- **Purpose**: Handle transient failures without compromising determinism
- **Implementation**: Configure retries at node instantiation, not runtime
- **Code Example**:
  ```python
  # From Tutorial-Codebase-Knowledge
  identify_abstractions = IdentifyAbstractions(max_retries=5, wait=20)
  analyze_relationships = AnalyzeRelationships(max_retries=5, wait=20)

  # Deterministic - same config always produces same retry behavior
  ```
- **Task Mapping**:
  - Task 32 (Deferred - Execution Config) - Retry pattern reference
  - Node instantiation for all node tasks

## Module Organization for CLI Tools

- **Found in**: [All analyzed repositories]
- **Purpose**: Clear separation enables easy discovery and testing
- **Implementation**: Consistent directory structure
- **Code Example**:
  ```
  pflow/
  ├── cli/              # CLI interface
  ├── nodes/            # Node implementations
  ├── planner/          # Natural language planning
  ├── runtime/          # Execution engine
  ├── registry/         # Node discovery
  └── utils/            # Shared utilities
  ```
- **Task Mapping**:
  - Task 5 (Node Discovery) - Where to scan for nodes
  - Task 2 (CLI Setup) - Module structure

## Template Variable Resolution

- **Found in**: [Tutorial-Cold-Email-Personalization, Tutorial-AI-Paul-Graham]
- **Purpose**: Enable dynamic prompts and parameters
- **Implementation**: String interpolation from shared store
- **Code Example**:
  ```python
  # CLI usage
  pflow llm --prompt="Analyze this issue: $issue_data"

  # Resolution at runtime
  prompt = template.replace("$issue_data", shared["issue_data"])
  ```
- **Task Mapping**:
  - Task 19 (Template Resolver) - Variable substitution
  - Task 18 (Prompt Templates) - Template usage

These patterns provide a solid foundation for pflow's implementation, emphasizing simplicity, determinism, and CLI-friendly design. The recurring themes across all repositories validate pflow's architectural choices and provide concrete implementation guidance for the MVP tasks.
