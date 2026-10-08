# prompt_cache On Non-LLM (Shell) Node

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
The article:

${article}
```

## Steps

### echo

Echo the article via shell.

- type: shell
- prompt_cache: [article]
- env:
    ARTICLE: ${article}

```shell command
echo "$ARTICLE"
```

## Outputs

### echoed

The echoed text.

- source: ${echo.response}
- type: string
