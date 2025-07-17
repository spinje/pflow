# CI Node Package Specification

> **Prerequisites**: Before implementing or using these nodes, read the [Node Implementation Reference](../reference/node-reference.md) for common patterns and best practices.

This document specifies the **CI node package** - a collection of simple, single-purpose nodes for continuous integration operations. Each node has one specific CI-related responsibility with clear interfaces and natural shared store patterns.

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

**Interface**:
- Reads: `shared["test_command"]`: str  # Test command to execute (optional)
- Reads: `shared["project_path"]`: str  # Path to project directory (optional)
- Writes: `shared["test_results"]`: dict  # Structured test results and summary
- Params: `framework`: str  # Test framework (pytest, npm, jest, cargo, etc.)
- Params: `path`: str  # Test directory/file path (default: current directory)
- Params: `timeout`: int  # Test execution timeout in seconds (default: 300)
- Params: `verbose`: bool  # Enable verbose output (default: false)
- Params: `coverage`: bool  # Enable coverage reporting (default: true)

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

**Interface**:
- Reads: `shared["repo"]`: str  # Repository name (format: owner/repo)
- Reads: `shared["branch"]`: str  # Branch name (optional)
- Writes: `shared["build_status"]`: dict  # Current build status information
- Params: `platform`: str  # CI platform (github-actions, travis, circleci, etc.)
- Params: `timeout`: int  # API timeout in seconds (default: 30)

**CLI Examples**:
```bash
# Check status for main branch
pflow ci-get-status --repo=owner/project

# Check specific branch
pflow ci-get-status --repo=owner/project --branch=feature-branch

# From shared store
pflow github-get-repo => ci-get-status
```

**Parameters**:
- `platform` (optional): CI platform (github-actions, travis, circleci, etc.)
- `repo` (optional): Repository name (format: owner/repo) - can come from shared store
- `branch` (optional): Branch name (default: main)
- `timeout` (optional): API timeout in seconds (default: 30)

### ci-trigger-build

**Purpose**: Trigger CI pipeline execution

**Interface**:
- Reads: `shared["repo"]`: str  # Repository name (format: owner/repo)
- Reads: `shared["workflow"]`: str  # Workflow name or ID (optional)
- Writes: `shared["build_id"]`: str  # Triggered build identifier
- Params: `platform`: str  # CI platform
- Params: `branch`: str  # Branch to trigger build on
- Params: `inputs`: dict  # Custom workflow inputs

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

**Interface**:
- Reads: `shared["build_id"]`: str  # Build identifier
- Writes: `shared["logs"]`: str  # Build execution logs
- Params: `platform`: str  # CI platform
- Params: `lines`: int  # Number of log lines to retrieve
- Params: `format`: str  # Log output format

**CLI Examples**:
```bash
# Get recent logs
pflow ci-get-logs --build-id=12345

# Get more lines in JSON format
pflow ci-get-logs --build-id=12345 --lines=500 --format=json

# Chain from trigger
pflow ci-trigger-build --repo=owner/project => ci-get-logs
```

### ci-analyze-coverage

**Purpose**: Analyze test coverage reports and metrics

**Interface**:
- Reads: `shared["coverage_file"]`: str  # Path to coverage file
- Reads: `shared["test_results"]`: dict  # Test results with coverage data
- Writes: `shared["coverage_report"]`: dict  # Analyzed coverage metrics
- Params: `threshold`: float  # Coverage threshold percentage
- Params: `format`: str  # Report format
- Params: `fail_under`: float  # Fail if coverage is below this percentage

**CLI Examples**:
```bash
# Analyze coverage file
pflow ci-analyze-coverage --threshold=85

# Chain from test execution
pflow ci-run-tests --coverage=true => ci-analyze-coverage --threshold=90

# Fail build if under threshold
pflow ci-analyze-coverage --fail-under=true --threshold=85
```

## Node Package Composition Patterns

### Basic Test Pipeline
```bash
# Simple test execution with coverage analysis
pflow ci-run-tests --coverage=true => ci-analyze-coverage --threshold=85
```

### CI Status Check
```bash
# Check status and get logs if failed
pflow github-get-repo => ci-get-status => ci-get-logs
```

### Complete CI Workflow
```bash
# Trigger build, monitor, and analyze
pflow ci-trigger-build --repo=owner/project =>
  ci-get-logs =>
  ci-run-tests --coverage=true =>
  ci-analyze-coverage --threshold=90
```

### Integration with Other Nodes
```bash
# GitHub issue → test → report results
pflow github-get-issue --issue=123 =>
  ci-run-tests --verbose=true =>
  llm --prompt="Summarize test results" =>
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

All nodes use intuitive shared store keys:
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

- **Design Philosophy**: [Simple Nodes Pattern](../features/simple-nodes.md) - Understanding single-purpose node design
- **Interface Format**: [Node Metadata Schema](../core-concepts/schemas.md#node-metadata-schema) - How node interfaces are defined
- **Communication**: [Shared Store Pattern](../core-concepts/shared-store.md) - Inter-node data flow
- **Node Registry**: [Registry System](../core-concepts/registry.md) - How nodes are discovered and managed
- **Related Nodes**:
  - [GitHub Nodes](./github-nodes.md) - Repository and issue management
  - [Claude Nodes](./claude-nodes.md) - Development automation nodes
  - [LLM Node](./llm-nodes.md) - General text processing
