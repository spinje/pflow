# Three-way coalesce with mixed states

Tests three-way coalesce: ${a.x ?? b.x ?? c.x} where a fails, b is absent
(branch not taken), and c succeeds. Expected: c's value.

## Steps

### a

Fails.

- type: shell
- on-error: c
- next: end
- cache: false

```shell command
exit 1
```

### b

Never runs (a goes to c, b is on a separate branch never touched).

- type: shell
- next: end
- cache: false

```shell command
echo "b ran (unexpected)"
```

### c

Succeeds with value.

- type: shell
- next: end
- cache: false

```shell command
echo "c-output"
```

## Outputs

### result

Should resolve to "c-output".

- source: ${a.stdout ?? b.stdout ?? c.stdout}
