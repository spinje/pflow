# Claude Code Basic

Generate a Fibonacci function with Claude Code, save it to a file,
and report execution cost and duration.

## Steps

### generate

Generate a Python Fibonacci function using Claude Code.

- type: claude-code
- task: Write a Python function that calculates the nth Fibonacci number using dynamic programming. Include proper error handling, type hints, and a docstring explaining the algorithm.
- max_turns: 1

### save

Save the generated code to a file.

- type: write-file
- path: fibonacci.py
- content: ${generate.result}

### report

Report generation results and cost.

- type: echo
- message: "Code generated and saved to fibonacci.py\n\nExecution cost: $${generate._claude_metadata.total_cost_usd}\nDuration: ${generate._claude_metadata.duration_ms}ms\nTokens used: ${generate._claude_metadata.usage.input_tokens} input, ${generate._claude_metadata.usage.output_tokens} output"
