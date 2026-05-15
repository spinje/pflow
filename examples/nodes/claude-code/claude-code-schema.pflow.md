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
- file_path: ${file_path}

### review

Review the code for quality, security issues, and best practices.

- type: claude-code
- prompt: "Review this Python code for quality, security issues, and best practices:\n\n${read_code.content}"
- max_turns: 2

```yaml output_schema
type: object
properties:
  overall_quality:
    type: string
    enum: [excellent, good, fair, poor]
    description: Overall quality assessment
  security_score:
    type: integer
    minimum: 1
    maximum: 10
    description: Security score from 1-10 (10 being most secure)
  issues:
    type: array
    items:
      type: string
    description: List of specific issues found
  improvements:
    type: array
    items:
      type: string
    description: List of recommended improvements
  has_critical_issues:
    type: boolean
    description: Whether there are critical issues that must be fixed
  refactored_code:
    type: string
    description: Improved version of the code with issues fixed
required: [overall_quality, security_score, issues, improvements, has_critical_issues, refactored_code]
```

### save_review

Save the review report as a markdown file.

- type: write-file
- file_path: ${file_path}.review.md

```text content
# Code Review Report

**File:** ${file_path}
**Date:** $(date)

## Overall Assessment
- **Quality:** ${review.result.overall_quality}
- **Security Score:** ${review.result.security_score}/10
- **Critical Issues:** ${review.result.has_critical_issues}

## Issues Found
${review.result.issues}

## Recommended Improvements
${review.result.improvements}

## Refactored Code
${review.result.refactored_code}

---
*Review cost: $${review.llm_usage.cost_usd}*
```

### save_improved

Save the improved code to a separate file.

- type: write-file
- file_path: ${file_path}.improved.py
- content: ${review.result.refactored_code}
