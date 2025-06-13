# Claude Platform Node Specification

## Overview

The `claude-code` node is a platform node that provides comprehensive AI-assisted development capabilities through action-based dispatch. It integrates with Anthropics `Claude Code` in headless mode to provide analysis, implementation, review, and explanation capabilities by leveraging the agentic capabilities of the `Claude Code` CLI.

## Node Interface

### Basic Information
- **Node ID**: `claude-code`
- **Type**: Platform node with action dispatch
- **Purity**: Impure (stochastic AI outputs, potential filesystem modifications)
- **MCP Alignment**: Compatible with Claude Code MCP server patterns

### Natural Interface Pattern

```python
class ClaudeNode(Node):
    """Claude Code AI agent via action dispatch.

    Actions:
    - analyze: Code/text analysis and understanding
    - implement: Code generation and implementation
    - review: Code review with suggestions
    - explain: Code explanation and documentation
    - refactor: Code refactoring and improvement

    Interface:
    - Reads: shared["code"], shared["prompt"], shared["context"]
    - Writes: shared["analysis"], shared["implementation"], shared["review"], shared["explanation"]
    - Params: action, model, temperature, max_tokens, etc.
    """
```

## Supported Actions

### 1. analyze
**Purpose**: Analyze code, issues, or text for understanding and insights

**Parameters**:
- `model` (optional): Claude model to use (default: "claude-3-5-sonnet")
- `temperature` (optional): Creativity level 0.0-1.0 (default: 0.3)
- `max_tokens` (optional): Maximum response length (default: 2000)

**Natural Interface**:
- Reads: `shared["code"]` or `shared["text"]` or `shared["issue"]`
- Writes: `shared["analysis"]` - Structured analysis and insights

**Example Usage**:
```bash
claude-code --action=analyze --prompt="Understand this GitHub issue and identify the root cause"
```

**Shared Store Flow**:
```python
# Input
shared["issue"] = {
    "title": "Authentication fails after deployment",
    "body": "Users can't log in after latest deployment..."
}

# Output after analysis
shared["analysis"] = {
    "root_cause": "Configuration mismatch in production environment",
    "affected_components": ["auth service", "database connection"],
    "severity": "high",
    "suggested_investigation": "Check environment variables and database connectivity"
}
```

### 2. implement
**Purpose**: Generate code implementation based on requirements

**Parameters**:
- `model` (optional): Claude model to use (default: "claude-3-5-sonnet-20240620")
- `temperature` (optional): Creativity level 0.0-1.0 (default: 0.2)
- `language` (optional): Programming language (auto-detected if not specified)
- `style` (optional): Coding style preferences

**Natural Interface**:
- Reads: `shared["requirements"]` or `shared["prompt"]`, `shared["context"]`
- Writes: `shared["implementation"]` - Generated code and explanations

**Example Usage**:
```bash
claude-code --action=implement --prompt="Create a function to fix the authentication issue" --language=python
```

**Integration with Claude Code CLI**:
For file modifications, this action can integrate with the headless Claude Code CLI:
```python
def _implement_with_claude_code(self, prep_res):
    """Use Claude Code CLI for file-based implementations"""
    cmd = [
        "claude", "--headless",
        "--prompt", prep_res["prompt"],
        "--model", self.params.get("model", "claude-3-5-sonnet")
    ]
    # Execute and capture result
```

### 3. review
**Purpose**: Perform code review with suggestions and improvements

**Parameters**:
- `model` (optional): Claude model to use (default: "claude-3-5-sonnet-20240620")
- `focus` (optional): Review focus areas (security, performance, style, etc.)
- `severity` (optional): Review severity level (strict, normal, lenient)

**Natural Interface**:
- Reads: `shared["code"]` or `shared["diff"]` or `shared["pr"]`
- Writes: `shared["review"]` - Structured review feedback

**Example Usage**:
```bash
claude-code --action=review --focus=security,performance
```

**Shared Store Flow**:
```python
# Input
shared["code"] = """
def authenticate_user(username, password):
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    return db.execute(query)
"""

# Output after review
shared["review"] = {
    "issues": [
        {
            "type": "security",
            "severity": "high",
            "message": "SQL injection vulnerability",
            "line": 2,
            "suggestion": "Use parameterized queries instead of string formatting"
        }
    ],
    "overall_score": 3,
    "recommendations": ["Use SQLAlchemy ORM", "Add input validation"]
}
```

### 4. explain
**Purpose**: Generate explanations and documentation for code

**Parameters**:
- `model` (optional): Claude model to use (default: "claude-3-5-sonnet-20240620")
- `audience` (optional): Target audience (beginner, intermediate, expert)
- `format` (optional): Output format (markdown, docstring, comment)

**Natural Interface**:
- Reads: `shared["code"]` or `shared["function"]` or `shared["file"]`
- Writes: `shared["explanation"]` - Clear explanations and documentation

**Example Usage**:
```bash
claude-code --action=explain --audience=beginner --format=markdown
```

### 5. refactor
**Purpose**: Refactor and improve existing code

**Parameters**:
- `model` (optional): Claude model to use (default: "claude-3-5-sonnet")
- `goals` (optional): Refactoring goals (readability, performance, maintainability)
- `preserve_behavior` (optional): Ensure behavior preservation (default: true)

**Natural Interface**:
- Reads: `shared["code"]` or `shared["file"]`
- Writes: `shared["refactored_code"]` - Improved code with explanations

**Example Usage**:
```bash
claude-code --action=refactor --goals=readability,performance
```

## Implementation Details

### Action Dispatch Pattern

```python
def exec(self, prep_res):
    action = self.params.get("action")

    if action == "analyze":
        return self._analyze(prep_res)
    elif action == "implement":
        return self._implement(prep_res)
    elif action == "review":
        return self._review(prep_res)
    elif action == "explain":
        return self._explain(prep_res)
    elif action == "refactor":
        return self._refactor(prep_res)
    else:
        raise ValueError(f"Unknown Claude action: {action}")
```

### LLM Integration

**Primary Integration**: Anthropic Claude API
- Environment variable: `ANTHROPIC_API_KEY`
- Model selection: claude-3-5-sonnet (default), claude-3-opus, claude-3-haiku
- Temperature and token limits configurable per action

**Secondary Integration**: Claude Code CLI
- For file-based implementations and modifications
- Headless mode for automated execution
- Environment detection and tool integration

### Context Management

The node intelligently manages context based on action:
- **analyze**: Focus on understanding and insight generation
- **implement**: Include relevant code patterns and best practices
- **review**: Apply security, performance, and style guidelines
- **explain**: Adapt to audience level and format requirements
- **refactor**: Preserve behavior while improving code quality

### Error Actions

The node returns action strings for error handling:
- `"default"`: Successful operation
- `"api_error"`: LLM API failure
- `"rate_limited"`: Rate limit exceeded
- `"context_too_large"`: Input exceeds context window
- `"invalid_code"`: Unparseable code input

### Testing Strategy

1. **Unit Tests**: Mock LLM API responses for each action
2. **Integration Tests**: Real API testing with various code examples
3. **Quality Tests**: Validate output quality and format consistency
4. **Performance Tests**: Context management and response time optimization

## Workflow Integration Examples

### Issue Analysis and Implementation
```bash
# Natural language workflow
pflow "analyze github issue 123 and implement a fix"

# Generated action-based workflow
github --action=get-issue --issue=123 >>
claude-code --action=analyze --prompt="understand this issue" >>
claude-code --action=implement --prompt="create fix based on analysis" >>
git --action=commit --message="Fix for issue 123"
```

### Code Review and Improvement
```bash
# Natural language workflow
pflow "review this pull request and suggest improvements"

# Generated action-based workflow
github --action=get-pr --pr=456 >>
claude-code --action=review --focus=security,performance >>
claude-code --action=refactor --goals=maintainability
```

## Benefits of Action-Based Design

1. **Unified AI Interface**: Single node for all Claude/AI operations
2. **Context Awareness**: Actions automatically adapt prompts and parameters
3. **Flexible Integration**: Works with both API and CLI implementations
4. **Consistent Outputs**: Structured results across different AI operations
5. **Easy Extension**: Add new AI capabilities as actions

This design enables natural workflows that leverage AI capabilities throughout the development process while maintaining the action-based architecture benefits.
