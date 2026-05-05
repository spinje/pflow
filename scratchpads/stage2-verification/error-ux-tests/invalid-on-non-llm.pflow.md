# Invalid-on-non-llm test

`prompt_cache:` declared on a shell node (not LLM). Should error with
`cache.invalid-on-non-llm`.

## Inputs

### context

Test context value.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
${context}
```

## Steps

### shell-step

Shell node with prompt_cache declared — should be invalid.

- type: shell
- prompt_cache: [context]
- command: echo "hello"
