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

<!-- New pitfalls are appended below this line -->
