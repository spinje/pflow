# GitHub Workflow Example

## Purpose
This advanced example demonstrates a complete GitHub issue automation workflow. It shows:
- Complex multi-stage processing with LLM integration
- Extensive use of template variables
- Error handling with user notification
- Real-world API integration patterns

## Use Case
Automated issue resolution for:
- Bug fixes with clear descriptions
- Feature requests with implementation details
- Documentation updates
- Code refactoring tasks

## Visual Flow
```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│fetch_issue  │────►│analyze_issue │────►│search_codebase│
└─────┬───────┘     └──────┬───────┘     └──────┬────────┘
      │                    │                     │
   (error)              (error)                  ↓
      │                    │              ┌──────────────┐
      ▼                    ▼              │generate_patch│
┌─────────────┐                          └──────┬────────┘
│comment_error│◄─────────────────────────────(error)
└─────────────┘                                  │
                                           (success)
                                                 ↓
                                          ┌─────────────┐
                                          │create_pr    │
                                          └─────────────┘
```

## Template Variables
**Input Variables** (provided at workflow start):
- `$repo_owner`: GitHub repository owner
- `$repo_name`: Repository name
- `$issue_number`: Issue to process

**Runtime Variables** (set by nodes):
- `$issue_title`: Fetched from GitHub
- `$issue_body`: Issue description
- `$issue_labels`: Applied labels
- `$issue_summary`: LLM-generated summary
- `$suggested_fix`: LLM suggestion
- `$suggested_search_terms`: What to search for
- `$relevant_code`: Found code snippets
- `$branch_name`: Generated branch for PR
- `$change_summary`: What was changed

## Node Details

### 1. fetch_issue
Retrieves issue details from GitHub API using repository and issue information.

### 2. analyze_issue
Uses LLM to understand the issue and suggest approach. Extracts:
- Root cause analysis
- Potential fix strategy
- Likely affected files

### 3. search_codebase
Searches repository for relevant code based on LLM suggestions.

### 4. generate_patch
LLM generates actual code fix based on issue analysis and found code.

### 5. create_pr
Creates pull request with generated fix, linking back to original issue.

### 6. comment_error
Fallback node that comments on issue if any step fails, explaining what went wrong.

## Error Handling
Each critical node has error routing to `comment_error`, ensuring the issue reporter is notified if automation fails.

## How to Run
```python
# Validate the workflow
from pflow.core import validate_ir
import json

with open('github-workflow.json') as f:
    ir = json.load(f)
    validate_ir(ir)

# At runtime, provide:
params = {
    "repo_owner": "example",
    "repo_name": "myproject",
    "issue_number": "123"
}
```

## Extending This Workflow
1. **Add testing**: Run generated patches through test suite
2. **Multi-file changes**: Handle fixes spanning multiple files
3. **Review loop**: Request human review before creating PR
4. **Style checking**: Ensure generated code matches project style

## Implementation Notes
This example demonstrates how pflow can orchestrate complex, real-world automation tasks combining:
- External API calls
- LLM processing
- Code analysis
- Error recovery

The extensive use of template variables makes this workflow highly reusable across different repositories and issue types.
