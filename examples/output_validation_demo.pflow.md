# Output Validation Demo

Read a file and summarize it with an LLM, demonstrating declared outputs
including a dynamic result that cannot be statically traced.

## Steps

### read

Read the input text file for processing.

- type: read-file
- path: input.txt

### process

Summarize the text content using an LLM.

- type: llm

```prompt
Summarize this text: ${content}
```

## Outputs

### content

The file content read by read-file node.

- type: string

### response

The LLM response.

- type: string

### dynamic_result

A dynamically written key that cannot be traced.

- type: object
