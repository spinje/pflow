# CI Node Package Specification

This document specifies the **CI node package** - a collection of simple, single-purpose nodes for continuous integration operations. Each node has one specific CI-related responsibility with clear interfaces and natural shared store patterns.

These nodes follow the [simple node design philosophy](../simple-nodes.md) and use the [shared store pattern](../shared-store.md) for inter-node communication.

## Node Package Overview

The CI node package provides essential CI/CD functionality through individual, focused nodes:

| Node | Purpose | Interface |
|------|---------|-----------|
| **`ci-run-tests`** | Execute test suites | Reads: `test_command`, `project_path` → Writes: `test_results` |
| **`ci-get-status`** | Check CI build status | Reads: `repo`, `branch` → Writes: `build_status` |
| **`ci-trigger-build`** | Trigger CI pipeline | Reads: `repo`, `workflow` → Writes: `build_id` |
| **`ci-get-logs`** | Retrieve build logs | Reads: `build_id` → Writes: `logs` |
| **`ci-analyze-coverage`** | Analyze test coverage | Reads: `coverage_file` → Writes: `coverage_report` |

## Individual Node Specifications

### ci-run-tests

**Purpose**: Execute test suites with automatic framework detection

```python
class CIRunTestsNode(Node):  # Inherits from pocketflow.Node
    """Execute test suites with framework auto-detection.

    Interface:
    - Reads: shared["test_command"] (optional), shared["project_path"] (optional)
    - Writes: shared["test_results"] - structured test results and summary
    - Params: framework, path, timeout, verbose, coverage
    """

    def prep(self, shared):
        project_path = shared.get("project_path") or self.params.get("path", ".")
        test_command = shared.get("test_command") or self._detect_test_framework(project_path)
        return {
            "command": test_command,
            "path": project_path,
            "timeout": self.params.get("timeout", 300),
            "verbose": self.params.get("verbose", False),
            "coverage": self.params.get("coverage", True)
        }

    def exec(self, prep_res):
        # Execute tests and return structured results
        return execute_tests(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["test_results"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Basic test execution
pflow ci-run-tests

# With specific framework
pflow ci-run-tests --framework=pytest --coverage=true

# From shared store
echo "/path/to/tests" | pflow ci-run-tests --verbose=true
```

**Parameters**:
- `framework` (optional): Specific framework (pytest, npm, jest, cargo, etc.)
- `path` (optional): Test directory/file path (default: current directory)
- `timeout` (optional): Test execution timeout in seconds (default: 300)
- `verbose` (optional): Verbose output (default: false)
- `coverage` (optional): Enable coverage reporting (default: true)

### ci-get-status

**Purpose**: Check CI build/test status for repositories

```python
class CIGetStatusNode(Node):
    """Get CI build status for repository branches.

    Interface:
    - Reads: shared["repo"], shared["branch"] (optional)
    - Writes: shared["build_status"] - current build status information
    - Params: platform, repo, branch, timeout
    """

    def prep(self, shared):
        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")
        return {
            "repo": repo,
            "branch": shared.get("branch") or self.params.get("branch", "main"),
            "platform": self.params.get("platform", "github-actions")
        }

    def exec(self, prep_res):
        return get_ci_status(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["build_status"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Check status for main branch
pflow ci-get-status --repo=owner/project

# Check specific branch
pflow ci-get-status --repo=owner/project --branch=feature-branch

# From shared store
pflow github-get-repo >> ci-get-status
```

**Parameters**:
- `platform` (optional): CI platform (github-actions, travis, circleci, etc.)
- `repo` (optional): Repository name (format: owner/repo) - can come from shared store
- `branch` (optional): Branch name (default: main)
- `timeout` (optional): API timeout in seconds (default: 30)

### ci-trigger-build

**Purpose**: Trigger CI pipeline execution

```python
class CITriggerBuildNode(Node):
    """Trigger CI pipeline execution for repositories.

    Interface:
    - Reads: shared["repo"], shared["workflow"] (optional)
    - Writes: shared["build_id"] - triggered build identifier
    - Params: platform, repo, workflow, branch, inputs
    """

    def prep(self, shared):
        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")
        return {
            "repo": repo,
            "workflow": shared.get("workflow") or self.params.get("workflow", "main"),
            "branch": self.params.get("branch", "main"),
            "platform": self.params.get("platform", "github-actions"),
            "inputs": self.params.get("inputs", {})
        }

    def exec(self, prep_res):
        return trigger_ci_build(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["build_id"] = exec_res["build_id"]
        return "default"
```

**CLI Examples**:
```bash
# Trigger default workflow
pflow ci-trigger-build --repo=owner/project

# Trigger specific workflow
pflow ci-trigger-build --repo=owner/project --workflow=deploy

# With custom inputs
pflow ci-trigger-build --repo=owner/project --inputs='{"environment":"staging"}'
```

### ci-get-logs

**Purpose**: Retrieve build/test logs from CI systems

```python
class CIGetLogsNode(Node):
    """Retrieve build logs from CI platforms.

    Interface:
    - Reads: shared["build_id"]
    - Writes: shared["logs"] - build execution logs
    - Params: platform, build_id, lines, format
    """

    def prep(self, shared):
        build_id = shared.get("build_id") or self.params.get("build_id")
        if not build_id:
            raise ValueError("build_id must be in shared store or params")
        return {
            "build_id": build_id,
            "platform": self.params.get("platform", "github-actions"),
            "lines": self.params.get("lines", 100),
            "format": self.params.get("format", "text")
        }

    def exec(self, prep_res):
        return get_ci_logs(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["logs"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Get recent logs
pflow ci-get-logs --build-id=12345

# Get more lines in JSON format
pflow ci-get-logs --build-id=12345 --lines=500 --format=json

# Chain from trigger
pflow ci-trigger-build --repo=owner/project >> ci-get-logs
```

### ci-analyze-coverage

**Purpose**: Analyze test coverage reports and metrics

```python
class CIAnalyzeCoverageNode(Node):
    """Analyze test coverage reports and generate metrics.

    Interface:
    - Reads: shared["coverage_file"] OR shared["test_results"]
    - Writes: shared["coverage_report"] - analyzed coverage metrics
    - Params: threshold, format, fail_under
    """

    def prep(self, shared):
        coverage_file = shared.get("coverage_file")
        test_results = shared.get("test_results")

        if not coverage_file and not test_results:
            raise ValueError("Either coverage_file or test_results must be in shared store")

        return {
            "coverage_file": coverage_file,
            "test_results": test_results,
            "threshold": self.params.get("threshold", 80),
            "format": self.params.get("format", "summary"),
            "fail_under": self.params.get("fail_under", False)
        }

    def exec(self, prep_res):
        return analyze_coverage(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["coverage_report"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Analyze coverage file
pflow ci-analyze-coverage --threshold=85

# Chain from test execution
pflow ci-run-tests --coverage=true >> ci-analyze-coverage --threshold=90

# Fail build if under threshold
pflow ci-analyze-coverage --fail-under=true --threshold=85
```

## Node Package Composition Patterns

### Basic Test Pipeline
```bash
# Simple test execution with coverage analysis
pflow ci-run-tests --coverage=true >> ci-analyze-coverage --threshold=85
```

### CI Status Check
```bash
# Check status and get logs if failed
pflow github-get-repo >> ci-get-status >> ci-get-logs
```

### Complete CI Workflow
```bash
# Trigger build, monitor, and analyze
pflow ci-trigger-build --repo=owner/project >>
  ci-get-logs >>
  ci-run-tests --coverage=true >>
  ci-analyze-coverage --threshold=90
```

### Integration with Other Nodes
```bash
# GitHub issue → test → report results
pflow github-get-issue --issue=123 >>
  ci-run-tests --verbose=true >>
  llm --prompt="Summarize test results" >>
  github-add-comment --issue=123
```

## Design Principles

### Single Responsibility
Each CI node has one clear purpose:
- `ci-run-tests`: Only test execution
- `ci-get-status`: Only status checking
- `ci-trigger-build`: Only build triggering
- `ci-get-logs`: Only log retrieval
- `ci-analyze-coverage`: Only coverage analysis

### Natural Interfaces

All nodes use intuitive shared store keys following the [shared store pattern](../shared-store.md#natural-interfaces):
- `shared["test_results"]` for test output
- `shared["build_status"]` for CI status
- `shared["logs"]` for build logs
- `shared["coverage_report"]` for coverage data

### Platform Flexibility
Nodes support multiple CI platforms through parameters:
- GitHub Actions (default)
- Travis CI
- CircleCI
- Jenkins
- Local execution

### Framework Auto-Detection
`ci-run-tests` automatically detects test frameworks:
- Python: pytest, unittest, nose
- JavaScript: jest, mocha, jasmine
- Rust: cargo test
- Go: go test
- Java: maven, gradle

## Future Extensions

### Additional Nodes (v2.0)
- `ci-deploy`: Application deployment
- `ci-validate-config`: CI config validation
- `ci-cache-management`: Build cache operations
- `ci-notify`: CI notification dispatch

### Enhanced Integration
- MCP CI server integration
- Advanced parallel test execution
- Cross-platform test matrix support
- Performance benchmark tracking

This CI node package provides comprehensive CI/CD functionality through simple, composable nodes that integrate naturally with other pflow node packages.

## See Also

- **Design Philosophy**: [Simple Nodes Pattern](../simple-nodes.md) - Understanding single-purpose node design
- **Interface Format**: [Node Metadata Schema](../schemas.md#node-metadata-schema) - How node interfaces are defined
- **Communication**: [Shared Store Pattern](../shared-store.md) - Inter-node data flow
- **Node Registry**: [Registry System](../registry.md) - How nodes are discovered and managed
- **Related Nodes**:
  - [GitHub Nodes](./github-nodes.md) - Repository and issue management
  - [Claude Nodes](./claude-nodes.md) - Development automation nodes
  - [LLM Node](./llm-nodes.md) - General text processing
