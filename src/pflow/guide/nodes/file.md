# File Node

**Use for**: Reading and writing files. Known interface — no probing needed.

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

