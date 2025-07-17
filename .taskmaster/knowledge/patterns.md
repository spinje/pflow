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

## Pattern: PocketFlow for Complex AI Orchestration (Task 17 Only)
- **Date**: 2025-06-29 (Revised)
- **Discovered in**: Architecture analysis and refinement
- **Problem**: Natural language planning with LLMs requires complex retry strategies, self-correcting loops, and branching paths that lead to deeply nested code
- **Solution**: Use PocketFlow ONLY for Task 17 (Natural Language Planner) where complex orchestration genuinely adds value
- **Example**:
  ```python
  # Task 17: Natural Language Planner needs complex orchestration
  class GenerateWorkflowNode(Node):
      def __init__(self):
          super().__init__(max_retries=3)  # Built-in retry!

      def exec(self, shared):
          response = call_llm(shared["prompt"], shared["context"])
          shared["workflow"] = response
          return "validate"

      def exec_fallback(self, shared, exc):
          # Progressive enhancement on failure
          shared["prompt"] = enhance_prompt(shared["prompt"], exc)
          return "retry" if self.cur_retry < 3 else "error"

  class ValidateWorkflowNode(Node):
      def exec(self, shared):
          if validate_workflow(shared["workflow"]):
              return "success"
          else:
              # Self-correcting loop
              shared["validation_errors"] = get_errors(shared["workflow"])
              return "regenerate"

  # Visual flow with complex branching
  generate >> validate >> success
  generate - "error" >> fallback_strategy
  validate - "invalid" >> regenerate >> validate
  ```
- **When to use**: ONLY for components with ALL of these characteristics:
  - Multiple LLM API calls with different retry strategies
  - Self-correcting validation loops
  - Complex branching based on external responses
  - Progressive enhancement on failures
  - Multiple fallback paths
- **When NOT to use** (use traditional Python instead):
  - Simple I/O operations (file reading, API calls)
  - Linear execution flows
  - Basic error handling
  - Pure transformations (IR compilation, JSON parsing)
  - User interactions (approval flows)
  - Observability/tracing
- **Benefits for Task 17**:
  - Built-in retry mechanism for flaky LLM APIs
  - Visual representation of complex planning flow
  - Isolated nodes for testing different strategies
  - Explicit paths for all failure modes
  - Progressive prompt enhancement support
- **Architectural Decision**: Originally planned for 6 tasks, refined to only Task 17 after recognizing that other tasks are straightforward enough for traditional Python patterns

---

## Pattern: Structured Logging with Phase Tracking
- **Date**: 2025-06-29
- **Discovered in**: Task 4.1
- **Problem**: Multi-phase operations (compilation, validation, execution) need clear debugging trails and phase-specific error context
- **Solution**: Use Python's logging extra dict to attach structured metadata including phase information
- **Example**:
  ```python
  import logging

  logger = logging.getLogger(__name__)

  # Log with phase context
  logger.debug("Starting IR compilation", extra={"phase": "init"})
  logger.debug("IR structure validated", extra={
      "phase": "validation",
      "node_count": len(ir_dict["nodes"]),
      "edge_count": len(ir_dict["edges"])
  })
  logger.error("Compilation failed", extra={
      "phase": "node_creation",
      "node_id": "failing_node",
      "error_type": "ImportError"
  })

  # In tests, verify with caplog:
  for record in caplog.records:
      if "Starting IR compilation" in record.message:
          assert record.phase == "init"
  ```
- **When to use**: Any multi-step process where tracking progress and debugging failures requires phase context:
  - Compilers and parsers
  - Validation pipelines
  - Workflow execution engines
  - Any process with distinct stages
- **Benefits**:
  - Structured data enables log analysis and filtering
  - Phase tracking helps pinpoint where failures occur
  - Extra attributes accessible in tests via caplog
  - Compatible with log aggregation systems (ELK, Datadog)
  - Clear separation between message and metadata

---

## Pattern: Truthiness-Safe Parameter Fallback
- **Date**: 2025-06-29
- **Discovered in**: Task 11.1
- **Problem**: Python's `or` operator treats empty strings, 0, False, and None as falsy, causing incorrect fallbacks when these are valid values
- **Solution**: Check for key existence explicitly instead of relying on truthiness
- **Example**:
  ```python
  # DON'T DO THIS - treats empty string as missing
  content = shared.get("content") or self.params.get("content")
  if content is None:
      raise ValueError("Missing content")

  # DO THIS - properly handles empty string as valid
  if "content" in shared:
      content = shared["content"]
  elif "content" in self.params:
      content = self.params["content"]
  else:
      raise ValueError("Missing required 'content'")
  ```
- **When to use**: Always when parameters could have valid falsy values:
  - Text content that could be empty strings
  - Numbers that could be 0
  - Booleans that need to distinguish False from missing
  - Any optional parameter with a falsy default
- **Benefits**:
  - Correctly handles all valid Python values
  - Clear distinction between "not provided" and "provided as falsy"
  - Prevents subtle bugs in parameter handling
  - More explicit about intent

---

## Pattern: Safety Flags Must Be Explicitly Set in Shared Store
- **Date**: 2025-06-29
- **Discovered in**: Task 11.2
- **Problem**: Destructive operations (delete, overwrite) need safety mechanisms that can't be accidentally triggered by default parameters or config files
- **Solution**: Require safety confirmation flags to be explicitly set in shared store, with no fallback to params
- **Example**:
  ```python
  def prep(self, shared: dict) -> tuple[str, bool]:
      # File path can come from shared or params
      file_path = shared.get("file_path") or self.params.get("file_path")
      if not file_path:
          raise ValueError("Missing required 'file_path'")

      # Safety flag MUST come from shared store only
      if "confirm_delete" not in shared:
          raise ValueError("Missing required 'confirm_delete' in shared store. "
                         "This safety flag must be explicitly set in shared store.")

      confirm_delete = shared["confirm_delete"]
      # Note: We do NOT fallback to self.params here

      return (str(file_path), bool(confirm_delete))
  ```
- **When to use**:
  - Any destructive file operations (delete, overwrite, truncate)
  - Database operations that modify or drop data
  - Any irreversible action that could cause data loss
  - Operations that could affect system stability
- **Benefits**:
  - Prevents accidental operations from config files or defaults
  - Forces explicit user intent for dangerous operations
  - Clear error messages guide correct usage
  - Audit trail shows deliberate action

---

## Pattern: PocketFlow Node Error Handling for Automatic Retry
- **Date**: 2025-07-07
- **Discovered in**: PocketFlow anti-pattern investigation
- **Problem**: File operations and other nodes need robust retry behavior for transient errors (temporary locks, network issues, etc.)
- **Solution**: Let exceptions bubble up in exec() method, handle final errors in exec_fallback() after retries exhausted
- **Example**:
  ```python
  # CORRECT - Enables automatic retry
  class ReadFileNode(Node):
      def __init__(self):
          super().__init__(max_retries=3, wait=0.1)

      def exec(self, prep_res: tuple[str, str]) -> str:
          """Execute file read - let exceptions bubble up for retry."""
          file_path, encoding = prep_res

          # No try/except - let exceptions bubble up!
          with open(file_path, encoding=encoding) as f:
              content = f.read()

          return content  # Only return success value

      def exec_fallback(self, prep_res: tuple[str, str], exc: Exception) -> str:
          """Handle errors AFTER all retries exhausted."""
          file_path, _ = prep_res

          if isinstance(exc, FileNotFoundError):
              return f"Error: File '{file_path}' does not exist"
          elif isinstance(exc, PermissionError):
              return f"Error: Permission denied for '{file_path}'"
          elif isinstance(exc, UnicodeDecodeError):
              return f"Error: Cannot read file with specified encoding"
          else:
              return f"Error: Could not read file: {exc!s}"

      def post(self, shared: dict, prep_res: Any, exec_res: str) -> str:
          """Process results - check if error occurred."""
          if exec_res.startswith("Error:"):
              shared["error"] = exec_res
              return "error"
          else:
              shared["content"] = exec_res
              return "default"

  # For validation errors that should NOT retry
  from src.pflow.nodes.file.exceptions import NonRetriableError

  class DeleteFileNode(Node):
      def exec(self, prep_res: tuple[str, bool]) -> str:
          file_path, confirm_delete = prep_res

          # Validation error - will not retry
          if not confirm_delete:
              raise NonRetriableError(
                  f"Deletion of '{file_path}' not confirmed"
              )

          # This WILL retry on failure
          os.remove(file_path)
          return f"Successfully deleted '{file_path}'"
  ```
- **When to use**: ALWAYS in every PocketFlow node implementation - this is the fundamental pattern
- **Benefits**:
  - Automatic retry for transient errors (file locks, network issues, etc.)
  - Clean separation of success path from error handling
  - Framework handles retry complexity (exponential backoff, max attempts)
  - Better reliability without manual retry loops
  - Consistent error handling across all nodes
- **Testing Pattern**:
  ```python
  # Test retry behavior
  def test_retry_on_transient_error():
      node = ReadFileNode()
      shared = {"file_path": "/test/file.txt"}

      with patch("builtins.open") as mock_open:
          # Fail twice, then succeed
          mock_open.side_effect = [
              PermissionError("Locked"),
              PermissionError("Still locked"),
              mock_open(read_data="content")
          ]

          action = node.run(shared)

          assert action == "default"
          assert mock_open.call_count == 3

  # Test non-retriable errors
  def test_validation_error_no_retry():
      node = DeleteFileNode()
      shared = {"file_path": "/test.txt", "confirm_delete": False}

      with pytest.raises(NonRetriableError):
          node.exec(node.prep(shared))
  ```
- **Implementation Checklist**:
  - [ ] Inherit from `Node` (not `BaseNode`) for retry support
  - [ ] NO try/except blocks in `exec()` method
  - [ ] Return only success values from `exec()`
  - [ ] Implement `exec_fallback()` for error messages
  - [ ] Use `NonRetriableError` for validation failures
  - [ ] Test both retry and non-retry scenarios
  - [ ] Verify `post()` detects errors correctly

---

## Pattern: Self-Contained Test Workflows
- **Date**: 2024-12-19
- **Discovered in**: Task 8.2
- **Problem**: Test workflows using nodes like write-file fail when they depend on data from shared store that isn't populated in tests
- **Solution**: Create test workflows with all required data embedded in node params, making them completely self-contained
- **Example**:
  ```python
  # DON'T DO THIS - depends on shared store data
  workflow = {
      "ir_version": "0.1.0",
      "nodes": [{
          "id": "writer",
          "type": "write-file",
          "params": {"file_path": "/tmp/out.txt"}  # Missing content!
      }],
      "edges": [],
      "start_node": "writer"
  }

  # DO THIS - self-contained with all data
  workflow = {
      "ir_version": "0.1.0",
      "nodes": [{
          "id": "writer",
          "type": "write-file",
          "params": {
              "file_path": str(tmp_path / "output.txt"),
              "content": "Test content from workflow"  # Content in params
          }
      }],
      "edges": [],
      "start_node": "writer"
  }
  ```
- **When to use**: Any test that executes actual workflows, especially:
  - CLI integration tests
  - Subprocess tests simulating real usage
  - Backward compatibility tests
  - End-to-end workflow tests
- **Benefits**:
  - Tests are predictable and repeatable
  - No hidden dependencies on shared store state
  - Easier to understand test intent
  - Can verify file creation or other side effects
  - Works in isolation without complex setup

---

<!-- New patterns are appended below this line -->

## Pattern: Connection Tracking in Mock Nodes
- **Date**: 2025-06-29
- **Discovered in**: Task 4.3
- **Problem**: Testing PocketFlow node wiring requires verifying connections without executing real node logic
- **Solution**: Override >> and - operators in mock nodes to track connections in a list
- **Example**:
  ```python
  class MockNode(BaseNode):
      def __init__(self):
          super().__init__()
          self.connections = []  # Track connections

      def __rshift__(self, other):
          """Override >> to track default connections."""
          self.connections.append(("default", other))
          return super().__rshift__(other)

      def __sub__(self, action):
          """Override - to track action-based connections."""
          class MockTransition:
              def __init__(self, source, action):
                  self.source = source
                  self.action = action

              def __rshift__(self, target):
                  self.source.connections.append((self.action, target))
                  return self.source.next(target, self.action)

          return MockTransition(self, action)

  # Usage in tests:
  node_a >> node_b
  assert ("default", node_b) in node_a.connections

  node_a - "error" >> node_c
  assert ("error", node_c) in node_a.connections
  ```
- **When to use**: Testing any PocketFlow-based component that wires nodes together:
  - Flow compilers
  - Node orchestration logic
  - Dynamic flow builders
  - Visual flow editors
- **Benefits**:
  - No need for real node implementations in tests
  - Can verify complex wiring patterns
  - Fast test execution (no real logic)
  - Clear assertions about connections
  - Catches wiring bugs early

---

## Pattern: Avoid Reserved Logging Field Names
- **Date**: 2025-06-29
- **Discovered in**: Task 4.2
- **Problem**: Python's logging module has reserved field names in LogRecord that cannot be overridden in the extra dict
- **Solution**: Use alternative field names that don't conflict with LogRecord attributes
- **Example**:
  ```python
  # List of reserved fields to avoid:
  # name, msg, args, created, filename, funcName, levelname, levelno,
  # lineno, module, msecs, pathname, process, processName, thread, threadName

  # DON'T DO THIS - raises KeyError
  logger.debug("Found module", extra={"module": module_path})

  # DO THIS - use non-conflicting names
  logger.debug("Found module", extra={"module_path": module_path})
  logger.debug("Processing file", extra={"file_path": filename})  # not "filename"
  logger.debug("In function", extra={"function_name": func})     # not "funcName"
  ```
- **When to use**: Always when adding structured logging with extra fields
- **Benefits**:
  - Prevents runtime KeyError exceptions
  - Allows rich context in log messages
  - Maintains compatibility with log aggregation systems
  - Enables structured log queries

---

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


## Pattern: Multiple Input Format Compatibility
- **Date**: 2025-06-29
- **Discovered in**: Task 4.4
- **Problem**: Need to support multiple field naming conventions in input data (e.g., API evolution, backwards compatibility)
- **Solution**: Use Python's or operator to check multiple field names in order of preference
- **Example**:
  ```python
  # Support both old and new field names
  def parse_edge(edge_data):
      source_id = edge_data.get("source") or edge_data.get("from")
      target_id = edge_data.get("target") or edge_data.get("to")

      # Validate we got valid values
      if not source_id or not target_id:
          raise ValueError("Edge missing required fields")

      return source_id, target_id
  ```
- **When to use**:
  - API versioning without breaking changes
  - Migrating field names gradually
  - Supporting multiple input sources with different conventions
  - Reading configuration from various formats
- **Benefits**:
  - Clean, readable code without nested if statements
  - Short-circuit evaluation for performance
  - Easy to extend with more alternatives
  - No breaking changes for existing users
- **Caution**: Document which format is preferred/canonical to avoid confusion

---

## Pattern: Pure Utility Module Design
- **Date**: 2024-12-19
- **Discovered in**: Task 8.1
- **Problem**: Need reusable utility functions that can be imported and used anywhere without side effects
- **Solution**: Create modules with only pure functions, no top-level code execution, minimal dependencies
- **Example**:
  ```python
  # shell_integration.py - pure utility module
  import sys
  import json

  # Pure function - no side effects
  def detect_stdin() -> bool:
      """Check if stdin is piped."""
      return not sys.stdin.isatty()

  # Pure function - predictable output
  def determine_stdin_mode(content: str) -> str:
      """Categorize stdin content."""
      try:
          parsed = json.loads(content)
          if isinstance(parsed, dict) and "ir_version" in parsed:
              return "workflow"
      except (json.JSONDecodeError, TypeError):
          pass
      return "data"

  # Only this function has side effects (mutates dict)
  def populate_shared_store(shared: dict, content: str) -> None:
      """Add stdin to shared store."""
      shared["stdin"] = content
  ```
- **When to use**: Creating utilities for shell integration, data transformation, validation logic
- **Benefits**:
  - Easy to test (no mocking globals)
  - Safe to import anywhere
  - Predictable behavior
  - Can be used in any context (CLI, nodes, tests)

---

## Pattern: Enhanced API Alongside Legacy
- **Date**: 2024-12-19
- **Discovered in**: Task 8.4
- **Problem**: Need to enhance an existing API with new functionality (binary support, richer return types) without breaking existing code
- **Solution**: Create a new function with "_enhanced" suffix that provides new functionality while keeping original function unchanged
- **Example**:
  ```python
  # Original function - keep unchanged for compatibility
  def read_stdin() -> str | None:
      """Original API - returns text only."""
      # ... original simple implementation

  # Enhanced function - new functionality
  def read_stdin_enhanced() -> StdinData | None:
      """Enhanced API - handles binary and large files."""
      # ... new implementation with richer return type

  # Caller can choose based on needs
  text_data = read_stdin()  # Old code continues to work
  rich_data = read_stdin_enhanced()  # New code gets more features
  ```
- **When to use**: Any time you need to change an API's return type or add breaking changes
- **Benefits**:
  - Zero risk to existing code
  - Clear migration path for users
  - Can deprecate old version later
  - Both APIs can coexist indefinitely

---

## Pattern: Shared Store Inputs as Automatic Parameter Fallbacks
- **Date**: 2025-01-10
- **Discovered in**: Task 16 context builder design
- **Problem**: Nodes need to accept data from either the shared store (for inter-node communication) or parameters (for direct user configuration), leading to redundant specification in node interfaces
- **Solution**: Establish a universal pattern where ALL shared store inputs automatically work as parameter fallbacks, eliminating the need to document them twice
- **Example**:
  ```python
  class WriteFileNode(Node):
      """
      Interface:
      - Reads: shared["file_path"], shared["content"], shared["encoding"]
      - Writes: shared["written"], shared["error"]
      - Params: append  # ONLY exclusive params listed!
      """

      def prep(self, shared: dict) -> tuple[str, str, str, bool]:
          # Default pattern: Use "or" for most inputs
          file_path = shared.get("file_path") or self.params.get("file_path")
          if not file_path:
              raise ValueError("Missing required 'file_path' in shared store or params")

          # Truthiness-safe: Only when empty strings are valid values
          if "content" in shared:
              content = shared["content"]
          elif "content" in self.params:
              content = self.params["content"]
          else:
              raise ValueError("Missing required 'content' in shared store or params")

          # Optional with default: Use "or" with default value
          encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

          # Exclusive param: Never check shared store
          append = self.params.get("append", False)

          return (file_path, content, encoding, append)

      def exec(self, prep_res: tuple[str, str, str, bool]) -> str:
          file_path, content, encoding, append = prep_res
          # Pure computation - let exceptions bubble up for retry

          mode = "a" if append else "w"
          with open(file_path, mode, encoding=encoding) as f:
              f.write(content)

          return f"Successfully wrote to '{file_path}'"

      def post(self, shared: dict, prep_res: Any, exec_res: str) -> str:
          shared["written"] = exec_res
          return "default"
  ```
- **Key Insight**: Every value in "Reads" is automatically a valid parameter - no need to document it twice!
- **The Pattern**:
  ```python
  # DEFAULT: Use "or" syntax for most inputs
  value = shared.get("key") or self.params.get("key")
  if not value:
      raise ValueError("Missing required 'key' in shared store or params")

  # OPTIONAL: With default value
  value = shared.get("key") or self.params.get("key", "default")

  # TRUTHINESS-SAFE: Only when empty/0/False are valid values
  if "content" in shared:
      content = shared["content"]
  elif "content" in self.params:
      content = self.params["content"]
  else:
      raise ValueError("Missing required 'content'")
  ```
- **Documentation Impact**:
  - **Before**: `Reads: shared["file"], Params: file (as fallback), verbose`
  - **After**: `Reads: shared["file"], Params: verbose` ✨
- **Context Builder Implementation**:
  ```python
  # Filter out params that are already inputs
  exclusive_params = [p for p in metadata['params'] if p not in metadata['inputs']]
  # Only show these exclusive params in documentation
  ```
- **When to use**: ALWAYS - this is a core pflow architectural decision
- **Benefits**:
  - No redundant documentation
  - Cleaner node interfaces
  - Planner only thinks about data flow
  - Users can override any input with --param at runtime
  - Consistent behavior across all nodes

---

## Pattern: Format Detection with Graceful Enhancement
- **Date**: 2025-01-16
- **Discovered in**: Task 14.1
- **Problem**: Need to support both old (simple) and new (enhanced) input formats in a parser without breaking existing users
- **Solution**: Detect format based on type indicators (like colons), then route to appropriate parser. Always return enhanced format for consistency.
- **Example**:
  ```python
  def _detect_interface_format(self, content: str, component_type: str) -> bool:
      """Detect format based on presence of type indicators."""
      if component_type in ("inputs", "outputs"):
          # Check for new format indicator (colon after key)
          if re.search(r'shared\[\"[^\"]+\"\]\s*:', content):
              return True  # Enhanced format
      # Default to simple format
      return False

  def _extract_interface_component(self, content: str, component_type: str):
      """Route to appropriate parser based on format."""
      if self._detect_interface_format(content, component_type):
          return self._extract_enhanced_format(content)
      else:
          # Parse simple format but return as enhanced
          simple_keys = self._extract_simple_format(content)
          return [{"key": k, "type": "any", "description": ""} for k in simple_keys]
  ```
- **When to use**: Adding optional enhancements to existing parsers, API evolution, gradual feature rollouts
- **Benefits**:
  - Zero breaking changes for existing users
  - Allows gradual migration to new format
  - Single consistent output format simplifies downstream code
  - Clear detection logic prevents ambiguity

---

## Pattern: Modular Processing and Formatting Separation
- **Date**: 2025-01-17
- **Discovered in**: Task 14.2
- **Problem**: Need to support multiple output formats from the same data source without duplicating processing logic
- **Solution**: Separate data extraction/processing from formatting. Process once, format many ways.
- **Example**:
  ```python
  def _process_data(raw_data: dict) -> dict:
      """Extract and enrich data (expensive operation)."""
      processed = {}
      # Complex processing logic here
      return processed

  def build_output(raw_data: dict, format: str = "detailed") -> str:
      """Build output in specified format."""
      # Process once
      processed_data = _process_data(raw_data)

      # Format based on need
      if format == "detailed":
          return _format_detailed(processed_data)
      elif format == "summary":
          return _format_summary(processed_data)
      else:
          return _format_basic(processed_data)
  ```
- **When to use**:
  - Multiple output formats from same data
  - Expensive processing that shouldn't be repeated
  - Future-proofing for additional formats
  - Clean separation of concerns
- **Benefits**:
  - Easy to add new formats without touching processing
  - Processing bugs fixed in one place
  - Can unit test processing and formatting separately
  - Makes major pivots possible (as we experienced)

---

## Pattern: Show Expected Output Before Implementation
- **Date**: 2025-01-17
- **Discovered in**: Task 14.2 (learned from major refactoring)
- **Problem**: Misunderstandings about requirements often only surface after implementation is complete, leading to wasted work
- **Solution**: Always show concrete before/after examples of expected output BEFORE starting implementation
- **Example**:
  ```markdown
  # Before implementing any UI/output changes:
  "Current output:
  **Inputs**: file_path, encoding

  Planned output:
  **Inputs**: `file_path: str` - Path to the file, `encoding: str` - File encoding

  Does this match what you're expecting?"
  ```
- **When to use**:
  - Any task that changes user-visible output
  - Infrastructure that affects downstream formatting
  - CLI output modifications
  - Documentation generation
  - Any ambiguous requirements
- **Benefits**:
  - Users understand output without reading code
  - Catches misunderstandings before implementation
  - Creates clear agreement on deliverables
  - Saves massive refactoring time
  - No technical knowledge required to review

---
