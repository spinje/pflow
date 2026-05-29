# Loop re-entry recovery

A node fails on visit 1 (creates a marker file), succeeds on visit 2 (marker
exists). Loop guard should clear stale __failures__ entry. Final state:
node in shared (succeeded), NOT in __failures__.

## Steps

### setup

Removes any pre-existing marker so the test is repeatable.

- type: shell
- next: maybe-fail

```shell command
rm -f /tmp/pflow-task148-marker
```

### maybe-fail

Fails first time, creates marker, succeeds on retry.

- type: shell
- on-error: retry
- next: end

```shell command
if [ -f /tmp/pflow-task148-marker ]; then
  echo "succeeded-on-retry"
else
  touch /tmp/pflow-task148-marker
  exit 9
fi
```

### retry

Loops back to maybe-fail after a brief moment.

- type: shell
- next: maybe-fail

```shell command
echo "retrying"
```

## Outputs

### result

Should be "succeeded-on-retry".

- source: ${maybe-fail.stdout}
