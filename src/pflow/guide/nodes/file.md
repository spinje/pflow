# File Node

**Use for**: Reading and writing files. Known interface — no probing needed.

**Caching**: file nodes don't cache by default — a `read-file` sees the current file each run (safe when a prior step or iteration rewrote it) and a `write-file` always performs its side effect. Add `cache: true` only for an expensive read of a file you know won't change during the run.

### Node Creation Patterns

```markdown
### read-config

Read configuration from disk.

- type: read-file
- file_path: ${config_path}
```

```markdown
### deliver

Write the final report to disk.

- type: write-file
- file_path: ${output_path}
- content: ${format-for-delivery.response}
```

**`delete-file` safety flag:** it won't act on `file_path` alone — it requires a `confirm_delete: true` flag that deliberately **cannot** be a node param (so a deletion can't be triggered by node config alone). Provide it as a workflow input and wire it in with `- inputs:` (that reference is also what lets the workflow validate):

```markdown
- type: delete-file
- file_path: ${target}
- inputs:
    confirm_delete: ${confirm_delete}
```

