# To Uppercase

Convert input text to uppercase.

## Inputs

### text
The text to convert.
- type: string

## Outputs

### result
The uppercased text.
- source: ${transform.stdout}

## Steps

### transform

Convert text to uppercase using tr.

- type: shell
- command: echo "${text}" | tr '[:lower:]' '[:upper:]'
