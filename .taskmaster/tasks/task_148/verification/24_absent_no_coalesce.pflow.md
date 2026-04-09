# Absent node, no coalesce

A branch-not-taken node referenced directly (no ??) in an output. Should
error (this does work correctly today).

## Steps

### always_runs

Succeeds.

- type: shell
- next: end

```shell command
echo "ok"
```

### never_runs

Orphan — never entered.

- type: shell
- next: end

```shell command
echo "dead"
```

## Outputs

### content

Direct reference to absent node.

- source: ${never_runs.stdout}
