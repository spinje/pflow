# Source line with heavy offset from start

Lots of lines before the output to stress-test the line tracker.

Some prose text.

More prose text.

Even more prose text.

## Steps

### primary

Fails.

- type: shell
- on-error: fallback
- next: end

```shell command
exit 1
```

### fallback

Succeeds.

- type: shell
- next: end

```shell command
echo "ok"
```

## Outputs

### content

Description with

multiple

lines

above

- source: ${primary.stdout}
