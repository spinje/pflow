# Agent (Claude) Basic

Generate a Fibonacci function with Claude Code, save it to a file,
and report execution cost and duration.

## Steps

### generate

Generate a Python Fibonacci function using Claude Code.

- type: agent
- backend: claude
- prompt: Write a Python function that calculates the nth Fibonacci number using dynamic programming. Include proper error handling, type hints, and a docstring explaining the algorithm.
- max_turns: 1

### save

Save the generated code to a file.

- type: write-file
- file_path: fibonacci.py
- content: ${generate.result}

### report

Report generation results and cost.

- type: shell
- env:
    COST: ${generate.llm_usage.cost_usd}
    DURATION_MS: ${generate.llm_usage.duration_ms}
    INPUT_TOKENS: ${generate.llm_usage.input_tokens}
    OUTPUT_TOKENS: ${generate.llm_usage.output_tokens}

```text command
echo "Code generated and saved to fibonacci.py\n\nExecution cost: \$$COST\nDuration: $DURATION_MS""ms\nTokens used: $INPUT_TOKENS input, $OUTPUT_TOKENS output"
```
