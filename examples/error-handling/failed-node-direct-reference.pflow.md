# Direct reference to a failed node — no coalesce

Reference a failed node's output directly without `??`. The error should
surface the actual failure (exit_code, command, stderr) and offer a paste-able
coalesce fix using a real peer node name.

## Steps

### primary

Fails with exit 42.

- type: shell
- on-error: fallback
- next: end
- cache: false

```shell command
echo "stuff to stderr" >&2; exit 42
```

### fallback

Runs when primary fails.

- type: shell
- next: end
- cache: false

```shell command
echo "fallback ran"
```

## Outputs

### content

Direct reference to failed node should error with helpful message.

- source: ${primary.stdout}
