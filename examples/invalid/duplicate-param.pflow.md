# Duplicate Param

A workflow where the same parameter is defined both inline and in a code block.

## Steps

### process

Run a shell command with conflicting command definitions.

- type: shell
- command: echo "inline command"

```shell command
echo "code block command"
```
