{
            "id": 1,
            "title": "Create shell_integration.py with stdin detection and content reading",
            "description": "Implement the core shell integration module in src/pflow/core/shell_integration.py with functions to detect if stdin is piped using sys.stdin.isatty() and read piped content into shared['stdin']",
            "status": "pending",
            "dependencies": [],
            "details": "Create the shell_integration module following docs/features/shell-pipes.md#internal-implementation. Key functions: detect_stdin() to check if stdin is piped, read_stdin() to read content and place in shared['stdin']. Handle text encoding (UTF-8) and empty stdin cases. Ensure the module can be imported by other pflow components.",
            "testStrategy": ""
          },
          {
            "id": 2,
            "title": "Add streaming support for large inputs with buffered reading",
            "description": "Implement buffered reading using 8KB chunks to handle large piped inputs without loading entire content into memory at once",
            "status": "pending",
            "dependencies": [
              1
            ],
            "details": "Extend shell_integration.py with stream_stdin() function that reads in 8KB chunks as specified in docs/features/shell-pipes.md#streaming-support. Support both full read mode (for small inputs) and streaming mode (for large inputs). Add configuration option to set chunk size. Ensure chunks are properly concatenated when needed.",
            "testStrategy": ""
          },
          {
            "id": 3,
            "title": "Implement exit code handling for shell scripting compatibility",
            "description": "Add proper exit code propagation where 0 indicates success and non-zero indicates errors, enabling pflow to work correctly in shell scripts and pipelines",
            "status": "pending",
            "dependencies": [
              1
            ],
            "details": "Following docs/features/shell-pipes.md#exit-code-propagation, implement exit code handling in shell_integration.py. Create exit_with_code() function that properly exits with given code. Define standard exit codes (0=success, 1=general error, 2=usage error, etc). Ensure all error paths in stdin handling use appropriate exit codes.",
            "testStrategy": ""
          },
          {
            "id": 4,
            "title": "Add SIGINT signal handling for graceful interruption",
            "description": "Implement signal handling using Python's signal module to allow users to interrupt pflow execution with Ctrl+C gracefully",
            "status": "pending",
            "dependencies": [
              1,
              3
            ],
            "details": "As per docs/features/shell-pipes.md#signal-handling, add signal handler for SIGINT in shell_integration.py. Create setup_signal_handlers() function that registers handler. Handler should clean up resources, print interruption message to stderr, and exit with code 130 (standard for SIGINT). Ensure handler works during stdin reading.",
            "testStrategy": ""
          }
