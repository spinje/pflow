# Parent with on-error handling a failed child workflow

Parent routes child's failure to a recovery node via on-error.

## Steps

### child

Calls a child that fails unrecoverably.

- type: workflow
- workflow: 13_child_unrecovered.pflow.md
- on-error: recover
- next: end
- cache: false

### recover

Runs when child fails.

- type: shell
- next: end
- cache: false

```shell command
echo "parent-recovered"
```

## Outputs

### final

Should be "parent-recovered" via coalesce fallthrough of failed child.

- source: ${child.child_result ?? recover.stdout}
