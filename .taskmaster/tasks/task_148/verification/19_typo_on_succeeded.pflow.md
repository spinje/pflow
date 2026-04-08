# Typo on a succeeded node

Reference a field that doesn't exist on a succeeded node. Expect:
"Did you mean: ${producer.stdout}?"

## Steps

### producer

Succeeds.

- type: shell
- next: end
- cache: false

```shell command
echo "hello"
```

## Outputs

### content

Typo: stddout instead of stdout.

- source: ${producer.stddout}
