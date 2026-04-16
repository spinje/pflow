# Stdout Result

Demonstrates explicit stdout output routing. A workflow that produces multiple outputs marks one with `stdout: true` so redirecting or piping the CLI lands that specific output on stdout.

Usage:

```
pflow stdout-result.pflow.md greeting="hi alice" > result.txt      # content → result.txt
pflow stdout-result.pflow.md greeting="hi alice" --output-format json   # all outputs as JSON
```

## Inputs

### greeting

The greeting message to emit.

- type: string
- default: hello world

## Steps

### emit

Echo the greeting.

- type: shell

```shell command
echo "${greeting}"
```

### count

Count the characters in the greeting.

- type: shell

```shell command
printf %s "${greeting}" | wc -c | tr -d ' '
```

## Outputs

### message

The greeting, streamed to stdout in text mode.

- source: ${emit.stdout}
- stdout: true

### length

Character count of the greeting. Available in JSON mode or via `-o length`.

- source: ${count.stdout}
