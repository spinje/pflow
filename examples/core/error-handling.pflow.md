# Error Handling

Demonstrates error handling with on-error routing. When a node fails,
it routes to the error handler instead of the next node in document order.

## Steps

### read-source

Read the source data file from disk. On failure, routes to error handler.

- type: read-file
- file_path: data/input.txt
- on-error: log-error

### process-file

Process the file data. On failure, routes to error handler.

- type: shell
- on-error: log-error

```shell command
echo "Processing data"
```

### save-result

Save the processed result to the output directory.

- type: write-file
- file_path: output/result.txt

### log-error

Log any error information. All error paths converge here.

- type: shell
- next: create-fallback

```shell command
echo "Error occurred, creating fallback" >&2
```

### create-fallback

Create a fallback output when processing fails.

- type: write-file
- file_path: output/fallback.txt
- content: Processing failed - using default content
- next: end
