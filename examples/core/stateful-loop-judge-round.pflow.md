# Stateful Loop Judge Round

One tournament round for `stateful-loop-tournament.pflow.md`.

## Inputs

### contenders

Current contenders.

- type: array

## Outputs

### survivors

Contenders that advance to the next round.

- type: array
- source: ${judge.result.survivors}

### more

Whether another round is needed.

- type: boolean
- source: ${judge.result.more}

## Steps

### judge

Keep every other contender.

- type: code
- inputs:
    contenders: ${contenders}

```python code
contenders: list
survivors = contenders[::2] if len(contenders) > 1 else contenders
result: dict = {
    "survivors": survivors,
    "more": len(survivors) > 1,
}
```
