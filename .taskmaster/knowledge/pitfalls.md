# Pitfalls to Avoid

A consolidated collection of failed approaches, anti-patterns, and mistakes discovered during task implementations. Learning from these failures prevents future repetition.

**Before adding**: Read this entire file and search for related pitfalls to avoid duplicates.

---

## Pitfall: Direct task-master Updates During Implementation
- **Date**: 2024-01-15
- **Discovered in**: Task 2.1 (Example)
- **What we tried**: Updating task-master continuously during implementation to track progress
- **Why it seemed good**: Wanted to maintain real-time progress visibility
- **Why it failed**: task-master is a simple task list, not a progress tracker. It doesn't support incremental updates or progress logs.
- **Symptoms**:
  - No ability to query progress history
  - Lost detailed learning logs
  - task-master commands failed or were ignored
- **Better approach**: Write all progress to `progress-log.md` files, update task-master only when marking tasks complete
- **Example of failure**:
  ```bash
  # DON'T DO THIS
  task-master update-subtask --id=1.2 --prompt="Found bug in auth module"
  task-master update-subtask --id=1.2 --prompt="Fixed bug, testing now"
  task-master update-subtask --id=1.2 --prompt="Tests passing"
  # None of these updates are actually stored or retrievable
  ```

---

## Pitfall: Shell Operator Conflicts in CLI Design
- **Date**: 2025-06-28
- **Discovered in**: Task 2.2
- **What we tried**: Using >> as a flow operator in CLI syntax without considering shell behavior
- **Why it seemed good**: The >> operator visually represents data flow and is used in documentation
- **Why it failed**: Shell intercepts >> for output redirection before the command sees it
- **Symptoms**:
  - `pflow node1 >> node2` creates a file named "node2" instead of passing >> as argument
  - Users forced to quote the operator: `pflow node1 ">>" node2`
  - Poor user experience requiring special escaping
- **Better approach**: Choose operators without shell conflicts: =>, |>, ~>, ::, ++, etc.
- **Example of failure**:
  ```bash
  # DON'T DO THIS
  pflow read-file >> process-text
  # Shell redirects stdout to file "process-text"
  # pflow only sees: ["read-file"]

  # Required workaround (poor UX)
  pflow read-file ">>" process-text
  ```

---

## Pitfall: Partial Recursive Data Structure Handling in Multi-Layer Systems
- **Date**: 2025-01-19
- **Discovered in**: Nested template resolution bug fix
- **What we tried**: Adding recursive template checking to just the validator component
- **Why it seemed good**: The validator was reporting the error, so fixing it there seemed sufficient
- **Why it failed**: Template processing happens across multiple layers - detection, validation, compilation, and runtime resolution. Missing ANY layer breaks the entire feature.
- **Symptoms**:
  - Validator says templates are "unused" even though they're in nested structures
  - Templates in headers/body/params remain unresolved at runtime
  - Nodes with nested templates don't get wrapped, so resolution never happens
- **Better approach**: When adding recursive handling, audit ALL components in the processing pipeline and update each one
- **Example of failure**:
  ```python
  # DON'T DO THIS - Only fixing one layer
  # template_validator.py
  def check_templates(value):
      if isinstance(value, dict):
          for v in value.values():
              check_templates(v)  # Added recursion here

  # compiler.py - BUT FORGOT THIS CRITICAL PIECE!
  def should_wrap(params):
      # Still only checking top-level strings!
      return any(has_templates(v) for v in params.values() if isinstance(v, str))
      # Result: Nodes with nested templates never get wrapped, resolution never happens

  # DO THIS - Update ALL layers
  # 1. Validator: Recursive detection
  # 2. Resolver: has_templates() and resolve_nested()
  # 3. Compiler: Check ALL param values for wrapping decision (most critical!)
  # 4. Node wrapper: Handle nested structures at runtime
  ```
- **Critical insight**: The compiler's wrapping decision is the control point - if nodes don't get wrapped with TemplateAwareNodeWrapper, no resolution occurs regardless of other fixes

---

## Pitfall: Catching Exceptions in PocketFlow Node exec() Method
- **Date**: 2025-07-07
- **Discovered in**: PocketFlow anti-pattern investigation
- **What we tried**: Traditional try/except blocks in exec() methods to handle errors gracefully and provide user-friendly messages
- **Why it seemed good**: Responsible error handling, prevents crashes, provides helpful error messages to users
- **Why it failed**: Completely bypasses PocketFlow's automatic retry mechanism - the framework's most powerful feature
- **Symptoms**:
  - Transient errors (file locks, network issues) fail immediately instead of retrying
  - No automatic recovery from temporary failures
  - Silent loss of retry capability - no errors, just degraded reliability
  - Manual retry logic becomes necessary, adding complexity
- **Better approach**: Let exceptions bubble up in exec(), implement exec_fallback() for final error handling after retries
- **Example of failure**:
  ```python
  # DON'T DO THIS - Breaks retry mechanism!
  class ReadFileNode(Node):
      def exec(self, prep_res):
          file_path, encoding = prep_res
          try:
              with open(file_path, encoding=encoding) as f:
                  content = f.read()
              return (content, True)  # Success tuple
          except FileNotFoundError:
              return (f"Error: File '{file_path}' not found", False)
          except PermissionError:
              # This error might be temporary! But we never retry
              return (f"Error: Permission denied", False)

  # DO THIS - Enables automatic retry
  class ReadFileNode(Node):
      def exec(self, prep_res):
          file_path, encoding = prep_res
          # No try/except - let it bubble up!
          with open(file_path, encoding=encoding) as f:
              content = f.read()
          return content  # Just the success value

      def exec_fallback(self, prep_res, exc):
          # Only called after all retries exhausted
          if isinstance(exc, FileNotFoundError):
              return "Error: File not found"
          # ... handle other final errors
  ```
- **Critical Note**: This is PocketFlow's #1 anti-pattern from their official documentation. Every node in the codebase was violating this pattern, disabling retries for all file operations.

---

## Pitfall: Making Assumptions About Code Structure in Handoff Documents
- **Date**: 2025-07-08
- **Discovered in**: Task 7 to Task 16 handoff
- **What we tried**: Writing detailed handoff memos with specific code examples and data structures based on memory/assumptions
- **Why it seemed good**: Wanted to provide comprehensive guidance to help the next agent
- **Why it failed**: Made factual errors about field names, function signatures, and data structures that would cause immediate failures
- **Symptoms**:
  - Implementing agent tries to access non-existent fields (`type`, `description`)
  - Function calls fail due to wrong parameter names (`node_name` vs `node_type`)
  - Time wasted debugging discrepancies between handoff and reality
  - False confidence in incorrect information
- **Better approach**: In handoffs, verify every code example and data structure against actual implementation. When uncertain, point to files rather than showing potentially wrong examples
- **Example of failure**:
  ```python
  # DON'T DO THIS - Assumed structure
  registry_data = {
      "type": "file",  # DOESN'T EXIST
      "description": "..."  # WRONG - it's "docstring"
  }

  # DON'T DO THIS - Wrong parameter name
  import_node_class(node_name, registry)  # WRONG - it's node_type
  ```
- **Key Lesson**: Handoff documents have high impact - errors multiply downstream. Always verify against code, especially for integration points between tasks.

---

## Pitfall: Implementing Without Understanding Related Tasks
- **Date**: 2025-01-17
- **Discovered in**: Task 14.2
- **What we tried**: Implemented "minimal changes" as specified - added navigation hints to show data structure paths
- **Why it seemed good**: Task specification explicitly said "minimal changes", seemed clear and focused
- **Why it failed**: User revealed Task 15 would split output into two formats, requiring ALL descriptions to be shown, not just navigation paths
- **Symptoms**:
  - Complete implementation thrown away halfway through
  - Major refactoring from navigation hints to hierarchical display
  - Time wasted on wrong approach
  - Had to update all tests twice
- **Better approach**: Show expected output format BEFORE implementing. Users can easily spot misunderstandings without reading code.
- **Example of failure**:
  ```markdown
  # DON'T DO THIS - Jump straight to implementation
  # Implemented: "Navigate: .number, .user.login"
  # When user actually wanted full hierarchical descriptions

  # DO THIS - Show expected output first:
  "I plan to change the output from:
  **Outputs**: `issue_data: dict`

  To:
  **Outputs**: `issue_data: dict` - Navigate: .number, .user.login

  Is this what you're looking for?"

  # User can immediately correct: "No, show ALL fields with descriptions"
  ```
- **Key Lesson**: Tasks don't exist in isolation. Infrastructure tasks especially impact multiple downstream consumers. A few clarifying questions early saves major rework later.

---

## Pitfall: Assuming String Processing is Trivial Without Considering Edge Cases
- **Date**: 2025-07-17
- **Discovered in**: Task 14.3
- **What we tried**: Simple string splitting and regex patterns for parsing structured text formats
- **Why it seemed good**: Standard library functions like `split()` are simple and well-understood
- **Why it failed**: Real-world text contains the delimiter characters in unexpected places (commas in descriptions, parentheses in defaults, colons in examples)
- **Symptoms**:
  - Descriptions truncated at first comma: "File encoding (optional, default: utf-8)" → "File encoding (optional"
  - Extra "phantom" parameters created from split fragments
  - Parser silently producing incorrect results
  - Complex workarounds needed everywhere
- **Better approach**: Design formats and parsers together. Use proper tokenization, escape sequences, or unambiguous delimiters. Consider existing robust formats (JSON, YAML) before creating new ones.
- **Example of failure**:
  ```python
  # DON'T DO THIS - Naive splitting
  segments = content.split(",")  # Breaks on ALL commas
  # Input: 'shared["key"]: type # Description with comma, more text'
  # Result: ['shared["key"]: type # Description with comma', ' more text']

  # DO THIS - Context-aware splitting
  segments = re.split(r',\s*(?=shared\[)', content)  # Only split between items
  # Or better: Use a proper parser/tokenizer
  ```
- **Key Lesson**: String processing that "looks simple" often hides complexity. Any parser dealing with human-written text needs to handle natural language punctuation. Test with realistic data early.

---

## Pitfall: Registry Must Point to Importable Modules in Integration Tests
- **Date**: 2025-07-27
- **Discovered in**: Task 20 (WorkflowNode implementation)
- **What we tried**: Creating mock registries with fake module paths like `"test.module"` that don't exist
- **Why it seemed good**: Seemed sufficient for testing - we just needed the registry structure, not actual nodes
- **Why it failed**: WorkflowNode's `compile_ir_to_flow()` actually imports modules dynamically. Non-existent modules cause import errors.
- **Symptoms**:
  - Integration tests fail with `ModuleNotFoundError: No module named 'test'`
  - Tests that should test execution errors instead fail during compilation
  - Mocking at wrong level (node class) doesn't prevent dynamic imports
  - All unit tests pass but integration tests fail mysteriously
- **Better approach**: Either define test nodes in the test file itself and reference that module, or use real nodes from the project
- **Example of failure**:
  ```python
  # DON'T DO THIS - Registry with non-existent modules
  registry_data = {
      "echo": {
          "module": "test.module",  # Doesn't exist!
          "class_name": "TestNode"
      }
  }

  # DO THIS - Reference actual test file
  class TestNode(BaseNode):
      # Define in test file
      pass

  registry_data = {
      "echo": {
          "module": "tests.test_nodes.test_workflow.test_integration",
          "class_name": "TestNode",
          "file_path": __file__  # Current test file
      }
  }

  # OR DO THIS - Use real project nodes
  registry_data = {
      "read-file": {
          "module": "pflow.nodes.file.read_file",
          "class_name": "ReadFileNode"
      }
  }
  ```
- **Key Lesson**: Integration tests that use `compile_ir_to_flow()` need a registry pointing to real, importable modules. The compiler performs actual dynamic imports, not just lookups.

---

## Pitfall: Global State in context_builder Module Causes Test Pollution
- **Date**: 2025-07-31
- **Discovered in**: Test Suite Quality Fix
- **What we tried**: Running planning tests individually (they passed) vs. in full test suite (14 failures)
- **Why it seemed good**: Tests were well-isolated with proper mocking and fixtures
- **Why it failed**: `_workflow_manager` global variable in `src/pflow/planning/context_builder.py` persists between tests
- **Symptoms**:
  - Tests pass in isolation but fail in full suite
  - AssertionError: nodes appear as 'node-000' instead of expected names
  - Mock data from one test pollutes others
  - Random test failures depending on execution order
- **Better approach**: Always patch `_workflow_manager` to None when testing context builder functions
- **Example of fix**:
  ```python
  # Required for ANY test using build_discovery_context or build_planning_context
  with patch("pflow.planning.context_builder._workflow_manager", None):
      context = build_discovery_context(registry_metadata=metadata)
  ```
- **Critical Note**: This global state design is a production code issue, not just a test problem. Consider refactoring to dependency injection.

---

<!-- New pitfalls are appended below this line -->

## Pitfall: Interactive Prompts in Pipelines Cause Hangs
- **Date**: 2025-08-31
- **Discovered in**: CLI post-execution prompt (planner path)
- **What we tried**: Showing a "Save this workflow? (y/n)" prompt when `sys.stdin.isatty()` was true
- **Why it seemed good**: Avoided prompting when stdin was piped
- **Why it failed**: In a typical shell pipeline only stdout is piped; stdin can still be a TTY. Gating on stdin alone prompts into a non-interactive pipeline, blocking downstream consumers (e.g., `jq`) that wait for EOF.
- **Symptoms**:
  - `pflow ... | jq ...` hangs after workflow finishes
  - No progress, no error, terminal appears stuck
- **Better approach**: Prompt only when both stdin and stdout are TTYs: `if sys.stdin.isatty() and sys.stdout.isatty(): ...`. Never prompt in non-interactive contexts. Also ensure SIGPIPE is set to default and all output goes through a BrokenPipe-safe function.
- **Key Lesson**: Treat “interactive” as (stdin && stdout are TTY). Tests rarely catch this because CliRunner is not a real TTY; verify with real pipelines.

---

## Pitfall: Declared Outputs Require Explicit Source When Namespacing Is On
- **Date**: 2025-08-31
- **Discovered in**: Workflow output handling
- **What we tried**: Declaring outputs without `source` while automatic namespacing is enabled
- **Why it seemed good**: Older flows wrote directly to root keys; expected the same
- **Why it failed**: With namespacing, node writes live under `shared["node_id"]["key"]`. Root-level outputs aren’t populated unless (a) compiler’s run wrapper maps them via `populate_declared_outputs()` using `outputs[*].source`, or (b) a node explicitly writes root keys.
- **Symptoms**:
  - `--output-format json` returns empty/missing keys despite nodes producing values
  - In text mode, fallback keys sometimes show, creating inconsistent behavior
- **Better approach**: Always include `"source": "${node_id.key}"` (or path) for each declared output. Rely on compiler’s post-run mapping; the CLI fallback is best-effort only.
- **Key Lesson**: Namespacing is the default; declared outputs must bridge namespaced values to root explicitly.

---

## Pitfall: JSON Output Contract Is Wrapped and Includes Metrics
- **Date**: 2025-08-31
- **Discovered in**: CLI JSON output consumption
- **What we tried**: Parsing top-level keys directly from stdout JSON
- **Why it seemed good**: Early assumptions before metrics integration
- **Why it failed**: In JSON mode, the CLI wraps results as `{ "result": <outputs>, "is_error": false, ...metrics }`. jq scripts expecting bare outputs break.
- **Symptoms**:
  - `jq -r '.some_key'` returns null
  - Users think outputs are missing
- **Better approach**: Parse `.result` first (`jq -r '.result.some_key'`). Treat the top-level as an envelope that may include metrics like `duration_ms`, `total_cost_usd`, `num_nodes`, and a `metrics` breakdown.
- **Key Lesson**: The JSON envelope is a stable contract; downstream tools should always read from `.result`.

---

## Pitfall: Testing TTY/PIPE Behavior with CliRunner Gives False Confidence
- **Date**: 2025-08-31
- **Discovered in**: CLI integration tests
- **What we tried**: Using Click’s `CliRunner` for pipeline/TTY behavior
- **Why it seemed good**: Fast, in-process testing
- **Why it failed**: `CliRunner` is not a real TTY and doesn’t simulate shell pipelines/EOF semantics. TTY gating logic and SIGPIPE behavior diverge from reality.
- **Symptoms**:
  - Tests pass while real pipelines hang
  - Prompt gating appears correct in tests, wrong in practice
- **Better approach**: For critical TTY/pipe paths, use subprocess + pty (or mock `isatty` explicitly for both stdin and stdout). Add at least one end-to-end test that runs through a real shell pipeline.
- **Key Lesson**: Separate fast unit tests from e2e TTY/pipe tests; mock both ends or use pty.

---

## Pitfall: SIGPIPE Handler Choice Affects Both CLI Output AND Subprocess Operations
- **Date**: 2025-08-31 (updated 2025-12-30)
- **Discovered in**: CLI output layer, then subprocess stdin handling
- **What we tried**: Using `SIG_DFL` to handle SIGPIPE for CLI output pipes
- **Why it seemed good**: `SIG_DFL` makes the process exit cleanly when stdout is closed
- **Why it failed**: `SIG_DFL` also affects `subprocess.run()` stdin writes. When a subprocess doesn't consume all its stdin (e.g., `echo 'ignored'` with 20KB+ piped in), SIGPIPE kills the **parent** Python process with exit 141 - silently, no error, no cleanup.
- **Symptoms**:
  - Exit code 141 with no output whatsoever
  - No trace file, no error message, complete silence
  - Only occurs with large stdin data (>16KB on macOS, >64KB on Linux)
  - Works fine when subprocess consumes all stdin
- **Root cause**: Pipe buffer overflow. Small data fits in buffer and is discarded on pipe close. Large data requires continued writes, which trigger SIGPIPE when the subprocess exits early.
- **Better approach**: Use `SIG_IGN` (ignore SIGPIPE). This allows:
  - `subprocess.run()` to handle broken pipes gracefully internally
  - Python to raise `BrokenPipeError` on direct writes, which you can catch
  - Wrap CLI output in `safe_output()` that catches `BrokenPipeError`
- **Example of failure**:
  ```python
  # DON'T DO THIS
  signal.signal(signal.SIGPIPE, signal.SIG_DFL)

  # Later, in a shell node:
  subprocess.run("echo 'ignored'", input=large_data, ...)  # 20KB+ data
  # Subprocess runs 'echo', which doesn't read stdin
  # Python tries to write to closed pipe → SIGPIPE → Process killed (exit 141)

  # DO THIS
  signal.signal(signal.SIGPIPE, signal.SIG_IGN)
  # Now subprocess.run() handles the broken pipe internally
  # Process completes normally
  ```
- **Key Lesson**: SIGPIPE affects ALL pipe operations in the process, not just stdout. Always use `SIG_IGN` when your application spawns subprocesses. The only exception is if you're certain no subprocess will ever ignore its stdin.

---

## Pitfall: Wrappers That Change Output Structure Must Update Validation Systems
- **Date**: 2025-12-29
- **Discovered in**: Batch validation bug fix (GitHub #15)
- **What we tried**: Added batch processing (Task 96) which wraps nodes and changes their output structure, without updating template validation
- **Why it seemed good**: Batch wrapper worked correctly at runtime - tests passed, workflows executed properly
- **Why it failed**: Template validation happens at compile-time using static analysis. It has no knowledge of runtime wrappers that transform output structures.
- **Symptoms**:
  - Valid batch workflows fail validation with confusing errors
  - `${item}` reported as "undefined input" even though it works at runtime
  - `${node.results}` fails with suggestion to use `${node.response}` (wrong!)
  - `batch.items` templates not recognized, causing "unused input" warnings
- **Better approach**: When adding wrappers that change node output structure, audit ALL validation systems:
  1. `template_validator.py` - Static template extraction and output recognition
  2. `workflow_data_flow.py` - Data flow and execution order validation
  3. Any other compile-time validation that reasons about node outputs
- **Example of failure**:
  ```python
  # batch_node.py - Runtime correctly produces:
  shared[node_id] = {
      "results": [...],  # Array of results
      "count": N,
      "success_count": N,
      # etc.
  }
  # Also injects: shared["item"] = current_item

  # BUT template_validator.py still thinks the node outputs:
  # {"response": "...", "llm_usage": {...}}  # From base llm node
  # Because it only queries registry for static interface metadata

  # FIX: Detect batch config and register batch outputs instead:
  if batch_config:
      # Register batch outputs (results, count, etc.)
      # Register item alias as available variable
  ```
- **Key Lesson**: Runtime wrappers and compile-time validation are separate systems with separate data sources. Registry metadata describes unwrapped nodes. Any wrapper that transforms outputs needs corresponding validation updates.
