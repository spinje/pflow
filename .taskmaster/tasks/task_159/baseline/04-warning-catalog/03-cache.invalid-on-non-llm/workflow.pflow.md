# Invalid On Non-LLM

## Inputs

### article

Article text.

- type: string
- required: true

## Cache

```cache
The article:

${article}
```

## Steps

### echo

Echo via shell.

- type: shell
- prompt_cache: [article]
- env:
    ARTICLE: ${article}

```shell command
echo "$ARTICLE"
```

## Outputs

### echoed

Echoed text.

- source: ${echo.response}
- type: string
