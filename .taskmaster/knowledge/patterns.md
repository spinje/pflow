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

## Pattern: Click Validation Override for Custom Errors
- **Date**: 2025-01-28
- **Discovered in**: Task 2.3
- **Problem**: Click's built-in validators (like Path(exists=True)) run during parsing phase, preventing custom error messages
- **Solution**: Use basic types instead of Click's validation types and handle validation manually in the command function
- **Example**:
  ```python
  # DON'T DO THIS - Click shows generic error
  @click.option("--file", type=click.Path(exists=True))
  def main(file):
      # Never reached if file doesn't exist
      pass

  # DO THIS - Custom error messages
  @click.option("--file", type=str)
  def main(file):
      if file:
          try:
              content = Path(file).read_text()
          except FileNotFoundError:
              raise click.ClickException("cli: File not found. Check the path.")
  ```
- **When to use**: When you need specific error message formatting or namespace prefixes for consistency
- **Benefits**:
  - Full control over error message content
  - Consistent error formatting across the application
  - Better user experience with helpful suggestions

---

## Pattern: Context Manager for Dynamic sys.path Modification
- **Date**: 2025-06-29
- **Discovered in**: Task 5.1
- **Problem**: Dynamic imports require modifying sys.path but this pollutes global state and can cause issues if not restored
- **Solution**: Use a context manager to temporarily modify sys.path with guaranteed restoration
- **Example**:
  ```python
  @contextmanager
  def temporary_syspath(paths: List[Path]):
      """Temporarily add paths to sys.path for imports."""
      original_path = sys.path.copy()
      try:
          # Add paths at the beginning for priority
          for path in reversed(paths):
              sys.path.insert(0, str(path))
          yield
      finally:
          sys.path = original_path

  # Usage:
  with temporary_syspath([project_root, plugin_dir]):
      module = importlib.import_module('some.dynamic.module')
  ```
- **When to use**: Any time you need dynamic imports from non-standard locations
- **Benefits**:
  - No global state pollution
  - Exception-safe (path restored even on errors)
  - Can add multiple paths with priority ordering
  - Clear scope of path modifications

---

## Pattern: Registry Storage Without Key Duplication
- **Date**: 2025-06-29
- **Discovered in**: Task 5.2
- **Problem**: When converting a list of objects to a dictionary keyed by an identifier, the identifier gets duplicated in both key and value
- **Solution**: Remove the identifier field from the value before storing since the key already provides it
- **Example**:
  ```python
  # Convert list to dict, removing 'name' from values
  nodes = {}
  for item in items:
      name = item.get("name")
      # Store without the key field
      node_data = {k: v for k, v in item.items() if k != "name"}
      nodes[name] = node_data
  ```
- **When to use**: Any registry or index where objects are keyed by one of their properties
- **Benefits**:
  - Cleaner data structure without redundancy
  - Smaller storage footprint
  - No risk of key/value mismatch
  - Simpler updates (only one place to change)

---

## Pattern: Graceful JSON Configuration Loading
- **Date**: 2025-06-29
- **Discovered in**: Task 5.2
- **Problem**: JSON configuration files might be missing, empty, corrupt, or have permission issues, causing application crashes
- **Solution**: Chain multiple fallbacks with specific handling for each failure mode
- **Example**:
  ```python
  def load_config(self) -> dict:
      if not self.path.exists():
          logger.debug(f"Config file not found at {self.path}")
          return {}

      try:
          content = self.path.read_text()
          if not content.strip():
              logger.debug("Config file is empty")
              return {}

          data = json.loads(content)
          logger.info(f"Loaded {len(data)} items from config")
          return data
      except json.JSONDecodeError as e:
          logger.warning(f"Failed to parse JSON: {e}")
          return {}
      except Exception as e:
          logger.warning(f"Error reading config: {e}")
          return {}
  ```
- **When to use**: Loading any user-editable or optional configuration files
- **Benefits**:
  - Application never crashes due to config issues
  - Clear logging helps debugging
  - Consistent fallback behavior
  - Easy to extend with migration logic

---

## Pattern: PocketFlow for Internal Orchestration
- **Date**: 2025-06-29
- **Discovered in**: Architecture analysis
- **Problem**: Complex multi-step operations with I/O and error handling lead to deeply nested try/catch blocks and manual retry loops
- **Solution**: Use PocketFlow as an internal orchestration framework for complex operations while keeping simple utilities as traditional code
- **Example**:
  ```python
  # Instead of nested traditional code:
  def compile_workflow(ir_path):
      try:
          with open(ir_path) as f:
              try:
                  ir_json = json.load(f)
                  try:
                      validate(ir_json)
                      # More nesting...
                  except ValidationError:
                      # Handle...
              except JSONError:
                  # Handle...
      except IOError:
          # Handle...

  # Use PocketFlow orchestration:
  class LoadIRNode(Node):
      def __init__(self):
          super().__init__(max_retries=3)  # Built-in retry!

      def exec(self, shared):
          with open(shared["ir_path"]) as f:
              shared["ir_json"] = json.load(f)
          return "validate"

      def exec_fallback(self, shared, exc):
          shared["error"] = f"Failed to load: {exc}"
          return "error"

  # Visual flow
  load >> validate >> compile >> execute
  ```
- **When to use**: Components with:
  - Multiple discrete steps with data flow
  - External dependencies (file I/O, network, APIs)
  - Multiple execution paths (branching)
  - Retry/fallback requirements
  - State accumulation through process
- **When NOT to use**:
  - Simple utilities or pure functions (unnecessary complexity)
  - Performance-critical code paths (method call overhead)
  - Components with linear flow and no error cases
- **Benefits**:
  - Built-in retry mechanism for I/O operations
  - Visual flow representation with >> operator
  - Isolated, testable nodes
  - Explicit error handling paths
  - No manual retry loops or nested error handling
  - Proves PocketFlow works by using it ourselves
- **Implementation Guides**:
  - [Task 4: IR Compiler](../../.taskmaster/tasks/task_4/pocketflow-implementation-guide.md)
  - [Task 8: Shell Integration](../../.taskmaster/tasks/task_8/pocketflow-implementation-guide.md)
  - [Task 17: Workflow Generator](../../.taskmaster/tasks/task_17/pocketflow-implementation-guide.md)
  - [Task 20: Storage System](../../.taskmaster/tasks/task_20/pocketflow-implementation-guide.md)
  - [Task 22: Runtime Engine](../../.taskmaster/tasks/task_22/pocketflow-implementation-guide.md)
  - [Task 23: Tracing System](../../.taskmaster/tasks/task_23/pocketflow-implementation-guide.md)

---

<!-- New patterns are appended below this line -->

## Pattern: Layered Validation with Custom Business Logic
- **Date**: 2025-06-29
- **Discovered in**: Task 6.1
- **Problem**: JSON Schema validation alone cannot enforce complex business rules like referential integrity or uniqueness constraints
- **Solution**: Use a three-layer validation approach that separates concerns
- **Example**:
  ```python
  def validate_ir(data: Union[Dict, str]) -> None:
      # Layer 1: JSON parsing (if string input)
      if isinstance(data, str):
          try:
              data = json.loads(data)
          except json.JSONDecodeError as e:
              raise ValueError(f"Invalid JSON: {e}")

      # Layer 2: Schema validation (structure and types)
      validator = Draft7Validator(SCHEMA)
      errors = list(validator.iter_errors(data))
      if errors:
          raise ValidationError(format_error(errors[0]))

      # Layer 3: Business logic validation
      _validate_node_references(data)  # Check edges reference existing nodes
      _validate_duplicate_ids(data)     # Check for unique IDs
  ```
- **When to use**: Any validation scenario where JSON Schema alone is insufficient:
  - Referential integrity checks (foreign keys)
  - Uniqueness constraints across arrays
  - Cross-field dependencies
  - Complex business rules
- **Benefits**:
  - Clear separation of structural vs business validation
  - Each layer can be tested independently
  - Easy to add new business rules without touching schema
  - Better error messages for each type of failure
  - Reusable pattern for any JSON validation task

---

## Pattern: Tempfile-Based Dynamic Test Data
- **Date**: 2025-06-29
- **Discovered in**: Task 5.3
- **Problem**: Testing file-based operations (scanners, parsers) with edge cases requires complex fixture management
- **Solution**: Create test files dynamically in each test using tempfile.TemporaryDirectory()
- **Example**:
  ```python
  def test_scanner_edge_case(self):
      with tempfile.TemporaryDirectory() as tmpdir:
          # Create test file with exact content needed
          test_file = Path(tmpdir) / "test.py"
          test_file.write_text('''
  from pocketflow import BaseNode

  class TestNode(BaseNode):
      """Test node with specific characteristics."""
      def exec(self, shared):
          pass
  ''')

          # Test the scanner
          results = scan_for_nodes([Path(tmpdir)])
          assert len(results) == 1
  ```
- **When to use**: Testing any file-based operations, especially with many edge cases
- **When NOT to use**:
  - When debugging test failures (temp files vanish, making inspection impossible)
  - Performance-critical test suites (file I/O is slow)
  - Simple test data that can be mocked or passed as strings
- **Benefits**:
  - Each test is self-contained with its data
  - No fixture directory management
  - Tests are more readable with inline data
  - Automatic cleanup via context manager
- **Drawbacks**:
  - Makes debugging test failures nearly impossible (files vanish)
  - Significant performance overhead from file I/O
  - Platform-dependent behavior (Windows vs Unix paths)

---
