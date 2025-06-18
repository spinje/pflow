# Template Variables and Resolution in pflow

## Overview

Template variables in pflow provide a powerful mechanism for creating dynamic, data-driven workflows. They enable sophisticated parameter passing between nodes while maintaining the simplicity of the shared store pattern.

## Core Concepts

### 1. Template Variable Syntax

Template variables use the `$variable` syntax in CLI commands and are resolved at runtime to values from the shared store:

```bash
# Template variable syntax
$code_report → shared["code_report"]
$commit_message → shared["commit_message"]
$issue_title → shared["issue_title"]
```

### 2. Template-Driven Workflows

The planner generates template-driven workflows that use these variables to create sophisticated, reusable patterns:

```bash
# Example template-driven workflow
github-get-issue --issue=1234 >> \
claude-code --prompt="$comprehensive_fix_instructions" >> \
llm --prompt="Write commit message for: $code_report" >> \
git-commit --message="$commit_message" >> \
git-push >> \
github-create-pr --title="Fix: $issue_title" --body="$code_report"
```

### 3. Template String Composition

The planner uses LLM capabilities to generate template strings that combine static text with dynamic variables:

```bash
# Template string with embedded variables
claude-code --prompt="<instructions>
                        1. Understand the problem described in the issue
                        2. Search the codebase for relevant files
                        3. Implement the necessary changes to fix the issue
                        4. Write and run tests to verify the fix
                        5. Return a report of what you have done as output
                      </instructions>
                      This is the issue: $issue"
```

## How Template Variables Work

### 1. Variable Detection
The parser identifies `$variable` patterns in CLI syntax during planning.

### 2. Dependency Tracking
The planner tracks which variables depend on which node outputs:
- `$issue` depends on `github-get-issue` output
- `$code_report` depends on `claude-code` output
- `$commit_message` depends on `llm` output

### 3. Runtime Resolution
During execution, template variables are resolved to actual shared store values:
```bash
# At runtime
$issue → shared["issue"] → "Button component touch events not working properly on mobile devices"
```

### 4. Content Substitution
Variable placeholders are replaced with actual content before node execution.

## Integration with Planner

The planner performs several template-related responsibilities:

### Natural Language Path
1. **Intent Analysis & Template Design**: Analyze user intent and design template-driven workflow structure
2. **Template String Composition**: Generate template strings that populate all node inputs with static text and $variable references
3. **Parameter Value Creation**: Generate appropriate parameter values based on workflow context
4. **Template Variable Mapping**: Create mappings between $variables and shared store keys
5. **Template Resolution Validation**: Ensure all template variables can be resolved through workflow execution order

### CLI Pipe Syntax Path
1. **Template Variable Analysis**: Identify and validate template variable patterns and dependencies
2. **Template String Resolution**: Resolve template strings for all node inputs, ensuring $variables map to available shared store values
3. **Template Variable Tracking**: Monitor variable usage and dependencies throughout the flow

## Template Variable Resolution Process

### 1. Variable Flow Management
The planner tracks variable dependencies to ensure proper execution order:

```bash
# Variable dependency flow
github-get-issue --issue=1234 >>        # Outputs: shared["issue"], shared["issue_title"]
claude-code --prompt="...$issue" >>     # Depends on: shared["issue"]
llm --prompt="...$code_report" >>       # Depends on: shared["code_report"]
git-commit --message="$commit_message"  # Depends on: shared["commit_message"]
```

### 2. Missing Variable Handling
If a required template variable is not available, the runtime provides clear error messages:
```
Error: Template variable $code_report not found in shared store
Available keys: issue, issue_title, repo
```

### 3. Context-Aware Resolution
The CLI intelligently routes different types of inputs:
- **Data flags**: `--issue=1234` → `shared["issue_number"] = "1234"`
- **Behavior flags**: `--temperature=0.3` → `node.set_params({"temperature": 0.3})`
- **Template variables**: `$code_report` → resolved from `shared["code_report"]` at runtime

## Advanced Template Features

### 1. Planner-Generated Instructions
The planner can generate sophisticated template values:

```bash
# The planner generates complex instructions
$comprehensive_fix_instructions = "Analyze issue #1234, understand root cause,
search codebase for relevant files, implement complete fix with error handling,
write tests, ensure code quality standards..."
```

### 2. Multi-Consumer Variables
Template variables can be used by multiple nodes:
```bash
# $code_report used by both llm and github-create-pr
llm --prompt="Write commit message for: $code_report" >> \
github-create-pr --body="$code_report"
```

### 3. Nested Template Structures
Templates can reference other template results:
```bash
# $commit_message comes from llm processing of $code_report
llm --prompt="Summarize: $code_report" >> \
git-commit --message="$commit_message"
```

## Benefits of Template-Driven Approach

### 1. Reduced Token Usage
- Orchestration logic captured once in templates
- Subsequent runs only process actual work
- Significant cost savings for repeated workflows

### 2. Deterministic Execution
- Same inputs produce same workflow structure
- Predictable behavior and timing
- Better debugging and observability

### 3. Progressive Learning
- Users see how natural language translates to concrete steps
- Template structure reveals workflow logic
- Users can modify templates to learn cause-effect

### 4. Sophisticated Node Instructions
- Complex, multi-step instructions passed to nodes like `claude-code`
- Preserves context within single node execution
- Eliminates repeated "what's next" reasoning

## Implementation in JSON IR

The planner generates JSON IR with template support:

```json
{
  "node_input_templates": {
    "claude-code": {
      "prompt": "...$issue",
      "dependencies": ["issue"]
    },
    "llm": {
      "prompt": "Write commit message for: $code_report",
      "dependencies": ["code_report"]
    }
  },
  "variable_flow": {
    "issue": "github-get-issue.outputs.issue_data",
    "code_report": "claude-code.outputs.code_report",
    "commit_message": "llm.outputs.response"
  }
}
```

## Current Implementation Status

Based on the documentation:
- ✅ Template variable syntax defined
- ✅ Shared store integration documented
- ✅ Planner template composition specified
- ✅ Runtime resolution process outlined
- ⏳ Implementation pending in MVP development

## Key Takeaways

1. **Template variables enable sophisticated workflows** while maintaining simplicity
2. **$variable syntax** provides intuitive parameter passing between nodes
3. **Planner generates template strings** that combine static and dynamic content
4. **Runtime resolves variables** from shared store during execution
5. **Template-driven approach reduces costs** and improves determinism
6. **Progressive transparency** helps users learn workflow patterns

## Related Documentation

- [Shared Store Pattern](../docs/core-concepts/shared-store.md#template-variable-resolution) - Template variable resolution details
- [Planner Specification](../docs/features/planner.md) - Template string composition and variable flow management
- [Workflow Analysis](../docs/features/workflow-analysis.md) - Real-world template-driven workflow examples
- [CLI Runtime](../docs/features/cli-runtime.md) - CLI flag and template variable routing
