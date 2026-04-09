# Batch with partial item failures

Run a batch of shell commands where some succeed and some fail. Verify:
(1) batch node itself shows in execution summary with batch_error_details
(2) failed items are visible
(3) the batch node appears in shared (succeeded, even though items failed)
    because the BATCH node itself succeeded.

## Steps

### process

Processes a batch of items, some will fail.

- type: shell
- command: "test ${item.should_fail} = 'no' && echo ok-${item.name} || exit ${item.exit}"
- cache: false

```yaml batch
items:
  - name: first
    should_fail: "no"
    exit: 0
  - name: second
    should_fail: "yes"
    exit: 3
  - name: third
    should_fail: "no"
    exit: 0
  - name: fourth
    should_fail: "yes"
    exit: 7
parallel: false
error_handling: continue
```
