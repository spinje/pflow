# CI Platform Node Specification

## Overview

The `ci` node is a platform node that provides comprehensive continuous integration capabilities through action-based dispatch. It supports various testing frameworks, build systems, and CI platforms while maintaining a consistent interface.

## Node Interface

### Basic Information
- **Node ID**: `ci`
- **Type**: Platform node with action dispatch
- **Purity**: Impure (executes external commands, may modify filesystem)
- **MCP Alignment**: Compatible with CI/CD MCP server patterns

### Natural Interface Pattern

```python
class CINode(Node):
    """Continuous Integration operations via action dispatch.

    Actions:
    - run-tests: Execute test suites with various frameworks
    - get-status: Check CI build/test status
    - trigger-build: Trigger CI pipeline execution
    - get-logs: Retrieve build/test logs
    - analyze-coverage: Analyze test coverage reports

    Interface:
    - Reads: shared["test_command"], shared["project_path"], shared["build_config"]
    - Writes: shared["test_results"], shared["build_status"], shared["coverage"], shared["logs"]
    - Params: action, framework, timeout, verbose, etc.
    """
```

## Supported Actions

### 1. run-tests
**Purpose**: Execute test suites with automatic framework detection

**Parameters**:
- `framework` (optional): Specific framework (pytest, npm, jest, cargo, etc.) - auto-detected if not specified
- `path` (optional): Test directory/file path (default: current directory)
- `timeout` (optional): Test execution timeout in seconds (default: 300)
- `verbose` (optional): Verbose output (default: false)
- `coverage` (optional): Enable coverage reporting (default: true)

**Natural Interface**:
- Reads: `shared["test_command"]` (optional), `shared["project_path"]`
- Writes: `shared["test_results"]` - Structured test results and summary

**Example Usage**:
```bash
ci --action=run-tests --framework=pytest --coverage=true --verbose=true
```

**Framework Auto-Detection**:
```python
def _detect_test_framework(self, project_path):
    """Auto-detect testing framework based on project files"""
    if os.path.exists(os.path.join(project_path, "pytest.ini")) or \
       os.path.exists(os.path.join(project_path, "pyproject.toml")):
        return "pytest"
    elif os.path.exists(os.path.join(project_path, "package.json")):
        return "npm"  # or jest if jest config found
    elif os.path.exists(os.path.join(project_path, "Cargo.toml")):
        return "cargo"
    # ... more framework detection
```

**Shared Store Result**:
```python
shared["test_results"] = {
    "framework": "pytest",
    "status": "passed",  # passed, failed, error
    "total_tests": 45,
    "passed": 43,
    "failed": 2,
    "skipped": 0,
    "duration": 12.5,
    "coverage": {
        "percentage": 87.5,
        "lines_covered": 350,
        "lines_total": 400
    },
    "failed_tests": [
        {
            "name": "test_authentication",
            "file": "tests/test_auth.py",
            "line": 25,
            "error": "AssertionError: Expected 200, got 401"
        }
    ]
}
```

### 2. get-status
**Purpose**: Check CI build and test status from various CI platforms

**Parameters**:
- `platform` (optional): CI platform (github-actions, jenkins, gitlab-ci, etc.)
- `repo` (optional): Repository identifier
- `branch` (optional): Branch name (default: current branch)
- `build_id` (optional): Specific build ID to check

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["branch"]` (fallback to params)
- Writes: `shared["build_status"]` - Current CI status information

**Example Usage**:
```bash
ci --action=get-status --platform=github-actions --repo=myorg/myrepo --branch=main
```

### 3. trigger-build
**Purpose**: Trigger CI pipeline execution

**Parameters**:
- `platform` (required): CI platform to trigger
- `repo` (optional): Repository identifier
- `branch` (optional): Branch to build (default: current branch)
- `workflow` (optional): Specific workflow/pipeline name

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["branch"]`, `shared["workflow"]`
- Writes: `shared["build_trigger"]` - Trigger response and build ID

**Example Usage**:
```bash
ci --action=trigger-build --platform=github-actions --workflow=test-and-deploy
```

### 4. get-logs
**Purpose**: Retrieve build and test logs

**Parameters**:
- `build_id` (optional): Specific build ID (default: latest)
- `job` (optional): Specific job name within build
- `lines` (optional): Number of log lines to retrieve (default: 100)

**Natural Interface**:
- Reads: `shared["build_id"]`, `shared["job"]` (fallback to params)
- Writes: `shared["logs"]` - Retrieved log content

**Example Usage**:
```bash
ci --action=get-logs --build-id=12345 --lines=50
```

### 5. analyze-coverage
**Purpose**: Analyze test coverage reports

**Parameters**:
- `format` (optional): Coverage report format (lcov, xml, json, etc.)
- `threshold` (optional): Coverage threshold percentage (default: 80)
- `path` (optional): Path to coverage report files

**Natural Interface**:
- Reads: `shared["coverage_files"]`, `shared["project_path"]`
- Writes: `shared["coverage_analysis"]` - Coverage analysis and recommendations

**Example Usage**:
```bash
ci --action=analyze-coverage --threshold=85 --format=lcov
```

## Implementation Details

### Action Dispatch Pattern

```python
def exec(self, prep_res):
    action = self.params.get("action")

    if action == "run-tests":
        return self._run_tests(prep_res)
    elif action == "get-status":
        return self._get_status(prep_res)
    elif action == "trigger-build":
        return self._trigger_build(prep_res)
    elif action == "get-logs":
        return self._get_logs(prep_res)
    elif action == "analyze-coverage":
        return self._analyze_coverage(prep_res)
    else:
        raise ValueError(f"Unknown CI action: {action}")
```

### Framework Support

**Testing Frameworks**:
- **Python**: pytest, unittest, nose2
- **JavaScript**: jest, mocha, jasmine, npm test
- **Java**: JUnit, TestNG, Maven test
- **Rust**: cargo test
- **Go**: go test
- **C#**: dotnet test

**CI Platforms**:
- **GitHub Actions**: Via GitHub API
- **GitLab CI**: Via GitLab API
- **Jenkins**: Via Jenkins API
- **Local**: Direct command execution

### Command Execution

```python
def _execute_test_command(self, command, cwd, timeout):
    """Execute test command with proper error handling and output capture"""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False  # Don't raise on non-zero exit
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "timeout": timeout}
    except Exception as e:
        return {"error": "execution_failed", "details": str(e)}
```

### Error Actions

The node returns action strings for error handling:
- `"default"`: Successful operation
- `"test_failed"`: Tests failed (different from execution error)
- `"build_failed"`: Build/compilation failed
- `"timeout"`: Operation exceeded timeout
- `"platform_error"`: CI platform API error
- `"not_found"`: Test files/configuration not found

### Integration Examples

#### Test Execution in Development Workflow
```bash
# Natural language workflow
pflow "implement fix for issue 123, run tests, and create PR if tests pass"

# Generated action-based workflow
claude --action=implement --prompt="fix issue 123" >>
ci --action=run-tests --coverage=true >>
github --action=create-pr --title="Fix for issue 123"
```

#### CI Status Monitoring
```bash
# Check CI status and notify team
pflow "check CI status for main branch and notify team if failed"

# Generated workflow
ci --action=get-status --branch=main >>
slack --action=send --channel=dev-team --condition=failed
```

## Testing Strategy

1. **Unit Tests**: Mock command execution and API responses
2. **Framework Tests**: Test framework detection and command generation
3. **Integration Tests**: Real test execution with sample projects
4. **CI Platform Tests**: Test API integration with real CI services
5. **Error Handling**: Test timeout, failure, and platform error scenarios

## Benefits of Action-Based Design

1. **Framework Agnostic**: Single interface for all testing frameworks
2. **CI Platform Unified**: Consistent interface across different CI systems
3. **Intelligent Detection**: Automatic framework and configuration detection
4. **Flexible Integration**: Works with local and remote CI environments
5. **Structured Results**: Consistent output format regardless of underlying tools

This design enables seamless integration of testing and CI operations into development workflows while abstracting away the complexity of different tools and platforms.
