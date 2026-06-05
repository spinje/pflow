# Non-Retriable File Error

Demonstrates that deterministic file validation errors skip the retry wait and route to `on-error`.

## Steps

### prepare-directory

Creates a directory where the copy node expects a file.

- type: shell

```shell command
mkdir -p /private/tmp/pflow-non-retriable-example
rm -f /private/tmp/pflow-non-retriable-example/dest.txt
mkdir -p /private/tmp/pflow-non-retriable-example/source-dir
```

### copy-directory

Attempts to copy a directory as if it were a file; this is deterministic and should not retry.

- type: copy-file
- source_path: /private/tmp/pflow-non-retriable-example/source-dir
- dest_path: /private/tmp/pflow-non-retriable-example/dest.txt
- retry:
    max: 3
    wait: 0.5
    backoff: exponential
- on-error: report-error
- next: done

### report-error

Reports the expected deterministic failure path.

- type: shell
- next: done

```shell command
echo "copy-directory failed without retrying deterministic validation"
```

### done

Marks the end of the recovery path.

- type: shell

```shell command
echo "non-retriable example complete"
```
