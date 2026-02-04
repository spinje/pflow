# Test Nested Index

Demonstrate batch processing with nested index access across correlated batches.
The first batch generates data, and the second batch cross-references results
using index-based access.

## Steps

### generate-data

Generate a JSON array of user objects with names and scores.

- type: shell

```shell command
echo '[{"name": "alice", "score": 85}, {"name": "bob", "score": 92}, {"name": "charlie", "score": 78}]'
```

### process-batch

Process each user and display their name, index, and score.

- type: shell

```yaml batch
items: ${generate-data.stdout}
as: user
```

```shell command
echo "Processing user ${user.name} (index ${__index__}) with score ${user.score}"
```

### correlate-batch

Correlate batch results with labels using index-based access to prior results.

- type: shell

```yaml batch
items:
  - label: First user
    extra: VIP
  - label: Second user
    extra: Regular
  - label: Third user
    extra: New
```

```shell command
echo "${item.label}: ${process-batch.results[${__index__}].stdout} (${item.extra})"
```
