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

## Pattern: Empty stdin handling with CliRunner
- **Date**: 2025-06-28
- **Discovered in**: Task 2.2
- **Problem**: Click's CliRunner simulates a non-tty stdin even when empty, causing false positive stdin detection
- **Solution**: Check if stdin has actual content before treating it as stdin input
- **Example**:
  ```python
  elif not sys.stdin.isatty():
      raw_input = sys.stdin.read().strip()
      if raw_input:  # Only use stdin if it has content
          if workflow:
              raise click.ClickException("Cannot specify both stdin and command arguments")
          source = "stdin"
      else:
          # Empty stdin, treat as command arguments
          raw_input = " ".join(workflow)
          source = "args"
  ```
- **When to use**: Any CLI command that accepts both stdin and other input methods (args, files)
- **Benefits**:
  - Prevents test failures with CliRunner
  - Allows proper fallback to other input methods
  - Maintains compatibility with both testing and production environments

---

## Pattern: Non-Conflicting CLI Operators
- **Date**: 2025-06-28
- **Discovered in**: Task 2.2
- **Problem**: Need operators for CLI syntax that don't conflict with shell or Click parsing
- **Solution**: Test operators systematically and choose ones without conflicts
- **Example**:
  ```python
  # Testing methodology:
  # 1. Test shell conflicts: echo "cmd1 OPERATOR cmd2"
  # 2. Test Click conflicts: create minimal CLI and test parsing

  # Operators with conflicts:
  # >> - Shell output redirection
  # >>> - Shell interprets as >> followed by >
  # -> - Click interprets as option due to leading dash
  # | - Shell pipe
  # < - Shell input redirection
  # & - Shell background process

  # Safe operators:
  # => - Arrow-like, no conflicts (RECOMMENDED)
  # |> - Pipe-like semantics, no conflicts
  # ~> - Wavy arrow, unique
  # :: - Double colon separator
  # ++ - Concatenation style
  # .. - Range/continuation style

  # Implementation with Click:
  @click.command(context_settings={"allow_interspersed_args": False})
  @click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
  def main(workflow):
      # Now => works without quotes: pflow node1 => node2
  ```
- **When to use**: Designing any CLI tool that needs operators between arguments
- **Benefits**:
  - No quoting required for users
  - Better user experience
  - Works in all shells
  - No special escaping needed

---

<!-- New patterns are appended below this line -->
