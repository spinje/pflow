# Source line tracking — multiple outputs

Multiple outputs at different lines. Fail the first. Error should show line
of first output (expected: line 33).

## Steps

### primary

Fails.

- type: shell
- on-error: fallback
- next: end
- cache: false

```shell command
exit 1
```

### fallback

Succeeds.

- type: shell
- next: end
- cache: false

```shell command
echo "ok"
```

## Outputs

### first_output

Uses failed node directly.

- source: ${primary.stdout}

### second_output

Succeeds.

- source: ${fallback.stdout}
