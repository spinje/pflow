# Execution Failure After Success

A workflow where the first step succeeds but the second fails.

## Steps

### step1

First step succeeds.

- type: shell
- command: echo "step1 ok"

### step2

Second step fails.

- type: shell
- command: exit 42
