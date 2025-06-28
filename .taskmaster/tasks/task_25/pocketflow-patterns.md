# PocketFlow Patterns for Task 25: Implement claude-code Super Node

## Overview

The claude-code node is a comprehensive AI development assistant that represents the "super node" pattern - a single powerful node that can handle complex, multi-step development tasks through instruction-based prompts.

## Relevant Cookbook Examples

- `cookbook/pocketflow-agent`: Complex decision-making and multi-step execution
- `cookbook/Tutorial-Cursor`: AI coding assistant with file operations
- `cookbook/pocketflow-thinking`: Chain-of-thought reasoning patterns

## Patterns to Adopt

### Pattern: Super Node with Instruction Interface
**Source**: Agent patterns combined with tool integration
**Compatibility**: ✅ Direct
**Description**: Single node that interprets complex instructions and executes multiple operations

**Implementation for pflow**:
```python
from pocketflow import Node
import os
import subprocess
from typing import Dict, List, Any

class ClaudeCodeNode(Node):
    def __init__(self):
        # Complex operations benefit from retry
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        # Required: instructions (natural language)
        prompt = shared.get("prompt") or shared.get("instructions")
        if not prompt:
            raise ValueError("Missing required input: prompt or instructions")

        # Optional: project context
        project_context = shared.get("project_context", {})

        # Build comprehensive context
        return {
            "prompt": prompt,
            "project_context": project_context,
            "working_directory": self.params.get("working_directory", os.getcwd()),
            "model": self.params.get("model", "claude-3-opus-20240229"),
            "temperature": self.params.get("temperature", 0.2),  # Low for coding
            "max_tokens": self.params.get("max_tokens", 4000),
            "tools_enabled": self.params.get("tools_enabled", [
                "read_file", "write_file", "list_files",
                "search_files", "run_command", "run_tests"
            ]),
            "safety_mode": self.params.get("safety_mode", True)
        }

    def exec(self, prep_res):
        # This would integrate with Claude API in production
        # For now, showing the pattern structure

        # 1. Analyze the instruction
        analysis = self._analyze_instruction(prep_res["prompt"])

        # 2. Plan the approach
        plan = self._create_execution_plan(analysis, prep_res["project_context"])

        # 3. Execute the plan step by step
        results = []
        for step in plan["steps"]:
            if step["type"] == "search":
                result = self._search_codebase(step["query"])
            elif step["type"] == "read":
                result = self._read_files(step["files"])
            elif step["type"] == "analyze":
                result = self._analyze_code(step["context"])
            elif step["type"] == "implement":
                result = self._implement_changes(step["changes"])
            elif step["type"] == "test":
                result = self._run_tests(step["test_command"])
            else:
                result = {"error": f"Unknown step type: {step['type']}"}

            results.append(result)

            # Check if we should continue based on result
            if result.get("error") and prep_res["safety_mode"]:
                break

        # 4. Generate comprehensive report
        report = self._generate_report(plan, results)

        return report

    def _analyze_instruction(self, prompt):
        """Understand what the user is asking for."""
        # This would use Claude to analyze the instruction
        # For now, return a structured analysis
        return {
            "intent": "fix_issue",
            "requires_search": True,
            "requires_implementation": True,
            "requires_testing": True
        }

    def _create_execution_plan(self, analysis, context):
        """Create a step-by-step plan."""
        # This would use Claude to create a detailed plan
        return {
            "steps": [
                {"type": "search", "query": "relevant files for issue"},
                {"type": "read", "files": ["identified_files.py"]},
                {"type": "analyze", "context": "understanding the issue"},
                {"type": "implement", "changes": "fix implementation"},
                {"type": "test", "test_command": "pytest tests/"}
            ]
        }

    def _search_codebase(self, query):
        """Search for relevant files and code."""
        try:
            # Use ripgrep for fast searching
            result = subprocess.run(
                ["rg", "-l", query],
                capture_output=True,
                text=True
            )
            files = result.stdout.strip().split("\n") if result.stdout else []
            return {"files": files, "count": len(files)}
        except Exception as e:
            return {"error": str(e)}

    def _read_files(self, file_paths):
        """Read multiple files with context."""
        contents = {}
        for path in file_paths:
            try:
                with open(path, 'r') as f:
                    contents[path] = f.read()
            except Exception as e:
                contents[path] = f"Error reading file: {e}"
        return {"files": contents}

    def _implement_changes(self, changes):
        """Apply code changes."""
        # This would use Claude to generate and apply changes
        return {
            "files_modified": ["example.py"],
            "changes_applied": True
        }

    def _run_tests(self, test_command):
        """Run tests and capture results."""
        try:
            result = subprocess.run(
                test_command.split(),
                capture_output=True,
                text=True
            )
            return {
                "passed": result.returncode == 0,
                "output": result.stdout,
                "errors": result.stderr
            }
        except Exception as e:
            return {"error": str(e)}

    def _generate_report(self, plan, results):
        """Generate comprehensive execution report."""
        return {
            "summary": "Successfully completed the requested task",
            "plan": plan,
            "execution_results": results,
            "files_modified": self._extract_modified_files(results),
            "tests_passed": self._check_test_results(results)
        }

    def post(self, shared, prep_res, exec_res):
        # Rich output interface
        shared["code_report"] = exec_res["summary"]
        shared["execution_plan"] = exec_res["plan"]
        shared["files_modified"] = exec_res["files_modified"]
        shared["tests_passed"] = exec_res["tests_passed"]
        shared["full_report"] = exec_res

        return "default"
```

### Pattern: Tool Integration
**Source**: `cookbook/Tutorial-Cursor/` AI assistant patterns
**Compatibility**: ✅ Direct
**Description**: Integrate multiple development tools

**Tool functions pattern**:
```python
class ClaudeCodeNode(Node):
    # ... other methods ...

    def _setup_tools(self):
        """Define available tools for Claude."""
        return {
            "read_file": {
                "description": "Read contents of a file",
                "parameters": {
                    "path": "string"
                }
            },
            "write_file": {
                "description": "Write content to a file",
                "parameters": {
                    "path": "string",
                    "content": "string"
                }
            },
            "search_files": {
                "description": "Search for files containing pattern",
                "parameters": {
                    "pattern": "string",
                    "file_type": "string (optional)"
                }
            },
            "run_command": {
                "description": "Execute a shell command",
                "parameters": {
                    "command": "string",
                    "timeout": "integer (optional)"
                }
            },
            "run_tests": {
                "description": "Run test suite",
                "parameters": {
                    "target": "string (optional)",
                    "verbose": "boolean (optional)"
                }
            }
        }
```

### Pattern: Comprehensive Context Building
**Source**: Agent patterns with project awareness
**Compatibility**: ✅ Direct
**Description**: Build rich context for AI decision-making

**Context aggregation**:
```python
def _build_comprehensive_context(self, prep_res):
    """Build full context for Claude."""
    context = {
        "instruction": prep_res["prompt"],
        "project_structure": self._analyze_project_structure(),
        "recent_changes": self._get_recent_git_changes(),
        "test_status": self._check_current_test_status(),
        "dependencies": self._analyze_dependencies(),
        "relevant_docs": self._find_relevant_documentation()
    }

    # Add any provided context
    if prep_res.get("project_context"):
        context.update(prep_res["project_context"])

    return context

def _analyze_project_structure(self):
    """Understand project layout."""
    # Identify key directories
    structure = {
        "has_tests": os.path.exists("tests/"),
        "has_docs": os.path.exists("docs/"),
        "project_type": self._detect_project_type(),
        "main_language": self._detect_primary_language()
    }
    return structure
```

### Pattern: Safety and Validation
**Source**: Best practices for AI code generation
**Compatibility**: ✅ Direct
**Description**: Ensure safe execution of AI-generated code

**Safety measures**:
```python
def _validate_changes(self, changes):
    """Validate AI-proposed changes before applying."""
    validations = []

    for change in changes:
        # Check file paths are within project
        if not self._is_safe_path(change["path"]):
            validations.append({
                "valid": False,
                "reason": f"Path outside project: {change['path']}"
            })
            continue

        # Check for dangerous operations
        if self._contains_dangerous_code(change["content"]):
            validations.append({
                "valid": False,
                "reason": "Contains potentially dangerous operations"
            })
            continue

        validations.append({"valid": True})

    return all(v["valid"] for v in validations), validations

def _is_safe_path(self, path):
    """Ensure path is within project directory."""
    abs_path = os.path.abspath(path)
    project_dir = os.path.abspath(self.working_directory)
    return abs_path.startswith(project_dir)
```

## Patterns to Avoid

### Pattern: Unstructured Output
**Issue**: Returning only text makes integration difficult
**Alternative**: Structured report with specific fields

### Pattern: Unlimited Scope
**Issue**: Trying to do everything in one node
**Alternative**: Focus on development tasks, delegate to other nodes

### Pattern: No Safety Checks
**Issue**: Executing arbitrary AI-generated code
**Alternative**: Always validate and sandbox operations

## Implementation Guidelines

1. **Rich context**: Gather comprehensive project information
2. **Structured execution**: Plan, execute, report pattern
3. **Safety first**: Validate all operations before execution
4. **Clear reporting**: Structured output for downstream nodes
5. **Tool integration**: Leverage existing development tools

## Usage Examples

### Example 1: Fix GitHub Issue
```bash
# CLI usage
pflow github-get-issue --issue=1234 >> \
  claude-code --prompt="Fix this issue by:
    1. Understanding the problem
    2. Finding relevant code
    3. Implementing a fix
    4. Writing tests
    5. Ensuring all tests pass"
```

### Example 2: Implement New Feature
```python
shared = {
    "prompt": """Implement a new 'export to CSV' feature:
    - Add a new endpoint /api/export/csv
    - Support filtering by date range
    - Include proper error handling
    - Write comprehensive tests
    - Update documentation
    """,
    "project_context": {
        "framework": "FastAPI",
        "database": "PostgreSQL"
    }
}

node = ClaudeCodeNode()
node.run(shared)

# Result includes:
# shared["files_modified"] = ["api/endpoints/export.py", "tests/test_export.py"]
# shared["tests_passed"] = True
# shared["code_report"] = "Implemented CSV export feature with 5 new tests"
```

### Example 3: Refactoring Task
```python
shared = {
    "prompt": "Refactor the authentication module to use dependency injection",
    "project_context": {
        "current_auth_file": "auth/manager.py",
        "target_pattern": "DI with FastAPI"
    }
}

node = ClaudeCodeNode()
node.set_params({
    "safety_mode": True,
    "run_tests_after": True
})
node.run(shared)
```

## Testing Approach

```python
def test_claude_code_analysis():
    node = ClaudeCodeNode()

    # Mock the Claude API and tool executions
    with patch.object(node, '_analyze_instruction') as mock_analyze:
        mock_analyze.return_value = {
            "intent": "fix_bug",
            "requires_search": True
        }

        shared = {"prompt": "Fix the login bug"}
        # ... continue test

def test_safety_validation():
    node = ClaudeCodeNode()

    # Test dangerous path
    dangerous_changes = [{
        "path": "../../etc/passwd",
        "content": "malicious"
    }]

    valid, validations = node._validate_changes(dangerous_changes)
    assert not valid
    assert "outside project" in validations[0]["reason"]

def test_comprehensive_report():
    node = ClaudeCodeNode()

    # Test report generation
    plan = {"steps": [{"type": "search"}]}
    results = [{"files": ["test.py"]}]

    report = node._generate_report(plan, results)
    assert "summary" in report
    assert "plan" in report
    assert "execution_results" in report
```

This claude-code super node embodies the power of AI-assisted development while maintaining safety and structure for integration with pflow workflows.
