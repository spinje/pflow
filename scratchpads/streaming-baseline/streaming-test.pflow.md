# Streaming Test

Exercises pflow's live progress output: a few sequential shell steps with short
sleeps, then a parallel batch node that processes several items concurrently.
Purpose: verify what streaming looks like interactively before touching #194.

## Steps

### stage_one

First sequential stage — short sleep so the progress update is visible.

- type: shell
- cache: false

```shell command
sleep 1 && echo "stage_one done"
```

### stage_two

Second sequential stage — slightly longer sleep.

- type: shell
- cache: false

```shell command
sleep 2 && echo "stage_two done"
```

### make_items

Emit a JSON list of items to feed the batch node.

- type: shell
- cache: false

```shell command
echo '[{"name": "alpha"}, {"name": "bravo"}, {"name": "charlie"}, {"name": "delta"}, {"name": "echo"}]'
```

### process_items

Parallel batch — each item sleeps 1.5s so you can watch them run concurrently.

- type: shell

```yaml batch
items: ${make_items.stdout}
as: item
parallel: true
max_concurrent: 3
```

```shell command
sleep 1.5 && echo "processed ${item.name}"
```

### final

Final sequential stage so the completion summary is clearly after the batch.

- type: shell
- cache: false

```shell command
echo "all done"
```
