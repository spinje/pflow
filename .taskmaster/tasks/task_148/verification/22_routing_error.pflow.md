# Unmatched action — routing error

A python node returns an action string that doesn't match any defined
successor. Engine should fall into _handle_no_successor path and archive
to __failures__ with category "routing_error".

## Steps

### router

Returns an unmatched action at runtime (branched via action). The declared
`- next:` targets list the valid routes; the code returns an action that
matches none of them, forcing the engine into `_handle_no_successor`.

- type: code
- next: path_a, path_b
- cache: false

```code
# Computed at runtime — non-literal assignment bypasses the parser's
# static AST analysis so this reaches the engine's routing path.
result: str = "router-ran"
_action: str = "not_a_real_action"
next: str = _action
```

### path_a

Never runs (router returns an unmatched action before reaching any declared branch).

- type: shell
- next: end
- cache: false

```shell command
echo "a"
```

### path_b

Never runs.

- type: shell
- next: end
- cache: false

```shell command
echo "b"
```
