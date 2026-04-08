# ignore_errors=true should NOT fall through coalesce

A shell node with ignore_errors=true that produces empty stdout should
return its empty value via coalesce — it succeeded with empty data, not failed.
This tests that the invariant correctly distinguishes "succeeded with empty"
from "failed".

## Steps

### produces_empty

Shell that exits with failure but ignore_errors swallows it.

- type: shell
- ignore_errors: true
- next: end
- cache: false

```shell command
exit 1
```

### never_runs

Should never actually be referenced by output resolution.

- type: shell
- next: end
- cache: false

```shell command
echo "this should NOT appear"
```

## Outputs

### result

The expected value is empty string (NOT "this should NOT appear").

- source: ${produces_empty.stdout ?? never_runs.stdout}
