# Claude Code Node Package Specification

This document specifies the **Claude Code node package** - a collection of simple, single-purpose nodes that integrate with Anthropic's Claude Code CLI in headless mode. These nodes provide AI-assisted development capabilities with full project context and file system integration.

## Node Package Overview

The Claude Code node package provides AI-powered development functionality through individual, focused nodes that leverage Claude Code CLI:

| Node | Purpose | Primary Input | Output |
|------|---------|---------------|--------|
| **`claude-analyze`** | Analyze code/issues with AI | `prompt` | `analysis` |
| **`claude-implement`** | Generate code implementation | `prompt` | `implementation` |
| **`claude-review`** | AI-powered code review | `prompt` | `review` |
| **`claude-explain`** | Generate code explanations | `prompt` | `explanation` |
| **`claude-refactor`** | AI-assisted code refactoring | `prompt` | `refactored_code` |

## Key Differentiation

**Claude Code CLI vs General LLM Node:**
- **`llm` node**: General text processing with prompts (API-based)
- **`claude-*` nodes**: Development-specific with project context, file access, and tool integration (CLI-based)

The Claude Code CLI provides:
- Full project understanding and context
- Direct file system access and modification
- Integration with development tools
- Structured, development-specific outputs
- Multi-turn conversation capabilities within project scope

## Individual Node Specifications

### claude-analyze

**Purpose**: Analyze code, issues, or development problems with AI assistance

```python
class ClaudeAnalyzeNode(Node):
    """Analyze code/issues using Claude Code CLI.

    Interface:
    - Reads: shared["prompt"] - analysis instruction and content
    - Writes: shared["analysis"] - structured analysis and insights
    - Params: model, temperature, focus_areas
    """

    def prep(self, shared):
        prompt = shared["prompt"]
        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-3-5-sonnet"),
            "temperature": self.params.get("temperature", 0.3),
            "focus_areas": self.params.get("focus_areas", [])
        }

    def exec(self, prep_res):
        # Execute Claude Code CLI in headless mode
        cmd = [
            "claude", "--headless",
            "--prompt", prep_res["prompt"],
            "--model", prep_res["model"]
        ]

        if prep_res["focus_areas"]:
            cmd.extend(["--focus", ",".join(prep_res["focus_areas"])])

        result = subprocess.run(cmd, capture_output=True, text=True)

        return {
            "analysis": result.stdout,
            "insights": self._parse_analysis(result.stdout),
            "confidence": self._extract_confidence(result.stdout)
        }

    def post(self, shared, prep_res, exec_res):
        shared["analysis"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Analyze code issue
echo "Analyze this GitHub issue for security vulnerabilities: $(cat issue.json)" | pflow claude-analyze --focus-areas=security

# Chain from GitHub issue
pflow github-get-issue --issue-number=123 >>
  llm --prompt="Create analysis prompt: analyze this issue for root cause" >>
  claude-analyze

# Custom analysis
echo "Analyze this code for performance bottlenecks: $(cat slow_function.py)" | pflow claude-analyze --focus-areas=performance
```

**Parameters**:
- `model` (optional): Claude model (default: claude-3-5-sonnet)
- `temperature` (optional): Creativity level 0.0-1.0 (default: 0.3)
- `focus_areas` (optional): Analysis focus areas (performance, security, maintainability, etc.)

### claude-implement

**Purpose**: Generate code implementation using Claude Code CLI with project context

```python
class ClaudeImplementNode(Node):
    """Generate code implementation using Claude Code CLI.

    Interface:
    - Reads: shared["prompt"] - implementation requirements and context
    - Writes: shared["implementation"] - generated code with explanations
    - Params: model, language, style, temperature
    """

    def prep(self, shared):
        prompt = shared["prompt"]
        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-3-5-sonnet"),
            "language": self.params.get("language", "auto"),
            "style": self.params.get("style", ""),
            "temperature": self.params.get("temperature", 0.2)
        }

    def exec(self, prep_res):
        # Use Claude Code CLI for implementation
        cmd = [
            "claude", "--headless",
            "--prompt", prep_res["prompt"],
            "--model", prep_res["model"]
        ]

        if prep_res["language"] != "auto":
            cmd.extend(["--language", prep_res["language"]])

        result = subprocess.run(cmd, capture_output=True, text=True)

        return {
            "code": self._extract_code(result.stdout),
            "explanation": self._extract_explanation(result.stdout),
            "files_modified": self._get_modified_files(result),
            "implementation": result.stdout
        }

    def post(self, shared, prep_res, exec_res):
        shared["implementation"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Implement from requirements
echo "Create a secure authentication function with JWT tokens" | pflow claude-implement --language=python

# Chain from issue analysis
pflow claude-analyze >>
  llm --prompt="Create implementation prompt: implement a fix for this analysis" >>
  claude-implement

# Custom implementation
echo "Implement a Redis cache wrapper with error handling" | pflow claude-implement --style=clean --language=python
```

### claude-review

**Purpose**: Perform AI-powered code review with Claude Code CLI

```python
class ClaudeReviewNode(Node):
    """Perform code review using Claude Code CLI.

    Interface:
    - Reads: shared["prompt"] - review instruction and code content
    - Writes: shared["review"] - structured review feedback
    - Params: model, focus, severity, format
    """

    def prep(self, shared):
        prompt = shared["prompt"]
        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-3-5-sonnet"),
            "focus": self.params.get("focus", "general"),
            "severity": self.params.get("severity", "normal"),
            "format": self.params.get("format", "structured")
        }

    def exec(self, prep_res):
        # Claude Code CLI review command
        cmd = [
            "claude", "--headless",
            "--prompt", prep_res["prompt"],
            "--model", prep_res["model"]
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        return {
            "issues": self._parse_issues(result.stdout),
            "suggestions": self._parse_suggestions(result.stdout),
            "overall_score": self._extract_score(result.stdout),
            "review": result.stdout
        }

    def post(self, shared, prep_res, exec_res):
        shared["review"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Review with security focus
echo "Review this code for security issues: $(cat auth.py)" | pflow claude-review --focus=security

# Chain from file read
pflow github-get-files --path=user_auth.py >>
  llm --prompt="Create review prompt: review this code for security and performance" >>
  claude-review --severity=strict

# Review pull request
pflow github-get-pr --pr-number=456 >>
  llm --prompt="Create review prompt for this PR diff" >>
  claude-review
```

### claude-explain

**Purpose**: Generate AI-powered code explanations and documentation

```python
class ClaudeExplainNode(Node):
    """Generate code explanations using Claude Code CLI.

    Interface:
    - Reads: shared["prompt"] - explanation request and code content
    - Writes: shared["explanation"] - clear explanations and documentation
    - Params: model, audience, format, detail_level
    """

    def prep(self, shared):
        prompt = shared["prompt"]
        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-3-5-sonnet"),
            "audience": self.params.get("audience", "developer"),
            "format": self.params.get("format", "markdown"),
            "detail_level": self.params.get("detail_level", "medium")
        }

    def exec(self, prep_res):
        # Add audience and format context to prompt
        enhanced_prompt = f"Explain for {prep_res['audience']} audience in {prep_res['format']} format: {prep_res['prompt']}"

        cmd = [
            "claude", "--headless",
            "--prompt", enhanced_prompt,
            "--model", prep_res["model"]
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        return {
            "explanation": result.stdout,
            "summary": self._extract_summary(result.stdout),
            "complexity": self._assess_complexity(result.stdout)
        }

    def post(self, shared, prep_res, exec_res):
        shared["explanation"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Explain for beginners
echo "Explain this complex algorithm: $(cat algorithm.py)" | pflow claude-explain --audience=beginner --format=markdown

# Chain from file read
pflow github-get-files --path=complex_function.py >>
  llm --prompt="Create explanation prompt: explain this function in detail" >>
  claude-explain --detail-level=high

# Generate documentation
echo "Generate API documentation for this module: $(cat api.py)" | pflow claude-explain --format=docstring
```

### claude-refactor

**Purpose**: AI-assisted code refactoring with Claude Code CLI

```python
class ClaudeRefactorNode(Node):
    """Refactor code using Claude Code CLI.

    Interface:
    - Reads: shared["prompt"] - refactoring instruction and code content
    - Writes: shared["refactored_code"] - improved code with explanations
    - Params: model, goals, preserve_behavior, style
    """

    def prep(self, shared):
        prompt = shared["prompt"]
        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-3-5-sonnet"),
            "goals": self.params.get("goals", ["readability", "maintainability"]),
            "preserve_behavior": self.params.get("preserve_behavior", True),
            "style": self.params.get("style", "")
        }

    def exec(self, prep_res):
        goals_str = ", ".join(prep_res["goals"])
        enhanced_prompt = f"Refactor focusing on {goals_str}"

        if prep_res["preserve_behavior"]:
            enhanced_prompt += " while preserving exact behavior"

        enhanced_prompt += f": {prep_res['prompt']}"

        cmd = [
            "claude", "--headless",
            "--prompt", enhanced_prompt,
            "--model", prep_res["model"]
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        return {
            "refactored_code": self._extract_code(result.stdout),
            "improvements": self._extract_improvements(result.stdout),
            "diff": self._generate_diff(prep_res["prompt"], result.stdout),
            "explanation": result.stdout
        }

    def post(self, shared, prep_res, exec_res):
        shared["refactored_code"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Refactor for readability
echo "Refactor this legacy code for readability: $(cat legacy.py)" | pflow claude-refactor --goals=readability,performance

# Chain from file read
pflow github-get-files --path=messy_code.py >>
  llm --prompt="Create refactor prompt: refactor this code for maintainability" >>
  claude-refactor --preserve-behavior=true

# Style-guided refactor
echo "Refactor to follow PEP8: $(cat unformatted.py)" | pflow claude-refactor --style=pep8
```

## Node Package Composition Patterns

### Issue Analysis and Fix Workflow
```bash
# Complete issue resolution workflow
pflow github-get-issue --issue-number=123 >>
  llm --prompt="Create analysis prompt for this GitHub issue" >>
  claude-analyze --focus-areas=root-cause >>
  llm --prompt="Create implementation prompt based on this analysis" >>
  claude-implement --language=python >>
  llm --prompt="Create review prompt for this implementation" >>
  claude-review --focus=correctness
```

### Code Quality Improvement
```bash
# Comprehensive code improvement
pflow github-get-files --path=legacy_module.py >>
  llm --prompt="Create analysis prompt for technical debt in this code" >>
  claude-analyze --focus-areas=technical-debt >>
  llm --prompt="Create refactor prompt based on this analysis" >>
  claude-refactor --goals=readability,performance >>
  llm --prompt="Create review prompt for the refactored code" >>
  claude-review --severity=strict
```

### Documentation Generation
```bash
# Generate comprehensive documentation
pflow github-get-files --path=main.py >>
  llm --prompt="Create explanation prompt: generate comprehensive documentation for this module" >>
  claude-explain --audience=new-developers --format=markdown >>
  file-write --path=MODULE_DOCS.md
```

### Pull Request Support
```bash
# AI-assisted PR workflow
pflow github-get-pr --pr-number=456 >>
  llm --prompt="Create review prompt for this PR diff focusing on security" >>
  claude-review --focus=security,performance >>
  llm --prompt="Create summary comment from this review" >>
  github-add-comment
```

## Design Principles

### Single Responsibility
Each Claude node has one clear purpose:
- `claude-analyze`: Only analysis and understanding
- `claude-implement`: Only code generation
- `claude-review`: Only code review and feedback
- `claude-explain`: Only explanation and documentation
- `claude-refactor`: Only code improvement

### Prompt-Driven Interface
All nodes use `shared["prompt"]` as their primary input:
- Clear, focused prompts with context
- No "OR" logic or multiple input types
- Consistent with pocketflow patterns
- Easy to chain with `llm` node for prompt generation

### Natural Shared Store Keys
All nodes write to intuitive shared store keys:
- `shared["analysis"]` for analysis results
- `shared["implementation"]` for generated code
- `shared["review"]` for review feedback
- `shared["explanation"]` for explanations
- `shared["refactored_code"]` for improved code

### Claude Code CLI Integration
Each node leverages the unique capabilities of Claude Code CLI:
- **Project Context**: Full understanding of project structure
- **File System Access**: Can read, analyze, and modify files
- **Tool Integration**: Access to development tools and environment
- **Structured Output**: Development-specific formatted results

## Technical Requirements

### Claude Code CLI Setup
```bash
# Install Claude Code CLI
pip install claude-code-cli

# Authenticate
claude auth login

# Verify installation
claude --version
```

### Environment Variables
- `ANTHROPIC_API_KEY`: API key for Claude access
- `CLAUDE_MODEL`: Default model (optional)
- `CLAUDE_PROJECT_PATH`: Project context path (optional)

### Error Handling
Each node handles Claude Code CLI specific errors:
- Authentication failures
- Model availability
- Context window limits
- File system permissions
- CLI version compatibility

## Future Extensions

### Additional Nodes (v2.0)
- `claude-debug`: AI-assisted debugging
- `claude-test`: AI-generated test cases
- `claude-optimize`: Performance optimization
- `claude-migrate`: Code migration assistance

### Enhanced Integration
- IDE plugin integration
- Git hook integration
- CI/CD pipeline integration
- Team collaboration features

### Advanced Capabilities
- Multi-file refactoring
- Architecture analysis
- Security vulnerability detection
- Performance profiling integration

This Claude Code node package provides comprehensive AI-assisted development capabilities through simple, composable nodes that leverage the full power of Claude Code CLI while following proper pocketflow patterns with clear prompt-driven interfaces.
