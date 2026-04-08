# Both coalesce operands fail

Both primary and fallback fail. Should produce a structured "all operands failed"
template error referencing both nodes.

## Steps

### primary

Primary fails with exit 7.

- type: shell
- on-error: fallback
- next: end
- cache: false

```shell command
echo "primary error" >&2; exit 7
```

### fallback

Fallback also fails with exit 5. Routes to soak so workflow reaches outputs.

- type: shell
- on-error: soak
- next: end
- cache: false

```shell command
echo "fallback error" >&2; exit 5
```

### soak

Absorbs the second failure so the workflow proceeds to outputs.

- type: shell
- next: end
- cache: false

```shell command
echo "soaked"
```

## Outputs

### content

Should produce all-operands-failed error.

- source: ${primary.stdout ?? fallback.stdout}
