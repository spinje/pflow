# Stateful Loop Tournament

Demonstrates `loop.carry`: each round's `survivors` output becomes the next
round's `contenders` input.

## Steps

### run-rounds

Run elimination rounds until one contender remains.

- type: workflow
- workflow: ./stateful-loop-judge-round.pflow.md
- inputs:
    contenders: ["ada", "beck", "cy", "dee"]
- loop:
    carry:
      contenders: ${run-rounds.survivors}
    while: ${run-rounds.more}
    max_iterations: 10

### announce

Print the winner.

- type: shell

```shell command
echo "Winner: ${run-rounds.survivors[0]}"
```
