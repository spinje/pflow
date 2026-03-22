# Sub Echo

Sub-workflow that converts input text to uppercase. Used as a dependency in parent-with-sub.pflow.md.

## Inputs

### text

Text to convert.

- type: string
- required: true

## Steps

### uppercase

Convert input to uppercase.

- type: shell

```command
echo "${text}" | tr '[:lower:]' '[:upper:]'
```

## Outputs

### result

Uppercased text.

- source: ${uppercase.stdout}
