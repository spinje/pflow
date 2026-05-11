# Print Only Mode Signal

## Steps

### step-a

First step.

- type: shell
- cache: false
- command: printf FIRST

### step-b

Target step.

- type: shell
- cache: false
- command: printf TARGET_ONLY_VALUE

### step-c

Skipped step.

- type: shell
- cache: false
- command: printf SHOULD_NOT_RUN

## Outputs

### result

Full-run declared output that should not shadow the --only target.

- source: ${step-a.stdout}
