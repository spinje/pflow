# Child workflow that fails without recovery

Inner node fails with no on-error. Whole child workflow fails.

## Steps

### doomed

Fails terminally.

- type: shell
- next: end
- cache: false

```shell command
echo "reason" >&2; exit 13
```

## Outputs

### child_result

Unreachable.

- source: ${doomed.stdout}
