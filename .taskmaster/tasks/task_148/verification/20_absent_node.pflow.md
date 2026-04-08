# Reference a node on the branch-not-taken path

A conditional branch with the "other branch" being referenced. The other
node never executed (branch not taken). Expect a clear "branch not taken"
message.

## Steps

### selector

Chooses path-a.

- type: shell
- next: path-a

```shell command
echo "choose"
```

### path-a

Ran.

- type: shell
- next: end
- cache: false

```shell command
echo "from path-a"
```

### path-b

Never runs.

- type: shell
- next: end
- cache: false

```shell command
echo "from path-b"
```

## Outputs

### content

Reference the path that didn't run.

- source: ${path-b.stdout}
