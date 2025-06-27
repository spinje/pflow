# Patterns Discovered

A consolidated collection of successful patterns and approaches discovered during task implementations. Each pattern represents a proven solution to a recurring problem.

**Before adding**: Read this entire file and search for related patterns to avoid duplicates.

---

## Pattern: Shared Store Proxy for Incompatible Nodes
- **Date**: 2024-01-15
- **Discovered in**: Task 1.2 (Example)
- **Problem**: Two nodes need to communicate but have incompatible data formats
- **Solution**: Create a proxy node that translates between formats using the shared store
- **Example**:
  ```python
  class TranslatorNode(Node):
      def exec(self, shared):
          # Get data from Node A's format
          raw_data = shared.get("node_a_output")

          # Transform to Node B's expected format
          transformed = {
              "text": raw_data["content"],
              "metadata": {"source": "node_a"}
          }

          # Put in format Node B expects
          shared["node_b_input"] = transformed
  ```
- **When to use**: When integrating nodes from different sources or with different data contracts
- **Benefits**: Maintains node independence while enabling communication

---

## Pattern: Test-As-You-Go Development
- **Date**: 2025-06-27
- **Discovered in**: Task 1.3
- **Problem**: Separate testing tasks/subtasks create redundancy and delay feedback on implementation quality
- **Solution**: Write tests immediately as part of the implementation task, not as a separate subtask
- **Example**:
  ```python
  # When implementing a new CLI command:
  # 1. Create the command in src/pflow/cli/command.py
  # 2. Immediately create tests/test_command.py
  # 3. Test and iterate until both code and tests pass
  # 4. Commit together as one unit of work
  ```
- **When to use**: Always - every new feature, function, or component should include tests in the same task
- **Benefits**:
  - Immediate validation of implementation
  - Faster feedback loop
  - Tests serve as documentation of intended behavior
  - Prevents accumulation of untested code
  - Reduces overall task count and complexity

---

<!-- New patterns are appended below this line -->
