# Mixed absent + failed coalesce in output

One operand is absent (branch not taken), the other failed. In output
path, this is silently skipped by the current gate.

## Steps

### selector

Chooses path-a, never touches never_run.

- type: shell
- next: fails

```shell command
echo "go"
```

### never_run

Never executes.

- type: shell
- next: end

```shell command
echo "never"
```

### fails

Fails with exit 1.

- type: shell
- on-error: soak
- next: end

```shell command
exit 4
```

### soak

Absorbs failure so workflow reaches outputs.

- type: shell
- next: end

```shell command
echo "soaked"
```

## Outputs

### content

Should error: never_run is absent, fails is failed. But will silently skip.

- source: ${never_run.stdout ?? fails.stdout}
