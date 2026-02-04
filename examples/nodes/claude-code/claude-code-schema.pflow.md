# Claude Code Schema

Review a Python file for code quality and security issues using Claude Code
with structured output schema. Saves both a review report and an improved
version of the code.

## Inputs

### file_path

Path to the Python file to review.

- type: string
- required: true

## Steps

### read_code

Read the Python source file for review.

- type: read-file
- path: ${input.file_path}

### review

Review the code for quality, security issues, and best practices.

- type: claude-code
- task: "Review this Python code for quality, security issues, and best practices:\n\n${read_code.content}"
- max_turns: 2

```yaml output_schema
overall_quality:
  type: str
  description: "Overall quality assessment: excellent/good/fair/poor"
security_score:
  type: int
  description: Security score from 1-10 (10 being most secure)
issues:
  type: list
  description: List of specific issues found
improvements:
  type: list
  description: List of recommended improvements
has_critical_issues:
  type: bool
  description: Whether there are critical issues that must be fixed
refactored_code:
  type: str
  description: Improved version of the code with issues fixed
```

### save_review

Save the review report as a markdown file.

- type: write-file
- path: ${input.file_path}.review.md
- content: "# Code Review Report\n\n**File:** ${input.file_path}\n**Date:** $(date)\n\n## Overall Assessment\n- **Quality:** ${review.result.overall_quality}\n- **Security Score:** ${review.result.security_score}/10\n- **Critical Issues:** ${review.result.has_critical_issues}\n\n## Issues Found\n${review.result.issues}\n\n## Recommended Improvements\n${review.result.improvements}\n\n## Refactored Code\n```python\n${review.result.refactored_code}\n```\n\n---\n*Review cost: $${review._claude_metadata.total_cost_usd}*"

### save_improved

Save the improved code to a separate file.

- type: write-file
- path: ${input.file_path}.improved.py
- content: ${review.result.refactored_code}
