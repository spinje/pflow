# Child workflow (sub-workflow) — internal failure

A sub-workflow whose first node fails and falls through to a fallback.
The parent should NOT see __failures__ propagated. The child's final
output should propagate cleanly via the declared output.

## Steps

### inner_primary

Fails inside the child workflow.

- type: shell
- on-error: inner_fallback
- next: end
- cache: false

```shell command
exit 11
```

### inner_fallback

Recovers inside the child workflow.

- type: shell
- next: end
- cache: false

```shell command
echo "child recovered"
```

## Outputs

### child_result

Child workflow output.

- source: ${inner_primary.stdout ?? inner_fallback.stdout}
