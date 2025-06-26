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

<!-- New patterns are appended below this line -->
