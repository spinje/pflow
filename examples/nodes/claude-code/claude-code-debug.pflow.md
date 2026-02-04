# Claude Code Debug

Analyze an error with Claude Code to provide debugging assistance,
including root cause analysis, fixes, and prevention tips.

## Inputs

### error_message

The error message to analyze.

- type: string
- required: true

### code_context

Relevant code around the error.

- type: string
- required: false
- default: ""

### stack_trace

Full stack trace if available.

- type: string
- required: false
- default: ""

## Steps

### analyze_error

Analyze the error and provide structured debugging assistance.

- type: claude-code
- task: "Analyze this error and provide debugging assistance:\n\nError message:\n${input.error_message}\n\nCode context (if available):\n${input.code_context}\n\nStack trace (if available):\n${input.stack_trace}"
- max_turns: 2
- system_prompt: You are an expert debugger. Be concise but thorough. Focus on practical solutions.

```yaml output_schema
error_type:
  type: str
  description: Type of error (syntax/runtime/logic/configuration)
root_cause:
  type: str
  description: Root cause analysis
immediate_fix:
  type: str
  description: Quick fix to resolve the error
long_term_solution:
  type: str
  description: Better long-term solution
prevention_tips:
  type: list
  description: Tips to prevent similar errors
code_snippet:
  type: str
  description: Fixed code snippet if applicable
confidence:
  type: int
  description: Confidence level in the solution (1-10)
```

### format_report

Format the debug analysis into a readable report.

- type: echo
- message: "DEBUG ANALYSIS REPORT\n========================\n\n**Error Type:** ${analyze_error.result.error_type}\n**Confidence:** ${analyze_error.result.confidence}/10\n\n## Root Cause\n${analyze_error.result.root_cause}\n\n## Immediate Fix\n${analyze_error.result.immediate_fix}\n\n## Code Fix\n```\n${analyze_error.result.code_snippet}\n```\n\n## Long-term Solution\n${analyze_error.result.long_term_solution}\n\n## Prevention Tips\n${analyze_error.result.prevention_tips}\n\n---\nAnalysis cost: $${analyze_error._claude_metadata.total_cost_usd}"
