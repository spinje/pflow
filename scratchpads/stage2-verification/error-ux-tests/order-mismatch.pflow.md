# Order-mismatch test

`prompt_cache:` declares chunks in a different order than the `## Cache`
block. Should error with `cache.order-mismatch`.

## Inputs

### a

First test value.

- type: string
- required: true

### b

Second test value.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
First chunk:

${a}

Second chunk:

${b}
```

## Steps

### test-call

prompt_cache lists b BEFORE a — wrong order vs ## Cache block.

- type: llm
- prompt_cache: [b, a]

```prompt
Test prompt that uses ${a} and ${b}.
```
