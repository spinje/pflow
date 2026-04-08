# Python Exception Path

A python node raises an exception. Verify exception path archives to __failures__.

## Steps

### crasher

Crashes by raising an exception.

- type: code
- on-error: recovery
- next: end
- cache: false

```code
result: str = ""
raise RuntimeError("intentional crash")
```

### recovery

Runs when crasher fails.

- type: shell
- next: end
- cache: false

```shell command
echo "recovered"
```

## Outputs

### result

Coalesced output.

- source: ${crasher.value ?? recovery.stdout}
