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

```shell command
echo "${article}"
```

## Outputs

### echoed

Echoed text.

- source: ${echo.response}
- type: string
