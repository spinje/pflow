# Stdin Echo

Demonstrates piped stdin routing. Accepts data via Unix pipe and echoes it back.

Usage: `echo "hello" | pflow stdin-echo.pflow.md`

## Inputs

### data

The piped input data to echo back.

- type: string
- required: true
- stdin: true

## Steps

### echo-it

Echo the received stdin data with a prefix.

- type: shell

```shell command
echo "Received: ${data}"
```

## Outputs

### result

The echoed output confirming what was received.

- source: ${echo-it.stdout}
