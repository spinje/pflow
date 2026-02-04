# Error Handling

Demonstrates a file processing pipeline with error handling and fallback
nodes. The original JSON workflow used action-based edge routing for
error recovery — in the current linear-only markdown format, nodes are
connected sequentially by document order.

* Future: conditional branching (Task 38) will enable error/retry routing
* Pattern: read → process → save → log errors → fallback → retry

## Steps

### read_source

Read the source data file from disk. In the branching version, failure
here routes to log_error.

- type: read-file
- file_path: data/input.txt

### process_file

Process the file data through the test processor. In the branching
version, failure routes to log_error with retry support.

- type: test

### save_result

Save the processed result to the output directory.

- type: write-file
- file_path: output/result.txt

### log_error

Append any error information to the log file. Central error logging
node that all error paths converge to.

- type: write-file
- file_path: logs/error.log
- append: true

### create_fallback

Create a fallback output file with default content when processing
fails. Ensures the workflow always produces some output.

- type: write-file
- file_path: output/fallback.txt
- content: Processing failed - using default content

### retry_processor

Retry the processing step up to three times before giving up.

- type: test-retry
- max_attempts: 3
