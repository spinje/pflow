# Task 126: Structured Output for Claude Code Node

## Description
Add structured output support to the Claude Code node, allowing workflow authors to specify an expected output schema so Claude Code returns typed/structured data (e.g., JSON objects) rather than free-form text. This is the Claude Code equivalent of Task 66 (structured output for LLM node).

## Status
not started

## Dependencies
- Task 42: Claude Code Agentic Node (done)

## Priority
medium

## Details

### Problem
The Claude Code node currently returns free-form text output. When used as part of a larger workflow, downstream nodes often need structured data (JSON objects, lists, specific fields). Without structured output, workflow authors must parse free-form text or add explicit "return JSON" instructions to prompts — which is fragile and error-prone.

### Proposed Solution
Add an `output_schema` parameter to the Claude Code node that instructs Claude to return data matching a specified schema.

```yaml
- id: analyze_pr
  type: claude-code
  params:
    prompt: "Analyze this PR and identify issues"
    output_schema:
      type: object
      properties:
        issues:
          type: array
          items:
            type: object
            properties:
              file: { type: string }
              line: { type: integer }
              severity: { type: string, enum: [critical, warning, info] }
              description: { type: string }
        summary: { type: string }
        approval_recommendation: { type: boolean }
```

### Implementation Considerations

1. **Claude Agent SDK support**: Investigate whether the Claude Agent SDK / CLI supports structured output natively (e.g., via `--output-format json` or similar). If so, leverage that mechanism.

2. **Prompt-based fallback**: If no native SDK support, inject schema instructions into the system prompt and parse/validate the response.

3. **Validation**: Validate the returned output against the schema. If validation fails, consider retry with error feedback (similar to how LLM structured output tools work).

4. **Output key**: The structured output should be placed in the node's output key as a parsed object (dict/list), not as a JSON string, so downstream template resolution works naturally (e.g., `${analyze_pr.issues[0].severity}`).

### Relationship to Task 66
Task 66 covers structured output for the LLM node. The implementation patterns should be consistent across both nodes where possible, but the mechanisms may differ since Claude Code uses the Agent SDK while the LLM node uses Simon Willison's `llm` library.

### Example Usage (Markdown Workflow Format)

```markdown
## analyze_pr
- type: claude-code
- prompt: "Analyze the codebase for security vulnerabilities"
- output_schema:
    type: object
    properties:
      vulnerabilities:
        type: array
        items:
          type: object
          properties:
            file: { type: string }
            severity: { type: string }
            description: { type: string }
      risk_score: { type: number }

## report
- type: llm
- prompt: "Write a security report based on: ${analyze_pr.vulnerabilities}"
```

## Test Strategy

### Unit Tests
1. Schema parameter parsing and validation
2. Output validation against provided schema
3. Structured output placed as parsed object in shared store (not JSON string)
4. Missing `output_schema` → default behavior (free-form text output)

### Integration Tests
1. End-to-end: Claude Code returns structured data matching schema (mocked SDK)
2. Downstream template resolution works with structured output fields

### Edge Cases
1. Claude returns invalid JSON → appropriate error message
2. Claude returns JSON that doesn't match schema → validation error with details
3. Empty/null output handling
