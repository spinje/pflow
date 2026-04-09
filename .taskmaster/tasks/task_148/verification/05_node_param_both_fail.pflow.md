# Both-fail coalesce in NODE PARAM (not output)

A downstream node tries to use `${primary.stdout ?? fallback.stdout}` as a
parameter when both upstream nodes failed. This tests the node-param path
in template_resolution.py, not the output_resolver.py path.

## Steps

### primary

Primary fails.

- type: shell
- on-error: fallback
- next: end
- cache: false

```shell command
echo "p_err" >&2; exit 7
```

### fallback

Fallback fails too.

- type: shell
- on-error: consumer
- next: end
- cache: false

```shell command
echo "f_err" >&2; exit 5
```

### consumer

Tries to use the failed coalesce as input. Should error with structured message.

- type: shell
- next: end
- cache: false

```shell command
echo "got: ${primary.stdout ?? fallback.stdout}"
```
