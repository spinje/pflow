# Retry With Backoff

Demonstrates node-level retry with exponential backoff before an `on-error` recovery route.

## Steps

### prepare-path

Ensures the destination path is clear while leaving the source file absent.

- type: shell

```shell command
mkdir -p /tmp/pflow-retry-with-backoff-example
rm -f /tmp/pflow-retry-with-backoff-example/source.txt
rm -f /tmp/pflow-retry-with-backoff-example/dest.txt
```

### copy-missing-file

Attempts to copy a missing file, exhausts retry attempts, then routes to recovery.

- type: copy-file
- source_path: /tmp/pflow-retry-with-backoff-example/source.txt
- dest_path: /tmp/pflow-retry-with-backoff-example/dest.txt
- retry:
    max: 2
    wait: 0.1
    backoff: exponential
- on-error: retry-exhausted
- next: done

### retry-exhausted

Runs after the copy retry budget is exhausted.

- type: shell
- next: done

```shell command
echo "retry budget exhausted" >&2
```

### done

Marks the end of the recovery path.

- type: shell

```shell command
echo "retry example complete"
```
