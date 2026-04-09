# Typo on node name (node doesn't exist at all)

`${produucer.stdout}` — "produucer" is a typo for "producer" and no node
by that name exists in the workflow.

## Steps

### producer

Succeeds.

- type: shell
- next: end
- cache: false

```shell command
echo "hi"
```

## Outputs

### content

Typo on node name.

- source: ${produucer.stdout}
