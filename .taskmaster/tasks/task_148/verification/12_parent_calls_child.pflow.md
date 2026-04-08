# Parent workflow calling a child that has internal failure/recovery

The child fails internally but recovers. Parent should see success and
NOT inherit __failures__ from the child.

## Steps

### child

Runs the child workflow that has internal failure.

- type: workflow
- workflow: 11_child_workflow.pflow.md
- next: end
- cache: false

## Outputs

### final

Should be "child recovered" — propagated from child's child_result output.

- source: ${child.child_result}
