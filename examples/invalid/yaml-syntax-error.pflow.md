# YAML Syntax Error

A workflow with invalid YAML in the parameter list.

## Steps

### fetch

Fetches data from an API.

- type: http
- url: https://api.example.com/data
- headers:
    invalid: [unclosed bracket
