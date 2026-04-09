# Coalesce on a sub-field of a failed node

Tests `${primary.deep.nested ?? fallback.stdout}` — root extraction must
correctly identify "primary" as the root for the first operand and find
it in __failures__.

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
echo "got-fallback"
```

## Outputs

### result

Should resolve to "got-fallback" (primary.deep.nested is unreachable).

- source: ${primary.deep.nested ?? fallback.stdout}
