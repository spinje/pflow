# Natural Language to Workflow Patterns

## Overview

This document catalogs common patterns for converting natural language requests into workflows. Understanding these patterns helps the planner achieve ≥95% success rate.

## Core Patterns

### 1. Action + Target Pattern
**Natural Language**: "analyze customer churn"
**Workflow**: `get-customers >> filter-churned >> analyze >> report`

**Natural Language**: "fix github issue 123"
**Workflow**: `github-get-issue >> claude-code >> git-commit >> github-create-pr`

**Key**: Verb + noun usually maps to a sequence of nodes

### 2. Source + Transform + Destination Pattern
**Natural Language**: "get data from stripe and save to database"
**Workflow**: `stripe-get-data >> transform >> db-save`

**Natural Language**: "read CSV, analyze it, write summary"
**Workflow**: `read-file >> llm --prompt="analyze" >> write-file`

**Key**: From X to Y patterns indicate data flow

### 3. Temporal Patterns
**Natural Language**: "analyze last month's revenue"
**Workflow**: `get-revenue --start=$last_month_start --end=$last_month_end >> analyze`

**Natural Language**: "daily standup summary"
**Workflow**: `github-list-prs --since=yesterday >> slack-get-messages --since=yesterday >> llm --prompt="summarize for standup"`

**Key**: Time references become parameter constraints

### 4. Conditional/Filtering Patterns
**Natural Language**: "find failed builds"
**Workflow**: `ci-list-builds >> filter --status=failed`

**Natural Language**: "analyze errors in production"
**Workflow**: `get-logs --env=production >> filter --level=error >> analyze`

**Key**: Adjectives often become filters or parameters

### 5. Aggregation Patterns
**Natural Language**: "summarize all PRs"
**Workflow**: `github-list-prs >> llm --prompt="summarize"`

**Natural Language**: "total revenue by customer"
**Workflow**: `get-transactions >> group-by --field=customer >> sum --field=amount`

**Key**: "All", "total", "summarize" indicate aggregation

## Parameter Extraction Patterns

### Numeric Values
- "issue 123" → `issue_number: 123`
- "last 5 commits" → `limit: 5`
- "port 8080" → `port: 8080`

### Time Periods
- "last month" → `period: "last_month"`
- "since yesterday" → `since: "yesterday"`
- "between Jan 1 and Jan 31" → `start: "2024-01-01", end: "2024-01-31"`

### Named Entities
- "customer Acme Corp" → `customer: "Acme Corp"`
- "repo pflow" → `repo: "pflow"`
- "branch feature-x" → `branch: "feature-x"`

### States/Statuses
- "open issues" → `state: "open"`
- "failed builds" → `status: "failed"`
- "production environment" → `env: "production"`

## Complex Patterns

### Multi-Step Analysis
**Natural Language**: "check if any tests are failing, and if so, analyze why and create a fix"
**Workflow Structure**:
```
ci-get-status
  - "success" >> done
  - "failure" >> get-failed-tests >> analyze-failures >> claude-code >> create-fix-pr
```

### Parallel Operations
**Natural Language**: "analyze both GitHub issues and customer tickets"
**Workflow**: Two parallel branches merged:
```
github-list-issues >> analyze-issues ─┐
                                      ├>> combine-analysis >> report
customer-list-tickets >> analyze-tickets ─┘
```

### Iterative Patterns
**Natural Language**: "for each customer, generate a report"
**Workflow**: Batch processing:
```
get-customers >> map(customer => generate-report --customer=$customer)
```

## LLM Prompt Engineering for Pattern Recognition

### System Prompt Structure
```
You are a workflow planner. Convert natural language to node chains.

Available nodes:
{node_registry}

Rules:
1. Map verbs to action nodes
2. Extract entities as parameters
3. Use template variables for dynamic values
4. Chain nodes with >> operator
5. Preserve user intent
```

### Few-Shot Examples in Prompt
```
Example 1:
Input: "analyze customer churn from stripe"
Output: stripe-get-customers >> filter-churned >> llm --prompt="analyze churn patterns"

Example 2:
Input: "fix github issue 123"
Output: github-get-issue --issue=$issue_number >> claude-code >> git-commit >> github-create-pr
Parameters: {issue_number: 123}
```

## Common Mistakes to Avoid

### 1. Over-Literal Translation
❌ "get me the data" → `get-me-the-data` (no such node)
✅ "get me the data" → Understand context and use appropriate data source node

### 2. Missing Implicit Steps
❌ "fix the bug" → `fix-bug` (too high level)
✅ "fix the bug" → `identify-bug >> analyze-code >> generate-fix >> test >> commit`

### 3. Hardcoding Dynamic Values
❌ "analyze issue 123" → `github-get-issue --issue=123` (hardcoded)
✅ "analyze issue 123" → `github-get-issue --issue=$issue_number` with params

### 4. Ignoring Context
❌ "analyze it" → `analyze` (what is "it"?)
✅ "analyze it" → Look for previous context or ask for clarification

## Testing Natural Language Understanding

### Test Cases Should Cover:

1. **Simple Commands**
   - "read file data.csv"
   - "list github issues"
   - "run tests"

2. **Complex Workflows**
   - "analyze customer churn and create a report with recommendations"
   - "check all PRs, run tests on each, and merge the passing ones"

3. **Ambiguous Requests**
   - "check the status" (of what?)
   - "analyze the data" (which data?)
   - "fix it" (fix what?)

4. **Parameter-Heavy Requests**
   - "analyze revenue for enterprise customers in Q4 2023 excluding trials"
   - "get all closed issues from repo pflow labeled bug with high priority"

## Success Metrics

Track these to ensure ≥95% success rate:

1. **Parse Success**: Can extract intent and parameters
2. **Node Selection**: Chooses appropriate nodes
3. **Parameter Mapping**: Correctly maps values to parameters
4. **Flow Logic**: Correct node ordering and connections
5. **User Approval**: Workflow accepted without modification

## Continuous Improvement

1. **Log Failed Conversions**: Track what patterns fail
2. **User Corrections**: Learn from user modifications
3. **Expand Examples**: Add successful patterns to prompt
4. **Refine Patterns**: Update this document with new patterns

## Remember

The goal is to understand user intent, not just parse words. When in doubt, generate a workflow that captures the spirit of the request, even if it requires slight interpretation.
