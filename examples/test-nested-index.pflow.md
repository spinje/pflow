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
- env:
    NAME: ${user.name}
    INDEX: ${__index__}
    SCORE: ${user.score}

```yaml batch
items: ${generate-data.stdout}
as: user
```

```shell command
echo "Processing user $NAME (index $INDEX) with score $SCORE"
```

### correlate-batch

Correlate batch results with labels using index-based access to prior results.

- type: shell
- env:
    LABEL: ${item.label}
    PREV: ${process-batch.results[${__index__}].stdout}
    EXTRA: ${item.extra}

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
echo "$LABEL: $PREV ($EXTRA)"
```
